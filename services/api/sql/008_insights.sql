CREATE TABLE IF NOT EXISTS insights (
    insight_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES analysis_runs(run_id),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    category text NOT NULL CHECK (category IN ('clinical','cost','experience')),
    label text NOT NULL CHECK (label IN ('CLIN_MEDICATION_CONTEXT_REVIEW','CLIN_EXAM_JUSTIFICATION_REVIEW','COST_SELF_PAY_DEVIATION','COST_AMOUNT_RECONCILIATION','EXP_TERMINOLOGY_BARRIER','EXP_DISCHARGE_GUIDANCE_GAP')),
    severity text NOT NULL CHECK (severity IN ('low','medium','high','undetermined')),
    confidence double precision CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    confidence_method text,
    evidence_ids jsonb NOT NULL,
    rationale text NOT NULL,
    uncertainty text,
    suggested_action text NOT NULL,
    review_required boolean NOT NULL,
    review_status text NOT NULL CHECK (review_status IN ('not_required','pending','approved','corrected','rejected')),
    judgment_status text NOT NULL CHECK (judgment_status IN ('candidate','supported','indeterminate','rejected')),
    rule_version text NOT NULL,
    knowledge_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, label, insight_id),
    CHECK (confidence IS NULL OR confidence_method IS NOT NULL),
    CHECK (category <> 'clinical' OR (review_required AND review_status <> 'not_required'))
);
CREATE INDEX IF NOT EXISTS insights_case_run_idx ON insights(case_id, run_id);
