CREATE TABLE IF NOT EXISTS account_members (
    actor_id uuid NOT NULL REFERENCES user_accounts(actor_id),
    subject_id uuid NOT NULL,
    name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 40),
    relationship text NOT NULL CHECK (relationship IN ('self','parent','spouse','child','other')),
    gender text NOT NULL DEFAULT 'unspecified' CHECK (gender IN ('male','female','unspecified')),
    birth_date date,
    profile_completed boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id,subject_id),
    FOREIGN KEY (actor_id,subject_id) REFERENCES actor_subject_access(actor_id,subject_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS account_members_self_idx ON account_members(actor_id) WHERE relationship='self';
INSERT INTO account_members(actor_id,subject_id,name,relationship)
SELECT actor_id,subject_id,display_name,'self' FROM user_accounts
ON CONFLICT (actor_id,subject_id) DO NOTHING;
