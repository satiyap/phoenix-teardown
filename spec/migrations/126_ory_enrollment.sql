-- Ory enrollment must never be redeemable through the old invitation-to-session
-- path. Keep the offers separate; legacy invitations require explicit reissue.
CREATE TABLE IF NOT EXISTS ory_enrollments (
    tenant_id BIGINT NOT NULL,
    invitation_id TEXT NOT NULL,
    realm_id TEXT NOT NULL,
    realm_kind TEXT NOT NULL DEFAULT 'tenant' CHECK (realm_kind = 'tenant'),
    principal_id TEXT NOT NULL,
    principal_kind principal_kind NOT NULL DEFAULT 'human' CHECK (principal_kind = 'human'),
    email TEXT NOT NULL CHECK (email = lower(btrim(email)) AND length(email) BETWEEN 3 AND 254),
    tenant_role TEXT NOT NULL CHECK (tenant_role IN ('member', 'admin')),
    purpose TEXT NOT NULL CHECK (purpose IN ('tenant_invite', 'first_admin')),
    token_digest TEXT NOT NULL UNIQUE CHECK (token_digest ~ '^[0-9a-f]{64}$'),
    inviter_realm_id TEXT NOT NULL,
    inviter_identity_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    redeemed_at TIMESTAMPTZ,
    redeemed_identity_id TEXT,
    revoked_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, invitation_id),
    FOREIGN KEY (realm_id, tenant_id, realm_kind)
        REFERENCES ory_realms (realm_id, tenant_id, kind),
    FOREIGN KEY (tenant_id, principal_id, principal_kind)
        REFERENCES principals (tenant_id, principal_id, kind),
    FOREIGN KEY (inviter_realm_id, inviter_identity_id)
        REFERENCES ory_identity_links (realm_id, identity_id),
    FOREIGN KEY (realm_id, redeemed_identity_id, tenant_id, principal_id)
        REFERENCES ory_identity_links (realm_id, identity_id, tenant_id, principal_id),
    CHECK (expires_at > created_at),
    CHECK ((redeemed_at IS NULL) = (redeemed_identity_id IS NULL)),
    CHECK (redeemed_at IS NULL OR revoked_at IS NULL),
    CHECK (purpose <> 'first_admin' OR tenant_role = 'admin')
);

-- Issuance revokes the previous open offer before inserting its replacement.
-- Expiry is not an index predicate: wall-clock predicates cannot be immutable.
CREATE UNIQUE INDEX IF NOT EXISTS ory_enrollment_open_principal
    ON ory_enrollments (tenant_id, principal_id)
    WHERE redeemed_at IS NULL AND revoked_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ory_enrollment_open_email
    ON ory_enrollments (tenant_id, email)
    WHERE redeemed_at IS NULL AND revoked_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ory_enrollment_first_admin
    ON ory_enrollments (tenant_id)
    WHERE purpose = 'first_admin' AND redeemed_at IS NULL AND revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS ory_enrollment_teams (
    tenant_id BIGINT NOT NULL,
    invitation_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
    PRIMARY KEY (tenant_id, invitation_id, team_id),
    FOREIGN KEY (tenant_id, invitation_id)
        REFERENCES ory_enrollments (tenant_id, invitation_id),
    FOREIGN KEY (tenant_id, team_id) REFERENCES teams (tenant_id, team_id)
);

-- One event for each terminal transition. A retry returns a receipt rather than
-- repeating a grant or manufacturing another historical acceptance.
CREATE TABLE IF NOT EXISTS ory_enrollment_events (
    tenant_id BIGINT NOT NULL,
    invitation_id TEXT NOT NULL,
    event TEXT NOT NULL CHECK (event IN ('issued', 'redeemed', 'revoked', 'replaced')),
    actor_realm_id TEXT NOT NULL,
    actor_identity_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 2000),
    request_id TEXT NOT NULL CHECK (length(btrim(request_id)) BETWEEN 1 AND 200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, invitation_id, event),
    FOREIGN KEY (tenant_id, invitation_id)
        REFERENCES ory_enrollments (tenant_id, invitation_id),
    FOREIGN KEY (actor_realm_id, actor_identity_id)
        REFERENCES ory_identity_links (realm_id, identity_id)
);
