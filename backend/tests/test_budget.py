"""S20-8 (A-037 / N-03): services/budget.py, daily_cap(tier), the kill-switch in llm.py. Offline: fake Supabase,
fake clock, fake LLM client factories."""
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


class RpcMissing(Exception):
    code = "PGRST202"


class SplitDb(FakeSupabase):
    """llm_tokens_used answers by p_owner (None = platform), so the global and the owner total differ."""

    def __init__(self, platform=0, owners=None):
        super().__init__()
        self.platform = platform
        self.owners = owners or {}

    def rpc(self, fn, params):
        self.rpc_responses[fn] = self.platform if params["p_owner"] is None else self.owners.get(params["p_owner"], 0)
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
# tokens_used
# ---------------------------------------------------------------------------
def test_tokens_used_sends_owner_and_iso_since(env):
    db = FakeSupabase()
    db.rpc_responses["llm_tokens_used"] = 1234
    assert budget.tokens_used(db, OWNER, MONTH_START) == 1234
    assert [(c.fn, c.params) for c in db.rpc_calls] == [
        ("llm_tokens_used", {"p_owner": OWNER, "p_since": "2026-11-01T00:00:00+00:00"})
    ]
    budget.tokens_used(db, None, DAY_START)
    assert db.rpc_calls[-1].params == {"p_owner": None, "p_since": "2026-11-05T00:00:00+00:00"}


@pytest.mark.parametrize("data, expected", [
    (5, 5),
    ("7", 7),
    ([{"llm_tokens_used": 9}], 9),
    ([{"llm_tokens_used": "11"}], 11),
    (None, 0),
    ([], 0),
    (-3, 0),
])
def test_tokens_used_result_formats(env, data, expected):
    db = FakeSupabase()
    db.rpc_responses["llm_tokens_used"] = data
    assert budget.tokens_used(db, OWNER, MONTH_START) == expected


@pytest.mark.parametrize("data", ["not a number", True, {"x": 1}])
def test_tokens_used_unparsable_result_is_unknown_with_a_warning(env, caplog, data):
    db = FakeSupabase()
    db.rpc_responses["llm_tokens_used"] = data
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.tokens_used(db, OWNER, MONTH_START) is None
    assert len(_warnings(caplog)) == 1


def test_tokens_used_is_cached_for_60_seconds_and_refreshed_after(env):
    db = FakeSupabase()
    db.rpc_responses["llm_tokens_used"] = 100
    assert budget.tokens_used(db, OWNER, MONTH_START) == 100
    db.rpc_responses["llm_tokens_used"] = 200
    env.clock.now += 59
    assert budget.tokens_used(db, OWNER, MONTH_START) == 100
    assert len(db.rpc_calls) == 1
    env.clock.now += 2  # 61 s since the first call
    assert budget.tokens_used(db, OWNER, MONTH_START) == 200
    assert len(db.rpc_calls) == 2


def test_tokens_used_cache_key_is_owner_and_since(env):
    db = FakeSupabase()
    db.rpc_responses["llm_tokens_used"] = 1
    budget.tokens_used(db, OWNER, MONTH_START)
    budget.tokens_used(db, None, MONTH_START)
    budget.tokens_used(db, OWNER, DAY_START)
    budget.tokens_used(db, "33333333-3333-3333-3333-333333333333", MONTH_START)
    assert len(db.rpc_calls) == 4
    budget.tokens_used(db, OWNER, MONTH_START)
    assert len(db.rpc_calls) == 4


def test_missing_function_disables_the_budget_with_one_warning(env, caplog):
    db = FakeSupabase()
    db.rpc_errors["llm_tokens_used"] = RpcMissing("function not found")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.tokens_used(db, OWNER, MONTH_START) is None
        assert budget.tokens_used(db, None, DAY_START) is None
        assert budget.tokens_used(db, OWNER, DAY_START) is None
    assert len(db.rpc_calls) == 1  # no RPC after the first PGRST202
    assert _warnings(caplog) == ["llm_tokens_used missing (migration 0035 not applied) - LLM budget disabled"]


def test_other_rpc_error_is_unknown_with_a_warning_and_retried_after_the_ttl(env, caplog):
    db = FakeSupabase()
    db.rpc_errors["llm_tokens_used"] = RuntimeError("connection reset secret-detail")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.tokens_used(db, OWNER, MONTH_START) is None
        assert budget.tokens_used(db, OWNER, MONTH_START) is None  # failure cached: no hammering a sick DB
        assert len(db.rpc_calls) == 1
        env.clock.now += 61
        del db.rpc_errors["llm_tokens_used"]
        db.rpc_responses["llm_tokens_used"] = 42
        assert budget.tokens_used(db, OWNER, MONTH_START) == 42  # not a permanent flag
    warnings = _warnings(caplog)
    assert len(warnings) == 1 and "RuntimeError" in warnings[0]
    assert "secret-detail" not in warnings[0]


# ---------------------------------------------------------------------------
# blocked_reason
# ---------------------------------------------------------------------------
def test_kill_switch_blocks_first_without_any_rpc(env):
    env.set_settings(llm_kill_switch=True)
    db = FakeSupabase()
    db.rpc_responses["llm_tokens_used"] = 10**12
    assert budget.blocked_reason(db, _shop("business")) == "kill_switch"
    assert db.rpc_calls == []


def test_daily_cap_blocks_when_platform_tokens_reach_the_cap(env, caplog):
    env.set_settings(llm_daily_token_cap=1000, llm_daily_tokens_per_owner=0)  # owner share off: RPC order is platform first
    db = SplitDb(platform=1000)
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.blocked_reason(db, _shop("business")) == "daily_cap"
    assert db.rpc_calls[0].params == {"p_owner": None, "p_since": DAY_START.isoformat()}
    assert _warnings(caplog) == ["LLM daily token cap reached - bot switched to operator"]


def test_daily_cap_warning_is_once_per_utc_day(env, caplog):
    env.set_settings(llm_daily_token_cap=1000)
    db = SplitDb(platform=5000)
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
    env.set_settings(llm_daily_token_cap=1000)
    db = SplitDb(platform=799)
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.blocked_reason(db, _shop("business")) is None
    assert _warnings(caplog) == []


def test_eighty_percent_alert_returns_none_and_warns_once_per_day(env, caplog):
    env.set_settings(llm_daily_token_cap=1000)
    db = SplitDb(platform=850)
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.blocked_reason(db, _shop("business")) is None
        assert budget.blocked_reason(db, _shop("business")) is None
    assert _warnings(caplog) == ["LLM spend alert: 85% of daily token cap"]


def test_monthly_budget_blocks_a_free_owner_at_2m_tokens(env):
    env.set_settings(llm_daily_token_cap=3_000_000, llm_daily_tokens_per_owner=0)  # isolate the monthly rule
    db = SplitDb(platform=100, owners={OWNER: 2_000_000})
    assert budget.blocked_reason(db, _shop("free")) == "monthly_budget"
    params = [c.params for c in db.rpc_calls]
    assert {"p_owner": None, "p_since": DAY_START.isoformat()} in params
    assert {"p_owner": OWNER, "p_since": MONTH_START.isoformat()} in params


def test_monthly_budget_just_below_is_allowed_and_tier_picks_the_budget(env):
    env.set_settings(llm_daily_token_cap=0, llm_daily_tokens_per_owner=0)
    db = SplitDb(owners={OWNER: 1_999_999})
    assert budget.blocked_reason(db, _shop("free")) is None
    assert budget.blocked_reason(db, _shop("basic")) is None  # same usage, 12M budget
    budget.reset()
    db2 = SplitDb(owners={OWNER: 12_000_000})
    assert budget.blocked_reason(db2, _shop("basic")) == "monthly_budget"
    assert budget.blocked_reason(db2, _shop("standard")) is None  # 48M
    assert budget.blocked_reason(db2, _shop("nonsense")) == "monthly_budget"  # unknown -> free


def test_monthly_budget_zero_disables_it(env):
    env.set_settings(llm_daily_token_cap=0, llm_daily_tokens_per_owner=0, llm_monthly_tokens_free=0)
    db = SplitDb(owners={OWNER: 10**12})
    assert budget.blocked_reason(db, _shop("free")) is None
    assert db.rpc_calls == []


def test_daily_cap_zero_skips_the_platform_rpc(env):
    env.set_settings(llm_daily_token_cap=0, llm_daily_tokens_per_owner=0)
    db = SplitDb(platform=10**12, owners={OWNER: 5})
    assert budget.blocked_reason(db, _shop("free")) is None
    assert [c.params["p_owner"] for c in db.rpc_calls] == [OWNER]


def test_shop_without_owner_skips_the_monthly_check(env):
    env.set_settings(llm_daily_token_cap=0)  # owner daily share stays at its default (on)
    db = SplitDb(owners={OWNER: 10**12})
    assert budget.blocked_reason(db, _shop("free", owner=None)) is None
    assert db.rpc_calls == []  # neither the owner-day nor the owner-month RPC without an owner


def test_unavailable_spend_data_never_blocks(env, caplog):
    db = FakeSupabase()
    db.rpc_errors["llm_tokens_used"] = RpcMissing("missing")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.blocked_reason(db, _shop("free")) is None
        assert budget.blocked_reason(db, _shop("free")) is None
    assert len(_warnings(caplog)) == 1
    assert len(db.rpc_calls) == 1


def test_budget_warnings_never_contain_the_owner_id(env, caplog):
    # the owner-daily WARNING names the owner on purpose (S20-19), so it is off here: global alert + monthly path
    env.set_settings(llm_daily_token_cap=1000, llm_daily_tokens_per_owner=0)
    db = SplitDb(platform=900, owners={OWNER: 2_000_000})
    with caplog.at_level(logging.WARNING, logger="app"):
        budget.blocked_reason(db, _shop("free"))
    assert OWNER not in "".join(r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# S20-19: owner daily token share
# ---------------------------------------------------------------------------
OTHER_OWNER = "33333333-3333-3333-3333-333333333333"
OWNER_WARNING = "LLM owner daily token cap reached - bot switched to operator (owner=%s)"


def test_owner_daily_cap_blocks_one_tenant_while_the_platform_is_below_its_cap(env, caplog):
    env.set_settings()  # defaults: owner 1M/day, platform 3M/day
    db = SplitDb(platform=1_500_000, owners={OWNER: 1_000_000})
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.blocked_reason(db, _shop("business")) == "owner_daily_cap"
    assert [c.params for c in db.rpc_calls] == [{"p_owner": OWNER, "p_since": DAY_START.isoformat()}]
    assert _warnings(caplog) == [OWNER_WARNING % OWNER]
    # another tenant of the same platform is not affected
    assert budget.blocked_reason(db, _shop("business", owner=OTHER_OWNER)) is None


def test_owner_daily_cap_just_below_is_allowed(env):
    env.set_settings(llm_daily_token_cap=0, llm_monthly_tokens_free=0)
    db = SplitDb(owners={OWNER: 999_999})
    assert budget.blocked_reason(db, _shop("free")) is None


def test_owner_daily_cap_is_checked_before_the_global_and_monthly_caps(env):
    env.set_settings()
    db = SplitDb(platform=10**9, owners={OWNER: 10**9})
    assert budget.blocked_reason(db, _shop("free")) == "owner_daily_cap"
    assert [c.params["p_owner"] for c in db.rpc_calls] == [OWNER]


def test_kill_switch_still_beats_the_owner_daily_cap(env):
    env.set_settings(llm_kill_switch=True)
    db = SplitDb(owners={OWNER: 10**9})
    assert budget.blocked_reason(db, _shop("free")) == "kill_switch"
    assert db.rpc_calls == []


def test_owner_daily_cap_zero_skips_the_owner_day_rpc(env):
    env.set_settings(llm_daily_tokens_per_owner=0, llm_daily_token_cap=0, llm_monthly_tokens_free=0)
    db = SplitDb(owners={OWNER: 10**12})
    assert budget.blocked_reason(db, _shop("free")) is None
    assert db.rpc_calls == []


def test_owner_daily_cap_zero_still_checks_global_and_monthly(env):
    env.set_settings(llm_daily_tokens_per_owner=0)
    db = SplitDb(platform=10**12, owners={OWNER: 10**12})
    assert budget.blocked_reason(db, _shop("free")) == "daily_cap"
    assert OWNER not in [c.params["p_owner"] for c in db.rpc_calls]  # no owner RPC before the platform one


def test_owner_daily_unknown_rpc_fails_open_and_continues_to_global_and_monthly(env):
    env.set_settings(llm_daily_token_cap=1000)
    seen = []

    class Db(FakeSupabase):
        def rpc(self, fn, params):
            seen.append((params["p_owner"], params["p_since"]))
            if params["p_owner"] == OWNER and params["p_since"] == DAY_START.isoformat():
                self.rpc_errors[fn] = RuntimeError("boom")  # only the owner-day call fails
            else:
                self.rpc_errors.pop(fn, None)
                self.rpc_responses[fn] = 5000 if params["p_owner"] is None else 3_000_000
            return super().rpc(fn, params)

    # owner-day unknown -> global daily (5000 >= 1000) decides
    assert budget.blocked_reason(Db(), _shop("free")) == "daily_cap"
    assert seen[0] == (OWNER, DAY_START.isoformat()) and seen[1] == (None, DAY_START.isoformat())
    # owner-day unknown, global below its cap -> monthly (3M >= free 2M) decides
    budget.reset()
    seen.clear()
    env.set_settings(llm_daily_token_cap=10**9)
    assert budget.blocked_reason(Db(), _shop("free")) == "monthly_budget"
    assert (OWNER, MONTH_START.isoformat()) in seen


def test_owner_daily_missing_migration_never_blocks(env):
    db = FakeSupabase()
    db.rpc_errors["llm_tokens_used"] = RpcMissing("missing")
    assert budget.blocked_reason(db, _shop("free")) is None
    assert len(db.rpc_calls) == 1


def test_shop_without_owner_skips_the_owner_daily_check(env):
    env.set_settings(llm_daily_token_cap=0)
    db = SplitDb(owners={OWNER: 10**12, "": 10**12})
    assert budget.blocked_reason(db, _shop("free", owner=None)) is None
    assert budget.blocked_reason(db, _shop("free", owner="")) is None
    assert db.rpc_calls == []


def test_owner_daily_warning_is_once_per_owner_per_utc_day(env, caplog):
    env.set_settings(llm_daily_token_cap=0)
    db = SplitDb(owners={OWNER: 2_000_000, OTHER_OWNER: 2_000_000})
    with caplog.at_level(logging.WARNING, logger="app"):
        for _ in range(3):
            assert budget.blocked_reason(db, _shop()) == "owner_daily_cap"
        assert _warnings(caplog) == [OWNER_WARNING % OWNER]
        assert budget.blocked_reason(db, _shop(owner=OTHER_OWNER)) == "owner_daily_cap"  # own warning
        assert _warnings(caplog) == [OWNER_WARNING % OWNER, OWNER_WARNING % OTHER_OWNER]
        env.now = datetime(2026, 11, 6, 0, 5, 0, tzinfo=timezone.utc)
        env.clock.now += 3600
        assert budget.blocked_reason(db, _shop()) == "owner_daily_cap"  # next UTC day: again
    assert _warnings(caplog)[-1] == OWNER_WARNING % OWNER
    assert len(_warnings(caplog)) == 3
    assert db.rpc_calls[-1].params == {"p_owner": OWNER, "p_since": "2026-11-06T00:00:00+00:00"}


def test_owner_day_and_owner_month_totals_are_cached_separately(env):
    env.set_settings(llm_daily_token_cap=0)
    db = SplitDb(owners={OWNER: 10})
    budget.blocked_reason(db, _shop("free"))
    assert [c.params["p_since"] for c in db.rpc_calls] == [DAY_START.isoformat(), MONTH_START.isoformat()]
    budget.blocked_reason(db, _shop("free"))
    assert len(db.rpc_calls) == 2  # both served from the cache


# ---------------------------------------------------------------------------
# spend_status
# ---------------------------------------------------------------------------
def test_spend_status_reports_platform_totals_and_alert(env):
    env.set_settings(llm_daily_token_cap=1000)

    class Db(FakeSupabase):
        def rpc(self, fn, params):
            self.rpc_responses[fn] = 900 if params["p_since"].startswith("2026-11-05") else 50_000
            return super().rpc(fn, params)

    st = budget.spend_status(Db())
    assert st == {"today_tokens": 900, "month_tokens": 50_000, "daily_cap": 1000, "kill_switch": False, "alert": True}


def test_spend_status_without_the_migration_has_unknown_totals_and_no_alert(env):
    env.set_settings(llm_kill_switch=True)
    db = FakeSupabase()
    db.rpc_errors["llm_tokens_used"] = RpcMissing("missing")
    st = budget.spend_status(db)
    assert st == {"today_tokens": None, "month_tokens": None, "daily_cap": 3_000_000, "kill_switch": True, "alert": False}


def test_reset_clears_cache_and_flags(env):
    db = FakeSupabase()
    db.rpc_errors["llm_tokens_used"] = RpcMissing("missing")
    assert budget.tokens_used(db, None, DAY_START) is None
    budget.reset()
    del db.rpc_errors["llm_tokens_used"]
    db.rpc_responses["llm_tokens_used"] = 3
    assert budget.tokens_used(db, None, DAY_START) == 3


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
