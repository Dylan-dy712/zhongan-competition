CREATE TABLE IF NOT EXISTS delivery_receipts (
    receipt_id uuid PRIMARY KEY,
    outbox_id uuid NOT NULL REFERENCES care_outbox(outbox_id),
    actor_id uuid NOT NULL REFERENCES actors(actor_id),
    receipt_version integer NOT NULL CHECK (receipt_version>0),
    state text NOT NULL CHECK (state IN ('presented','read')),
    idempotency_key text NOT NULL,
    request_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(actor_id,idempotency_key),
    UNIQUE(outbox_id,actor_id,receipt_version),
    UNIQUE(outbox_id,actor_id,state)
);
CREATE TABLE IF NOT EXISTS care_feedback (
    feedback_id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES actors(actor_id),
    subject_id uuid NOT NULL,
    case_id uuid NOT NULL REFERENCES cases(case_id),
    report_id uuid NOT NULL REFERENCES reports(report_id),
    report_version integer NOT NULL CHECK (report_version>0),
    action_id uuid,
    type text NOT NULL CHECK (type IN ('helpful','not_helpful','inaccurate','needs_help')),
    text text,
    consent_id uuid NOT NULL REFERENCES consents(consent_id),
    consent_version integer NOT NULL CHECK (consent_version>0),
    triage_status text NOT NULL CHECK (triage_status IN ('not_required','pending','resolved')),
    idempotency_key text NOT NULL,
    request_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(actor_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS care_feedback_triage_idx ON care_feedback(triage_status,created_at,feedback_id);
