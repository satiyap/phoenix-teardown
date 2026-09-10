-- Observed capability, recorded apart from the intent that asked for it.
--
-- The desired profile in migration 134 says what a deployment meant to build. This says
-- what was actually found, and the two must never be read off each other: a tenant asking
-- for execution does not have it, and a tenant that never asked may still have a worker
-- attached. Collapsing them is how "configured" came to mean "working".
--
-- status is deliberately five values rather than a boolean. not_configured and failed are
-- the pair that matters: a deployment that chose not to configure something and a
-- deployment whose configured thing is broken look identical to a boolean, and the second
-- must not be repaired by pretending it is the first. disabled is an operator's decision,
-- distinct from both.
CREATE TABLE IF NOT EXISTS tenant_capabilities (
    tenant_id BIGINT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('execution', 'credential_storage')),
    status TEXT NOT NULL
        CHECK (status IN ('not_configured', 'pending', 'ready', 'failed', 'disabled')),
    -- What configuration the observation was made against. An observation is not a
    -- permanent permit: admission compares this with the configuration in force and
    -- rechecks rather than trusting a record taken against something else.
    configuration_revision TEXT NOT NULL DEFAULT '',
    -- Which verifier reached this conclusion, and how it was spelled. An old verifier's
    -- ready is not a new verifier's ready, and a record with no provenance cannot be
    -- retired when the rule behind it changes.
    verifier_version TEXT NOT NULL DEFAULT '',
    -- Sanitized. A reason is read by an operator and never carries secret material.
    reason TEXT NOT NULL DEFAULT '' CHECK (length(reason) <= 2000),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, kind),
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
);
