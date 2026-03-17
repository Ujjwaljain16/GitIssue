import hashlib
import hmac

from app.api.webhook import verify_signature



def _sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
    return f"sha256={mac.hexdigest()}"



def test_verify_signature_valid() -> None:
    body = b'{"action":"opened"}'
    secret = "top-secret"
    signature = _sign(secret, body)

    assert verify_signature(secret, body, signature)



def test_verify_signature_invalid() -> None:
    body = b'{"action":"opened"}'

    assert not verify_signature("top-secret", body, "sha256=deadbeef")
    assert not verify_signature("", body, "sha256=deadbeef")
    assert not verify_signature("top-secret", body, "")
