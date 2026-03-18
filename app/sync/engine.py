from app.sync.idempotency import should_sync
from app.sync.models import CanonicalFieldChange
from app.sync.policy import merge_field_value, should_apply


async def fanout_change(conn, change: CanonicalFieldChange, targets: list[str]) -> list[str]:
    queued_targets: list[str] = []

    for target in targets:
        if target == change.changed_by:
            continue

        if not should_apply(change.changed_by, change.field):
            continue

        allowed = await should_sync(conn, change, target)
        if not allowed:
            continue

        await conn.execute(
            """
            INSERT INTO sync_jobs (node_id, field, value, source, target)
            VALUES ($1, $2, $3, $4, $5)
            """,
            change.node_id,
            change.field,
            str(change.new_value),
            change.changed_by,
            target,
        )
        queued_targets.append(target)

    return queued_targets


def resolve_field_value(field: str, current, incoming):
    return merge_field_value(field, current, incoming)


def apply_change_to_projection(projection: dict, change: CanonicalFieldChange) -> dict:
    """Apply one canonical change to an in-memory projection with policy enforcement."""
    updated = dict(projection)

    if not should_apply(change.changed_by, change.field):
        return updated

    current = updated.get(change.field)
    updated[change.field] = resolve_field_value(change.field, current, change.new_value)
    return updated


def apply_partial_update(projection: dict, source: str, fields: dict) -> dict:
    """Apply a partial update without touching unspecified fields."""
    updated = dict(projection)
    for field, value in fields.items():
        if not should_apply(source, field):
            continue
        current = updated.get(field)
        updated[field] = resolve_field_value(field, current, value)
    return updated
