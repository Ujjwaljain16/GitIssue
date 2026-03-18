import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load workspace-local .env so runtime and scripts consistently use the same config source.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


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
    enable_comments: bool
    repo_whitelist: list[str]
    max_comments_per_issue: int
    max_suggestions_per_comment: int
    min_comment_score: float
    min_signal_strength: float



def _to_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_list(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]



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
        enable_comments=_to_bool(os.getenv("ENABLE_COMMENTS", "false"), False),
        repo_whitelist=_to_list(os.getenv("REPO_WHITELIST", "")),
        max_comments_per_issue=_to_int(os.getenv("MAX_COMMENTS_PER_ISSUE", "1"), 1),
        max_suggestions_per_comment=_to_int(os.getenv("MAX_SUGGESTIONS_PER_COMMENT", "2"), 2),
        min_comment_score=_to_float(os.getenv("MIN_COMMENT_SCORE", "0.85"), 0.85),
        min_signal_strength=_to_float(os.getenv("MIN_SIGNAL_STRENGTH", "0.30"), 0.30),
    )


settings = load_settings()
