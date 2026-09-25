CREATE TABLE IF NOT EXISTS extracted_facts (
    fact_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES analysis_runs(run_id),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    fact_type text NOT NULL CHECK (fact_type IN ('diagnosis', 'surgery', 'medication', 'stay_days', 'total_cost')),
    value jsonb,
    raw_value text,
    status text NOT NULL CHECK (status IN ('observed', 'derived', 'missing', 'unreadable', 'conflict', 'not_applicable')),
    assertion text NOT NULL CHECK (assertion IN ('present', 'negated', 'suspected', 'historical', 'unknown')),
    evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    confidence_score double precision CHECK (confidence_score IS NULL OR confidence_score BETWEEN 0 AND 1),
    confidence_method text,
    unit text,
    derivation jsonb,
    alternatives jsonb NOT NULL DEFAULT '[]'::jsonb,
    missing_reason text,
    extractor_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, fact_type),
    CHECK (confidence_score IS NULL OR confidence_method IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS extracted_facts_case_run_idx
    ON extracted_facts(case_id, run_id, fact_type);
