-- Pending-tenant identity preparation is a different deployment operation from
-- attaching a realm to an already-active tenant. Retries preserve that intent.
ALTER TABLE ory_realm_deployments
    ADD COLUMN IF NOT EXISTS pending_setup BOOLEAN NOT NULL DEFAULT FALSE;
