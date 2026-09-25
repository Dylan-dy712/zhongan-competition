-- REQ-01 minimal PostgreSQL schema. Apply to an isolated development database.
CREATE TABLE IF NOT EXISTS actors (
    actor_id uuid PRIMARY KEY,
    token_sha256 char(64) UNIQUE NOT NULL,
    active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS actor_subject_access (
    actor_id uuid NOT NULL REFERENCES actors(actor_id),
    subject_id uuid NOT NULL,
    can_create_case boolean NOT NULL DEFAULT false,
    can_read_case boolean NOT NULL DEFAULT false,
    PRIMARY KEY (actor_id, subject_id)
);
CREATE TABLE IF NOT EXISTS consents (
    consent_id uuid PRIMARY KEY,
    subject_id uuid NOT NULL,
    notice_version text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS consent_purposes (
    consent_id uuid NOT NULL REFERENCES consents(consent_id),
    purpose text NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'revoked', 'expired')),
    granted_at timestamptz NOT NULL,
    revoked_at timestamptz,
    expires_at timestamptz,
    PRIMARY KEY (consent_id, purpose)
);
CREATE TABLE IF NOT EXISTS cases (
    case_id uuid PRIMARY KEY,
    subject_id uuid NOT NULL,
    consent_id uuid NOT NULL REFERENCES consents(consent_id),
    created_by uuid NOT NULL REFERENCES actors(actor_id),
    source_system text,
    external_case_id text,
    source_ref text NOT NULL,
    user_context jsonb,
    data_origin text NOT NULL CHECK (data_origin IN ('official_deidentified', 'authorized_historical', 'synthetic')),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    idempotency_key text NOT NULL,
    request_hash char(64) NOT NULL,
    UNIQUE (created_by, idempotency_key)
);
CREATE INDEX IF NOT EXISTS cases_subject_created_idx ON cases(subject_id, created_at DESC, case_id DESC);
