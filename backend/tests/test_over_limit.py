"""FA-11: over the monthly customer limit, keep serving already-counted customers.

`_process_events` is called directly with a fake service client; Facebook and
Gemini calls are monkeypatched, so nothing leaves the process.
"""
import logging

import pytest

import app.api.webhook as webhook

AUTO_REPLY = "მადლობა შეტყობინებისთვის! 🙏 ჩვენი ოპერატორი მალე დაგიკავშირდებათ."
PAGE_ID = "1234567890"
SHOP_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def env(monkeypatch, service_db):
    db = service_db
    db.responses[("shops", "select")] = [{
        "id": SHOP_ID, "bot_enabled": True, "facebook_page_token": "enc",
        "subscription_tier": "free",  # 30 customers
    }]
    db.responses[("products", "select")] = []
    db.responses[("bot_customers", "select")] = [{"created_at": "2026-10-01T10:00:00+00:00"}]

    sent, bot_calls = [], []
    monkeypatch.setattr(webhook, "get_service_client", lambda: db)
    monkeypatch.setattr(webhook, "decrypt", lambda token: "page-token")
    monkeypatch.setattr(webhook, "send_text_message", lambda tok, psid, text: sent.append(text))
    monkeypatch.setattr(webhook, "download_image", lambda url, timeout=8: None)

    def fake_bot_reply(shop, products, text, history, images=None):
        bot_calls.append(text)
        return "gemini reply"

    monkeypatch.setattr(webhook, "get_bot_reply", fake_bot_reply)
    return db, sent, bot_calls


def _run(db, monthly):
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": monthly, "day_count": 1}]
    webhook._process_events({"entry": [{
        "id": PAGE_ID,
        "messaging": [{"sender": {"id": "psid-1"}, "message": {"text": "გამარჯობა"}}],
    }]})


def _rank_queries(db):
    return db.calls_for("bot_customers", "select")


def test_early_customer_still_served_when_shop_over_limit(env):
    db, sent, bot_calls = env
    db.counts[("bot_customers", "select")] = 4  # 4 earlier customers → rank 5

    _run(db, monthly=31)

    assert bot_calls == ["გამარჯობა"]
    assert sent == ["gemini reply"]
    assert AUTO_REPLY not in sent
    count_q = _rank_queries(db)[1]
    assert ("lt", "created_at", "2026-10-01T10:00:00+00:00") in count_q.filters


def test_customer_past_limit_gets_auto_reply_and_is_flagged(env):
    db, sent, bot_calls = env
    db.counts[("bot_customers", "select")] = 30  # rank 31

    _run(db, monthly=31)

    assert sent == [AUTO_REPLY]
    assert bot_calls == []
    saves = db.calls_for("bot_conversations", "upsert")
    assert len(saves) == 1
    payload = saves[0].payload
    assert payload["needs_attention"] is True
    assert payload["psid"] == "psid-1"
    assert payload["messages"][-2:] == [
        {"role": "user", "content": "გამარჯობა"},
        {"role": "bot", "content": AUTO_REPLY},
    ]


def test_rank_query_failure_falls_back_to_old_rule(env, caplog):
    db, sent, bot_calls = env
    db.errors[("bot_customers", "select")] = RuntimeError("db down")

    with caplog.at_level(logging.WARNING, logger="app"):
        _run(db, monthly=31)

    assert sent == [AUTO_REPLY]
    assert bot_calls == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.exc_info]
    assert any(SHOP_ID in r.getMessage() for r in warnings)


def test_rank_not_queried_within_limit(env):
    db, sent, bot_calls = env

    _run(db, monthly=30)

    assert _rank_queries(db) == []
    assert sent == ["gemini reply"]
