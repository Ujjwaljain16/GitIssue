CREATE TABLE IF NOT EXISTS issues (
    id SERIAL PRIMARY KEY,
    external_id TEXT UNIQUE,
    repo TEXT NOT NULL,
    issue_number INT NOT NULL,
    state TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    clean_body TEXT NOT NULL,
    author TEXT NOT NULL,
    labels TEXT[] NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    inserted_at TIMESTAMP NOT NULL DEFAULT NOW(),
    raw_payload JSONB NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_repo_issue ON issues(repo, issue_number);
