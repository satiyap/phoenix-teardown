-- Ports do not isolate host-only Ory cookies. Refuse a topology that gives two
-- realms the same browser cookie host, including an operator/customer pair.
CREATE UNIQUE INDEX IF NOT EXISTS ory_realms_cookie_host_key
    ON ory_realms ((lower(substring(public_origin FROM '^https?://(\[[^]]+\]|[^/:]+)'))));

-- Deployment metadata is not an identity link or an invitation. The receipt is
-- retained so a failed configuration publication can be retried without changing
-- the trusted upstream, resurrecting a realm, or silently adopting legacy rows.
CREATE TABLE IF NOT EXISTS ory_realm_deployments (
    realm_id TEXT PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    realm_kind TEXT NOT NULL DEFAULT 'tenant' CHECK (realm_kind = 'tenant'),
    tenant_slug TEXT NOT NULL,
    public_origin TEXT NOT NULL,
    kratos_public_url TEXT NOT NULL UNIQUE,
    allow_http_upstream BOOLEAN NOT NULL,
    deployment_actor TEXT NOT NULL CHECK (length(btrim(deployment_actor)) BETWEEN 1 AND 200),
    request_id TEXT NOT NULL UNIQUE CHECK (length(btrim(request_id)) BETWEEN 1 AND 200),
    reason TEXT NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 2000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (realm_id, tenant_id, realm_kind)
        REFERENCES ory_realms (realm_id, tenant_id, kind)
);
