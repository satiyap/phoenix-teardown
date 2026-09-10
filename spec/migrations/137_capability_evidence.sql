-- What makes an observation admissible, and for how long.
--
-- Migration 135 recorded what a verifier found. This adds the two things that stop a past
-- finding admitting work forever: when it stops counting, and what it was actually taken
-- against.
--
-- A ready observation with no expiry is a permanent permit. The dependency it checked can
-- be turned off, the worker can go away, the placement can lose its egress policy, and the
-- record still says ready because nothing ever revisits it. Admission needs an unexpired
-- observation, so a capability that stops being verified stops admitting work by itself
-- rather than by somebody remembering to withdraw it.
ALTER TABLE tenant_capabilities
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

-- What the verifier actually looked at: a challenge id, a diagnostic run, a resolver
-- round-trip. Sanitized and never the evidence itself — a credential probe's material must
-- not survive in a column an operator screen reads.
ALTER TABLE tenant_capabilities
    ADD COLUMN IF NOT EXISTS evidence_ref TEXT NOT NULL DEFAULT '';
ALTER TABLE tenant_capabilities DROP CONSTRAINT IF EXISTS tenant_capabilities_evidence_ref_check;
ALTER TABLE tenant_capabilities ADD CONSTRAINT tenant_capabilities_evidence_ref_check
    CHECK (length(evidence_ref) <= 200);

-- Ready is the only status that claims something works, so it is the only one required to
-- say who established it, against what configuration, on what evidence, and until when.
-- The weaker statuses need none of that: "there is nothing here" is not a claim.
--
-- Enforced in the database rather than only in Go because this is the row an admission
-- decision is read from. A ready written by a future code path that forgot one of these
-- would be indistinguishable from a verified one.
ALTER TABLE tenant_capabilities DROP CONSTRAINT IF EXISTS tenant_capabilities_ready_evidence_check;
ALTER TABLE tenant_capabilities ADD CONSTRAINT tenant_capabilities_ready_evidence_check
    CHECK (status <> 'ready' OR (
        expires_at IS NOT NULL
        AND length(btrim(evidence_ref)) > 0
        AND length(btrim(verifier_version)) > 0
        AND length(btrim(configuration_revision)) > 0));
