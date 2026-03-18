import asyncio
import json

import pytest

from app.worker import worker as worker_module



def _issue_payload(action: str = "opened") -> dict:
    return {
        "action": action,
        "repository": {"full_name": "acme/repo"},
        "issue": {
            "number": 42,
            "title": "Bug",
            "body": "broken",
            "labels": [{"name": "bug"}],
            "user": {"login": "alice"},
            "state": "open",
            "created_at": "2026-03-17T10:00:00Z",
            "updated_at": "2026-03-17T10:01:00Z",
        },
    }


@pytest.mark.asyncio
async def test_process_event_ignores_non_issue_events(monkeypatch) -> None:
    called = {"upsert": 0}

    async def fake_upsert_issue(_normalized):
        called["upsert"] += 1

    monkeypatch.setattr(worker_module, "upsert_issue", fake_upsert_issue)

    await worker_module.process_event({"event_type": "pull_request", "payload": json.dumps({})})

    assert called["upsert"] == 0


@pytest.mark.asyncio
async def test_process_event_ignores_unhandled_actions(monkeypatch) -> None:
    called = {"upsert": 0}

    async def fake_upsert_issue(_normalized):
        called["upsert"] += 1

    monkeypatch.setattr(worker_module, "upsert_issue", fake_upsert_issue)

    payload = _issue_payload(action="closed")
    await worker_module.process_event({"event_type": "issues", "payload": json.dumps(payload)})

    assert called["upsert"] == 0


@pytest.mark.asyncio
async def test_process_event_maps_issue_into_graph(monkeypatch) -> None:
    called = {"map": 0}

    async def fake_upsert_issue(_normalized):
        return 77

    async def fake_suggest_duplicates(**kwargs):
        return [{"external_id": "github:acme/repo#1", "score": 0.5}]

    async def fake_map_issue_to_graph(*, issue_id: int, issue, suggestions, actor: str):
        called["map"] += 1
        assert issue_id == 77
        assert actor == "worker"
        assert isinstance(suggestions, list)
        return "node-77"

    monkeypatch.setattr(worker_module, "upsert_issue", fake_upsert_issue)
    monkeypatch.setattr(worker_module, "suggest_duplicates", fake_suggest_duplicates)
    monkeypatch.setattr(worker_module, "map_issue_to_graph", fake_map_issue_to_graph)

    async def fake_embed_async(*args, **kwargs):
        pass

    async def fake_suggest_async(*args, **kwargs):
        pass

    monkeypatch.setattr(worker_module, "_embed_issue_async", fake_embed_async)
    monkeypatch.setattr(worker_module, "_suggest_and_comment_async", fake_suggest_async)

    payload = _issue_payload(action="opened")
    await worker_module.process_event({"event_type": "issues", "payload": json.dumps(payload)})

    assert called["map"] == 1


@pytest.mark.asyncio
async def test_run_worker_acks_on_success(monkeypatch) -> None:
    stop_event = asyncio.Event()
    acks: list[str] = []

    async def fake_read_group(*, consumer: str, count: int, block_ms: int):
        stop_event.set()
        payload = _issue_payload(action="opened")
        envelope = {"event_type": "issues", "payload": json.dumps(payload)}
        return [("github_events", [("1-0", {"data": json.dumps(envelope)})])]

    async def fake_ack_event(message_id: str):
        acks.append(message_id)
        return 1

    async def fake_upsert_issue(_normalized):
        return 42

    async def fake_suggest_duplicates(**kwargs):
        return []

    async def fake_map_issue_to_graph(*, issue_id: int, issue, suggestions, actor: str):
        return "node-1"

    async def fake_reclaim_stale_messages(*, consumer: str, min_idle_ms: int, count: int):
        return []

    # Stub fire-and-forget tasks so they complete immediately (no orphaned tasks)
    async def fake_embed_async(*args, **kwargs):
        pass

    async def fake_suggest_async(*args, **kwargs):
        pass

    monkeypatch.setattr(worker_module, "read_group", fake_read_group)
    monkeypatch.setattr(worker_module, "ack_event", fake_ack_event)
    monkeypatch.setattr(worker_module, "upsert_issue", fake_upsert_issue)
    monkeypatch.setattr(worker_module, "suggest_duplicates", fake_suggest_duplicates)
    monkeypatch.setattr(worker_module, "map_issue_to_graph", fake_map_issue_to_graph)
    monkeypatch.setattr(worker_module, "reclaim_stale_messages", fake_reclaim_stale_messages)
    monkeypatch.setattr(worker_module, "_embed_issue_async", fake_embed_async)
    monkeypatch.setattr(worker_module, "_suggest_and_comment_async", fake_suggest_async)

    await worker_module.run_worker(stop_event=stop_event)

    assert acks == ["1-0"]


@pytest.mark.asyncio
async def test_run_worker_does_not_ack_on_failure(monkeypatch) -> None:
    stop_event = asyncio.Event()
    acks: list[str] = []

    async def fake_read_group(*, consumer: str, count: int, block_ms: int):
        stop_event.set()
        envelope = {"event_type": "issues", "payload": "{invalid-json"}
        return [("github_events", [("2-0", {"data": json.dumps(envelope)})])]

    async def fake_ack_event(message_id: str):
        acks.append(message_id)
        return 1

    async def fake_reclaim_stale_messages(*, consumer: str, min_idle_ms: int, count: int):
        return []

    async def fake_pending_delivery_count(message_id: str):
        return 1

    async def fake_push_dead_letter(message_id: str, message_data: dict, reason: str):
        return "dlq-1"

    monkeypatch.setattr(worker_module, "read_group", fake_read_group)
    monkeypatch.setattr(worker_module, "ack_event", fake_ack_event)
    monkeypatch.setattr(worker_module, "reclaim_stale_messages", fake_reclaim_stale_messages)
    monkeypatch.setattr(worker_module, "pending_delivery_count", fake_pending_delivery_count)
    monkeypatch.setattr(worker_module, "push_dead_letter", fake_push_dead_letter)

    before = worker_module.failure_counts.get("2-0", 0)
    await worker_module.run_worker(stop_event=stop_event)
    after = worker_module.failure_counts.get("2-0", 0)

    assert acks == []
    assert after == before + 1


@pytest.mark.asyncio
async def test_run_worker_dead_letters_after_retry_threshold(monkeypatch) -> None:
    stop_event = asyncio.Event()
    acks: list[str] = []
    dead_lettered: list[str] = []

    async def fake_read_group(*, consumer: str, count: int, block_ms: int):
        stop_event.set()
        envelope = {"event_type": "issues", "payload": "{invalid-json"}
        return [("github_events", [("3-0", {"data": json.dumps(envelope)})])]

    async def fake_ack_event(message_id: str):
        acks.append(message_id)
        return 1

    async def fake_reclaim_stale_messages(*, consumer: str, min_idle_ms: int, count: int):
        return []

    async def fake_pending_delivery_count(message_id: str):
        return 999

    async def fake_push_dead_letter(message_id: str, message_data: dict, reason: str):
        dead_lettered.append(message_id)
        return "dlq-2"

    monkeypatch.setattr(worker_module, "read_group", fake_read_group)
    monkeypatch.setattr(worker_module, "ack_event", fake_ack_event)
    monkeypatch.setattr(worker_module, "reclaim_stale_messages", fake_reclaim_stale_messages)
    monkeypatch.setattr(worker_module, "pending_delivery_count", fake_pending_delivery_count)
    monkeypatch.setattr(worker_module, "push_dead_letter", fake_push_dead_letter)

    await worker_module.run_worker(stop_event=stop_event)

    assert dead_lettered == ["3-0"]
    assert acks == ["3-0"]
