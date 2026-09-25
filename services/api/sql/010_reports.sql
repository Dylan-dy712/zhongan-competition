CREATE TABLE IF NOT EXISTS reports (
    report_id uuid PRIMARY KEY,
    case_id uuid NOT NULL REFERENCES cases(case_id),
    run_id uuid NOT NULL REFERENCES analysis_runs(run_id),
    report_version integer NOT NULL CHECK (report_version > 0),
    status text NOT NULL CHECK (status IN ('draft','validating','ready','pending_review','rejected','published','superseded','invalidated')),
    sections jsonb NOT NULL,
    actions jsonb NOT NULL DEFAULT '[]'::jsonb,
    input_hash char(64) NOT NULL,
    model_id text NOT NULL,
    prompt_version text NOT NULL,
    knowledge_version text NOT NULL,
    policy_version text NOT NULL,
    memory_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    consent_refs jsonb NOT NULL,
    validation_errors jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id,report_version), UNIQUE (run_id,report_version),
    CHECK (jsonb_array_length(actions) <= 3)
);
CREATE INDEX IF NOT EXISTS reports_case_version_idx ON reports(case_id,report_version DESC);
