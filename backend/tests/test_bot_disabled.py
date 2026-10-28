"""S14-6: the selected provider's key is missing -> the app runs, the bot is disabled.

The webhook sends the safe operator reply, flags the conversation (needs_attention), never
calls the LLM or downloads photos, still counts the customer, and logs a WARNING with the
variable NAME and shop id only (no PSID, no message text, no values).

`_process_events` is called directly with a fake service client; nothing leaves the process.
"""
import logging

import pytest

import app.api.webhook as webhook
from app.core.tiers import DAILY_ABUSE_CAP
from app.services.graph import TurnResult
from tests.test_reply_delivery import PAGE_ID, PSID, SHOP_ID

CUSTOMER_TEXT = "ფასი რა არის? ჩემი ნომერია 555123456"


@pytest.fixture
def env(monkeypatch, service_db):
    db = service_db
    db.responses[("shops", "select")] = [{
        "id": SHOP_ID, "bot_enabled": True, "facebook_page_token": "enc",
        "subscription_tier": "free",
    }]
    db.responses[("products", "select")] = []
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 1}]

    calls = {"bot": 0, "download": 0}
    sent = []

    def fake_run_turn(shop, products, text, history, images=None, **kw):
        calls["bot"] += 1
        return TurnResult("llm reply")

    def fake_download(url, timeout=8):
        calls["download"] += 1
        return b"img", "image/jpeg"

    monkeypatch.setattr(webhook, "get_service_client", lambda: db)
    monkeypatch.setattr(webhook, "decrypt", lambda token: "page-token")
    monkeypatch.setattr(webhook, "send_text_message", lambda tok, psid, text: sent.append(text))
    monkeypatch.setattr(webhook, "download_image", fake_download)
    monkeypatch.setattr(webhook, "run_turn", fake_run_turn)
    return db, sent, calls


def _settings(monkeypatch, **update):
    s = webhook.get_settings().model_copy(update=update)
    monkeypatch.setattr(webhook, "get_settings", lambda: s)
    return s


def _run(message=None):
    webhook._process_events({"object": "page", "entry": [{
        "id": PAGE_ID,
        "messaging": [{"sender": {"id": PSID}, "message": message or {"text": CUSTOMER_TEXT}}],
    }]})


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def _assert_disabled_outcome(db, sent, calls):
    assert sent == [webhook.OPERATOR_SOON_REPLY]
    assert calls == {"bot": 0, "download": 0}
    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["needs_attention"] is True
    assert save.payload["psid"] == PSID
    assert save.payload["messages"][-2:] == [
        {"role": "user", "content": CUSTOMER_TEXT},
        {"role": "bot", "content": webhook.OPERATOR_SOON_REPLY},
    ]
    assert db.calls_for("llm_usage", "insert") == []
    # the customer is still counted (monthly limit accounting is unchanged)
    assert [c.fn for c in db.rpc_calls] == ["track_bot_customer"]


def test_missing_claude_key_sends_operator_reply_and_flags_conversation(env, monkeypatch, caplog):
    db, sent, calls = env
    _settings(monkeypatch, anthropic_api_key="")

    with caplog.at_level(logging.WARNING, logger="app"):
        _run()

    _assert_disabled_outcome(db, sent, calls)
    warnings = _warnings(caplog)
    disabled = [m for m in warnings if "bot disabled" in m]
    assert len(disabled) == 1
    assert SHOP_ID in disabled[0] and "ANTHROPIC_API_KEY" in disabled[0]
    joined = "\n".join(warnings)
    assert PSID not in joined
    assert "555123456" not in joined
    assert "test-anthropic-key-not-real" not in joined


def test_missing_openai_key_names_openai_variable(env, monkeypatch, caplog):
    db, sent, calls = env
    _settings(monkeypatch, llm_provider="openai", openai_api_key="")

    with caplog.at_level(logging.WARNING, logger="app"):
        _run()

    _assert_disabled_outcome(db, sent, calls)
    disabled = [m for m in _warnings(caplog) if "bot disabled" in m]
    assert len(disabled) == 1
    assert SHOP_ID in disabled[0] and "OPENAI_API_KEY" in disabled[0]
    assert "ANTHROPIC_API_KEY" not in disabled[0]
    assert PSID not in "\n".join(_warnings(caplog))


def test_whitespace_only_key_counts_as_missing(env, monkeypatch):
    db, sent, calls = env
    _settings(monkeypatch, anthropic_api_key="   ")

    _run()

    _assert_disabled_outcome(db, sent, calls)


def test_photo_message_does_not_download_images_when_disabled(env, monkeypatch):
    db, sent, calls = env
    _settings(monkeypatch, anthropic_api_key="")

    _run({"attachments": [{"type": "image", "payload": {"url": "https://cdn.example.com/a.jpg"}}]})

    assert sent == [webhook.OPERATOR_SOON_REPLY]
    assert calls == {"bot": 0, "download": 0}
    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["needs_attention"] is True
    assert save.payload["messages"][-2]["content"] == "[სურათი]"


def test_abuse_cap_is_still_silent_when_disabled(env, monkeypatch, caplog):
    db, sent, calls = env
    _settings(monkeypatch, anthropic_api_key="")
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": DAILY_ABUSE_CAP + 1}]

    with caplog.at_level(logging.WARNING, logger="app"):
        _run()

    assert sent == []
    assert calls == {"bot": 0, "download": 0}
    assert db.calls_for("bot_conversations", "upsert") == []
    assert not any("bot disabled" in m for m in _warnings(caplog))


def test_disabled_bot_and_over_limit_send_one_reply(env, monkeypatch):
    db, sent, calls = env
    _settings(monkeypatch, anthropic_api_key="")
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 31, "day_count": 1}]
    db.responses[("bot_customers", "select")] = [{"created_at": "2026-10-01T10:00:00+00:00"}]
    db.counts[("bot_customers", "select")] = 30  # rank 31 -> over the free limit

    _run()

    assert sent == [webhook.OPERATOR_SOON_REPLY]
    assert len(db.calls_for("bot_conversations", "upsert")) == 1
    assert calls["bot"] == 0


def test_with_key_the_normal_path_runs(env, monkeypatch, caplog):
    db, sent, calls = env
    _settings(monkeypatch)  # default test settings: claude + dummy key

    with caplog.at_level(logging.WARNING, logger="app"):
        _run()

    assert sent == ["llm reply"]
    assert calls["bot"] == 1
    (save,) = db.calls_for("bot_conversations", "upsert")
    assert "needs_attention" not in save.payload
    assert not any("bot disabled" in m for m in _warnings(caplog))
