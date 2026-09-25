CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id uuid PRIMARY KEY,
    case_id uuid NOT NULL REFERENCES cases(case_id),
    input_hash char(64) NOT NULL,
    schema_version text NOT NULL,
    pipeline_version text NOT NULL,
    document_versions jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('queued', 'running', 'waiting_review', 'completed', 'failed', 'cancelled')),
    current_stage text NOT NULL CHECK (current_stage IN ('parse', 'extract', 'reconcile', 'insights', 'guidance', 'recommend', 'validate')),
    stage_results jsonb NOT NULL DEFAULT '{}'::jsonb,
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts integer NOT NULL DEFAULT 2 CHECK (max_attempts > 0),
    lease_token uuid,
    lease_expires_at timestamptz,
    error jsonb,
    execution_mode text NOT NULL CHECK (execution_mode IN ('live', 'mock', 'replay')),
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS analysis_runs_queue_idx
    ON analysis_runs(status, created_at);
CREATE INDEX IF NOT EXISTS analysis_runs_case_input_idx
    ON analysis_runs(case_id, input_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS document_pages (
    document_id uuid NOT NULL REFERENCES documents(document_id),
    document_version integer NOT NULL,
    page_index integer NOT NULL CHECK (page_index >= 0),
    text_content text,
    content_hash char(64),
    parser_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('parsed', 'unreadable', 'failed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, document_version, page_index)
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES analysis_runs(run_id),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    document_id uuid NOT NULL REFERENCES documents(document_id),
    document_version integer NOT NULL,
    page_index integer,
    text_start integer,
    text_end integer,
    text_value text,
    offset_unit text NOT NULL DEFAULT 'unicode_code_point',
    bbox jsonb,
    extraction_method text NOT NULL,
    source_hash char(64) NOT NULL,
    parser_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((text_start IS NULL AND text_end IS NULL AND text_value IS NULL)
        OR (text_start >= 0 AND text_end > text_start AND text_value IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS evidence_case_run_idx ON evidence(case_id, run_id);
CREATE INDEX IF NOT EXISTS evidence_document_idx ON evidence(document_id, document_version, page_index);
