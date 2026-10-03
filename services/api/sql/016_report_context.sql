-- Explicit sharing of user utterances with case-authorized report readers.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS report_context_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS report_context_version integer NOT NULL DEFAULT 1;
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS context_snapshot jsonb;

CREATE OR REPLACE FUNCTION freeze_run_context() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN
    IF NEW.context_snapshot IS DISTINCT FROM OLD.context_snapshot THEN
        RAISE EXCEPTION 'analysis context snapshot is immutable';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS analysis_context_immutable ON analysis_runs;
CREATE TRIGGER analysis_context_immutable BEFORE UPDATE OF context_snapshot ON analysis_runs
    FOR EACH ROW EXECUTE FUNCTION freeze_run_context();
