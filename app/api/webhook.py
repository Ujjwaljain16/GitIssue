import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.core.metrics import inc
from app.queue.redis_stream import push_event

logger = logging.getLogger(__name__)
router = APIRouter()



def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    if not secret:
        return False

    if not signature or not signature.startswith("sha256="):
        return False

    mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    return hmac.compare_digest(expected, signature)


@router.post("/webhook/github")
async def github_webhook(request: Request) -> dict[str, Any]:
    body = await request.body()

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(settings.github_webhook_secret, body, signature):
        logger.warning("webhook_rejected_invalid_signature")
        raise HTTPException(status_code=401, detail="invalid signature")

    event_type = request.headers.get("X-GitHub-Event", "unknown")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")

    envelope = {
        "schema_version": "1.0",
        "source": "github",
        "event_type": event_type,
        "delivery_id": delivery_id,
        "payload": body.decode("utf-8"),
    }

    await push_event(envelope)
    inc("webhook_received")
    logger.info(
        "webhook_ingested",
        extra={
            "event_type": event_type,
            "delivery_id": delivery_id,
            "bytes": len(body),
        },
    )

    return {"status": "ok"}
