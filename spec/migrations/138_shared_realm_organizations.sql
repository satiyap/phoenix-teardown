-- One identity realm may serve several organizations, by explicit association.
--
-- Migration 125 made a realm belong to one tenant and an identity hold one membership. That
-- is right for a dedicated realm and it is what a shared realm has to stop assuming (#185).
--
-- FOUR THINGS, KEPT SEPARATE, because collapsing any pair of them is how authority leaks:
--
--   account       one row per identity per realm. Everything that records WHICH IDENTITY
--                 ACTED points here -- the enrollment and bootstrap event logs, and the
--                 installation-wide bootstrap fuse. Widening this key would turn an
--                 attributable actor into "some membership of this identity".
--   association   which organizations a realm may serve. An explicit, attributable row
--                 rather than an implication of ownership, so an unauthorized pairing fails
--                 on a foreign key rather than on a check somebody remembered to write.
--   membership    an account's binding to one stable principal and role WITHIN one
--                 organization. Everything that records which identity was bound to which
--                 principal points here, because that is what it always meant. An account
--                 holds AT MOST ONE, which is why there is no organization selector: the
--                 organization is derived, not chosen.
--   grant         operator authority. Explicit, revocable, and independent of organization
--                 administration: administering an organization never confers it.
--
-- A dedicated realm keeps exactly one association -- its owner -- so its behaviour and its
-- recorded state are unchanged, and realm ownership is retained.
--
-- Forward-only. Not backward compatible: per the 2026-09-11 amendment on #185, database
-- reset is an accepted recovery option for this transition, so the membership columns leave
-- the account record rather than lingering as a second statement of the same fact.

-- ── Association ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ory_realm_organizations (
    realm_id TEXT NOT NULL REFERENCES ory_realms (realm_id),
    tenant_id BIGINT NOT NULL REFERENCES tenants (tenant_id),
    -- Adding an organization to a realm is a deployment decision, answerable the same way
    -- provisioning is.
    associated_by TEXT NOT NULL CHECK (length(trim(associated_by)) > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (realm_id, tenant_id)
);

-- Declared, not inferred from how many rows happen to exist: a dedicated realm that
-- acquired a second organization by accident is exactly what this refuses. Every realm that
-- exists today stays dedicated until somebody says otherwise.
ALTER TABLE ory_realms
    ADD COLUMN IF NOT EXISTS association_mode TEXT NOT NULL DEFAULT 'dedicated'
        CHECK (association_mode IN ('dedicated', 'shared'));

INSERT INTO ory_realm_organizations (realm_id, tenant_id, associated_by, reason)
SELECT r.realm_id, r.tenant_id, 'migration/138',
       'backfilled: the realm''s owning tenant, which it already served'
  FROM ory_realms r
    ON CONFLICT DO NOTHING;

-- ── Membership ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ory_identity_memberships (
    realm_id TEXT NOT NULL,
    identity_id TEXT NOT NULL,
    tenant_id BIGINT NOT NULL,
    principal_id TEXT NOT NULL,
    principal_kind principal_kind NOT NULL DEFAULT 'human' CHECK (principal_kind = 'human'),
    tenant_role TEXT NOT NULL CHECK (tenant_role IN ('member', 'admin')),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (realm_id, identity_id, tenant_id),
    -- AT MOST ONE ORGANIZATION PER ACCOUNT, for this release.
    --
    -- The table is keyed to allow several so that relaxing this later is a constraint
    -- change rather than a reshaping, but the rule in force is one and nothing is promised
    -- about lifting it. #184 adds independent organization authentication; it does not
    -- currently lift this limit.
    --
    -- One membership is what removes the need for an organization selector: an
    -- authenticated account's organization is derived from its sole membership rather than
    -- chosen, so there is no selection to validate and no ambiguous context to fail safely
    -- on.
    --
    -- Deliberately not partial on `enabled`. A disabled membership still occupies the
    -- account's one slot: re-enabling it must be what restores access, rather than a second
    -- organization quietly taking the place of one somebody withdrew.
    UNIQUE (realm_id, identity_id),
    -- One identity binds to one principal within an organization. This is what holds run
    -- ownership, audit provenance and history onto a stable principal.
    UNIQUE (tenant_id, principal_id),
    UNIQUE (realm_id, identity_id, tenant_id, principal_id),

    FOREIGN KEY (realm_id, identity_id) REFERENCES ory_identity_links (realm_id, identity_id),
    -- The organization must be one this realm is allowed to serve.
    FOREIGN KEY (realm_id, tenant_id) REFERENCES ory_realm_organizations (realm_id, tenant_id),
    FOREIGN KEY (tenant_id, principal_id, principal_kind)
        REFERENCES principals (tenant_id, principal_id, kind)
);

-- Guarded, because the columns it reads are dropped further down. A second run of this
-- migration finds them gone, and an unguarded backfill would fail with
-- `column l.tenant_id does not exist` -- which reads like a broken migration rather than one
-- that has already done its work. Idempotence has to survive its own effects.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ory_identity_links' AND column_name = 'tenant_id') THEN
        INSERT INTO ory_identity_memberships
            (realm_id, identity_id, tenant_id, principal_id, principal_kind, tenant_role, enabled, created_at)
        SELECT l.realm_id, l.identity_id, l.tenant_id, l.principal_id, l.principal_kind,
               l.tenant_role, l.enabled, l.created_at
          FROM ory_identity_links l
            ON CONFLICT DO NOTHING;
    END IF;
END $$;

-- ── Dependent references, repointed by what each one MEANS ─────────────────────
--
-- Every foreign key that named the account-and-principal together meant a membership. The
-- ones that name only the account meant the actor, and are left alone. Constraint names are
-- discovered rather than assumed: Postgres generated them and the generated names differ
-- between installations that reached this schema by different routes.
DO $$
DECLARE
    c RECORD;
BEGIN
    FOR c IN
        SELECT con.conname, con.conrelid::regclass::text AS table_name,
               pg_get_constraintdef(con.oid) AS def
          FROM pg_constraint con
          JOIN pg_class ref ON ref.oid = con.confrelid
         WHERE con.contype = 'f' AND ref.relname = 'ory_identity_links'
    LOOP
        -- Four columns names a membership; two names the account and stays.
        IF c.def LIKE '%tenant_id%principal_id%' THEN
            EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', c.table_name, c.conname);
            EXECUTE format(
                'ALTER TABLE %s ADD CONSTRAINT %I %s',
                c.table_name, c.conname,
                replace(c.def, 'ory_identity_links', 'ory_identity_memberships'));
        END IF;
    END LOOP;
END $$;

-- ── The account record sheds what was never its own ────────────────────────────
ALTER TABLE ory_identity_links DROP COLUMN IF EXISTS tenant_role;
ALTER TABLE ory_identity_links DROP COLUMN IF EXISTS principal_id;
ALTER TABLE ory_identity_links DROP COLUMN IF EXISTS principal_kind;
ALTER TABLE ory_identity_links DROP COLUMN IF EXISTS tenant_id;

-- ── Operator authority, independent of organization administration ─────────────
--
-- The grant's authoritative subject is the ACCOUNT: (realm_id, identity_id). It was
-- qualified by the realm's kind, which a shared realm does not have a separate one of, and
-- by a membership, which made operator access depend on continuing to be a member of an
-- organization.
--
-- tenant_id and principal_id stay as IMMUTABLE HISTORICAL ATTRIBUTION -- which organization
-- and principal the grant was recorded through -- validated when the row is written and not
-- a prerequisite for continuing to hold it. They are deliberately not foreign keys any
-- more: a reference would make withdrawing a membership a constraint problem, and what it
-- should be is no problem at all.
--
-- THE SCHEMA IS NOT WHAT MAKES THIS INDEPENDENT. A foreign key constrains deletion and key
-- changes; it says nothing about a membership row being set enabled = false. Independence
-- is established in the authorization query, which must stop requiring an active membership
-- to resolve operator authority. Dropping the constraint alone would leave the old
-- behaviour running and the schema implying otherwise.
--
-- What still denies operator access: a disabled account or realm, an invalidated session, a
-- revoked grant, and the existing verification and AAL2 checks. What does not: losing an
-- organization membership or an admin role in one. And customer membership never creates or
-- implies a grant -- only the bootstrap and grant commands write this table, with audit.
ALTER TABLE platform_operator_grants DROP CONSTRAINT IF EXISTS platform_operator_grants_realm_id_tenant_id_realm_kind_fkey;
ALTER TABLE platform_operator_grants DROP COLUMN IF EXISTS realm_kind;
DO $$
DECLARE
    c RECORD;
BEGIN
    -- Any reference from the grant to an identity link or a membership, whatever the
    -- generated name and whichever route this installation reached the schema by.
    FOR c IN
        SELECT con.conname FROM pg_constraint con
          JOIN pg_class ref ON ref.oid = con.confrelid
         WHERE con.contype = 'f' AND con.conrelid = 'platform_operator_grants'::regclass
           AND ref.relname IN ('ory_identity_links', 'ory_identity_memberships')
    LOOP
        EXECUTE format('ALTER TABLE platform_operator_grants DROP CONSTRAINT %I', c.conname);
    END LOOP;

    -- Exactly one reference, to the account. A grant for an account that does not exist is
    -- refused; a grant whose holder left an organization is not.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'platform_operator_grants_account_fkey') THEN
        ALTER TABLE platform_operator_grants
            ADD CONSTRAINT platform_operator_grants_account_fkey
            FOREIGN KEY (realm_id, identity_id) REFERENCES ory_identity_links (realm_id, identity_id);
    END IF;
END $$;

-- ── Offers tie to an association, not to a realm's kind ───────────────────────
--
-- An invitation and a bootstrap offer each named (realm, tenant, realm_kind), which said two
-- things at once: that the realm serves this organization, and that it is of a particular
-- kind. The first is now the association's job and the second no longer exists for a shared
-- realm. Operator authority does not come from a realm being "the operator realm" -- it
-- comes from the grant, and only from the grant.
DO $$
DECLARE
    t TEXT;
    c RECORD;
BEGIN
    FOREACH t IN ARRAY ARRAY['ory_enrollments', 'ory_operator_bootstraps'] LOOP
        FOR c IN
            SELECT con.conname FROM pg_constraint con
              JOIN pg_class ref ON ref.oid = con.confrelid
             WHERE con.contype = 'f' AND con.conrelid = t::regclass
               AND ref.relname = 'ory_realms'
        LOOP
            EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', t, c.conname);
        END LOOP;
        EXECUTE format('ALTER TABLE %I DROP COLUMN IF EXISTS realm_kind', t);
        -- Guarded: on a second run the realm constraint is already gone, so an unguarded
        -- ADD would fail on the association constraint it created the first time.
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_association_fkey') THEN
            EXECUTE format(
                'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (realm_id, tenant_id) '
                'REFERENCES ory_realm_organizations (realm_id, tenant_id)',
                t, t || '_association_fkey');
        END IF;
    END LOOP;
END $$;

-- ── Dedicated realms stay dedicated, in both directions ────────────────────────
--
-- Two ways to break it and both are refused: associating a second organization with a
-- dedicated realm, and declaring a realm dedicated while it already serves several. The
-- second is the one an application-level check tends to miss.
CREATE OR REPLACE FUNCTION ory_realm_association_allowed() RETURNS TRIGGER AS $$
DECLARE
    mode TEXT;
    others INT;
BEGIN
    SELECT association_mode INTO mode FROM ory_realms WHERE realm_id = NEW.realm_id FOR UPDATE;
    IF mode = 'dedicated' THEN
        SELECT count(*) INTO others FROM ory_realm_organizations
         WHERE realm_id = NEW.realm_id AND tenant_id <> NEW.tenant_id;
        IF others > 0 THEN
            RAISE EXCEPTION 'realm % is dedicated and already serves another organization', NEW.realm_id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ory_realm_association_allowed ON ory_realm_organizations;
CREATE TRIGGER ory_realm_association_allowed
    BEFORE INSERT OR UPDATE ON ory_realm_organizations
    FOR EACH ROW EXECUTE FUNCTION ory_realm_association_allowed();

CREATE OR REPLACE FUNCTION ory_realm_mode_allowed() RETURNS TRIGGER AS $$
DECLARE
    serving INT;
BEGIN
    IF NEW.association_mode = 'dedicated' THEN
        SELECT count(*) INTO serving FROM ory_realm_organizations
         WHERE realm_id = NEW.realm_id AND tenant_id <> NEW.tenant_id;
        IF serving > 0 THEN
            RAISE EXCEPTION
                'realm % serves organizations other than its owner and cannot be declared dedicated', NEW.realm_id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ory_realm_mode_allowed ON ory_realms;
CREATE TRIGGER ory_realm_mode_allowed
    BEFORE UPDATE OF association_mode ON ory_realms
    FOR EACH ROW EXECUTE FUNCTION ory_realm_mode_allowed();
