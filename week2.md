Now we tighten everything into a **single, executable Week 2 plan**—clean, realistic, and aligned with all the corrections you’ve seen.

This is not exploratory anymore.
This is **what you build, in what order, with what guarantees**.

---

# Week 2 — Final Objective

> Build a **high-precision, non-spam duplicate suggestion system**
> using **correct retrieval → calibrated scoring → safe GitHub output**

---

# What You Will Have at the End

* Embeddings stored for all issues (including backfill)
* Hybrid retrieval (vector + FTS)
* Calibrated scoring system (0–1, meaningful thresholds)
* Signal-aware gating (no low-quality suggestions)
* Idempotent GitHub comment bot (no spam)
* Feedback logs (for future learning)

---

# 0. Final Architecture

```text id="week2-final-arch"
Issue Event (from Week 1)
   ↓
Embedding (thread pool)
   ↓
Candidate Retrieval
   ├─ Vector ANN (pgvector HNSW)
   └─ Full-text (Postgres GIN)
   ↓
Merge + Deduplicate Candidates
   ↓
Hybrid Scoring (normalized)
   ↓
Signal Strength Gate
   ↓
Decision Engine
   ↓
Idempotent Comment Bot (GitHub)
   ↓
Feedback Logging
```

---

# 1. Day 1 — Embeddings (Correct + Scalable)

---

## 1.1 Model (singleton, safe)

```python
from functools import lru_cache
from sentence_transformers import SentenceTransformer

@lru_cache(maxsize=1)
def get_model():
    return SentenceTransformer("all-MiniLM-L6-v2")
```

---

## 1.2 Embedding generation (non-blocking)

```python
from concurrent.futures import ThreadPoolExecutor
import asyncio

pool = ThreadPoolExecutor(max_workers=2)

async def generate_embedding_async(text: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        pool,
        lambda: get_model().encode(text, normalize_embeddings=True)
    )
```

---

## 1.3 Store in DB

```sql
ALTER TABLE issues ADD COLUMN embedding vector(384);
```

---

## 1.4 Backfill (MANDATORY)

```python
async def backfill_embeddings(batch_size=64):
    model = get_model()

    while True:
        rows = await db.fetch("""
            SELECT id, title, clean_body
            FROM issues
            WHERE embedding IS NULL
            LIMIT $1
        """, batch_size)

        if not rows:
            break

        texts = [f"{r['title']} {r['clean_body']}" for r in rows]
        embeddings = model.encode(texts, batch_size=batch_size, normalize_embeddings=True)

        for row, emb in zip(rows, embeddings):
            await db.execute(
                "UPDATE issues SET embedding = $1 WHERE id = $2",
                emb.tolist(), row["id"]
            )
```

---

# 2. Day 2 — Retrieval (THE CORE FIX)

---

## 2.1 Vector index (use HNSW)

```sql
CREATE INDEX idx_embedding ON issues
USING hnsw (embedding vector_cosine_ops);
```

---

## 2.2 Full-text index

```sql
CREATE INDEX idx_fts ON issues
USING GIN (to_tsvector('english', clean_body));
```

---

## 2.3 Vector query

```sql
SELECT id, title, clean_body, labels, state,
       1 - (embedding <=> $1::vector) AS vector_score
FROM issues
WHERE repo = $2
  AND id != $3
  AND created_at > NOW() - INTERVAL '1 year'
ORDER BY embedding <=> $1::vector
LIMIT 50;
```

---

## 2.4 FTS query

```sql
SELECT id, title, clean_body, labels, state
FROM issues
WHERE repo = $1
  AND id != $2
  AND to_tsvector('english', clean_body) @@ plainto_tsquery('english', $3)
LIMIT 50;
```

---

## 2.5 Merge candidates

```python
def merge_candidates(vector_results, fts_results):
    seen = {}
    for r in vector_results + fts_results:
        seen[r["id"]] = r
    return list(seen.values())
```

---

# 3. Day 3 — Scoring (CALIBRATED)

---

## 3.1 Normalize cosine

```python
def cosine_to_unit(c):
    return (c + 1) / 2
```

---

## 3.2 Keyword overlap (clean)

```python
def keyword_overlap(a, b):
    # use filtered tokens (no stopwords)
    ...
```

---

## 3.3 Structural similarity

```python
def structural_sim(a, b):
    # jaccard on file paths + errors
    return score  # [0,1]
```

---

## 3.4 Label similarity

```python
def label_sim(a, b):
    if not a or not b:
        return 0
    return len(set(a)&set(b)) / len(set(a)|set(b))
```

---

## 3.5 Final score

```python
score = (
    0.5 * semantic +
    0.2 * keyword +
    0.2 * struct +
    0.1 * label
)

score = max(0, min(score, 1))
```

---

# 4. Day 4 — Signal Strength Gate

---

```python
def signal_strength(issue):
    score = 0

    if issue.signals.file_paths:
        score += 0.3
    if issue.signals.error_messages:
        score += 0.3
    if issue.signals.stack_trace:
        score += 0.2

    if len(issue.clean_body.split()) > 50:
        score += 0.1

    return min(score, 1)
```

---

## Gate

```python
if signal_strength(issue) < 0.3:
    return []
```

---

# 5. Day 5 — Decision Engine

---

## Thresholds

```python
STRONG = 0.85
RELATED = 0.70
```

---

## Select top

```python
suggestions = [c for c in candidates if c.score > STRONG][:3]
```

---

# 6. Day 5 — Comment Bot (SAFE + IDEMPOTENT)

---

## Table

```sql
CREATE TABLE bot_comments (
    issue_external_id TEXT UNIQUE,
    comment_github_id BIGINT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Logic

```python
async def maybe_comment(issue, suggestions):

    exists = await db.fetchrow(
        "SELECT 1 FROM bot_comments WHERE issue_external_id=$1",
        issue.external_id
    )

    if exists:
        return

    await db.execute(
        "INSERT INTO bot_comments(issue_external_id) VALUES($1)",
        issue.external_id
    )

    comment_id = await github.post_comment(issue, suggestions)

    await db.execute(
        "UPDATE bot_comments SET comment_github_id=$1 WHERE issue_external_id=$2",
        comment_id, issue.external_id
    )
```

---

## Format (NO %)

```text
Possible related issues:

#45 — Crash on save  
→ similar error pattern

#12 — File write failure  
→ similar keywords
```

---

# 7. Day 6 — Feedback Logging

---

```sql
CREATE TABLE duplicate_suggestions (
    source_issue_id TEXT,
    suggested_issue_id TEXT,
    semantic_score FLOAT,
    keyword_score FLOAT,
    structural_score FLOAT,
    label_score FLOAT,
    final_score FLOAT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source_issue_id, suggested_issue_id)
);
```

---

# 8. Day 7 — Testing (CRITICAL)

---

## Test cases

---

### 1. Old duplicate

→ must retrieve from months ago

---

### 2. Generic issue

→ must NOT suggest

---

### 3. False positive

→ must be filtered

---

### 4. Latency

Target:

```text
< 2 seconds end-to-end
```

---

### 5. Idempotency

* same event twice
  → only one comment

---

# 9. Performance Targets

| Step      | Target |
| --------- | ------ |
| Embedding | <100ms |
| Retrieval | <100ms |
| Scoring   | <20ms  |
| Total     | <2s    |

---

# 10. Final Guarantees

By end of Week 2:

### Correctness

* no spam comments
* no wrong overwrites

### Quality

* high precision suggestions
* low noise

### Performance

* fast enough for real-time use

---

# Final Insight (carry forward)

> Week 1 = memory
> Week 2 = retrieval + reasoning

And the real system is:

> **A search engine over issues, not an ML model**

---