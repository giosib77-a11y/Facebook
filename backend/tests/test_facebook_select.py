"""A-045 (N-09): >=2 pages -> callback returns `fb: "choose"` (no side effects), then
`POST /facebook/connect/select` connects the page the seller picked."""
import json
import logging
import re
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import app.api.facebook as fb_api
import app.core.crypto as crypto
from app.main import app as fastapi_app
from app.services import fb_selection
from tests.conftest import USER_ID

SHOP_ID = "22222222-2222-2222-2222-222222222222"
OTHER_USER = "99999999-9999-9999-9999-999999999999"
USER_TOKEN = "long-token-SECRET-xyz"
SELECT_URL = "/facebook/connect/select"

CHOOSE_INVALID = "გვერდის არჩევანი არასწორია — დააჭირე „დაკავშირებას“ ხელახლა."
CHOOSE_EXPIRED = "არჩევანს ვადა გაუვიდა (10 წუთი) — დააჭირე „დაკავშირებას“ ხელახლა."
NOT_IN_SELECTION = "ეს გვერდი არჩევანში არ არის"


def _page(n, name=None):
    return {"id": str(100 + n), "access_token": f"page-token-{n}", "name": name or f"Page {n}"}


class Graph:
    """Recorder for the stubbed Graph helpers."""

    def __init__(self):
        self.pages = [_page(0), _page(1)]
        self.user_pages_calls: list[str] = []
        self.subscribed: list[tuple[str, str]] = []
        self.encrypted: list[str] = []
        self.pages_error: Exception | None = None


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    s = SimpleNamespace(fb_app_secret="select-test-secret")
    monkeypatch.setattr(crypto, "get_settings", lambda: s)


@pytest.fixture(autouse=True)
def graph(monkeypatch):
    g = Graph()
    fb = fb_api.fb
    monkeypatch.setattr(fb, "verify_state", lambda s: {"shop_id": SHOP_ID, "user_id": USER_ID})
    monkeypatch.setattr(fb, "exchange_code_for_token", lambda code: "short-token")
    monkeypatch.setattr(fb, "exchange_for_long_lived", lambda t: USER_TOKEN)

    def get_user_pages(token):
        g.user_pages_calls.append(token)
        if g.pages_error:
            raise g.pages_error
        return list(g.pages)

    monkeypatch.setattr(fb, "get_user_pages", get_user_pages)
    monkeypatch.setattr(fb, "subscribe_page", lambda pid, tok: g.subscribed.append((pid, tok)))
    monkeypatch.setattr(fb, "get_page_instagram_account", lambda pid, tok: None)
    monkeypatch.setattr(fb, "get_user_id", lambda t: "fb-user-1")
    monkeypatch.setattr(fb_api, "encrypt", lambda v: g.encrypted.append(v) or "enc:" + v)
    return g


@pytest.fixture
def shop_db(user_db, service_db):
    """The seller owns SHOP_ID (RLS read via user_db); service_db answers the connect writes."""
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    service_db.responses[("shops", "select")] = [
        {"id": SHOP_ID, "subscription_tier": "free", "bot_enabled": False}
    ]
    service_db.responses[("shops", "update")] = [{"id": SHOP_ID}]
    return service_db


def _token(page_ids=("101", "102"), user_id=USER_ID, shop_id=SHOP_ID) -> str:
    return fb_selection.make(user_id, shop_id, USER_TOKEN, list(page_ids))


def _select(client, selection=None, page_id="102"):
    return client.post(
        SELECT_URL, json={"selection": selection if selection is not None else _token(), "page_id": page_id}
    )


def _callback(client):
    return client.get("/facebook/connect/callback", params={"code": "c", "state": "s"})


def _message(html: str) -> dict:
    """The object the callback page postMessage()s to the panel."""
    m = re.search(r"var msg=(.*?);var origins=", html, re.S)
    assert m, html
    return json.loads(m.group(1))


def _fallback_query(html: str) -> dict:
    m = re.search(r"window\.location\.replace\((\".*?\")\)", html, re.S)
    assert m, html
    return {k: v[0] for k, v in parse_qs(urlparse(json.loads(m.group(1))).query).items()}


def _page_updates(db):
    return [u for u in db.calls_for("shops", "update") if "facebook_page_id" in u.payload]


# --- callback: >=2 pages -> choose ---------------------------------------------------------------

def test_callback_two_pages_returns_choose(client, service_db, graph):
    res = _callback(client)
    assert res.status_code == 200
    assert '"fb": "choose"' in res.text
    msg = _message(res.text)
    assert msg["fb"] == "choose"
    assert json.loads(msg["pages"]) == [{"id": "100", "name": "Page 0"}, {"id": "101", "name": "Page 1"}]
    # the selection token is valid for this seller and lists the same pages
    assert fb_selection.read(msg["selection"], USER_ID)["pages"] == ["100", "101"]
    # neither the FB user token nor any page token reaches the browser
    assert USER_TOKEN not in res.text and "long-token" not in res.text
    assert "page-token" not in res.text
    # no side effects
    assert graph.subscribed == [] and graph.encrypted == []
    assert service_db.calls_for("shops", "update") == []
    assert service_db.calls_for("shops", "insert") == []
    assert service_db.calls_for("shops", "select") == []


def test_callback_choose_fallback_carries_same_fields(client, graph):
    graph.pages = [_page(0, 'A "q" & <b> ü'), _page(1)]
    html = _callback(client).text
    msg, query = _message(html), _fallback_query(html)
    assert query == msg
    assert json.loads(query["pages"])[0]["name"] == 'A "q" & <b> ü'


def test_callback_caps_at_25_pages_and_trims_names(client, graph):
    graph.pages = [_page(i, "N" * 80 if i == 0 else None) for i in range(30)]
    msg = _message(_callback(client).text)
    listed = json.loads(msg["pages"])
    assert len(listed) == 25
    assert listed[0]["name"] == "N" * 50
    assert [p["id"] for p in listed] == [str(100 + i) for i in range(25)]
    assert fb_selection.read(msg["selection"], USER_ID)["pages"] == [p["id"] for p in listed]


def test_callback_page_name_cannot_break_out_of_html(client, graph):
    evil = '</script><script>alert(1)</script>"\';</script>'
    graph.pages = [_page(0, evil), _page(1, "x y")]
    res = _callback(client)
    html = res.text
    assert "<script>alert(1)" not in html and "</script><script" not in html
    assert html.count("<script") == 1 and html.count("</script>") == 1
    assert "alert(1)</script>" not in html
    # the data itself is intact once decoded
    assert json.loads(_message(html)["pages"])[0]["name"] == evil[:50]
    # inline script is still covered by the per-response nonce CSP
    nonce = re.search(r'<script nonce="([^"]+)"', html).group(1)
    assert f"script-src 'nonce-{nonce}'" in res.headers["content-security-policy"]


def test_callback_choose_logs_count_without_names_or_tokens(client, graph, caplog):
    graph.pages = [_page(0, "Secret Shop Name"), _page(1)]
    with caplog.at_level(logging.INFO, logger="app"):
        text = _callback(client).text
    msg = _message(text)
    log = "\n".join(r.getMessage() for r in caplog.records)
    assert "Facebook returned 2 pages" in log
    for secret_value in ("Secret Shop Name", USER_TOKEN, "page-token", msg["selection"]):
        assert secret_value not in log


def test_callback_choose_without_secret_fails_closed(client, service_db, monkeypatch):
    monkeypatch.setattr(crypto, "get_settings", lambda: SimpleNamespace(fb_app_secret=""))
    res = _callback(client)
    assert '"reason": "save_failed"' in res.text
    assert '"fb": "choose"' not in res.text
    assert service_db.calls_for("shops", "update") == []


# --- POST /facebook/connect/select ---------------------------------------------------------------

def test_select_connects_chosen_page(client, shop_db, user_db, graph):
    res = _select(client, page_id="101")
    assert res.status_code == 200
    assert res.json() == {"fb": "connected", "page": "Page 1"}
    # the page list is re-read with the user token from the selection, the chosen page is used
    assert graph.user_pages_calls == [USER_TOKEN]
    assert graph.subscribed == [("101", "page-token-1")]
    assert graph.encrypted == ["page-token-1"]
    (upd,) = _page_updates(shop_db)
    assert upd.payload["facebook_page_id"] == "101"
    assert upd.payload["facebook_page_token"] == "enc:page-token-1"
    assert upd.payload["facebook_user_id"] == "fb-user-1"
    assert upd.payload["bot_enabled"] is True
    assert ("eq", "id", SHOP_ID) in upd.filters
    assert ("eq", "owner_id", USER_ID) in upd.filters
    # ownership was checked through the user's RLS client first
    own = user_db.calls_for("shops", "select")
    assert len(own) == 1 and ("eq", "id", SHOP_ID) in own[0].filters


def test_select_bot_limit(client, shop_db):
    shop_db.responses[("shops", "select")] = [
        {"id": SHOP_ID, "subscription_tier": "free", "bot_enabled": False},
        {"id": "33333333-3333-3333-3333-333333333333", "subscription_tier": "free", "bot_enabled": True},
    ]
    res = _select(client, page_id="101")
    assert res.status_code == 200
    assert res.json() == {"fb": "connected", "page": "Page 1", "bot": "limit"}
    (upd,) = _page_updates(shop_db)
    assert upd.payload["bot_enabled"] is False


def test_select_expired_400(client, shop_db, graph, monkeypatch):
    token = _token()
    real = time.time()
    monkeypatch.setattr(fb_selection.time, "time", lambda: real + 601)
    res = _select(client, token)
    assert res.status_code == 400
    assert res.json() == {"detail": CHOOSE_EXPIRED}
    assert graph.user_pages_calls == []
    assert _page_updates(shop_db) == []


def test_select_other_users_selection_400(client, shop_db, graph):
    res = _select(client, _token(user_id=OTHER_USER))
    assert res.status_code == 400
    assert res.json() == {"detail": CHOOSE_INVALID}
    assert graph.user_pages_calls == [] and graph.subscribed == []


def test_select_forged_token_400(client, shop_db, graph):
    token = _token()
    forged = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")
    for bad in (forged, "not-a-token", "A" * 200):
        res = _select(client, bad)
        assert res.status_code == 400
        assert res.json() == {"detail": CHOOSE_INVALID}
    assert graph.user_pages_calls == [] and graph.subscribed == []


def test_select_page_not_in_selection_400(client, shop_db, graph):
    res = _select(client, page_id="999")
    assert res.status_code == 400
    assert res.json() == {"detail": NOT_IN_SELECTION}
    assert graph.user_pages_calls == []
    assert _page_updates(shop_db) == []


def test_select_shop_hidden_by_rls_404(client, shop_db, user_db, graph):
    user_db.responses[("shops", "select")] = []
    res = _select(client)
    assert res.status_code == 404
    assert res.json() == {"detail": "მაღაზია ვერ მოიძებნა"}
    assert graph.user_pages_calls == [] and graph.subscribed == []
    assert shop_db.calls_for("shops", "update") == []


def test_select_graph_failure_graph_failed_without_token_in_logs(client, shop_db, graph, caplog):
    graph.pages_error = RuntimeError(f"boom access_token={USER_TOKEN}")
    with caplog.at_level(logging.DEBUG):
        res = _select(client)
    assert res.status_code == 200
    assert res.json() == {"fb": "error", "reason": "graph_failed"}
    assert USER_TOKEN not in res.text
    assert USER_TOKEN not in "\n".join(r.getMessage() for r in caplog.records)
    assert any(r.levelno == logging.WARNING and "RuntimeError" in r.getMessage() for r in caplog.records)
    assert graph.subscribed == [] and shop_db.calls_for("shops", "update") == []


def test_select_page_no_longer_available(client, shop_db, graph):
    graph.pages = [_page(0)]  # page 101 was removed from the user's account
    res = _select(client, page_id="101")
    assert res.status_code == 200
    assert res.json() == {"fb": "error", "reason": "page_unavailable"}
    assert graph.subscribed == [] and shop_db.calls_for("shops", "update") == []


def test_select_page_taken(client, shop_db):
    shop_db.errors[("shops", "update")] = RuntimeError(
        'duplicate key value violates unique constraint "shops_facebook_page_id_key" (23505)'
    )
    res = _select(client, page_id="101")
    assert res.status_code == 200
    assert res.json() == {"fb": "error", "reason": "page_taken"}


def test_select_subscribe_failed(client, shop_db, graph, monkeypatch):
    def boom(pid, tok):
        raise RuntimeError("graph down")

    monkeypatch.setattr(fb_api.fb, "subscribe_page", boom)
    res = _select(client, page_id="101")
    assert res.json() == {"fb": "error", "reason": "subscribe_failed"}
    assert shop_db.calls_for("shops", "update") == []


def test_select_without_secret_503(client, shop_db, monkeypatch):
    token = _token()
    monkeypatch.setattr(crypto, "get_settings", lambda: SimpleNamespace(fb_app_secret=""))
    res = _select(client, token)
    assert res.status_code == 503
    assert res.json() == {"detail": "Facebook integration not configured"}


@pytest.mark.parametrize(
    "body",
    [
        {"selection": "tok", "page_id": "abc"},
        {"selection": "tok", "page_id": ""},
        {"selection": "tok", "page_id": "1" * 33},
        {"selection": "tok", "page_id": "12 34"},
        {"selection": "", "page_id": "101"},
        {"selection": "x" * 4097, "page_id": "101"},
        {"page_id": "101"},
        {"selection": "tok"},
    ],
)
def test_select_validation_422(client, shop_db, graph, body):
    res = client.post(SELECT_URL, json=body)
    assert res.status_code == 422
    assert graph.user_pages_calls == []


def test_select_requires_auth_401():
    fastapi_app.dependency_overrides.clear()
    res = TestClient(fastapi_app).post(SELECT_URL, json={"selection": "tok", "page_id": "101"})
    assert res.status_code == 401
