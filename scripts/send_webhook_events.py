import argparse
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import requests



def sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
    return f"sha256={mac.hexdigest()}"



def issue_event(*, issue_number: int, title: str, updated_at: datetime) -> dict:
    return {
        "action": "opened",
        "repository": {"full_name": "acme/repo"},
        "issue": {
            "number": issue_number,
            "title": title,
            "body": "synthetic test event",
            "labels": [{"name": "bug"}],
            "user": {"login": "load-tester"},
            "state": "open",
            "created_at": "2026-03-17T10:00:00Z",
            "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
        },
    }



def send(url: str, secret: str, payload: dict, mode: str, index: int) -> int:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": f"sim-{mode}-{index}",
        "Content-Type": "application/json",
    }

    if mode == "missing-signature":
        pass
    elif mode == "invalid-signature":
        headers["X-Hub-Signature-256"] = "sha256=deadbeef"
    else:
        headers["X-Hub-Signature-256"] = sign(secret, body)

    response = requests.post(url, data=body, headers=headers, timeout=10)
    return response.status_code



def main() -> None:
    parser = argparse.ArgumentParser(description="Send synthetic GitHub webhook events")
    parser.add_argument("--url", default="http://localhost:8000/webhook/github")
    parser.add_argument("--secret", default="replace_me")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument(
        "--mode",
        choices=["normal", "duplicate", "out-of-order", "invalid-signature", "missing-signature"],
        default="normal",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    statuses: list[int] = []

    if args.mode == "out-of-order":
        newer = issue_event(issue_number=42, title="new", updated_at=now + timedelta(minutes=1))
        older = issue_event(issue_number=42, title="old", updated_at=now)
        statuses.append(send(args.url, args.secret, newer, args.mode, 1))
        statuses.append(send(args.url, args.secret, older, args.mode, 2))
    elif args.mode == "duplicate":
        payload = issue_event(issue_number=42, title="duplicate", updated_at=now)
        for i in range(args.count):
            statuses.append(send(args.url, args.secret, payload, args.mode, i + 1))
    else:
        for i in range(args.count):
            payload = issue_event(issue_number=1000 + i, title=f"issue-{i}", updated_at=now + timedelta(seconds=i))
            statuses.append(send(args.url, args.secret, payload, args.mode, i + 1))

    success = sum(1 for status in statuses if 200 <= status < 300)
    print(f"sent={len(statuses)} success={success} failure={len(statuses) - success}")
    print(f"status_codes={sorted(set(statuses))}")


if __name__ == "__main__":
    main()
