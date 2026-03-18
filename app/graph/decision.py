from dataclasses import dataclass

ATTACH_THRESHOLD = 0.70
RELATED_THRESHOLD = 0.80
MERGE_THRESHOLD = 0.90


@dataclass
class NodeDecision:
    action: str
    adjusted_score: float


def apply_repo_tier_adjustment(raw_score: float, source_repo: str, candidate_repo: str) -> float:
    """Adjust score by repo similarity tier to reduce cross-repo false positives."""
    adjusted = raw_score

    if source_repo == candidate_repo:
        return adjusted

    source_org = source_repo.split("/")[0] if "/" in source_repo else source_repo
    candidate_org = candidate_repo.split("/")[0] if "/" in candidate_repo else candidate_repo

    if source_org == candidate_org:
        adjusted -= 0.10
    else:
        adjusted -= 0.20
        # Extra guardrail for cross-org merges.
        if raw_score < 0.95:
            adjusted = min(adjusted, MERGE_THRESHOLD - 0.01)

    return max(0.0, min(1.0, adjusted))


def classify_node_action(adjusted_score: float) -> NodeDecision:
    """Classify score into node action following Week 3 policy."""
    if adjusted_score < ATTACH_THRESHOLD:
        return NodeDecision(action="create_new", adjusted_score=adjusted_score)
    if adjusted_score < RELATED_THRESHOLD:
        return NodeDecision(action="add_related_edge", adjusted_score=adjusted_score)
    if adjusted_score < MERGE_THRESHOLD:
        return NodeDecision(action="add_duplicate_edge", adjusted_score=adjusted_score)
    return NodeDecision(action="merge", adjusted_score=adjusted_score)
