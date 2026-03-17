"""Singleton embedding model using sentence-transformers."""

from functools import lru_cache
from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Get cached model instance (thread-safe singleton via lru_cache)."""
    return SentenceTransformer("all-MiniLM-L6-v2")
