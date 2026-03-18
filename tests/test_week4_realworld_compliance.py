from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.sync.engine import apply_change_to_projection, apply_partial_update, fanout_change
from app.sync.jobs import mark_job_done, mark_job_retry
from app.sync.models import CanonicalFieldChange
from app.sync.visibility import can_surface


class SyncConn:
    def __init__(self):
        self.sync_events: list[dict] = []
        self.jobs: list[dict] = []

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
            node_id, field, value, source, target = args
            self.jobs.append(
                {
                    "id": len(self.jobs) + 1,
                    "node_id": str(node_id),
                    "field": field,
                    "value": value,
                    "source": source,
                    "target": target,
                }
            )
            return


class JobStateConn:
    def __init__(self):
        self.jobs: dict[int, dict] = {1: {"status": "pending", "attempts": 0, "last_error": None}}

    async def execute(self, query, *args):
        job_id = int(args[0])
        if "status='dead_letter'" in query:
            self.jobs[job_id]["status"] = "dead_letter"
            self.jobs[job_id]["attempts"] = int(args[1])
            self.jobs[job_id]["last_error"] = args[2]
            return

        if "status='retry'" in query:
            self.jobs[job_id]["status"] = "retry"
            self.jobs[job_id]["attempts"] = int(args[1])
            self.jobs[job_id]["last_error"] = args[2]
            self.jobs[job_id]["backoff_secs"] = int(args[3])
            return

        if "status='done'" in query:
            self.jobs[job_id]["status"] = "done"
            return


@pytest.mark.asyncio
async def test_realworld_ping_pong_loop_stops_after_one_roundtrip():
    conn = SyncConn()
    node_id = uuid4()

    gh_change = CanonicalFieldChange(
        node_id=node_id,
        field="title",
        old_value="old",
        new_value="Auth crash fix",
        changed_by="github",
        changed_at=datetime.now(timezone.utc),
        event_id="gh-1",
    )
    first = await fanout_change(conn, gh_change, ["jira", "github"])

    jira_echo = CanonicalFieldChange(
        node_id=node_id,
        field="title",
        old_value="old",
        new_value=" auth crash fix ",
        changed_by="jira",
        changed_at=datetime.now(timezone.utc),
        event_id="jira-echo-1",
    )
    second = await fanout_change(conn, jira_echo, ["github"])

    assert first == ["jira"]
    assert second == []
    assert len(conn.jobs) == 1


def test_realworld_non_owner_update_is_ignored():
    state = {"title": "Auth crash", "state": "open", "labels": ["bug"]}

    jira_title = CanonicalFieldChange(
        node_id=uuid4(),
        field="title",
        old_value="Auth crash",
        new_value="AUTH-CRASH",
        changed_by="jira",
        changed_at=datetime.now(timezone.utc),
        event_id="j-1",
    )
    github_state = CanonicalFieldChange(
        node_id=jira_title.node_id,
        field="state",
        old_value="open",
        new_value="closed",
        changed_by="github",
        changed_at=datetime.now(timezone.utc),
        event_id="g-1",
    )

    after_title = apply_change_to_projection(state, jira_title)
    after_state = apply_change_to_projection(after_title, github_state)

    assert after_title["title"] == "Auth crash"
    assert after_state["state"] == "open"


def test_realworld_partial_update_does_not_wipe_data():
    original = {
        "title": "A",
        "body": "B",
        "state": "open",
        "labels": ["bug"],
    }

    updated = apply_partial_update(original, source="jira", fields={"state": "closed"})

    assert updated["title"] == "A"
    assert updated["body"] == "B"
    assert updated["state"] == "closed"
    assert updated["labels"] == ["bug"]


def test_realworld_private_data_not_visible_cross_context():
    jira_private = {
        "visibility": "private",
        "org_id": "acme",
        "source": "jira",
    }
    assert can_surface(jira_private, context="github-comment", org="acme") is False


@pytest.mark.asyncio
async def test_realworld_duplicate_event_has_no_side_effects():
    conn = SyncConn()
    change = CanonicalFieldChange(
        node_id=uuid4(),
        field="title",
        old_value="old",
        new_value="same value",
        changed_by="github",
        changed_at=datetime.now(timezone.utc),
        event_id="dup-evt",
    )

    await fanout_change(conn, change, ["jira"])
    await fanout_change(conn, change, ["jira"])

    assert len(conn.jobs) == 1


def test_realworld_eventual_convergence_policy_consistent():
    projection = {
        "title": "old",
        "state": "open",
        "labels": ["bug"],
    }
    node = uuid4()

    events = [
        CanonicalFieldChange(node, "title", "old", "Auth crash", "github", datetime.now(timezone.utc), "e1"),
        CanonicalFieldChange(node, "state", "open", "closed", "jira", datetime.now(timezone.utc), "e2"),
        CanonicalFieldChange(node, "labels", ["bug"], ["bug", "auth"], "github", datetime.now(timezone.utc), "e3"),
    ]

    for event in events:
        projection = apply_change_to_projection(projection, event)

    assert projection["title"] == "Auth crash"
    assert projection["state"] == "closed"
    assert projection["labels"] == ["auth", "bug"]


@pytest.mark.asyncio
async def test_realworld_retry_then_done_not_lost():
    conn = JobStateConn()

    await mark_job_retry(conn, job_id=1, attempts=1, error="timeout", max_attempts=5)
    assert conn.jobs[1]["status"] == "retry"
    assert conn.jobs[1]["attempts"] == 1

    await mark_job_done(conn, job_id=1)
    assert conn.jobs[1]["status"] == "done"


@pytest.mark.asyncio
async def test_realworld_retry_hits_dead_letter_at_limit():
    conn = JobStateConn()

    await mark_job_retry(conn, job_id=1, attempts=5, error="permanent failure", max_attempts=5)

    assert conn.jobs[1]["status"] == "dead_letter"
    assert conn.jobs[1]["attempts"] == 5
