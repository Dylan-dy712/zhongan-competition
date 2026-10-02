CREATE TABLE IF NOT EXISTS report_releases (
    release_id uuid PRIMARY KEY,
    report_id uuid NOT NULL UNIQUE REFERENCES reports(report_id),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    report_version integer NOT NULL CHECK (report_version>0),
    released_by uuid NOT NULL REFERENCES actors(actor_id),
    consent_id uuid NOT NULL REFERENCES consents(consent_id),
    consent_version integer NOT NULL CHECK (consent_version>0),
    input_hash char(64) NOT NULL,
    knowledge_version text NOT NULL,
    policy_version text NOT NULL,
    idempotency_key text NOT NULL,
    request_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(released_by,idempotency_key)
);
CREATE TABLE IF NOT EXISTS care_outbox (
    outbox_id uuid PRIMARY KEY,
    release_id uuid NOT NULL UNIQUE REFERENCES report_releases(release_id),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    channel text NOT NULL DEFAULT 'app' CHECK (channel='app'),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','cancelled','acknowledged')),
    created_at timestamptz NOT NULL DEFAULT now()
);
