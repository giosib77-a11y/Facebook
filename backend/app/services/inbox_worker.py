"""webhook_inbox worker (A-040 / N-05): an asyncio task inside the web process (FastAPI lifespan).

Loop: claim due rows (startup: immediately - restart recovery of pending / stale `processing` rows) ->
group by conversation -> one conversation = its events one by one in id order, different conversations in
parallel -> `complete` / `fail`. Bot work runs on `inbox.bot_limiter()` (BOT_MAX_CONCURRENCY threads); DB calls
use anyio's default limiter, so the panel keeps its threads.

Logs: counts / row ids / exception class names only - never payload, psid, message text.
"""
import asyncio
import logging

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


async def _handle_group(sc, group: list[dict], stop: asyncio.Event) -> None:
    for row in group:
        if stop.is_set():
            return  # shutdown: the rest stays `processing` and is retried after the stale window
        await _handle(sc, row)


async def _claim_and_process(sc_factory, stop: asyncio.Event, batch: int) -> int:
    sc = sc_factory()
    rows = await anyio.to_thread.run_sync(inbox.claim, sc, batch)
    if not rows:
        return 0
    logger.info("webhook worker claimed %d events", len(rows))
    groups: dict[tuple, list[dict]] = {}
    for row in sorted(rows, key=lambda r: r.get("id") or 0):
        groups.setdefault(inbox.conversation_key(row), []).append(row)
    async with anyio.create_task_group() as tg:
        for group in groups.values():
            tg.start_soon(_handle_group, sc, group, stop)
    return len(rows)


async def run(stop: asyncio.Event, *, sc_factory=get_service_client) -> None:
    loop = asyncio.get_running_loop()
    wake_ev = asyncio.Event()
    inbox.set_waker(lambda: loop.call_soon_threadsafe(wake_ev.set))
    try:
        while not stop.is_set():
            batch = _batch_size()
            try:
                count = await _claim_and_process(sc_factory, stop, batch)
            except Exception as exc:
                logger.warning("webhook worker iteration failed (%s)", type(exc).__name__)
                await _wait(get_settings().webhook_poll_seconds, stop)
                wake_ev.clear()
                continue
            if count >= batch:
                continue  # full batch: more rows are probably waiting
            await _wait(get_settings().webhook_poll_seconds, wake_ev, stop)
            wake_ev.clear()
    finally:
        inbox.set_waker(None)
