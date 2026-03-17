from datetime import datetime, timezone
from types import SimpleNamespace

import asyncpg
import pytest
import pytest_asyncio

from app.db import store
from app.normalizer.schema import IssueSignals, NormalizedIssue



def _issue(*, title: str, updated_at: datetime) -> NormalizedIssue:
    return NormalizedIssue(
        external_id="github:acme/repo#42",
        repo="acme/repo",
        issue_number=42,
        title=title,
        body="body",
        clean_body="body",
        labels=["bug"],
        author="alice",
        state="open",
        created_at=datetime(2026, 3, 17, 10, 0, tzinfo=timezone.utc),
        updated_at=updated_at,
        signals=IssueSignals(),
        raw_payload={"k": "v"},
    )


@pytest_asyncio.fixture()
async def db_ready(monkeypatch):
    dsn = "postgresql://postgres:postgres@localhost:5432/issues"

    try:
        conn = await asyncpg.connect(dsn=dsn)
        await conn.close()
    except Exception as exc:
        pytest.skip(f"Postgres is not reachable for integration tests: {exc}")

    monkeypatch.setattr(store, "settings", SimpleNamespace(database_url=dsn))
    await store.init_db_pool()
    yield
    await store.close_db_pool()


@pytest.mark.asyncio
async def test_upsert_is_idempotent(db_ready) -> None:
    assert store._pool is not None

    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE issues")

    event = _issue(title="same", updated_at=datetime(2026, 3, 17, 10, 1, tzinfo=timezone.utc))
    for _ in range(10):
        await store.upsert_issue(event)

    async with store._pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM issues WHERE external_id=$1", event.external_id)

    assert count == 1


@pytest.mark.asyncio
async def test_out_of_order_update_does_not_regress_state(db_ready) -> None:
    assert store._pool is not None

    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE issues")

    newer = _issue(title="new", updated_at=datetime(2026, 3, 17, 10, 2, tzinfo=timezone.utc))
    older = _issue(title="old", updated_at=datetime(2026, 3, 17, 10, 1, tzinfo=timezone.utc))

    await store.upsert_issue(newer)
    await store.upsert_issue(older)

    async with store._pool.acquire() as conn:
        title = await conn.fetchval("SELECT title FROM issues WHERE external_id=$1", newer.external_id)

    assert title == "new"
