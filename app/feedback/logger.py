"""Logging of duplicate suggestions for future feedback and learning."""

import logging
from typing import Optional

from app.db import get_db_pool

logger = logging.getLogger(__name__)


async def setup_feedback_table() -> None:
    """Create duplicate_suggestions feedback table (idempotent)."""
    pool = get_db_pool()
    
    query = """
    CREATE TABLE IF NOT EXISTS duplicate_suggestions (
        id SERIAL PRIMARY KEY,
        source_issue_external_id TEXT NOT NULL,
        suggested_issue_external_id TEXT NOT NULL,
        semantic_score FLOAT,
        keyword_score FLOAT,
        structural_score FLOAT,
        label_score FLOAT,
        final_score FLOAT NOT NULL,
        suggested_at TIMESTAMP DEFAULT NOW(),
        user_feedback TEXT,
        feedback_at TIMESTAMP,
        UNIQUE(source_issue_external_id, suggested_issue_external_id)
    )
    """
    
    async with pool.acquire() as conn:
        await conn.execute(query)


async def log_suggestion(
    source_issue_external_id: str,
    suggested_issue_external_id: str,
    semantic_score: float,
    keyword_score: float,
    structural_score: float,
    label_score: float,
    final_score: float
) -> None:
    """
    Log a duplicate suggestion for analytics and learning.
    
    Args:
        source_issue_external_id: Issue that generated the suggestion
        suggested_issue_external_id: Suggested duplicate
        semantic_score: Vector similarity score
        keyword_score: Keyword overlap score
        structural_score: File path/error similarity
        label_score: Label similarity score
        final_score: Final weighted score
    """
    pool = get_db_pool()
    
    query = """
    INSERT INTO duplicate_suggestions (
        source_issue_external_id,
        suggested_issue_external_id,
        semantic_score,
        keyword_score,
        structural_score,
        label_score,
        final_score
    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
    ON CONFLICT (source_issue_external_id, suggested_issue_external_id)
    DO UPDATE SET
        final_score = $7,
        suggested_at = NOW()
    """
    
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                query,
                source_issue_external_id,
                suggested_issue_external_id,
                semantic_score,
                keyword_score,
                structural_score,
                label_score,
                final_score
            )
        logger.debug(
            "suggestion_logged",
            extra={
                "source": source_issue_external_id,
                "suggested": suggested_issue_external_id,
                "final_score": final_score
            }
        )
    except Exception:
        logger.exception("failed_to_log_suggestion")


async def log_suggestions_batch(suggestions_data: list[dict]) -> None:
    """
    Log multiple suggestions in batch.
    
    Args:
        suggestions_data: List of dicts with keys:
            - source_issue_external_id
            - suggested_issue_external_id
            - semantic_score
            - keyword_score
            - structural_score
            - label_score
            - final_score
    """
    for item in suggestions_data:
        await log_suggestion(
            source_issue_external_id=item["source_issue_external_id"],
            suggested_issue_external_id=item["suggested_issue_external_id"],
            semantic_score=item.get("semantic_score", 0.0),
            keyword_score=item.get("keyword_score", 0.0),
            structural_score=item.get("structural_score", 0.0),
            label_score=item.get("label_score", 0.0),
            final_score=item["final_score"]
        )


async def record_user_feedback(
    source_issue_external_id: str,
    suggested_issue_external_id: str,
    feedback: str  # "correct", "incorrect", "not_applicable"
) -> None:
    """
    Record user feedback on a suggestion (for future model training).
    
    Args:
        source_issue_external_id: Original issue
        suggested_issue_external_id: Suggested issue
        feedback: One of "correct", "incorrect", "not_applicable"
    """
    pool = get_db_pool()
    
    query = """
    UPDATE duplicate_suggestions
    SET user_feedback = $1, feedback_at = NOW()
    WHERE source_issue_external_id = $2
      AND suggested_issue_external_id = $3
    """
    
    try:
        async with pool.acquire() as conn:
            await conn.execute(query, feedback, source_issue_external_id, suggested_issue_external_id)
        logger.info(
            "user_feedback_recorded",
            extra={
                "source": source_issue_external_id,
                "suggested": suggested_issue_external_id,
                "feedback": feedback
            }
        )
    except Exception:
        logger.exception("failed_to_record_feedback")


async def get_suggestion_analytics(repo: Optional[str] = None, limit: int = 100) -> list[dict]:
    """
    Retrieve suggestion analytics for a repo (or all if repo=None).
    
    Returns:
        List of suggestion records with feedback
    """
    pool = get_db_pool()
    
    if repo:
        # In this simplified version, we don't have repo info in duplicate_suggestions table
        # In production, you'd join with issues table to filter by repo
        query = """
        SELECT * FROM duplicate_suggestions
        ORDER BY suggested_at DESC
        LIMIT $1
        """
        results = await pool.fetch(query, limit)
    else:
        query = """
        SELECT * FROM duplicate_suggestions
        ORDER BY suggested_at DESC
        LIMIT $1
        """
        results = await pool.fetch(query, limit)
    
    return [dict(r) for r in results]
