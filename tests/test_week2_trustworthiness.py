import time
from unittest.mock import AsyncMock, patch

import pytest

from app.retrieval.search import merge_candidates, retrieve_fts_candidates, retrieve_vector_candidates
from app.suggestions import bot as bot_module
from app.suggestions.engine import suggest_duplicates


class _FakePool:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        return self.rows


@pytest.mark.asyncio
async def test_retrieve_vector_candidates_passes_filters_and_keeps_closed_issues(monkeypatch):
    pool = _FakePool([
        {
            "id": 7,
            "external_id": "github:acme/repo#7",
            "title": "Older closed duplicate",
            "clean_body": "NullPointerException in src/main.py",
            "labels": ["bug"],
            "state": "closed",
            "vector_score": 0.91,
        }
    ])

    monkeypatch.setattr("app.retrieval.search.get_db_pool", lambda: pool)

    rows = await retrieve_vector_candidates(
        embedding=[0.1] * 384,
        repo="acme/repo",
        exclude_issue_id=99,
        limit=100,
        days_back=180,
    )

    assert len(rows) == 1
    assert rows[0]["state"] == "closed"
    assert len(pool.calls) == 1
    _, args = pool.calls[0]
    assert args[1] == "acme/repo"
    assert args[2] == 99
    assert args[3] == 180
    assert args[4] == 100


@pytest.mark.asyncio
async def test_retrieve_fts_candidates_uses_query_and_limit(monkeypatch):
    pool = _FakePool([
        {
            "id": 11,
            "external_id": "github:acme/repo#11",
            "title": "Exact stack trace match",
            "clean_body": "TypeError at src/handler.py:88",
            "labels": ["bug"],
            "state": "open",
        }
    ])

    monkeypatch.setattr("app.retrieval.search.get_db_pool", lambda: pool)

    rows = await retrieve_fts_candidates(
        query_text="TypeError src/handler.py",
        repo="acme/repo",
        exclude_issue_id=1,
        limit=50,
        days_back=365,
    )

    assert len(rows) == 1
    assert len(pool.calls) == 1
    _, args = pool.calls[0]
    assert args[0] == "acme/repo"
    assert args[1] == 1
    assert args[2] == 365
    assert args[3] == "TypeError src/handler.py"
    assert args[4] == 50


def test_merge_candidates_deduplicates_and_keeps_vector_priority():
    vector_rows = [
        {"id": 1, "external_id": "github:acme/repo#1", "title": "v1", "vector_score": 0.95},
        {"id": 2, "external_id": "github:acme/repo#2", "title": "v2", "vector_score": 0.83},
    ]
    fts_rows = [
        {"id": 2, "external_id": "github:acme/repo#2", "title": "fts2"},
        {"id": 3, "external_id": "github:acme/repo#3", "title": "fts3"},
    ]

    merged = merge_candidates(vector_rows, fts_rows)

    assert [item["id"] for item in merged] == [1, 2, 3]
    assert merged[1]["title"] == "v2"


@pytest.mark.asyncio
async def test_decision_threshold_boundary_behavior():
    candidates = [
        {
            "id": 10,
            "external_id": "github:acme/repo#10",
            "title": "almost",
            "clean_body": "NullPointerException src/main.py",
            "labels": ["bug"],
            "vector_score": 0.9,
        },
        {
            "id": 11,
            "external_id": "github:acme/repo#11",
            "title": "at-threshold",
            "clean_body": "NullPointerException src/main.py line 55",
            "labels": ["bug"],
            "vector_score": 0.9,
        },
    ]

    with patch("app.suggestions.engine.compute_signal_strength", return_value=1.0), patch(
        "app.suggestions.engine.should_suggest", return_value=True
    ), patch("app.suggestions.engine.generate_embedding_async", new=AsyncMock(return_value=[0.1] * 384)), patch(
        "app.suggestions.engine.retrieve_vector_candidates", new=AsyncMock(return_value=candidates)
    ), patch(
        "app.suggestions.engine.retrieve_fts_candidates", new=AsyncMock(return_value=[])
    ), patch(
        "app.suggestions.engine.merge_candidates", return_value=candidates
    ), patch(
        "app.suggestions.engine.log_suggestion", new=AsyncMock(return_value=None)
    ), patch(
        "app.suggestions.engine.compute_all_scores",
        side_effect=[
            {"semantic": 0.9, "keyword": 0.8, "structural": 0.7, "label": 1.0, "final": 0.84},
            {"semantic": 0.9, "keyword": 0.8, "structural": 0.7, "label": 1.0, "final": 0.85},
        ],
    ):
        result = await suggest_duplicates(
            issue_id=1,
            external_id="github:acme/repo#1",
            repo="acme/repo",
            title="crash",
            clean_body="NullPointerException at src/main.py:55",
            labels=["bug"],
            score_threshold=0.85,
        )

    assert len(result) == 1
    assert result[0]["external_id"] == "github:acme/repo#11"


@pytest.mark.asyncio
async def test_decision_top_n_limit_and_sorted_order():
    candidates = [
        {
            "id": i,
            "external_id": f"github:acme/repo#{i}",
            "title": f"candidate-{i}",
            "clean_body": "NullPointerException in src/main.py",
            "labels": ["bug"],
            "vector_score": 0.8,
        }
        for i in range(1, 6)
    ]
    finals = [0.86, 0.93, 0.88, 0.91, 0.89]

    with patch("app.suggestions.engine.compute_signal_strength", return_value=1.0), patch(
        "app.suggestions.engine.should_suggest", return_value=True
    ), patch("app.suggestions.engine.generate_embedding_async", new=AsyncMock(return_value=[0.2] * 384)), patch(
        "app.suggestions.engine.retrieve_vector_candidates", new=AsyncMock(return_value=candidates)
    ), patch(
        "app.suggestions.engine.retrieve_fts_candidates", new=AsyncMock(return_value=[])
    ), patch(
        "app.suggestions.engine.merge_candidates", return_value=candidates
    ), patch(
        "app.suggestions.engine.log_suggestion", new=AsyncMock(return_value=None)
    ), patch(
        "app.suggestions.engine.compute_all_scores",
        side_effect=[
            {"semantic": 0.8, "keyword": 0.7, "structural": 0.6, "label": 1.0, "final": score}
            for score in finals
        ],
    ):
        result = await suggest_duplicates(
            issue_id=50,
            external_id="github:acme/repo#50",
            repo="acme/repo",
            title="save crash",
            clean_body="NullPointerException src/main.py",
            labels=["bug"],
            max_suggestions=3,
            score_threshold=0.85,
        )

    assert len(result) == 3
    assert [item["score"] for item in result] == sorted([0.93, 0.91, 0.89], reverse=True)


@pytest.mark.asyncio
async def test_decision_is_deterministic_for_same_inputs():
    candidates = [
        {
            "id": 101,
            "external_id": "github:acme/repo#101",
            "title": "same-1",
            "clean_body": "ValueError at src/core.py:10",
            "labels": ["bug"],
            "vector_score": 0.9,
        },
        {
            "id": 102,
            "external_id": "github:acme/repo#102",
            "title": "same-2",
            "clean_body": "ValueError at src/core.py:12",
            "labels": ["bug"],
            "vector_score": 0.87,
        },
    ]

    score_by_id = {
        101: {"semantic": 0.9, "keyword": 0.7, "structural": 0.8, "label": 1.0, "final": 0.90},
        102: {"semantic": 0.87, "keyword": 0.6, "structural": 0.7, "label": 1.0, "final": 0.86},
    }

    def _scores(*, semantic_score, text_a, text_b, labels_a, labels_b):
        if "10" in text_a:
            return score_by_id[101]
        return score_by_id[102]

    with patch("app.suggestions.engine.compute_signal_strength", return_value=1.0), patch(
        "app.suggestions.engine.should_suggest", return_value=True
    ), patch("app.suggestions.engine.generate_embedding_async", new=AsyncMock(return_value=[0.3] * 384)), patch(
        "app.suggestions.engine.retrieve_vector_candidates", new=AsyncMock(return_value=candidates)
    ), patch(
        "app.suggestions.engine.retrieve_fts_candidates", new=AsyncMock(return_value=[])
    ), patch(
        "app.suggestions.engine.merge_candidates", return_value=candidates
    ), patch(
        "app.suggestions.engine.log_suggestion", new=AsyncMock(return_value=None)
    ), patch("app.suggestions.engine.compute_all_scores", side_effect=_scores):
        first = await suggest_duplicates(
            issue_id=99,
            external_id="github:acme/repo#99",
            repo="acme/repo",
            title="ValueError",
            clean_body="ValueError at src/core.py:10",
            labels=["bug"],
        )
        second = await suggest_duplicates(
            issue_id=99,
            external_id="github:acme/repo#99",
            repo="acme/repo",
            title="ValueError",
            clean_body="ValueError at src/core.py:10",
            labels=["bug"],
        )

    assert first == second


@pytest.mark.asyncio
async def test_feedback_logging_includes_component_scores():
    candidates = [
        {
            "id": 1,
            "external_id": "github:acme/repo#1",
            "title": "dup",
            "clean_body": "TypeError in src/a.py",
            "labels": ["bug"],
            "vector_score": 0.9,
        }
    ]
    log_mock = AsyncMock(return_value=None)

    with patch("app.suggestions.engine.compute_signal_strength", return_value=1.0), patch(
        "app.suggestions.engine.should_suggest", return_value=True
    ), patch("app.suggestions.engine.generate_embedding_async", new=AsyncMock(return_value=[0.1] * 384)), patch(
        "app.suggestions.engine.retrieve_vector_candidates", new=AsyncMock(return_value=candidates)
    ), patch(
        "app.suggestions.engine.retrieve_fts_candidates", new=AsyncMock(return_value=[])
    ), patch(
        "app.suggestions.engine.merge_candidates", return_value=candidates
    ), patch("app.suggestions.engine.log_suggestion", new=log_mock), patch(
        "app.suggestions.engine.compute_all_scores",
        return_value={"semantic": 0.91, "keyword": 0.62, "structural": 0.55, "label": 1.0, "final": 0.86},
    ):
        await suggest_duplicates(
            issue_id=10,
            external_id="github:acme/repo#10",
            repo="acme/repo",
            title="TypeError",
            clean_body="TypeError in src/a.py",
            labels=["bug"],
        )

    assert log_mock.await_count == 1
    kwargs = log_mock.await_args.kwargs
    assert kwargs["semantic_score"] == 0.91
    assert kwargs["keyword_score"] == 0.62
    assert kwargs["structural_score"] == 0.55
    assert kwargs["label_score"] == 1.0
    assert kwargs["final_score"] == 0.86


@pytest.mark.asyncio
async def test_comment_bot_idempotent_under_repeated_events():
    suggestions = [
        {
            "external_id": "github:acme/repo#21",
            "title": "Known duplicate",
            "score": 0.92,
            "reason": "similar error pattern",
        }
    ]

    has_comment = AsyncMock(side_effect=[False, True, True, True, True])
    post_comment = AsyncMock(return_value=123456)
    record_comment = AsyncMock(return_value=None)

    with patch.object(bot_module, "has_comment", new=has_comment), patch.object(
        bot_module, "post_comment_to_github", new=post_comment
    ), patch.object(bot_module, "record_comment", new=record_comment):
        outcomes = []
        for _ in range(5):
            posted = await bot_module.maybe_comment_with_suggestions(
                issue_id=5,
                external_id="github:acme/repo#5",
                repo="acme/repo",
                issue_number=5,
                suggestions=suggestions,
                github_token="token",
            )
            outcomes.append(posted)

    assert outcomes == [True, False, False, False, False]
    assert post_comment.await_count == 1
    assert record_comment.await_count == 1


@pytest.mark.asyncio
async def test_comment_bot_retry_safe_after_api_failure():
    suggestions = [
        {
            "external_id": "github:acme/repo#9",
            "title": "Known duplicate",
            "score": 0.9,
            "reason": "similar error pattern",
        }
    ]

    has_comment = AsyncMock(return_value=False)
    post_comment = AsyncMock(side_effect=[RuntimeError("api failure"), 999])
    record_comment = AsyncMock(return_value=None)

    with patch.object(bot_module, "has_comment", new=has_comment), patch.object(
        bot_module, "post_comment_to_github", new=post_comment
    ), patch.object(bot_module, "record_comment", new=record_comment):
        with pytest.raises(RuntimeError):
            await bot_module.maybe_comment_with_suggestions(
                issue_id=9,
                external_id="github:acme/repo#9",
                repo="acme/repo",
                issue_number=9,
                suggestions=suggestions,
                github_token="token",
            )

        posted = await bot_module.maybe_comment_with_suggestions(
            issue_id=9,
            external_id="github:acme/repo#9",
            repo="acme/repo",
            issue_number=9,
            suggestions=suggestions,
            github_token="token",
        )

    assert posted is True
    assert record_comment.await_count == 1


@pytest.mark.asyncio
async def test_pipeline_latency_under_two_seconds_with_100_candidates():
    candidates = [
        {
            "id": i,
            "external_id": f"github:acme/repo#{i}",
            "title": f"candidate-{i}",
            "clean_body": "NullPointerException at src/main.py",
            "labels": ["bug"],
            "vector_score": 0.9,
        }
        for i in range(1, 101)
    ]

    with patch("app.suggestions.engine.compute_signal_strength", return_value=1.0), patch(
        "app.suggestions.engine.should_suggest", return_value=True
    ), patch("app.suggestions.engine.generate_embedding_async", new=AsyncMock(return_value=[0.1] * 384)), patch(
        "app.suggestions.engine.retrieve_vector_candidates", new=AsyncMock(return_value=candidates)
    ), patch(
        "app.suggestions.engine.retrieve_fts_candidates", new=AsyncMock(return_value=[])
    ), patch(
        "app.suggestions.engine.merge_candidates", return_value=candidates
    ), patch(
        "app.suggestions.engine.log_suggestion", new=AsyncMock(return_value=None)
    ), patch(
        "app.suggestions.engine.compute_all_scores",
        return_value={"semantic": 0.9, "keyword": 0.5, "structural": 0.6, "label": 1.0, "final": 0.86},
    ):
        start = time.perf_counter()
        await suggest_duplicates(
            issue_id=300,
            external_id="github:acme/repo#300",
            repo="acme/repo",
            title="save crash",
            clean_body="NullPointerException at src/main.py:42",
            labels=["bug"],
            max_suggestions=3,
        )
        elapsed = time.perf_counter() - start

    assert elapsed < 2.0