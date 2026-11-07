"""Stage 24 (A-042 / N-08): no "migration not applied" fallbacks in the webhook.

A missing table / column / RPC is an error that goes up (inbox path: worker `inbox.fail` -> retry),
never a silent return to the old behaviour. `POST /webhook` with the inbox active answers 503 when
the event cannot be stored, so Meta retries. Nothing leaves the process (fake DB, patched Graph / LLM).
"""
import hashlib
import hmac
import json
import logging
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

import app.api.webhook as webhook
import app.services.inbox as inbox
from app.config import get_settings
from app.services.graph import TurnResult

SECRET = "test-app-secret"
PAGE_ID = "1234567890"
SHOP_ID = "22222222-2222-2222-2222-222222222222"
PSID = "psid-secret-777"
TEXT = "SECRET-TEXT hello"


def _api_error(code, message="relation does not exist"):
    return APIError({"code": code, "message": message, "details": None, "hint": None})


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _post(client, payload):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhook", content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sig(body)},
    )


def _event(mid="m1", psid=PSID, text=TEXT):
    return {"sender": {"id": psid}, "recipient": {"id": PAGE_ID}, "message": {"mid": mid, "text": text}}


def _payload(*events):
    return {"object": "page", "entry": [{"id": PAGE_ID, "messaging": list(events)}]}


def _warnings(caplog, needle):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and needle in r.getMessage()]


@pytest.fixture(autouse=True)
def _clean_state():
    inbox._reset_for_tests()
    webhook._RATE_HITS.clear()
    webhook._OUR_MIDS.clear()
    yield
    inbox._reset_for_tests()
    webhook._RATE_HITS.clear()
    webhook._OUR_MIDS.clear()


@pytest.fixture
def env(monkeypatch, service_db):
    """Fake DB with one active shop, fake Send API / LLM; `sent` records the replies."""
    db = service_db
    db.responses[("shops", "select")] = [{
        "id": SHOP_ID, "bot_enabled": True, "facebook_page_token": "enc", "subscription_tier": "free",
    }]
    db.responses[("products", "select")] = []
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 1}]
    sent = []
    bot = {"result": TurnResult("llm reply")}
    monkeypatch.setattr(webhook, "get_service_client", lambda: db)
    monkeypatch.setattr(webhook, "decrypt", lambda token: "page-token")
    monkeypatch.setattr(webhook, "send_text_message", lambda tok, psid, text: sent.append(text))
    monkeypatch.setattr(webhook, "download_image", lambda url, timeout=8: None)
    monkeypatch.setattr(webhook, "run_turn", lambda *a, **kw: bot["result"])
    s = get_settings().model_copy(update={"fb_app_secret": SECRET, "webhook_inbox_enabled": True})
    monkeypatch.setattr(webhook, "get_settings", lambda: s)
    return SimpleNamespace(db=db, sent=sent, bot=bot)


@pytest.fixture
def post_env(env, monkeypatch):
    """env + recorders for the background processing and the inbox wake-up (POST /webhook tests)."""
    env.processed, env.wakes = [], []
    monkeypatch.setattr(webhook, "_process_events", lambda data, **kw: env.processed.append(data))
    monkeypatch.setattr(inbox, "wake", lambda: env.wakes.append(1))
    return env


def _row(event):
    return {"object": "page", "page_id": PAGE_ID, "mid": event["message"]["mid"], "event": event}


# (1) enqueue failure -> 503 to Meta (old code: 200 + in-memory processing)
def test_enqueue_schema_error_is_503_without_background_processing(client, post_env, caplog):
    post_env.db.errors[("webhook_inbox", "upsert")] = _api_error("PGRST205")
    payload = _payload(_event())

    with caplog.at_level(logging.DEBUG, logger="app"):
        r = _post(client, payload)

    assert r.status_code == 503
    assert r.json() == {"detail": "webhook queue unavailable"}
    assert post_env.processed == []
    assert post_env.wakes == []
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("webhook_inbox enqueue failed (APIError)" in m for m in errors)
    assert PSID not in caplog.text and "SECRET-TEXT" not in caplog.text and "relation does not" not in caplog.text


# (2)
def test_enqueue_runtime_error_is_503(client, post_env, caplog):
    post_env.db.errors[("webhook_inbox", "upsert")] = RuntimeError("SECRET-TEXT psid-secret-777")

    with caplog.at_level(logging.DEBUG, logger="app"):
        r = _post(client, _payload(_event()))

    assert r.status_code == 503 and r.json() == {"detail": "webhook queue unavailable"}
    assert post_env.processed == []
    assert any("RuntimeError" in x.getMessage() for x in caplog.records if x.levelno == logging.ERROR)
    assert PSID not in caplog.text and "SECRET-TEXT" not in caplog.text


# (3) schema error while processing an inbox row goes up (the worker retries it)
def test_process_inbox_row_conversation_select_error_propagates(env, monkeypatch):
    monkeypatch.setattr(webhook, "_paused_until", lambda *a: None)  # isolate the memory load
    env.db.errors[("bot_conversations", "select")] = _api_error("42703", "column summary does not exist")

    with pytest.raises(APIError):
        webhook.process_inbox_row(_row(_event()))

    assert len(env.db.calls_for("bot_conversations", "select")) == 1  # old code: a second select without summary
    assert env.sent == []  # no Send API call, no reply
    assert env.db.calls_for("bot_conversations", "upsert") == []


# (4) handoff save error: ONE upsert attempt, a WARNING, the reply is not repeated
def test_handoff_save_error_is_a_single_upsert_attempt(env, caplog):
    env.bot["result"] = TurnResult("operator will contact you", handoff=True)
    env.db.errors[("bot_conversations", "upsert")] = _api_error("42703", "column bot_paused_until does not exist")

    with caplog.at_level(logging.WARNING, logger="app"):
        webhook._process_events(_payload(_event()))

    assert len(env.db.calls_for("bot_conversations", "upsert")) == 1  # old code: 3 attempts
    assert env.sent == ["operator will contact you"]
    assert len(_warnings(caplog, "საუბრის შენახვა ვერ მოხერხდა")) == 1
    assert PSID not in caplog.text and "SECRET-TEXT" not in caplog.text


# (5)
def test_bot_products_select_error_propagates_with_one_select(env):
    env.db.errors[("products", "select")] = _api_error("42703", "column image_description does not exist")

    with pytest.raises(APIError):
        webhook._load_bot_products(env.db, SHOP_ID)

    assert len(env.db.calls_for("products", "select")) == 1  # old code: a second select without image_description


# (6)
def test_shop_lookup_error_propagates_without_the_old_eq_query(env):
    env.db.errors[("shops", "select")] = _api_error("42703", "column instagram_account_id does not exist")

    with pytest.raises(APIError):
        webhook._process_events(_payload(_event()))

    selects = env.db.calls_for("shops", "select")
    assert len(selects) == 1
    assert [f for f in selects[0].filters if f[0] == "or"]
    assert not any(f[:2] == ("eq", "facebook_page_id") for c in selects for f in c.filters)  # no 0006 fallback
    assert env.sent == []


# (7) a failing status write is retried (and warned about) every time - no permanent off switch
def test_set_bot_status_failure_warns_and_retries_every_time(env, caplog):
    env.db.errors[("shops", "update")] = _api_error("42703", "column bot_status does not exist")
    shop = {"id": SHOP_ID, "bot_status": "send_failed"}

    with caplog.at_level(logging.WARNING, logger="app"):
        webhook._set_bot_status(env.db, shop, "ok")
        webhook._set_bot_status(env.db, shop, "ok")

    assert len(env.db.calls_for("shops", "update")) == 2  # old code: 1 (switched off after the first failure)
    warnings = _warnings(caplog, "bot status write failed")
    assert len(warnings) == 2
    assert all(f"shop={SHOP_ID}" in w and "APIError" in w for w in warnings)
    assert "does not exist" not in caplog.text
    assert shop["bot_status"] == "send_failed"


# (8)
def test_memory_dedup_is_gone():
    assert hasattr(webhook, "_SEEN_MIDS") is False
    assert hasattr(webhook, "_already_handled") is False
    assert hasattr(webhook, "_warn_inbox_unavailable") is False
    assert hasattr(webhook, "_warn_pause_missing") is False


# (9) legacy path (dev / inbox off): the same mid twice is processed twice (documented behaviour)
def test_legacy_path_processes_a_repeated_mid_twice(env):
    payload = _payload(_event(mid="m-same"))

    webhook._process_events(payload)
    webhook._process_events(payload)

    assert env.sent == ["llm reply", "llm reply"]


# W2: the pause lookup error goes up; a malformed value is still "not paused"
def test_pause_select_error_propagates(env):
    env.db.errors[("bot_conversations", "select")] = _api_error("42703", "column bot_paused_until does not exist")

    with pytest.raises(APIError):
        webhook._paused_until(env.db, SHOP_ID, PSID)


def test_pause_value_that_cannot_be_parsed_means_not_paused(env):
    env.db.responses[("bot_conversations", "select")] = [{"bot_paused_until": "not-a-date"}]

    assert webhook._paused_until(env.db, SHOP_ID, PSID) is None


# W3: the history write (echo / paused customer text) is one upsert; a failure is a WARNING + False
def test_append_history_failure_is_one_upsert_and_false(env, caplog):
    env.db.errors[("bot_conversations", "upsert")] = _api_error("42703", "column bot_paused_until does not exist")

    with caplog.at_level(logging.WARNING, logger="app"):
        ok = webhook._append_history(env.db, SHOP_ID, PSID, [{"role": "operator", "content": "x"}], pause=True)

    assert ok is False
    assert len(env.db.calls_for("bot_conversations", "upsert")) == 1  # old code: a second one without the pause
    assert len(_warnings(caplog, "საუბრის შენახვა ვერ მოხერხდა")) == 1
    assert "does not exist" not in caplog.text


# W5: `_save_turn` raises the DB error (its callers log it); the inbox path is untouched when it succeeds
def test_save_turn_error_goes_up_after_one_attempt(env):
    env.db.errors[("bot_conversations", "upsert")] = _api_error("PGRST205", "table does not exist")

    with pytest.raises(APIError):
        webhook._save_turn(env.db, SHOP_ID, PSID, [], "hi", "hello", needs_attention=True)

    assert len(env.db.calls_for("bot_conversations", "upsert")) == 1
