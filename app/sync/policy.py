from typing import Any

FIELD_POLICY: dict[str, dict[str, str]] = {
    "title": {"owner": "github", "rule": "owner_wins"},
    "body": {"owner": "github", "rule": "owner_wins"},
    "state": {"owner": "jira", "rule": "owner_wins"},
    "labels": {"owner": "both", "rule": "union"},
}


def should_apply(changed_by: str, field: str) -> bool:
    policy = FIELD_POLICY.get(field)
    if policy is None:
        return False

    owner = policy["owner"]
    if owner == "both":
        return True
    return changed_by == owner


def merge_field_value(field: str, current: Any, incoming: Any) -> Any:
    policy = FIELD_POLICY.get(field)
    if policy is None:
        return current

    if policy["rule"] == "union":
        current_set = set(current or [])
        incoming_set = set(incoming or [])
        return sorted(current_set | incoming_set)

    return incoming
