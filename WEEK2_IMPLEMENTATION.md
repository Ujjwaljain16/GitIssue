# Week 2 — Duplicate Suggestion System (Implementation)

## Overview

Week 2 builds a **high-precision, non-spam duplicate suggestion system** that:

1. **Retrieves** candidates via hybrid search (vector + full-text)
2. **Scores** them using calibrated hybrid scoring
3. **Gates** low-quality issues to avoid spam
4. **Suggests** duplicates and posts idempotent comments on GitHub
5. **Logs** all suggestions for future learning

---

## Architecture

```
Issue Event (from Week 1)
   ↓
[1. Embedding] → Generate vector representation (async, non-blocking)
   ↓
[2. Retrieval] → Hybrid search
   ├─ Vector ANN (pgvector HNSW, cosine distance)
   └─ Full-text (Postgres GIN, English tokenization)
   ↓
[3. Merge] → Deduplicate candidates (vector first, then FTS)
   ↓
[4. Scoring] → Hybrid weighted score
   ├─ Semantic: 50% (vector similarity)
   ├─ Keyword: 20% (token overlap)
   ├─ Structural: 20% (file paths, error patterns)
   └─ Label: 10% (label overlap)
   ↓
[5. Signal Gate] → Filter low-confidence issues
   (require: errors, files, stack traces, or length)
   ↓
[6. Threshold] → Select top candidates (score ≥ 0.85)
   ↓
[7. Comment Bot] → Post idempotent GitHub comment
   ↓
[8. Feedback] → Log for analytics
```

---

## Components

### 1. Embeddings (`app/embeddings/`)

- **Model**: `sentence-transformers/all-MiniLM-L6-v2` (cached singleton)
- **Generation**: Async thread pool (non-blocking, fire-and-forget)
- **Storage**: PostgreSQL `vector(384)` column with HNSW index

**Key files:**
- `model.py` — Cached model singleton
- `generator.py` — Async embedding generation
- `scripts/backfill_embeddings.py` — Backfill existing issues

---

### 2. Retrieval (`app/retrieval/`)

**Vector search** (HNSW index, cosine distance):
- Query embedding, search by distance
- Limit 50 candidates from past 365 days

**Full-text search** (GIN index, English tokenization):
- Clean body text, English stemming
- Limit 50 candidates from past 365 days

**Merge**: Candidates from both streams, deduplicated by ID.

---

### 3. Scoring (`app/scoring/`)

**Hybrid Score** (four weighted signals):
- Semantic: 50% (cosine similarity)
- Keyword: 20% (token Jaccard)
- Structural: 20% (file path + error Jaccard)
- Label: 10% (label Jaccard)

**Signal Strength Gate** (prevents low-quality suggestions):
- File paths: +0.3
- Error messages: +0.3
- Stack traces: +0.2
- Long description: +0.1
- Gate threshold: 0.3 (default)

---

### 4. Decision Engine (`app/suggestions/engine.py`)

End-to-end pipeline:
1. Gate on signal strength
2. Generate embedding
3. Hybrid retrieval
4. Score each candidate
5. Filter by score threshold (default: 0.85)
6. Return top N (default: 3)

---

### 5. Comment Bot (`app/suggestions/bot.py`)

**Idempotency**: `bot_comments` table with `UNIQUE(issue_external_id)`

**Flow**:
1. Check if already commented
2. Format markdown comment
3. Post to GitHub (placeholder)
4. Record in DB

---

### 6. Feedback Logger (`app/feedback/logger.py`)

**Table**: `duplicate_suggestions` with:
- Source and suggested issue IDs
- All four component scores + final score
- User feedback field (future learning)

---

## Testing

Unit tests for all core components:
- Scoring functions (token extraction, similarity)
- Signal strength computation
- Comment formatting
- End-to-end integration

**Run:**
```bash
python -m pytest tests/test_scoring_*.py tests/test_suggestions_*.py -v
```

---

## Performance Targets

| Component    | Target   |
| ------------ | -------- |
| Embedding    | <100ms   |
| Retrieval    | <100ms   |
| Scoring      | <20ms    |
| **Total**    | **<2s**  |

---

## Guarantees

✅ **Correctness**: No spam, no duplicates, no stale suggestions  
✅ **Quality**: High precision (≥0.85), low false positives  
✅ **Performance**: Sub-2s end-to-end, async embedding

---
