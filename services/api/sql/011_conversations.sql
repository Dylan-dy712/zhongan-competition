-- Conversations belong to an authenticated actor and one care case.
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES actors(actor_id),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    title text NOT NULL DEFAULT '新的关怀对话',
    recall_enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conversations_actor_idx ON conversations(actor_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS conversation_turns (
    turn_id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations(conversation_id),
    request_id uuid NOT NULL,
    question text NOT NULL,
    input_kind text NOT NULL DEFAULT 'user' CHECK (input_kind IN ('user','analysis_ready')),
    attachments jsonb NOT NULL DEFAULT '[]',
    status text NOT NULL CHECK (status IN ('running','completed','failed')),
    answer jsonb,
    tool_events jsonb NOT NULL DEFAULT '[]',
    error_code text,
    lease_token uuid NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    UNIQUE(conversation_id,request_id)
);
CREATE INDEX IF NOT EXISTS conversation_turns_history_idx ON conversation_turns(conversation_id, created_at, turn_id);
