"""webhook_inbox (migration 0037, A-040 / N-05): durable queue + dedup for Meta webhook events.

`receive_webhook` writes every `messaging` event that carries a `message.mid` into the table before
answering 200; the worker (`inbox_worker`) claims rows with `claim_webhook_events` (FOR UPDATE SKIP LOCKED),
runs the bot and marks them done / failed. `unique (page_id, mid)` is the dedup.

Logs never contain the psid, message text, payload or exception text - only class names, row id and page_id.
"""
import logging
import re
import threading
from datetime import datetime, timedelta, timezone

import anyio

from app.config import get_settings

logger = logging.getLogger("app")

TABLE = "webhook_inbox"
_OBJECTS = ("page", "instagram")
_PAGE_ID_RE = re.compile(r"[0-9]{1,32}")
_MAX_MID = 200
_RETRY_BASE_SECONDS = 30  # retry delay = 30 * 2^(attempts - 1)
_MAX_ERROR_LEN = 200

_lock = threading.Lock()
_waker = None
_limiter: anyio.CapacityLimiter | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def rows_from_payload(data) -> list[dict]:
    """One row per messaging event with a valid `message.mid` (echo included); everything else
    (postback / read / delivery / no mid / bad entry id) is skipped. Repeated (page_id, mid) -> once."""
    if not isinstance(data, dict) or data.get("object") not in _OBJECTS:
        return []
    entries = data.get("entry")
    if not isinstance(entries, list):
        return []
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
            continue
        page_id = str(raw_id)
        if not _PAGE_ID_RE.fullmatch(page_id):
            continue
        events = entry.get("messaging")
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            message = event.get("message")
            mid = message.get("mid") if isinstance(message, dict) else None
            if not isinstance(mid, str) or not 1 <= len(mid) <= _MAX_MID:
                continue
            if (page_id, mid) in seen:
                continue
            seen.add((page_id, mid))
            rows.append({"page_id": page_id, "mid": mid, "object": data["object"], "event": event})
    return rows


def enqueue(sc, rows: list[dict]) -> None:
    """Persists the rows; an already stored (page_id, mid) is ignored (DB dedup). Errors propagate."""
    if not rows:
        return
    sc.table(TABLE).upsert(rows, on_conflict="page_id,mid", ignore_duplicates=True).execute()


def claim(sc, limit: int) -> list[dict]:
    """Takes up to `limit` due rows (status -> processing, attempts + 1). Errors propagate (the worker logs the class
    and polls again)."""
    s = get_settings()
    res = sc.rpc("claim_webhook_events", {
        "p_limit": limit,
        "p_stale_seconds": s.webhook_claim_stale_seconds,
        "p_max_attempts": s.webhook_max_attempts,
    }).execute()
    data = getattr(res, "data", None)
    return list(data) if isinstance(data, list) else []


def complete(sc, row_id) -> None:
    """Processed: the event (PII) is dropped right away."""
    sc.table(TABLE).update({
        "status": "done", "event": None, "processed_at": _now().isoformat(), "last_error": None,
    }).eq("id", row_id).execute()


def fail(sc, row: dict, exc: BaseException) -> None:
    """Processing failed. `row["attempts"]` already counts this try (claim increments it): the last allowed
    try -> failed, otherwise back to pending with exponential backoff. Only the exception class is stored."""
    attempts = int(row.get("attempts") or 1)
    error = type(exc).__name__[:_MAX_ERROR_LEN]
    if attempts >= get_settings().webhook_max_attempts:
        payload = {"status": "failed", "last_error": error}
        logger.warning("webhook_inbox row %s failed for good (page_id=%s, %s)", row.get("id"), row.get("page_id"), error)
    else:
        delay = _RETRY_BASE_SECONDS * 2 ** (attempts - 1)
        payload = {
            "status": "pending", "claimed_at": None,
            "next_attempt_at": (_now() + timedelta(seconds=delay)).isoformat(), "last_error": error,
        }
    sc.table(TABLE).update(payload).eq("id", row["id"]).execute()


def conversation_key(row: dict) -> tuple:
    """(page_id, customer psid): the sender, or the recipient for the page's own echo."""
    event = row.get("event") or {}
    message = event.get("message")
    side = "recipient" if isinstance(message, dict) and message.get("is_echo") else "sender"
    party = event.get(side)
    return (row.get("page_id"), party.get("id") if isinstance(party, dict) else None)


def set_waker(fn) -> None:
    global _waker
    _waker = fn


def wake() -> None:
    """Nudges the worker to poll now. Never raises (the webhook must answer 200 regardless)."""
    fn = _waker
    if fn is None:
        return
    try:
        fn()
    except Exception as exc:
        logger.warning("inbox wake failed (%s)", type(exc).__name__)


def bot_limiter() -> anyio.CapacityLimiter:
    """Bot concurrency limiter (BOT_MAX_CONCURRENCY), shared by the worker and the legacy path.
    Created lazily on the first call inside a running event loop."""
    global _limiter
    if _limiter is None:
        _limiter = anyio.CapacityLimiter(get_settings().bot_max_concurrency)
    return _limiter


def _reset_for_tests() -> None:
    global _limiter, _waker
    with _lock:
        _limiter = None
        _waker = None
