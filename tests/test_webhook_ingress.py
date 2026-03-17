import hashlib
import hmac
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import webhook as webhook_module



def _sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
    return f"sha256={mac.hexdigest()}"



def _build_test_client(monkeypatch, secret: str, queued: list[dict]) -> TestClient:
    async def fake_push_event(data: dict) -> str:
        queued.append(data)
        return "1-0"

    monkeypatch.setattr(webhook_module, "push_event", fake_push_event)
    monkeypatch.setattr(webhook_module, "settings", SimpleNamespace(github_webhook_secret=secret))

    app = FastAPI()
    app.include_router(webhook_module.router)
    return TestClient(app)



def test_webhook_rejects_invalid_signature(monkeypatch) -> None:
    queued: list[dict] = []
    client = _build_test_client(monkeypatch, secret="top-secret", queued=queued)

    body = b'{"action":"opened"}'
    response = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "issues"},
    )

    assert response.status_code == 401
    assert queued == []



def test_webhook_rejects_missing_signature(monkeypatch) -> None:
    queued: list[dict] = []
    client = _build_test_client(monkeypatch, secret="top-secret", queued=queued)

    body = b'{"action":"opened"}'
    response = client.post("/webhook/github", content=body, headers={"X-GitHub-Event": "issues"})

    assert response.status_code == 401
    assert queued == []



def test_webhook_accepts_valid_signature_and_preserves_raw_payload(monkeypatch) -> None:
    queued: list[dict] = []
    secret = "top-secret"
    client = _build_test_client(monkeypatch, secret=secret, queued=queued)

    # Keep unusual spacing and key order to validate raw-body handling.
    body = b'{  "z":1, "a" : [1,2,3],"nested": {"k": "v"} }'
    signature = _sign(secret, body)

    response = client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-123",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(queued) == 1
    assert queued[0]["event_type"] == "issues"
    assert queued[0]["delivery_id"] == "delivery-123"
    assert queued[0]["payload"] == body.decode("utf-8")

    # Ensure raw payload remained valid JSON and unchanged semantically.
    assert json.loads(queued[0]["payload"]) == json.loads(body.decode("utf-8"))
