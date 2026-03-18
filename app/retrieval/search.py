"""Vector similarity and full-text search retrieval."""

from typing import Optional

from app.db import get_db_pool


def _to_pgvector_literal(embedding: list[float]) -> str:
    """Convert embedding values to pgvector literal format: [v1,v2,...]."""
    if not embedding:
        raise ValueError("embedding must not be empty")
    return "[" + ",".join(f"{float(v):.10f}" for v in embedding) + "]"


async def retrieve_vector_candidates(
    embedding: list,
    repo: str,
    exclude_issue_id: int,
    limit: int = 50,
    days_back: int = 365
) -> list[dict]:
    """
    Retrieve similar issues using vector similarity (cosine distance).
    
    Args:
        embedding: Query embedding (384 dims)
        repo: Repository to search within
        exclude_issue_id: Issue ID to exclude from results
        limit: Max candidates to return
        days_back: Search window (days in past)
        
    Returns:
        List of candidate issues with vector_score
    """
    pool = get_db_pool()
    
    query = """
        SELECT i.id, i.external_id, i.title, i.clean_body, i.labels, i.state,
                     s.file_paths, s.error_messages, s.stack_trace, s.has_stack_trace, s.signal_strength,
           1 - (embedding <=> $1::vector) AS vector_score
        FROM issues i
        LEFT JOIN issue_signals s ON s.issue_id = i.id
        WHERE i.repo = $2
            AND i.id != $3
            AND i.created_at > NOW() - make_interval(days => $4)
            AND i.embedding IS NOT NULL
    ORDER BY embedding <=> $1::vector
    LIMIT $5
    """
    
    vector_literal = _to_pgvector_literal(embedding)
    rows = await pool.fetch(query, vector_literal, repo, exclude_issue_id, days_back, limit)
    return [dict(r) for r in rows]


async def retrieve_fts_candidates(
    query_text: str,
    repo: str,
    exclude_issue_id: int,
    limit: int = 50,
    days_back: int = 365
) -> list[dict]:
    """
    Retrieve similar issues using full-text search.
    
    Args:
        query_text: Query text to search
        repo: Repository to search within
        exclude_issue_id: Issue ID to exclude
        limit: Max candidates to return
        days_back: Search window (days in past)
        
    Returns:
        List of candidate issues from FTS
    """
    pool = get_db_pool()
    
    query = """
        SELECT i.id, i.external_id, i.title, i.clean_body, i.labels, i.state,
                     s.file_paths, s.error_messages, s.stack_trace, s.has_stack_trace, s.signal_strength
        FROM issues i
        LEFT JOIN issue_signals s ON s.issue_id = i.id
        WHERE i.repo = $1
            AND i.id != $2
            AND i.created_at > NOW() - make_interval(days => $3)
            AND to_tsvector('english', i.clean_body) @@ plainto_tsquery('english', $4)
    LIMIT $5
    """
    
    rows = await pool.fetch(query, repo, exclude_issue_id, days_back, query_text, limit)
    return [dict(r) for r in rows]


def merge_candidates(vector_results: list[dict], fts_results: list[dict]) -> list[dict]:
    """
    Merge vector and FTS candidates, deduplicating by issue ID.
    Order: vector results first (higher precision), then FTS results.
    
    Args:
        vector_results: Results from vector search
        fts_results: Results from FTS search
        
    Returns:
        Deduplicated merged list
    """
    seen = {}
    
    # Add vector results first (higher relevance)
    for r in vector_results:
        seen[r["id"]] = r
    
    # Add FTS results, skipping duplicates
    for r in fts_results:
        if r["id"] not in seen:
            seen[r["id"]] = r
    
    return list(seen.values())
