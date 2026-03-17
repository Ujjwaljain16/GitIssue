"""Database migration tasks (run once after schema changes)."""

import asyncio
import sys

import asyncpg

from app.core.config import Settings


async def ensure_pgvector_extension() -> None:
    """Ensure pgvector extension is installed in Postgres."""
    settings = Settings()
    db_url = (
        f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@"
        f"{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    
    conn = await asyncpg.connect(db_url)
    
    try:
        # Install pgvector extension
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        print("✓ pgvector extension ready")
        
        # Apply schema to create tables and indexes
        from pathlib import Path
        schema_path = Path(__file__).parent / "app" / "db" / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        await conn.execute(schema_sql)
        print("✓ Schema applied successfully")
    
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(ensure_pgvector_extension())
