"""F-10: a failed Graph API call must never expose the app secret or a token.

httpx errors embed the full request URL, query string included — so the old
`r.raise_for_status()` put client_secret (or a page token) into the exception
text, and the OAuth callback sent that text to the browser. Graph is replaced
by httpx.MockTransport (no network).

X1/X2: no value may break out of the callback page's inline <script> — it runs
on the panel's origin, where the session token lives.
"""
import json
import time
from types import SimpleNamespace

import httpx
import pytest

import app.api.facebook as fb_api
from app.services import facebook as fb
from tests.conftest import USER_ID

SECRET = "SECRET_SENTINEL_123"
TOKEN = "TOKEN_SENTINEL_456"
SHOP_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def graph(monkeypatch):
    """Fake settings + every Graph call answered by `graph.reply(request)`.

    `graph.urls` records each request URL, so a test can first show the
    sentinel really was sent — otherwise "not leaked" would pass vacuously.
    """
    monkeypatch.setattr(fb, "get_settings", lambda: SimpleNamespace(
        fb_app_id="app-1",
        fb_app_secret=SECRET,
        fb_redirect_uri="https://shop.test/facebook/connect/callback",
        fb_graph_version="v21.0",
    ))
    fake = SimpleNamespace(urls=[], reply=None)

    def handler(request):
        fake.urls.append(str(request.url))
        return fake.reply(request)

    transport = httpx.MockTransport(handler)

    def request(method, url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.request(method, url, **kwargs)

    monkeypatch.setattr(httpx, "request", request)
    return fake


def graph_400(message):
    """A 400 with Graph's usual error body."""
    return lambda request: httpx.Response(
        400, json={"error": {"message": message, "type": "OAuthException", "code": 100}}
    )


def test_g1_token_exchange_error_hides_app_secret(graph):
    graph.reply = graph_400("Invalid verification code format.")
    # deliberately broad: the leak checks must run whatever was raised
    with pytest.raises(Exception) as caught:
        fb.exchange_code_for_token("bogus-code")
    err = caught.value
    assert SECRET in graph.urls[0]
    for text in (str(err), repr(err)):
        assert SECRET not in text
        assert "client_secret" not in text
    assert isinstance(err, fb.GraphError)
    assert err.status_code == 400
    assert str(err) == "Invalid verification code format."
    assert err.__suppress_context__ is True


def test_g2_callback_returns_fixed_reason_not_error_text(graph, client):
    graph.reply = graph_400("Invalid verification code format.")
    state = fb.sign_state({"shop_id": SHOP_ID, "user_id": USER_ID, "ts": time.time()})
    res = client.get("/facebook/connect/callback", params={"code": "bogus", "state": state})
    assert SECRET in graph.urls[0]  # state was valid, the exchange really ran
    assert res.status_code == 200
    assert SECRET not in res.text
    assert "client_secret" not in res.text
    assert "graph_failed" in res.text


def test_g3_send_message_error_hides_page_token(graph):
    graph.reply = graph_400("(#100) No matching user found")
    with pytest.raises(Exception) as caught:
        fb.send_text_message(TOKEN, "psid-1", "hello")
    err = caught.value
    assert TOKEN in graph.urls[0]
    for text in (str(err), repr(err)):
        assert TOKEN not in text
        assert "access_token" not in text
    assert isinstance(err, fb.GraphError)
    assert err.status_code == 400


def test_g4_network_error_hides_url(graph):
    def refuse(request):
        # the message carries the URL, so the test proves it is dropped
        raise httpx.ConnectError(f"connection refused: {request.url}", request=request)

    graph.reply = refuse
    with pytest.raises(fb.GraphError) as caught:
        fb.exchange_code_for_token("code")
    err = caught.value
    assert SECRET in graph.urls[0]
    for text in (str(err), repr(err)):
        assert "graph.facebook.com" not in text
        assert SECRET not in text
    assert err.status_code is None
    assert err.__suppress_context__ is True


def test_x1_callback_never_reflects_error_param(client):
    res = client.get(
        "/facebook/connect/callback", params={"error": "</script><script>alert(1)</script>"}
    )
    body = res.text
    assert "alert(1)" not in body
    assert "<script>alert" not in body
    assert body.count("</script>") == 1  # only the page's own closing tag
    assert "fb_denied" in body


def test_x2_finish_escapes_values_inside_script():
    reason = "</script><img src=x onerror=alert(1)>"
    body = fb_api._finish("error", reason=reason).body.decode()
    assert body.count("</script>") == 1
    assert "<img" not in body
    # escaping is lossless: the panel still receives the exact payload
    msg = body.split("var msg=", 1)[1].split(";var origins=", 1)[0]
    assert json.loads(msg) == {"fb": "error", "reason": reason}
