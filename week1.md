Good. Now we stop discussing and give you something you can **actually execute line-by-line**.

This is your **final Week 1 plan**—cleaned, hardened, and ready to code. No fluff, no ambiguity.

---

# Week 1 — Final Goal

> Build a **secure, lossless, idempotent GitHub ingestion pipeline**
> that stores issues correctly and can survive real production behavior.

---

# 0. What You Will Have by End of Week

* GitHub App receiving real events
* Verified webhook ingestion (secure)
* Queue with at-least-once delivery
* Worker processing safely
* Postgres storing normalized + raw data
* No data loss, no duplication, no corruption

---

# 1. Final Architecture

```text
GitHub App
   ↓ (Webhook)
FastAPI Ingress
   ↓ (validated, raw preserved)
Redis Streams (consumer groups)
   ↓
Worker (async)
   ↓
Postgres (normalized + raw)
   ↓
Logs + Metrics
```

---

# 2. Project Setup (Day 0)

### Repo structure

```text
/app
  /api
  /core
  /queue
  /worker
  /normalizer
  /models
  /db
/tests
/docker
```

---

### Install deps (Python)

```bash
pip install fastapi uvicorn redis asyncpg sqlalchemy pydantic python-dotenv
```

---

# 3. Day 1 — GitHub App + Secure Webhook

---

## 3.1 Create GitHub App

Permissions:

* Issues: Read & Write
* Metadata: Read

Events:

* issues

---

## 3.2 FastAPI Webhook (SECURE)

```python
# app/api/webhook.py

from fastapi import APIRouter, Request, HTTPException
import hmac, hashlib, json, os

router = APIRouter()
SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False

    mac = hmac.new(
        secret.encode(),
        msg=body,
        digestmod=hashlib.sha256
    )

    expected = "sha256=" + mac.hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhook/github")
async def github_webhook(request: Request):
    body = await request.body()  # MUST be first

    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(SECRET, body, signature):
        raise HTTPException(status_code=401)

    event_type = request.headers.get("X-GitHub-Event")

    # push raw event to queue
    from app.queue.redis_stream import push_event

    await push_event({
        "schema_version": "1.0",
        "source": "github",
        "event_type": event_type,
        "payload": body.decode(),
    })

    return {"status": "ok"}
```

---

# 4. Day 2 — Queue (Redis Streams, CORRECT WAY)

---

## 4.1 Redis Setup

```python
# app/queue/redis_stream.py

import redis.asyncio as redis
import os, json

r = redis.Redis.from_url(os.getenv("REDIS_URL"))

STREAM = "github_events"
GROUP = "workers"


async def init_stream():
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except:
        pass


async def push_event(data: dict):
    await r.xadd(STREAM, {"data": json.dumps(data)})
```

---

# 5. Day 3 — Worker (Correct Consumption + ACK)

---

```python
# app/worker/worker.py

import json, os
from app.queue.redis_stream import r, STREAM, GROUP

CONSUMER = "worker-1"

HANDLED_ACTIONS = {"opened", "edited", "reopened"}


async def process_event(data):
    payload = json.loads(data["payload"])
    event_type = data["event_type"]

    if event_type != "issues":
        return

    action = payload.get("action")
    if action not in HANDLED_ACTIONS:
        return

    from app.normalizer.normalize import normalize
    normalized = normalize(payload)

    from app.db.store import upsert_issue
    await upsert_issue(normalized)


async def run_worker():
    while True:
        messages = await r.xreadgroup(
            groupname=GROUP,
            consumername=CONSUMER,
            streams={STREAM: ">"},
            count=10,
            block=5000
        )

        for _, msgs in messages or []:
            for msg_id, msg_data in msgs:
                try:
                    data = json.loads(msg_data["data"])
                    await process_event(data)
                    await r.xack(STREAM, GROUP, msg_id)

                except Exception as e:
                    print("Error:", e)
                    # do NOT ack → retry
```

---

# 6. Day 4 — Normalization (STRICT CONTRACT)

---

```python
# app/normalizer/schema.py

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class IssueSignals(BaseModel):
    error_messages: List[str] = []
    file_paths: List[str] = []
    stack_trace: Optional[str] = None


class NormalizedIssue(BaseModel):
    external_id: str
    repo: str
    issue_number: int
    title: str
    body: str
    clean_body: str
    labels: List[str]
    author: str
    state: str
    created_at: datetime
    updated_at: datetime
    signals: IssueSignals
    raw_payload: dict
```

---

## Clean body (DEFINED)

````python
import re

def clean_body(text: str) -> str:
    if not text:
        return ""

    text = re.sub(r"```[\s\S]*?```", "[CODE]", text)
    text = re.sub(r"`[^`]+`", "[INLINE_CODE]", text)
    text = re.sub(r"https?://\S+", "[URL]", text)

    return " ".join(text.split())
````

---

## Normalize

```python
# app/normalizer/normalize.py

from app.normalizer.schema import NormalizedIssue, IssueSignals
from app.normalizer.clean import clean_body


def normalize(payload: dict) -> NormalizedIssue:
    issue = payload["issue"]
    repo = payload["repository"]["full_name"]

    return NormalizedIssue(
        external_id=f"github:{repo}#{issue['number']}",
        repo=repo,
        issue_number=issue["number"],
        title=issue["title"],
        body=issue.get("body") or "",
        clean_body=clean_body(issue.get("body") or ""),
        labels=[l["name"] for l in issue.get("labels", [])],
        author=issue["user"]["login"],
        state=issue["state"],
        created_at=issue["created_at"],
        updated_at=issue["updated_at"],
        signals=IssueSignals(),
        raw_payload=payload
    )
```

---

# 7. Day 5 — Database (FINAL SCHEMA)

---

```sql
CREATE TABLE issues (
    id SERIAL PRIMARY KEY,
    external_id TEXT UNIQUE,
    repo TEXT,
    issue_number INT,
    state TEXT,
    title TEXT,
    body TEXT,
    clean_body TEXT,
    author TEXT,
    labels TEXT[],
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    inserted_at TIMESTAMP DEFAULT NOW(),
    raw_payload JSONB
);

CREATE UNIQUE INDEX idx_repo_issue ON issues(repo, issue_number);
```

---

## Upsert (SAFE)

```python
# app/db/store.py

async def upsert_issue(issue):
    query = """
    INSERT INTO issues (
        external_id, repo, issue_number, state,
        title, body, clean_body, author, labels,
        created_at, updated_at, raw_payload
    )
    VALUES (...)
    ON CONFLICT (external_id) DO UPDATE SET
        title = EXCLUDED.title,
        body = EXCLUDED.body,
        clean_body = EXCLUDED.clean_body,
        updated_at = EXCLUDED.updated_at
    WHERE issues.updated_at <= EXCLUDED.updated_at;
    """
```

---

# 8. Day 6 — Observability + Testing

---

## Add logs everywhere

* webhook received
* event pushed
* event processed
* DB insert/update

---

## Simulate:

* 100 issues
* duplicate webhook events
* invalid payload

---

## Validate:

* no duplicates
* no crashes
* no missed events

---

# 9. Day 7 — Hardening

---

## Add:

### Retry tracking (basic)

* count failures per message

---

### Graceful shutdown

* finish current batch before exit

---

### Metrics

Track:

* events/sec
* queue size
* failures

---

# 10. Final Checklist (must pass)

### Security

* webhook signature verified
* no secret leaks

### Reliability

* no event loss
* retries work

### Correctness

* no duplicate rows
* no stale overwrite

### Performance

* <100ms webhook response
* stable under burst

---

# Final Truth

At the end of Week 1:

> You have built the **foundation of a distributed system**, not a feature.

If this layer is:

* correct → everything scales
* wrong → everything breaks later

---