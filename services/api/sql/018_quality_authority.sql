-- Stable entity mapping, case attribution and immutable quality snapshots (KR4).
CREATE TABLE IF NOT EXISTS entity_mappings (
    entity_id uuid PRIMARY KEY,
    entity_type text NOT NULL CHECK (entity_type IN ('hospital','doctor','treatment_plan')),
    display_name text NOT NULL,
    normalized_name text NOT NULL,
    source_evidence_ids jsonb NOT NULL,
    created_by uuid NOT NULL REFERENCES actors(actor_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_type, normalized_name)
);
CREATE TABLE IF NOT EXISTS case_entity_attribution (
    case_id uuid NOT NULL REFERENCES cases(case_id),
    run_id uuid NOT NULL REFERENCES analysis_runs(run_id),
    entity_id uuid NOT NULL REFERENCES entity_mappings(entity_id),
    evidence_ids jsonb NOT NULL,
    created_by uuid NOT NULL REFERENCES actors(actor_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, entity_id)
);
CREATE TABLE IF NOT EXISTS quality_snapshots (
    snapshot_id uuid PRIMARY KEY,
    dataset_version text NOT NULL,
    data_origin text NOT NULL,
    policy jsonb NOT NULL,
    manifest_hash char(64) NOT NULL UNIQUE,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    payload jsonb NOT NULL,
    created_by uuid NOT NULL REFERENCES actors(actor_id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION freeze_quality_snapshot() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN
    IF NEW.payload IS DISTINCT FROM OLD.payload OR NEW.policy IS DISTINCT FROM OLD.policy
       OR NEW.manifest_hash IS DISTINCT FROM OLD.manifest_hash THEN
        RAISE EXCEPTION 'quality snapshot is immutable';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS quality_snapshot_immutable ON quality_snapshots;
CREATE TRIGGER quality_snapshot_immutable BEFORE UPDATE ON quality_snapshots
    FOR EACH ROW EXECUTE FUNCTION freeze_quality_snapshot();
