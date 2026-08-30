# 11 — Routines and Task
<!-- status: draft -->

Settles what `spec/00-overview.md` owes — **schedule *or* trigger → Run**: the `tasks` table, the trigger
taxonomy, the additive `runs.task_id` migration, who may create, pause and disable a routine, the rule that
makes a doubled cron tick create one Run, the missed-tick policy, and delegation as a ledgered effect. It does
**not** settle per-firing cost budgets (cost is Tier 3), an unauthenticated webhook endpoint with its own secret
([`14-credentials.md`](14-credentials.md) settles `Credential` and
scopes a per-webhook secret out), what an `event` trigger observes (no metric resource exists), or the Run state machine,
which §05 owns. It also carries the composite FK for `channel_envelopes.task_id` (`01-schema.md`;
`17-messaging.md` §The Envelope, as data), which cannot live in 01 because `tasks` is created here.

---

## A routine is a row in `tasks`

`spec/00-overview.md` writes the owed area as "`tasks` / `routines`" and leaves the relationship open. It is
closed here: **the two words name one resource from two directions.** `Task` is what ADR-0002 calls the durable
intent that outlives its attempts; *routine* is what the customer buys. **A routine creates Runs and never
becomes one** — ADR-0002's shape, unchanged.

`synthesis/scope-reconciliation.md` §2's deferral was **reversed** on 2026-08-27: the OKF bundle carries a 10:00
IST daily cadence and a weekly roll-up as prose for want of a resource (ADR-0002, product-decision row). The
only precedent for the split as a *resource pair* is Omnigent's `scheduled_tasks` / `scheduled_task_runs`
(`omnigent/db/db_models.py:1434,1546 @ ba9e371`; `synthesis/v01-boundary.md` Tier 2 #16, "Omnigent (the only
precedent)"); ADR-0002's log records Cloudflare's `cf_agents_fibers` / `cf_agents_runs` as the same shape, minus
the resource.

---

## Schema

```sql
CREATE TYPE task_state AS ENUM ('active', 'paused', 'disabled');
CREATE TYPE task_trigger_kind AS ENUM ('cron', 'event', 'webhook', 'manual');
CREATE TABLE tasks (
    tenant_id      BIGINT NOT NULL,
    task_id        TEXT   NOT NULL,
    name           TEXT   NOT NULL,
    agent_id       TEXT   NOT NULL,      -- the NAME, not a digest; see below
    prompt         TEXT   NOT NULL,
    state          task_state NOT NULL DEFAULT 'active',
    trigger_kind   task_trigger_kind NOT NULL,
    cron_expression TEXT,                -- 5-field cron; NULL unless trigger_kind='cron'
    timezone       TEXT,                 -- IANA name, e.g. 'Asia/Kolkata'
    overlap_policy TEXT NOT NULL DEFAULT 'skip' CHECK (overlap_policy IN ('skip','allow')),
    misfire_grace_seconds INTEGER NOT NULL DEFAULT 30 CHECK (misfire_grace_seconds BETWEEN 0 AND 86400),
    created_by     TEXT   NOT NULL,      -- every Run this task creates is attributed here
    state_changed_by TEXT,               -- the LAST transition only; there is no task log
    state_changed_at TIMESTAMPTZ,
    next_fire_at   TIMESTAMPTZ,          -- a PROJECTION; a wrong value DROPS a tick, never doubles one
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, task_id),
    UNIQUE (tenant_id, name),
    FOREIGN KEY (tenant_id, agent_id) REFERENCES agents (tenant_id, agent_id),
    FOREIGN KEY (tenant_id, created_by) REFERENCES principals (tenant_id, principal_id),
    FOREIGN KEY (tenant_id, state_changed_by) REFERENCES principals (tenant_id, principal_id),
    CONSTRAINT task_cron_fields_together CHECK ((trigger_kind = 'cron')
        = (cron_expression IS NOT NULL AND timezone IS NOT NULL)),
    CONSTRAINT task_next_fire_only_cron CHECK (trigger_kind = 'cron' OR next_fire_at IS NULL)
);
CREATE INDEX tasks_due ON tasks (tenant_id, next_fire_at)   -- the system actor's access path
    WHERE state = 'active' AND trigger_kind = 'cron';
```

**`overlap_policy` defaults to `skip`** — Omnigent's policy, SKIP overlap alongside a 30-second
`MISFIRE_GRACE_TIME_S`, both guarding *self*-overlap (`projects/omnigent/teardown.md:666-667` →
`omnigent/server/scheduled/scheduler.py:1-24 @ ba9e371`). `allow` has no precedent in the study; whether a
routine may ever run concurrently with itself is **unknown — OQ**. `allow` is reserved in the CHECK and refused
by the API — `POST /v1/tasks` or `PATCH` with `overlap_policy: "allow"` is `422 overlap_policy_unsupported`, the
same treatment `event` gets and for the same reason: a stored value with no defined behaviour is a promise
nothing keeps. The upper bound on `misfire_grace_seconds` is the catch-up horizon (§Missed ticks): a longer
window would promise a late fire for a tick no scan can find. A grace approaching the horizon is legal and
inadvisable — §Missed ticks 2's premise argument applies against the operator's own configuration, and the
platform does not second-guess it.

**A routine binds an `agent_id`, not a digest.** Each firing pins the agent's then-current digest onto the Run
it creates, as `POST /v1/runs` does (`06-api.md` §Runs), so repointing an agent changes tomorrow's tick and
never today's in-flight run. A routine pinned to a digest of its own would be a second pin authority, and §05's
resume ordering compares against `run.pinned_definition_digest` only.

### `runs.task_id` — the additive migration

Planned in `synthesis/scope-reconciliation.md` §2, promised by `01-schema.md`'s comment on `runs`:

```sql
ALTER TABLE runs ADD COLUMN task_id TEXT;
ALTER TABLE runs ADD CONSTRAINT runs_task_fk
    FOREIGN KEY (tenant_id, task_id) REFERENCES tasks (tenant_id, task_id);
CREATE INDEX runs_by_task ON runs (tenant_id, task_id, created_at DESC) WHERE task_id IS NOT NULL;
```

Nullable because a Run created through `POST /v1/runs` has no routine. Intent stays on the Run (`01-schema.md`)
and is **copied** at firing rather than read through the task: a Run must stay readable after its routine is
disabled, and an edited prompt must not retroactively change what a completed Run says it did.

---

## Trigger taxonomy

| Kind | Fires when | v0.1 | Evidence |
|---|---|---|---|
| `cron` | a tick of a 5-field cron expression in an IANA timezone arrives | **shipped** | Omnigent (`rrule` + timezone, `db_models.py:1434 @ ba9e371`); Letta (timezone-aware IANA schedules, `projects/letta/teardown.md:346`) |
| `manual` | a person fires it | **shipped** | Letta's `one_off_due` run reason (`cron-file.ts:26-43 @ 852ca24`) |
| `webhook` | an external caller fires it through a relay we operate | **shipped, without a per-webhook secret** | v0.1 has no unauthenticated endpoint and no per-webhook secret; the kind records only that a fire arrived from outside, through an admin-credentialed relay. Evidence: none — a naming choice, and whether it earns its own credential is **unknown — OQ** |
| `event` | a metric or observation crosses a predicate | **reserved; `422 trigger_kind_unsupported`** | see below |

**Cron rather than RFC 5545 `rrule`.** Omnigent uses `rrule`, Letta uses cron; both work. Cron is chosen because
§Idempotent firing needs every tick to have a **name** two schedulers derive identically, and a 5-field
expression plus an IANA zone yields one UTC instant per tick with no library-dependent reading of `COUNT`,
`UNTIL` or `BYSETPOS`. The cost is real — no "third Tuesday" — and widening the column later is additive, key
unchanged. The residual dependency is tzdata: the expression and the zone are library-free, but the zone → UTC
resolution is not. Every scheduler replica resolves against **one pinned tzdata release**, recorded alongside
`canon_profile`, and a release change is a deployment event — two replicas straddling it would derive two names
for one tick.

**`event` is in the enum and refused by the API.** v0.1 has no metric or observation resource for a predicate to
bind to — OTel semantics are owed, cost measurement is Tier 3 — so the kind is reserved and `POST /v1/tasks`
with `trigger_kind: "event"` is `422 trigger_kind_unsupported`, the pattern `01-schema.md` uses for
`policies.scope = 'project'`. What it would observe is **unknown — OQ**, as is whether a task may carry more
than one trigger; v0.1 allows one.

---

## Idempotent firing

The rule: **a cron tick that is evaluated twice creates one Run.** Omnigent cannot promise that — its scheduler
is "an in-process RRULE scheduler" with no durable claim, so "two server replicas would each arm timers and
double-fire" (`scheduler.py:1-24 @ ba9e371`, OQ-023 in `projects/omnigent/teardown.md`). Letta answers with a
scheduler lease carrying `pid`, `token`, `process_start_ticks` and `boot_id` against PID reuse and reboot
(`cron-file.ts:45-52 @ 852ca24`). We need neither: **the tick has a name**, and a unique key does not care which
process is alive.

```sql
CREATE TYPE firing_outcome AS ENUM ('created', 'skipped', 'missed');
CREATE TYPE firing_reason AS ENUM ('scheduled_time_matched', 'manual_fire', 'webhook_received',
    'overlap', 'task_paused', 'principal_revoked', 'started_too_late', 'scheduler_inactive');
CREATE TABLE task_firings (
    tenant_id      BIGINT NOT NULL,
    task_id        TEXT   NOT NULL,
    firing_key     TEXT   NOT NULL,      -- deterministic and DERIVED; see below
    scheduled_for  TIMESTAMPTZ,          -- the tick instant; NULL for manual/webhook
    outcome        firing_outcome NOT NULL,
    reason         firing_reason NOT NULL,  -- bounded by the type, not by prose; see below
    run_id         TEXT,
    fired_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- THE PRIMITIVE. Recording a firing is an insert; losing the race is a conflict.
    PRIMARY KEY (tenant_id, task_id, firing_key),
    FOREIGN KEY (tenant_id, task_id) REFERENCES tasks (tenant_id, task_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    CHECK ((outcome = 'created') = (run_id IS NOT NULL)),
    CHECK (outcome <> 'missed' OR scheduled_for IS NOT NULL),
    -- a reason belongs to exactly one outcome; ('created','scheduler_inactive') is unstorable
    CONSTRAINT firing_reason_matches_outcome CHECK (
        (outcome = 'created') = (reason IN ('scheduled_time_matched','manual_fire','webhook_received'))
        AND (outcome = 'missed') = (reason IN ('started_too_late','scheduler_inactive')))
);
CREATE INDEX task_firings_recent ON task_firings (tenant_id, task_id, fired_at DESC);
GRANT SELECT, INSERT ON task_firings TO app_role;   -- no UPDATE, no DELETE
```

`firing_key` is **derived**, never a stored raw value, in the shape `01-schema.md` uses for
`effect_ledger.idempotency_key`, and is a registered `kind` in [§03](03-canonicalisation.md)'s domain table with
its own field-inclusion rules there, exactly as `work_bundle` and `knowledge_package` are:

```
firing_key = sha256_hex(canon({ kind: "firing_key", canonicalization: "nfc+intjson/v1",
                                payload: { tenant_id, task_id, source, value } }))
```

`source ∈ {cron, manual, webhook}` is derived from the **path that produced the firing**, never from
`tasks.trigger_kind`: the system scanner is the only producer of `source='cron'`, and `POST /v1/tasks/{id}/fire`
derives `manual`, or `webhook` when the fire arrives through the relay of §Trigger taxonomy. A cron task fired
by hand therefore takes a `manual` key. `value` is the tick instant as RFC 3339 UTC (`2026-08-30T04:30:00Z` for
10:00 `Asia/Kolkata`), derived from the expression and zone alone, or the caller's `Idempotency-Key`. **The
discriminator keeps a caller-supplied key out of the scheduler's namespace** — collapse the two sources into one
raw column and a manual key shaped like a tick instant reads as that tick already decided, silently suppressing
it. The readable instant stays in `scheduled_for`; the insert is the concurrency control, as with effects and
`idempotency_records`:

```sql
INSERT INTO task_firings (tenant_id, task_id, firing_key, scheduled_for, outcome, reason, run_id)
VALUES ($tenant, $task, $key, $tick, 'created', 'scheduled_time_matched', $run)
ON CONFLICT (tenant_id, task_id, firing_key) DO NOTHING
RETURNING run_id;
-- no row => this tick was already decided by another scanner. ROLL BACK the
-- transaction, discarding the `runs` row and the two appends above, then read
-- the existing firing.
```

**The `INSERT INTO runs`, the `run.created` and `run.queued` appends, and the `INSERT INTO task_firings` are one
transaction** (`02-consistency.md` §`runs.state` is a projection, rule 1), so neither half can be committed
alone. The FK on `(tenant_id, run_id)` makes a firing record naming a nonexistent Run a DB error; a
routine-created Run with no firing record is prevented by that transaction and by there being no route that sets
`runs.task_id` (§Who may create) — an enforced code path, not a constraint. `READ COMMITTED` suffices, the
unique key doing the work as for effect intent. **The firing record is a ledger row, not a resource** — no state
machine, no API identity — and like `run_events` it is granted `SELECT, INSERT` and nothing else (the grant is
issued with the `CREATE TABLE` above, on `01-schema.md` §Grants required's pattern; 01 cannot issue it, because
the table is created here), making a decided tick un-re-decidable in the schema, not in code. Whether it should instead
be a resource in Omnigent's `scheduled_task_runs` shape is **unknown — OQ**.

**A firing is performed by §05's system actor** — a timer — on the standing authority in `tasks.created_by`.
§05's transition table is **amended** by this document, 2026-08-30, with one row: trigger *routine firing*,
authorized **system**, covering `— → draft` and `draft → queued` and only inside the transaction that inserts
the `task_firings` row. §05's rule that an actor absent from a row may not trigger it is why this is an
amendment, not an assumption. `runs.created_by` is `tasks.created_by`, so **every Run a routine produces is
attributed to the principal who created the routine**, and is never left in `draft`. If that principal is
revoked (`principals.revoked_at`) the firing is recorded `skipped` / `principal_revoked`: a routine is standing
authority and must not outlive the authority it stands on.

### Reason vocabulary

Bounded by the `firing_reason` type and by `firing_reason_matches_outcome` above — a mechanism, not a promise.
The vocabulary is Letta's nine cron run reasons, the most careful failure-mode enumeration in the study
(`cron-file.ts:26-43 @ 852ca24`), and Omnigent's queryable `error_code` "for future retry logic"
(`db_models.py:1573-1575 @ ba9e371`).

| `reason` | `outcome` | Means |
|---|---|---|
| `scheduled_time_matched` | `created` | a cron tick inside its grace window |
| `manual_fire` | `created` | a person fired it |
| `webhook_received` | `created` | a fire arrived from outside through the relay |
| `overlap` | `skipped` | `overlap_policy='skip'` and a Run of this task is in any **non-terminal** state (`05-state-machine.md` §States: `draft`, `queued`, `running`, `waiting_input`, `cancelling`) — deliberately wider than `01-schema.md`'s `runs_live` partial index, which omits `waiting_input`; the access path is `runs_by_task` |
| `task_paused` | `skipped` | the task left `active` between selection and insert |
| `principal_revoked` | `skipped` | `tasks.created_by` is revoked |
| `started_too_late` | `missed` | the tick was claimed outside `misfire_grace_seconds` |
| `scheduler_inactive` | `missed` | no system scan ran at the tick; recorded on catch-up |

### Missed ticks

1. A tick fires only if it is claimed within `misfire_grace_seconds` of its instant; Omnigent's 30-second
   `MISFIRE_GRACE_TIME_S` is the default (`scheduler.py:1-24 @ ba9e371`).
2. **A tick outside its grace window is never fired late, and there is no backfill of Runs.** Omnigent
   deliberately does not replay fires missed while the server was down, and Letta names `missed` and
   `started_too_late` rather than swallowing them. Firing the 10:00 roll-up at 14:00 produces work whose premise
   has changed, and replaying an outage of ticks is a thundering herd against one tenant.
3. **The record is still written**, so "did the 10:00 tick run?" is a query, not an inference. A scan writes one
   `missed` row per un-recorded tick back to the later of the last recorded firing and `now() - 24 hours`; older
   ticks are neither fired nor enumerated. The horizon is 24 hours because an enumeration window is a **scan
   cost, not a correctness window**: `task_firings` is permanent, so a recorded decision stays recognisable
   forever, and the horizon bounds only how far back a restarting scanner will manufacture `missed` rows for
   ticks nobody was watching.

### One borrowed constraint

`channel_envelopes.task_id` (`17-messaging.md` §The Envelope, as data; the column is declared in
`01-schema.md`) is constrained here because `tasks` is created here and `channel_envelopes` in 01. Added
2026-08-30: an unconstrained cross-resource reference is what non-negotiable 1 forbids, and every other id
column in that table carries its composite FK.

```sql
ALTER TABLE channel_envelopes ADD CONSTRAINT channel_envelopes_task_fk
    FOREIGN KEY (tenant_id, task_id) REFERENCES tasks (tenant_id, task_id);
```

---

## Who may create, pause and disable a routine

Transition authorization, in the form §05 uses. **No transition may be triggered by an actor absent from its
row.**

| From | To | Trigger | Authorized | Notes |
|---|---|---|---|---|
| — | `active` | create task | operator | `created_by` is set here and names the principal every Run will carry; `trigger_kind='event'` ⇒ `422 trigger_kind_unsupported` |
| `active` | `paused` | pause | owner, operator | ticks are recorded, not fired; Runs already created are untouched |
| `paused` | `active` | resume | owner, operator | no catch-up; §Missed ticks applies |
| `active` / `paused` | `disabled` | disable | owner, operator | **terminal** |
| `disabled` | — | — | **nobody** | create a new task |
| any | any | any | **not the system** | v0.1 has no automatic transition on a task |

**owner** is the principal in `tasks.created_by`, **operator** one with tenant-level admin authority; both terms
are §05's. The system actor fires ticks (§Idempotent firing) and never moves a task between states. **Every
write to a task requires an admin credential**: an agent credential may read a task and may not create, pause,
disable or fire one. A routine is *standing authority to create Runs attributed to another principal*, so it
sits on the governor's side of `06-api.md`'s rule that the governed cannot edit the governor — the reasoning
that keeps approvals away from agent credentials (`synthesis/scope-reconciliation.md` §7a, D-A). A fire acts as
`tasks.created_by`, which is why it is admin-only though an ordinary Run is not. **No system transition in
v0.1**: a routine whose Runs fail every night keeps firing, its failures queryable through `runs.error_code` and
work in flight stopped by `POST /v1/runs/{id}/cancel` (`06-api.md` §Runs); auto-pausing after repeated failure
needs a threshold nobody has evidence for, **unknown — OQ**.

Routes are owed to `06-api.md` and `contracts/openapi.yaml`: `POST /v1/tasks`, `PATCH /v1/tasks/{id}`, `POST
/v1/tasks/{id}/{pause,resume,disable,fire}` (admin), and `GET /v1/tasks`, `/v1/tasks/{id}`,
`/v1/tasks/{id}/firings` (admin or agent, read). **`PATCH` may change `name`, `prompt`, `overlap_policy` and
`misfire_grace_seconds` only.** `cron_expression` and `timezone` are **immutable**: the firing key is derived
from them (§Idempotent firing), so an edit would rename ticks in flight and the primary key could not
deduplicate them. Changing a schedule is a new task; `422 schedule_immutable`. `Idempotency-Key` is **required**
on create and on fire, where it becomes the firing key's `value`. A fire whose key already names a
`task_firings` row returns `200` with that firing and its `run_id`, even after the `idempotency_records` row has
expired: the firing table outlives the 24-hour replay window. This is a **deliberate narrowing** of `06-api.md`
§Idempotency for this route only: `task_firings` stores no `request_digest`, so past 24 hours a reused key
cannot be told from a changed body and the firing is replayed rather than refused `422 idempotency_key_reused`.
`POST /v1/tasks/{id}/fire` carries no request body beyond the task it names, which is why the narrowing is safe
here and nowhere else. There is **no route that writes `task_firings` directly** and none that sets a Run's
`task_id`; as in `06-api.md`, the absence of a route is the enforcement.

---

## Delegation between Runs is a ledgered effect

A Run that starts another Run performs a side effect, and `01-schema.md` already names it: `effect_ledger.kind`
is `tool_call | delegation | notify | ...`. The five phases of `02-consistency.md` apply unchanged, with the key
derived as for any other effect from `(tenant_id, run_id, logical_step_path, request_digest)`. Delegation is
**not** carried by messaging: `ag2.network` is Tier 3, and ADR-0003's durable messages are a channel between
agents, not the mechanism by which one Run causes another.

**Dispatch is the platform's `INSERT INTO runs`** — the harness never creates a Run, exactly as it never
executes a tool (spike 06; `spec/07`'s `ToolCall → ledger → ToolResult` boundary). Settlement is `succeeded`
with `result_ref` = the child `run_id`, and it settles when the child Run *exists*, not when it finishes: the
effect lease is five minutes (`02-consistency.md` §3), a child may take an hour, and an effect whose lease
expires unsettled becomes `indeterminate` — uncertainty manufactured about a Run whose state is fully known,
which §05 says is never free.

**The platform increments the depth.** The child's `created_by` is a principal — agents and humans are one type
with a discriminator (ADR-0007), so a delegated Run has an accountable owner exactly as a human-initiated one —
with `kind='agent'`, `on_behalf_of` = the parent Run's `created_by`, and `delegation_depth` that principal's
plus one, "incremented BY US, never by the caller" (`01-schema.md`, `principals`; AG2's hub does the same on the
reply path, `projects/ag2/teardown.md:215`, AG2 @ 90f490a). **The platform inserts that child principal in the
same statement-level transaction as the child `INSERT INTO runs`.** `02-consistency.md` §4 holds no *ledger*
transaction across dispatch — phase 4 is explicitly `(no transaction)`, settlement a separate fenced UPDATE
(§5) — but here the side effect is itself a database write, so the child principal and the child Run commit
together or not at all, and the ledger row settles afterwards under §5's fence. No route creates a principal:
`06-api.md` publishes no principal-write endpoint at all, and as with `running` and `indeterminate` there, the
absence of a route is the enforcement — a caller who could supply a principal could supply a depth. The bound is
`CHECK (delegation_depth BETWEEN 0 AND 8)`, and a delegation that would exceed it settles `failed` with
`error_code = delegation_depth_exceeded` and **creates no Run** — the `CHECK` is the backstop, not the
mechanism, since a constraint violation is not a classified failure and `01-schema.md`'s queryable `error_code`
exists so retry logic can branch on it.

**Delegation is idempotent for free**, the reason to model it as an effect: a resumed parent derives the same
key, finds the row settled, and emits `effect.replayed` (`04-events.md` §Effects), not a second child. **No
`runs.parent_run_id`**: the parent link is the ledger row — `effect_ledger.run_id` is the parent, `result_ref`
the child — where the audit and the idempotency already live, a second link would be a second authority for one
fact, and the child carries no `task_id` because delegation is not a routine.

### What the log records

`run_events` needs a Run for every row (`01-schema.md`) and a task is not a Run, so **there is no task lifecycle
event in the log**; a second log for one resource would be worse than the gap. A firing that creates a Run
appears as that Run's `run.created`, whose payload needs `task_id` and `firing_key` — an owed addition to
`04-events.md`. A skipped or missed firing creates no Run and so no log entry, which is why `task_firings`
carries those outcomes. Who paused a routine is attributable only to the **last** transition (`state_changed_by`
/ `state_changed_at`); a full task audit history is **unknown — OQ**. Delegation needs no new event type:
`effect.claimed` carries `kind`, `effect.succeeded` the `result_ref` holding the child `run_id`.

---

## Tests, with negative controls

Binding form: `spikes/VERIFICATION-RULES.md`, rules 1, 3 and 4 in particular.

| Invariant | Test | Negative control |
|---|---|---|
| A tick evaluated twice creates one Run | run two scanner replicas against one tick, then assert through `GET /v1/tasks/{id}/firings` and `GET /v1/runs?task_id=` that exactly one firing and one Run exist | replace the insert with read-then-act ⇒ two Runs, the shape spike 01 reproduced |
| One tick, one name across replicas | derive the key for a DST-transition tick on two replicas | skew the tzdata release ⇒ two keys, two Runs for one tick |
| A caller-supplied key cannot name a tick | `POST /fire` with `Idempotency-Key: 2026-08-30T04:30:00Z`, then let that tick arrive | collapse the two sources into one raw column ⇒ the manual key suppresses the tick |
| Schedule fields are immutable | `PATCH` `cron_expression` on an active task | allow the edit ⇒ two scanners straddling it create two Runs for one tick |
| A Run and its firing record are atomic | kill the transaction between the two inserts | commit them separately ⇒ a Run no firing record claims |
| A routine Run waiting on a human blocks the next tick | leave a Run in `waiting_input`, let the next tick arrive, read `/v1/tasks/{id}/firings` | scope the check to `runs_live` ⇒ two concurrent Runs of one routine |
| A Run's intent is copied, not referenced | fire a task, edit its prompt via `PATCH`, re-read the Run and its `run.created` | read the prompt through `task_id` ⇒ a completed Run changes what it says it did |
| A tick outside grace never fires late | set the clock past `misfire_grace_seconds`, scan | drop the grace check ⇒ an outage replays as a burst of Runs |
| A missed tick is recorded | stop the system scan across a tick, restart, read `/v1/tasks/{id}/firings` | skip the `missed` row ⇒ "did 10:00 run?" is unanswerable |
| An agent credential cannot create or fire a routine | agent token on `POST /v1/tasks` and `/fire` | drop the class check ⇒ an agent grants itself standing authority |
| A revoked owner stops the routine | revoke `tasks.created_by`, fire | drop the check ⇒ Runs attributed to a revoked principal |
| `disabled` is terminal | resume a disabled task | drop the guard ⇒ a routine returns from the dead |
| A trigger kind with no referent is refused | `POST /v1/tasks` with `trigger_kind: "event"`; assert `422 trigger_kind_unsupported` | accept it ⇒ a routine that can never fire is stored silently |
| An overlap policy with no behaviour is refused | `POST /v1/tasks` with `overlap_policy: "allow"`; assert `422 overlap_policy_unsupported` | accept it ⇒ a stored value nothing implements |
| No route writes a firing or sets `task_id` | enumerate routes against the OpenAPI document | add one ⇒ a caller attributes an arbitrary Run to a routine |
| Delegation depth is platform-set | child request supplies `delegation_depth: 0` | trust the caller ⇒ an unbounded chain past the `CHECK` |
| Delegation replay creates one child | resume the parent across its delegation step | drop the ledger, call the API directly ⇒ a second child Run |

---

## What this does not guarantee

- **Ticks older than 24 hours are not enumerated.** After a longer outage the firing history has a hole, and the
  hole is the only evidence; a summary row for it is **unknown — OQ**.
- **`webhook` is a label, not a mechanism.** A `webhook` fire is an ordinary admin-credentialed `POST
  /v1/tasks/{id}/fire` through a relay we operate; the kind records provenance and nothing more. A real external
  source usually cannot present an admin token; whether the kind earns its own credential and endpoint is
  **unknown — OQ**.
- **No per-firing budget.** Omnigent caps a scheduled task with `max_cost_usd` (`db_models.py:1434 @ ba9e371`)
  and we cannot: cost measurement is Tier 3, so there is no priced usage to charge against, and a runaway
  routine is bounded only by its Runs' deadlines.
- **No digest pin on the routine.** An agent repointed at 09:59 changes what the 10:00 tick runs — the intended
  reading of `06-api.md` §Agents; a routine's behaviour can change without the routine changing. Whether it
  should pin a digest is **unknown — OQ**.
- **Daylight saving is handled by the key, not by intent.** The firing key's `value` is the tick's UTC instant,
  so a repeated local hour yields two keys and two firings and a skipped one yields none — correct against the
  rule, and a surprise to a customer who wrote `0 2 * * *`.
- **`next_fire_at` can be wrong.** It is a projection; a stale value can never *double* a tick, because the
  tick's name comes from the expression and not this column — but neither is the tick merely late. A tick the
  scan misses past `misfire_grace_seconds` is not fired at all; it is recorded `missed` / `scheduler_inactive`
  (§Missed ticks 2).
- **A replayed fire is not digest-checked.** Past the 24-hour idempotency retention, a reused `Idempotency-Key`
  on `/fire` replays the recorded firing rather than refusing `422 idempotency_key_reused`, because
  `task_firings` stores no `request_digest` (§Who may create, pause and disable a routine).
- **One trigger per task.** A nightly-AND-webhook routine is two tasks in v0.1; a second trigger changes the
  `firing_key` derivation, since two triggers can name one instant. **unknown — OQ**.
- **No automatic transition on a task.** A routine whose Runs fail every night keeps firing (§Who may create);
  auto-pause needs a threshold with no evidence behind it. **unknown — OQ**.
- **No Task-level retry.** ADR-0002 records Task-level and Run-level idempotency as different problems; this
  document answers only the firing side. Retrying a failed Run is a new firing with a new key, or a new Run.
