import logging

from fastapi import FastAPI

from app.api.webhook import router as webhook_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.metrics import snapshot
from app.db.store import close_db_pool, init_db_pool
from app.queue.redis_stream import close_redis, init_stream, pending_size, queue_size

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)
app.include_router(webhook_router)


@app.on_event("startup")
async def on_startup() -> None:
    await init_stream()
    await init_db_pool()
    logger.info("app_started", extra={"env": settings.app_env})


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await close_redis()
    await close_db_pool()
    logger.info("app_stopped")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> dict[str, int]:
    values = snapshot()
    values["queue_size"] = await queue_size()
    values["queue_pending"] = await pending_size()
    return values
