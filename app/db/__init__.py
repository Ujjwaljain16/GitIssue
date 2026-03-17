"""Database module: pool management and issue upsert."""

from app.db.store import get_db_pool, init_db_pool, close_db_pool, upsert_issue, update_embedding

__all__ = ["get_db_pool", "init_db_pool", "close_db_pool", "upsert_issue", "update_embedding"]
