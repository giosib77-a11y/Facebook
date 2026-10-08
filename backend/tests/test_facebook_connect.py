"""F-05: Facebook connect must not re-enable the bot beyond the owner's tier limit."""
import pytest

import app.api.facebook as fb_api
from tests.conftest import USER_ID

SHOP_ID = "22222222-2222-2222-2222-222222222222"
OTHER_SHOP = "33333333-3333-3333-3333-333333333333"
THIRD_SHOP = "44444444-4444-4444-4444-444444444444"


@pytest.fixture(autouse=True)
def fake_graph(monkeypatch):
    """No network: stub every Graph helper connect_callback touches."""
    fb = fb_api.fb
    monkeypatch.setattr(fb, "verify_state", lambda s: {"shop_id": SHOP_ID, "user_id": USER_ID})
    monkeypatch.setattr(fb, "exchange_code_for_token", lambda code: "short-token")
    monkeypatch.setattr(fb, "exchange_for_long_lived", lambda t: "long-token")
    monkeypatch.setattr(
        fb, "get_user_pages", lambda t: [{"id": "page-1", "access_token": "page-token", "name": "My Page"}]
    )
    monkeypatch.setattr(fb, "subscribe_page", lambda page_id, token: None)
    monkeypatch.setattr(fb, "get_page_instagram_account", lambda page_id, token: "ig-1")
    monkeypatch.setattr(fb, "get_user_id", lambda t: "fb-user-1")
    monkeypatch.setattr(fb_api, "encrypt", lambda v: "enc:" + v)


def _connect(client, service_db, owned):
    service_db.responses[("shops", "select")] = owned
    service_db.responses[("shops", "update")] = [{"id": SHOP_ID}]
    res = client.get("/facebook/connect/callback", params={"code": "c", "state": "s"})
    assert res.status_code == 200
    updates = [u for u in service_db.calls_for("shops", "update") if "facebook_page_id" in u.payload]
    assert len(updates) == 1
    return res.text, updates[0].payload


def test_c1_free_owner_with_other_active_shop_keeps_bot_off(client, service_db):
    text, saved = _connect(client, service_db, [
        {"id": SHOP_ID, "subscription_tier": "free", "bot_enabled": False},
        {"id": OTHER_SHOP, "subscription_tier": "free", "bot_enabled": True},
    ])
    assert saved["bot_enabled"] is False
    assert saved["facebook_page_id"] == "page-1"
    assert saved["facebook_page_token"] == "enc:page-token"
    assert saved["instagram_account_id"] == "ig-1"
    assert saved["facebook_user_id"] == "fb-user-1"
    assert '"fb": "connected"' in text
    assert '"bot": "limit"' in text


def test_c2_free_owner_without_other_active_shop_enables_bot(client, service_db):
    text, saved = _connect(client, service_db, [
        {"id": SHOP_ID, "subscription_tier": "free", "bot_enabled": False},
        {"id": OTHER_SHOP, "subscription_tier": "free", "bot_enabled": False},
    ])
    assert saved["bot_enabled"] is True
    assert '"fb": "connected"' in text
    assert '"bot"' not in text


def test_c3_business_owner_is_unlimited(client, service_db):
    text, saved = _connect(client, service_db, [
        {"id": SHOP_ID, "subscription_tier": "business", "bot_enabled": False},
        {"id": OTHER_SHOP, "subscription_tier": "business", "bot_enabled": True},
        {"id": THIRD_SHOP, "subscription_tier": "business", "bot_enabled": True},
    ])
    assert saved["bot_enabled"] is True
    assert '"bot"' not in text


def test_c4_shops_read_is_filtered_by_state_owner(client, service_db):
    _connect(client, service_db, [{"id": SHOP_ID, "subscription_tier": "free", "bot_enabled": False}])
    reads = [r for r in service_db.calls_for("shops", "select") if ("eq", "owner_id", USER_ID) in r.filters]
    assert len(reads) == 1
    assert ("eq", "owner_id", USER_ID) in reads[0].filters


def _callback(client):
    return client.get("/facebook/connect/callback", params={"code": "c", "state": "s"})


def test_c5_ig_owned_by_other_shop_is_refused_without_changes(client, service_db):
    service_db.responses[("shops", "select")] = [
        {"id": OTHER_SHOP, "instagram_account_id": "ig-1", "subscription_tier": "free", "bot_enabled": False},
    ]
    res = _callback(client)
    assert '"reason": "ig_taken"' in res.text
    assert OTHER_SHOP not in res.text
    assert service_db.calls_for("shops", "update") == []
    checks = [c for c in service_db.calls_for("shops", "select") if ("eq", "instagram_account_id", "ig-1") in c.filters]
    assert len(checks) == 1
    assert ("neq", "id", SHOP_ID) in checks[0].filters


def test_c5b_same_shop_reconnect_with_its_own_ig_id_works(client, service_db):
    # the neq filter excludes this shop, so the DB returns no other holder
    text, saved = _connect(client, service_db, [{"id": SHOP_ID, "subscription_tier": "free", "bot_enabled": False}])
    assert saved["instagram_account_id"] == "ig-1"
    assert '"fb": "connected"' in text
    assert len(service_db.calls_for("shops", "update")) == 1


def test_c5c_no_ig_account_skips_check_and_saves(client, service_db, monkeypatch):
    monkeypatch.setattr(fb_api.fb, "get_page_instagram_account", lambda page_id, token: None)
    text, saved = _connect(client, service_db, [{"id": SHOP_ID, "subscription_tier": "free", "bot_enabled": False}])
    assert saved["instagram_account_id"] is None
    assert '"fb": "connected"' in text
    assert not any(("eq", "instagram_account_id", None) in c.filters for c in service_db.calls_for("shops", "select"))


def test_c6_ig_check_failure_aborts_without_saving(client, service_db):
    service_db.errors[("shops", "select")] = RuntimeError("db down")
    res = _callback(client)
    assert '"reason": "save_failed"' in res.text
    assert service_db.calls_for("shops", "update") == []
