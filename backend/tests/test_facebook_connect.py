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
    reads = service_db.calls_for("shops", "select")
    assert len(reads) == 1
    assert ("eq", "owner_id", USER_ID) in reads[0].filters


def test_c5_connect_nulls_ig_id_on_other_shops_first(client, service_db):
    _connect(client, service_db, [{"id": SHOP_ID, "subscription_tier": "free", "bot_enabled": False}])
    updates = service_db.calls_for("shops", "update")
    assert len(updates) == 2
    clear, save = updates
    assert clear.payload == {"instagram_account_id": None}
    assert ("eq", "instagram_account_id", "ig-1") in clear.filters
    assert ("neq", "id", SHOP_ID) in clear.filters
    assert "facebook_page_id" in save.payload


def test_c6_ig_clear_failure_aborts_without_saving(client, service_db):
    service_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "free", "bot_enabled": False}]
    service_db.errors[("shops", "update")] = RuntimeError("db down")
    res = client.get("/facebook/connect/callback", params={"code": "c", "state": "s"})
    assert '"reason": "save_failed"' in res.text
    assert not any("facebook_page_id" in u.payload for u in service_db.calls_for("shops", "update"))
