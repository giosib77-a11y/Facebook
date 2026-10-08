"""FA-12: a bot reply is never dropped silently (empty model output, platform length limits).

`_process_events` is called directly with a fake service client; Facebook and
Gemini calls are monkeypatched, so nothing leaves the process.
"""
import logging

import pytest

import app.api.webhook as webhook

PAGE_ID = "1234567890"
SHOP_ID = "22222222-2222-2222-2222-222222222222"
PSID = "psid-1"


@pytest.fixture
def env(monkeypatch, service_db):
    db = service_db
    db.responses[("shops", "select")] = [{
        "id": SHOP_ID, "bot_enabled": True, "facebook_page_token": "enc",
        "subscription_tier": "free",
    }]
    db.responses[("products", "select")] = []
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 1}]

    sent = []
    bot = {"reply": "gemini reply"}
    monkeypatch.setattr(webhook, "get_service_client", lambda: db)
    monkeypatch.setattr(webhook, "decrypt", lambda token: "page-token")
    monkeypatch.setattr(webhook, "send_text_message", lambda tok, psid, text: sent.append(text))
    monkeypatch.setattr(webhook, "download_image", lambda url, timeout=8: None)
    monkeypatch.setattr(
        webhook, "get_bot_reply",
        lambda shop, products, text, history, images=None: bot["reply"],
    )
    return db, sent, bot


def _run(obj="page"):
    webhook._process_events({"object": obj, "entry": [{
        "id": PAGE_ID,
        "messaging": [{"sender": {"id": PSID}, "message": {"text": "გამარჯობა"}}],
    }]})


def _saved(db):
    saves = db.calls_for("bot_conversations", "upsert")
    assert len(saves) == 1
    return saves[0].payload


def test_empty_reply_sends_fallback_and_flags_conversation(env, caplog):
    db, sent, bot = env
    bot["reply"] = ""

    with caplog.at_level(logging.WARNING, logger="app"):
        _run()

    assert sent == [webhook.EMPTY_REPLY_FALLBACK]
    payload = _saved(db)
    assert payload["needs_attention"] is True
    assert payload["messages"][-1] == {"role": "bot", "content": webhook.EMPTY_REPLY_FALLBACK}
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(SHOP_ID in m for m in warnings)
    assert not any(PSID in m for m in warnings)


def test_long_page_reply_is_split_into_three_parts(env):
    db, sent, bot = env
    paras = [f"{i:02d}" + "ა" * 297 for i in range(15)]
    text = "\n".join(paras) + "!"
    assert len(text) == 4500
    bot["reply"] = text

    _run("page")

    assert len(sent) == 3
    assert all(len(p) <= 1900 for p in sent)
    assert "\n".join(sent) == text  # cut on paragraph breaks, nothing lost
    assert _saved(db)["messages"][-1]["content"] == text  # full reply stored


def test_instagram_reply_respects_lower_limit(env):
    db, sent, bot = env
    text = "x" * 2000
    bot["reply"] = text

    _run("instagram")

    assert len(sent) == 3
    assert all(len(p) <= 900 for p in sent)
    assert "".join(sent) == text


def test_short_reply_is_sent_once_unchanged(env):
    db, sent, bot = env

    _run()

    assert sent == ["gemini reply"]
    assert "needs_attention" not in _saved(db)


def test_split_exact_limit_is_one_part():
    assert webhook._split_reply("a" * 1900, 1900) == ["a" * 1900]


def test_split_prefers_newline_boundary():
    text = "a" * 50 + "\n" + "b" * 80
    assert webhook._split_reply(text, 100) == ["a" * 50, "b" * 80]


def test_split_keeps_period_on_sentence_boundary():
    text = "a" * 50 + ". " + "b" * 80
    assert webhook._split_reply(text, 100) == ["a" * 50 + ".", "b" * 80]


def test_split_caps_at_three_parts_with_ellipsis():
    parts = webhook._split_reply("a" * 1000, 100)
    assert len(parts) == 3
    assert all(len(p) <= 100 for p in parts)
    assert parts[-1].endswith("…")


def test_ambiguous_ig_match_is_not_routed(env, caplog):
    db, sent, bot = env
    db.responses[("shops", "select")] = [
        {"id": SHOP_ID, "bot_enabled": True, "facebook_page_token": "enc", "subscription_tier": "free"},
        {"id": "other-shop", "bot_enabled": True, "facebook_page_token": "enc", "subscription_tier": "free"},
    ]

    with caplog.at_level(logging.ERROR, logger="app"):
        _run("instagram")

    assert sent == []
    assert db.calls_for("bot_conversations", "upsert") == []
    assert any("AMBIGUOUS ROUTE" in r.getMessage() for r in caplog.records)
