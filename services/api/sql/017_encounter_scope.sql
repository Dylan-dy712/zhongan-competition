-- A run can cover several visits, so facts and events are scoped per encounter key
-- (see worker.assign_encounter_keys). extracted_facts no longer assumes one row per
-- (run_id, fact_type): each visit keeps its own field value, and medications keep one
-- row per (drug, phase). Rows are rebuilt after the per-run delete, and lookup breadth
-- still comes from extracted_facts_case_run_idx.
ALTER TABLE extracted_facts DROP CONSTRAINT IF EXISTS extracted_facts_run_id_fact_type_key;
ALTER TABLE extracted_facts ADD COLUMN IF NOT EXISTS encounter_key text;

-- Event identity is the deterministic event_id primary key (uuid5 of run, encounter
-- and fact), so the (run_id, event_type, fact_type) uniqueness from 015 is retired in
-- favor of an encounter-aware lookup index.
DROP INDEX IF EXISTS medical_events_run_fact_type_idx;
CREATE INDEX IF NOT EXISTS medical_events_run_encounter_idx ON medical_events (run_id, encounter_id);

-- Structured staff extractions get their own audit column, keeping the candidates
-- jsonb in its historical list shape for external auditors and exports.
ALTER TABLE model_extractions ADD COLUMN IF NOT EXISTS personnel jsonb NOT NULL DEFAULT '[]'::jsonb;
