"""S21-3 (A-040 / N-05): POST /webhook persists events in webhook_inbox before the 200;
process_inbox_row; the legacy in-memory path runs through the bot limiter; DB dedup (no memory dedup)."""
import hashlib
import hmac
import json
import logging
from types import SimpleNamespace

import anyio
import pytest

import app.api.webhook as webhook
import app.services.inbox as inbox
from app.config import get_settings
from app.services.graph import TurnResult

SECRET = "test-app-secret"
APP_ID = "test-app-id"
PAGE_ID = "1234567890"
SHOP_ID = "22222222-2222-2222-2222-222222222222"
UPSERT_KWARGS = {"on_conflict": "page_id,mid", "ignore_duplicates": True}


class CodedError(Exception):
    def __init__(self, code, message="db error"):
        super().__init__(message)
        self.code = code


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _post(client, payload):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhook", content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sig(body)},
    )


def _msg(mid, text="hello", psid="psid-1"):
    return {"sender": {"id": psid}, "recipient": {"id": PAGE_ID}, "message": {"mid": mid, "text": text}}


def _echo(mid, psid="psid-9"):
    return {
        "sender": {"id": PAGE_ID}, "recipient": {"id": psid},
        "message": {"mid": mid, "is_echo": True, "app_id": "other-app", "text": "seller says hi"},
    }


def _payload(*events, obj="page"):
    return {"object": obj, "entry": [{"id": PAGE_ID, "messaging": list(events)}]}


def _clear_memory_state():
    webhook._RATE_HITS.clear()
    webhook._SEEN_MIDS.clear()
    webhook._OUR_MIDS.clear()


@pytest.fixture
def env(monkeypatch, service_db):
    """Inbox active by default; the webhook uses the fake service DB; processing / wake are recorders."""
    inbox._reset_for_tests()
    monkeypatch.setattr(webhook, "_INBOX_MISSING_WARNED", False, raising=False)
    _clear_memory_state()
    monkeypatch.setattr(webhook, "get_service_client", lambda: service_db)

    def use_settings(active):
        s = get_settings().model_copy(
            update={"fb_app_secret": SECRET, "fb_app_id": APP_ID, "webhook_inbox_enabled": active}
        )
        monkeypatch.setattr(webhook, "get_settings", lambda: s)

    use_settings(True)
    processed, wakes = [], []
    real_process_events = webhook._process_events
    monkeypatch.setattr(webhook, "_process_events", lambda data, **kw: processed.append((data, kw)))
    monkeypatch.setattr(inbox, "wake", lambda: wakes.append(1))

    def use_real_process_events():
        monkeypatch.setattr(webhook, "_process_events", real_process_events)

    yield SimpleNamespace(
        db=service_db, processed=processed, wakes=wakes, use_settings=use_settings,
        use_real_process_events=use_real_process_events,
    )
    inbox._reset_for_tests()
    _clear_memory_state()  # other tests reuse mids like "m1" - leftovers would look like duplicates to them


def _bot_env(monkeypatch, db):
    """Shop + fake Graph / LLM so the real _process_events reaches the message / echo code."""
    db.responses[("shops", "select")] = [{
        "id": SHOP_ID, "bot_enabled": True, "facebook_page_token": "enc", "subscription_tier": "free",
    }]
    db.responses[("products", "select")] = []
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 1}]
    sent = []
    monkeypatch.setattr(webhook, "decrypt", lambda token: "page-token")
    monkeypatch.setattr(webhook, "send_text_message", lambda tok, psid, text: sent.append(psid))
    monkeypatch.setattr(webhook, "download_image", lambda url, timeout=8: None)
    monkeypatch.setattr(webhook, "run_turn", lambda *a, **kw: TurnResult("llm reply"))
    return sent


def _forbid_memory_dedup(monkeypatch):
    def boom(mid):
        raise AssertionError("_already_handled must not be used on the inbox path")

    monkeypatch.setattr(webhook, "_already_handled", boom)


def _recording_run_sync(monkeypatch):
    calls = []
    original = anyio.to_thread.run_sync

    async def spy(func, *args, **kwargs):
        calls.append((func, kwargs))
        return await original(func, *args, **kwargs)

    monkeypatch.setattr(anyio.to_thread, "run_sync", spy)
    return calls


# (1)
def test_post_webhook_persists_events_before_200(client, env):
    ev_a, ev_b, echo = _msg("m1"), _msg("m2", psid="psid-2"), _echo("m3")
    postback = {"sender": {"id": "psid-1"}, "recipient": {"id": PAGE_ID}, "postback": {"payload": "x"}}

    r = _post(client, _payload(ev_a, ev_b, echo, postback))

    assert r.status_code == 200 and r.json() == {"status": "ok"}
    upserts = env.db.calls_for("webhook_inbox", "upsert")
    assert len(upserts) == 1
    assert upserts[0].kwargs == UPSERT_KWARGS
    assert upserts[0].payload == [
        {"page_id": PAGE_ID, "mid": "m1", "object": "page", "event": ev_a},
        {"page_id": PAGE_ID, "mid": "m2", "object": "page", "event": ev_b},
        {"page_id": PAGE_ID, "mid": "m3", "object": "page", "event": echo},
    ]
    assert env.processed == []  # no in-memory processing on the inbox path
    assert env.wakes == [1]


# (2)
def test_inbox_path_never_uses_memory_dedup(client, env, monkeypatch):
    _forbid_memory_dedup(monkeypatch)
    payload = _payload(_msg("m-same"))

    assert _post(client, payload).status_code == 200
    assert _post(client, payload).status_code == 200

    assert len(env.db.calls_for("webhook_inbox", "upsert")) == 2  # dedup is the DB's unique(page_id, mid)


def test_process_inbox_row_never_uses_memory_dedup_for_echo(env, monkeypatch):
    _bot_env(monkeypatch, env.db)
    env.use_real_process_events()
    _forbid_memory_dedup(monkeypatch)
    echo = _echo("m-echo")

    webhook.process_inbox_row({"object": "page", "page_id": PAGE_ID, "mid": "m-echo", "event": echo})

    # the echo reached the history write, so the dedup check (skipped) was the only thing bypassed
    assert env.db.calls_for("bot_conversations", "upsert")


def test_process_inbox_row_never_uses_memory_dedup_for_message(env, monkeypatch):
    sent = _bot_env(monkeypatch, env.db)
    env.use_real_process_events()
    _forbid_memory_dedup(monkeypatch)
    row ={"object": "page", "page_id": PAGE_ID, "mid": "m-1", "event": _msg("m-1")}

    webhook.process_inbox_row(row)
    webhook.process_inbox_row(row)

    assert sent == ["psid-1", "psid-1"]


# (3)
@pytest.mark.parametrize("code", ["PGRST205", "42P01"])
def test_inbox_unavailable_falls_back_to_background(client, env, caplog, code):
    env.db.errors[("webhook_inbox", "upsert")] = CodedError(code, "secret detail")
    payload = _payload(_msg("m1"))

    with caplog.at_level(logging.WARNING, logger="app"):
        assert _post(client, payload).status_code == 200
        assert len(env.processed) == 1
        assert env.processed[0][0] == payload
        assert _post(client, payload).status_code == 200

    assert len(env.processed) == 2
    missing = [r for r in caplog.records if "webhook_inbox missing (migration 0037 not applied)" in r.getMessage()]
    assert len(missing) == 1  # one-time per process
    assert "secret detail" not in caplog.text
    assert env.wakes == []


def test_inbox_general_error_falls_back_and_warns_every_time(client, env, caplog):
    env.db.errors[("webhook_inbox", "upsert")] = RuntimeError("secret detail")
    payload = _payload(_msg("m1"))

    with caplog.at_level(logging.WARNING, logger="app"):
        assert _post(client, payload).status_code == 200
        assert _post(client, payload).status_code == 200

    assert len(env.processed) == 2
    warned = [r for r in caplog.records if "RuntimeError" in r.getMessage()]
    assert len(warned) == 2
    assert "secret detail" not in caplog.text
    assert "migration 0037" not in caplog.text


# (4)
def test_inbox_disabled_uses_background_with_bot_limiter(client, env, monkeypatch):
    env.use_settings(False)
    calls = _recording_run_sync(monkeypatch)
    payload = _payload(_msg("m1"))

    r = _post(client, payload)

    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert env.db.calls_for("webhook_inbox", "upsert") == []
    assert env.wakes == []
    assert len(env.processed) == 1 and env.processed[0][0] == payload
    run = [kw for fn, kw in calls if fn is webhook._process_events]
    assert len(run) == 1
    assert run[0]["limiter"] is inbox.bot_limiter()


# (5)
def test_payload_without_message_events_is_not_stored(client, env):
    postback = {"sender": {"id": "psid-1"}, "recipient": {"id": PAGE_ID}, "postback": {"payload": "x"}}
    read = {"sender": {"id": "psid-1"}, "recipient": {"id": PAGE_ID}, "read": {"watermark": 1}}

    r = _post(client, _payload(postback, read))

    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert env.db.calls_for("webhook_inbox", "upsert") == []
    assert env.processed == []
    assert env.wakes == []


# (6)
def test_process_inbox_row_builds_single_event_payload(env, monkeypatch):
    seen = []
    monkeypatch.setattr(webhook, "_process_events", lambda data, **kw: seen.append((data, kw)))
    ev = _msg("m1", psid="psid-5")

    webhook.process_inbox_row({"object": "instagram", "page_id": PAGE_ID, "mid": "m1", "event": ev})

    assert seen == [(
        {"object": "instagram", "entry": [{"id": PAGE_ID, "messaging": [ev]}]},
        {"dedup": False},
    )]


def test_process_inbox_row_without_event_does_nothing(env, monkeypatch):
    seen = []
    monkeypatch.setattr(webhook, "_process_events", lambda data, **kw: seen.append(data))

    webhook.process_inbox_row({"object": "page", "page_id": PAGE_ID, "mid": "m1", "event": None})

    assert seen == []


def test_process_inbox_row_propagates_errors_to_the_worker(env, monkeypatch):
    def boom(data, **kw):
        raise RuntimeError("bot failed")

    monkeypatch.setattr(webhook, "_process_events", boom)

    with pytest.raises(RuntimeError):
        webhook.process_inbox_row({"object": "page", "page_id": PAGE_ID, "mid": "m1", "event": _msg("m1")})


# (7)
def test_enqueue_runs_off_event_loop(client, env, monkeypatch):
    calls = _recording_run_sync(monkeypatch)

    assert _post(client, _payload(_msg("m1"))).status_code == 200

    assert any(fn is inbox.enqueue for fn, _ in calls)
    assert len(env.db.calls_for("webhook_inbox", "upsert")) == 1


# (8)
def test_rate_limit_warning_has_no_psid(env, monkeypatch, caplog):
    sent = _bot_env(monkeypatch, env.db)
    env.use_real_process_events()
    monkeypatch.setattr(webhook, "_rate_limited", lambda shop_id, psid: True)
    ev = _msg("m1", psid="psid-secret-42")

    with caplog.at_level(logging.WARNING, logger="app"):
        webhook._process_events(_payload(ev))

    limited = [r for r in caplog.records if SHOP_ID in r.getMessage()]
    assert limited, "rate-limit warning not logged"
    assert "psid-secret-42" not in caplog.text
    assert sent == []


# (9)
def test_enqueue_failure_log_has_no_payload_or_psid(client, env, caplog):
    env.db.errors[("webhook_inbox", "upsert")] = RuntimeError("SECRET-TEXT psid-777 payload")
    payload = _payload(_msg("m1", text="SECRET-TEXT", psid="psid-777"))

    with caplog.at_level(logging.DEBUG, logger="app"):
        assert _post(client, payload).status_code == 200

    assert "SECRET-TEXT" not in caplog.text
    assert "psid-777" not in caplog.text
    assert all(not r.exc_info for r in caplog.records)
