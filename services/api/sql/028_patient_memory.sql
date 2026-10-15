-- REQ-11: product memory is private to an account + patient, never a developer user.db.
ALTER TABLE conversations ALTER COLUMN recall_enabled SET DEFAULT false;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema()
        AND table_name='conversations' AND column_name='memory_settings_version') THEN
        UPDATE conversations SET recall_enabled=false;
    END IF;
END $$;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS memory_export_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS memory_settings_version integer NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS cases_memory_subject_idx ON cases(case_id,subject_id);

CREATE TABLE IF NOT EXISTS patient_memory_settings (
    actor_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    enabled boolean NOT NULL DEFAULT false,
    version integer NOT NULL DEFAULT 0 CHECK (version >= 0),
    epoch bigint NOT NULL DEFAULT 0,
    consent_id uuid REFERENCES consents(consent_id),
    PRIMARY KEY(actor_id,subject_id),
    FOREIGN KEY(actor_id,subject_id) REFERENCES actor_subject_access(actor_id,subject_id)
);
CREATE TABLE IF NOT EXISTS care_memory_candidates (
    candidate_id uuid PRIMARY KEY,
    dedup_key char(64) NOT NULL,
    actor_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    source_turn_id uuid NOT NULL REFERENCES conversation_turns(turn_id),
    scope text NOT NULL CHECK (scope IN ('patient','case')),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    kind text NOT NULL CHECK (kind IN ('communication_preference','confirmed_context')),
    field_key text NOT NULL,
    content text NOT NULL CHECK (length(content) BETWEEN 2 AND 1000),
    expires_at timestamptz,
    source_consent_version integer NOT NULL,
    memory_consent_version integer NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','confirmed','dismissed')),
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(actor_id,subject_id) REFERENCES patient_memory_settings(actor_id,subject_id),
    FOREIGN KEY(case_id,subject_id) REFERENCES cases(case_id,subject_id)
);
CREATE INDEX IF NOT EXISTS memory_candidates_owner_idx ON care_memory_candidates(actor_id,subject_id,status,created_at);
CREATE INDEX IF NOT EXISTS memory_candidates_dedup_idx ON care_memory_candidates(actor_id,subject_id,dedup_key,created_at);
CREATE TABLE IF NOT EXISTS care_memories (
    memory_id uuid NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    actor_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    candidate_id uuid NOT NULL REFERENCES care_memory_candidates(candidate_id),
    source_turn_id uuid NOT NULL REFERENCES conversation_turns(turn_id),
    source_case_id uuid NOT NULL REFERENCES cases(case_id),
    scope text NOT NULL CHECK (scope IN ('patient','case')),
    kind text NOT NULL CHECK (kind IN ('communication_preference','confirmed_context')),
    field_key text NOT NULL,
    content text NOT NULL CHECK (length(content) BETWEEN 2 AND 1000),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked','superseded')),
    source_consent_version integer NOT NULL,
    memory_consent_version integer NOT NULL,
    expires_at timestamptz,
    confirmed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(memory_id,version),
    UNIQUE(candidate_id),
    FOREIGN KEY(actor_id,subject_id) REFERENCES patient_memory_settings(actor_id,subject_id),
    FOREIGN KEY(source_case_id,subject_id) REFERENCES cases(case_id,subject_id)
);
CREATE INDEX IF NOT EXISTS memories_owner_idx ON care_memories(actor_id,subject_id,status,confirmed_at);
CREATE TABLE IF NOT EXISTS care_memory_operations (
    actor_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    idempotency_key text NOT NULL,
    request_hash char(64) NOT NULL,
    response jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(actor_id,subject_id,idempotency_key),
    FOREIGN KEY(actor_id,subject_id) REFERENCES patient_memory_settings(actor_id,subject_id)
);
CREATE TABLE IF NOT EXISTS chat_memory_refs (
    turn_id uuid NOT NULL REFERENCES conversation_turns(turn_id),
    memory_id uuid NOT NULL,
    memory_version integer NOT NULL,
    policy_epoch bigint NOT NULL,
    PRIMARY KEY(turn_id,memory_id,memory_version),
    FOREIGN KEY(memory_id,memory_version) REFERENCES care_memories(memory_id,version)
);
CREATE TABLE IF NOT EXISTS chat_history_refs (
    turn_id uuid NOT NULL REFERENCES conversation_turns(turn_id),
    source_turn_id uuid NOT NULL REFERENCES conversation_turns(turn_id),
    source_consent_version integer NOT NULL,
    source_settings_version integer NOT NULL,
    memory_consent_version integer NOT NULL,
    policy_epoch bigint NOT NULL,
    PRIMARY KEY(turn_id,source_turn_id)
);
