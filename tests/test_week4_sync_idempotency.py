from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.sync.idempotency import compute_change_hash, should_sync
from app.sync.models import CanonicalFieldChange


class FakeConn:
    def __init__(self):
        self.records = []

    async def fetchrow(self, query, node_id, field, change_hash, target, changed_by, window_seconds):
        for rec in self.records:
            if rec["node_id"] != str(node_id):
                continue
            if rec["field"] != field or rec["change_hash"] != change_hash:
                continue
            same_target = rec["target"] == target
            reverse_echo = rec["source"] == target and rec["target"] == changed_by
            if same_target or reverse_echo:
                return {"exists": 1}
        return None

    async def execute(self, query, node_id, field, change_hash, source, target, event_id):
        self.records.append(
            {
                "node_id": str(node_id),
                "field": field,
                "change_hash": change_hash,
                "source": source,
                "target": target,
                "event_id": event_id,
            }
        )


def test_compute_change_hash_is_content_based_and_normalized():
    node_id = str(uuid4())
    h1 = compute_change_hash(node_id, "Title", "  Crash on Save  ")
    h2 = compute_change_hash(node_id, "title", "crash on save")
    assert h1 == h2


@pytest.mark.asyncio
async def test_should_sync_blocks_duplicate_loop_within_window():
    node = uuid4()
    change = CanonicalFieldChange(
        node_id=node,
        field="title",
        old_value="old",
        new_value="new",
        changed_by="github",
        changed_at=datetime.now(timezone.utc),
        event_id="evt-1",
    )
    conn = FakeConn()

    first = await should_sync(conn, change, "jira")
    second = await should_sync(conn, change, "jira")

    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_should_sync_blocks_reverse_direction_ping_pong_echo():
    node = uuid4()
    conn = FakeConn()

    outbound = CanonicalFieldChange(
        node_id=node,
        field="title",
        old_value="old",
        new_value="Auth crash fix",
        changed_by="github",
        changed_at=datetime.now(timezone.utc),
        event_id="gh_1",
    )
    assert await should_sync(conn, outbound, "jira") is True

    echo = CanonicalFieldChange(
        node_id=node,
        field="title",
        old_value="old",
        new_value=" auth crash fix ",
        changed_by="jira",
        changed_at=datetime.now(timezone.utc),
        event_id="jira_1",
    )
    assert await should_sync(conn, echo, "github") is False
