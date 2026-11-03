"""A-026 (N-15): `_SEEN_MIDS` and the ratelimit `_HITS` are mutated under a lock."""
import threading

import pytest
from fastapi import HTTPException

from app.api import webhook
from app.core import ratelimit


class RecordingLock:
    """Context-manager lock that counts entries and tracks nesting."""

    def __init__(self):
        self._lock = threading.Lock()
        self.entered = 0
        self.held = False

    def __enter__(self):
        self._lock.acquire()
        self.entered += 1
        self.held = True
        return self

    def __exit__(self, *exc):
        self.held = False
        self._lock.release()
        return False


@pytest.fixture(autouse=True)
def _clean_state():
    last_sweep = ratelimit._last_sweep[0]
    webhook._SEEN_MIDS.clear()
    ratelimit._HITS.clear()
    yield
    webhook._SEEN_MIDS.clear()
    ratelimit._HITS.clear()
    ratelimit._last_sweep[0] = last_sweep
    for bucket in ("lk_allow", "lk_hit", "stress", "shared_bucket"):
        ratelimit._WINDOWS.pop(bucket, None)


# --- (1) structural: the lock is really used --------------------------------

def test_already_handled_takes_seen_lock(monkeypatch):
    lock = RecordingLock()
    monkeypatch.setattr(webhook, "_SEEN_LOCK", lock)
    assert webhook._already_handled("m1") is False
    assert lock.entered == 1
    assert webhook._already_handled("m1") is True
    assert lock.entered == 2


def test_already_handled_empty_mid_needs_no_lock(monkeypatch):
    lock = RecordingLock()
    monkeypatch.setattr(webhook, "_SEEN_LOCK", lock)
    assert webhook._already_handled(None) is False
    assert webhook._already_handled("") is False
    assert lock.entered == 0


def test_allow_takes_ratelimit_lock(monkeypatch):
    lock = RecordingLock()
    monkeypatch.setattr(ratelimit, "_LOCK", lock)
    assert ratelimit.allow("lk_allow", "ip1", 2, 60) is True
    assert lock.entered >= 1
    before = lock.entered
    assert ratelimit.allow("lk_allow", "ip1", 2, 60) is True
    assert ratelimit.allow("lk_allow", "ip1", 2, 60) is False
    assert lock.entered > before


def test_hit_takes_ratelimit_lock_and_raises_outside_it(monkeypatch):
    lock = RecordingLock()
    monkeypatch.setattr(ratelimit, "_LOCK", lock)
    ratelimit._hit("lk_hit", "ip1", 1, 60)
    assert lock.entered == 1
    with pytest.raises(HTTPException) as exc:
        ratelimit._hit("lk_hit", "ip1", 1, 60)
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) >= 1
    assert lock.entered == 2
    assert lock.held is False  # the 429 is raised after the lock is released


# --- (2) stress: concurrent access, forced sweep ----------------------------

THREADS = 8
PER_THREAD = 500


def _run_threads(target):
    errors: list[BaseException] = []

    def wrapper(n):
        try:
            target(n)
        except BaseException as e:  # noqa: BLE001 - collected and asserted below
            errors.append(e)

    ts = [threading.Thread(target=wrapper, args=(n,)) for n in range(THREADS)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in ts), "deadlock / hang"
    assert errors == []


def test_already_handled_concurrent_unique_mids():
    results: list[list[bool]] = [[] for _ in range(THREADS)]

    def work(n):
        for i in range(PER_THREAD):
            results[n].append(webhook._already_handled(f"t{n}-m{i}"))

    _run_threads(work)
    flat = [r for part in results for r in part]
    assert len(flat) == THREADS * PER_THREAD
    assert flat.count(False) == THREADS * PER_THREAD  # each unique mid handled once
    assert len(webhook._SEEN_MIDS) == THREADS * PER_THREAD


def test_already_handled_concurrent_same_mid_returns_false_once():
    results: list[bool] = []
    res_lock = threading.Lock()

    def work(n):
        for i in range(PER_THREAD):
            r = webhook._already_handled(f"shared-{i}")
            with res_lock:
                results.append(r)

    _run_threads(work)
    assert results.count(False) == PER_THREAD  # exactly one winner per mid


def test_allow_concurrent_with_forced_sweep(monkeypatch):
    granted: list[bool] = []
    res_lock = threading.Lock()

    def work(n):
        for i in range(PER_THREAD):
            ratelimit._last_sweep[0] = float("-inf")  # sweep on every call
            r = ratelimit.allow("stress", f"ip-{n}-{i}", 1, 60)
            with res_lock:
                granted.append(r)

    _run_threads(work)
    assert len(granted) == THREADS * PER_THREAD
    assert all(granted)  # unique keys, limit 1 -> each granted once


def test_allow_concurrent_shared_key_respects_limit():
    limit = 50
    granted: list[bool] = []
    res_lock = threading.Lock()

    def work(n):
        for _ in range(PER_THREAD):
            ratelimit._last_sweep[0] = float("-inf")
            r = ratelimit.allow("shared_bucket", "one-ip", limit, 3600)
            with res_lock:
                granted.append(r)

    _run_threads(work)
    assert granted.count(True) == limit
