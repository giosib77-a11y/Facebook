"""S20-11 (A-038 / N-07): bot health in the webhook - BOT DOWN alert, `shops.bot_status`, handoff email.

* decrypt failure             -> bot_status "token_error" + alert_bot_down(shop, "token_error")
* send failure                -> "token_expired" (GraphError.code 190) / "send_failed" (anything else) + alert
* send success                -> "ok" only when the stored status was a failure (no write on the happy path)
* shops.bot_status missing    -> the reply still goes out; ONE WARNING per process; no more write attempts
* handoff                     -> notify_handoff on the main path and the operator path; never on pause / echo
* monthly_budget              -> "budget_exhausted"
* GraphError.code             -> Graph JSON error.code (int) via `_graph`
* ShopOut                     -> bot_status / bot_status_at

`_process_events` is called directly with a fake service client; `notify.alert_bot_down` /
`notify.notify_handoff` are replaced by recorders, so no SMTP / Telegram / Graph call happens.
"""
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

import app.api.webhook as webhook
from app.services import budget
from app.services import facebook as fb
from app.services.facebook import GraphError
from app.services.graph import TurnResult
from tests.test_reply_delivery import PAGE_ID, PSID, SHOP_ID

OWNER = "33333333-3333-3333-3333-333333333333"
STATUS_WARNING = "shops.bot_status missing"
PAGE_TOKEN = "PAGE_TOKEN_SENTINEL_789"


@pytest.fixture(autouse=True)
def _reset_process_state(monkeypatch):
    monkeypatch.setattr(webhook, "_BOT_STATUS_COLUMN_WARNED", False, raising=False)
    webhook._SEEN_MIDS.clear()
    yield
    webhook._SEEN_MIDS.clear()


def _shop(status=None, **extra):
    shop = {
        "id": SHOP_ID, "owner_id": OWNER, "name": "Test shop", "bot_enabled": True,
        "facebook_page_token": "enc", "subscription_tier": "free",
    }
    if status is not None:
        shop["bot_status"] = status
    shop.update(extra)
    return shop


@pytest.fixture
def env(monkeypatch, service_db):
    """db, sent, alerts, handoffs, calls — alerts/handoffs record the notify calls."""
    db = service_db
    db.responses[("shops", "select")] = [_shop()]
    db.responses[("products", "select")] = []
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 1}]

    sent, alerts, handoffs = [], [], []
    calls = {"bot": 0, "result": None, "send_error": None}

    def fake_send(tok, psid, text):
        if calls["send_error"] is not None:
            raise calls["send_error"]
        sent.append(text)

    def fake_run_turn(shop, products, text, history, images=None, **kw):
        calls["bot"] += 1
        return calls["result"] or TurnResult("llm reply")

    monkeypatch.setattr(webhook, "get_service_client", lambda: db)
    monkeypatch.setattr(webhook, "decrypt", lambda token: PAGE_TOKEN)
    monkeypatch.setattr(webhook, "send_text_message", fake_send)
    monkeypatch.setattr(webhook, "download_image", lambda url, timeout=8: None)
    monkeypatch.setattr(webhook, "run_turn", fake_run_turn)
    monkeypatch.setattr(webhook.notify, "alert_bot_down", lambda shop, kind: alerts.append((shop.get("id"), kind)))
    monkeypatch.setattr(webhook.notify, "notify_handoff", lambda sc, shop: handoffs.append((sc, shop.get("id"))))
    return db, sent, alerts, handoffs, calls


def _run(*texts):
    texts = texts or ("გამარჯობა",)
    events = [{"sender": {"id": PSID}, "message": {"text": t}} for t in texts]
    webhook._process_events({"object": "page", "entry": [{"id": PAGE_ID, "messaging": events}]})


def _status_updates(db):
    return db.calls_for("shops", "update")


def _payload_status(update):
    return update.payload["bot_status"]


def _warnings(caplog, needle=""):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and needle in r.getMessage()]


# ---- (1) decrypt failure -----------------------------------------------------
def test_decrypt_failure_sets_token_error_and_alerts_once(env, monkeypatch, caplog):
    db, sent, alerts, handoffs, calls = env

    def boom(token):
        raise ValueError("bad key")

    monkeypatch.setattr(webhook, "decrypt", boom)

    with caplog.at_level(logging.ERROR, logger="app"):
        _run()

    (upd,) = _status_updates(db)
    assert _payload_status(upd) == "token_error"
    assert upd.payload["bot_status_at"]
    assert ("eq", "id", SHOP_ID) in upd.filters
    assert alerts == [(SHOP_ID, "token_error")]
    assert sent == [] and calls["bot"] == 0
    assert any("BOT DOWN" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)


def test_decrypt_failure_does_not_rewrite_same_status(env, monkeypatch):
    db, *_ = env
    db.responses[("shops", "select")] = [_shop("token_error")]
    monkeypatch.setattr(webhook, "decrypt", lambda token: (_ for _ in ()).throw(ValueError("bad key")))

    _run()

    assert _status_updates(db) == []


# ---- (2) send failure kinds --------------------------------------------------
@pytest.mark.parametrize("error, kind", [
    (GraphError(400, "Error validating access token", code=190), "token_expired"),
    (GraphError(400, "(#10) permission", code=10), "send_failed"),
    (GraphError(None, "network error"), "send_failed"),
    (GraphError(500, "HTTP 500"), "send_failed"),
    (RuntimeError("boom"), "send_failed"),
])
def test_send_failure_sets_status_by_graph_code_and_alerts(env, error, kind):
    db, sent, alerts, handoffs, calls = env
    calls["send_error"] = error

    _run()

    (upd,) = _status_updates(db)
    assert _payload_status(upd) == kind
    assert alerts == [(SHOP_ID, kind)]
    assert sent == []
    assert db.calls_for("bot_conversations", "upsert") == []  # existing behaviour: nothing saved on a failed send


def test_second_send_failure_with_same_status_is_not_rewritten_but_still_alerts(env):
    db, sent, alerts, handoffs, calls = env
    calls["send_error"] = GraphError(400, "expired", code=190)

    _run("one", "two")

    assert len(_status_updates(db)) == 1
    assert alerts == [(SHOP_ID, "token_expired")] * 2  # notify throttles; the webhook just reports


# ---- (3) success -------------------------------------------------------------
@pytest.mark.parametrize("stored", ["send_failed", "token_expired", "token_error", "budget_exhausted"])
def test_successful_send_clears_failure_status(env, stored):
    db, sent, alerts, handoffs, calls = env
    db.responses[("shops", "select")] = [_shop(stored)]

    _run()

    assert sent == ["llm reply"]
    (upd,) = _status_updates(db)
    assert _payload_status(upd) == "ok"
    assert upd.payload["bot_status_at"]
    assert alerts == []


@pytest.mark.parametrize("stored", [None, "ok"])
def test_successful_send_on_healthy_shop_writes_nothing(env, stored):
    db, sent, alerts, handoffs, calls = env
    db.responses[("shops", "select")] = [_shop(stored)]

    _run("one", "two")

    assert sent == ["llm reply", "llm reply"]
    assert _status_updates(db) == []


def test_recovery_is_written_once_for_several_messages(env):
    db, sent, alerts, handoffs, calls = env
    db.responses[("shops", "select")] = [_shop("send_failed")]

    _run("one", "two", "three")

    assert len(sent) == 3
    assert len(_status_updates(db)) == 1


# ---- (4) shops.bot_status missing (migration 0036 not applied) ---------------
def test_status_write_failure_does_not_block_reply_and_warns_once(env, caplog):
    db, sent, alerts, handoffs, calls = env
    db.responses[("shops", "select")] = [_shop("send_failed")]
    db.errors[("shops", "update")] = RuntimeError("column bot_status does not exist")

    with caplog.at_level(logging.WARNING, logger="app"):
        _run("one", "two")
        _run("three")

    assert sent == ["llm reply"] * 3
    assert len(db.calls_for("bot_conversations", "upsert")) == 3  # conversation saving unaffected
    assert len(_warnings(caplog, STATUS_WARNING)) == 1
    assert "migration 0036" in _warnings(caplog, STATUS_WARNING)[0]
    assert len(_status_updates(db)) == 1  # after the failure no more attempts


def test_status_write_failure_on_send_failure_still_alerts(env, caplog):
    db, sent, alerts, handoffs, calls = env
    db.errors[("shops", "update")] = RuntimeError("column bot_status does not exist")
    calls["send_error"] = GraphError(400, "expired", code=190)

    with caplog.at_level(logging.WARNING, logger="app"):
        _run()

    assert alerts == [(SHOP_ID, "token_expired")]
    assert len(_warnings(caplog, STATUS_WARNING)) == 1


def test_status_write_failure_leaves_in_memory_status_unchanged(env):
    db, *_ = env
    db.errors[("shops", "update")] = RuntimeError("no column")
    shop = _shop("send_failed")

    webhook._set_bot_status(db, shop, "ok")

    assert shop["bot_status"] == "send_failed"


# ---- (5) handoff email -------------------------------------------------------
def test_handoff_turn_notifies_owner_after_saving(env):
    db, sent, alerts, handoffs, calls = env
    calls["result"] = TurnResult("ოპერატორი დაგიკავშირდებათ", handoff=True)

    _run()

    assert handoffs == [(db, SHOP_ID)]
    assert db.calls_for("bot_conversations", "upsert")[0].payload["needs_attention"] is True


def test_every_handoff_turn_calls_notify(env):
    db, sent, alerts, handoffs, calls = env
    calls["result"] = TurnResult("x", handoff=True)

    _run("one", "two")  # the second message is not paused: the fake db never returns a paused row

    assert len(handoffs) == 2  # per-shop throttling lives in notify


def test_ordinary_reply_does_not_notify(env):
    db, sent, alerts, handoffs, calls = env

    _run()

    assert sent == ["llm reply"]
    assert handoffs == []


def test_empty_reply_fallback_counts_as_handoff(env):
    db, sent, alerts, handoffs, calls = env
    calls["result"] = TurnResult("")

    _run()

    assert sent == [webhook.EMPTY_REPLY_FALLBACK]
    assert handoffs == [(db, SHOP_ID)]


def test_failed_send_of_a_handoff_reply_does_not_email(env):
    db, sent, alerts, handoffs, calls = env
    calls["result"] = TurnResult("x", handoff=True)
    calls["send_error"] = GraphError(400, "expired", code=190)

    _run()

    assert handoffs == []
    assert alerts == [(SHOP_ID, "token_expired")]


def test_paused_conversation_does_not_notify(env):
    db, sent, alerts, handoffs, calls = env
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    db.responses[("bot_conversations", "select")] = [{"bot_paused_until": future, "messages": []}]

    _run()

    assert sent == [] and calls["bot"] == 0
    assert handoffs == []
    assert _status_updates(db) == []


def test_seller_echo_does_not_notify(env, monkeypatch):
    db, sent, alerts, handoffs, calls = env
    s = webhook.get_settings().model_copy(update={"fb_app_id": "111"})
    monkeypatch.setattr(webhook, "get_settings", lambda: s)

    webhook._process_events({"object": "page", "entry": [{"id": PAGE_ID, "messaging": [{
        "sender": {"id": PAGE_ID}, "recipient": {"id": PSID},
        "message": {"is_echo": True, "app_id": "999", "text": "seller reply", "mid": "m-echo-1"},
    }]}]})

    assert handoffs == []
    assert sent == []


def test_disabled_bot_operator_path_notifies(env, monkeypatch):
    db, sent, alerts, handoffs, calls = env
    s = webhook.get_settings().model_copy(update={"anthropic_api_key": ""})
    monkeypatch.setattr(webhook, "get_settings", lambda: s)

    _run()

    assert sent == [webhook.OPERATOR_SOON_REPLY]
    assert handoffs == [(db, SHOP_ID)]
    assert calls["bot"] == 0


def test_over_limit_operator_path_notifies(env):
    db, sent, alerts, handoffs, calls = env
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 31, "day_count": 1}]
    db.responses[("bot_customers", "select")] = [{"created_at": "2026-10-01T10:00:00+00:00"}]
    db.counts[("bot_customers", "select")] = 30  # rank 31 > free limit

    _run()

    assert sent == [webhook.OPERATOR_SOON_REPLY]
    assert handoffs == [(db, SHOP_ID)]


def test_budget_operator_path_notifies(env, monkeypatch):
    db, sent, alerts, handoffs, calls = env
    monkeypatch.setattr(budget, "blocked_reason", lambda sc, shop: "daily_cap")

    _run()

    assert sent == [webhook.OPERATOR_SOON_REPLY]
    assert handoffs == [(db, SHOP_ID)]
    assert _status_updates(db) == []  # only monthly_budget is a per-shop status


# ---- (6) monthly budget ------------------------------------------------------
def test_monthly_budget_sets_budget_exhausted(env, monkeypatch):
    db, sent, alerts, handoffs, calls = env
    monkeypatch.setattr(budget, "blocked_reason", lambda sc, shop: "monthly_budget")

    _run()

    (upd,) = _status_updates(db)
    assert _payload_status(upd) == "budget_exhausted"
    assert sent == [webhook.OPERATOR_SOON_REPLY]
    assert alerts == []


def test_monthly_budget_repeated_is_written_once(env, monkeypatch):
    db, sent, alerts, handoffs, calls = env
    monkeypatch.setattr(budget, "blocked_reason", lambda sc, shop: "monthly_budget")

    _run("one", "two")

    assert len(_status_updates(db)) == 1


# ---- (7) GraphError.code -----------------------------------------------------
@pytest.fixture
def graph(monkeypatch):
    monkeypatch.setattr(fb, "get_settings", lambda: SimpleNamespace(
        fb_app_id="app-1", fb_app_secret="secret", fb_graph_version="v21.0",
    ))
    fake = SimpleNamespace(reply=None)
    transport = httpx.MockTransport(lambda request: fake.reply(request))

    def request(method, url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.request(method, url, **kwargs)

    monkeypatch.setattr(httpx, "request", request)
    return fake


def test_graph_error_carries_graph_json_code(graph):
    graph.reply = lambda request: httpx.Response(
        400, json={"error": {"message": "Error validating access token", "code": 190}}
    )

    with pytest.raises(GraphError) as exc:
        fb.send_text_message("tok", "psid", "hi")

    assert exc.value.code == 190
    assert exc.value.status_code == 400
    assert str(exc.value) == "Error validating access token"


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="<html>oops</html>"),
    httpx.Response(400, json={"error": {"message": "x"}}),
    httpx.Response(400, json={"error": {"message": "x", "code": "190"}}),
    httpx.Response(400, json={"error": {"message": "x", "code": True}}),
    httpx.Response(400, json=["not", "a", "dict"]),
])
def test_graph_error_code_is_none_when_not_an_int(graph, response):
    graph.reply = lambda request: response

    with pytest.raises(GraphError) as exc:
        fb.send_text_message("tok", "psid", "hi")

    assert exc.value.code is None


def test_graph_error_default_code_and_existing_callers_unchanged():
    err = GraphError(None, "network error")
    assert err.code is None and err.status_code is None and str(err) == "network error"
    assert GraphError(400, "m", 190).code == 190


# ---- (8) ShopOut -------------------------------------------------------------
def _shop_row(**extra):
    row = {
        "id": SHOP_ID, "owner_id": "11111111-1111-1111-1111-111111111111", "name": "S", "currency": "GEL",
        "bot_enabled": True, "created_at": "2026-11-01T10:00:00+00:00", "updated_at": "2026-11-01T10:00:00+00:00",
    }
    row.update(extra)
    return row


def test_shops_me_returns_bot_status(client, user_db):
    user_db.responses[("shops", "select")] = [
        _shop_row(bot_status="token_expired", bot_status_at="2026-11-04T09:30:00+00:00")
    ]

    resp = client.get("/shops/me")

    assert resp.status_code == 200
    (shop,) = resp.json()
    assert shop["bot_status"] == "token_expired"
    assert shop["bot_status_at"].startswith("2026-11-04T09:30:00")
    assert "facebook_page_token" not in shop


def test_shops_me_without_migration_returns_null_status(client, user_db):
    user_db.responses[("shops", "select")] = [_shop_row()]

    (shop,) = client.get("/shops/me").json()

    assert shop["bot_status"] is None and shop["bot_status_at"] is None


# ---- (9) logs never contain psid / token -------------------------------------
def test_logs_contain_no_psid_or_token(env, monkeypatch, caplog):
    db, sent, alerts, handoffs, calls = env
    db.errors[("shops", "update")] = RuntimeError("column bot_status does not exist")
    calls["send_error"] = GraphError(400, "Error validating access token", code=190)

    with caplog.at_level(logging.DEBUG, logger="app"):
        _run("one")  # send failure + status write failure
        monkeypatch.setattr(webhook, "decrypt", lambda token: (_ for _ in ()).throw(ValueError("bad key")))
        _run("two")  # decrypt failure

    text = caplog.text
    assert "BOT DOWN" in text and STATUS_WARNING in text and "page token" in text
    assert PSID not in text
    assert PAGE_TOKEN not in text
