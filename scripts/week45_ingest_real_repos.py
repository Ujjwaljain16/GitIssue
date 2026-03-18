import argparse
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
import httpx

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DEFAULT_REPOS = [
    "microsoft/vscode",
    "facebook/react",
    "redis/redis",
    "golang/go",
    "public-apis/public-apis",
    "sindresorhus/awesome",
]


def _sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def _to_payload(repo: str, issue: dict, action: str = "opened") -> dict:
    labels = [{"name": lbl.get("name", "")} for lbl in issue.get("labels", []) if lbl.get("name")]
    return {
        "action": action,
        "repository": {"full_name": repo},
        "issue": {
            "number": issue["number"],
            "title": issue.get("title") or "",
            "body": issue.get("body") or "",
            "labels": labels,
            "user": {"login": (issue.get("user") or {}).get("login", "unknown")},
            "state": issue.get("state", "open"),
            "created_at": issue.get("created_at"),
            "updated_at": issue.get("updated_at"),
        },
    }


async def _fetch_issues(client: httpx.AsyncClient, repo: str, per_repo: int) -> list[dict]:
    issues: list[dict] = []
    page = 1

    while len(issues) < per_repo:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/issues",
            params={"state": "all", "per_page": 100, "page": page, "sort": "updated", "direction": "desc"},
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break

        for item in batch:
            if "pull_request" in item:
                continue
            issues.append(item)
            if len(issues) >= per_repo:
                break

        page += 1

    return issues


async def _send_webhook_events(
    client: httpx.AsyncClient,
    webhook_url: str,
    webhook_secret: str,
    repo: str,
    issues: Iterable[dict],
    mode: str,
) -> int:
    sent = 0
    for idx, issue in enumerate(issues, start=1):
        payload = _to_payload(repo, issue, action="opened")
        events = [payload]

        if mode in {"duplicates", "mixed"} and idx % 10 == 0:
            events.append(payload)

        if mode in {"out-of-order", "mixed"} and idx % 15 == 0:
            older = json.loads(json.dumps(payload))
            newer = json.loads(json.dumps(payload))
            newer["issue"]["title"] = f"{payload['issue']['title']} (newer)"
            events = [newer, older]

        for ev_no, event_payload in enumerate(events, start=1):
            body = json.dumps(event_payload, separators=(",", ":")).encode("utf-8")
            headers = {
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": f"week45-{repo.replace('/', '-')}-{idx}-{ev_no}",
                "X-Hub-Signature-256": _sign(webhook_secret, body),
                "Content-Type": "application/json",
            }
            resp = await client.post(webhook_url, content=body, headers=headers)
            resp.raise_for_status()
            sent += 1

    return sent


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest real GitHub issues into the local pipeline via webhook")
    parser.add_argument("--repos", default=",".join(DEFAULT_REPOS), help="Comma-separated owner/repo list")
    parser.add_argument("--per-repo", type=int, default=50, help="Issue count per repo")
    parser.add_argument("--mode", choices=["normal", "duplicates", "out-of-order", "mixed"], default="mixed")
    parser.add_argument("--webhook-url", default="http://localhost:8000/webhook/github")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN", ""))
    parser.add_argument("--webhook-secret", default=os.getenv("GITHUB_WEBHOOK_SECRET", "replace_me"))
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("GITHUB_TOKEN is required. Set env var or pass --token")

    repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    headers = {
        "Authorization": f"Bearer {args.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "git-issue-tracker-week45",
    }

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        total_sent = 0
        for repo in repos:
            issues = await _fetch_issues(client, repo, args.per_repo)
            sent = await _send_webhook_events(client, args.webhook_url, args.webhook_secret, repo, issues, args.mode)
            total_sent += sent
            print(f"repo={repo} issues={len(issues)} events_sent={sent}")

    print(f"done repos={len(repos)} total_events_sent={total_sent} mode={args.mode}")


if __name__ == "__main__":
    asyncio.run(main())
