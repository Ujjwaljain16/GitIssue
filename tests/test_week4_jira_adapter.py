from app.sync.jira_adapter import build_jira_status_map, clean_jira, normalize_jira_partial_update


def test_build_jira_status_map_uses_status_category():
    statuses = [
        {"name": "Done", "statusCategory": {"key": "done"}},
        {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
    ]
    mapped = build_jira_status_map(statuses)
    assert mapped["Done"] == "closed"
    assert mapped["In Progress"] == "open"


def test_clean_jira_adf_extracts_text_content():
    adf = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Crash"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "on save"}]},
        ],
    }
    text = clean_jira(adf)
    assert "Crash" in text
    assert "save" in text


def test_normalize_jira_partial_update_only_changed_fields():
    payload = {
        "issue": {
            "id": "JIRA-1",
            "fields": {
                "summary": "Updated summary",
                "description": {"type": "doc", "content": [{"type": "text", "text": "Body"}]},
                "status": {"name": "Done"},
                "labels": ["bug"],
            },
        },
        "changelog": {
            "items": [
                {"field": "status"},
                {"field": "labels"},
            ]
        },
    }

    update = normalize_jira_partial_update(payload)

    assert update.external_id == "JIRA-1"
    assert set(update.fields.keys()) == {"state", "labels"}
    assert update.fields["state"] == "Done"
