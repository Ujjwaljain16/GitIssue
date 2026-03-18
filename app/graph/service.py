import json
import re
from typing import Optional
from uuid import UUID

import asyncpg

from app.db import get_db_pool
from app.graph.decision import classify_node_action, apply_repo_tier_adjustment
from app.normalizer.schema import NormalizedIssue


async def map_issue_to_graph(
    issue_id: int,
    issue: NormalizedIssue,
    suggestions: list[dict],
    actor: str = "worker",
) -> str:
    """Map issue to graph node and create edges/merge when confidence is high enough."""
    pool = get_db_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchval("SELECT node_id FROM issue_node_map WHERE issue_id=$1", issue_id)
            if existing is not None:
                return str(existing)

            target = await _find_best_target_node(conn, issue.repo, suggestions)

            if target is None:
                node_id = await _create_node(conn, issue.title, issue.state, confidence=1.0)
                await _map_issue(conn, issue_id, node_id, actor)
                await _log_event(
                    conn,
                    node_id,
                    "node_created",
                    actor,
                    {"reason": "no_candidate"},
                )
                await _recompute_canonical(conn, node_id)
                return str(node_id)

            decision = classify_node_action(target["adjusted_score"])
            target_node = target["node_id"]

            if decision.action == "create_new":
                node_id = await _create_node(conn, issue.title, issue.state, confidence=decision.adjusted_score)
                await _map_issue(conn, issue_id, node_id, actor)
                await _log_event(conn, node_id, "node_created", actor, {"score": decision.adjusted_score})
                await _recompute_canonical(conn, node_id)
                return str(node_id)

            if decision.action in {"add_related_edge", "add_duplicate_edge", "merge"}:
                fresh_node = await _create_node(conn, issue.title, issue.state, confidence=decision.adjusted_score)
                await _map_issue(conn, issue_id, fresh_node, actor)

                if decision.action == "merge":
                    keep, merged = await merge_nodes_with_conn(conn, target_node, fresh_node, actor=actor)
                    await _recompute_canonical(conn, keep)
                    return str(keep)

                edge_type = "related_to" if decision.action == "add_related_edge" else "duplicate_of"
                await _upsert_edge(
                    conn,
                    fresh_node,
                    target_node,
                    edge_type=edge_type,
                    confidence=decision.adjusted_score,
                    source="week3-decision-engine",
                )
                await _log_event(
                    conn,
                    fresh_node,
                    "edge_created",
                    actor,
                    {
                        "edge_type": edge_type,
                        "to_node": str(target_node),
                        "score": decision.adjusted_score,
                    },
                )
                await _recompute_canonical(conn, fresh_node)
                await _recompute_canonical(conn, target_node)
                return str(fresh_node)

            node_id = await _create_node(conn, issue.title, issue.state, confidence=1.0)
            await _map_issue(conn, issue_id, node_id, actor)
            await _recompute_canonical(conn, node_id)
            return str(node_id)


async def merge_nodes(primary_node_id: str, secondary_node_id: str, actor: str = "system") -> tuple[str, str]:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            keep, merged = await merge_nodes_with_conn(conn, UUID(primary_node_id), UUID(secondary_node_id), actor)
            return str(keep), str(merged)


async def merge_nodes_with_conn(
    conn: asyncpg.Connection,
    primary_node_id: UUID,
    secondary_node_id: UUID,
    actor: str,
) -> tuple[UUID, UUID]:
    if primary_node_id == secondary_node_id:
        return primary_node_id, secondary_node_id

    # Canonical lock order avoids deadlocks under concurrent merges.
    first_lock, second_lock = sorted([str(primary_node_id), str(secondary_node_id)])
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", first_lock)
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", second_lock)

    keep = await _resolve_root_node(conn, primary_node_id)
    merged = await _resolve_root_node(conn, secondary_node_id)

    if keep == merged:
        return keep, merged

    # Keep lexicographically older UUID as canonical survivor.
    if str(keep) > str(merged):
        keep, merged = merged, keep

    await conn.execute(
        """
        UPDATE issue_node_map
        SET node_id = $1, mapped_at = NOW(), mapped_by = $3
        WHERE node_id = $2
        """,
        keep,
        merged,
        actor,
    )

    edge_rows = await conn.fetch(
        """
        SELECT from_node, to_node, edge_type, confidence, source
        FROM issue_edges
        WHERE from_node = $1 OR to_node = $1
        """,
        merged,
    )

    await conn.execute("DELETE FROM issue_edges WHERE from_node = $1 OR to_node = $1", merged)

    for row in edge_rows:
        a = keep if row["from_node"] == merged else row["from_node"]
        b = keep if row["to_node"] == merged else row["to_node"]
        if a == b:
            continue
        await _upsert_edge(
            conn,
            a,
            b,
            edge_type=row["edge_type"],
            confidence=float(row["confidence"]),
            source=row["source"],
        )

    await conn.execute(
        """
        UPDATE issue_nodes
        SET canonical_state = 'merged',
            merged_into = $1,
            merged_at = NOW(),
            updated_at = NOW()
        WHERE id = $2
        """,
        keep,
        merged,
    )

    await _log_event(
        conn,
        keep,
        "node_merged",
        actor,
        {"merged_node": str(merged)},
    )
    await _log_event(
        conn,
        merged,
        "node_soft_deleted",
        actor,
        {"merged_into": str(keep)},
    )

    await _recompute_canonical(conn, keep)
    return keep, merged


async def get_issues_in_node(node_id: str) -> list[dict]:
    pool = get_db_pool()
    query = """
    SELECT i.*
    FROM issue_node_map nm
    JOIN issues i ON i.id = nm.issue_id
    WHERE nm.node_id = $1::uuid
    ORDER BY i.updated_at DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, node_id)
    return [dict(r) for r in rows]


async def get_two_hop_neighbors(node_id: str) -> list[dict]:
    pool = get_db_pool()
    query = """
    WITH RECURSIVE walk AS (
        SELECT from_node, to_node, edge_type, 1 AS depth
        FROM issue_edges
        WHERE from_node = $1::uuid OR to_node = $1::uuid
        UNION ALL
        SELECT e.from_node, e.to_node, e.edge_type, w.depth + 1
        FROM issue_edges e
        JOIN walk w
          ON (e.from_node = w.to_node OR e.to_node = w.from_node)
        WHERE w.depth < 2
    )
    SELECT DISTINCT from_node, to_node, edge_type, depth
    FROM walk
    ORDER BY depth ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, node_id)
    return [dict(r) for r in rows]


async def _find_best_target_node(
    conn: asyncpg.Connection,
    source_repo: str,
    suggestions: list[dict],
) -> Optional[dict]:
    best: Optional[dict] = None

    for suggestion in suggestions:
        external_id = suggestion.get("external_id")
        score = float(suggestion.get("score", 0.0))
        if not external_id:
            continue

        candidate = await conn.fetchrow(
            """
            SELECT nm.node_id, i.repo
            FROM issues i
            JOIN issue_node_map nm ON nm.issue_id = i.id
            WHERE i.external_id = $1
            LIMIT 1
            """,
            external_id,
        )
        if candidate is None:
            continue

        root_node = await _resolve_root_node(conn, candidate["node_id"])
        adjusted = apply_repo_tier_adjustment(score, source_repo, candidate["repo"])

        if best is None or adjusted > best["adjusted_score"]:
            best = {
                "node_id": root_node,
                "repo": candidate["repo"],
                "raw_score": score,
                "adjusted_score": adjusted,
                "external_id": external_id,
            }

    return best


async def _create_node(
    conn: asyncpg.Connection,
    title: str,
    state: str,
    confidence: float,
) -> UUID:
    canonical_state = "open" if state == "open" else "closed"
    row = await conn.fetchrow(
        """
        INSERT INTO issue_nodes (canonical_title, canonical_state, confidence)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        title.strip() or "Untitled issue",
        canonical_state,
        max(0.0, min(1.0, confidence)),
    )
    return row["id"]


async def _map_issue(conn: asyncpg.Connection, issue_id: int, node_id: UUID, actor: str) -> None:
    await conn.execute(
        """
        INSERT INTO issue_node_map (issue_id, node_id, mapped_by)
        VALUES ($1, $2, $3)
        ON CONFLICT (issue_id) DO UPDATE
        SET node_id = EXCLUDED.node_id,
            mapped_at = NOW(),
            mapped_by = EXCLUDED.mapped_by
        """,
        issue_id,
        node_id,
        actor,
    )


async def _upsert_edge(
    conn: asyncpg.Connection,
    node_a: UUID,
    node_b: UUID,
    edge_type: str,
    confidence: float,
    source: str,
) -> None:
    from_node, to_node = (node_a, node_b) if str(node_a) < str(node_b) else (node_b, node_a)

    await conn.execute(
        """
        INSERT INTO issue_edges (from_node, to_node, edge_type, confidence, source)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (from_node, to_node, edge_type) DO UPDATE
        SET confidence = GREATEST(issue_edges.confidence, EXCLUDED.confidence),
            source = EXCLUDED.source
        """,
        from_node,
        to_node,
        edge_type,
        max(0.0, min(1.0, confidence)),
        source,
    )


async def _resolve_root_node(conn: asyncpg.Connection, node_id: UUID) -> UUID:
    current = node_id
    for _ in range(16):
        row = await conn.fetchrow(
            "SELECT canonical_state, merged_into FROM issue_nodes WHERE id = $1",
            current,
        )
        if row is None:
            return current
        if row["canonical_state"] != "merged" or row["merged_into"] is None:
            return current
        current = row["merged_into"]
    return current


async def _recompute_canonical(conn: asyncpg.Connection, node_id: UUID) -> None:
    node_row = await conn.fetchrow("SELECT canonical_state FROM issue_nodes WHERE id = $1", node_id)
    if node_row is None or node_row["canonical_state"] == "merged":
        return

    issue_rows = await conn.fetch(
        """
        SELECT i.title, i.state
        FROM issue_node_map nm
        JOIN issues i ON i.id = nm.issue_id
        WHERE nm.node_id = $1
        """,
        node_id,
    )

    if not issue_rows:
        return

    titles = [r["title"] for r in issue_rows]
    states = [r["state"] for r in issue_rows]

    closed = sum(1 for s in states if s == "closed")
    opened = sum(1 for s in states if s == "open")

    if closed == len(states):
        canonical_state = "closed"
    elif opened == len(states):
        canonical_state = "open"
    elif closed > opened:
        canonical_state = "likely_resolved"
    else:
        canonical_state = "open"

    canonical_title = _pick_canonical_title(titles)

    await conn.execute(
        """
        UPDATE issue_nodes
        SET canonical_title = $2,
            canonical_state = $3,
            updated_at = NOW()
        WHERE id = $1
        """,
        node_id,
        canonical_title,
        canonical_state,
    )


def _pick_canonical_title(titles: list[str]) -> str:
    if not titles:
        return "Untitled issue"

    best = max(titles, key=_title_quality_score)
    return best.strip() or "Untitled issue"


def _title_quality_score(title: str) -> float:
    t = title.strip().lower()
    if not t:
        return 0.0

    length = len(t)
    # Prefer medium informative titles.
    length_score = 1.0 - (abs(length - 60) / 60)

    generic_penalty = 0.0
    for token in ("bug", "issue", "problem", "help", "urgent"):
        if re.fullmatch(rf"{token}[\W\d]*", t):
            generic_penalty += 0.5
        elif token in t and len(t.split()) <= 3:
            generic_penalty += 0.2

    specificity_bonus = 0.0
    if re.search(r"(error|exception|timeout|nullpointer|typeerror|valueerror)", t):
        specificity_bonus += 0.3
    if re.search(r"[a-z0-9_./\-]+\.[a-z0-9]+", t):
        specificity_bonus += 0.3

    return max(0.0, length_score + specificity_bonus - generic_penalty)


async def _log_event(
    conn: asyncpg.Connection,
    node_id: UUID,
    event_type: str,
    actor: str,
    metadata: Optional[dict] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO node_events (node_id, event_type, actor, metadata)
        VALUES ($1, $2, $3, $4::jsonb)
        """,
        node_id,
        event_type,
        actor,
        json.dumps(metadata or {}),
    )
