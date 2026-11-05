"""webhook_inbox worker (A-040 / N-05): an asyncio task inside the web process (FastAPI lifespan).

Loop: claim due rows, at most as many as there are free slots (batch - rows in flight; startup: immediately -
restart recovery of pending / stale `processing` rows) -> one conversation = its events one by one in id order
(a row claimed while its conversation is running joins that queue), different conversations in parallel ->
`complete` / `fail`. A finished row frees a slot and wakes the loop - no waiting for the rest of a batch.
Bot work runs on `inbox.bot_limiter()` (BOT_MAX_CONCURRENCY threads); DB calls use anyio's default limiter,
so the panel keeps its threads.

Logs: counts / row ids / exception class names only - never payload, psid, message text.
"""
import asyncio
import logging
from collections import deque

import anyio
import anyio.to_thread

from app.api import webhook
from app.config import get_settings
from app.core.supabase_client import get_service_client
from app.services import inbox

logger = logging.getLogger("app")

_MAX_BATCH = 50  # claim_webhook_events clamps p_limit to 50 as well


def _batch_size() -> int:
    return min(_MAX_BATCH, 2 * get_settings().bot_max_concurrency)


async def _wait(timeout: float, *events: asyncio.Event) -> None:
    """Returns when any of the events is set or after `timeout` seconds."""
    with anyio.move_on_after(timeout):
        async with anyio.create_task_group() as tg:
            async def watch(ev: asyncio.Event) -> None:
                await ev.wait()
                tg.cancel_scope.cancel()

            for ev in events:
                tg.start_soon(watch, ev)


async def _finish(label: str, row_id, fn, *args) -> None:
    """complete / fail in a thread; an error is only logged - the row is retried after the stale window."""
    try:
        await anyio.to_thread.run_sync(fn, *args)
    except Exception as exc:
        logger.warning("webhook_inbox %s failed for row %s (%s)", label, row_id, type(exc).__name__)


async def _handle(sc, row: dict) -> None:
    try:
        await anyio.to_thread.run_sync(webhook.process_inbox_row, row, limiter=inbox.bot_limiter())
    except Exception as exc:
        await _finish("fail", row.get("id"), inbox.fail, sc, row, exc)
        return
    await _finish("complete", row.get("id"), inbox.complete, sc, row.get("id"))


class _InFlight:
    """Claimed rows that are not finished yet, per conversation. One consumer task per conversation drains its
    deque in order, so one long turn never holds back other conversations (no per-batch barrier). Everything
    here runs on the event loop thread, so there is no await between a deque's emptiness check and its removal."""

    def __init__(self, tg, stop: asyncio.Event, wake_ev: asyncio.Event):
        self._tg = tg
        self._stop = stop
        self._wake_ev = wake_ev
        self._queues: dict[tuple, deque[dict]] = {}
        self.rows = 0  # claimed and not finished: they occupy batch slots

    def add(self, sc, rows: list[dict]) -> None:
        for row in sorted(rows, key=lambda r: r.get("id") or 0):
            self.rows += 1
            key = inbox.conversation_key(row)
            queue = self._queues.get(key)
            if queue is not None:
                queue.append(row)  # the conversation is running: waits its turn
            else:
                self._queues[key] = deque([row])
                self._tg.start_soon(self._drain, sc, key)

    async def _drain(self, sc, key: tuple) -> None:
        queue = self._queues[key]
        try:
            while queue and not self._stop.is_set():
                row = queue.popleft()
                try:
                    await _handle(sc, row)
                finally:
                    self.rows -= 1
                    self._wake_ev.set()  # a slot is free: the loop may claim again
        finally:
            # shutdown: the unstarted rest stays `processing` and is retried after the stale window
            self.rows -= len(queue)
            del self._queues[key]


async def run(stop: asyncio.Event, *, sc_factory=get_service_client) -> None:
    loop = asyncio.get_running_loop()
    wake_ev = asyncio.Event()
    inbox.set_waker(lambda: loop.call_soon_threadsafe(wake_ev.set))
    try:
        async with anyio.create_task_group() as tg:
            in_flight = _InFlight(tg, stop, wake_ev)
            while not stop.is_set():
                free = _batch_size() - in_flight.rows
                if free > 0:
                    try:
                        sc = sc_factory()
                        rows = await anyio.to_thread.run_sync(inbox.claim, sc, free)
                    except Exception as exc:
                        logger.warning("webhook worker iteration failed (%s)", type(exc).__name__)
                        await _wait(get_settings().webhook_poll_seconds, stop)
                        wake_ev.clear()
                        continue
                    if rows:
                        logger.info("webhook worker claimed %d events", len(rows))
                        in_flight.add(sc, rows)
                    if len(rows) >= free:
                        continue  # all free slots were filled: more rows are probably waiting
                await _wait(get_settings().webhook_poll_seconds, wake_ev, stop)
                wake_ev.clear()
    finally:
        inbox.set_waker(None)
