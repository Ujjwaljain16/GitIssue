import json
import logging
from pathlib import Path
from typing import Optional

import asyncpg

from app.core.config import settings
from app.normalizer.schema import NormalizedIssue

_pool: Optional[asyncpg.Pool] = None
logger = logging.getLogger(__name__)


def get_db_pool() -> asyncpg.Pool:
    """Return the active connection pool (must call init_db_pool first)."""
    if _pool is None:
        raise RuntimeError("database pool not initialized")
    return _pool


async def init_db_pool() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=1, max_size=10)
        await apply_schema()


async def close_db_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def apply_schema() -> None:
    if _pool is None:
        raise RuntimeError("database pool not initialized")

    schema_path = Path(__file__).with_name("schema.sql")
    schema_sql = schema_path.read_text(encoding="utf-8")

    async with _pool.acquire() as conn:
        await conn.execute(schema_sql)


async def upsert_issue(issue: NormalizedIssue) -> None:
    if _pool is None:
        raise RuntimeError("database pool not initialized")

    query = """
    INSERT INTO issues (
        external_id, repo, issue_number, state,
        title, body, clean_body, author, labels,
        created_at, updated_at, raw_payload
    )
    VALUES (
        $1, $2, $3, $4,
        $5, $6, $7, $8, $9,
        $10, $11, $12::jsonb
    )
    ON CONFLICT (external_id) DO UPDATE
    SET
        state = EXCLUDED.state,
        title = EXCLUDED.title,
        body = EXCLUDED.body,
        clean_body = EXCLUDED.clean_body,
        author = EXCLUDED.author,
        labels = EXCLUDED.labels,
        created_at = EXCLUDED.created_at,
        updated_at = EXCLUDED.updated_at,
        raw_payload = EXCLUDED.raw_payload
    WHERE issues.updated_at <= EXCLUDED.updated_at;
    """

    async with _pool.acquire() as conn:
        await conn.execute(
            query,
            issue.external_id,
            issue.repo,
            issue.issue_number,
            issue.state,
            issue.title,
            issue.body,
            issue.clean_body,
            issue.author,
            issue.labels,
            issue.created_at,
            issue.updated_at,
            json.dumps(issue.raw_payload),
        )
    logger.info("issue_upserted", extra={"external_id": issue.external_id, "repo": issue.repo})


async def update_embedding(external_id: str, embedding: list) -> None:
    """Update embedding for an issue (non-blocking, fire-and-forget safe)."""
    if _pool is None:
        raise RuntimeError("database pool not initialized")

    query = "UPDATE issues SET embedding = $1 WHERE external_id = $2"
    
    async with _pool.acquire() as conn:
        await conn.execute(query, embedding, external_id)
    
    logger.debug("embedding_updated", extra={"external_id": external_id})
