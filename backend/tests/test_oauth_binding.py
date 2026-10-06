"""FA-05: the Facebook OAuth callback only completes in the browser that started it.

connect_start puts a random nonce both into the signed state and into an
HttpOnly cookie; in production the callback requires the two to match, so a
stolen or planted callback URL cannot attach a page to someone else's shop.
Graph calls are replaced by fakes (no network).
"""
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

import app.api.facebook as fb_api
from app.services import facebook as fb
from tests.conftest import USER_ID

SHOP_ID = "22222222-2222-2222-2222-222222222222"
COOKIE = "fb_oauth_nonce"


@pytest.fixture
def oauth(monkeypatch):
    """Fake FB settings, a fake login URL that echoes the state, and fake Graph calls.

    `oauth.exchanges` records every token exchange, so a test can tell whether
    the callback got past the nonce check.
    """
    monkeypatch.setattr(fb, "get_settings", lambda: SimpleNamespace(fb_app_secret="state-secret"))
    monkeypatch.setattr(fb, "build_login_url", lambda state: "https://fb.test/login?state=" + state)
    fake = SimpleNamespace(exchanges=[])

    def exchange(code):
        fake.exchanges.append(code)
        return "user-token"

    monkeypatch.setattr(fb, "exchange_code_for_token", exchange)
    monkeypatch.setattr(fb, "exchange_for_long_lived", lambda token: token)
    monkeypatch.setattr(
        fb, "get_user_pages", lambda token: [{"id": "page-1", "access_token": "page-token", "name": "Page"}]
    )
    monkeypatch.setattr(fb, "subscribe_page", lambda page_id, token: None)
    monkeypatch.setattr(fb, "get_page_instagram_account", lambda page_id, token: None)
    monkeypatch.setattr(fb, "get_user_id", lambda token: "fb-user-1")
    monkeypatch.setattr(fb_api, "encrypt", lambda value: "enc:" + value)
    return fake


def set_env(monkeypatch, app_env):
    real = fb_api.get_settings()
    patched = real.model_copy(update={"app_env": app_env})
    monkeypatch.setattr(fb_api, "get_settings", lambda: patched)


@pytest.fixture
def production(monkeypatch):
    set_env(monkeypatch, "production")


def signed_state(nonce="nonce-abc"):
    return fb.sign_state({"shop_id": SHOP_ID, "user_id": USER_ID, "ts": time.time(), "n": nonce})


def callback(client, nonce_cookie=None, **params):
    headers = {"Cookie": f"{COOKIE}={nonce_cookie}"} if nonce_cookie is not None else {}
    return client.get("/facebook/connect/callback", params=params, headers=headers)


def nonce_set_cookies(res):
    return [h for h in res.headers.get_list("set-cookie") if h.startswith(COOKIE + "=")]


def assert_nonce_deleted(res):
    cookies = nonce_set_cookies(res)
    assert len(cookies) == 1, cookies
    attrs = [a.strip().lower() for a in cookies[0].split(";")]
    assert "max-age=0" in attrs
    assert "path=/facebook/connect" in attrs


def test_b1_start_sets_nonce_cookie_matching_state(oauth, production, client, user_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    res = client.get("/facebook/connect/start", params={"shop_id": SHOP_ID})
    assert res.status_code == 200
    assert set(res.json()) == {"login_url"}

    cookies = nonce_set_cookies(res)
    assert len(cookies) == 1, cookies
    name_value, *attrs = [a.strip() for a in cookies[0].split(";")]
    nonce = name_value.split("=", 1)[1]
    lowered = [a.lower() for a in attrs]
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/facebook/connect" in lowered
    assert "max-age=600" in lowered
    assert "secure" in lowered

    state = parse_qs(urlparse(res.json()["login_url"]).query)["state"][0]
    data = fb.verify_state(state)
    assert data["n"] == nonce
    assert len(nonce) >= 16


def test_b2_valid_state_without_cookie_is_rejected(oauth, production, client):
    res = callback(client, code="code-1", state=signed_state())
    assert "invalid_state" in res.text
    assert oauth.exchanges == []


def test_b3_valid_state_with_other_cookie_is_rejected(oauth, production, client):
    res = callback(client, nonce_cookie="someone-elses-nonce", code="code-1", state=signed_state())
    assert "invalid_state" in res.text
    assert oauth.exchanges == []


def test_b4_matching_cookie_passes_the_check(oauth, production, client, service_db):
    service_db.responses[("shops", "update")] = [{"id": SHOP_ID}]
    res = callback(client, nonce_cookie="nonce-abc", code="code-1", state=signed_state("nonce-abc"))
    assert oauth.exchanges == ["code-1"]
    assert "invalid_state" not in res.text
    assert '"connected"' in res.text


@pytest.mark.parametrize(
    "case",
    ["fb_denied", "missing_code", "bad_state", "no_cookie", "other_cookie", "graph_failed", "connected"],
)
def test_b5_every_callback_response_deletes_nonce(case, oauth, production, client, service_db, monkeypatch):
    service_db.responses[("shops", "update")] = [{"id": SHOP_ID}]
    if case == "graph_failed":
        def fail(code):
            raise RuntimeError("boom")
        monkeypatch.setattr(fb, "exchange_code_for_token", fail)
    good = {"nonce_cookie": "nonce-abc", "code": "code-1", "state": signed_state("nonce-abc")}
    kwargs = {
        "fb_denied": {"nonce_cookie": "nonce-abc", "error": "access_denied"},
        "missing_code": {"nonce_cookie": "nonce-abc", "state": signed_state("nonce-abc")},
        "bad_state": {**good, "state": "garbage.sig"},
        "no_cookie": {**good, "nonce_cookie": None},
        "other_cookie": {**good, "nonce_cookie": "other"},
        "graph_failed": good,
        "connected": good,
    }[case]
    expected = {
        "fb_denied": "fb_denied",
        "missing_code": "missing_code",
        "bad_state": "invalid_state",
        "no_cookie": "invalid_state",
        "other_cookie": "invalid_state",
        "graph_failed": "graph_failed",
        "connected": '"connected"',
    }[case]
    res = callback(client, **kwargs)
    assert expected in res.text
    assert_nonce_deleted(res)


def test_b6_outside_production_missing_cookie_does_not_block(oauth, client, service_db, monkeypatch):
    set_env(monkeypatch, "development")
    service_db.responses[("shops", "update")] = [{"id": SHOP_ID}]
    res = callback(client, code="code-1", state=signed_state())
    assert "invalid_state" not in res.text
    assert oauth.exchanges == ["code-1"]
