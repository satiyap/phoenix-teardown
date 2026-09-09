-- Deployment-authorized first-operator offers are deliberately not ordinary
-- tenant invitations. No tenant invitation or existing customer admin can create
-- an operator grant by choosing a different purpose or realm in a request.
CREATE TABLE IF NOT EXISTS ory_operator_bootstraps (
    bootstrap_id TEXT PRIMARY KEY,
    realm_id TEXT NOT NULL,
    tenant_id BIGINT NOT NULL,
    realm_kind TEXT NOT NULL DEFAULT 'operator' CHECK (realm_kind = 'operator'),
    principal_id TEXT NOT NULL,
    principal_kind principal_kind NOT NULL DEFAULT 'human' CHECK (principal_kind = 'human'),
    email TEXT NOT NULL CHECK (email = lower(btrim(email)) AND length(email) BETWEEN 3 AND 254),
    token_digest TEXT NOT NULL UNIQUE CHECK (token_digest ~ '^[0-9a-f]{64}$'),
    deployment_actor TEXT NOT NULL CHECK (length(btrim(deployment_actor)) BETWEEN 1 AND 200),
    reason TEXT NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 2000),
    request_id TEXT NOT NULL CHECK (length(btrim(request_id)) BETWEEN 1 AND 200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    redeemed_at TIMESTAMPTZ,
    redeemed_identity_id TEXT,
    revoked_at TIMESTAMPTZ,
    FOREIGN KEY (realm_id, tenant_id, realm_kind)
        REFERENCES ory_realms (realm_id, tenant_id, kind),
    FOREIGN KEY (tenant_id, principal_id, principal_kind)
        REFERENCES principals (tenant_id, principal_id, kind),
    FOREIGN KEY (realm_id, redeemed_identity_id, tenant_id, principal_id)
        REFERENCES ory_identity_links (realm_id, identity_id, tenant_id, principal_id),
    CHECK (expires_at > created_at),
    CHECK ((redeemed_at IS NULL) = (redeemed_identity_id IS NULL)),
    CHECK (redeemed_at IS NULL OR revoked_at IS NULL)
);

-- A single installation gets one initial operator, not one bypass per realm.
-- The redeemed row is a durable fuse, retained even after access is revoked.
CREATE UNIQUE INDEX IF NOT EXISTS ory_operator_bootstrap_pending
    ON ory_operator_bootstraps ((TRUE))
    WHERE redeemed_at IS NULL AND revoked_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ory_operator_bootstrap_consumed
    ON ory_operator_bootstraps ((TRUE)) WHERE redeemed_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS ory_operator_bootstrap_events (
    bootstrap_id TEXT NOT NULL REFERENCES ory_operator_bootstraps (bootstrap_id),
    event TEXT NOT NULL CHECK (event IN ('issued', 'replaced', 'revoked', 'redeemed')),
    deployment_actor TEXT CHECK (length(btrim(deployment_actor)) BETWEEN 1 AND 200),
    actor_realm_id TEXT,
    actor_identity_id TEXT,
    reason TEXT NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 2000),
    request_id TEXT NOT NULL CHECK (length(btrim(request_id)) BETWEEN 1 AND 200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (bootstrap_id, event),
    FOREIGN KEY (actor_realm_id, actor_identity_id)
        REFERENCES ory_identity_links (realm_id, identity_id),
    CHECK ((actor_realm_id IS NULL) = (actor_identity_id IS NULL)),
    CHECK ((deployment_actor IS NOT NULL) <> (actor_identity_id IS NOT NULL)),
    CHECK ((event = 'redeemed') = (actor_identity_id IS NOT NULL))
);
