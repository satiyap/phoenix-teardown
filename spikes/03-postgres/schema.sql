-- The v0.1 spine, as spec/01-schema.md specifies it, reduced to what the eight
-- Postgres scenarios exercise. Table and column names match the spec exactly so a
-- divergence is a spec bug, not a translation bug.

-- Re-running this file must fully rebuild. CREATE FUNCTION is not idempotent, so a
-- second apply used to ABORT partway and leave a half-built schema -- which is how a
-- test run reported PASS against a database missing the very constraint under test
-- (found 2026-08-27). Hence CREATE OR REPLACE below, and DROP ... CASCADE here.
DROP TRIGGER IF EXISTS run_events_epoch_check ON run_events;
DROP TABLE IF EXISTS approvals, effect_ledger, run_events, run_leases,
                     run_lease_history, runs, principals CASCADE;
DROP TYPE IF EXISTS effect_status, principal_kind CASCADE;

CREATE TYPE principal_kind AS ENUM ('human', 'agent', 'service', 'remote');

CREATE TABLE principals (
    tenant_id    BIGINT NOT NULL,
    principal_id TEXT   NOT NULL,
    kind         principal_kind NOT NULL,
    PRIMARY KEY (tenant_id, principal_id),
    CONSTRAINT principals_id_kind UNIQUE (tenant_id, principal_id, kind)
);

CREATE TABLE runs (
    tenant_id     BIGINT NOT NULL,
    run_id        TEXT   NOT NULL,
    state         TEXT   NOT NULL,
    current_epoch INTEGER NOT NULL DEFAULT 0
        CONSTRAINT runs_epoch_nonneg CHECK (current_epoch >= 0),
    ended_at      TIMESTAMPTZ,
    error_code    TEXT,
    PRIMARY KEY (tenant_id, run_id)
);

CREATE TABLE run_events (
    tenant_id   BIGINT NOT NULL,
    run_id      TEXT   NOT NULL,
    seq         BIGINT NOT NULL,
    epoch       INTEGER NOT NULL CHECK (epoch >= 0),
    event_type  TEXT   NOT NULL,
    payload     JSONB  NOT NULL,
    traceparent TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id, seq),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id)
);
CREATE INDEX run_events_fold ON run_events (tenant_id, run_id, epoch, seq);

CREATE OR REPLACE FUNCTION check_event_epoch() RETURNS trigger AS $$
DECLARE cur INTEGER;
BEGIN
  SELECT current_epoch INTO cur FROM runs
   WHERE tenant_id = NEW.tenant_id AND run_id = NEW.run_id
   FOR UPDATE;

  IF NEW.event_type = 'run.rewound' THEN
    IF NEW.epoch <> cur + 1 THEN
      RAISE EXCEPTION 'a rewind must open epoch %, got %', cur + 1, NEW.epoch
        USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF (NEW.payload->>'to_epoch')::INTEGER > cur THEN
      RAISE EXCEPTION 'cannot supersede epoch % which does not exist yet',
                      NEW.payload->>'to_epoch'
        USING ERRCODE = 'invalid_parameter_value';
    END IF;
    UPDATE runs SET current_epoch = NEW.epoch
     WHERE tenant_id = NEW.tenant_id AND run_id = NEW.run_id;
  ELSE
    IF NEW.epoch <> cur THEN
      RAISE EXCEPTION 'event in epoch % but run is at epoch %', NEW.epoch, cur
        USING ERRCODE = 'invalid_parameter_value';
    END IF;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER run_events_epoch_check
  BEFORE INSERT ON run_events
  FOR EACH ROW EXECUTE FUNCTION check_event_epoch();

CREATE TABLE run_leases (
    tenant_id   BIGINT NOT NULL,
    run_id      TEXT   NOT NULL,
    holder      TEXT   NOT NULL,
    fence_token BIGINT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, run_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id)
);

CREATE TABLE run_lease_history (
    tenant_id       BIGINT NOT NULL,
    run_id          TEXT   NOT NULL,
    max_fence_token BIGINT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id)
);

CREATE TYPE effect_status AS ENUM
    ('intended', 'awaiting_approval', 'claimed', 'succeeded', 'failed',
     'denied', 'abandoned', 'indeterminate');

CREATE TABLE effect_ledger (
    tenant_id       BIGINT NOT NULL,
    idempotency_key TEXT   NOT NULL,
    run_id          TEXT   NOT NULL,
    kind            TEXT   NOT NULL,
    status          effect_status NOT NULL DEFAULT 'intended',
    request_digest  TEXT   NOT NULL,
    result_ref      TEXT,
    error_code      TEXT,
    claim_owner     TEXT,
    claim_token     TEXT,
    claimed_at      TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, idempotency_key),
    UNIQUE (tenant_id, idempotency_key, run_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    CHECK ((status IN ('succeeded','failed')) = (completed_at IS NOT NULL)),
    CONSTRAINT effect_claim_fields_together CHECK (
        (status IN ('intended','awaiting_approval','denied','abandoned')
           AND claim_owner IS NULL AND claim_token IS NULL
           AND lease_expires_at IS NULL)
     OR (status IN ('claimed','succeeded','failed','indeterminate')
           AND claim_owner IS NOT NULL AND claim_token IS NOT NULL
           AND lease_expires_at IS NOT NULL)
    )
);
CREATE INDEX effect_ledger_stuck ON effect_ledger (tenant_id, lease_expires_at)
    WHERE status = 'claimed';
CREATE INDEX effect_ledger_awaiting ON effect_ledger (tenant_id, run_id)
    WHERE status = 'awaiting_approval';

CREATE TABLE approvals (
    tenant_id   BIGINT NOT NULL,
    approval_id TEXT   NOT NULL,
    run_id      TEXT   NOT NULL,
    action_ref  TEXT   NOT NULL,
    status      TEXT   NOT NULL
        CHECK (status IN ('pending','approved','denied','expired','superseded')),
    decided_by  TEXT,
    -- Widened 2026-08-30 (OQ-044, ADR-0015 amendment 4): a 'service' principal may
    -- decide, standing for a customer's external finance/legal approval system.
    decided_by_kind principal_kind
        CHECK (decided_by_kind IS NULL OR decided_by_kind IN ('human', 'service')),
    decided_at  TIMESTAMPTZ,   -- spec/01 name; `responded_at` was the spike's own drift
    expires_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, approval_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    FOREIGN KEY (tenant_id, decided_by, decided_by_kind)
        REFERENCES principals (tenant_id, principal_id, kind),
    FOREIGN KEY (tenant_id, action_ref, run_id)
        REFERENCES effect_ledger (tenant_id, idempotency_key, run_id),
    CHECK ((status IN ('approved','denied'))
           = (decided_by IS NOT NULL AND decided_by_kind IS NOT NULL
              AND decided_at IS NOT NULL))
);
CREATE UNIQUE INDEX approvals_pending_one ON approvals (tenant_id, action_ref)
    WHERE status = 'pending';
