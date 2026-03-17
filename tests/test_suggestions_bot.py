"""Tests for duplicate suggestion bot."""

import pytest

from app.suggestions.bot import format_suggestion_comment


class TestFormatSuggestionComment:
    def test_empty_suggestions(self):
        comment = format_suggestion_comment([])
        assert comment == ""
    
    def test_single_suggestion(self):
        suggestions = [{
            "external_id": "github:owner/repo#42",
            "title": "Crash on save",
            "score": 0.92,
            "reason": "similar error pattern"
        }]
        comment = format_suggestion_comment(suggestions)
        
        assert "🔍" in comment
        assert "Crash on save" in comment
        assert "similar error pattern" in comment
        assert "#42" in comment
    
    def test_multiple_suggestions(self):
        suggestions = [
            {
                "external_id": "github:owner/repo#45",
                "title": "File write failure",
                "score": 0.88,
                "reason": "similar keywords"
            },
            {
                "external_id": "github:owner/repo#12",
                "title": "Write timeout",
                "score": 0.85,
                "reason": "related issue"
            }
        ]
        comment = format_suggestion_comment(suggestions)
        
        assert "File write failure" in comment
        assert "Write timeout" in comment
        assert "#45" in comment
        assert "#12" in comment
        assert "1." in comment
        assert "2." in comment
    
    def test_comment_footer(self):
        suggestions = [{
            "external_id": "github:owner/repo#10",
            "title": "Test issue",
            "score": 0.9,
            "reason": "test reason"
        }]
        comment = format_suggestion_comment(suggestions)
        
        assert "automated suggestion" in comment.lower()
        assert "review" in comment.lower()
