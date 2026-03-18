import hashlib

from app.sync.models import CanonicalFieldChange


def compute_change_hash(node_id: str, field: str, value: object) -> str:
    payload = f"{str(node_id).strip()}:{field.strip().lower()}:{str(value).strip().lower()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


async def should_sync(conn, change: CanonicalFieldChange, target: str, window_seconds: int = 30) -> bool:
    change_hash = compute_change_hash(str(change.node_id), change.field, change.new_value)

    exists = await conn.fetchrow(
        """
        SELECT 1 FROM sync_events
        WHERE node_id=$1
          AND field=$2
          AND change_hash=$3
                    AND (
                                target=$4
                                OR (source=$4 AND target=$5)
                            )
          AND synced_at > NOW() - make_interval(secs => $6)
        """,
        change.node_id,
        change.field,
        change_hash,
        target,
                change.changed_by,
        window_seconds,
    )

    if exists:
        return False

    await conn.execute(
        """
        INSERT INTO sync_events (node_id, field, change_hash, source, target, external_event_id)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (node_id, field, change_hash, target) DO NOTHING
        """,
        change.node_id,
        change.field,
        change_hash,
        change.changed_by,
        target,
        change.event_id,
    )
    return True
