import pytest

from app.graph.decision import (
    ATTACH_THRESHOLD,
    MERGE_THRESHOLD,
    RELATED_THRESHOLD,
    apply_repo_tier_adjustment,
    classify_node_action,
)


def test_threshold_classification_boundaries():
    assert classify_node_action(ATTACH_THRESHOLD - 0.01).action == "create_new"
    assert classify_node_action(ATTACH_THRESHOLD).action == "add_related_edge"
    assert classify_node_action(RELATED_THRESHOLD).action == "add_duplicate_edge"
    assert classify_node_action(MERGE_THRESHOLD).action == "merge"


def test_repo_tier_same_repo_no_penalty():
    score = apply_repo_tier_adjustment(0.91, "acme/repo", "acme/repo")
    assert score == pytest.approx(0.91)


def test_repo_tier_same_org_penalty():
    score = apply_repo_tier_adjustment(0.91, "acme/repo-a", "acme/repo-b")
    assert score == pytest.approx(0.81)


def test_repo_tier_cross_org_penalty_blocks_easy_merge():
    score = apply_repo_tier_adjustment(0.92, "acme/repo", "other/repo")
    assert score < MERGE_THRESHOLD


def test_repo_tier_cross_org_allows_only_very_high_confidence():
    score = apply_repo_tier_adjustment(0.98, "acme/repo", "other/repo")
    assert score < MERGE_THRESHOLD
