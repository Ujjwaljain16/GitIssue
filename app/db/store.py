import json
import logging
from pathlib import Path
from typing import Optional

import asyncpg

from app.core.config import settings
from app.normalizer.schema import IssueSignals, NormalizedIssue

_pool: Optional[asyncpg.Pool] = None
logger = logging.getLogger(__name__)


def _to_pgvector_literal(embedding: list[float]) -> str:
    if not embedding:
        raise ValueError("embedding must not be empty")
    return "[" + ",".join(f"{float(v):.10f}" for v in embedding) + "]"


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


async def upsert_issue(issue: NormalizedIssue) -> int:
    if _pool is None:
        raise RuntimeError("database pool not initialized")

    async with _pool.acquire() as conn:
        return await upsert_issue_with_conn(conn, issue)


async def upsert_issue_with_conn(conn: asyncpg.Connection, issue: NormalizedIssue) -> int:
    """Upsert issue in an existing transaction and return internal issue id."""

    query = """
    INSERT INTO issues (
        external_id, repo, issue_number, state,
        title, body, clean_body, author, labels,
        created_at, updated_at, raw_payload
    )
    VALUES (
        $1, $2, $3, $4,
        $5, $6, $7, $8, $9,
        $10::timestamptz, $11::timestamptz, $12::jsonb
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
    WHERE issues.updated_at <= EXCLUDED.updated_at
    """

    row = await conn.fetchrow(
        query + " RETURNING id",
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

    if row is not None:
        issue_id = int(row["id"])
    else:
        issue_id = await conn.fetchval("SELECT id FROM issues WHERE external_id = $1", issue.external_id)

    await upsert_issue_signals_with_conn(conn, issue_id, issue.signals)

    logger.info(
        "issue_upserted",
        extra={"external_id": issue.external_id, "repo": issue.repo, "issue_id": issue_id},
    )
    return issue_id


async def upsert_issue_signals(issue_id: int, signals: IssueSignals) -> None:
    if _pool is None:
        raise RuntimeError("database pool not initialized")

    async with _pool.acquire() as conn:
        await upsert_issue_signals_with_conn(conn, issue_id, signals)


async def upsert_issue_signals_with_conn(
    conn: asyncpg.Connection,
    issue_id: int,
    signals: IssueSignals,
) -> None:
    await conn.execute(
        """
        INSERT INTO issue_signals (
            issue_id,
            file_paths,
            error_messages,
            stack_trace,
            has_stack_trace,
            signal_strength,
            extracted_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, NOW())
        ON CONFLICT (issue_id) DO UPDATE
        SET file_paths = EXCLUDED.file_paths,
            error_messages = EXCLUDED.error_messages,
            stack_trace = EXCLUDED.stack_trace,
            has_stack_trace = EXCLUDED.has_stack_trace,
            signal_strength = EXCLUDED.signal_strength,
            extracted_at = NOW()
        """,
        issue_id,
        signals.file_paths,
        signals.error_messages,
        signals.stack_trace,
        signals.has_stack_trace,
        signals.signal_strength,
    )


async def update_embedding(external_id: str, embedding: list) -> None:
    """Update embedding for an issue (non-blocking, fire-and-forget safe)."""
    if _pool is None:
        raise RuntimeError("database pool not initialized")

    query = "UPDATE issues SET embedding = $1::vector WHERE external_id = $2"
    vector_literal = _to_pgvector_literal(embedding)
    
    async with _pool.acquire() as conn:
        await conn.execute(query, vector_literal, external_id)
    
    logger.debug("embedding_updated", extra={"external_id": external_id})
