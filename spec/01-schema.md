# 01 — Schema
<!-- status: final -->

PostgreSQL 16+. Every table is tenant-scoped in its **primary key**, and every
cross-table reference is a **composite foreign key including `tenant_id`** — so a
cross-tenant relationship is a constraint violation, not a silent success.

Convention: `tenant_id BIGINT` (not UUID) because it appears in every index and
narrower keys matter. `id` columns are `TEXT` holding a sortable ULID.

**Two exceptions to the composite-FK rule, stated rather than hidden:**

1. `state_entries.scope_key` is unconstrained text, because its referent depends on
   `scope` (a principal id, a session id, or empty for app scope). A polymorphic FK is
   not expressible in SQL. Enforced by a trigger instead — see §Polymorphic scope.
2. `policies.scope = 'project'` is accepted by the enum but **has no referent in
   v0.1**, because `Project` is not a v0.1 resource. The API rejects it (`422`) until
   `projects` exists. Recorded here so the gap is visible rather than surprising.

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
    identity       TEXT   NOT NULL,       -- 'acp:claude-code'
    digest         TEXT   NOT NULL,       -- DERIVED from the contract, not supplied
    protocol_version TEXT NOT NULL,
    -- The enum is Omnigent's full taxonomy and is kept so the column never needs a
    -- migration. Only 'sdk_in_process' is SHIPPED: we build and operate the agents on
    -- a thin internal harness over the vendor SDKs, so there is no third-party
    -- subprocess or TUI to adapt. The others are reserved, not supported.
    integration_mode TEXT NOT NULL
        CHECK (integration_mode IN ('sdk_in_process','cli_subprocess',
                                    'acp_subprocess','native_tui','native_server')),
    CONSTRAINT integration_mode_shipped
        CHECK (integration_mode = 'sdk_in_process'),   -- drop this to ship another
    -- the adapter's OWN checkpoint payload format, which runs pin (07 6)
    payload_schema_digest TEXT NOT NULL,
    declared_capabilities JSONB NOT NULL DEFAULT '{}',
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, identity, digest)
);
```

`integration_mode` is Omnigent's taxonomy. Only `sdk_in_process` is shipped (amended
2026-08-27); the rest are retained so the column never needs a migration. The original
argument for `native_tui` — adapting an agent
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

    FOREIGN KEY (tenant_id, pinned_adapter_identity, pinned_adapter_digest)
        REFERENCES adapter_contracts (tenant_id, identity, digest),

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
    epoch          INTEGER NOT NULL,       -- rewind generation; see 04 and below
    event_type     TEXT   NOT NULL,        -- from the registry; see 04
    payload        JSONB  NOT NULL,
    traceparent    TEXT,                   -- full W3C header; context rides the event
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
     'indeterminate',     -- claimed, lease expired unsettled: may have happened
     'observed');         -- UNMEDIATED: we saw it, we did not own it. See below.

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

    -- an unclaimed row carries no lease; a dispatched row has an owner.
    -- `observed` is deliberately grouped with the NEVER-CLAIMED statuses: an
    -- unmediated effect executed on the vendor's side, so there is nothing to
    -- claim, fence or settle, and a claim field on such a row would assert an
    -- at-most-once guarantee the platform did not provide.
    CONSTRAINT effect_claim_fields_together CHECK (
        (status IN ('intended','awaiting_approval','denied','abandoned','observed')
           AND claim_owner IS NULL AND claim_token IS NULL
           AND lease_expires_at IS NULL)
     OR (status IN ('claimed','succeeded','failed','indeterminate')
           AND claim_owner IS NOT NULL AND claim_token IS NOT NULL
           AND lease_expires_at IS NOT NULL)
    ),

    -- `observed` exists ONLY for unmediated effects, and `unmediated` effects can
    -- reach no other status: they are never claimed, so they can never succeed,
    -- fail or become indeterminate in the senses those words carry here.
    CONSTRAINT observed_iff_unmediated CHECK (
        (status = 'observed') = (kind = 'unmediated')
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

### Unmediated effects — `kind = 'unmediated'`, status `observed`

A vendor-hosted tool (web search, code execution, file search, computer use) runs inside the
model provider and cannot be intercepted. Such a tool is permitted **only** as a declared
adapter capability, **denied by default**, and **never alongside a mutation** — the three
conditions are stated once, normatively, in [`spec/07`](07-adapter-protocol.md)
§"Unmediated tools".

What the schema enforces:

| Rule | Mechanism |
|---|---|
| `observed` carries no claim, token or lease | `effect_claim_fields_together` |
| `observed` ⇔ `kind = 'unmediated'` | `observed_iff_unmediated` |
| an unmediated effect never becomes `succeeded` | the same biconditional — it cannot leave `observed` |
| the capability is part of the adapter digest | `declared_capabilities` participates in `adapter_contracts.digest` |

The row exists so an unmediated effect is **visible and auditable**, not so it is trusted. A
reader joining `effect_ledger` for at-most-once evidence must filter
`status <> 'observed'`, and the biconditional is what makes that filter reliable rather than
conventional.

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
    decision_rationale TEXT,               -- durable on APPROVE as well as deny

    PRIMARY KEY (tenant_id, approval_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    FOREIGN KEY (tenant_id, decided_by)
        REFERENCES principals (tenant_id, principal_id),
    -- run_id is IN the FK, so an approval cannot gate an effect belonging to a
    -- DIFFERENT run. With separate FKs, approval-for-run-B could reference
    -- effect-of-run-A and the database would accept it.
    FOREIGN KEY (tenant_id, action_ref, run_id)
        REFERENCES effect_ledger (tenant_id, idempotency_key, run_id),

    -- a terminal decision MUST name its approver and when (invariant 8)
    CHECK ((status IN ('approved','denied'))
           = (decided_by IS NOT NULL AND decided_at IS NOT NULL))
);

-- At most ONE pending approval per gated action. Without this, two concurrent
-- "request approval" paths create two pending rows for one effect and a human can
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

-- One hub per channel (see 02). Same mechanism, different resource.
CREATE TABLE channel_leases (
    tenant_id      BIGINT NOT NULL,
    channel_id     TEXT   NOT NULL,
    hub_id         TEXT   NOT NULL,
    fence_token    BIGINT NOT NULL,
    acquired_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, channel_id)
);

CREATE TABLE channel_lease_history (
    tenant_id      BIGINT NOT NULL,
    channel_id     TEXT   NOT NULL,
    max_fence_token BIGINT NOT NULL,
    PRIMARY KEY (tenant_id, channel_id)
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
```

## Migration discipline

Numbered, forward-only, each guarded by an existence check so re-running is safe
(HumanLayer's pattern). Every migration gets its own test asserting the post-state,
per ADK and Agent Control.
