"""S20-9 (A-037 / N-03): the webhook honours the LLM spend control and the per-tier daily cap.

* day_count above the tier cap (free 30, paid 100) -> silent (abuse/loop), no reply, no LLM
* kill-switch / daily cap / monthly budget (`budget.blocked_reason`) -> the operator path
  (OPERATOR_SOON_REPLY, needs_attention, bot pause), never `run_turn`
* over-limit / disabled bot / paused conversation never reach the budget RPC
* unknown spend (RPC error) -> fail-open: the bot answers normally

`_process_events` is called directly with a fake service client; nothing leaves the process.
"""
import logging
from datetime import datetime, timedelta, timezone

import pytest

import app.api.webhook as webhook
from app.services import budget
from app.services.graph import TurnResult
from tests.test_reply_delivery import PAGE_ID, PSID, SHOP_ID

CUSTOMER_TEXT = "ფასი რა არის? ჩემი ნომერია 555123456"
OWNER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def env(monkeypatch, service_db):
    db = service_db
    db.responses[("shops", "select")] = [_shop("free")]
    db.responses[("products", "select")] = []
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 1}]

    calls = {"bot": 0}
    sent = []

    def fake_run_turn(shop, products, text, history, images=None, **kw):
        calls["bot"] += 1
        return TurnResult("llm reply")

    monkeypatch.setattr(webhook, "get_service_client", lambda: db)
    monkeypatch.setattr(webhook, "decrypt", lambda token: "page-token")
    monkeypatch.setattr(webhook, "send_text_message", lambda tok, psid, text: sent.append(text))
    monkeypatch.setattr(webhook, "download_image", lambda url, timeout=8: None)
    monkeypatch.setattr(webhook, "run_turn", fake_run_turn)
    return db, sent, calls


def _shop(tier, owner=OWNER):
    return {
        "id": SHOP_ID, "owner_id": owner, "bot_enabled": True, "facebook_page_token": "enc",
        "subscription_tier": tier,
    }


def _budget_settings(monkeypatch, **update):
    s = budget.get_settings().model_copy(update=update)
    monkeypatch.setattr(budget, "get_settings", lambda: s)
    return s


def _run(message=None):
    webhook._process_events({"object": "page", "entry": [{
        "id": PAGE_ID,
        "messaging": [{"sender": {"id": PSID}, "message": message or {"text": CUSTOMER_TEXT}}],
    }]})


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def _budget_rpcs(db):
    return [c for c in db.rpc_calls if c.fn == "llm_tokens_used"]


def _assert_operator_outcome(db, sent, calls):
    assert sent == [webhook.OPERATOR_SOON_REPLY]
    assert calls["bot"] == 0
    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["needs_attention"] is True
    assert save.payload["bot_paused_until"]
    assert save.payload["messages"][-2:] == [
        {"role": "user", "content": CUSTOMER_TEXT},
        {"role": "bot", "content": webhook.OPERATOR_SOON_REPLY},
    ]
    assert db.calls_for("llm_usage", "insert") == []


# ---- (1) per-tier daily cap -------------------------------------------------
def test_free_tier_daily_cap_30_is_silent(env):
    db, sent, calls = env
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 31}]

    _run()

    assert sent == []
    assert calls["bot"] == 0
    assert db.calls_for("bot_conversations", "upsert") == []


def test_free_tier_at_cap_30_still_answers(env):
    db, sent, calls = env
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 30}]

    _run()

    assert sent == ["llm reply"]
    assert calls["bot"] == 1


def test_basic_tier_day_count_31_still_answers(env):
    db, sent, calls = env
    db.responses[("shops", "select")] = [_shop("basic")]
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 31}]

    _run()

    assert sent == ["llm reply"]
    assert calls["bot"] == 1


def test_basic_tier_day_count_101_is_silent(env):
    db, sent, calls = env
    db.responses[("shops", "select")] = [_shop("basic")]
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 101}]

    _run()

    assert sent == []
    assert calls["bot"] == 0
    assert db.calls_for("bot_conversations", "upsert") == []


# ---- (2) blocked_reason -> operator path ------------------------------------
def test_monthly_budget_reason_sends_operator_reply_and_pauses(env, monkeypatch, caplog):
    db, sent, calls = env
    monkeypatch.setattr(budget, "blocked_reason", lambda sc, shop: "monthly_budget")

    with caplog.at_level(logging.WARNING, logger="app"):
        _run()

    _assert_operator_outcome(db, sent, calls)
    msgs = [m for m in _warnings(caplog) if "bot budget" in m]
    assert len(msgs) == 1
    assert "monthly_budget" in msgs[0] and SHOP_ID in msgs[0]
    joined = "\n".join(_warnings(caplog))
    assert PSID not in joined
    assert "555123456" not in joined


def test_blocked_reason_receives_service_client_and_shop(env, monkeypatch):
    db, _, _ = env
    seen = []
    monkeypatch.setattr(budget, "blocked_reason", lambda sc, shop: seen.append((sc, shop)))

    _run()

    assert len(seen) == 1
    assert seen[0][0] is db
    assert seen[0][1]["id"] == SHOP_ID and seen[0][1]["owner_id"] == OWNER


# ---- (3) kill-switch ---------------------------------------------------------
def test_kill_switch_uses_operator_path_without_budget_rpc(env, monkeypatch, caplog):
    db, sent, calls = env
    _budget_settings(monkeypatch, llm_kill_switch=True)

    with caplog.at_level(logging.WARNING, logger="app"):
        _run()

    _assert_operator_outcome(db, sent, calls)
    assert _budget_rpcs(db) == []
    assert any("bot budget: kill_switch" in m and SHOP_ID in m for m in _warnings(caplog))


# ---- (4) real blocked_reason over the fake RPC -------------------------------
def test_owner_monthly_total_above_budget_uses_operator_path(env, monkeypatch, caplog):
    db, sent, calls = env
    _budget_settings(monkeypatch, llm_daily_token_cap=0)  # isolate the monthly rule
    db.rpc_responses["llm_tokens_used"] = 10_000_000  # free budget: 2_000_000

    with caplog.at_level(logging.WARNING, logger="app"):
        _run()

    _assert_operator_outcome(db, sent, calls)
    (rpc,) = _budget_rpcs(db)
    assert rpc.params["p_owner"] == OWNER
    assert any("bot budget: monthly_budget" in m for m in _warnings(caplog))


def test_global_daily_cap_uses_operator_path(env, caplog):
    db, sent, calls = env
    db.rpc_responses["llm_tokens_used"] = 10_000_000  # default daily cap: 3_000_000

    with caplog.at_level(logging.WARNING, logger="app"):
        _run()

    _assert_operator_outcome(db, sent, calls)
    assert any("bot budget: daily_cap" in m for m in _warnings(caplog))


def test_spend_below_budget_answers_normally(env):
    db, sent, calls = env
    db.rpc_responses["llm_tokens_used"] = 1_000

    _run()

    assert sent == ["llm reply"]
    assert calls["bot"] == 1


# ---- (5) budget is not consulted when the decision is already made -----------
def _spy(monkeypatch):
    seen = []
    monkeypatch.setattr(budget, "blocked_reason", lambda sc, shop: seen.append(shop) or "monthly_budget")
    return seen


def test_over_limit_customer_does_not_consult_budget(env, monkeypatch):
    db, sent, calls = env
    seen = _spy(monkeypatch)
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 31, "day_count": 1}]
    db.responses[("bot_customers", "select")] = [{"created_at": "2026-10-01T10:00:00+00:00"}]
    db.counts[("bot_customers", "select")] = 30  # rank 31 -> over the free limit

    _run()

    assert seen == []
    assert sent == [webhook.OPERATOR_SOON_REPLY]  # exactly one reply
    assert calls["bot"] == 0


def test_disabled_bot_does_not_consult_budget(env, monkeypatch):
    db, sent, calls = env
    seen = _spy(monkeypatch)
    s = webhook.get_settings().model_copy(update={"anthropic_api_key": ""})
    monkeypatch.setattr(webhook, "get_settings", lambda: s)

    _run()

    assert seen == []
    assert sent == [webhook.OPERATOR_SOON_REPLY]


def test_paused_conversation_does_not_consult_budget(env, monkeypatch):
    db, sent, calls = env
    seen = _spy(monkeypatch)
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    db.responses[("bot_conversations", "select")] = [{"bot_paused_until": future, "messages": []}]

    _run()

    assert seen == []
    assert sent == []
    assert calls["bot"] == 0
    assert _budget_rpcs(db) == []


# ---- (6) fail-open -----------------------------------------------------------
def test_budget_rpc_error_keeps_bot_answering(env, caplog):
    db, sent, calls = env
    db.rpc_errors["llm_tokens_used"] = RuntimeError("db down")

    with caplog.at_level(logging.WARNING, logger="app"):
        _run()

    assert sent == ["llm reply"]
    assert calls["bot"] == 1
    (save,) = db.calls_for("bot_conversations", "upsert")
    assert "needs_attention" not in save.payload
    assert not any("bot budget" in m for m in _warnings(caplog))


def test_missing_migration_keeps_bot_answering(env):
    db, sent, calls = env

    class Missing(Exception):
        code = "PGRST202"

    db.rpc_errors["llm_tokens_used"] = Missing("function not found")

    _run()

    assert sent == ["llm reply"]
    assert calls["bot"] == 1
