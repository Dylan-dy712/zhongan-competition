ALTER TABLE actors ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'patient'
    CHECK (role IN ('patient','medical_reviewer','customer_service','evaluator','system'));

ALTER TABLE insights DROP CONSTRAINT IF EXISTS insights_check1;
ALTER TABLE insights DROP CONSTRAINT IF EXISTS insights_clinical_review_state_chk;
ALTER TABLE insights ADD CONSTRAINT insights_clinical_review_state_chk
    CHECK (category <> 'clinical' OR review_status <> 'not_required');

CREATE TABLE IF NOT EXISTS review_tasks (
    review_id uuid PRIMARY KEY,
    case_id uuid NOT NULL REFERENCES cases(case_id),
    run_id uuid NOT NULL REFERENCES analysis_runs(run_id),
    target_type text NOT NULL CHECK (target_type IN ('insight')),
    target_id uuid NOT NULL,
    target_version integer NOT NULL DEFAULT 1 CHECK (target_version > 0),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','decided','cancelled')),
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    UNIQUE (target_type,target_id,target_version)
);
CREATE INDEX IF NOT EXISTS review_tasks_queue_idx ON review_tasks(status,created_at,review_id);

CREATE TABLE IF NOT EXISTS review_decisions (
    decision_id uuid PRIMARY KEY,
    review_id uuid NOT NULL UNIQUE REFERENCES review_tasks(review_id),
    target_type text NOT NULL,
    target_id uuid NOT NULL,
    target_version integer NOT NULL CHECK (target_version > 0),
    decision text NOT NULL CHECK (decision IN ('approve','correct','reject')),
    reason text NOT NULL,
    corrections jsonb NOT NULL DEFAULT '[]'::jsonb,
    reviewer_id uuid NOT NULL REFERENCES actors(actor_id),
    decided_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS insight_revisions (
    insight_id uuid NOT NULL REFERENCES insights(insight_id),
    version integer NOT NULL CHECK (version > 1),
    payload jsonb NOT NULL,
    review_id uuid NOT NULL REFERENCES review_tasks(review_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (insight_id,version)
);
