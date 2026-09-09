-- Principal withdrawal and Ory cleanup intent commit together. Completed jobs
-- remain as receipts; a failed or abandoned attempt never permits restoration.
CREATE TABLE IF NOT EXISTS ory_session_revocations (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    realm_id TEXT NOT NULL,
    identity_id TEXT NOT NULL,
    tenant_id BIGINT NOT NULL,
    principal_id TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    completed_at TIMESTAMPTZ,
    FOREIGN KEY (realm_id, identity_id, tenant_id, principal_id)
        REFERENCES ory_identity_links (realm_id, identity_id, tenant_id, principal_id),
    CHECK (last_error IS NULL OR last_error = 'ory_cleanup_unconfirmed')
);
CREATE UNIQUE INDEX IF NOT EXISTS ory_session_revocations_pending_identity
    ON ory_session_revocations (realm_id, identity_id) WHERE completed_at IS NULL;
CREATE INDEX IF NOT EXISTS ory_session_revocations_pending_realm
    ON ory_session_revocations (realm_id, requested_at) WHERE completed_at IS NULL;

-- Existing withdrawals also need cleanup. Empty requested_by means this forward
-- migration reconciled an older withdrawal, not that a new human performed it.
INSERT INTO ory_session_revocations (realm_id, identity_id, tenant_id, principal_id, requested_by)
SELECT l.realm_id, l.identity_id, l.tenant_id, l.principal_id, ''
  FROM ory_identity_links l JOIN principals p
    ON p.tenant_id = l.tenant_id AND p.principal_id = l.principal_id
 WHERE p.revoked_at IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM ory_session_revocations j
        WHERE j.realm_id = l.realm_id AND j.identity_id = l.identity_id)
ON CONFLICT DO NOTHING;
