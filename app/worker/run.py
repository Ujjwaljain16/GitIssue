import asyncio
import logging
import signal

from app.core.logging import setup_logging
from app.db.store import close_db_pool, init_db_pool
from app.queue.redis_stream import close_redis, init_stream
from app.worker.worker import run_worker

setup_logging()
logger = logging.getLogger(__name__)


async def main() -> None:
    await init_stream()
    await init_db_pool()

    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows event loop may not support add_signal_handler for all signals.
            pass

    try:
        await run_worker(stop_event=stop_event)
    finally:
        await close_redis()
        await close_db_pool()
        logger.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
