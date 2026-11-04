"""A-038 (N-07): GET /shops/{id}/usage exposes `email_notifications`; FB connect clears the bot health status.

Offline: FakeSupabase from conftest; Graph helpers stubbed (same pattern as test_facebook_connect.py).
"""
import logging

import pytest

import app.api.facebook as fb_api
from app.config import get_settings
from tests.conftest import USER_ID

SHOP = "aaaaaaaa-0000-0000-0000-000000000001"
SHOP_ID = "22222222-2222-2222-2222-222222222222"
SMTP_FULL = {
    "smtp_host": "smtp.example.test",
    "smtp_user": "smtp-user",
    "smtp_password": "smtp-secret-pass",
    "notify_email_from": "bot@example.test",
}


# ---- GET /shops/{id}/usage ---------------------------------------------------
def _usage(client, user_db):
    user_db.responses[("shops", "select")] = [{"subscription_tier": "free"}]
    r = client.get(f"/shops/{SHOP}/usage")
    assert r.status_code == 200, r.text
    return r.json()


def test_usage_email_notifications_false_by_default(client, user_db):
    assert _usage(client, user_db)["email_notifications"] is False


def test_usage_email_notifications_true_when_smtp_configured(client, user_db, monkeypatch):
    s = get_settings().model_copy(update=SMTP_FULL)
    monkeypatch.setattr("app.api.shops.get_settings", lambda: s)
    body = _usage(client, user_db)
    assert body["email_notifications"] is True
    assert "smtp-secret-pass" not in str(body)  # only the flag, never the config


@pytest.mark.parametrize("missing", list(SMTP_FULL))
def test_usage_email_notifications_false_when_any_setting_missing(client, user_db, monkeypatch, missing):
    s = get_settings().model_copy(update={**SMTP_FULL, missing: ""})
    monkeypatch.setattr("app.api.shops.get_settings", lambda: s)
    assert _usage(client, user_db)["email_notifications"] is False


# ---- GET /facebook/connect/callback -----------------------------------------
@pytest.fixture
def fake_graph(monkeypatch):
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


def _connect(client, service_db):
    service_db.responses[("shops", "select")] = [
        {"id": SHOP_ID, "subscription_tier": "free", "bot_enabled": False}
    ]
    service_db.responses[("shops", "update")] = [{"id": SHOP_ID}]
    return client.get("/facebook/connect/callback", params={"code": "c", "state": "s"})


def _reset_updates(db):
    return [u for u in db.calls_for("shops", "update") if "bot_status" in (u.payload or {})]


def test_connect_success_clears_bot_status_after_saving_the_page(client, service_db, fake_graph):
    res = _connect(client, service_db)
    assert '"fb": "connected"' in res.text
    updates = service_db.calls_for("shops", "update")
    assert len(updates) == 2
    assert "facebook_page_id" in updates[0].payload and "bot_status" not in updates[0].payload
    (reset,) = _reset_updates(service_db)
    assert reset is updates[1]  # after the successful save
    assert reset.payload == {"bot_status": None, "bot_status_at": None}
    assert ("eq", "id", SHOP_ID) in reset.filters
    assert ("eq", "owner_id", USER_ID) in reset.filters  # ownership is in the query itself


def test_connect_reset_failure_still_connected_and_logged(client, service_db, fake_graph, monkeypatch, caplog):
    # conftest is loaded as a top-level module by pytest: take the class the fake DB really uses
    FakeQuery = type(service_db.table("shops"))
    real_execute = FakeQuery.execute

    def execute(self):
        if self.op == "update" and "bot_status" in (self.payload or {}):
            self._db.calls.append(self)
            raise RuntimeError("column bot_status does not exist: secret-detail")
        return real_execute(self)

    monkeypatch.setattr(FakeQuery, "execute", execute)
    with caplog.at_level(logging.WARNING, logger="app"):
        res = _connect(client, service_db)
    assert '"fb": "connected"' in res.text
    assert "error" not in res.text
    assert len(_reset_updates(service_db)) == 1  # it was attempted
    # 0036 missing must not push the page save into the 0006/0011 fallback (which drops facebook_user_id)
    (save,) = [u for u in service_db.calls_for("shops", "update") if "facebook_page_id" in u.payload]
    assert save.payload["facebook_user_id"] == "fb-user-1" and "bot_status" not in save.payload
    warnings = [r.getMessage() for r in caplog.records if "bot_status reset failed" in r.getMessage()]
    assert len(warnings) == 1
    assert SHOP_ID in warnings[0] and "RuntimeError" in warnings[0]
    assert "secret-detail" not in caplog.text and "page-token" not in caplog.text


@pytest.mark.parametrize("data", [[], None])
def test_connect_shop_not_found_does_not_reset_status(client, service_db, fake_graph, data):
    service_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "free", "bot_enabled": False}]
    service_db.responses[("shops", "update")] = data
    res = client.get("/facebook/connect/callback", params={"code": "c", "state": "s"})
    assert '"reason": "shop_not_found"' in res.text
    assert _reset_updates(service_db) == []
