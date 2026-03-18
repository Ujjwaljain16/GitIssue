
What follows is not a rewrite of your Week 4 plan—it is the **corrected, production-ready Week 4**, with every one of those failure modes addressed and integrated into a coherent system.

---

# Week 4 — Final, Correct Plan (Production-Grade)

## Objective (refined)

> Build a **multi-system IssueNode layer with safe, loop-free, policy-driven sync**, using a canonical event model—not point-to-point integrations.

---

# 0. The Real Upgrade (What changes in Week 4)

Before:

```text
GitHub → Node → Graph
```

After:

```text
System → Canonical Event → Node → Canonical Event → System
```

This is the difference between:

* integrations (fragile)
* infrastructure (composable)

---

# 1. Core Foundation (NEW — MUST BE BUILT FIRST)

## 1.1 Canonical Event Contract (Non-negotiable)

Everything flows through this.

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from typing import Any

@dataclass
class CanonicalFieldChange:
    node_id: UUID
    field: str              # "title", "state", etc.
    old_value: Any
    new_value: Any
    
    changed_by: str         # "github", "jira"
    changed_at: datetime
    
    event_id: str           # source event ID (for dedup)
    schema_version: str = "1.0"
```

**Rule:**

* Adapters ONLY emit and consume this
* No adapter talks to another adapter

---

# 2. Fix #1 — Loop Prevention (FINAL DESIGN)

## Problem

Source-based checks fail.

## Solution

**Content-based idempotency + event tracking**

---

## 2.1 Schema

```sql
CREATE TABLE sync_events (
    id SERIAL PRIMARY KEY,
    
    node_id UUID NOT NULL,
    field TEXT NOT NULL,
    change_hash TEXT NOT NULL,
    
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    
    external_event_id TEXT,
    
    synced_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE (node_id, field, change_hash, target)
);
```

---

## 2.2 Logic

```python
def compute_change_hash(node_id, field, value):
    payload = f"{node_id}:{field}:{str(value).strip().lower()}"
    return sha256(payload.encode()).hexdigest()[:16]
```

---

## 2.3 Gate

```python
async def should_sync(conn, change, target):
    h = compute_change_hash(change.node_id, change.field, change.new_value)

    exists = await conn.fetchrow("""
        SELECT 1 FROM sync_events
        WHERE node_id=$1 AND field=$2 AND change_hash=$3 AND target=$4
        AND synced_at > NOW() - INTERVAL '30 seconds'
    """, change.node_id, change.field, h, target)

    if exists:
        return False

    await conn.execute("""
        INSERT INTO sync_events (node_id, field, change_hash, source, target)
        VALUES ($1,$2,$3,$4,$5)
        ON CONFLICT DO NOTHING
    """, change.node_id, change.field, h, change.changed_by, target)

    return True
```

---

# 3. Fix #2 — Conflict Resolution (No More “Latest Wins”)

## Replace with:

### Field Ownership Model

```python
FIELD_POLICY = {
    "title":    {"owner": "github", "rule": "owner_wins"},
    "body":     {"owner": "github", "rule": "owner_wins"},
    "state":    {"owner": "jira",   "rule": "owner_wins"},
    "labels":   {"owner": "both",   "rule": "union"},
}
```

---

## Sync Rule

```python
def should_apply(change, field):
    policy = FIELD_POLICY.get(field)
    if not policy:
        return False
    
    if policy["owner"] == "both":
        return True
    
    return change.changed_by == policy["owner"]
```

---

## Insight

You are not syncing data.
You are enforcing **authority boundaries between systems**.

---

# 4. Fix #3 — Jira Adapter (Correct Model)

## 4.1 Jira is NOT snapshot-based

→ Only process **partial updates**

---

## Model

```python
@dataclass
class PartialUpdate:
    external_id: str
    source: str
    fields: dict[str, Any]
```

---

## 4.2 Normalize ONLY changed fields

Never overwrite full issue.

---

## 4.3 Status Mapping (Dynamic)

```python
# On startup
statuses = jira_api.get_statuses(project)

for s in statuses:
    category = s["statusCategory"]["key"]
    if category == "done":
        map[s["name"]] = "closed"
    else:
        map[s["name"]] = "open"
```

---

## 4.4 ADF Cleaning (CRITICAL)

```python
def clean_jira(adf):
    if isinstance(adf, dict):
        if adf.get("type") == "text":
            return adf["text"]
        return " ".join(clean_jira(c) for c in adf.get("content", []))
    return ""
```

---

# 5. Fix #4 — Migration (NO DUAL SOURCE OF TRUTH)

---

## Step 1 — Backfill

```sql
INSERT INTO issue_representations (...)
SELECT ... FROM issue_node_map;
```

---

## Step 2 — Shadow Mode

* Keep old mapping read-only
* Use new table for all writes

---

## Step 3 — Cutover (after validation)

---

# 6. Fix #5 — Visibility Layer (MANDATORY)

---

## Schema

```sql
ALTER TABLE issue_representations 
ADD COLUMN visibility TEXT DEFAULT 'private',
ADD COLUMN org_id TEXT;
```

---

## Rule

```python
def can_surface(rep, context, org):
    if rep.visibility == "public":
        return True
    
    if rep.visibility == "internal":
        return rep.org_id == org
    
    return context.startswith(rep.source)
```

---

## Apply at READ time (not write)

---

# 7. Fix #6 — Reliable Sync (Job Queue)

---

## Schema

```sql
CREATE TABLE sync_jobs (
    id SERIAL PRIMARY KEY,
    
    node_id UUID,
    field TEXT,
    value TEXT,
    
    source TEXT,
    target TEXT,
    
    status TEXT DEFAULT 'pending',
    attempts INT DEFAULT 0,
    next_retry_at TIMESTAMP DEFAULT NOW()
);
```

---

## Worker

```python
FOR UPDATE SKIP LOCKED
```

→ prevents duplicate execution

---

## Retry Strategy

* exponential backoff
* rate limit aware
* dead-letter after max attempts

---

# 8. Fix #7 — Field Mapping (Transformer System)

---

## Replace lookup with transformers

```python
class Transformer:
    def to_canonical(self, v): ...
    def from_canonical(self, v): ...
```

---

## Example

```python
class StateTransformer:
    def to_canonical(self, v, source):
        if source == "jira":
            return jira_map[v]
        return v
```

---

# 9. Sync Engine (FINAL FLOW)

---

```text
Webhook (GitHub/Jira)
    ↓
Adapter → PartialUpdate
    ↓
Convert → CanonicalFieldChange
    ↓
Apply to Node (DB)
    ↓
For each other system:
    if should_sync + should_apply:
        enqueue sync_job
    ↓
Worker executes sync_job
```

---

# 10. Day-by-Day Execution (FINAL)

---

## Day 1

* representation table
* migration
* visibility fields

---

## Day 2

* Jira adapter (partial updates)
* rate limit handling

---

## Day 3

* canonical event model
* transformers

---

## Day 4

* loop prevention (sync_events)
* change hash

---

## Day 5

* field ownership rules
* conflict resolution

---

## Day 6

* sync_jobs queue
* retry + backoff

---

## Day 7

* full system testing

---

# 11. Testing (What Actually Matters)

---

## Must pass:

### 1. Loop Test

GitHub → Jira → GitHub
→ stops after 1 round

---

### 2. Conflict Test

GitHub title vs Jira title
→ GitHub wins (policy)

---

### 3. Partial Update Test

Jira updates status only
→ body untouched

---

### 4. Privacy Test

Private Jira → public GitHub
→ NOT leaked

---

### 5. Failure Test

GitHub API fails
→ retried → eventually consistent

---

### 6. Idempotency Test

Same webhook twice
→ no duplicate sync

---

# 12. What You Have Built

At the end of Week 4:

```text
        GitHub         Jira
           \           /
            \         /
             IssueNode
            /         \
     Canonical Event Bus
```

---

# Final Insight

Week 4 is where most systems fail—not because of bugs, but because:

> they confuse “data sync” with “state authority”

You didn’t.

You now have:

* authority model (field ownership)
* event model (canonical events)
* safety model (idempotency + retry + visibility)

That’s enough to scale.

---