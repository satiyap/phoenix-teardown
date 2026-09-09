-- Existing runs remain explicitly unassigned; creator membership is not evidence
-- of historical team ownership. Do not guess a backfill that grants access.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS team_id TEXT;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'runs_team_binding_fk' AND conrelid = 'runs'::regclass) THEN
        ALTER TABLE runs ADD CONSTRAINT runs_team_binding_fk FOREIGN KEY (tenant_id, team_id)
            REFERENCES teams (tenant_id, team_id);
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS runs_team_visibility ON runs (tenant_id, team_id, run_id DESC);
CREATE OR REPLACE FUNCTION refuse_run_team_reassignment() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.team_id IS DISTINCT FROM OLD.team_id THEN
        RAISE EXCEPTION 'run team ownership is immutable; historical reconciliation needs an explicitly audited path'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS runs_team_immutable ON runs;
CREATE TRIGGER runs_team_immutable BEFORE UPDATE OF team_id ON runs
    FOR EACH ROW EXECUTE FUNCTION refuse_run_team_reassignment();
