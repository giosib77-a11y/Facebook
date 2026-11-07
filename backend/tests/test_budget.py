"""S20-8 / S21-7 (A-037 / A-048, N-03): services/budget.py (USD budget), daily_cap(tier), the kill-switch in llm.py.
Offline: fake Supabase, fake clock, fake LLM client factories."""
import logging
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.api.chat as chat
from app.config import get_settings
from app.core.tiers import DAILY_ABUSE_CAP, daily_cap
from app.services import budget, llm
from tests.conftest import FakeSupabase

OWNER = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 11, 5, 13, 30, 0, tzinfo=timezone.utc)
DAY_START = datetime(2026, 11, 5, 0, 0, 0, tzinfo=timezone.utc)
MONTH_START = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
KILL_TEXT = "LLM_KILL_SWITCH ჩართულია — ბოტი გამორთულია"
CLAUDE = "claude-haiku-5-5"
GPT = "gpt-6-luna"
UNKNOWN_WARNING = "llm_usage_by_model failed - LLM budget check skipped (RpcMissing)"


class RpcMissing(Exception):
    code = "PGRST202"


def usage_row(model=CLAUDE, provider="anthropic", input=0, output=0, cache_read=0, cache_write=0):
    return {
        "provider": provider, "model": model, "input_tokens": input, "output_tokens": output,
        "cache_read_tokens": cache_read, "cache_write_tokens": cache_write,
    }


def usd_rows(usd):
    """Rows that cost exactly `usd` at the default Claude output price ($0.50 / 1M tokens)."""
    return [usage_row(output=round(usd * 2_000_000))]


class UsageDb(FakeSupabase):
    """llm_usage_by_model answers by scope: platform (no p_shop) / one shop; day or month by p_since."""

    def __init__(self, platform_day=0.0, platform_month=0.0, shops_day=None, shops_month=None):
        super().__init__()
        self.platform_day = platform_day
        self.platform_month = platform_month
        self.shops_day = shops_day or {}
        self.shops_month = shops_month or {}

    def rpc(self, fn, params):
        day = params["p_since"] != MONTH_START.isoformat()  # day starts: 2026-11-05 (and 11-06 after midnight)
        if params["p_shop"] is None:
            usd = self.platform_day if day else self.platform_month
        else:
            usd = (self.shops_day if day else self.shops_month).get(params["p_shop"], 0.0)
        self.rpc_responses[fn] = usd_rows(usd)
        return super().rpc(fn, params)


class Clock:
    def __init__(self):
        self.now = 5000.0

    def monotonic(self):
        return self.now


@pytest.fixture
def env(monkeypatch):
    """Fixed UTC time + fake monotonic clock + settings override for budget."""
    clock = Clock()
    state = SimpleNamespace(clock=clock, now=NOW)
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(budget, "_now", lambda: state.now)

    def set_settings(**update):
        s = get_settings().model_copy(update=update)
        monkeypatch.setattr(budget, "get_settings", lambda: s)
        return s

    state.set_settings = set_settings
    return state


def _shop(tier="free", owner=OWNER):
    return {"id": str(uuid.uuid4()), "owner_id": owner, "subscription_tier": tier}


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


# ---------------------------------------------------------------------------
# tiers.daily_cap
# ---------------------------------------------------------------------------
def test_daily_cap_free_is_30_paid_are_100_unknown_is_free():
    assert daily_cap("free") == 30
    assert daily_cap("basic") == daily_cap("standard") == daily_cap("business") == 100
    assert daily_cap("platinum") == 30
    assert daily_cap(None) == 30
    assert DAILY_ABUSE_CAP == 100


# ---------------------------------------------------------------------------
# cost_usd  (was: tokens_used)
# ---------------------------------------------------------------------------
def test_cost_uses_per_model_prices(env):
    env.set_settings()
    one_m = 1_000_000

    def cost(rows):
        budget.reset()
        db = FakeSupabase()
        db.rpc_responses["llm_usage_by_model"] = rows
        return budget.cost_usd(db, shop_id="s1", since=MONTH_START)

    assert cost([usage_row(output=one_m)]) == pytest.approx(0.50)
    assert cost([usage_row(input=one_m)]) == pytest.approx(0.10)
    assert cost([usage_row(cache_read=one_m)]) == pytest.approx(0.01)
    assert cost([usage_row(cache_write=one_m)]) == pytest.approx(0.20)  # Claude: 1h write, 2x input
    assert cost([usage_row(model=GPT, provider="openai", cache_write=one_m)]) == pytest.approx(0.10)
    # several models are summed
    mixed = [usage_row(output=one_m), usage_row(model=GPT, provider="openai", output=2 * one_m, cache_read=one_m)]
    assert cost(mixed) == pytest.approx(0.50 + 1.00 + 0.01)


def test_cost_sends_scope_and_iso_since(env):
    db = FakeSupabase()
    db.rpc_responses["llm_usage_by_model"] = []
    assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) == 0.0
    assert [(c.fn, c.params) for c in db.rpc_calls] == [
        ("llm_usage_by_model", {"p_owner": None, "p_shop": "s1", "p_since": "2026-11-01T00:00:00+00:00"})
    ]
    budget.cost_usd(db, since=DAY_START)
    assert db.rpc_calls[-1].params == {"p_owner": None, "p_shop": None, "p_since": "2026-11-05T00:00:00+00:00"}
    budget.cost_usd(db, owner_id=OWNER, since=DAY_START)
    assert db.rpc_calls[-1].params == {"p_owner": OWNER, "p_shop": None, "p_since": "2026-11-05T00:00:00+00:00"}


@pytest.mark.parametrize("data, expected", [
    ([usage_row(output=1_000_000)], 0.5),
    ([usage_row(output="1000000")], 0.5),  # numeric string
    ([usage_row(output=None)], 0.0),
    ([], 0.0),
    (None, 0.0),
    ([usage_row(output=-5)], 0.0),  # negative clamps to zero
])
def test_cost_result_formats(env, data, expected):
    db = FakeSupabase()
    db.rpc_responses["llm_usage_by_model"] = data
    assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) == pytest.approx(expected)


@pytest.mark.parametrize("data", [
    [usage_row(output="not a number")],
    [usage_row(output=True)],
    {"x": 1},
    5,
    ["not a row"],
])
def test_cost_unparsable_result_is_unknown_with_a_warning(env, caplog, data):
    db = FakeSupabase()
    db.rpc_responses["llm_usage_by_model"] = data
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) is None
    assert len(_warnings(caplog)) == 1


def test_unknown_model_priced_at_max(env, caplog):
    env.set_settings(llm_prices={
        "model-a": {"input": 1.0, "output": 2.0, "cache_read": 0.5, "cache_write": 3.0},
        "model-b": {"input": 0.5, "output": 4.0, "cache_read": 0.1, "cache_write": 1.0},
    })
    one_m = 1_000_000

    def cost(**tokens):
        budget.reset()
        db = FakeSupabase()
        db.rpc_responses["llm_usage_by_model"] = [usage_row(model="mystery-9", **tokens)]
        return budget.cost_usd(db, shop_id="s1", since=MONTH_START)

    with caplog.at_level(logging.WARNING, logger="app"):
        assert cost(input=one_m) == pytest.approx(1.0)  # max input
        assert cost(output=one_m) == pytest.approx(4.0)  # max output
        assert cost(cache_read=one_m) == pytest.approx(0.5)  # max cache_read
        assert cost(cache_write=one_m) == pytest.approx(3.0)  # max cache_write


def test_unknown_model_warns_once_per_model(env, caplog):
    db = FakeSupabase()
    db.rpc_responses["llm_usage_by_model"] = [usage_row(model="mystery-9", output=10)]
    with caplog.at_level(logging.WARNING, logger="app"):
        budget.cost_usd(db, shop_id="s1", since=MONTH_START)
        budget.cost_usd(db, shop_id="s2", since=MONTH_START)  # other cache key, same model
        budget.cost_usd(db, shop_id="s1", since=DAY_START)
        assert len(_warnings(caplog)) == 1 and "mystery-9" in _warnings(caplog)[0]
        db.rpc_responses["llm_usage_by_model"] = [usage_row(model="mystery-10", output=10)]
        budget.cost_usd(db, shop_id="s3", since=MONTH_START)
    assert len(_warnings(caplog)) == 2


def test_known_models_do_not_warn(env, caplog):
    db = FakeSupabase()
    db.rpc_responses["llm_usage_by_model"] = [usage_row(output=10), usage_row(model=GPT, provider="openai", output=10)]
    with caplog.at_level(logging.WARNING, logger="app"):
        budget.cost_usd(db, shop_id="s1", since=MONTH_START)
    assert _warnings(caplog) == []


def test_cost_is_cached_for_60_seconds_and_refreshed_after(env):
    db = FakeSupabase()
    db.rpc_responses["llm_usage_by_model"] = usd_rows(1.0)
    assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) == pytest.approx(1.0)
    db.rpc_responses["llm_usage_by_model"] = usd_rows(2.0)
    env.clock.now += 59
    assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) == pytest.approx(1.0)
    assert len(db.rpc_calls) == 1
    env.clock.now += 2  # 61 s since the first call
    assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) == pytest.approx(2.0)
    assert len(db.rpc_calls) == 2


def test_cost_cache_key_is_scope_and_since(env):
    db = FakeSupabase()
    db.rpc_responses["llm_usage_by_model"] = usd_rows(1.0)
    budget.cost_usd(db, shop_id="s1", since=MONTH_START)
    budget.cost_usd(db, since=MONTH_START)
    budget.cost_usd(db, shop_id="s1", since=DAY_START)
    budget.cost_usd(db, shop_id="s2", since=MONTH_START)
    budget.cost_usd(db, owner_id=OWNER, since=MONTH_START)
    assert len(db.rpc_calls) == 5
    budget.cost_usd(db, shop_id="s1", since=MONTH_START)
    assert len(db.rpc_calls) == 5


def test_expired_cache_entries_are_pruned(env):
    db = FakeSupabase()
    db.rpc_responses["llm_usage_by_model"] = usd_rows(1.0)
    for i in range(5):
        budget.cost_usd(db, shop_id=f"s{i}", since=MONTH_START)
    assert len(budget._cache) == 5
    env.clock.now += 61
    budget.cost_usd(db, shop_id="s-new", since=MONTH_START)
    assert len(budget._cache) == 1  # the five expired keys are gone


def test_missing_function_is_a_logged_rpc_error_not_a_permanent_off_switch(env, caplog):
    db = FakeSupabase()
    db.rpc_errors["llm_usage_by_model"] = RpcMissing("function not found")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) is None
        assert budget.cost_usd(db, since=DAY_START) is None
        assert budget.cost_usd(db, shop_id="s1", since=DAY_START) is None
        assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) is None  # cached failure: no RPC
        assert len(db.rpc_calls) == 3  # one RPC per scope - PGRST202 does not stop the next scope
        env.clock.now += 61
        assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) is None
        assert len(db.rpc_calls) == 4  # after the TTL the RPC is tried again
    assert _warnings(caplog) == [UNKNOWN_WARNING] * 4  # same text as any other error


def test_other_rpc_error_is_unknown_with_a_warning_and_retried_after_the_ttl(env, caplog):
    db = FakeSupabase()
    db.rpc_errors["llm_usage_by_model"] = RuntimeError("connection reset secret-detail")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) is None
        assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) is None  # failure cached: no hammering a sick DB
        assert len(db.rpc_calls) == 1
        env.clock.now += 61
        del db.rpc_errors["llm_usage_by_model"]
        db.rpc_responses["llm_usage_by_model"] = usd_rows(0.42)
        assert budget.cost_usd(db, shop_id="s1", since=MONTH_START) == pytest.approx(0.42)  # not a permanent flag
    warnings = _warnings(caplog)
    assert len(warnings) == 1 and "RuntimeError" in warnings[0]
    assert "secret-detail" not in warnings[0]


# ---------------------------------------------------------------------------
# blocked_reason
# ---------------------------------------------------------------------------
def test_kill_switch_blocks_first_without_any_rpc(env):
    env.set_settings(llm_kill_switch=True)
    db = FakeSupabase()
    db.rpc_responses["llm_usage_by_model"] = usd_rows(10**6)
    assert budget.blocked_reason(db, _shop("business")) == "kill_switch"
    assert db.rpc_calls == []


# ---- global daily USD cap (was: daily token cap) ----
def test_global_daily_usd_cap(env, caplog):
    env.set_settings(llm_daily_usd_cap=1.0)
    db = UsageDb(platform_day=1.0)
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.blocked_reason(db, _shop("business")) == "daily_cap"
    # the platform query: no owner, no shop, since the start of the UTC day
    assert any(c.params == {"p_owner": None, "p_shop": None, "p_since": DAY_START.isoformat()} for c in db.rpc_calls)
    assert _warnings(caplog) == ["LLM daily USD cap reached - bot switched to operator"]


def test_global_daily_cap_warning_is_once_per_utc_day(env, caplog):
    env.set_settings(llm_daily_usd_cap=1.0)
    db = UsageDb(platform_day=5.0)
    with caplog.at_level(logging.WARNING, logger="app"):
        for _ in range(3):
            assert budget.blocked_reason(db, _shop()) == "daily_cap"
        assert len(_warnings(caplog)) == 1
        env.now = datetime(2026, 11, 6, 0, 5, 0, tzinfo=timezone.utc)
        env.clock.now += 3600
        assert budget.blocked_reason(db, _shop()) == "daily_cap"
    assert len(_warnings(caplog)) == 2
    assert db.rpc_calls[-1].params["p_since"] == "2026-11-06T00:00:00+00:00"


def test_below_the_alert_threshold_is_allowed_and_silent(env, caplog):
    env.set_settings(llm_daily_usd_cap=1.0)
    db = UsageDb(platform_day=0.79)
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.blocked_reason(db, _shop("business")) is None
    assert _warnings(caplog) == []


def test_eighty_percent_alert_returns_none_and_warns_once_per_day(env, caplog):
    env.set_settings(llm_daily_usd_cap=1.0)
    db = UsageDb(platform_day=0.85)
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.blocked_reason(db, _shop("business")) is None
        assert budget.blocked_reason(db, _shop("business")) is None
    assert _warnings(caplog) == ["LLM spend alert: 85% of daily USD cap"]


def test_global_daily_cap_zero_skips_the_platform_rpc(env):
    env.set_settings(llm_daily_usd_cap=0)
    db = UsageDb(platform_day=10**6, shops_day={})
    assert budget.blocked_reason(db, _shop("free")) is None
    assert all(c.params["p_shop"] is not None for c in db.rpc_calls)  # shop day + shop month only


# ---- per-shop daily cap (was: owner daily token share) ----
@pytest.mark.parametrize("tier, cap, just_below", [
    ("free", 0.03, 0.0299),
    ("basic", 0.25, 0.2499),
    ("standard", 0.80, 0.7999),
    ("business", 2.50, 2.49),
])
def test_shop_daily_cap_is_monthly_over_divisor(env, tier, cap, just_below):
    env.set_settings(llm_daily_usd_cap=0)  # isolate the shop day rule from the platform cap
    shop = _shop(tier)
    blocked = UsageDb(shops_day={shop["id"]: cap})
    assert budget.blocked_reason(blocked, shop) == "shop_daily_cap"
    # RPC is for THIS shop, not for the owner
    assert blocked.rpc_calls[0].params == {"p_owner": None, "p_shop": shop["id"], "p_since": DAY_START.isoformat()}
    budget.reset()
    assert budget.blocked_reason(UsageDb(shops_day={shop["id"]: just_below}), shop) is None


def test_shop_daily_cap_is_per_shop_not_per_owner(env):
    env.set_settings(llm_daily_usd_cap=0)
    shop_a, shop_b = _shop("business"), _shop("business")  # same owner
    db = UsageDb(shops_day={shop_a["id"]: 2.50})
    assert budget.blocked_reason(db, shop_a) == "shop_daily_cap"
    assert budget.blocked_reason(db, shop_b) is None
    assert all(c.params["p_owner"] is None for c in db.rpc_calls)


def test_shop_daily_cap_divisor_zero_skips_the_day_rpc(env):
    env.set_settings(llm_daily_usd_shop_divisor=0, llm_daily_usd_cap=0)
    shop = _shop("business")
    db = UsageDb(shops_day={shop["id"]: 10**6})
    assert budget.blocked_reason(db, shop) is None
    assert DAY_START.isoformat() not in [c.params["p_since"] for c in db.rpc_calls]  # only the month query


def test_shop_daily_cap_is_checked_before_global_and_monthly(env):
    env.set_settings()
    shop = _shop("free")
    db = UsageDb(platform_day=10**3, shops_day={shop["id"]: 1.0}, shops_month={shop["id"]: 10**3})
    assert budget.blocked_reason(db, shop) == "shop_daily_cap"
    assert [c.params["p_shop"] for c in db.rpc_calls] == [shop["id"]]


def test_global_cap_is_checked_before_monthly(env):
    env.set_settings()
    shop = _shop("free")
    db = UsageDb(platform_day=10.0, shops_month={shop["id"]: 10**3})
    assert budget.blocked_reason(db, shop) == "daily_cap"
    assert MONTH_START.isoformat() not in [c.params["p_since"] for c in db.rpc_calls]


def test_kill_switch_still_beats_the_shop_daily_cap(env):
    env.set_settings(llm_kill_switch=True)
    shop = _shop("free")
    db = UsageDb(shops_day={shop["id"]: 10**3})
    assert budget.blocked_reason(db, shop) == "kill_switch"
    assert db.rpc_calls == []


def test_shop_daily_unknown_rpc_fails_open_and_continues_to_global_and_monthly(env):
    env.set_settings(llm_daily_usd_cap=1.0)
    seen = []

    class Db(FakeSupabase):
        def rpc(self, fn, params):
            seen.append((params["p_shop"], params["p_since"]))
            if params["p_shop"] is not None and params["p_since"] == DAY_START.isoformat():
                self.rpc_errors[fn] = RuntimeError("boom")  # only the shop-day call fails
            else:
                self.rpc_errors.pop(fn, None)
                self.rpc_responses[fn] = usd_rows(5.0)
            return super().rpc(fn, params)

    shop = _shop("free")
    # shop-day unknown -> global daily ($5 >= $1) decides
    assert budget.blocked_reason(Db(), shop) == "daily_cap"
    assert seen[0] == (shop["id"], DAY_START.isoformat()) and seen[1] == (None, DAY_START.isoformat())
    # shop-day unknown, global below its cap -> monthly ($5 >= free $0.30) decides
    budget.reset()
    seen.clear()
    env.set_settings(llm_daily_usd_cap=10**6)
    assert budget.blocked_reason(Db(), shop) == "monthly_budget"
    assert (shop["id"], MONTH_START.isoformat()) in seen


def test_shop_without_id_skips_the_shop_checks(env):
    env.set_settings(llm_daily_usd_cap=0)
    db = UsageDb(shops_day={"": 10**6, "None": 10**6})
    assert budget.blocked_reason(db, {"id": None, "owner_id": OWNER, "subscription_tier": "free"}) is None
    assert budget.blocked_reason(db, {"owner_id": OWNER, "subscription_tier": "free"}) is None
    assert db.rpc_calls == []


# ---- monthly budget (was: owner monthly token budget) ----
def test_monthly_usd_budget_is_per_shop(env):
    env.set_settings(llm_daily_usd_cap=0, llm_daily_usd_shop_divisor=0)  # isolate the monthly rule
    shop, sibling = _shop("free"), _shop("free")  # same owner
    db = UsageDb(shops_month={shop["id"]: 0.30})
    assert budget.blocked_reason(db, shop) == "monthly_budget"
    assert [c.params for c in db.rpc_calls] == [
        {"p_owner": None, "p_shop": shop["id"], "p_since": MONTH_START.isoformat()}
    ]
    assert budget.blocked_reason(db, sibling) is None  # the owner's other shop has its own budget


def test_monthly_budget_just_below_is_allowed_and_tier_picks_the_budget(env):
    env.set_settings(llm_daily_usd_cap=0, llm_daily_usd_shop_divisor=0)
    shop = _shop("free")
    db = UsageDb(shops_month={shop["id"]: 0.29})
    assert budget.blocked_reason(db, shop) is None
    basic = dict(shop, subscription_tier="basic")
    assert budget.blocked_reason(db, basic) is None  # same usage, $2.50 budget
    budget.reset()
    db2 = UsageDb(shops_month={shop["id"]: 2.50})
    assert budget.blocked_reason(db2, dict(shop, subscription_tier="basic")) == "monthly_budget"
    assert budget.blocked_reason(db2, dict(shop, subscription_tier="standard")) is None  # $8
    assert budget.blocked_reason(db2, dict(shop, subscription_tier="nonsense")) == "monthly_budget"  # unknown -> free


def test_monthly_budget_zero_disables_it(env):
    env.set_settings(llm_daily_usd_cap=0, llm_daily_usd_shop_divisor=0, llm_monthly_usd_free=0)
    shop = _shop("free")
    db = UsageDb(shops_month={shop["id"]: 10**6})
    assert budget.blocked_reason(db, shop) is None
    assert db.rpc_calls == []


def test_shop_day_and_shop_month_totals_are_cached_separately(env):
    env.set_settings(llm_daily_usd_cap=0)
    shop = _shop("free")
    db = UsageDb(shops_day={shop["id"]: 0.01}, shops_month={shop["id"]: 0.01})
    budget.blocked_reason(db, shop)
    assert [c.params["p_since"] for c in db.rpc_calls] == [DAY_START.isoformat(), MONTH_START.isoformat()]
    budget.blocked_reason(db, shop)
    assert len(db.rpc_calls) == 2  # both served from the cache


# ---- fail-open ----
def test_unavailable_spend_data_never_blocks(env, caplog):
    db = FakeSupabase()
    db.rpc_errors["llm_usage_by_model"] = RpcMissing("missing")
    with caplog.at_level(logging.WARNING, logger="app"):
        shop = _shop("free")
        assert budget.blocked_reason(db, shop) is None
        first_round = len(db.rpc_calls)
        assert budget.blocked_reason(db, shop) is None
    assert first_round >= 1
    assert len(db.rpc_calls) == first_round  # every scope's failure is cached: the 2nd check calls nothing
    assert _warnings(caplog) == [UNKNOWN_WARNING] * first_round  # one WARNING per failed RPC


def test_budget_warnings_never_contain_the_owner_id(env, caplog):
    env.set_settings(llm_daily_usd_cap=1.0)
    shop = _shop("free")
    db = UsageDb(platform_day=0.9, shops_month={shop["id"]: 5.0})
    with caplog.at_level(logging.WARNING, logger="app"):
        budget.blocked_reason(db, shop)
    assert OWNER not in "".join(r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# spend_status
# ---------------------------------------------------------------------------
def test_spend_status_reports_platform_totals_and_alert(env):
    env.set_settings(llm_daily_usd_cap=1.0)
    st = budget.spend_status(UsageDb(platform_day=0.9, platform_month=50.0))
    assert st == {"today_usd": 0.9, "month_usd": 50.0, "daily_cap_usd": 1.0, "kill_switch": False, "alert": True}


def test_spend_status_rounds_to_four_decimals_and_alert_threshold(env):
    env.set_settings(llm_daily_usd_cap=1.0)
    db = FakeSupabase()
    db.rpc_responses["llm_usage_by_model"] = [usage_row(output=1_234_567)]  # 0.6172835
    st = budget.spend_status(db)
    assert st["today_usd"] == 0.6173 and st["alert"] is False
    budget.reset()
    db.rpc_responses["llm_usage_by_model"] = usd_rows(0.8)
    assert budget.spend_status(db)["alert"] is True  # exactly 80%


def test_spend_status_without_the_migration_has_unknown_totals_and_no_alert(env):
    env.set_settings(llm_kill_switch=False)
    db = FakeSupabase()
    db.rpc_errors["llm_usage_by_model"] = RpcMissing("missing")
    st = budget.spend_status(db)
    assert st == {"today_usd": None, "month_usd": None, "daily_cap_usd": 1.0, "kill_switch": False, "alert": False}


def test_spend_status_kill_switch_alone_raises_the_alert(env):
    env.set_settings(llm_kill_switch=True)
    db = FakeSupabase()
    db.rpc_errors["llm_usage_by_model"] = RpcMissing("missing")
    st = budget.spend_status(db)
    assert st["kill_switch"] is True and st["alert"] is True
    assert st["today_usd"] is None


def test_spend_status_has_exactly_the_contract_keys(env):
    db = FakeSupabase()
    db.rpc_responses["llm_usage_by_model"] = []
    assert set(budget.spend_status(db)) == {"today_usd", "month_usd", "daily_cap_usd", "kill_switch", "alert"}


def test_reset_clears_cache_and_flags(env, caplog):
    db = FakeSupabase()
    db.rpc_errors["llm_usage_by_model"] = RpcMissing("missing")
    assert budget.cost_usd(db, since=DAY_START) is None
    budget.reset()
    del db.rpc_errors["llm_usage_by_model"]
    db.rpc_responses["llm_usage_by_model"] = usd_rows(0.5)
    assert budget.cost_usd(db, since=DAY_START) == pytest.approx(0.5)
    # the unknown-model "warned" memory is cleared too
    db.rpc_responses["llm_usage_by_model"] = [usage_row(model="mystery-9", output=1)]
    with caplog.at_level(logging.WARNING, logger="app"):
        budget.cost_usd(db, shop_id="s1", since=DAY_START)
        budget.reset()
        budget.cost_usd(db, shop_id="s1", since=DAY_START)
    assert len([w for w in _warnings(caplog) if "mystery-9" in w]) == 2


# ---------------------------------------------------------------------------
# kill-switch in llm.py
# ---------------------------------------------------------------------------
@pytest.fixture
def llm_env(monkeypatch):
    calls = SimpleNamespace(factory=0)

    def factory(s):
        calls.factory += 1
        raise AssertionError("no client may be built while the kill-switch is on")

    monkeypatch.setattr(llm, "_anthropic_client", factory)
    monkeypatch.setattr(llm, "_openai_client", factory)

    def set_settings(**update):
        s = get_settings().model_copy(update=update)
        for module in (llm, chat):
            monkeypatch.setattr(module, "get_settings", lambda: s)

    calls.set_settings = set_settings
    return calls


def test_kill_switch_makes_generate_raise_before_any_client(llm_env):
    llm_env.set_settings(llm_kill_switch=True)
    prompt = SimpleNamespace(layer1="a", layer2="b", history=[], final=[{"type": "text", "text": "hi"}])
    with pytest.raises(RuntimeError, match="LLM_KILL_SWITCH"):
        llm.generate(prompt, "shop-1")
    assert llm_env.factory == 0


def test_kill_switch_makes_complete_raise_before_any_client(llm_env):
    llm_env.set_settings(llm_kill_switch=True)
    with pytest.raises(RuntimeError) as err:
        llm.complete("system", "text", "shop-1", max_tokens=50)
    assert str(err.value) == KILL_TEXT
    assert llm_env.factory == 0


def test_kill_switch_beats_the_provider_override_and_the_key_check(llm_env):
    llm_env.set_settings(llm_kill_switch=True, anthropic_api_key="")
    with pytest.raises(RuntimeError, match="LLM_KILL_SWITCH"):
        llm.complete("system", "text", "shop-1", max_tokens=50, provider="openai")


def test_test_chat_returns_503_with_the_kill_switch_text(client, service_db, llm_env, monkeypatch):
    shop_id = str(uuid.uuid4())
    service_db.responses[("shops", "select")] = [{"id": shop_id, "name": "Tbilisi Style", "currency": "GEL"}]
    service_db.responses[("products", "select")] = []
    monkeypatch.setattr(chat, "get_service_client", lambda: service_db)
    llm_env.set_settings(llm_kill_switch=True)
    r = client.post("/test-chat", json={"shop_id": shop_id, "message": "what is the price of Item 1?", "history": []})
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == KILL_TEXT
    assert llm_env.factory == 0
