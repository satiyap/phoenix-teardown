-- Historical runs are not backfilled from current publications: that would invent
-- their execution inputs. A missing pin needs explicit reconciliation before execution.
CREATE TABLE IF NOT EXISTS run_knowledge_pins (
    tenant_id BIGINT NOT NULL,
    run_id TEXT NOT NULL,
    resolution_digest TEXT NOT NULL CHECK (resolution_digest ~ '^[0-9a-f]{64}$'),
    snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id) ON DELETE CASCADE
);
CREATE OR REPLACE FUNCTION refuse_run_knowledge_reassignment() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'run knowledge resolution is immutable; create a new run for changed inputs'
        USING ERRCODE = '23514';
END;
$$;
DROP TRIGGER IF EXISTS run_knowledge_immutable ON run_knowledge_pins;
CREATE TRIGGER run_knowledge_immutable BEFORE UPDATE ON run_knowledge_pins
    FOR EACH ROW EXECUTE FUNCTION refuse_run_knowledge_reassignment();
