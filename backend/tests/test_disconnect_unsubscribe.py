"""A-027 (N-16): disconnect also unsubscribes the app from the page (DELETE /{page_id}/subscribed_apps)."""
import hashlib
import hmac
import logging
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet

import app.core.crypto as crypto
import app.services.facebook as fb
from app.services.facebook import GraphError

SHOP_ID = "22222222-2222-2222-2222-222222222222"
PAGE_ID = "9876543210"
PAGE_TOKEN = "EAAB-plain-page-token-xyz"


@pytest.fixture(autouse=True)
def _crypto_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto, "get_settings", lambda: SimpleNamespace(fb_token_encryption_key=key))


@pytest.fixture
def graph(monkeypatch):
    """Records every Graph call made through services.facebook._graph."""
    calls = []

    def fake(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return httpx.Response(200, json={"success": True})

    monkeypatch.setattr(fb, "_graph", fake)
    return calls


def _connected(user_db, service_db, token=None):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    service_db.responses[("shops", "select")] = [
        {"facebook_page_id": PAGE_ID, "facebook_page_token": crypto.encrypt(PAGE_TOKEN) if token is None else token}
    ]
    service_db.responses[("shops", "update")] = [{"id": SHOP_ID}]


def _disconnect(client):
    return client.post("/facebook/disconnect", params={"shop_id": SHOP_ID})


def test_unsubscribe_page_sends_delete_with_appsecret_proof(monkeypatch):
    monkeypatch.setattr(fb, "get_settings", lambda: SimpleNamespace(fb_app_secret="s3cret", fb_graph_version="v99.0"))
    seen = {}

    def fake_request(method, url, **kwargs):
        seen.update(method=method, url=url, kwargs=kwargs)
        return httpx.Response(200, json={"success": True})

    monkeypatch.setattr(fb.httpx, "request", fake_request)
    fb.unsubscribe_page(PAGE_ID, PAGE_TOKEN)
    assert seen["method"] == "DELETE"
    assert seen["url"] == f"https://graph.facebook.com/v99.0/{PAGE_ID}/subscribed_apps"
    params = seen["kwargs"]["params"]
    assert params["access_token"] == PAGE_TOKEN
    assert params["appsecret_proof"] == hmac.new(b"s3cret", PAGE_TOKEN.encode(), hashlib.sha256).hexdigest()
    assert seen["kwargs"]["timeout"] == 15


def test_disconnect_unsubscribes_then_clears_row(client, user_db, service_db, graph):
    _connected(user_db, service_db)
    r = _disconnect(client)
    assert r.status_code == 200 and r.json() == {"status": "disconnected"}

    assert len(graph) == 1
    method, path, kwargs = graph[0]
    assert (method, path) == ("DELETE", f"/{PAGE_ID}/subscribed_apps")
    assert kwargs["params"] == {"access_token": PAGE_TOKEN}  # decrypted token

    # the lookup is scoped to the owner, and the row is cleared afterwards
    sel = service_db.calls_for("shops", "select")[0]
    assert ("eq", "id", SHOP_ID) in sel.filters and ("eq", "owner_id", "11111111-1111-1111-1111-111111111111") in sel.filters
    (upd,) = service_db.calls_for("shops", "update")
    assert upd.payload["facebook_page_token"] is None and upd.payload["bot_enabled"] is False
    assert service_db.calls.index(sel) < service_db.calls.index(upd)


@pytest.mark.parametrize("exc", [GraphError(400, "Invalid token"), GraphError(None, "network error")])
def test_graph_failure_still_disconnects_and_does_not_log_token(client, user_db, service_db, monkeypatch, caplog, exc):
    _connected(user_db, service_db)

    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(fb, "_graph", boom)
    with caplog.at_level(logging.WARNING, logger="app"):
        r = _disconnect(client)
    assert r.status_code == 200
    assert len(service_db.calls_for("shops", "update")) == 1
    warnings = [x for x in caplog.records if x.levelno == logging.WARNING and "unsubscribe on disconnect failed" in x.getMessage()]
    assert len(warnings) == 1
    assert PAGE_TOKEN not in caplog.text and PAGE_ID not in caplog.text


def test_decrypt_failure_still_disconnects_without_graph_call(client, user_db, service_db, graph, caplog):
    _connected(user_db, service_db, token="not-a-valid-fernet-token")
    with caplog.at_level(logging.WARNING, logger="app"):
        r = _disconnect(client)
    assert r.status_code == 200
    assert graph == []
    assert len(service_db.calls_for("shops", "update")) == 1
    assert "unsubscribe on disconnect failed" in caplog.text
    assert "not-a-valid-fernet-token" not in caplog.text


@pytest.mark.parametrize("row", [
    {"facebook_page_id": None, "facebook_page_token": None},
    {"facebook_page_id": PAGE_ID, "facebook_page_token": None},
    {"facebook_page_id": None, "facebook_page_token": "x"},
])
def test_shop_without_page_makes_no_graph_call(client, user_db, service_db, graph, row):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    service_db.responses[("shops", "select")] = [row]
    service_db.responses[("shops", "update")] = [{"id": SHOP_ID}]
    r = _disconnect(client)
    assert r.status_code == 200
    assert graph == []
    assert len(service_db.calls_for("shops", "update")) == 1


def test_foreign_shop_is_404_and_makes_no_graph_call(client, user_db, service_db, graph):
    user_db.responses[("shops", "select")] = []  # RLS: not the owner's shop
    r = _disconnect(client)
    assert r.status_code == 404
    assert graph == []
    assert service_db.calls == []
