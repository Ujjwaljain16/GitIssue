import asyncio
import json
import logging
import time
from typing import Any

from app.core.config import settings
from app.core.metrics import inc, observe_processing_latency
from app.db.store import upsert_issue
from app.normalizer.normalize import normalize
from app.queue.redis_stream import ack_event, pending_delivery_count, push_dead_letter, read_group, reclaim_stale_messages

logger = logging.getLogger(__name__)

HANDLED_ACTIONS = {"opened", "edited", "reopened"}
failure_counts: dict[str, int] = {}


async def process_event(data: dict[str, Any]) -> None:
    event_type = data.get("event_type", "")
    if event_type != "issues":
        return

    payload = json.loads(data["payload"])
    action = payload.get("action")
    if action not in HANDLED_ACTIONS:
        return

    normalized = normalize(payload)
    await upsert_issue(normalized)


async def run_worker(stop_event: asyncio.Event | None = None) -> None:
    consumer = settings.worker_consumer
    logger.info("worker_started", extra={"consumer": consumer})

    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("worker_stop_requested")
            break

        reclaimed_messages = await reclaim_stale_messages(
            consumer=consumer,
            min_idle_ms=settings.worker_reclaim_idle_ms,
            count=settings.worker_reclaim_count,
        )
        if reclaimed_messages:
            inc("event_reclaimed", len(reclaimed_messages))

        messages = []
        if reclaimed_messages:
            messages.append((settings.redis_stream, reclaimed_messages))
        else:
            messages = await read_group(
                consumer=consumer,
                count=settings.worker_batch_size,
                block_ms=settings.worker_block_ms,
            )

        for _, stream_messages in messages or []:
            for message_id, message_data in stream_messages:
                started = time.perf_counter()
                try:
                    data = json.loads(message_data["data"])
                    await process_event(data)
                    await ack_event(message_id)
                    inc("event_processed")
                    observe_processing_latency(int((time.perf_counter() - started) * 1000))
                    failure_counts.pop(message_id, None)
                    logger.info("event_processed", extra={"message_id": message_id})
                except Exception:
                    inc("event_failed")
                    failure_counts[message_id] = failure_counts.get(message_id, 0) + 1
                    deliveries = await pending_delivery_count(message_id)
                    if deliveries >= settings.worker_retry_max_attempts:
                        await push_dead_letter(message_id, message_data, reason="max_delivery_attempts_exceeded")
                        await ack_event(message_id)
                        inc("event_dead_lettered")
                    logger.exception("event_processing_failed", extra={"message_id": message_id})
                    # Intentionally not acking failed messages so Redis can redeliver.
