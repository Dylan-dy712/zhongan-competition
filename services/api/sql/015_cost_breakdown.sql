-- Keep the five required scalar fields and add the source-bound structured expense field.
ALTER TABLE extracted_facts DROP CONSTRAINT IF EXISTS extracted_facts_fact_type_check;
ALTER TABLE extracted_facts ADD CONSTRAINT extracted_facts_fact_type_check CHECK
    (fact_type IN ('diagnosis','surgery','medication','stay_days','total_cost','cost_breakdown'));
