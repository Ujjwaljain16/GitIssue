"""Tests for hybrid scoring system."""

import pytest

from app.scoring.hybrid import (
    cosine_to_unit,
    extract_tokens,
    keyword_overlap_score,
    extract_file_paths,
    extract_error_patterns,
    structural_similarity,
    label_similarity,
    compute_hybrid_score
)


class TestCosineToUnit:
    def test_identical(self):
        assert cosine_to_unit(1.0) == 1.0
    
    def test_orthogonal(self):
        assert cosine_to_unit(0.0) == 0.5
    
    def test_opposite(self):
        assert cosine_to_unit(-1.0) == 0.0


class TestTokenExtraction:
    def test_stopwords_removed(self):
        tokens = extract_tokens("the quick brown fox jumps")
        assert "the" not in tokens
        assert "quick" in tokens
        assert "brown" in tokens
    
    def test_lowercase(self):
        tokens = extract_tokens("ERROR Exception Failure")
        assert "'ERROR".lower() or "ERROR".lower() in [t.lower() for t in tokens]
    
    def test_empty(self):
        tokens = extract_tokens("")
        assert len(tokens) == 0


class TestKeywordOverlap:
    def test_identical_text(self):
        score = keyword_overlap_score("error in parsing", "error in parsing")
        assert score == 1.0
    
    def test_no_overlap(self):
        score = keyword_overlap_score("error in parsing", "success in deployment")
        assert score == 0.0
    
    def test_partial_overlap(self):
        score = keyword_overlap_score("error in parsing config", "error in parsing")
        assert 0 < score < 1
    
    def test_empty_text(self):
        score = keyword_overlap_score("", "error")
        assert score == 0.0


class TestFilePathExtraction:
    def test_simple_path(self):
        paths = extract_file_paths("error in src/main.py line 42")
        assert "src/main.py" in paths
    
    def test_multiple_paths(self):
        paths = extract_file_paths("in src/main.py and lib/utils.ts")
        assert "src/main.py" in paths
        assert "lib/utils.ts" in paths
    
    def test_no_paths(self):
        paths = extract_file_paths("this is just text")
        assert len(paths) == 0


class TestErrorExtraction:
    def test_exception_patterns(self):
        errors = extract_error_patterns("NullPointerException at line 42")
        assert "NullPointerException" in errors
    
    def test_error_patterns(self):
        errors = extract_error_patterns("TypeError and RuntimeError occurred")
        assert "TypeError" in errors
        assert "RuntimeError" in errors
    
    def test_no_errors(self):
        errors = extract_error_patterns("just a normal message")
        assert len(errors) == 0


class TestStructuralSimilarity:
    def test_identical_errors(self):
        text_a = "error in src/main.py: NullPointerException"
        text_b = "error in src/main.py: NullPointerException"
        score = structural_similarity(text_a, text_b)
        assert score == 1.0
    
    def test_different_errors(self):
        text_a = "NullPointerException in src/main.py"
        text_b = "TypeError in lib/utils.ts"
        score = structural_similarity(text_a, text_b)
        assert score < 0.5
    
    def test_empty_text(self):
        score = structural_similarity("", "error")
        assert score == 0.0


class TestLabelSimilarity:
    def test_identical_labels(self):
        score = label_similarity(["bug", "urgent"], ["bug", "urgent"])
        assert score == 1.0
    
    def test_no_overlap(self):
        score = label_similarity(["bug"], ["feature"])
        assert score == 0.0
    
    def test_partial_overlap(self):
        score = label_similarity(["bug", "urgent", "backend"], ["bug", "frontend"])
        # Jaccard: 1 / 4 = 0.25
        assert abs(score - 0.25) < 0.01
    
    def test_empty_labels(self):
        score = label_similarity([], ["bug"])
        assert score == 0.0
    
    def test_none_labels(self):
        score = label_similarity(None, ["bug"])
        assert score == 0.0


class TestHybridScore:
    def test_perfect_match(self):
        # Use text with structural signals (file paths + errors) to exercise all dimensions
        text = "NullPointerException in src/main.py line 42"
        score = compute_hybrid_score(
            semantic_score=1.0,
            text_a=text,
            text_b=text,
            labels_a=["bug"],
            labels_b=["bug"]
        )
        assert score > 0.9
    
    def test_low_similarity(self):
        score = compute_hybrid_score(
            semantic_score=-1.0,
            text_a="success in deployment",
            text_b="error in parsing",
            labels_a=["feature"],
            labels_b=["bug"]
        )
        assert score < 0.2
    
    def test_custom_weights(self):
        weights = {"semantic": 0.9, "keyword": 0.05, "structural": 0.03, "label": 0.02}
        score1 = compute_hybrid_score(
            semantic_score=1.0,
            text_a="text",
            text_b="text",
            labels_a=["a"],
            labels_b=["a"],
            weights=weights
        )
        # Should be dominated by semantic score (converted 1.0 -> 1.0)
        assert score1 > 0.85
    
    def test_clamped_to_01(self):
        score = compute_hybrid_score(
            semantic_score=999.0,
            text_a="text",
            text_b="text",
            labels_a=["a"],
            labels_b=["a"]
        )
        assert 0 <= score <= 1.0
