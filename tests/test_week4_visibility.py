from app.sync.visibility import can_surface


def test_public_visibility_always_visible():
    rep = {"visibility": "public", "org_id": "acme", "source": "jira"}
    assert can_surface(rep, context="github-webhook", org="other") is True


def test_internal_visibility_requires_same_org():
    rep = {"visibility": "internal", "org_id": "acme", "source": "jira"}
    assert can_surface(rep, context="jira-webhook", org="acme") is True
    assert can_surface(rep, context="jira-webhook", org="other") is False


def test_private_visibility_scoped_to_source_context():
    rep = {"visibility": "private", "org_id": "acme", "source": "jira"}
    assert can_surface(rep, context="jira-worker", org="acme") is True
    assert can_surface(rep, context="github-worker", org="acme") is False
