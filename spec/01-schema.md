# 01 — Schema
<!-- status: final -->

PostgreSQL 16+. Every table is tenant-scoped in its **primary key**, and every
cross-table reference is a **composite foreign key including `tenant_id`** — so a
cross-tenant relationship is a constraint violation, not a silent success.

Convention: `tenant_id BIGINT` (not UUID) because it appears in every index and
narrower keys matter. `id` columns are `TEXT` holding a sortable ULID.

**Five exceptions to the composite-FK rule, stated rather than hidden:**

1. `state_entries.scope_key` is unconstrained text, because its referent depends on
   `scope` (a principal id, a session id, or empty for app scope). A polymorphic FK is
   not expressible in SQL. Enforced by a trigger instead — see §Polymorphic scope.
2. `policies.scope = 'project'` is accepted by the enum but **has no referent in
   v0.1**, because `Project` is not a v0.1 resource. The API rejects it (`422`) until
   `projects` exists. Recorded here so the gap is visible rather than surprising.
3. `channel_envelopes.audience` holds principal ids inside a JSON array, which SQL cannot
   constrain. The hub checks membership and refuses `not_a_member`; the database does not.
   Added 2026-08-30 with the channel DDL — see [`17-messaging.md`](17-messaging.md) §The
   Envelope, as data.
4. `knowledge_compilations.sources` and `resolution` hold `knowledge_sources.source_id`
   inside a JSON array, which SQL cannot constrain. The compiler checks membership; the
   database does not — the same shape as 3. See
   [`16-knowledge.md`](16-knowledge.md) §Schema.
5. `knowledge_compilations.bundle_id` / `bundle_revision` carry no FK, because a
   compilation may name a bundle revision that is not registered here. The composite FK
   `(tenant_id, bundle_id, bundle_revision)` to `bundles`
   ([`10-work-bundles.md`](10-work-bundles.md) §Schema) is the closing condition, and is
   deliberately not applied in v0.1. (16)

---

## Identity

```sql
CREATE TABLE tenants (
    tenant_id      BIGINT PRIMARY KEY,
    slug           TEXT NOT NULL UNIQUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Principal: who is acting. Humans and agents are the SAME type with a
-- discriminator (AG2's PassportKind), so both are addressable and auditable.
-- Amended 2026-09-03: 'remote' DROPPED. Superseded:
--   ENUM ('human', 'agent', 'service', 'remote')
-- It was inherited from AG2's `remote_agent` (an agent on another hub) and had
-- no referent after 2026-08-27: no foreign agents, ACP unshipped, A2A interop
-- unshipped, the remote adapter transport retained-but-unshipped. Nothing in
-- specs 00-19 read it -- no rule, CHECK, test row, policy branch or refusal --
-- so it was a storable value with no defined behaviour, which §11's rule
-- ("a stored value with no defined behaviour is a promise nothing keeps")
-- forbids. Unlike `event` triggers and `overlap_policy='allow'`, which are
-- reserved AND refused 422, nothing refused it. ADR-0007's decision block named
-- the fourth kind `delegated`, not `remote`, so the ADR and this schema had
-- also disagreed since they were written; `delegated` is in any case redundant
-- with `on_behalf_of` + `delegation_depth` below.
-- If federation ever ships, re-adding a value to this ENUM is an additive
-- migration; the FK in `principals_id_kind` is unaffected.
CREATE TYPE principal_kind AS ENUM ('human', 'agent', 'service');

CREATE TABLE principals (
    tenant_id      BIGINT NOT NULL,
    principal_id   TEXT   NOT NULL,
    kind           principal_kind NOT NULL,
    display_name   TEXT   NOT NULL,
    -- how identity was established; NULL only for kind='agent' whose
    -- credentials are issued by us
    authenticated_by JSONB,
    -- delegation: who this principal acts for, and how deep the chain is.
    -- depth is incremented BY US, never by the caller (AG2).
    on_behalf_of   TEXT,
    delegation_depth SMALLINT NOT NULL DEFAULT 0
                     CHECK (delegation_depth BETWEEN 0 AND 8),
    revoked_at     TIMESTAMPTZ,          -- revocation is a STATE, not a DELETE
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, principal_id),
    FOREIGN KEY (tenant_id, on_behalf_of)
        REFERENCES principals (tenant_id, principal_id),

    -- lets approvals.decided_by pin the kind in its FK (see `approvals`)
    CONSTRAINT principals_id_kind UNIQUE (tenant_id, principal_id, kind)
);

CREATE INDEX principals_active
    ON principals (tenant_id, kind) WHERE revoked_at IS NULL;
```

`delegation_depth` is capped in a `CHECK`, so a runaway delegation chain is rejected
by the database rather than by policy code that might not run.

---

## Agent definition — content-addressed and immutable

```sql
-- The artifact. The digest IS the key, so a row can never disagree with its name.
-- Inserts are idempotent; there is no UPDATE path.
CREATE TABLE agent_definitions (
    tenant_id      BIGINT NOT NULL,
    digest         TEXT   NOT NULL,       -- sha256 hex, see 03-canonicalisation
    body           JSONB  NOT NULL,       -- canonical definition document; `tools`
                                          -- and `extensions` are arrays of full
                                          -- BINDINGS (03), each carrying an
                                          -- artifact_digest. A name alone does not
                                          -- pin an implementation.
    canon_profile  TEXT   NOT NULL,       -- e.g. 'nfc+intjson/v1' — pins the rules used
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, digest),
    CHECK (digest ~ '^[0-9a-f]{64}$')
);

-- A stable, human-facing name that POINTS AT a digest. Mutable on purpose:
-- this is how you "edit an agent" without mutating an artifact.
CREATE TABLE agents (
    tenant_id      BIGINT NOT NULL,
    agent_id       TEXT   NOT NULL,
    name           TEXT   NOT NULL,
    current_digest TEXT   NOT NULL,
    declared_version INTEGER NOT NULL DEFAULT 1,   -- human-facing, NEVER compared
    lifecycle      TEXT   NOT NULL DEFAULT 'active'
                   CHECK (lifecycle IN ('active','deprecated','revoked')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, agent_id),
    UNIQUE (tenant_id, name),
    FOREIGN KEY (tenant_id, current_digest)
        REFERENCES agent_definitions (tenant_id, digest)
);
```

`lifecycle` exists now even though revocation *enforcement* is deferred — adding the
column later is a migration, and the identity model is cheap to get right up front.

---

## Adapter contracts

```sql
CREATE TABLE adapter_contracts (
    tenant_id      BIGINT NOT NULL,
    identity       TEXT   NOT NULL,       -- 'sdk:pydantic-ai'
                                          -- (an acp: identity was superseded 2026-08-27;
                                          --  a per-vendor sdk: identity likewise, when the
                                          --  two-SDK plan was superseded in redo 4)
    digest         TEXT   NOT NULL,       -- DERIVED from the contract, not supplied
    protocol_version TEXT NOT NULL,
    -- The enum is Omnigent's full taxonomy and is kept so the column never needs a
    -- migration. Only 'sdk_subprocess' is SHIPPED (renamed from 'sdk_in_process' 2026-08-28 and from 'sdk_sidecar' 2026-08-29,
    -- OQ-056: the harness is a separate process, so the old name was false): we build and operate the agents on
    -- an internal harness on Pydantic AI (amended 2026-08-27), so there is no third-party
    -- subprocess or TUI to adapt. The others are reserved, not supported.
    -- 'sdk_subprocess' MEANS (decided 2026-08-28/29, OQ-056 + spike 05 T2): the Go driver is
    -- PID 1 of the run's container and spawns the Python harness as a child process; the
    -- two speak the 07 frames over an AF_UNIX socketpair the driver creates and passes to
    -- the child by fd inheritance, with run_token on Start as the protocol authentication
    -- (amended 2026-08-29; superseded: "a Unix socket in a 0700 dir the driver created" --
    -- Unix permissions check UID, not ancestry; ADR-0016:65-70, spec/13). It is
    -- NOT 'cli_subprocess' (a third-party CLI driven from outside; reserved, never shipped).
    -- 'sdk_in_process' and 'sdk_sidecar' stay in the enum as reserved; neither shipped.
    integration_mode TEXT NOT NULL
        CHECK (integration_mode IN ('sdk_subprocess','sdk_sidecar','sdk_in_process','cli_subprocess',
                                    'acp_subprocess','native_tui','native_server')),
    CONSTRAINT integration_mode_shipped
        CHECK (integration_mode = 'sdk_subprocess'),   -- drop this to ship another
    -- the adapter's OWN checkpoint payload format, which runs pin (07 6)
    payload_schema_digest TEXT NOT NULL,
    declared_capabilities JSONB NOT NULL DEFAULT '{}',
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, identity, digest)
);
```

`integration_mode` is Omnigent's taxonomy. Only `sdk_subprocess` is shipped (amended
2026-08-27; renamed from `sdk_in_process` 2026-08-28 and from `sdk_sidecar` 2026-08-29 after spike 05 T2); the rest are retained so the column never needs a migration. The original
argument for `native_tui` — adapting a third-party agent (superseded 2026-08-27)
that offers no API by driving its terminal.

**Amended 2026-08-30 (OQ-109):** the deploy pipeline writes one `adapter_contracts` row
**per tenant** at provisioning time, derived from the driver image manifest — not a single
platform-wide row every tenant reads. `(tenant_id, identity, digest)` is already the primary
key, so the row shape does not change; what was open was who writes it and how many rows
exist, and the answer is one insert per tenant, done by the deploy pipeline rather than the
control plane's first sight of an image.

---

## Run — the execution unit

```sql
CREATE TYPE run_state AS ENUM (
    'draft', 'queued', 'running', 'waiting_input', 'cancelling',
    'succeeded', 'failed', 'expired', 'cancelled',
    'indeterminate', 'incompatible', 'discarded'
);

CREATE TABLE runs (
    tenant_id      BIGINT NOT NULL,
    run_id         TEXT   NOT NULL,
    state          run_state NOT NULL DEFAULT 'draft',

    -- intent lives ON the run. `Task`/routines are Tier 2 as of 2026-08-27; `runs.task_id`
    -- is added as a nullable FK by spec/11 (additive migration), and intent is COPIED onto
    -- the run at firing rather than read through the task (11 §`runs.task_id`).
    agent_id       TEXT   NOT NULL,
    prompt         TEXT,
    created_by     TEXT   NOT NULL,        -- the acting principal

    -- THE PIN. Compared on every resume; a mismatch is terminal (INCOMPATIBLE).
    pinned_definition_digest TEXT NOT NULL,
    pinned_adapter_identity  TEXT NOT NULL,
    pinned_adapter_digest    TEXT NOT NULL,
    pinned_payload_schema    TEXT NOT NULL,   -- the ADAPTER's own format
    checkpoint_schema_version INTEGER NOT NULL,

    -- The bundle half of the pin, where the run pins one (10). Nullable as a set: a run
    -- pins a bundle or it does not, and a half-pin is not a state 05 step 4 can compare.
    -- The composite FK to `bundles` is an ALTER in 10, because `bundles` is created there.
    pinned_bundle_id       TEXT,
    pinned_bundle_revision TEXT,
    pinned_bundle_digest   TEXT,
    CHECK (num_nulls(pinned_bundle_id, pinned_bundle_revision, pinned_bundle_digest)
           IN (0, 3)),

    FOREIGN KEY (tenant_id, pinned_adapter_identity, pinned_adapter_digest)
        REFERENCES adapter_contracts (tenant_id, identity, digest),

    -- failure classification: queryable, so retry logic can branch (Omnigent)
    error_code     TEXT,
    error_detail   TEXT,

    rewind_before_step BIGINT,              -- logical history reduction (ADK)
    session_id     TEXT,                    -- nullable; binds session-scoped state (16)

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,
    ended_at       TIMESTAMPTZ,
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, run_id),
    FOREIGN KEY (tenant_id, agent_id) REFERENCES agents (tenant_id, agent_id),
    FOREIGN KEY (tenant_id, pinned_definition_digest)
        REFERENCES agent_definitions (tenant_id, digest),
    FOREIGN KEY (tenant_id, created_by)
        REFERENCES principals (tenant_id, principal_id),

    -- a terminal run must have an end time; a live one must not
    CHECK ((state IN ('succeeded','failed','expired','cancelled',
                      'indeterminate','incompatible','discarded'))
           = (ended_at IS NOT NULL)),
    -- failures must be classified
    CHECK (state <> 'failed' OR error_code IS NOT NULL)
);

-- "what needs a human right now" must stay cheap as history grows (HumanLayer)
CREATE INDEX runs_waiting ON runs (tenant_id, last_activity_at)
    WHERE state = 'waiting_input';
CREATE INDEX runs_live ON runs (tenant_id, state)
    WHERE state IN ('queued','running','cancelling');
```

The two `CHECK`s encode invariants people otherwise get wrong: a terminal state
without `ended_at`, and a `failed` run with no `error_code`.

Sandbox identity is **not** run identity (`ADR-0016`:73;
[`15-sandbox.md`](15-sandbox.md) §2). The table lives here because this document owns
schema and the FK target is already above it; the FK points one way only, and `runs`
gains no `sandbox_id` column — a column there would make run state depend on sandbox
identity, which is the dependency ADR-0016 forbids.

```sql
CREATE TYPE sandbox_state AS ENUM ('creating','live','suspended','lost','destroyed');

CREATE TABLE sandboxes (
    tenant_id       BIGINT NOT NULL,
    sandbox_id      TEXT   NOT NULL,   -- minted by the plane, opaque; never derived from
                                       -- a provider name or a pod name
    run_id          TEXT   NOT NULL,
    provider        TEXT   NOT NULL,   -- 'k8s-gvisor' in v0.1
    provider_handle TEXT,              -- the provider's own name for it. NOT an identity:
                                       -- never a lookup key in either direction
    state           sandbox_state NOT NULL DEFAULT 'creating',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,

    PRIMARY KEY (tenant_id, sandbox_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    CHECK ((state IN ('lost','destroyed')) = (ended_at IS NOT NULL))
);

-- One NON-TERMINAL sandbox per run. The predicate is `ended_at IS NULL`, not a state
-- list: `suspended` is non-terminal too, and `WHERE state IN ('creating','live')` would
-- let a run holding a suspended row acquire a second sandbox with no violation.
CREATE UNIQUE INDEX sandboxes_one_live ON sandboxes (tenant_id, run_id)
    WHERE ended_at IS NULL;
```

---

## The log — append-only, single-writer by primary key

```sql
CREATE TABLE run_events (
    tenant_id      BIGINT NOT NULL,
    run_id         TEXT   NOT NULL,
    seq            BIGINT NOT NULL,        -- assigned INSIDE the txn; see 02
    epoch          INTEGER NOT NULL,       -- rewind generation; see 04 and below
    event_type     TEXT   NOT NULL,        -- from the registry; see 04
    payload        JSONB  NOT NULL,
    traceparent    TEXT   NOT NULL,        -- full W3C header; context rides the event.
                                           -- NOT NULL since 2026-08-30 (19): a sweeper-
                                           -- originated event opens its own root span, so
                                           -- every append can carry one.
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- (tenant, run, seq) as PK is the single-writer guarantee: two concurrent
    -- appends collide and one rolls back. No lock service. (Google AX.)
    PRIMARY KEY (tenant_id, run_id, seq),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),

    CONSTRAINT run_events_epoch_nonneg CHECK (epoch >= 0)
);

-- Folding reads by (run, epoch, seq); make that the access path.
CREATE INDEX run_events_fold ON run_events (tenant_id, run_id, epoch, seq);
```

There is **no `UPDATE` or `DELETE` grant** on this table (see §02).

### `epoch` — who may set it, and to what

The epoch model in §04 is only sound if the *persistence* protocol cannot produce an
invalid epoch history. Prose alone permitted an event to invent a future or past epoch,
which review correctly flagged as the gap between the algorithm and the store.

`runs` carries the authority:

```sql
ALTER TABLE runs ADD COLUMN current_epoch INTEGER NOT NULL DEFAULT 0
    CONSTRAINT runs_epoch_nonneg CHECK (current_epoch >= 0);
```

Four rules, all enforced in the database rather than by convention:

1. **An ordinary event MUST carry exactly `runs.current_epoch`.** Not less, not more.
2. **Only a `run.rewound` event may change it**, and only to `current_epoch + 1`.
3. **`seq` stays globally monotonic per run**, across epochs. `epoch` partitions `seq`;
   it never restarts it. Therefore `(epoch, seq)` order and `seq` order **coincide**, and
   §04's fold may use either — the contradiction review found is resolved by making
   monotonicity an enforced invariant instead of an assumption.
4. **Epochs are dense.** No skipping, so `current_epoch` is also the rewind count.

```sql
CREATE FUNCTION check_event_epoch() RETURNS trigger AS $$
DECLARE cur INTEGER;
BEGIN
  SELECT current_epoch INTO cur FROM runs
   WHERE tenant_id = NEW.tenant_id AND run_id = NEW.run_id
   FOR UPDATE;                            -- serialises concurrent appends

  IF NEW.event_type = 'run.rewound' THEN
    IF NEW.epoch <> cur + 1 THEN
      RAISE EXCEPTION 'a rewind must open epoch %, got %', cur + 1, NEW.epoch
        USING ERRCODE = 'invalid_parameter_value';       -- 22023, see below
    END IF;
    IF (NEW.payload->>'to_epoch')::INTEGER > cur THEN
      RAISE EXCEPTION 'cannot supersede epoch % which does not exist yet',
                      NEW.payload->>'to_epoch'
        USING ERRCODE = 'invalid_parameter_value';
    END IF;
    UPDATE runs SET current_epoch = NEW.epoch
     WHERE tenant_id = NEW.tenant_id AND run_id = NEW.run_id;
  ELSE
    IF NEW.epoch <> cur THEN
      RAISE EXCEPTION 'event in epoch % but run is at epoch % (an ordinary event '
                      'may not change the epoch)', NEW.epoch, cur
        USING ERRCODE = 'invalid_parameter_value';
    END IF;
  END IF;

  -- seq must be strictly increasing per run, regardless of epoch
  IF EXISTS (SELECT 1 FROM run_events
              WHERE tenant_id = NEW.tenant_id AND run_id = NEW.run_id
                AND seq >= NEW.seq) THEN
    RAISE EXCEPTION 'seq % is not greater than every existing seq for this run',
                    NEW.seq
      USING ERRCODE = 'invalid_parameter_value';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER run_events_epoch_check
  BEFORE INSERT ON run_events
  FOR EACH ROW EXECUTE FUNCTION check_event_epoch();
```

**`USING ERRCODE` is not cosmetic.** A bare `RAISE EXCEPTION` raises `P0001`
(`raise_exception`), which is what *every* PL/pgSQL error uses — so a caller cannot tell an
epoch violation from any other trigger failure, and a retry loop matching broadly would
retry a bug forever. Spike 03 asserts the code is `22023` and, separately, that it is **not**
`23505`, because `23505` is the one code the append path *does* retry.

The `FOR UPDATE` is what makes epoch assignment atomic: two concurrent appends to the
same run serialise on the `runs` row, so they cannot both read `current_epoch = 3` and
both claim to open epoch 4. This is the same single-writer discipline as the `seq` PK,
extended to the one column the PK does not cover.

---

## Effect ledger — the atomic claim

```sql
-- The lifecycle is: intent -> (approval) -> claim -> dispatch -> settle.
-- `intended` exists because an effect awaiting a HUMAN cannot hold an execution
-- lease: a 5-minute lease cannot span an hour of deliberation, and claiming
-- early would mark an effect indeterminate that was never dispatched.
CREATE TYPE effect_status AS ENUM
    ('intended',          -- key derived, policy evaluated, NOT dispatchable
     'awaiting_approval', -- a human must answer before it may be claimed
     'claimed',           -- lease held, about to dispatch
     'succeeded', 'failed',
     'denied',            -- an approver refused; never dispatched
     'abandoned',         -- intent superseded or run ended; never dispatched
     'indeterminate');    -- claimed, lease expired unsettled: may have happened
-- (`observed` was added and RETRACTED on 2026-08-27: an unintercepted vendor-side
--  tool cannot be guaranteed to report, so the status promised what the platform
--  could not keep. Vendor-hosted tools are unsupported in v0.1; see spec/07.)

CREATE TABLE effect_ledger (
    tenant_id      BIGINT NOT NULL,
    idempotency_key TEXT  NOT NULL,        -- deterministic; see below
    run_id         TEXT   NOT NULL,
    kind           TEXT   NOT NULL,        -- tool_call | delegation | notify | ...
    status         effect_status NOT NULL DEFAULT 'intended',
    attempt        INTEGER NOT NULL DEFAULT 1,
    request_digest TEXT   NOT NULL,
    result_ref     TEXT,
    error_code     TEXT,

    -- FENCING. A lease_expires_at alone is NOT fencing: worker A can claim,
    -- stall past expiry, have the sweeper mark it indeterminate, then wake and
    -- settle it 'succeeded'. Settlement must therefore prove BOTH that it still
    -- owns the claim and that the claim is still open.
    -- NULL until the row is claimed; an intent has no owner and no lease.
    claim_owner    TEXT,                      -- worker identity
    claim_token    TEXT,                      -- OPAQUE RANDOM, not a counter
    claimed_at     TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    completed_at   TIMESTAMPTZ,

    -- THE PRIMITIVE. Recording intent is an insert; losing the race is a conflict.
    PRIMARY KEY (tenant_id, idempotency_key),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),

    -- lets approvals reference (key, run) TOGETHER, so an approval cannot gate
    -- an effect belonging to a different run
    UNIQUE (tenant_id, idempotency_key, run_id),

    CHECK ((status IN ('succeeded','failed')) = (completed_at IS NOT NULL)),

    -- an unclaimed row carries no lease; a dispatched row has an owner
    CONSTRAINT effect_claim_fields_together CHECK (
        (status IN ('intended','awaiting_approval','denied','abandoned')
           AND claim_owner IS NULL AND claim_token IS NULL
           AND lease_expires_at IS NULL)
     OR (status IN ('claimed','succeeded','failed','indeterminate')
           AND claim_owner IS NOT NULL AND claim_token IS NOT NULL
           AND lease_expires_at IS NOT NULL)
    )
);

-- a claim whose lease has expired and never completed is INDETERMINATE, and
-- must surface to a human rather than being retried
CREATE INDEX effect_ledger_stuck ON effect_ledger (tenant_id, lease_expires_at)
    WHERE status = 'claimed';

-- intents awaiting a human are NOT stuck; they are waiting, on the approval's
-- own (far longer) clock. Keeping them out of the sweeper's path is the whole
-- reason `awaiting_approval` is a distinct status.
CREATE INDEX effect_ledger_awaiting ON effect_ledger (tenant_id, run_id)
    WHERE status = 'awaiting_approval';
```

**`idempotency_key` derivation** — deterministic, and independent of message-log
retention (spike 01, criterion 2):

```
idempotency_key = sha256_hex(canon({
    kind:            "effect_key",
    canonicalization: "nfc+intjson/v1",
    payload: {
        tenant_id, run_id,
        logical_step_path,     -- position, not time
        request_digest         -- digest of the effect's inputs
    }
}))
```

Position rather than time, so a replay of the same logical step derives the same key
while a genuinely different call at the same step derives a different one. There is
**one derivation and no second source**: an explicit key a caller supplies — Cloudflare's,
or one carried on an envelope ([`17-messaging.md`](17-messaging.md) §Dedupe) — is an input
to `request_digest`, never a value written to this column. A caller-supplied string is not
derivable from position, so admitting one as a key would give the ledger two authorities
for one identity and put a value in the column that [§03](03-canonicalisation.md)'s
registered `effect_key` rule cannot reproduce. `causation_id` is not a key source either:
the derivation above contains no message field, and [§02](02-consistency.md) §Claiming and
performing an effect requires the key be derived "never from a message id, so intent
survives message-log retention".
*(Amended 2026-08-30; superseded: "Two key *sources* are supported (Cloudflare's explicit
key, AG2's `causation_id`), but both feed this one column." Both are digest inputs.)*

---

## Session and state — four scopes

```sql
CREATE TABLE sessions (
    tenant_id      BIGINT NOT NULL,
    session_id     TEXT   NOT NULL,
    principal_id   TEXT   NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, session_id),
    FOREIGN KEY (tenant_id, principal_id)
        REFERENCES principals (tenant_id, principal_id)
);

-- `runs.session_id` is declared with `runs` (above) and constrained here, because
-- `sessions` is created after `runs` in this document's order.
ALTER TABLE runs ADD CONSTRAINT runs_session_fk
    FOREIGN KEY (tenant_id, session_id) REFERENCES sessions (tenant_id, session_id);

-- Scope is IN THE KEY, so it cannot be forgotten in a WHERE clause (ADK).
CREATE TYPE state_scope AS ENUM ('app', 'user', 'session');
-- NOTE: 'temp' is deliberately ABSENT from this enum. temp: state has no row.

CREATE TABLE state_entries (
    tenant_id      BIGINT NOT NULL,
    scope          state_scope NOT NULL,
    scope_key      TEXT   NOT NULL,       -- '' for app, principal_id, or session_id
    key            TEXT   NOT NULL,
    value          JSONB  NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, scope, scope_key, key),
    CHECK (key NOT LIKE 'temp:%')          -- non-durable state cannot be stored
);
```

The `CHECK` is how invariant 9 is enforced *in the storage layer*: writing a `temp:`
key is a constraint violation, not a convention someone remembers.

---

### Polymorphic scope enforcement

`state_entries.scope_key` cannot carry a foreign key, so the constraint is a trigger:

```sql
CREATE FUNCTION check_state_scope() RETURNS trigger AS $$
BEGIN
  IF NEW.scope = 'app' THEN
    IF NEW.scope_key <> '' THEN
      RAISE EXCEPTION 'app scope requires an empty scope_key';
    END IF;
  ELSIF NEW.scope = 'user' THEN
    PERFORM 1 FROM principals
      WHERE tenant_id = NEW.tenant_id AND principal_id = NEW.scope_key;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'user scope_key % is not a principal in tenant %',
        NEW.scope_key, NEW.tenant_id;
    END IF;
  ELSIF NEW.scope = 'session' THEN
    PERFORM 1 FROM sessions
      WHERE tenant_id = NEW.tenant_id AND session_id = NEW.scope_key;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'session scope_key % is not a session in tenant %',
        NEW.scope_key, NEW.tenant_id;
    END IF;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER state_entries_scope_check
  BEFORE INSERT OR UPDATE ON state_entries
  FOR EACH ROW EXECUTE FUNCTION check_state_scope();
```

A trigger is weaker than a foreign key — it does not cascade, and it can be bypassed by
a superuser with `session_replication_role`. That is the cost of polymorphism, and it is
why the exception is documented at the top rather than discovered here.

### Effect status transitions, and why `claim_token` is random

```
            +-- policy: deny --> denied
            |
intended ---+-- approval required --> awaiting_approval --+-- approved --> claimed
            |                                             +-- denied ----> denied
            +-- policy: allow ----------------------------> claimed        (expired
                                                                            -> denied)
claimed --> succeeded | failed | indeterminate
intended | awaiting_approval --> abandoned      (run ended, or intent superseded)
```

Two transitions are deliberately absent: **`intended` never becomes `succeeded`**
directly (nothing is dispatched without a claim), and **nothing returns to `intended`**
(a superseded intent is `abandoned` and a fresh intent gets a fresh key).

An effect is only **dispatchable in `claimed`**, and only the worker holding
`claim_token` may dispatch it.

**`claim_token` is an opaque random value, not a monotonic counter.** An earlier draft
had a `effect_claim_history` table to keep tokens monotonic across re-claims, which review
correctly called an inconsistency: **effect rows are never deleted or re-claimed**, so
"monotonic across reclaims" described a transition that cannot occur. Monotonicity buys
nothing when there is never a second claim to order against; uniqueness is the whole
requirement, and a random 128-bit token gives that with no extra table.

This is the difference from the *run* lease, where reclaim is real (a dead worker's run
must be picked up), so fence tokens there must be monotonic and do need history.

`effect_claim_fields_together` (in the DDL above) makes this structural: a row that has
never been claimed cannot carry a lease, and a dispatched row cannot lack an owner.

> **Retracted 2026-08-27 (redo 2).** A subsection here specified `kind = 'unmediated'` with
> status `observed`, plus a matching CHECK (both retracted 2026-08-27). All of it is removed: the status
> asserted that every vendor-side tool use would be recorded, which the platform cannot
> guarantee across a boundary it does not control. Vendor-hosted tools are **unsupported in
> v0.1** — see [`spec/07`](07-adapter-protocol.md) and OQ-043.

## Idempotency records — the table §06 promises

`06-api.md` requires `Idempotency-Key` on run creation and approval decisions, scoped
`(tenant_id, endpoint, key)`, retained 24 hours, with a replay returning the original
response and a *different* body returning `422`. None of that is possible without storage,
and review found the table missing.

```sql
CREATE TABLE idempotency_records (
    tenant_id     BIGINT NOT NULL,
    endpoint      TEXT   NOT NULL,        -- 'POST /v1/runs'
    idem_key      TEXT   NOT NULL,        -- client-supplied
    request_digest TEXT  NOT NULL,        -- canonical (03): detects a changed body
    response_status INTEGER NOT NULL,
    response_body JSONB  NOT NULL,        -- replayed verbatim
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL,   -- created_at + 24h

    PRIMARY KEY (tenant_id, endpoint, idem_key)
);

CREATE INDEX idempotency_expiry ON idempotency_records (expires_at);
```

The insert is the concurrency control, exactly as with effects:

```sql
INSERT INTO idempotency_records (...) VALUES (...)
ON CONFLICT (tenant_id, endpoint, idem_key) DO NOTHING
RETURNING 1;
-- no row => a record exists. Compare request_digest:
--   same     -> replay response_body with Idempotency-Replayed: true
--   different-> 422 idempotency_key_reused (never replay a different request's answer)
```

Two in-flight requests with the same key mean the second waits or returns `409
idempotency_in_flight`; it must not execute. **The digest comparison is why `request_digest`
is canonical** — a re-serialised body with reordered keys is the same request and must not
look like a client bug.

## Approval — with an approver

```sql
CREATE TYPE approval_status AS ENUM
    ('pending', 'approved', 'denied', 'expired', 'superseded');

CREATE TABLE approvals (
    tenant_id      BIGINT NOT NULL,
    approval_id    TEXT   NOT NULL,
    run_id         TEXT   NOT NULL,
    action_ref     TEXT   NOT NULL,        -- the gated effect's idempotency_key
    status         approval_status NOT NULL DEFAULT 'pending',
    requested_by_rule TEXT NOT NULL,       -- WHICH policy required it (ADR-0015 r6)
    request_payload JSONB NOT NULL,        -- what the human was actually shown
    requested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ,
    decided_at     TIMESTAMPTZ,
    decided_by     TEXT,                   -- → principals. THE field nobody has.
    -- Carried so the FK below can PIN the kind. Redundant by design: without it
    -- `decided_by` is any principal, and "one attributable human decision"
    -- (spec/09 7) is prose the schema does not enforce. Found 2026-08-27 while
    -- applying decision D-A.
    -- Widened 2026-08-30 (OQ-044, ADR-0015 amendment 4): a `service` principal may
    -- decide, standing for a customer's external finance/legal approval system with
    -- the ticket ref in decision_rationale below -- still ONE attributable decision,
    -- never a quorum. `human` stays the only kind for a decision made directly by a
    -- person at the keyboard; the class is chosen at decide time, not guessed.
    decided_by_kind principal_kind
        CHECK (decided_by_kind IS NULL OR decided_by_kind IN ('human', 'service')),
    decision_rationale TEXT,               -- durable on APPROVE as well as deny

    PRIMARY KEY (tenant_id, approval_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    -- (principal_id, kind) must be UNIQUE on principals for this to be a legal FK;
    -- see the `principals_id_kind` unique constraint. This is what makes "the
    -- approver is a human" a database fact rather than an API convention.
    FOREIGN KEY (tenant_id, decided_by, decided_by_kind)
        REFERENCES principals (tenant_id, principal_id, kind),
    -- run_id is IN the FK, so an approval cannot gate an effect belonging to a
    -- DIFFERENT run. With separate FKs, approval-for-run-B could reference
    -- effect-of-run-A and the database would accept it.
    FOREIGN KEY (tenant_id, action_ref, run_id)
        REFERENCES effect_ledger (tenant_id, idempotency_key, run_id),

    -- a terminal decision MUST name its approver and when (invariant 8)
    CHECK ((status IN ('approved','denied'))
           = (decided_by IS NOT NULL AND decided_at IS NOT NULL
              AND decided_by_kind IS NOT NULL))
);

-- At most ONE pending approval per gated action. Without this, two concurrent
-- "request approval" paths create two pending APPROVAL rows for one effect, and a
-- approve one while another is still outstanding -- so the effect looks both
-- approved and pending. Spike 03 asserts this index refuses the second insert.
CREATE UNIQUE INDEX approvals_pending_one ON approvals (tenant_id, action_ref)
    WHERE status = 'pending';

CREATE INDEX approvals_pending ON approvals (tenant_id, requested_at)
    WHERE status = 'pending';
```

That final `CHECK` is invariant 8 made unbreakable: an approved row without a
`decided_by` cannot exist. HumanLayer has the best approval design in the study and
still cannot answer "who approved this"; this closes it in the schema rather than in
review.

---

## Policy

```sql
CREATE TYPE policy_decision AS ENUM ('deny', 'steer', 'observe');
CREATE TYPE policy_scope AS ENUM ('tenant', 'project', 'agent', 'session');

CREATE TABLE policies (
    tenant_id      BIGINT NOT NULL,
    policy_id      TEXT   NOT NULL,
    name           TEXT   NOT NULL,
    scope          policy_scope NOT NULL,
    scope_key      TEXT   NOT NULL DEFAULT '',
    cedar_source   TEXT   NOT NULL,
    decision       policy_decision NOT NULL,
    steering_guidance TEXT,                -- REQUIRED when decision='steer'
    enabled        BOOLEAN NOT NULL DEFAULT true,
    created_by     TEXT   NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, policy_id),
    UNIQUE (tenant_id, name),
    FOREIGN KEY (tenant_id, created_by)
        REFERENCES principals (tenant_id, principal_id),

    -- a steer that cannot say how to comply is invalid (Agent Control)
    CHECK (decision <> 'steer' OR steering_guidance IS NOT NULL)
);
```

**Amended 2026-08-30 (OQ-079):** a platform rule with no Cedar policy behind it — the `app`-scope
default deny ([`16-knowledge.md`](16-knowledge.md) §State), the `temp:` refusal, and messaging's
scope checks ([`17-messaging.md`](17-messaging.md) §Public surface) — is recorded against a
**reserved `policies` row seeded per tenant at provisioning**, named `platform:<rule>` (e.g.
`platform:app_scope_deny`), `cedar_source` a comment stating the rule is enforced in code, not
Cedar. `policy_decisions.policy_id`'s `NOT NULL` FK holds unchanged and every platform refusal is
aggregable through the same table a Cedar verdict lands in, rather than a nullable FK carving an
exception into it.

```sql
-- Every evaluation, including refusals, aggregable (AG2 + Agent Control).
CREATE TABLE policy_decisions (
    tenant_id      BIGINT NOT NULL,
    decision_id    TEXT   NOT NULL,
    run_id         TEXT   NOT NULL,
    policy_id      TEXT   NOT NULL,
    principal_id   TEXT   NOT NULL,        -- WHOM the decision was about
    phase          TEXT   NOT NULL,        -- request | tool_call | tool_result
    decision       policy_decision NOT NULL,
    enforced       BOOLEAN NOT NULL,       -- false for observe-mode (shadow)
    latency_ms     INTEGER NOT NULL,
    decided_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, decision_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    FOREIGN KEY (tenant_id, policy_id) REFERENCES policies (tenant_id, policy_id),
    FOREIGN KEY (tenant_id, principal_id)
        REFERENCES principals (tenant_id, principal_id)
);

CREATE INDEX policy_decisions_shadow
    ON policy_decisions (tenant_id, policy_id, decided_at) WHERE enforced = false;
```

`enforced` is what makes `observe` mode measurable: shadow verdicts are recorded in
the same table as enforced ones and can be aggregated per policy over time.

---

## Admin audit

**Amended 2026-08-30 (OQ-078).** Credential and routine administration have nowhere to land:
`run_events` requires a `run_id` FK to `runs`, so creating or revoking a `Credential`
([`14-credentials.md`](14-credentials.md)) and pausing, resuming or disabling a routine
([`11-routines.md`](11-routines.md), which keeps only `state_changed_by`/`state_changed_at`)
have no run to append against. `admin_events` is the tenant-scoped, non-run-scoped audit log
for exactly this: every admin write that is not a `run_events` row.

```sql
CREATE TABLE admin_events (
    tenant_id      BIGINT NOT NULL,
    admin_event_id TEXT   NOT NULL,       -- sortable ULID
    principal_id   TEXT   NOT NULL,       -- who acted; the system actor is a principal too
    action         TEXT   NOT NULL,       -- OPEN: 'credential.created', 'task.paused', ...
    target_kind    TEXT   NOT NULL,       -- 'credential' | 'task' | ...
    target_id      TEXT   NOT NULL,
    detail         JSONB  NOT NULL DEFAULT '{}'::jsonb,
    at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, admin_event_id),
    FOREIGN KEY (tenant_id, principal_id)
        REFERENCES principals (tenant_id, principal_id)
);
CREATE INDEX admin_events_by_target ON admin_events (tenant_id, target_kind, target_id, at);

GRANT SELECT, INSERT ON admin_events TO app_role;   -- no UPDATE, no DELETE: an audit row
                                                     -- that can be edited is not an audit row
```

`action` is open text, in `01-schema.md`'s `effect_ledger.kind` and `10-work-bundles.md`'s
`actions.operation` style — a closed enum here would need a migration for every new admin
route. `detail` carries whatever the action needs that the four typed columns do not: a
scheduler summary row (`task.catchup_skipped {from, to, count}`,
[`11-routines.md`](11-routines.md) §Missed ticks, OQ-097) and an auto-pause's failure count
(§Who may create, pause and disable a routine, OQ-095) both live here rather than forcing a
column per action.

---

## Leases

```sql
-- Fenced resume lease. Pin correctness does not prevent duplicate execution
-- (spike 02), so reaching the adapter requires winning this insert.
CREATE TABLE run_leases (
    tenant_id      BIGINT NOT NULL,
    run_id         TEXT   NOT NULL,
    holder         TEXT   NOT NULL,        -- worker identity
    fence_token    BIGINT NOT NULL,        -- monotonic; see 02
    acquired_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL,

    PRIMARY KEY (tenant_id, run_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id)
);

CREATE INDEX run_leases_expiring ON run_leases (tenant_id, expires_at);

-- Fence tokens must be monotonic ACROSS reclaims, so the high-water mark has to
-- outlive the lease row it came from. Without this table, a reclaim after a
-- DELETE would reissue token 1 and a stalled holder's writes would be accepted.
CREATE TABLE run_lease_history (
    tenant_id      BIGINT NOT NULL,
    run_id         TEXT   NOT NULL,
    max_fence_token BIGINT NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id)
);

-- Moved here 2026-08-30 from `17-messaging.md`, on the precedent §02 records for the
-- lease tables: DDL for one resource in two documents is how an implementer builds two
-- tables. `17-messaging.md` names these and no longer defines them.
CREATE TABLE channels (
    tenant_id      BIGINT NOT NULL,
    channel_id     TEXT   NOT NULL,
    protocol       TEXT   NOT NULL
                   CHECK (protocol IN ('conversation','discussion',
                                       'consulting','workflow')),
    state          TEXT   NOT NULL DEFAULT 'open'
                   CHECK (state IN ('open','closed')),
                   -- two states only, because AG2's close_channel / is_terminal() has
                   -- two (RESULT.md §Criterion 2; hub/core.py:2907-2911 @ 90f490a)
    depth_cap      SMALLINT NOT NULL DEFAULT 5,   -- ADR-0003: Rule.limits default
    created_by     TEXT   NOT NULL,
    expires_at     TIMESTAMPTZ,                   -- the default a bare envelope takes
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at      TIMESTAMPTZ,
    max_seq        BIGINT NOT NULL DEFAULT 0,     -- the seq high-water mark. It outlives
                                                  -- the envelope rows; see §Retention.

    PRIMARY KEY (tenant_id, channel_id),
    FOREIGN KEY (tenant_id, created_by)
        REFERENCES principals (tenant_id, principal_id),
    CHECK ((state = 'closed') = (closed_at IS NOT NULL))
);

-- The per-channel WAL, one row per envelope. Every ACCEPTED envelope is recorded
-- in full regardless of who was notified: audit scope is deliberately wider than
-- delivery scope (ADR-0003, from AG2's "audit + debug" comment).
CREATE TABLE channel_envelopes (
    tenant_id      BIGINT NOT NULL,
    channel_id     TEXT   NOT NULL,
    seq            BIGINT NOT NULL,        -- assigned INSIDE the insert, from channels.max_seq
    envelope_id    TEXT   NOT NULL,        -- stamped on accept, never by the sender
    sender_id      TEXT   NOT NULL,
    audience       JSONB,                  -- NULL broadcasts in-channel; array targets
    event_type     TEXT   NOT NULL,
    event_data     JSONB  NOT NULL,
    causation_id   TEXT,                   -- threading ONLY; see §Dedupe
    run_id         TEXT,
    task_id        TEXT,                   -- the routine, when the post came from one (11).
                                           -- The composite FK is added by 11's own DDL,
                                           -- because `tasks` is created there.
    traceparent    TEXT,                   -- ADR-0003 carries trace_id; renamed 2026-08-27
                                           -- to the full W3C header value, as in run_events (04)
    priority       TEXT   NOT NULL DEFAULT 'normal'
                   CHECK (priority IN ('background','normal','urgent')),
    depth          SMALLINT NOT NULL DEFAULT 0 CHECK (depth BETWEEN 0 AND 8),
    idempotency_key TEXT,                  -- carried for an externally-triggered effect
    ttl_seconds    INTEGER,
    accepted_fence BIGINT NOT NULL,        -- the channel-lease fence held at accept
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, channel_id, seq),
    UNIQUE (tenant_id, envelope_id),
    FOREIGN KEY (tenant_id, channel_id) REFERENCES channels (tenant_id, channel_id),
    FOREIGN KEY (tenant_id, sender_id)
        REFERENCES principals (tenant_id, principal_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    CHECK (audience IS NULL OR jsonb_typeof(audience) = 'array')
);

-- Amended 2026-08-30 (OQ-126): the durable membership record `not_a_member` reads.
-- AG2 keeps passports in hub memory only; this makes membership a row instead.
CREATE TABLE channel_members (
    tenant_id      BIGINT NOT NULL,
    channel_id     TEXT   NOT NULL,
    principal_id   TEXT   NOT NULL,
    role           TEXT   NOT NULL DEFAULT 'member',   -- OPEN: 'member', 'admin', ...
    added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, channel_id, principal_id),
    FOREIGN KEY (tenant_id, channel_id) REFERENCES channels (tenant_id, channel_id),
    FOREIGN KEY (tenant_id, principal_id)
        REFERENCES principals (tenant_id, principal_id)
);

-- Per-subscriber progress. At-least-once falls out of this table: the cursor moves
-- only after the subscriber has durably handled the envelope.
CREATE TABLE channel_cursors (
    tenant_id      BIGINT NOT NULL,
    channel_id     TEXT   NOT NULL,
    subscriber_id  TEXT   NOT NULL,
    acked_seq      BIGINT NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, channel_id, subscriber_id),
    FOREIGN KEY (tenant_id, channel_id) REFERENCES channels (tenant_id, channel_id),
    FOREIGN KEY (tenant_id, subscriber_id)
        REFERENCES principals (tenant_id, principal_id)
);

-- One hub per channel (see 02). Same mechanism, different resource.
CREATE TABLE channel_leases (
    tenant_id      BIGINT NOT NULL,
    channel_id     TEXT   NOT NULL,
    hub_id         TEXT   NOT NULL,
    fence_token    BIGINT NOT NULL,
    acquired_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, channel_id),
    FOREIGN KEY (tenant_id, channel_id) REFERENCES channels (tenant_id, channel_id)
);

CREATE TABLE channel_lease_history (
    tenant_id      BIGINT NOT NULL,
    channel_id     TEXT   NOT NULL,
    max_fence_token BIGINT NOT NULL,
    PRIMARY KEY (tenant_id, channel_id),
    FOREIGN KEY (tenant_id, channel_id) REFERENCES channels (tenant_id, channel_id)
);
```

`fence_token` exists because a TTL alone is insufficient: a paused holder can wake
after expiry believing it still owns the run. §02 specifies how the token is used to
reject its writes.

---

## Grants required

Enforcing "append-only" in the schema rather than in code:

```sql
GRANT SELECT, INSERT ON run_events TO app_role;   -- no UPDATE, no DELETE
GRANT SELECT, INSERT ON agent_definitions TO app_role;   -- immutable artifacts
GRANT SELECT, INSERT, UPDATE ON runs, approvals, effect_ledger TO app_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON run_leases TO app_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON sandboxes TO app_role;

-- The channel tables are the messaging layer's, and the grant IS the enforcement of
-- [`17-messaging.md`](17-messaging.md) §Retention: no correctness predicate outside
-- that layer may read the envelope log, so `app_role` is given no SELECT on it.
GRANT SELECT, INSERT ON channel_envelopes TO messaging_role;   -- no UPDATE, no DELETE
GRANT SELECT, INSERT, UPDATE ON channels, channel_cursors TO messaging_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON channel_leases TO messaging_role;
GRANT SELECT, INSERT, DELETE ON channel_members TO messaging_role;   -- membership can be revoked
```

Each table `spec/10`-`spec/18` creates issues its own grants beside its own
`CREATE TABLE`, which is the only order in which they apply; this section states the
discipline they follow, not the statements.

## Migration discipline

Numbered, forward-only, each guarded by an existence check so re-running is safe
(HumanLayer's pattern). Every migration gets its own test asserting the post-state,
per ADK and Agent Control.
