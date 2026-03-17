"""Async embedding generation (non-blocking thread pool)."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List

from app.embeddings.model import get_model

# Thread pool for embedding generation (non-blocking)
_pool = ThreadPoolExecutor(max_workers=2)


async def generate_embedding_async(text: str) -> List[float]:
    """
    Generate embedding asynchronously using thread pool.
    
    Args:
        text: Input text to embed
        
    Returns:
        Normalized embedding vector as list (384 dimensions)
    """
    loop = asyncio.get_event_loop()
    embedding = await loop.run_in_executor(
        _pool,
        lambda: get_model().encode(text, normalize_embeddings=True)
    )
    return embedding.tolist()


async def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for multiple texts asynchronously.
    
    Args:
        texts: List of texts to embed
        
    Returns:
        List of normalized embedding vectors
    """
    loop = asyncio.get_event_loop()
    embeddings = await loop.run_in_executor(
        _pool,
        lambda: get_model().encode(texts, batch_size=64, normalize_embeddings=True)
    )
    return [emb.tolist() for emb in embeddings]
