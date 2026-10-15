-- One-time retry for titles affected by the original GLM thinking-mode mismatch.
-- The worker rechecks live conversation authorization before any model request.
UPDATE conversation_title_jobs SET status='queued',attempts=0,next_attempt_at=now(),
    lease_token=NULL,lease_expires_at=NULL,error_code=NULL
WHERE status IN ('queued','failed') AND error_code='TITLE_GENERATION_FAILED';
