-- Logical record organization. Original cases, documents and reports remain immutable.
CREATE TABLE IF NOT EXISTS medical_records (
    record_id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES actors(actor_id),
    subject_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS medical_records_owner_idx ON medical_records(actor_id,subject_id);
CREATE TABLE IF NOT EXISTS medical_record_cases (
    case_id uuid PRIMARY KEY REFERENCES cases(case_id),
    record_id uuid NOT NULL REFERENCES medical_records(record_id),
    related_record_id uuid REFERENCES medical_records(record_id),
    proposed_record_id uuid REFERENCES medical_records(record_id),
    relation text NOT NULL DEFAULT 'independent' CHECK (relation IN ('same_episode','follow_up','new_episode','uncertain','mixed','independent')),
    assignment_source text NOT NULL DEFAULT 'provisional' CHECK (assignment_source IN ('provisional','ai','user')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','ready','needs_confirmation','unavailable')),
    profile jsonb NOT NULL DEFAULT '{}'::jsonb,
    decision jsonb NOT NULL DEFAULT '{}'::jsonb,
    run_id uuid REFERENCES analysis_runs(run_id),
    version integer NOT NULL DEFAULT 1 CHECK (version>0),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS medical_record_cases_record_idx ON medical_record_cases(record_id);
CREATE TABLE IF NOT EXISTS medical_record_jobs (
    run_id uuid PRIMARY KEY REFERENCES analysis_runs(run_id),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','failed','obsolete')),
    attempts integer NOT NULL DEFAULT 0,
    lease_token uuid,
    lease_expires_at timestamptz,
    error_code text,
    model_id text,
    prompt_version text,
    usage_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS medical_record_jobs_queue_idx ON medical_record_jobs(status,created_at);
CREATE TABLE IF NOT EXISTS medical_record_audit (
    event_id uuid PRIMARY KEY,
    case_id uuid NOT NULL REFERENCES cases(case_id),
    actor_id uuid NOT NULL REFERENCES actors(actor_id),
    run_id uuid REFERENCES analysis_runs(run_id),
    previous_record_id uuid,
    record_id uuid NOT NULL REFERENCES medical_records(record_id),
    assignment_source text NOT NULL CHECK (assignment_source IN ('ai','user')),
    decision jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
