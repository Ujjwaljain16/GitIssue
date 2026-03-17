"""Embeddings module for vector representation of issues."""

from app.embeddings.generator import generate_embedding_async, generate_embeddings_batch
from app.embeddings.model import get_model

__all__ = ["get_model", "generate_embedding_async", "generate_embeddings_batch"]
