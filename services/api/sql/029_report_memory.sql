-- Separate explicit permission to share confirmed private memory with reports/reviewers.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS report_memory_enabled boolean NOT NULL DEFAULT false;
