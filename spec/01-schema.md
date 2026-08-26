# 01 — Schema
<!-- status: final -->

PostgreSQL 16+. Every table is tenant-scoped in its **primary key**, and every
cross-table reference is a **composite foreign key including `tenant_id`** — so a
cross-tenant relationship is a constraint violation, not a silent success.

Convention: `tenant_id BIGINT` (not UUID) because it appears in every index and
narrower keys matter. `id` columns are `TEXT` holding a sortable ULID.

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
CREATE TYPE principal_kind AS ENUM ('human', 'agent', 'service', 'remote');

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
        REFERENCES principals (tenant_id, principal_id)
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
    body           JSONB  NOT NULL,       -- the canonical definition document
    canon_profile  TEXT   NOT NULL,       -- e.g. 'nfc+jcs/v1' — pins the rules used
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
    identity       TEXT   NOT NULL,       -- 'acp:claude-code'
    digest         TEXT   NOT NULL,       -- DERIVED from the contract, not supplied
    protocol_version TEXT NOT NULL,
    integration_mode TEXT NOT NULL
        CHECK (integration_mode IN ('sdk_in_process','cli_subprocess',
                                    'acp_subprocess','native_tui','native_server')),
    declared_capabilities JSONB NOT NULL DEFAULT '{}',
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, identity, digest)
);
```

`integration_mode` is Omnigent's taxonomy, including `native_tui` — adapting an agent
that offers no API by driving its terminal.

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

    -- intent lives ON the run in v0.1 (no Task resource yet)
    agent_id       TEXT   NOT NULL,
    prompt         TEXT,
    created_by     TEXT   NOT NULL,        -- the acting principal

    -- THE PIN. Compared on every resume; a mismatch is terminal (INCOMPATIBLE).
    pinned_definition_digest TEXT NOT NULL,
    pinned_adapter_identity  TEXT NOT NULL,
    pinned_adapter_digest    TEXT NOT NULL,
    pinned_payload_schema    TEXT NOT NULL,   -- the ADAPTER's own format
    checkpoint_schema_version INTEGER NOT NULL,

    -- failure classification: queryable, so retry logic can branch (Omnigent)
    error_code     TEXT,
    error_detail   TEXT,

    rewind_before_step BIGINT,              -- logical history reduction (ADK)

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

---

## The log — append-only, single-writer by primary key

```sql
CREATE TABLE run_events (
    tenant_id      BIGINT NOT NULL,
    run_id         TEXT   NOT NULL,
    seq            BIGINT NOT NULL,        -- assigned INSIDE the txn; see 02
    event_type     TEXT   NOT NULL,        -- from the registry; see 04
    payload        JSONB  NOT NULL,
    trace_id       TEXT,                   -- context rides the event (AG2)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- (tenant, run, seq) as PK is the single-writer guarantee: two concurrent
    -- appends collide and one rolls back. No lock service. (Google AX.)
    PRIMARY KEY (tenant_id, run_id, seq),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id)
);
```

There is **no `UPDATE` or `DELETE` grant** on this table (see §02). State is derived
by folding it, never stored in a parallel column that can drift.

---

## Effect ledger — the atomic claim

```sql
CREATE TYPE effect_status AS ENUM
    ('claimed', 'succeeded', 'failed', 'indeterminate');

CREATE TABLE effect_ledger (
    tenant_id      BIGINT NOT NULL,
    idempotency_key TEXT  NOT NULL,        -- deterministic; see below
    run_id         TEXT   NOT NULL,
    kind           TEXT   NOT NULL,        -- tool_call | delegation | notify | ...
    status         effect_status NOT NULL DEFAULT 'claimed',
    attempt        INTEGER NOT NULL DEFAULT 1,
    request_digest TEXT   NOT NULL,
    result_ref     TEXT,
    error_code     TEXT,
    claimed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_expires_at TIMESTAMPTZ NOT NULL,     -- fenced; see 02
    completed_at   TIMESTAMPTZ,

    -- THE PRIMITIVE. Claiming is an insert; losing the race is a conflict.
    PRIMARY KEY (tenant_id, idempotency_key),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),

    CHECK ((status IN ('succeeded','failed')) = (completed_at IS NOT NULL))
);

-- a claim whose lease has expired and never completed is INDETERMINATE, and
-- must surface to a human rather than being retried
CREATE INDEX effect_ledger_stuck ON effect_ledger (tenant_id, lease_expires_at)
    WHERE status = 'claimed';
```

**`idempotency_key` derivation** — deterministic, and independent of message-log
retention (spike 01, criterion 2):

```
idempotency_key = sha256_hex(canon({
    kind:            "effect_key",
    canonicalization: "nfc+jcs/v1",
    payload: {
        tenant_id, run_id,
        logical_step_path,     -- position, not time
        request_digest         -- digest of the effect's inputs
    }
}))
```

Position rather than time, so a replay of the same logical step derives the same key
while a genuinely different call at the same step derives a different one. Two key
*sources* are supported (Cloudflare's explicit key, AG2's `causation_id`), but both
feed this one column.

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
    decision_rationale TEXT,               -- durable on APPROVE as well as deny

    PRIMARY KEY (tenant_id, approval_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    FOREIGN KEY (tenant_id, decided_by)
        REFERENCES principals (tenant_id, principal_id),

    -- a terminal decision MUST name its approver and when (invariant 8)
    CHECK ((status IN ('approved','denied'))
           = (decided_by IS NOT NULL AND decided_at IS NOT NULL))
);

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
    FOREIGN KEY (tenant_id, policy_id) REFERENCES policies (tenant_id, policy_id)
);

CREATE INDEX policy_decisions_shadow
    ON policy_decisions (tenant_id, policy_id, decided_at) WHERE enforced = false;
```

`enforced` is what makes `observe` mode measurable: shadow verdicts are recorded in
the same table as enforced ones and can be aggregated per policy over time.

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
```

## Migration discipline

Numbered, forward-only, each guarded by an existence check so re-running is safe
(HumanLayer's pattern). Every migration gets its own test asserting the post-state,
per ADK and Agent Control.
