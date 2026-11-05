"""S21-4 (A-040 / N-05): inbox worker (claim loop, recovery, retry, per-conversation order, bot limiter) + lifespan.

Offline: fake inbox.claim / complete / fail and fake webhook.process_inbox_row. Every test sets `stop`
and releases its blocking fakes in `finally`, so no task / thread outlives the test."""
import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager

import anyio
import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import webhook
from app.config import get_settings
from app.main import app
from app.services import inbox, inbox_worker


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _patch_settings(monkeypatch, **updates):
    s = get_settings().model_copy(update=updates)
    for module in (inbox_worker, inbox, main):
        monkeypatch.setattr(module, "get_settings", lambda: s)
    return s


@pytest.fixture(autouse=True)
def _clean_inbox(monkeypatch):
    inbox._reset_for_tests()
    # model_copy skips validation: a long poll proves that wake() / stop - not the timeout - drive the loop
    _patch_settings(monkeypatch, webhook_poll_seconds=60.0, bot_max_concurrency=4)
    yield
    inbox._reset_for_tests()


def _row(row_id, psid="u1", attempts=1):
    return {
        "id": row_id, "page_id": "100", "mid": f"m{row_id}", "object": "page", "attempts": attempts,
        "event": {"sender": {"id": psid}, "recipient": {"id": "100"}, "message": {"mid": f"m{row_id}"}},
    }


class FakeInbox:
    """claim() hands out the queued batches (a list, or an Exception to raise), then [] forever."""

    def __init__(self, monkeypatch, batches):
        self.batches = list(batches)
        self.claim_times = []
        self.completed = []
        self.failed = []
        self._lock = threading.Lock()
        monkeypatch.setattr(inbox, "claim", self.claim)
        monkeypatch.setattr(inbox, "complete", self.complete)
        monkeypatch.setattr(inbox, "fail", self.fail)

    def claim(self, sc, limit):
        with self._lock:
            self.claim_times.append(time.monotonic())
            batch = self.batches.pop(0) if self.batches else []
        if isinstance(batch, Exception):
            raise batch
        return batch

    def complete(self, sc, row_id):
        self.completed.append(row_id)

    def fail(self, sc, row, exc):
        self.failed.append((row["id"], exc))


async def _until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached in time")
        await anyio.sleep(0.01)


@asynccontextmanager
async def _running():
    stop = asyncio.Event()
    task = asyncio.create_task(inbox_worker.run(stop, sc_factory=lambda: "sc"))
    try:
        yield stop, task
    finally:
        stop.set()
        inbox.wake()
        await asyncio.wait_for(task, 5)


@pytest.mark.anyio
async def test_startup_claims_without_wake(monkeypatch):
    fake = FakeInbox(monkeypatch, [[_row(1), _row(2, psid="u2")]])
    processed = []
    monkeypatch.setattr(webhook, "process_inbox_row", lambda row: processed.append(row["id"]))
    async with _running():
        await _until(lambda: len(fake.completed) == 2)
    assert sorted(processed) == [1, 2]
    assert sorted(fake.completed) == [1, 2]
    assert fake.failed == []
    assert len(fake.claim_times) >= 1  # no wake() was ever called


@pytest.mark.anyio
async def test_processing_error_calls_fail_not_complete(monkeypatch):
    fake = FakeInbox(monkeypatch, [[_row(1), _row(2, psid="u2")]])

    def process(row):
        if row["id"] == 1:
            raise RuntimeError("psid u1 secret text")

    monkeypatch.setattr(webhook, "process_inbox_row", process)
    async with _running():
        await _until(lambda: fake.failed and fake.completed)
    assert [(rid, type(exc)) for rid, exc in fake.failed] == [(1, RuntimeError)]
    assert fake.completed == [2]


@pytest.mark.anyio
async def test_complete_and_fail_errors_are_only_warnings(monkeypatch, caplog):
    fake = FakeInbox(monkeypatch, [[_row(1), _row(2, psid="u2")]])
    attempts = []

    def complete(sc, row_id):
        attempts.append(("complete", row_id))
        raise RuntimeError("db secret")

    def fail(sc, row, exc):
        attempts.append(("fail", row["id"]))
        raise RuntimeError("db secret")

    monkeypatch.setattr(inbox, "complete", complete)
    monkeypatch.setattr(inbox, "fail", fail)

    def process(row):
        if row["id"] == 2:
            raise ValueError("boom")

    monkeypatch.setattr(webhook, "process_inbox_row", process)
    with caplog.at_level(logging.WARNING, logger="app"):
        async with _running():
            await _until(lambda: len(attempts) == 2)
            await _until(lambda: sum("failed for row" in r.getMessage() for r in caplog.records) == 2)
    assert sorted(attempts) == [("complete", 1), ("fail", 2)]
    assert "db secret" not in caplog.text
    assert fake.claim_times  # the loop survived


@pytest.mark.anyio
async def test_same_conversation_sequential_other_parallel(monkeypatch):
    FakeInbox(monkeypatch, [[_row(3, psid="u2"), _row(2, psid="u1"), _row(1, psid="u1")]])
    lock = threading.Lock()
    active = {}
    peak_total = [0]
    same_conv_overlap = [False]
    order = []
    barrier_seen = threading.Event()

    def process(row):
        key = row["event"]["sender"]["id"]
        with lock:
            active[key] = active.get(key, 0) + 1
            if active[key] > 1:
                same_conv_overlap[0] = True
            peak_total[0] = max(peak_total[0], sum(active.values()))
            if sum(active.values()) >= 2:
                barrier_seen.set()
            order.append(row["id"])
        barrier_seen.wait(0.3)  # lets the other conversation overlap
        time.sleep(0.05)
        with lock:
            active[key] -= 1

    monkeypatch.setattr(webhook, "process_inbox_row", process)
    async with _running():
        await _until(lambda: len(order) == 3 and not any(active.values()))
    assert same_conv_overlap[0] is False
    assert peak_total[0] >= 2  # u1 and u2 overlapped
    assert [i for i in order if i in (1, 2)] == [1, 2]  # id order inside the conversation


@pytest.mark.anyio
async def test_bot_work_runs_on_dedicated_limiter(monkeypatch):
    s = get_settings().model_copy(update={"webhook_poll_seconds": 60.0, "bot_max_concurrency": 2})
    for module in (inbox_worker, inbox):
        monkeypatch.setattr(module, "get_settings", lambda: s)
    FakeInbox(monkeypatch, [[_row(1, psid="u1"), _row(2, psid="u2")]])
    release = threading.Event()
    started = []
    monkeypatch.setattr(webhook, "process_inbox_row", lambda row: (started.append(row["id"]), release.wait(5)))
    try:
        async with _running():
            await _until(lambda: len(started) == 2)
            limiter = inbox.bot_limiter()
            assert limiter.total_tokens == s.bot_max_concurrency == 2
            assert limiter.borrowed_tokens == 2  # both bot jobs hold a bot-limiter token
            # the bot limiter is exhausted, but the default one is free: panel endpoints keep their threads
            with anyio.fail_after(2):
                assert await anyio.to_thread.run_sync(lambda: 1) == 1
            release.set()
            await _until(lambda: limiter.borrowed_tokens == 0)
    finally:
        release.set()


@pytest.mark.anyio
async def test_wake_triggers_next_claim_before_poll_timeout(monkeypatch):
    fake = FakeInbox(monkeypatch, [[], [_row(7)]])
    monkeypatch.setattr(webhook, "process_inbox_row", lambda row: None)
    async with _running():
        await _until(lambda: len(fake.claim_times) == 1)
        await anyio.sleep(0.2)
        assert len(fake.claim_times) == 1  # idle: poll is 60 s
        woke_at = time.monotonic()
        inbox.wake()
        await _until(lambda: fake.completed == [7], timeout=1.0)
    assert fake.claim_times[1] - woke_at < 1.0


@pytest.mark.anyio
async def test_claim_error_warns_and_loop_continues(monkeypatch, caplog):
    _patch_settings(monkeypatch, webhook_poll_seconds=0.05, bot_max_concurrency=4)
    fake = FakeInbox(monkeypatch, [RuntimeError("db secret"), [_row(1)]])
    monkeypatch.setattr(webhook, "process_inbox_row", lambda row: None)
    with caplog.at_level(logging.WARNING, logger="app"):
        async with _running():
            await _until(lambda: fake.completed == [1])
    warned = [r for r in caplog.records if r.levelno == logging.WARNING and "RuntimeError" in r.getMessage()]
    assert len(warned) == 1
    assert "db secret" not in caplog.text


@pytest.mark.anyio
async def test_stop_ends_run_and_removes_waker(monkeypatch):
    FakeInbox(monkeypatch, [])
    stop = asyncio.Event()
    task = asyncio.create_task(inbox_worker.run(stop, sc_factory=lambda: "sc"))
    try:
        await _until(lambda: inbox._waker is not None)
        stop.set()
        await asyncio.wait_for(task, 2)  # does not wait for the 60 s poll
    finally:
        stop.set()
        if not task.done():
            task.cancel()
    assert task.done() and task.exception() is None
    assert inbox._waker is None
    inbox.wake()  # no waker: no-op


@pytest.mark.anyio
async def test_full_batch_claims_again_immediately(monkeypatch):
    # bot_max_concurrency=4 -> batch = 8; a full batch means "more rows may wait": no idle wait
    full = [_row(i, psid=f"u{i}") for i in range(1, 9)]
    fake = FakeInbox(monkeypatch, [full, [_row(9, psid="u9")]])
    monkeypatch.setattr(webhook, "process_inbox_row", lambda row: None)
    async with _running():
        await _until(lambda: len(fake.completed) == 9)
    assert len(fake.claim_times) >= 2


def test_lifespan_worker_not_started_when_inbox_disabled(monkeypatch):
    _patch_settings(monkeypatch, webhook_inbox_enabled=False)
    started = []

    async def fake_run(stop, **kwargs):
        started.append(1)
        await stop.wait()

    monkeypatch.setattr(inbox_worker, "run", fake_run)
    with TestClient(app):
        time.sleep(0.1)
    assert started == []


def test_lifespan_starts_worker_once_and_stops_it_on_exit(monkeypatch, caplog):
    _patch_settings(monkeypatch, webhook_inbox_enabled=True, bot_max_concurrency=4)
    events = []

    async def fake_run(stop, **kwargs):
        events.append("started")
        try:
            await stop.wait()
        finally:
            events.append("stopped")

    monkeypatch.setattr(inbox_worker, "run", fake_run)
    with caplog.at_level(logging.INFO, logger="app"):
        with TestClient(app):
            deadline = time.monotonic() + 3
            while "started" not in events and time.monotonic() < deadline:
                time.sleep(0.01)
            assert events == ["started"]
    assert events == ["started", "stopped"]
    assert any("webhook worker started (concurrency=4)" in r.getMessage() for r in caplog.records)


def test_lifespan_warns_when_worker_does_not_stop_in_time(monkeypatch, caplog):
    _patch_settings(monkeypatch, webhook_inbox_enabled=True)
    monkeypatch.setattr(main, "_WORKER_STOP_TIMEOUT", 0.1)
    events = []

    async def stubborn_run(stop, **kwargs):
        events.append("started")
        try:
            await asyncio.sleep(30)  # ignores `stop`; wait_for cancels it
        finally:
            events.append("cancelled")

    monkeypatch.setattr(inbox_worker, "run", stubborn_run)
    with caplog.at_level(logging.WARNING, logger="app"):
        with TestClient(app):
            deadline = time.monotonic() + 3
            while "started" not in events and time.monotonic() < deadline:
                time.sleep(0.01)
    assert events == ["started", "cancelled"]
    assert any("webhook worker did not stop in time" in r.getMessage() for r in caplog.records)
