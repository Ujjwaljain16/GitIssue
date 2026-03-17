from app.normalizer.clean import clean_body
from app.normalizer.normalize import normalize



def test_clean_body_masks_code_and_links() -> None:
    text = "See `x=1` and ```python\nprint('x')\n``` plus https://example.com/path"
    cleaned = clean_body(text)

    assert "[INLINE_CODE]" in cleaned
    assert "[CODE]" in cleaned
    assert "[URL]" in cleaned



def test_normalize_minimal_issue_payload() -> None:
    payload = {
        "action": "opened",
        "repository": {"full_name": "acme/repo"},
        "issue": {
            "number": 42,
            "title": "Bug",
            "body": "broken",
            "labels": [{"name": "bug"}],
            "user": {"login": "alice"},
            "state": "open",
            "created_at": "2026-03-17T10:00:00Z",
            "updated_at": "2026-03-17T10:01:00Z",
        },
    }

    normalized = normalize(payload)

    assert normalized.external_id == "github:acme/repo#42"
    assert normalized.repo == "acme/repo"
    assert normalized.issue_number == 42
    assert normalized.labels == ["bug"]
    assert normalized.author == "alice"


def test_normalize_handles_null_body_and_empty_labels() -> None:
    payload = {
        "action": "opened",
        "repository": {"full_name": "acme/repo"},
        "issue": {
            "number": 7,
            "title": "Null body",
            "body": None,
            "labels": [],
            "user": {"login": "bob"},
            "state": "open",
            "created_at": "2026-03-17T10:00:00Z",
            "updated_at": "2026-03-17T10:01:00Z",
        },
    }

    normalized = normalize(payload)

    assert normalized.body == ""
    assert normalized.clean_body == ""
    assert normalized.labels == []


def test_normalize_raises_for_malformed_payload() -> None:
    malformed_payload = {
        "action": "opened",
        "repository": {"full_name": "acme/repo"},
    }

    try:
        normalize(malformed_payload)
    except KeyError:
        pass
    else:
        raise AssertionError("normalize should fail on malformed payload")
