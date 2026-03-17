"""Integration test for Week 2 duplicate suggestion pipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.suggestions.engine import suggest_duplicates, STRONG_THRESHOLD

@pytest.mark.asyncio
async def test_suggest_duplicates_end_to_end():
    """Test end-to-end suggestion pipeline with mocked retrieval."""
    
    # Mock candidate retrieval
    mock_candidates = [
        {
            "id": 101,
            "external_id": "github:owner/repo#101",
            "title": "Crash when saving file",
            "clean_body": "Getting NullPointerException in FileWriter.save()",
            "labels": ["bug", "critical"],
            "vector_score": 0.92  # Cosine similarity from vector search
        },
        {
            "id": 102,
            "external_id": "github:owner/repo#102",
            "title": "File operation timeout",
            "clean_body": "Timeout writing to disk",
            "labels": ["bug"],
            "vector_score": 0.75
        }
    ]
    
    query_issue = {
        "issue_id": 1,
        "external_id": "github:owner/repo#1",
        "repo": "owner/repo",
        "title": "Save button crashes app",
        "clean_body": "NullPointerException at src/FileWriter.java:42",
        "labels": ["bug", "critical"]
    }
    
    # Mock the embedding, retrieval, and feedback functions
    with patch("app.suggestions.engine.generate_embedding_async") as mock_embed, \
         patch("app.suggestions.engine.retrieve_vector_candidates") as mock_vec, \
         patch("app.suggestions.engine.retrieve_fts_candidates") as mock_fts, \
         patch("app.suggestions.engine.merge_candidates") as mock_merge, \
         patch("app.suggestions.engine.log_suggestion", new_callable=AsyncMock) as mock_log:
        
        mock_embed.return_value = [0.1] * 384  # Fake embedding
        mock_vec.return_value = mock_candidates
        mock_fts.return_value = []
        mock_merge.return_value = mock_candidates
        mock_log.return_value = None
        
        # Run suggestion pipeline
        suggestions = await suggest_duplicates(
            issue_id=query_issue["issue_id"],
            external_id=query_issue["external_id"],
            repo=query_issue["repo"],
            title=query_issue["title"],
            clean_body=query_issue["clean_body"],
            labels=query_issue["labels"],
            max_suggestions=3,
            signal_gate_threshold=0.3,  # Low gate to allow test
            score_threshold=0.7  # Allow both candidates
        )
        
        # Verify suggestions returned
        assert len(suggestions) > 0
        assert suggestions[0]["score"] >= 0.7
        
        # Verify top result has expected fields
        top = suggestions[0]
        assert "external_id" in top
        assert "title" in top
        assert "score" in top
        assert "reason" in top


@pytest.mark.asyncio
async def test_suggest_duplicates_low_signal_gated():
    """Test that low-signal issues are gated and no suggestions returned."""
    
    query_issue = {
        "issue_id": 1,
        "external_id": "owner/repo:1",
        "repo": "owner/repo",
        "title": "something",
        "clean_body": "broken",  # Low signal (no errors, files, etc.)
        "labels": None
    }
    
    suggestions = await suggest_duplicates(
        issue_id=query_issue["issue_id"],
        external_id=query_issue["external_id"],
        repo=query_issue["repo"],
        title=query_issue["title"],
        clean_body=query_issue["clean_body"],
        labels=query_issue["labels"],
        signal_gate_threshold=0.3  # Standard gate
    )
    
    # Should be empty because signal strength is too low
    assert len(suggestions) == 0


@pytest.mark.asyncio
async def test_suggest_duplicates_high_signal_no_matches():
    """Test high-signal issue that retrieves no good matches."""
    
    query_issue = {
        "issue_id": 1,
        "external_id": "github:owner/repo#1",
        "repo": "owner/repo",
        "title": "NullPointerException crash",
        "clean_body": "NullPointerException at src/FileWriter.java:42 in line 42",
        "labels": ["bug"]
    }
    
    with patch("app.suggestions.engine.generate_embedding_async") as mock_embed, \
         patch("app.suggestions.engine.retrieve_vector_candidates") as mock_vec, \
         patch("app.suggestions.engine.retrieve_fts_candidates") as mock_fts, \
         patch("app.suggestions.engine.merge_candidates") as mock_merge, \
         patch("app.suggestions.engine.log_suggestion", new_callable=AsyncMock) as mock_log:
        
        mock_embed.return_value = [0.1] * 384
        # Return low-scoring candidates
        mock_vec.return_value = [{
            "id": 101,
            "external_id": "github:owner/repo#101",
            "title": "Something else",
            "clean_body": "completely unrelated",
            "labels": ["feature"],
            "vector_score": 0.4  # Too low
        }]
        mock_fts.return_value = []
        mock_merge.return_value = mock_vec.return_value
        mock_log.return_value = None
        
        suggestions = await suggest_duplicates(
            issue_id=query_issue["issue_id"],
            external_id=query_issue["external_id"],
            repo=query_issue["repo"],
            title=query_issue["title"],
            clean_body=query_issue["clean_body"],
            labels=query_issue["labels"],
            score_threshold=STRONG_THRESHOLD  # High threshold
        )
        
        # No suggestions because score is below threshold
        assert len(suggestions) == 0
