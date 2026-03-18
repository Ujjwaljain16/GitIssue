from app.sync.policy import merge_field_value, should_apply


def test_owner_wins_policy():
    assert should_apply("github", "title") is True
    assert should_apply("jira", "title") is False


def test_state_owned_by_jira():
    assert should_apply("jira", "state") is True
    assert should_apply("github", "state") is False


def test_labels_union_policy():
    merged = merge_field_value("labels", ["bug", "backend"], ["bug", "urgent"])
    assert merged == ["backend", "bug", "urgent"]
