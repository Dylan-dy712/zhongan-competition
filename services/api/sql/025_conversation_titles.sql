-- Best-effort metadata jobs, independent of chat/report delivery.
CREATE TABLE IF NOT EXISTS conversation_title_jobs (
    conversation_id uuid PRIMARY KEY REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    requested_turn_id uuid NOT NULL REFERENCES conversation_turns(turn_id) ON DELETE CASCADE,
    requested_created_at timestamptz NOT NULL,
    completed_turn_id uuid,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','failed')),
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    lease_token uuid,
    lease_expires_at timestamptz,
    prompt_version text,
    model_id text,
    error_code text
);
CREATE INDEX IF NOT EXISTS conversation_titles_pending_idx
    ON conversation_title_jobs(next_attempt_at) WHERE status IN ('queued','running');
