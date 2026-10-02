ALTER TABLE review_tasks DROP CONSTRAINT IF EXISTS review_tasks_target_type_check;
ALTER TABLE review_tasks ADD CONSTRAINT review_tasks_target_type_check
    CHECK (target_type IN ('insight','report'));
ALTER TABLE reports ADD COLUMN IF NOT EXISTS review_parent_id uuid REFERENCES reports(report_id);
ALTER TABLE review_decisions ADD COLUMN IF NOT EXISTS result_report_id uuid REFERENCES reports(report_id);
ALTER TABLE review_decisions ADD COLUMN IF NOT EXISTS idempotency_key text;
ALTER TABLE review_decisions ADD COLUMN IF NOT EXISTS request_hash char(64);
CREATE UNIQUE INDEX IF NOT EXISTS review_decision_idempotency_idx
    ON review_decisions(reviewer_id,idempotency_key) WHERE idempotency_key IS NOT NULL;

-- Existing pending drafts need the same review entry point as future worker output.
INSERT INTO review_tasks(review_id,case_id,run_id,target_type,target_id,target_version,status,reason)
SELECT r.report_id,r.case_id,r.run_id,'report',r.report_id,r.report_version,'pending','report_requires_review'
FROM reports r WHERE r.status='pending_review'
ON CONFLICT (target_type,target_id,target_version) DO NOTHING;
