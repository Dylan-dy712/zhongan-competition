-- Feedback resolution audit: who handled each triage item and why.
ALTER TABLE care_feedback ADD COLUMN IF NOT EXISTS resolved_by uuid REFERENCES actors(actor_id);
ALTER TABLE care_feedback ADD COLUMN IF NOT EXISTS resolved_at timestamptz;
ALTER TABLE care_feedback ADD COLUMN IF NOT EXISTS resolution_reason text;
ALTER TABLE care_feedback ADD COLUMN IF NOT EXISTS resolution_version integer NOT NULL DEFAULT 0;
