import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    github_webhook_secret: str
    github_token: str
    redis_url: str
    redis_stream: str
    redis_group: str
    worker_consumer: str
    database_url: str
    worker_block_ms: int
    worker_batch_size: int
    worker_retry_max_attempts: int
    worker_reclaim_idle_ms: int
    worker_reclaim_count: int
    redis_dead_letter_stream: str



def _to_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default



def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "git-issue-tracker"),
        app_env=os.getenv("APP_ENV", "dev"),
        github_webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
        github_token=os.getenv("GITHUB_TOKEN", ""),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        redis_stream=os.getenv("REDIS_STREAM", "github_events"),
        redis_group=os.getenv("REDIS_GROUP", "workers"),
        worker_consumer=os.getenv("WORKER_CONSUMER", "worker-1"),
        database_url=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/issues"),
        worker_block_ms=_to_int(os.getenv("WORKER_BLOCK_MS", "5000"), 5000),
        worker_batch_size=_to_int(os.getenv("WORKER_BATCH_SIZE", "10"), 10),
        worker_retry_max_attempts=_to_int(os.getenv("WORKER_RETRY_MAX_ATTEMPTS", "5"), 5),
        worker_reclaim_idle_ms=_to_int(os.getenv("WORKER_RECLAIM_IDLE_MS", "30000"), 30000),
        worker_reclaim_count=_to_int(os.getenv("WORKER_RECLAIM_COUNT", "20"), 20),
        redis_dead_letter_stream=os.getenv("REDIS_DEAD_LETTER_STREAM", "github_events_dlq"),
    )


settings = load_settings()
