from app.sync.models import PartialUpdate


def clean_jira(adf):
    if isinstance(adf, dict):
        if adf.get("type") == "text":
            return adf.get("text", "")
        return " ".join(clean_jira(c) for c in adf.get("content", [])).strip()
    if isinstance(adf, list):
        return " ".join(clean_jira(item) for item in adf).strip()
    if isinstance(adf, str):
        return adf
    return ""


def build_jira_status_map(statuses: list[dict]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for status in statuses:
        name = status.get("name")
        category = ((status.get("statusCategory") or {}).get("key") or "").lower()
        if not name:
            continue
        mapped[name] = "closed" if category == "done" else "open"
    return mapped


def normalize_jira_partial_update(payload: dict) -> PartialUpdate:
    issue = payload.get("issue", {})
    fields = issue.get("fields", {})
    changed = payload.get("changelog", {}).get("items", [])

    changed_field_names = {item.get("field") for item in changed if item.get("field")}

    normalized_fields: dict[str, object] = {}

    if "summary" in changed_field_names:
        normalized_fields["title"] = fields.get("summary", "")

    if "description" in changed_field_names:
        normalized_fields["body"] = clean_jira(fields.get("description"))

    if "status" in changed_field_names:
        status_name = ((fields.get("status") or {}).get("name"))
        if status_name is not None:
            normalized_fields["state"] = status_name

    if "labels" in changed_field_names:
        normalized_fields["labels"] = list(fields.get("labels") or [])

    return PartialUpdate(
        external_id=str(issue.get("id") or issue.get("key") or ""),
        source="jira",
        fields=normalized_fields,
    )
