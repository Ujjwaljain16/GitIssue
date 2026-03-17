# Week 1 Reliability Test Runbook

This runbook validates trust properties for Week 1:

1. No event loss
2. No duplicate row corruption
3. No stale overwrite
4. Signature security cannot be bypassed
5. Recovery after worker/database failure

## 1. Prerequisites

1. Start infrastructure:

```bash
docker compose -f docker/docker-compose.yml up -d postgres redis
```

2. Configure environment:

```bash
copy .env.example .env
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Start API and worker (separate terminals):

```bash
uvicorn app.main:app --reload
```

```bash
python -m app.worker.run
```

## 2. Automated Tests

Run all tests:

```bash
pytest -q
```

Expected baseline:
- unit and worker tests pass
- db integration tests pass when local Postgres is available
- db tests are skipped if Postgres is unavailable

## 3. Security Validation

Invalid signature should be rejected:

```bash
python scripts/send_webhook_events.py --mode invalid-signature --count 5 --secret replace_me
```

Missing signature should be rejected:

```bash
python scripts/send_webhook_events.py --mode missing-signature --count 5 --secret replace_me
```

Expected:
- mostly 401 status codes
- no queue growth from invalid requests

## 4. Duplicate and Ordering Validation

Duplicate storm:

```bash
python scripts/send_webhook_events.py --mode duplicate --count 50 --secret replace_me
```

Out-of-order update sequence:

```bash
python scripts/send_webhook_events.py --mode out-of-order --secret replace_me
```

Expected:
- duplicate events do not create multiple rows for the same external_id
- final state keeps newest updated_at values

## 5. Burst Validation

```bash
python scripts/send_webhook_events.py --mode normal --count 500 --secret replace_me
```

Expected:
- API remains responsive
- queue can absorb burst and drain over time
- no worker crashes

## 6. Failure Injection

### Worker crash and recovery

1. Start sending normal events.
2. Kill worker process mid-run.
3. Restart worker.

Expected:
- unacked messages are retried
- no permanent event loss
- stale pending messages are reclaimed by the active worker

### Database outage

1. Stop Postgres container while worker is running.
2. Send events.
3. Start Postgres again.

Expected:
- processing failures logged
- events not acked during outage
- events eventually persist after DB returns
- repeatedly failing poison messages move to dead-letter stream

### Redis outage

1. Stop Redis container.
2. Send webhook requests.

Expected:
- webhook call fails (5xx), not false-success
- after Redis returns, normal ingestion resumes

## 7. Operational Checks

Validate endpoints:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/metrics
```

Check that metrics include:
- webhook_received
- event_processed
- event_failed
- queue_size
- queue_pending
- event_reclaimed
- event_dead_lettered

## 8. Acceptance Criteria

Week 1 is accepted only when all are true:

1. Invalid/missing signatures are rejected.
2. Duplicate storm does not create duplicate logical issues.
3. Out-of-order updates do not regress issue state.
4. Worker crash does not lose events.
5. DB/Redis outages are visible and recoverable.
