"""Tests for signal strength gating."""

import pytest

from app.scoring.signal import (
    extract_error_messages,
    extract_stack_trace,
    extract_file_paths,
    compute_signal_strength,
    should_suggest
)


class TestErrorExtraction:
    def test_error_messages(self):
        text = "Got NullPointerException and then ValueError"
        errors = extract_error_messages(text)
        assert "NullPointerException" in errors
        assert "ValueError" in errors
    
    def test_no_errors(self):
        text = "completed successfully"
        errors = extract_error_messages(text)
        assert len(errors) == 0


class TestStackTraceExtraction:
    def test_with_stacktrace(self):
        text = """
        Traceback:
        at src/main.py:42
        in utils.ts:10
        """
        assert extract_stack_trace(text) is True
    
    def test_without_stacktrace(self):
        text = "just a normal issue"
        assert extract_stack_trace(text) is False


class TestFilePathExtraction:
    def test_multiple_paths(self):
        text = "error in src/main.py and lib/utils.ts"
        paths = extract_file_paths(text)
        assert len(paths) >= 2
    
    def test_no_paths(self):
        text = "just text without paths"
        paths = extract_file_paths(text)
        assert len(paths) == 0


class TestSignalStrength:
    def test_high_signal_with_errors_and_files(self):
        text = (
            "Getting NullPointerException in src/main.py when calling foo(). "
            "Stack trace: at src/handler.py:123. "
            "This error occurs every time we process a request."
        )
        strength = compute_signal_strength(text)
        assert strength > 0.5
    
    def test_low_signal_generic(self):
        text = "something is broken"
        strength = compute_signal_strength(text)
        assert strength < 0.3
    
    def test_high_signal_with_length(self):
        text = " ".join(["word"] * 100)  # Long description
        strength = compute_signal_strength(text)
        assert strength > 0.0
    
    def test_signal_clamped_to_01(self):
        text = (
            "NullPointerException in src/file1.py and src/file2.py "
            "RuntimeError TypeError at src/file3.py:42 "
            "Now adding lots of words to make it long. "
        )
        strength = compute_signal_strength(text)
        assert 0 <= strength <= 1.0


class TestShouldSuggest:
    def test_above_threshold(self):
        assert should_suggest(0.5, gate_threshold=0.3) is True
    
    def test_below_threshold(self):
        assert should_suggest(0.2, gate_threshold=0.3) is False
    
    def test_at_threshold(self):
        assert should_suggest(0.3, gate_threshold=0.3) is True
    
    def test_custom_threshold(self):
        assert should_suggest(0.5, gate_threshold=0.7) is False
        assert should_suggest(0.8, gate_threshold=0.7) is True
