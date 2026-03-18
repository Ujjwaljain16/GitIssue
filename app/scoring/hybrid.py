"""Hybrid scoring system: normalize and combine multiple signals."""

import re
from typing import Optional

import nltk
from nltk.corpus import stopwords


# Download NLTK data (idempotent)
try:
    stopwords.words('english')
except LookupError:
    nltk.download('stopwords', quiet=True)


def cosine_to_unit(cosine_score: float) -> float:
    """
    Convert cosine similarity [-1, 1] to unit [0, 1].
    cosine=1 (identical) → 1.0
    cosine=0 (orthogonal) → 0.5
    cosine=-1 (opposite) → 0.0
    """
    return (cosine_score + 1) / 2


def extract_tokens(text: str) -> set[str]:
    """Extract meaningful tokens (no stopwords, lowercase, alphanumeric only)."""
    stop_words = set(stopwords.words('english'))
    tokens = re.findall(r'\b[a-z0-9]+\b', text.lower())
    return {t for t in tokens if t not in stop_words and len(t) > 2}


def keyword_overlap_score(text_a: str, text_b: str) -> float:
    """
    Compute keyword overlap as Jaccard similarity.
    Range: [0, 1]
    """
    if not text_a or not text_b:
        return 0.0
    
    tokens_a = extract_tokens(text_a)
    tokens_b = extract_tokens(text_b)
    
    if not tokens_a or not tokens_b:
        return 0.0
    
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    
    return intersection / union if union > 0 else 0.0


def extract_file_paths(text: str) -> set[str]:
    """Extract file paths from text (e.g., 'src/main.py', 'lib/utils.ts')."""
    pattern = r'([a-zA-Z0-9_./\-]+\.[a-zA-Z0-9]+)'
    return set(re.findall(pattern, text))


def extract_error_patterns(text: str) -> set[str]:
    """Extract error/exception patterns (e.g., 'NullPointerException', 'TypeError')."""
    pattern = r'\b([A-Z][a-zA-Z]*(?:Error|Exception|Warning))\b'
    return set(re.findall(pattern, text))


def structural_similarity(text_a: str, text_b: str) -> float:
    """
    Jaccard similarity on extracted file paths and error patterns.
    Range: [0, 1]
    """
    files_a = extract_file_paths(text_a)
    files_b = extract_file_paths(text_b)
    errors_a = extract_error_patterns(text_a)
    errors_b = extract_error_patterns(text_b)
    
    combined_a = files_a | errors_a
    combined_b = files_b | errors_b
    
    if not combined_a or not combined_b:
        return 0.0
    
    intersection = len(combined_a & combined_b)
    union = len(combined_a | combined_b)
    
    return intersection / union if union > 0 else 0.0


def _signals_to_structural_set(signals: Optional[dict]) -> set[str]:
    if not signals:
        return set()

    file_paths = signals.get("file_paths") or []
    errors = signals.get("error_messages") or []
    stack_trace = signals.get("stack_trace")
    has_stack_trace = bool(signals.get("has_stack_trace")) or bool(stack_trace)

    tokens = set(file_paths) | set(errors)
    if has_stack_trace:
        tokens.add("__stack_trace__")
    return tokens


def structural_similarity_from_signals(
    signals_a: Optional[dict],
    signals_b: Optional[dict],
) -> float:
    set_a = _signals_to_structural_set(signals_a)
    set_b = _signals_to_structural_set(signals_b)

    if not set_a or not set_b:
        return 0.0

    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def label_similarity(labels_a: Optional[list[str]], labels_b: Optional[list[str]]) -> float:
    """
    Jaccard similarity on labels.
    Range: [0, 1]
    """
    if not labels_a or not labels_b:
        return 0.0
    
    set_a = set(labels_a)
    set_b = set(labels_b)
    
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    
    return intersection / union if union > 0 else 0.0


def compute_hybrid_score(
    semantic_score: float,
    text_a: str,
    text_b: str,
    labels_a: Optional[list[str]],
    labels_b: Optional[list[str]],
    signals_a: Optional[dict] = None,
    signals_b: Optional[dict] = None,
    weights: Optional[dict] = None
) -> float:
    """
    Compute final hybrid score combining multiple signals.
    
    Default weights:
    - semantic: 0.5 (vector similarity)
    - keyword: 0.2 (text overlap)
    - structural: 0.2 (file paths, errors)
    - label: 0.1 (label overlap)
    
    Args:
        semantic_score: Already-computed cosine similarity (before unit conversion)
        text_a: Candidate issue text
        text_b: Query issue text
        labels_a: Candidate labels
        labels_b: Query labels
        weights: Optional custom weights
        
    Returns:
        Final score in [0, 1]
    """
    if weights is None:
        weights = {
            "semantic": 0.5,
            "keyword": 0.2,
            "structural": 0.2,
            "label": 0.1
        }
    
    # Convert cosine to unit and clamp
    semantic = max(0.0, min(1.0, cosine_to_unit(semantic_score)))
    keyword = keyword_overlap_score(text_a, text_b)
    structural = (
        structural_similarity_from_signals(signals_a, signals_b)
        if signals_a is not None and signals_b is not None
        else structural_similarity(text_a, text_b)
    )
    label = label_similarity(labels_a, labels_b)
    
    # Weighted sum
    score = (
        weights["semantic"] * semantic +
        weights["keyword"] * keyword +
        weights["structural"] * structural +
        weights["label"] * label
    )
    
    # Clamp to [0, 1]
    return max(0.0, min(1.0, score))


def compute_all_scores(
    semantic_score: float,
    text_a: str,
    text_b: str,
    labels_a: Optional[list[str]],
    labels_b: Optional[list[str]],
    signals_a: Optional[dict] = None,
    signals_b: Optional[dict] = None,
    weights: Optional[dict] = None
) -> dict:
    """
    Compute all score components and return as a dict.
    Useful for feedback logging.
    
    Returns:
        Dict with keys: semantic, keyword, structural, label, final
    """
    if weights is None:
        weights = {"semantic": 0.5, "keyword": 0.2, "structural": 0.2, "label": 0.1}

    semantic = max(0.0, min(1.0, cosine_to_unit(semantic_score)))
    keyword = keyword_overlap_score(text_a, text_b)
    structural = (
        structural_similarity_from_signals(signals_a, signals_b)
        if signals_a is not None and signals_b is not None
        else structural_similarity(text_a, text_b)
    )
    label = label_similarity(labels_a, labels_b)

    final = max(0.0, min(1.0,
        weights["semantic"] * semantic +
        weights["keyword"] * keyword +
        weights["structural"] * structural +
        weights["label"] * label
    ))

    return {
        "semantic": semantic,
        "keyword": keyword,
        "structural": structural,
        "label": label,
        "final": final,
    }
