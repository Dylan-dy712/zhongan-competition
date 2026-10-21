-- Page-level extraction can retain usable fields while marking other fields for review.
-- Preserve that status rather than rolling back all material/report persistence.
ALTER TABLE model_extractions DROP CONSTRAINT IF EXISTS model_extractions_status_check;
ALTER TABLE model_extractions ADD CONSTRAINT model_extractions_status_check
    CHECK (status IN ('completed', 'partial', 'invalid', 'failed', 'not_configured'));
