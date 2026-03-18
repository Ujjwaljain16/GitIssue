from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.sync.engine import apply_change_to_projection, apply_partial_update, fanout_change
from app.sync.models import CanonicalFieldChange


class FakeConn:
    def __init__(self):
        self.sync_events = []
        self.jobs = []

    async def fetchrow(self, query, node_id, field, change_hash, target, changed_by, window_seconds):
        for rec in self.sync_events:
            if rec["node_id"] != str(node_id):
                continue
            if rec["field"] != field or rec["change_hash"] != change_hash:
                continue
            same_target = rec["target"] == target
            reverse_echo = rec["source"] == target and rec["target"] == changed_by
            if same_target or reverse_echo:
                return {"exists": 1}
        return None

    async def execute(self, query, *args):
        if "INSERT INTO sync_events" in query:
            node_id, field, change_hash, source, target, event_id = args
            self.sync_events.append(
                {
                    "node_id": str(node_id),
                    "field": field,
                    "change_hash": change_hash,
                    "source": source,
                    "target": target,
                    "event_id": event_id,
                }
            )
            return
        if "INSERT INTO sync_jobs" in query:
            self.jobs.append(args)
            return


@pytest.mark.asyncio
async def test_fanout_change_prevents_loop_on_duplicate_event():
    conn = FakeConn()
    change = CanonicalFieldChange(
        node_id=uuid4(),
        field="title",
        old_value="old",
        new_value="new title",
        changed_by="github",
        changed_at=datetime.now(timezone.utc),
        event_id="evt-123",
    )

    targets = ["jira", "github"]
    first = await fanout_change(conn, change, targets)
    second = await fanout_change(conn, change, targets)

    assert first == ["jira"]
    assert second == []
    assert len(conn.jobs) == 1


@pytest.mark.asyncio
async def test_fanout_change_respects_owner_policy():
    conn = FakeConn()
    change = CanonicalFieldChange(
        node_id=uuid4(),
        field="state",
        old_value="open",
        new_value="closed",
        changed_by="github",
        changed_at=datetime.now(timezone.utc),
        event_id="evt-456",
    )

    result = await fanout_change(conn, change, ["jira"])
    assert result == []
    assert len(conn.jobs) == 0


def test_apply_partial_update_keeps_unspecified_fields_unchanged():
    original = {"title": "A", "body": "B", "state": "open", "labels": ["bug"]}
    result = apply_partial_update(original, source="jira", fields={"state": "closed"})

    assert result["title"] == "A"
    assert result["body"] == "B"
    assert result["state"] == "closed"
    assert result["labels"] == ["bug"]


def test_apply_changes_converges_to_policy_consistent_state():
    state = {"title": "old", "state": "open", "labels": ["bug"]}

    github_title = CanonicalFieldChange(
        node_id=uuid4(),
        field="title",
        old_value="old",
        new_value="Auth crash",
        changed_by="github",
        changed_at=datetime.now(timezone.utc),
        event_id="e1",
    )
    jira_state = CanonicalFieldChange(
        node_id=github_title.node_id,
        field="state",
        old_value="open",
        new_value="closed",
        changed_by="jira",
        changed_at=datetime.now(timezone.utc),
        event_id="e2",
    )
    github_labels = CanonicalFieldChange(
        node_id=github_title.node_id,
        field="labels",
        old_value=["bug"],
        new_value=["backend", "bug"],
        changed_by="github",
        changed_at=datetime.now(timezone.utc),
        event_id="e3",
    )

    for change in (github_title, jira_state, github_labels):
        state = apply_change_to_projection(state, change)

    assert state["title"] == "Auth crash"
    assert state["state"] == "closed"
    assert state["labels"] == ["backend", "bug"]
