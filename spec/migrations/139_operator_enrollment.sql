-- Additional operators are INVITED, through the same offer an ordinary member gets.
--
-- The first operator arrives by `ory_operator_bootstraps`, which is a deployment operation
-- behind an installation-wide fuse: it exists because at that moment there is nobody to ask.
-- After it, there is. An additional operator is authorized by an operator who already holds
-- a grant, and that is an ENROLLMENT question, not a deployment one.
--
-- So this adds a purpose to the existing offer rather than a second offer table. Everything
-- an invitation already has is the whole reason: one digest, one expiry, replay and
-- withdrawal, the open-offer uniqueness per principal and per email, ownership of the
-- invited address, the AAL2 rule on an admin offer, and the enrollment event log. A parallel
-- table would restate every one of those, and the copy that drifts is the one nobody reads.
--
-- What acceptance does differently is a single extra write: an explicit, audited operator
-- grant. It is not implied by the membership and nothing else creates one.

-- ── The purpose ────────────────────────────────────────────────────────────────
-- Constraint names are discovered rather than assumed: Postgres generated them and the
-- generated names differ between installations that reached this schema by different routes.
DO $$
DECLARE
    c RECORD;
BEGIN
    FOR c IN
        SELECT con.conname, pg_get_constraintdef(con.oid) AS def
          FROM pg_constraint con
         WHERE con.contype = 'c' AND con.conrelid = 'ory_enrollments'::regclass
           AND pg_get_constraintdef(con.oid) LIKE '%purpose%'
    LOOP
        EXECUTE format('ALTER TABLE ory_enrollments DROP CONSTRAINT %I', c.conname);
    END LOOP;
END $$;

ALTER TABLE ory_enrollments
    ADD CONSTRAINT ory_enrollments_purpose
        CHECK (purpose IN ('tenant_invite', 'first_admin', 'operator'));

-- An operator offer is an administrator offer, for the same reason a first-administrator
-- offer is: the acceptance path requires a second factor on an admin role, and an operator
-- offer that could be issued as 'member' would accept at aal1.
ALTER TABLE ory_enrollments
    ADD CONSTRAINT ory_enrollments_admin_purpose
        CHECK (purpose = 'tenant_invite' OR tenant_role = 'admin');

-- Deliberately NO partial unique index on operator offers, unlike first_admin.
--
-- `ory_enrollment_first_admin` exists because an organization has exactly one first
-- administrator and two open offers for it are a race. An installation has no such limit on
-- operators: inviting three at once is ordinary. The open-offer uniqueness per principal and
-- per email still applies, which is what stops the same person holding two.

-- ── The grant is recorded in the enrollment log, not inferred from the purpose ─
-- The grant row carries its own reason and timestamp, but reading the offer log should not
-- require joining another table to find out whether platform authority was handed over. One
-- event per terminal transition is this table's rule and this is one: it happens once, in
-- the acceptance transaction, and only for an operator offer.
DO $$
DECLARE
    c RECORD;
BEGIN
    FOR c IN
        SELECT con.conname FROM pg_constraint con
         WHERE con.contype = 'c' AND con.conrelid = 'ory_enrollment_events'::regclass
           AND pg_get_constraintdef(con.oid) LIKE '%event%'
    LOOP
        EXECUTE format('ALTER TABLE ory_enrollment_events DROP CONSTRAINT %I', c.conname);
    END LOOP;
END $$;

ALTER TABLE ory_enrollment_events
    ADD CONSTRAINT ory_enrollment_events_event
        CHECK (event IN ('issued', 'redeemed', 'revoked', 'replaced', 'operator_granted'));

-- ── The grant an operator enrollment writes ────────────────────────────────────
-- platform_operator_grants was qualified by a realm's KIND, which #185 removed: a shared
-- realm has no operator kind, and the grant's authoritative subject is the account. This
-- migration only restates that the column is gone, so an installation that reached 138 by a
-- route that left it behind converges here rather than failing on the first grant written
-- outside the bootstrap.
ALTER TABLE platform_operator_grants DROP COLUMN IF EXISTS realm_kind;
