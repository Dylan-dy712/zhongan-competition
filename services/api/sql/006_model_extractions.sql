CREATE TABLE IF NOT EXISTS model_extractions (
    extraction_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES analysis_runs(run_id),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    provider text NOT NULL,
    model_id text NOT NULL,
    prompt_version text NOT NULL,
    schema_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('completed', 'invalid', 'failed', 'not_configured')),
    raw_output jsonb,
    repaired_output jsonb,
    candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
    usage_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, provider, model_id, prompt_version)
);
CREATE INDEX IF NOT EXISTS model_extractions_case_run_idx
    ON model_extractions(case_id, run_id);
