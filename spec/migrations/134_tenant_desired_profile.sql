-- Desired profile is persisted deployment intent, held apart from observed readiness.
--
-- Activation required all five provisioning steps, so a deployment with no KMS and no
-- cluster could not give anyone an account: human identity waited on execution. The
-- profile records which prerequisites this tenant's control plane is meant to have, and
-- one transaction reads it.
--
-- Existing rows default to execution-enabled because that is the rule every already
-- activated tenant was activated under. Inferring the weaker profile from an old
-- not_applicable receipt is exactly the reinterpretation spec/20 forbids.
ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS desired_profile TEXT NOT NULL DEFAULT 'execution-enabled';
ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_desired_profile_check;
ALTER TABLE tenants ADD CONSTRAINT tenants_desired_profile_check
    CHECK (desired_profile IN ('control-plane', 'execution-enabled'));

-- The receipt binds the profile it was committed under. A retry that changes the profile
-- is a different request: it must reconcile explicitly rather than quietly widen or
-- narrow what the tenant was activated for.
ALTER TABLE ory_realm_deployments
    ADD COLUMN IF NOT EXISTS desired_profile TEXT NOT NULL DEFAULT 'execution-enabled';
ALTER TABLE ory_realm_deployments DROP CONSTRAINT IF EXISTS ory_realm_deployments_desired_profile_check;
ALTER TABLE ory_realm_deployments ADD CONSTRAINT ory_realm_deployments_desired_profile_check
    CHECK (desired_profile IN ('control-plane', 'execution-enabled'));

-- A versioned fingerprint over the normalised request, so an identical retry is
-- recognised by the configuration it names. The audit reason was carrying a
-- machine-readable declaration suffix appended by the service; a human sentence is not a
-- protocol, and this column is what replaces it.
ALTER TABLE ory_realm_deployments
    ADD COLUMN IF NOT EXISTS intent_fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE ory_realm_deployments DROP CONSTRAINT IF EXISTS ory_realm_deployments_intent_fingerprint_check;
ALTER TABLE ory_realm_deployments ADD CONSTRAINT ory_realm_deployments_intent_fingerprint_check
    CHECK (length(intent_fingerprint) <= 200);
