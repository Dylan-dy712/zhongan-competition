-- Keep the five required scalar fields and add the source-bound structured expense field.
ALTER TABLE extracted_facts DROP CONSTRAINT IF EXISTS extracted_facts_fact_type_check;
ALTER TABLE extracted_facts ADD CONSTRAINT extracted_facts_fact_type_check CHECK
    (fact_type IN ('diagnosis','surgery','medication','stay_days','total_cost','cost_breakdown'));

-- A scalar total and structured components are distinct facts of the same event type.
-- Fall back to event_type for legacy events without a fact_type attribute.
ALTER TABLE medical_events DROP CONSTRAINT IF EXISTS medical_events_run_id_event_type_key;
CREATE UNIQUE INDEX IF NOT EXISTS medical_events_run_fact_type_idx ON medical_events
    (run_id, event_type, (coalesce(attributes->>'fact_type', event_type)));
