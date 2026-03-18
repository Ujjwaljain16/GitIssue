import re

from app.normalizer.schema import IssueSignals


def _unique(values: list[str]) -> list[str]:
    return sorted({v for v in values if v})


def extract_file_paths(text: str) -> list[str]:
    pattern = r'(?:[a-z0-9_./\-]*[/\\])*[a-z0-9_]+\.[a-z0-9]+'
    return _unique(re.findall(pattern, text.lower()))


def extract_error_messages(text: str) -> list[str]:
    pattern = r'\b([A-Z][a-zA-Z]*(?:Error|Exception|Warning|Failure))\b'
    return _unique(re.findall(pattern, text))


def extract_stack_trace(text: str) -> str | None:
    pattern = r'((?:at\s+|in\s+)[^\s]+\.(?:py|js|ts|java|go|rs|cpp):\d+)'
    matches = re.findall(pattern, text)
    if not matches:
        return None
    return " | ".join(_unique(matches))


def compute_signal_strength(signals: IssueSignals, issue_text: str = "") -> float:
    score = 0.0

    if signals.file_paths:
        score += 0.3
    if signals.error_messages:
        score += 0.3
    if signals.has_stack_trace:
        score += 0.2
    if issue_text and len(issue_text.split()) > 50:
        score += 0.1

    return min(score, 1.0)


def extract_signals(issue_text: str) -> IssueSignals:
    file_paths = extract_file_paths(issue_text)
    error_messages = extract_error_messages(issue_text)
    stack_trace = extract_stack_trace(issue_text)

    signals = IssueSignals(
        file_paths=file_paths,
        error_messages=error_messages,
        stack_trace=stack_trace,
        has_stack_trace=stack_trace is not None,
    )
    signals.signal_strength = compute_signal_strength(signals, issue_text)
    return signals
