"""Scoring module: hybrid scoring and signal strength evaluation."""

from app.scoring.hybrid import (
    compute_hybrid_score,
    compute_all_scores,
    cosine_to_unit,
    keyword_overlap_score,
    structural_similarity,
    structural_similarity_from_signals,
    label_similarity,
)
from app.scoring.signal import compute_signal_strength, compute_signal_strength_from_signals, should_suggest

__all__ = [
    "compute_hybrid_score",
    "compute_all_scores",
    "cosine_to_unit",
    "keyword_overlap_score",
    "structural_similarity",
    "structural_similarity_from_signals",
    "label_similarity",
    "compute_signal_strength",
    "compute_signal_strength_from_signals",
    "should_suggest",
]
