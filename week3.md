Now we bring everything together into a **final, production-grade Week 3 plan**—clean, safe, and aligned with all the brutal review corrections.

This is no longer “feature building.”
This is **data-structure engineering under concurrency**.

---

# Week 3 — Final Objective

> Build a **safe, auditable Issue Graph layer** that:

* maps issues → canonical IssueNodes
* links problems via edges
* merges nodes **without corruption**
* preserves full history (reversible system)

---

# What You Will Have at End of Week 3

* IssueNode abstraction (canonical problem layer)
* Safe mapping: issue → node (atomic)
* Graph edges (duplicate / related)
* Concurrency-safe node merge system
* Audit trail (node_events)
* Basic graph queries
* No data corruption under concurrent operations

---

# 0. The Core Principle (Do NOT forget)

> **Never lose information. Never create invalid structure.**

Everything in Week 3 enforces this.

---

# 1. Final Architecture

```text id="w3-final-arch"
GitHub Issue
     ↓
Week 2 Intelligence (retrieval + scoring)
     ↓
Node Decision Engine
     ↓
Transaction Boundary
     ├─ Upsert Issue
     ├─ Create/Attach Node
     ├─ Create Edge (if needed)
     └─ Map Issue → Node
     ↓
(Optional) Merge Engine (safe + locked)
     ↓
Graph (IssueNodes + Edges)
     ↓
Audit Log (node_events)
```

---

# 2. Semantic Definition (VERY IMPORTANT)

Before writing code, define this:

> Two issues belong to the same IssueNode **only if they represent the same root cause in the same component**, not just similar symptoms.

Implications:

* Same error message ≠ same node
* Cross-repo merge requires very high confidence
* Otherwise → `related_to`, not merge

---

# 3. Database Schema (FINAL — DO FIRST)

---

## 3.1 IssueNodes

```sql id="nodes-schema"
CREATE TABLE issue_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    canonical_title TEXT NOT NULL,
    canonical_state TEXT NOT NULL 
        CHECK (canonical_state IN ('open', 'closed', 'merged', 'likely_resolved')),
    
    merged_into UUID REFERENCES issue_nodes(id),
    merged_at TIMESTAMP WITH TIME ZONE,
    
    confidence FLOAT NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT merged_consistency CHECK (
        (canonical_state = 'merged') = (merged_into IS NOT NULL)
    )
);
```

---

## 3.2 Mapping (Issue → Node)

```sql id="mapping-schema"
CREATE TABLE issue_node_map (
    issue_id INT PRIMARY KEY REFERENCES issues(id) ON DELETE CASCADE,
    node_id UUID NOT NULL REFERENCES issue_nodes(id),
    mapped_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mapped_by TEXT NOT NULL
);
```

---

## 3.3 Edges

```sql id="edges-schema"
CREATE TABLE issue_edges (
    id SERIAL PRIMARY KEY,
    
    from_node UUID NOT NULL REFERENCES issue_nodes(id),
    to_node UUID NOT NULL REFERENCES issue_nodes(id),
    
    edge_type TEXT NOT NULL 
        CHECK (edge_type IN ('duplicate_of', 'related_to', 'blocks')),
    
    confidence FLOAT NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    source TEXT NOT NULL,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT no_self_loop CHECK (from_node != to_node),
    CONSTRAINT canonical_direction CHECK (from_node < to_node),
    CONSTRAINT unique_edge UNIQUE (from_node, to_node, edge_type)
);
```

---

## 3.4 Audit Trail

```sql id="events-schema"
CREATE TABLE node_events (
    id SERIAL PRIMARY KEY,
    node_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 3.5 Indexes

```sql id="indexes"
CREATE INDEX idx_edges_from ON issue_edges(from_node);
CREATE INDEX idx_edges_to ON issue_edges(to_node);
CREATE INDEX idx_node_map_node ON issue_node_map(node_id);
```

---

# 4. Day-by-Day Execution

---

# Day 1 — Schema + Migrations

* Create all tables above
* Add constraints (non-negotiable)
* Add indexes
* Test FK + constraint violations

---

# Day 2 — Atomic Issue → Node Mapping

---

## Flow

```text id="atomic-flow"
1. Run similarity (outside tx)
2. Begin transaction
3. Upsert issue
4. Decide node action
5. Create/attach node
6. Insert mapping
7. Commit
```

---

## Code shape

```python
async with conn.transaction():
    issue_id = upsert_issue(...)
    action = decide_node_action(...)

    if action.type == "CREATE_NEW":
        node_id = create_node(...)

    elif action.type == "ATTACH":
        node_id = action.target_node

    await map_issue(issue_id, node_id)
```

---

# Day 3 — Node Decision Engine (CORE)

---

## Thresholds

```python
ATTACH_THRESHOLD = 0.70
MERGE_THRESHOLD  = 0.90
```

---

## Logic

```python
if score < 0.70:
    CREATE_NEW

elif score < 0.80:
    ADD_EDGE (related_to)

elif score < 0.90:
    ADD_EDGE (duplicate_of)

else:
    MERGE
```

---

# Day 4 — Safe Merge Engine

---

## Rules

```text id="merge-rules"
- Always merge newer → older
- Always lock both nodes
- Always soft-delete
- Always reassign mappings + edges
```

---

## Steps

1. Canonical ordering (UUID)
2. Advisory locks
3. Re-fetch nodes
4. Reassign:

   * mappings
   * edges (both directions)
5. Remove self loops
6. Soft delete secondary
7. Log event

---

# Day 5 — Canonical State + Title

---

## State logic

```text id="state"
all closed → closed  
all open → open  
mixed → likely_resolved (if majority closed)
```

---

## Title logic

* medium length preferred
* penalize generic
* reward specificity (errors, files)

---

# Day 6 — Graph Queries

---

## Get all issues in node

```sql id="q1"
SELECT i.*
FROM issue_node_map nm
JOIN issues i ON i.id = nm.issue_id
WHERE nm.node_id = $1;
```

---

## 2-hop traversal

Use recursive query (already defined earlier)

---

# Day 7 — Testing (CRITICAL)

---

## Must test:

---

### 1. Concurrent merge

* merge(A,B) and merge(B,A)
  → only one survives

---

### 2. Merge already merged node

* merge(A,B), then merge(A,C)
  → resolves correctly

---

### 3. Orphan detection

```sql
SELECT id FROM issues
WHERE id NOT IN (SELECT issue_id FROM issue_node_map);
```

→ must be empty

---

### 4. Edge deduplication

* no duplicate edges
* no cycles

---

### 5. Cross-repo false positive

* similar error across repos
  → should NOT merge

---

# 5. Cross-Repo Strategy (SAFE)

---

## DO NOT blindly remove repo filter

Use tiers:

```text id="tiers"
same repo → normal threshold  
same org → stricter  
cross org → very strict + structural signals required
```

---

# 6. Final Guarantees

At end of Week 3:

### Correctness

* no orphan issues
* no duplicate nodes
* no invalid edges

---

### Safety

* merges are reversible
* audit trail exists

---

### Concurrency

* no race condition corruption

---

### Graph Integrity

* consistent structure
* queryable graph

---

# 7. What You Now Have

You’ve built:

> A **problem identity layer**

Not just:

* issues
* not just duplicates

But:

```text id="final-shift"
Problem → Node  
Issue → Representation  
Relations → Graph
```

---

# Final Insight

Week 3 is the hardest because:

> You’re no longer processing data.
> You’re defining **truth** in your system.

If Week 1 fails → retry
If Week 2 fails → ignore suggestion
If Week 3 fails → **system becomes untrustworthy**

---


