"""FA-02: every Graph call that sends an access_token also sends appsecret_proof.

appsecret_proof = HMAC-SHA256(access_token, key=app secret). With "Require App
Secret" on in the Meta app, a stolen token is useless without the secret.
Graph is replaced by httpx.MockTransport (no network), as in test_graph_errors.
"""
import hashlib
import hmac
from types import SimpleNamespace

import httpx
import pytest

from app.services import facebook as fb

SECRET = "SECRET_SENTINEL_123"
TOKEN = "TOKEN_SENTINEL_456"


def expected_proof(token: str, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def make_graph(monkeypatch, secret):
    """Fake settings + Graph answering 200; `graph.params` records each query."""
    monkeypatch.setattr(fb, "get_settings", lambda: SimpleNamespace(
        fb_app_id="app-1",
        fb_app_secret=secret,
        fb_redirect_uri="https://shop.test/facebook/connect/callback",
        fb_graph_version="v21.0",
    ))
    fake = SimpleNamespace(params=[])

    def handler(request):
        fake.params.append(dict(request.url.params))
        return httpx.Response(200, json={"access_token": "new-token", "data": [], "id": "u-1"})

    transport = httpx.MockTransport(handler)

    def request(method, url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.request(method, url, **kwargs)

    monkeypatch.setattr(httpx, "request", request)
    return fake


@pytest.fixture
def graph(monkeypatch):
    return make_graph(monkeypatch, SECRET)


TOKEN_CALLS = {
    "get_user_pages": lambda: fb.get_user_pages(TOKEN),
    "get_user_id": lambda: fb.get_user_id(TOKEN),
    "subscribe_page": lambda: fb.subscribe_page("page-1", TOKEN),
    "get_page_instagram_account": lambda: fb.get_page_instagram_account("page-1", TOKEN),
    "send_text_message": lambda: fb.send_text_message(TOKEN, "psid-1", "hello"),
}


@pytest.mark.parametrize("name", list(TOKEN_CALLS))
def test_p1_token_call_sends_appsecret_proof(graph, name):
    TOKEN_CALLS[name]()
    assert len(graph.params) == 1
    sent = graph.params[0]
    assert sent["access_token"] == TOKEN
    assert sent["appsecret_proof"] == expected_proof(TOKEN)


def test_p2_code_exchange_sends_no_proof(graph):
    fb.exchange_code_for_token("code-1")
    assert len(graph.params) == 1
    assert "appsecret_proof" not in graph.params[0]
    assert "access_token" not in graph.params[0]


def test_p3_caller_params_not_mutated(graph):
    params = {"access_token": TOKEN}
    fb._graph("GET", "/me", params=params)
    assert params == {"access_token": TOKEN}
    assert graph.params[0]["appsecret_proof"] == expected_proof(TOKEN)


def test_p4_empty_secret_refuses_before_request(monkeypatch):
    make_graph(monkeypatch, "")
    calls = []
    monkeypatch.setattr(httpx, "request", lambda *a, **kw: calls.append(a))
    with pytest.raises(fb.GraphError) as caught:
        fb.send_text_message(TOKEN, "psid-1", "hello")
    err = caught.value
    assert calls == []
    assert err.status_code is None
    assert str(err) == "app secret not configured"
    for text in (str(err), repr(err)):
        assert TOKEN not in text
