"""S21-2 (A-040 / N-05): services/inbox.py - payload -> rows, enqueue / claim / complete / fail, wake, bot limiter.
Offline: fake Supabase, no real loop left running (anyio.run)."""
import json
import logging
from datetime import datetime, timedelta, timezone

import anyio
import pytest

from app.config import get_settings
from app.services import inbox
from tests.conftest import FakeSupabase

PAGE = "1234567890"
SECRET = "psid 123 secret"


class RpcMissing(Exception):
    code = "PGRST202"


class Boom(Exception):
    pass


@pytest.fixture(autouse=True)
def _fresh_inbox_state():
    inbox._reset_for_tests()
    yield
    inbox._reset_for_tests()


def _msg(mid, sender="555", text="hi", **extra):
    return {"sender": {"id": sender}, "recipient": {"id": PAGE}, "message": {"mid": mid, "text": text, **extra}}


def _payload(*events, entry_id=PAGE, obj="page"):
    return {"object": obj, "entry": [{"id": entry_id, "messaging": list(events)}]}


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def _iso(value):
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------- rows_from_payload

def test_rows_from_payload_keeps_message_events_and_echo_skips_the_rest():
    echo = {"sender": {"id": PAGE}, "recipient": {"id": "555"}, "message": {"mid": "m.echo", "is_echo": True, "text": "x"}}
    first, second = _msg("m.1"), _msg("m.2", text="second")
    data = {
        "object": "page",
        "entry": [
            {"id": PAGE, "messaging": [
                first,
                echo,
                {"sender": {"id": "555"}, "postback": {"payload": "P"}},
                {"sender": {"id": "555"}, "read": {"watermark": 1}},
                {"sender": {"id": "555"}, "delivery": {"mids": ["m.1"]}},
            ]},
            {"id": "not-digits", "messaging": [_msg("m.bad")]},
            {"id": PAGE, "messaging": [second]},
        ],
    }
    rows = inbox.rows_from_payload(data)
    assert rows == [
        {"page_id": PAGE, "mid": "m.1", "object": "page", "event": first},
        {"page_id": PAGE, "mid": "m.echo", "object": "page", "event": echo},
        {"page_id": PAGE, "mid": "m.2", "object": "page", "event": second},
    ]


def test_rows_from_payload_instagram_object_is_kept():
    rows = inbox.rows_from_payload(_payload(_msg("m.ig"), obj="instagram"))
    assert [(r["object"], r["mid"]) for r in rows] == [("instagram", "m.ig")]


def test_rows_from_payload_same_page_and_mid_twice_in_one_payload_is_one_row():
    data = _payload(_msg("m.1"), _msg("m.1", text="retry"), _msg("m.2"))
    assert [r["mid"] for r in inbox.rows_from_payload(data)] == ["m.1", "m.2"]


def test_rows_from_payload_same_mid_on_different_pages_is_two_rows():
    data = {"object": "page", "entry": [
        {"id": "111", "messaging": [_msg("m.1")]},
        {"id": "222", "messaging": [_msg("m.1")]},
    ]}
    assert [(r["page_id"], r["mid"]) for r in inbox.rows_from_payload(data)] == [("111", "m.1"), ("222", "m.1")]


@pytest.mark.parametrize("entry_id", ["", "abc", "12 34", "-5", "1" * 33, None, True, 1.5, ["1"]])
def test_rows_from_payload_rejects_bad_entry_ids(entry_id):
    assert inbox.rows_from_payload(_payload(_msg("m.1"), entry_id=entry_id)) == []


def test_rows_from_payload_accepts_numeric_entry_id_and_32_digits():
    assert [r["page_id"] for r in inbox.rows_from_payload(_payload(_msg("m.1"), entry_id=42))] == ["42"]
    long_id = "9" * 32
    assert [r["page_id"] for r in inbox.rows_from_payload(_payload(_msg("m.1"), entry_id=long_id))] == [long_id]


@pytest.mark.parametrize("mid", [None, "", 5, ["m"], "m" * 201])
def test_rows_from_payload_skips_missing_or_invalid_mid(mid):
    event = {"sender": {"id": "555"}, "message": {"mid": mid, "text": "x"}}
    assert inbox.rows_from_payload(_payload(event)) == []


def test_rows_from_payload_mid_of_exactly_200_chars_is_kept():
    assert len(inbox.rows_from_payload(_payload(_msg("m" * 200)))) == 1


@pytest.mark.parametrize("data", [
    None, [], "x", 5,
    {}, {"object": "user", "entry": []}, {"object": "page"}, {"object": "page", "entry": "x"},
    {"object": "page", "entry": [None, 5, "x", {"id": PAGE}, {"id": PAGE, "messaging": "x"}]},
    {"object": "page", "entry": [{"id": PAGE, "messaging": [None, 5, "x", {"message": "x"}, {"message": None}]}]},
])
def test_rows_from_payload_malformed_payloads_give_no_rows_and_do_not_raise(data):
    assert inbox.rows_from_payload(data) == []


# ---------------------------------------------------------------- enqueue

def test_enqueue_upserts_with_db_dedup_kwargs():
    db = FakeSupabase()
    rows = inbox.rows_from_payload(_payload(_msg("m.1"), _msg("m.2")))
    inbox.enqueue(db, rows)
    (call,) = db.calls_for("webhook_inbox", "upsert")
    assert call.payload == rows
    assert call.kwargs == {"on_conflict": "page_id,mid", "ignore_duplicates": True}


def test_enqueue_without_rows_does_not_touch_the_database():
    db = FakeSupabase()
    inbox.enqueue(db, [])
    assert db.calls == []


def test_enqueue_database_error_propagates():
    db = FakeSupabase()
    db.errors[("webhook_inbox", "upsert")] = Boom("db down")
    with pytest.raises(Boom):
        inbox.enqueue(db, inbox.rows_from_payload(_payload(_msg("m.1"))))


# ---------------------------------------------------------------- claim

def test_claim_calls_the_rpc_with_settings_and_returns_data():
    db = FakeSupabase()
    row = {"id": 7, "page_id": PAGE, "mid": "m.1", "attempts": 1, "event": _msg("m.1")}
    db.rpc_responses["claim_webhook_events"] = [row]
    assert inbox.claim(db, 5) == [row]
    (call,) = db.rpc_calls
    s = get_settings()
    assert call.fn == "claim_webhook_events"
    assert call.params == {"p_limit": 5, "p_stale_seconds": 180, "p_max_attempts": 3}
    assert (s.webhook_claim_stale_seconds, s.webhook_max_attempts) == (180, 3)


def test_claim_uses_configured_stale_and_max_attempts(monkeypatch):
    s = get_settings().model_copy(update={"webhook_claim_stale_seconds": 600, "webhook_max_attempts": 5})
    monkeypatch.setattr(inbox, "get_settings", lambda: s)
    db = FakeSupabase()
    inbox.claim(db, 1)
    assert db.rpc_calls[0].params == {"p_limit": 1, "p_stale_seconds": 600, "p_max_attempts": 5}


@pytest.mark.parametrize("data", [None, "x", {"id": 1}])
def test_claim_unexpected_result_shape_is_empty(data):
    db = FakeSupabase()
    db.rpc_responses["claim_webhook_events"] = data
    assert inbox.claim(db, 5) == []


def test_claim_missing_function_raises(caplog):
    db = FakeSupabase()
    db.rpc_errors["claim_webhook_events"] = RpcMissing("could not find the function")
    with caplog.at_level(logging.WARNING, logger="app"):
        with pytest.raises(RpcMissing):
            inbox.claim(db, 5)
        with pytest.raises(RpcMissing):
            inbox.claim(db, 5)  # no "once per process" state: every poll sees the error
    assert len(db.rpc_calls) == 2
    assert _warnings(caplog) == []  # claim itself logs nothing - the worker logs the class


def test_claim_other_error_propagates():
    db = FakeSupabase()
    db.rpc_errors["claim_webhook_events"] = Boom("db down")
    with pytest.raises(Boom):
        inbox.claim(db, 5)


# ---------------------------------------------------------------- complete

def test_complete_marks_done_and_drops_the_event():
    db = FakeSupabase()
    before = datetime.now(timezone.utc)
    inbox.complete(db, 42)
    (call,) = db.calls_for("webhook_inbox", "update")
    assert call.filters == [("eq", "id", 42)]
    assert call.payload["status"] == "done"
    assert call.payload["event"] is None
    assert call.payload["last_error"] is None
    assert set(call.payload) == {"status", "event", "processed_at", "last_error"}
    assert before - timedelta(seconds=1) <= _iso(call.payload["processed_at"]) <= datetime.now(timezone.utc)


def test_complete_database_error_propagates():
    db = FakeSupabase()
    db.errors[("webhook_inbox", "update")] = Boom("db down")
    with pytest.raises(Boom):
        inbox.complete(db, 1)


# ---------------------------------------------------------------- fail

@pytest.mark.parametrize("attempts,delay", [(1, 30), (2, 60)])
def test_fail_before_the_last_attempt_requeues_with_exponential_backoff(attempts, delay):
    db = FakeSupabase()
    row = {"id": 9, "page_id": PAGE, "attempts": attempts}
    inbox.fail(db, row, Boom(SECRET))
    (call,) = db.calls_for("webhook_inbox", "update")
    assert call.filters == [("eq", "id", 9)]
    assert call.payload["status"] == "pending"
    assert call.payload["claimed_at"] is None
    assert call.payload["last_error"] == "Boom"
    expected = datetime.now(timezone.utc) + timedelta(seconds=delay)
    assert abs((_iso(call.payload["next_attempt_at"]) - expected).total_seconds()) <= 5
    assert set(call.payload) == {"status", "claimed_at", "next_attempt_at", "last_error"}


def test_fail_on_the_last_attempt_is_final_with_one_warning(caplog):
    db = FakeSupabase()
    row = {"id": 9, "page_id": PAGE, "attempts": 3, "event": _msg("m.1", text=SECRET)}
    with caplog.at_level(logging.WARNING, logger="app"):
        inbox.fail(db, row, Boom(SECRET))
    (call,) = db.calls_for("webhook_inbox", "update")
    assert call.payload == {"status": "failed", "last_error": "Boom"}
    assert call.filters == [("eq", "id", 9)]
    (warning,) = _warnings(caplog)
    assert "9" in warning and PAGE in warning and "Boom" in warning


def test_fail_respects_the_configured_max_attempts(monkeypatch):
    s = get_settings().model_copy(update={"webhook_max_attempts": 5})
    monkeypatch.setattr(inbox, "get_settings", lambda: s)
    db = FakeSupabase()
    inbox.fail(db, {"id": 1, "page_id": PAGE, "attempts": 3}, Boom())
    inbox.fail(db, {"id": 1, "page_id": PAGE, "attempts": 5}, Boom())
    first, second = [c.payload["status"] for c in db.calls_for("webhook_inbox", "update")]
    assert (first, second) == ("pending", "failed")


def test_fail_never_stores_or_logs_exception_text_payload_or_psid(caplog):
    db = FakeSupabase()
    event = _msg("m.1", sender="987654321", text=SECRET)
    with caplog.at_level(logging.DEBUG, logger="app"):
        inbox.fail(db, {"id": 1, "page_id": PAGE, "attempts": 1, "event": event}, Boom(SECRET))
        inbox.fail(db, {"id": 2, "page_id": PAGE, "attempts": 3, "event": event}, Boom(SECRET))
    stored = json.dumps([c.payload for c in db.calls])
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for text in (stored, logged):
        assert "secret" not in text and "987654321" not in text and SECRET not in text


def test_fail_truncates_a_very_long_exception_class_name():
    db = FakeSupabase()
    long_exc = type("E" * 300, (Exception,), {})
    inbox.fail(db, {"id": 1, "page_id": PAGE, "attempts": 3}, long_exc("x"))
    assert len(db.calls[0].payload["last_error"]) == 200


# ---------------------------------------------------------------- conversation_key

def test_conversation_key_is_page_and_sender_for_a_message():
    row = {"page_id": PAGE, "event": _msg("m.1", sender="555")}
    assert inbox.conversation_key(row) == (PAGE, "555")


def test_conversation_key_is_page_and_recipient_for_an_echo():
    event = {"sender": {"id": PAGE}, "recipient": {"id": "555"}, "message": {"mid": "m.e", "is_echo": True}}
    assert inbox.conversation_key({"page_id": PAGE, "event": event}) == (PAGE, "555")


@pytest.mark.parametrize("event", [None, {}, {"message": "x"}, {"sender": "x"}])
def test_conversation_key_tolerates_missing_parts(event):
    assert inbox.conversation_key({"page_id": PAGE, "event": event}) == (PAGE, None)


# ---------------------------------------------------------------- wake

def test_wake_calls_the_registered_waker():
    calls = []
    inbox.set_waker(lambda: calls.append(1))
    inbox.wake()
    inbox.wake()
    assert calls == [1, 1]


def test_wake_without_a_waker_is_a_noop():
    inbox.wake()


def test_wake_after_unregistering_does_nothing():
    calls = []
    inbox.set_waker(lambda: calls.append(1))
    inbox.set_waker(None)
    inbox.wake()
    assert calls == []


def test_wake_never_raises_and_logs_only_the_class(caplog):
    def broken():
        raise Boom(SECRET)

    inbox.set_waker(broken)
    with caplog.at_level(logging.WARNING, logger="app"):
        inbox.wake()
    (warning,) = _warnings(caplog)
    assert "Boom" in warning and "secret" not in warning


# ---------------------------------------------------------------- bot_limiter

def test_bot_limiter_has_the_configured_capacity_and_is_shared():
    async def main():
        first = inbox.bot_limiter()
        return first, inbox.bot_limiter()

    first, second = anyio.run(main)
    assert isinstance(first, anyio.CapacityLimiter)
    assert first.total_tokens == 8
    assert second is first


def test_bot_limiter_follows_bot_max_concurrency(monkeypatch):
    s = get_settings().model_copy(update={"bot_max_concurrency": 3})
    monkeypatch.setattr(inbox, "get_settings", lambda: s)

    async def main():
        return inbox.bot_limiter().total_tokens

    assert anyio.run(main) == 3


def test_reset_for_tests_drops_the_limiter_and_waker():
    async def main():
        return inbox.bot_limiter()

    first = anyio.run(main)
    inbox.set_waker(lambda: None)
    inbox._reset_for_tests()
    assert inbox._waker is None
    assert anyio.run(main) is not first
