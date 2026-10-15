-- Message attachments never enter the report document set or invalidate a saved report.
CREATE TABLE IF NOT EXISTS chat_attachments (
    attachment_id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations(conversation_id),
    name text NOT NULL,
    media_type text NOT NULL CHECK (media_type IN ('image/jpeg','image/png','application/pdf','text/plain')),
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    source_hash char(64) NOT NULL,
    storage_ref text NOT NULL,
    extraction jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, source_hash)
);
