import pytest
from uuid import uuid4

from app.graph.service import _pick_canonical_title, _title_quality_score


def test_title_quality_prefers_specific_over_generic():
    generic = "bug"
    specific = "NullPointerException in src/main.py during save"
    assert _title_quality_score(specific) > _title_quality_score(generic)


def test_pick_canonical_title_selects_best_title():
    titles = [
        "issue",
        "problem",
        "TypeError in api/handler.py when parsing payload",
    ]
    selected = _pick_canonical_title(titles)
    assert "TypeError" in selected


def test_pick_canonical_title_handles_empty_input():
    assert _pick_canonical_title([]) == "Untitled issue"


class FakeConn:
    def __init__(self, merged_map):
        self.merged_map = merged_map

    async def fetchrow(self, query, node_id):
        merged_into = self.merged_map.get(str(node_id))
        if merged_into is None:
            return {"canonical_state": "open", "merged_into": None}
        return {"canonical_state": "merged", "merged_into": merged_into}


@pytest.mark.asyncio
async def test_resolve_root_node_walks_merge_chain():
    from app.graph.service import _resolve_root_node

    n1 = uuid4()
    n2 = uuid4()
    n3 = uuid4()
    conn = FakeConn({str(n1): n2, str(n2): n3})

    root = await _resolve_root_node(conn, n1)
    assert root == n3
