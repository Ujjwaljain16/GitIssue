from app.scoring.hybrid import compute_hybrid_score
from app.sync.jira_adapter import clean_jira


def test_cross_system_similarity_github_vs_jira_adf_text():
    github_text = "Auth fails with NullPointerException in src/auth.py during login"
    jira_adf = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Auth fails with NullPointerException"}
                ],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "in src/auth.py during login"}],
            },
        ],
    }

    jira_text = clean_jira(jira_adf)

    score = compute_hybrid_score(
        semantic_score=1.0,
        text_a=github_text,
        text_b=jira_text,
        labels_a=["bug", "auth"],
        labels_b=["bug", "auth"],
    )

    assert score > 0.8
