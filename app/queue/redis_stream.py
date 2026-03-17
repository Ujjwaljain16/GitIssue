import json
import logging

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

r = redis.Redis.from_url(settings.redis_url, decode_responses=True)


async def init_stream() -> None:
    try:
        await r.xgroup_create(
            name=settings.redis_stream,
            groupname=settings.redis_group,
            id="0",
            mkstream=True,
        )
        logger.info("redis_group_created", extra={"stream": settings.redis_stream, "group": settings.redis_group})
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def push_event(data: dict) -> str:
    message_id = await r.xadd(settings.redis_stream, {"data": json.dumps(data)})
    logger.info("event_queued", extra={"message_id": message_id, "event_type": data.get("event_type")})
    return str(message_id)


async def read_group(consumer: str, count: int, block_ms: int):
    return await r.xreadgroup(
        groupname=settings.redis_group,
        consumername=consumer,
        streams={settings.redis_stream: ">"},
        count=count,
        block=block_ms,
    )


async def ack_event(message_id: str) -> int:
    return await r.xack(settings.redis_stream, settings.redis_group, message_id)


async def reclaim_stale_messages(consumer: str, min_idle_ms: int, count: int) -> list[tuple[str, dict]]:
    next_id, messages, _deleted = await r.xautoclaim(
        name=settings.redis_stream,
        groupname=settings.redis_group,
        consumername=consumer,
        min_idle_time=min_idle_ms,
        start_id="0-0",
        count=count,
    )
    if messages:
        logger.info("messages_reclaimed", extra={"count": len(messages), "next_id": next_id})
    return messages


async def pending_delivery_count(message_id: str) -> int:
    pending = await r.xpending_range(
        name=settings.redis_stream,
        groupname=settings.redis_group,
        min=message_id,
        max=message_id,
        count=1,
    )
    if not pending:
        return 0

    first = pending[0]
    if isinstance(first, dict):
        return int(first.get("times_delivered", 0))
    return int(getattr(first, "times_delivered", 0))


async def push_dead_letter(message_id: str, message_data: dict, reason: str) -> str:
    payload = {
        "reason": reason,
        "source_stream": settings.redis_stream,
        "original_message_id": message_id,
        "data": json.dumps(message_data),
    }
    dead_letter_id = await r.xadd(settings.redis_dead_letter_stream, payload)
    logger.warning("dead_lettered", extra={"message_id": message_id, "dead_letter_id": dead_letter_id, "reason": reason})
    return str(dead_letter_id)


async def queue_size() -> int:
    return await r.xlen(settings.redis_stream)


async def pending_size() -> int:
    info = await r.xpending(settings.redis_stream, settings.redis_group)
    return int(info.get("pending", 0))


async def close_redis() -> None:
    await r.aclose()
