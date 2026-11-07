"""LLM spend control in USD (S21-7, A-048 / N-03; Stage 20 token budget replaced): per-shop daily cap, platform daily
cap, per-shop monthly budget.

Reads `llm_usage` totals per (provider, model) through the RPC `llm_usage_by_model` (migration 0038), prices them with
`Settings.llm_price(model)` (USD / 1M tokens) and keeps a short in-process cache. Fail-open everywhere: when the RPC
fails (any error, a missing function included) the spend check is skipped (None) rather than switching every bot off;
the failure is cached for `CACHE_SECONDS` (one WARNING per window) and then tried again - there is no process-wide
off switch. The kill-switch needs no database at all.

Used by the webhook (S20-9); `llm.py` only checks the kill-switch itself.
"""
import logging
import threading
import time
from datetime import datetime, timezone

from app.config import get_settings

logger = logging.getLogger("app")

ALERT_RATIO = 0.8  # share of the daily cap at which one WARNING per UTC day is logged
CACHE_SECONDS = 60
PER_MILLION = 1_000_000
ROW_FIELDS = {  # llm_usage_by_model column -> price key
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_tokens": "cache_read",
    "cache_write_tokens": "cache_write",
}

_lock = threading.Lock()
_cache: dict[tuple[str, str, datetime], tuple[float, float | None]] = {}  # key -> (expires monotonic, USD)
_logged_day: dict[str, object] = {}  # WARNING kind ("cap" / "alert") -> UTC date it was last logged
_unknown_models: set[str] = set()  # models already warned about (priced at the maximum)


def reset() -> None:
    """Clears the cache and every flag (tests: the module state is process-global)."""
    with _lock:
        _cache.clear()
        _logged_day.clear()
        _unknown_models.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now: datetime) -> datetime:
    return _day_start(now).replace(day=1)


def _tokens(value) -> int:
    """One token counter -> int >= 0. None -> 0; a bool or a non-number raises (caller: unknown spend)."""
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError("unexpected boolean")
    return max(0, int(value))


def _price_rows(data, settings) -> float:
    """RPC `.data` (list of per-(provider, model) token sums) -> USD. Raises on a malformed result."""
    if data is None:
        return 0.0
    if not isinstance(data, list):
        raise ValueError("unexpected result shape")
    total = 0.0
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("unexpected row shape")
        model = str(row.get("model") or "")
        if model not in settings.llm_prices:
            with _lock:
                first = model not in _unknown_models
                _unknown_models.add(model)
            if first:
                logger.warning("LLM model %r has no price - priced at the maximum of the known models", model)
        price = settings.llm_price(model)
        for column, key in ROW_FIELDS.items():
            total += _tokens(row.get(column)) * price[key] / PER_MILLION
    return round(total, 6)


def cost_usd(sc, *, owner_id: str | None = None, shop_id: str | None = None, since: datetime) -> float | None:
    """Spend in USD since `since`: of one shop, of one owner's shops, or of the whole platform (both None).
    None = unknown (RPC error / bad result) -> caller fails open."""
    key =(f"owner:{owner_id}" if owner_id else "", f"shop:{shop_id}" if shop_id else "", since)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
    value: float | None
    try:
        res = sc.rpc("llm_usage_by_model", {
            "p_owner": str(owner_id) if owner_id else None,
            "p_shop": str(shop_id) if shop_id else None,
            "p_since": since.isoformat(),
        }).execute()
        value = _price_rows(getattr(res, "data", None), get_settings())
    except Exception as exc:
        value = None
        logger.warning("llm_usage_by_model failed - LLM budget check skipped (%s)", type(exc).__name__)
    with _lock:
        for k in [k for k, (expires, _) in _cache.items() if expires <= now]:
            del _cache[k]  # expired entries must not pile up (one key per shop and period)
        _cache[key] = (now + CACHE_SECONDS, value)
    return value


def _once_per_day(kind: str, today) -> bool:
    """True the first time per UTC day for this WARNING kind."""
    with _lock:
        if _logged_day.get(kind) == today:
            return False
        for k in [k for k, day in _logged_day.items() if day != today]:
            del _logged_day[k]  # yesterday's entries must not pile up
        _logged_day[kind] = today
        return True


def blocked_reason(sc, shop: dict) -> str | None:
    """Why the bot must not call the LLM for this shop: "kill_switch" | "shop_daily_cap" | "daily_cap" |
    "monthly_budget", or None (allowed, or unknown because the spend data is unavailable).
    The shop's own daily cap is checked before the platform cap: one shop must not exhaust the shared pool."""
    s = get_settings()
    if s.llm_kill_switch:
        return "kill_switch"
    now = _now()
    shop_id = shop.get("id")
    tier = shop.get("subscription_tier")
    shop_cap = s.llm_daily_usd_shop_cap(tier)
    if shop_cap > 0 and shop_id:
        shop_today = cost_usd(sc, shop_id=str(shop_id), since=_day_start(now))
        if shop_today is not None and shop_today >= round(shop_cap, 6):
            return "shop_daily_cap"
    cap = s.llm_daily_usd_cap
    if cap > 0:
        today = cost_usd(sc, since=_day_start(now))
        if today is not None:
            if today >= cap:
                if _once_per_day("cap", now.date()):
                    logger.warning("LLM daily USD cap reached - bot switched to operator")
                return "daily_cap"
            if today >= cap * ALERT_RATIO and _once_per_day("alert", now.date()):
                logger.warning("LLM spend alert: %d%% of daily USD cap", int(today * 100 / cap))
    monthly = s.llm_monthly_usd_budget(tier)
    if monthly > 0 and shop_id:
        month = cost_usd(sc, shop_id=str(shop_id), since=_month_start(now))
        if month is not None and month >= round(monthly, 6):
            return "monthly_budget"
    return None


def spend_status(sc) -> dict:
    """Platform spend for the admin overview (USD). today_usd / month_usd are None when unknown.
    `alert` = kill-switch on, or today's spend at 80% of the daily cap."""
    s = get_settings()
    now = _now()
    today = cost_usd(sc, since=_day_start(now))
    month = cost_usd(sc, since=_month_start(now))
    cap = s.llm_daily_usd_cap
    return {
        "today_usd": None if today is None else round(today, 4),
        "month_usd": None if month is None else round(month, 4),
        "daily_cap_usd": cap,
        "kill_switch": s.llm_kill_switch,
        "alert": bool(s.llm_kill_switch or (cap > 0 and today is not None and today >= cap * ALERT_RATIO)),
    }
