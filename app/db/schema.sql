CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

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
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    inserted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    raw_payload JSONB NOT NULL,
    embedding vector(384)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_repo_issue ON issues(repo, issue_number);

-- Migration: Ensure timezone-aware timestamps
ALTER TABLE IF EXISTS issues ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE;
ALTER TABLE IF EXISTS issues ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE;
ALTER TABLE IF EXISTS issues ALTER COLUMN inserted_at TYPE TIMESTAMP WITH TIME ZONE;

CREATE TABLE IF NOT EXISTS issue_signals (
    issue_id INT PRIMARY KEY REFERENCES issues(id) ON DELETE CASCADE,
    file_paths TEXT[] DEFAULT ARRAY[]::TEXT[],
    error_messages TEXT[] DEFAULT ARRAY[]::TEXT[],
    stack_trace TEXT,
    has_stack_trace BOOLEAN NOT NULL DEFAULT FALSE,
    signal_strength FLOAT NOT NULL DEFAULT 0.0 CHECK (signal_strength BETWEEN 0 AND 1),
    extracted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS duplicate_suggestions (
    id SERIAL PRIMARY KEY,
    source_issue_external_id TEXT NOT NULL,
    suggested_issue_external_id TEXT NOT NULL,
    semantic_score FLOAT,
    keyword_score FLOAT,
    structural_score FLOAT,
    label_score FLOAT,
    final_score FLOAT NOT NULL,
    suggested_at TIMESTAMP DEFAULT NOW(),
    user_feedback TEXT,
    feedback_at TIMESTAMP,
    UNIQUE(source_issue_external_id, suggested_issue_external_id)
);

    ALTER TABLE duplicate_suggestions
        ADD COLUMN IF NOT EXISTS repo TEXT,
        ADD COLUMN IF NOT EXISTS source_signal_strength FLOAT,
        ADD COLUMN IF NOT EXISTS candidate_signal_strength FLOAT,
        ADD COLUMN IF NOT EXISTS source_file_paths TEXT[] DEFAULT ARRAY[]::TEXT[],
        ADD COLUMN IF NOT EXISTS source_error_messages TEXT[] DEFAULT ARRAY[]::TEXT[],
        ADD COLUMN IF NOT EXISTS source_has_stack_trace BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS candidate_file_paths TEXT[] DEFAULT ARRAY[]::TEXT[],
        ADD COLUMN IF NOT EXISTS candidate_error_messages TEXT[] DEFAULT ARRAY[]::TEXT[],
        ADD COLUMN IF NOT EXISTS candidate_has_stack_trace BOOLEAN DEFAULT FALSE;

    CREATE TABLE IF NOT EXISTS suggestion_labels (
        suggestion_id INT PRIMARY KEY REFERENCES duplicate_suggestions(id) ON DELETE CASCADE,
        label TEXT NOT NULL CHECK (label IN (
            'true_positive',
            'false_positive',
            'related_not_duplicate',
            'cant_tell'
        )),
        notes TEXT,
        labeled_by TEXT,
        labeled_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS known_duplicates (
        id SERIAL PRIMARY KEY,
        repo TEXT NOT NULL,
        source_external_id TEXT NOT NULL,
        target_external_id TEXT NOT NULL,
        evidence TEXT,
        captured_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        UNIQUE (repo, source_external_id, target_external_id)
    );

    CREATE INDEX IF NOT EXISTS idx_duplicate_suggestions_repo_time ON duplicate_suggestions(repo, suggested_at DESC);
    CREATE INDEX IF NOT EXISTS idx_known_duplicates_repo ON known_duplicates(repo);

CREATE INDEX IF NOT EXISTS idx_signals_files ON issue_signals USING GIN (file_paths);
CREATE INDEX IF NOT EXISTS idx_signals_errors ON issue_signals USING GIN (error_messages);

-- Vector similarity search (cosine distance)
CREATE INDEX IF NOT EXISTS idx_embedding ON issues
USING hnsw (embedding vector_cosine_ops);

-- Full-text search on clean body
CREATE INDEX IF NOT EXISTS idx_fts ON issues
USING GIN (to_tsvector('english', clean_body));

CREATE TABLE IF NOT EXISTS issue_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_title TEXT NOT NULL,
    canonical_state TEXT NOT NULL
        CHECK (canonical_state IN ('open', 'closed', 'merged', 'likely_resolved')),
    merged_into UUID REFERENCES issue_nodes(id),
    merged_at TIMESTAMP WITH TIME ZONE,
    confidence FLOAT NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT merged_consistency CHECK (
        (canonical_state = 'merged') = (merged_into IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS issue_node_map (
    issue_id INT PRIMARY KEY REFERENCES issues(id) ON DELETE CASCADE,
    node_id UUID NOT NULL REFERENCES issue_nodes(id),
    mapped_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    mapped_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issue_edges (
    id SERIAL PRIMARY KEY,
    from_node UUID NOT NULL REFERENCES issue_nodes(id),
    to_node UUID NOT NULL REFERENCES issue_nodes(id),
    edge_type TEXT NOT NULL
        CHECK (edge_type IN ('duplicate_of', 'related_to', 'blocks')),
    confidence FLOAT NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    source TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT no_self_loop CHECK (from_node != to_node),
    CONSTRAINT canonical_direction CHECK (from_node < to_node),
    CONSTRAINT unique_edge UNIQUE (from_node, to_node, edge_type)
);

CREATE TABLE IF NOT EXISTS node_events (
    id SERIAL PRIMARY KEY,
    node_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_edges_from ON issue_edges(from_node);
CREATE INDEX IF NOT EXISTS idx_edges_to ON issue_edges(to_node);
CREATE INDEX IF NOT EXISTS idx_node_map_node ON issue_node_map(node_id);

CREATE TABLE IF NOT EXISTS issue_representations (
    id SERIAL PRIMARY KEY,
    node_id UUID NOT NULL REFERENCES issue_nodes(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT,
    body TEXT,
    state TEXT,
    labels TEXT[] DEFAULT ARRAY[]::TEXT[],
    visibility TEXT NOT NULL DEFAULT 'private'
        CHECK (visibility IN ('public', 'internal', 'private')),
    org_id TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS sync_events (
    id SERIAL PRIMARY KEY,
    node_id UUID NOT NULL REFERENCES issue_nodes(id) ON DELETE CASCADE,
    field TEXT NOT NULL,
    change_hash TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    external_event_id TEXT,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (node_id, field, change_hash, target)
);

CREATE TABLE IF NOT EXISTS sync_jobs (
    id SERIAL PRIMARY KEY,
    node_id UUID NOT NULL REFERENCES issue_nodes(id) ON DELETE CASCADE,
    field TEXT NOT NULL,
    value TEXT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'retry', 'done', 'dead_letter')),
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    next_retry_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_issue_reps_node ON issue_representations(node_id);
CREATE INDEX IF NOT EXISTS idx_issue_reps_visibility ON issue_representations(visibility, org_id);
CREATE INDEX IF NOT EXISTS idx_sync_events_window ON sync_events(node_id, field, target, synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_jobs_pending ON sync_jobs(status, next_retry_at);
