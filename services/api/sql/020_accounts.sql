CREATE TABLE IF NOT EXISTS user_accounts (
    actor_id uuid PRIMARY KEY REFERENCES actors(actor_id),
    username text UNIQUE NOT NULL,
    subject_id uuid UNIQUE NOT NULL,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(actor_id,subject_id) REFERENCES actor_subject_access(actor_id,subject_id)
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_sha256 char(64) PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES user_accounts(actor_id),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_sessions_actor_idx ON auth_sessions(actor_id);
CREATE TABLE IF NOT EXISTS auth_attempts (
    attempt_key char(64) PRIMARY KEY,
    attempts integer NOT NULL DEFAULT 0,
    window_started_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS account_consent_operations (
    actor_id uuid NOT NULL REFERENCES user_accounts(actor_id),
    idempotency_key text NOT NULL,
    request_hash char(64) NOT NULL,
    response jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(actor_id,idempotency_key)
);
