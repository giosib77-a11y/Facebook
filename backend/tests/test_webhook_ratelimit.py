"""B-3: per-minute webhook limits — (shop, psid) and per-shop; excess is skipped silently."""
import logging
import time as real_time
from types import SimpleNamespace

import pytest

import app.api.webhook as webhook

PAGE_ID = "1234567890"
SHOP_ID = "22222222-2222-2222-2222-222222222222"
OTHER_PAGE_ID = "9876543210"
OTHER_SHOP_ID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def env(monkeypatch, service_db):
    db = service_db
    db.responses[("shops", "select")] = [{
        "id": SHOP_ID, "bot_enabled": True, "facebook_page_token": "enc",
        "subscription_tier": "free",
    }]
    db.responses[("products", "select")] = []
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 1}]

    sent, bot_calls = [], []
    clock = {"t": 1000.0}
    monkeypatch.setattr(webhook, "get_service_client", lambda: db)
    monkeypatch.setattr(webhook, "decrypt", lambda token: "page-token")
    monkeypatch.setattr(webhook, "send_text_message", lambda tok, psid, text: sent.append(psid))
    monkeypatch.setattr(webhook, "download_image", lambda url, timeout=8: None)
    monkeypatch.setattr(
        webhook, "time",
        SimpleNamespace(time=real_time.time, monotonic=lambda: clock["t"]),
    )

    def fake_bot_reply(shop, products, text, history, images=None):
        bot_calls.append(text)
        return "gemini reply"

    monkeypatch.setattr(webhook, "get_bot_reply", fake_bot_reply)
    return db, sent, bot_calls, clock


_mid = iter(range(10**6))


def _send(psid, page_id=PAGE_ID):
    webhook._process_events({"entry": [{
        "id": page_id,
        "messaging": [{
            "sender": {"id": psid},
            "message": {"text": "hi", "mid": f"m{next(_mid)}"},
        }],
    }]})


def test_psid_over_limit_skipped_without_gemini_or_reply(env, caplog):
    db, sent, bot_calls, _ = env
    with caplog.at_level(logging.WARNING, logger="app"):
        for _ in range(webhook._RATE_PER_PSID + 1):
            _send("psid-1")

    assert len(bot_calls) == webhook._RATE_PER_PSID
    assert len(sent) == webhook._RATE_PER_PSID
    # skipped message costs no track_bot_customer DB work
    assert len(db.rpc_calls) == webhook._RATE_PER_PSID
    assert any(SHOP_ID in r.getMessage() for r in caplog.records)


def test_other_psid_unaffected(env):
    _, _, bot_calls, _ = env
    for _ in range(webhook._RATE_PER_PSID + 1):
        _send("psid-1")
    _send("psid-2")
    assert len(bot_calls) == webhook._RATE_PER_PSID + 1


def test_shop_limit_applies_across_psids(env):
    _, _, bot_calls, _ = env
    for i in range(webhook._RATE_PER_SHOP + 5):
        _send(f"psid-{i}")
    assert len(bot_calls) == webhook._RATE_PER_SHOP


def test_other_shop_unaffected(env):
    db, _, bot_calls, _ = env
    for _ in range(webhook._RATE_PER_PSID + 1):
        _send("psid-1")
    assert len(bot_calls) == webhook._RATE_PER_PSID
    db.responses[("shops", "select")] = [{
        "id": OTHER_SHOP_ID, "bot_enabled": True, "facebook_page_token": "enc",
        "subscription_tier": "free",
    }]
    _send("psid-1", page_id=OTHER_PAGE_ID)  # same psid, different shop
    assert len(bot_calls) == webhook._RATE_PER_PSID + 1


def test_window_expiry_allows_again(env):
    _, _, bot_calls, clock = env
    for _ in range(webhook._RATE_PER_PSID + 1):
        _send("psid-1")
    assert len(bot_calls) == webhook._RATE_PER_PSID

    clock["t"] += webhook._RATE_WINDOW + 1
    _send("psid-1")
    assert len(bot_calls) == webhook._RATE_PER_PSID + 1


def test_blocked_psid_does_not_consume_shop_budget(env):
    _, _, bot_calls, _ = env
    for _ in range(webhook._RATE_PER_PSID + 20):  # 20 blocked extras
        _send("psid-1")
    for i in range(webhook._RATE_PER_SHOP - webhook._RATE_PER_PSID):
        _send(f"other-{i}")
    assert len(bot_calls) == webhook._RATE_PER_SHOP


def test_stale_keys_swept(env):
    _, _, _, clock = env
    for i in range(50):
        _send(f"psid-{i}")
    assert len(webhook._RATE_HITS) > 50
    clock["t"] += webhook._RATE_WINDOW + webhook._RATE_SWEEP_EVERY + 1
    _send("fresh")
    assert set(webhook._RATE_HITS) == {(SHOP_ID, "fresh"), (SHOP_ID,)}
