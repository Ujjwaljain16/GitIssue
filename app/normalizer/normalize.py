from app.normalizer.clean import clean_body
from app.normalizer.schema import IssueSignals, NormalizedIssue



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
        labels=[label["name"] for label in issue.get("labels", [])],
        author=issue["user"]["login"],
        state=issue["state"],
        created_at=issue["created_at"],
        updated_at=issue["updated_at"],
        signals=IssueSignals(),
        raw_payload=payload,
    )
