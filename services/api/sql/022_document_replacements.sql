-- Preserve original evidence and content; only active documents enter new analyses.
CREATE TABLE IF NOT EXISTS document_replacements (
    old_document_id uuid PRIMARY KEY REFERENCES documents(document_id),
    new_document_id uuid NOT NULL UNIQUE REFERENCES documents(document_id),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    actor_id uuid NOT NULL REFERENCES actors(actor_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (old_document_id <> new_document_id)
);
CREATE INDEX IF NOT EXISTS document_replacements_case_idx ON document_replacements(case_id);
