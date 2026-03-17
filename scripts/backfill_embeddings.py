"""Backfill embeddings for all existing issues without them."""

import asyncio
import sys
from typing import Optional

import asyncpg

from app.core.config import Settings
from app.embeddings import generate_embeddings_batch


async def backfill_embeddings(batch_size: int = 64, limit: Optional[int] = None) -> None:
    """
    Backfill embeddings for issues missing them.
    
    Args:
        batch_size: Number of issues to process per batch
        limit: Max total issues to backfill (None = all)
    """
    settings = Settings()
    db_url = (
        f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@"
        f"{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    
    conn = await asyncpg.connect(db_url)
    
    try:
        total_backfilled = 0
        
        while True:
            # Fetch batch of issues without embeddings
            rows = await conn.fetch(
                """
                SELECT id, title, clean_body
                FROM issues
                WHERE embedding IS NULL
                LIMIT $1
                """,
                batch_size
            )
            
            if not rows:
                print(f"\n✓ Backfill complete. Total: {total_backfilled}")
                break
            
            # Generate embeddings
            texts = [f"{r['title']} {r['clean_body']}" for r in rows]
            embeddings = await generate_embeddings_batch(texts)
            
            # Update database
            for row, embedding in zip(rows, embeddings):
                await conn.execute(
                    "UPDATE issues SET embedding = $1 WHERE id = $2",
                    embedding, row["id"]
                )
            
            total_backfilled += len(rows)
            print(f"Backfilled {total_backfilled} issues...", end="\r")
            
            # Check limit
            if limit and total_backfilled >= limit:
                print(f"\n✓ Reached limit of {limit}")
                break
    
    finally:
        await conn.close()


if __name__ == "__main__":
    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            print(f"Usage: python -m scripts.backfill_embeddings [limit]")
            sys.exit(1)
    
    asyncio.run(backfill_embeddings(limit=limit))
