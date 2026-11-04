"""LLM spend control (S20-8, A-037 / N-03): per-owner monthly token budget, platform daily cap.

Reads `llm_usage` totals through the RPC `llm_tokens_used` (migration 0035) with a short in-process
cache. Fail-open everywhere: when the RPC is missing (migration not applied) or fails, the spend checks
are skipped (None) rather than switching every bot off. The kill-switch needs no database at all.

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

_lock = threading.Lock()
_cache: dict[tuple[str, datetime], tuple[float, int | None]] = {}  # key -> (expires monotonic, value)
_rpc_missing = False  # migration 0035 not applied: no more RPC attempts in this process
_logged_day: dict[str, object] = {}  # WARNING kind ("cap" / "alert") -> UTC date it was last logged


def reset() -> None:
    """Clears the cache and every flag (tests: the module state is process-global)."""
    global _rpc_missing
    with _lock:
        _cache.clear()
        _logged_day.clear()
        _rpc_missing = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now: datetime) -> datetime:
    return _day_start(now).replace(day=1)


def _parse_total(data) -> int:
    """RPC `.data` -> int >= 0. Accepts int, numeric str, [{"llm_tokens_used": n}], None (-> 0)."""
    if isinstance(data, list):
        if not data:
            return 0
        first = data[0]
        data = first.get("llm_tokens_used") if isinstance(first, dict) else first
    if data is None:
        return 0
    if isinstance(data, bool):
        raise ValueError("unexpected boolean")
    return max(0, int(data))


def tokens_used(sc, owner_id: str | None, since: datetime) -> int | None:
    """Total tokens (all four llm_usage counters) since `since`: of one owner's shops, or the whole
    platform when owner_id is None. None = unknown (migration missing / DB error) -> caller fails open."""
    global _rpc_missing
    key = (str(owner_id) if owner_id else "*", since)
    now = time.monotonic()
    with _lock:
        if _rpc_missing:
            return None
        hit = _cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
    value: int | None
    try:
        res = sc.rpc("llm_tokens_used", {
            "p_owner": str(owner_id) if owner_id else None, "p_since": since.isoformat(),
        }).execute()
        value = _parse_total(getattr(res, "data", None))
    except Exception as exc:
        value = None
        if getattr(exc, "code", None) == "PGRST202":
            with _lock:
                first = not _rpc_missing
                _rpc_missing = True
            if first:
                logger.warning("llm_tokens_used missing (migration 0035 not applied) - LLM budget disabled")
            return None
        logger.warning("llm_tokens_used failed - LLM budget check skipped (%s)", type(exc).__name__)
    with _lock:
        for k in [k for k, (expires, _) in _cache.items() if expires <= now]:
            del _cache[k]  # expired entries must not pile up (one key per owner and period)
        _cache[key] = (now + CACHE_SECONDS, value)
    return value


def _once_per_day(kind: str, today) -> bool:
    """True the first time per UTC day for this WARNING kind."""
    with _lock:
        if _logged_day.get(kind) == today:
            return False
        _logged_day[kind] = today
        return True


def blocked_reason(sc, shop: dict) -> str | None:
    """Why the bot must not call the LLM for this shop: "kill_switch" | "daily_cap" | "monthly_budget",
    or None (allowed, or unknown because the spend data is unavailable)."""
    s = get_settings()
    if s.llm_kill_switch:
        return "kill_switch"
    now = _now()
    cap = s.llm_daily_token_cap
    if cap > 0:
        today = tokens_used(sc, None, _day_start(now))
        if today is not None:
            if today >= cap:
                if _once_per_day("cap", now.date()):
                    logger.warning("LLM daily token cap reached - bot switched to operator")
                return "daily_cap"
            if today >= cap * ALERT_RATIO and _once_per_day("alert", now.date()):
                logger.warning("LLM spend alert: %d%% of daily token cap", int(today * 100 / cap))
    budget = s.llm_monthly_budget(shop.get("subscription_tier"))
    owner_id = shop.get("owner_id")
    if budget > 0 and owner_id:
        month = tokens_used(sc, str(owner_id), _month_start(now))
        if month is not None and month >= budget:
            return "monthly_budget"
    return None


def spend_status(sc) -> dict:
    """Platform spend for the admin overview. today_tokens / month_tokens are None when unknown."""
    s = get_settings()
    now = _now()
    today = tokens_used(sc, None, _day_start(now))
    month = tokens_used(sc, None, _month_start(now))
    cap = s.llm_daily_token_cap
    return {
        "today_tokens": today,
        "month_tokens": month,
        "daily_cap": cap,
        "kill_switch": s.llm_kill_switch,
        "alert": bool(cap > 0 and today is not None and today >= cap * ALERT_RATIO),
    }
