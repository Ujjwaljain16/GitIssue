"""Decision engine: select and rank candidate suggestions."""

import asyncio
from typing import Optional

from app.retrieval import retrieve_vector_candidates, retrieve_fts_candidates, merge_candidates
from app.scoring import compute_all_scores, compute_signal_strength, should_suggest
from app.embeddings import generate_embedding_async
from app.feedback import log_suggestion


# Confidence thresholds
STRONG_THRESHOLD = 0.85  # Highly confident duplicate
RELATED_THRESHOLD = 0.70  # Likely duplicate


async def suggest_duplicates(
    issue_id: int,
    external_id: str,
    repo: str,
    title: str,
    clean_body: str,
    labels: Optional[list[str]],
    max_suggestions: int = 3,
    signal_gate_threshold: float = 0.3,
    score_threshold: float = STRONG_THRESHOLD
) -> list[dict]:
    """
    End-to-end duplicate suggestion pipeline.

    Args:
        issue_id: Internal issue ID (for exclusion)
        external_id: External issue ID (for tracking)
        repo: Repository name
        title: Issue title
        clean_body: Cleaned issue body
        labels: Issue labels
        max_suggestions: Max candidates to return
        signal_gate_threshold: Min signal strength to proceed
        score_threshold: Min final score to include suggestion

    Returns:
        List of suggested duplicate issues, sorted by score DESC.
        Each item: {id, external_id, title, score, reason}
    """

    # Gate 1: Signal strength
    signal_strength = compute_signal_strength(clean_body, labels)
    if not should_suggest(signal_strength, signal_gate_threshold):
        return []

    # Generate embedding for query
    query_text = f"{title} {clean_body}"
    query_embedding = await generate_embedding_async(query_text)

    # Retrieve candidates (hybrid: vector + FTS)
    vector_results = await retrieve_vector_candidates(
        embedding=query_embedding,
        repo=repo,
        exclude_issue_id=issue_id,
        limit=50
    )

    fts_results = await retrieve_fts_candidates(
        query_text=clean_body,
        repo=repo,
        exclude_issue_id=issue_id,
        limit=50
    )

    candidates = merge_candidates(vector_results, fts_results)

    # Score each candidate
    scored_candidates = []
    feedback_tasks = []

    for candidate in candidates:
        semantic_score = candidate.get("vector_score", 0.0)

        scores = compute_all_scores(
            semantic_score=semantic_score,
            text_a=candidate["clean_body"],
            text_b=clean_body,
            labels_a=candidate.get("labels"),
            labels_b=labels
        )

        if scores["final"] >= score_threshold:
            scored_candidates.append({
                "id": candidate["id"],
                "external_id": candidate["external_id"],
                "title": candidate["title"],
                "score": scores["final"],
                "reason": _score_to_reason(scores["final"])
            })

        # Log every candidate scored (for analytics / future learning)
        feedback_tasks.append(log_suggestion(
            source_issue_external_id=external_id,
            suggested_issue_external_id=candidate["external_id"],
            semantic_score=scores["semantic"],
            keyword_score=scores["keyword"],
            structural_score=scores["structural"],
            label_score=scores["label"],
            final_score=scores["final"]
        ))

    # Fire feedback logging concurrently (best-effort, non-blocking)
    if feedback_tasks:
        await asyncio.gather(*feedback_tasks, return_exceptions=True)

    # Sort by score DESC and limit
    scored_candidates.sort(key=lambda x: x["score"], reverse=True)
    return scored_candidates[:max_suggestions]


def _score_to_reason(score: float) -> str:
    """Generate human-readable reason for result."""
    if score >= 0.9:
        return "very similar error pattern"
    elif score >= 0.85:
        return "similar error pattern"
    elif score >= 0.75:
        return "similar keywords and structure"
    else:
        return "related issue"
