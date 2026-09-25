CREATE TABLE IF NOT EXISTS medical_events (
    event_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES analysis_runs(run_id),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    encounter_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('diagnosis', 'surgery', 'medication', 'stay', 'cost')),
    assertion text NOT NULL CHECK (assertion IN ('present', 'negated', 'suspected', 'historical', 'unknown')),
    occurred_at jsonb,
    time_precision text NOT NULL CHECK (time_precision IN ('datetime', 'day', 'month', 'year', 'interval', 'unknown')),
    attributes jsonb NOT NULL,
    evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    confidence_score double precision CHECK (confidence_score IS NULL OR confidence_score BETWEEN 0 AND 1),
    builder_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, event_type)
);

CREATE TABLE IF NOT EXISTS event_relations (
    relation_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES analysis_runs(run_id),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    from_event_id uuid NOT NULL REFERENCES medical_events(event_id) ON DELETE CASCADE,
    relation_type text NOT NULL,
    to_ref jsonb NOT NULL,
    evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    status text NOT NULL CHECK (status IN ('supported', 'conflict', 'indeterminate')),
    builder_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, from_event_id, relation_type)
);

CREATE INDEX IF NOT EXISTS medical_events_case_run_idx ON medical_events(case_id, run_id);
CREATE INDEX IF NOT EXISTS event_relations_case_run_idx ON event_relations(case_id, run_id);
