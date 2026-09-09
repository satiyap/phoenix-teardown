-- Ory owns credentials and sessions. Phoenix binds an immutable realm-scoped
-- identity to one tenant principal; email never serves as that binding key.
CREATE TABLE IF NOT EXISTS ory_realms (
    realm_id TEXT PRIMARY KEY,
    tenant_id BIGINT NOT NULL UNIQUE REFERENCES tenants (tenant_id),
    kind TEXT NOT NULL CHECK (kind IN ('tenant', 'operator')),
    public_origin TEXT NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (realm_id, tenant_id),
    UNIQUE (realm_id, tenant_id, kind)
);

CREATE TABLE IF NOT EXISTS ory_identity_links (
    realm_id TEXT NOT NULL,
    identity_id TEXT NOT NULL,
    tenant_id BIGINT NOT NULL,
    principal_id TEXT NOT NULL,
    principal_kind principal_kind NOT NULL DEFAULT 'human' CHECK (principal_kind = 'human'),
    tenant_role TEXT NOT NULL CHECK (tenant_role IN ('member', 'admin')),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (realm_id, identity_id),
    UNIQUE (tenant_id, principal_id),
    UNIQUE (realm_id, identity_id, tenant_id, principal_id),
    FOREIGN KEY (realm_id, tenant_id) REFERENCES ory_realms (realm_id, tenant_id),
    FOREIGN KEY (tenant_id, principal_id, principal_kind)
        REFERENCES principals (tenant_id, principal_id, kind)
);

-- Even a mistaken direct write cannot grant platform authority to an identity
-- in a customer realm. Operator access requires a separate, revocable grant.
CREATE TABLE IF NOT EXISTS platform_operator_grants (
    realm_id TEXT NOT NULL,
    identity_id TEXT NOT NULL,
    tenant_id BIGINT NOT NULL,
    principal_id TEXT NOT NULL,
    realm_kind TEXT NOT NULL DEFAULT 'operator' CHECK (realm_kind = 'operator'),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    PRIMARY KEY (realm_id, identity_id),
    FOREIGN KEY (realm_id, tenant_id, realm_kind)
        REFERENCES ory_realms (realm_id, tenant_id, kind),
    FOREIGN KEY (realm_id, identity_id, tenant_id, principal_id)
        REFERENCES ory_identity_links (realm_id, identity_id, tenant_id, principal_id)
);
