from datetime import timedelta


async def enqueue_sync_job(
    conn,
    *,
    node_id,
    field: str,
    value: str,
    source: str,
    target: str,
) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO sync_jobs (node_id, field, value, source, target)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        node_id,
        field,
        value,
        source,
        target,
    )
    return int(row["id"])


async def claim_pending_jobs(conn, limit: int = 20) -> list[dict]:
    rows = await conn.fetch(
        """
        UPDATE sync_jobs sj
        SET status = 'processing',
            updated_at = NOW()
        WHERE sj.id IN (
            SELECT id
            FROM sync_jobs
            WHERE status IN ('pending', 'retry')
              AND next_retry_at <= NOW()
            ORDER BY next_retry_at ASC, id ASC
            FOR UPDATE SKIP LOCKED
            LIMIT $1
        )
        RETURNING *
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def mark_job_done(conn, job_id: int) -> None:
    await conn.execute(
        """
        UPDATE sync_jobs
        SET status='done', updated_at=NOW()
        WHERE id=$1
        """,
        job_id,
    )


def compute_backoff_seconds(attempts: int) -> int:
    # 2, 4, 8, 16, ... capped to 5 minutes.
    return min(300, 2 ** max(1, attempts))


async def mark_job_retry(conn, job_id: int, attempts: int, error: str, max_attempts: int = 5) -> None:
    if attempts >= max_attempts:
        await conn.execute(
            """
            UPDATE sync_jobs
            SET status='dead_letter',
                attempts=$2,
                last_error=$3,
                updated_at=NOW()
            WHERE id=$1
            """,
            job_id,
            attempts,
            error,
        )
        return

    backoff = compute_backoff_seconds(attempts)
    await conn.execute(
        """
        UPDATE sync_jobs
        SET status='retry',
            attempts=$2,
            last_error=$3,
            next_retry_at = NOW() + make_interval(secs => $4),
            updated_at=NOW()
        WHERE id=$1
        """,
        job_id,
        attempts,
        error,
        backoff,
    )
