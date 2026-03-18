import pytest

from app.sync.jobs import compute_backoff_seconds, mark_job_retry


class FakeConn:
    def __init__(self):
        self.calls = []

    async def execute(self, query, *args):
        self.calls.append((query, args))


def test_compute_backoff_exponential_with_cap():
    assert compute_backoff_seconds(1) == 2
    assert compute_backoff_seconds(2) == 4
    assert compute_backoff_seconds(10) == 300


@pytest.mark.asyncio
async def test_mark_job_retry_moves_to_dead_letter_after_max_attempts():
    conn = FakeConn()
    await mark_job_retry(conn, job_id=10, attempts=5, error="boom", max_attempts=5)
    assert len(conn.calls) == 1
    query, args = conn.calls[0]
    assert "dead_letter" in query
    assert args[0] == 10


@pytest.mark.asyncio
async def test_mark_job_retry_sets_retry_and_backoff():
    conn = FakeConn()
    await mark_job_retry(conn, job_id=11, attempts=2, error="temp", max_attempts=5)
    assert len(conn.calls) == 1
    query, args = conn.calls[0]
    assert "status='retry'" in query
    assert args[0] == 11
    # attempts and backoff seconds
    assert args[1] == 2
    assert args[3] == 4


@pytest.mark.asyncio
async def test_rate_limit_style_retry_uses_future_next_retry():
    conn = FakeConn()
    await mark_job_retry(conn, job_id=12, attempts=3, error="429 rate limit", max_attempts=5)
    assert len(conn.calls) == 1
    query, args = conn.calls[0]
    assert "next_retry_at = NOW() + make_interval" in query
    assert args[0] == 12
    assert args[3] == 8
