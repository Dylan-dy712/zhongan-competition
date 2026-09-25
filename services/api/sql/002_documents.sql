CREATE TABLE IF NOT EXISTS documents (
    document_id uuid PRIMARY KEY,
    case_id uuid NOT NULL REFERENCES cases(case_id),
    document_version integer NOT NULL DEFAULT 1 CHECK (document_version > 0),
    document_type text,
    media_type text NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    page_count integer CHECK (page_count >= 0),
    source_hash char(64) NOT NULL,
    source_ref text NOT NULL,
    storage_ref text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('registered', 'parsing', 'parsed', 'unreadable', 'failed')),
    policy_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, source_hash)
);
CREATE INDEX IF NOT EXISTS documents_case_created_idx
    ON documents(case_id, created_at, document_id);
