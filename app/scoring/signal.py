"""Signal strength evaluation to gate low-confidence suggestions."""

import re
from typing import Optional


def extract_error_messages(text: str) -> list[str]:
    """Extract error/exception messages from text."""
    pattern = r'\b([A-Z][a-zA-Z]*(?:Error|Exception|Warning|Failure))\b'
    return re.findall(pattern, text)


def extract_stack_trace(text: str) -> bool:
    """Check if text contains stack trace signatures (file:line patterns)."""
    pattern = r'(?:at\s+|in\s+)[^\s]+\.(?:py|js|ts|java|go|rs|cpp):\d+'
    return bool(re.search(pattern, text))


def extract_file_paths(text: str) -> list[str]:
    """Extract file paths from text."""
    pattern = r'(?:[a-z0-9_./\-]*[/\\])*[a-z0-9_]+\.[a-z0-9]+'
    return re.findall(pattern, text.lower())


def compute_signal_strength(issue_text: str, issue_labels: Optional[list[str]] = None) -> float:
    """
    Compute signal strength for an issue (0-1).
    Higher = more confident to suggest duplicates.
    
    Signals:
    - File paths: +0.3
    - Error messages: +0.3
    - Stack trace: +0.2
    - Long description (>50 words): +0.1
    
    Returns:
        Score clamped to [0, 1]
    """
    score = 0.0
    
    # File paths signal
    if extract_file_paths(issue_text):
        score += 0.3
    
    # Error messages signal
    if extract_error_messages(issue_text):
        score += 0.3
    
    # Stack trace signal
    if extract_stack_trace(issue_text):
        score += 0.2
    
    # Length signal (detailed description)
    word_count = len(issue_text.split())
    if word_count > 50:
        score += 0.1
    
    return min(score, 1.0)


def should_suggest(signal_strength: float, gate_threshold: float = 0.3) -> bool:
    """
    Determine if issue has enough signal to suggest duplicates.
    
    Args:
        signal_strength: Computed signal strength [0, 1]
        gate_threshold: Minimum strength to pass gate (default 0.3)
        
    Returns:
        True if signal strength >= threshold
    """
    return signal_strength >= gate_threshold
