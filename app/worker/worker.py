import asyncio
import json
import logging
import time
from typing import Any

from app.core.config import settings
from app.core.metrics import inc, observe_processing_latency
from app.db.store import upsert_issue, update_embedding
from app.embeddings import generate_embedding_async
from app.normalizer.normalize import normalize
from app.queue.redis_stream import ack_event, pending_delivery_count, push_dead_letter, read_group, reclaim_stale_messages
from app.suggestions import suggest_duplicates, maybe_comment_with_suggestions

logger = logging.getLogger(__name__)

HANDLED_ACTIONS = {"opened", "edited", "reopened"}
failure_counts: dict[str, int] = {}


async def _embed_issue_async(external_id: str, title: str, body: str) -> None:
    """Fire-and-forget embedding generation and storage (non-blocking)."""
    try:
        text = f"{title} {body}"
        embedding = await generate_embedding_async(text)
        await update_embedding(external_id, embedding)
        logger.debug("embedding_generated", extra={"external_id": external_id})
    except Exception:
        logger.exception("embedding_generation_failed", extra={"external_id": external_id})


async def _suggest_and_comment_async(
    issue_id: int,
    external_id: str,
    repo: str,
    issue_number: int,
    title: str,
    clean_body: str,
    labels: list[str],
) -> None:
    """Fire-and-forget: run suggestion pipeline and post comment (non-blocking)."""
    try:
        suggestions = await suggest_duplicates(
            issue_id=issue_id,
            external_id=external_id,
            repo=repo,
            title=title,
            clean_body=clean_body,
            labels=labels,
        )
        if suggestions:
            await maybe_comment_with_suggestions(
                issue_id=issue_id,
                external_id=external_id,
                repo=repo,
                issue_number=issue_number,
                suggestions=suggestions,
                github_token=settings.github_token or None,
            )
    except Exception:
        logger.exception("suggestion_pipeline_failed", extra={"external_id": external_id})


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

    # Generate embedding async (non-blocking, fire-and-forget)
    asyncio.create_task(_embed_issue_async(normalized.external_id, normalized.title, normalized.clean_body))

    # Run suggestion + comment pipeline (non-blocking, fire-and-forget)
    # Only suggest for new issues (not edits) to avoid comment spam on every edit
    if action == "opened":
        asyncio.create_task(_suggest_and_comment_async(
            issue_id=normalized.issue_number,  # used for exclusion only
            external_id=normalized.external_id,
            repo=normalized.repo,
            issue_number=normalized.issue_number,
            title=normalized.title,
            clean_body=normalized.clean_body,
            labels=normalized.labels,
        ))


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
