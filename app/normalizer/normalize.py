from datetime import datetime, timezone

from app.normalizer.clean import clean_body
from app.normalizer.schema import NormalizedIssue
from app.normalizer.signals import extract_signals


def _parse_iso_datetime(iso_str: str | None) -> datetime:
    """Parse ISO datetime string from GitHub (always UTC), ensuring timezone-aware result."""
    if not iso_str:
        return datetime.now(timezone.utc)
    # GitHub always returns UTC times; parse and ensure timezone-aware
    dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def normalize(payload: dict) -> NormalizedIssue:
    issue = payload["issue"]
    repo = payload["repository"]["full_name"]
    body = issue.get("body") or ""

    return NormalizedIssue(
        external_id=f"github:{repo}#{issue['number']}",
        repo=repo,
        issue_number=issue["number"],
        title=issue["title"],
        body=body,
        clean_body=clean_body(body),
        labels=[label["name"] for label in issue.get("labels", [])],
        author=issue["user"]["login"],
        state=issue["state"],
        created_at=_parse_iso_datetime(issue.get("created_at")),
        updated_at=_parse_iso_datetime(issue.get("updated_at")),
        signals=extract_signals(body),
        raw_payload=payload,
    )
