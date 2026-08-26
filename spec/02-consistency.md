# 02 — Database, consistency, and leases
<!-- status: final -->

Settles the questions the spikes surfaced but did not answer: isolation levels,
transaction boundaries, lease expiry, and whether one hub per channel is an enforced
invariant.

---

## Database

**PostgreSQL 16+.** Not negotiable for v0.1, for three specific reasons rather than
preference:

1. **Composite foreign keys** — the tenancy invariant (Agent Control's mechanism)
   requires them; not all engines enforce them well.
2. **`INSERT ... ON CONFLICT DO NOTHING` with `rowcount`** — the atomic-claim
   primitive proven in both spikes.
3. **Partial indexes** — `WHERE state = 'waiting_input'` keeps the hot "needs a human"
   query cheap forever (HumanLayer).

The spikes used SQLite. The translation is mechanical, and the one behavioural
difference that matters is called out below.

### SQLite → Postgres translation

| Spike (SQLite) | Production (Postgres) |
|---|---|
| `INSERT OR IGNORE ...` then `cur.rowcount == 1` | `INSERT ... ON CONFLICT DO NOTHING RETURNING 1` then row present |
| `PRAGMA journal_mode=WAL` | default MVCC |
| implicit serialisation (one writer) | explicit isolation, below |

**`rowcount` is not portable.** Postgres must use `RETURNING` and check whether a row
came back — `rowcount` after `ON CONFLICT DO NOTHING` is 0 in both the "lost the race"
and "already completed" cases, which are different situations.

---

## Isolation levels, per operation

Default `READ COMMITTED`. Three operations need more, and each is named rather than
left to a global setting.

| Operation | Isolation | Why |
|---|---|---|
| Append a run event | `READ COMMITTED` | The primary key does the work; see below |
| Claim an effect | `READ COMMITTED` | The unique index does the work |
| Acquire a run lease | `READ COMMITTED` | Same |
| **Fold the log to derive state** | `REPEATABLE READ` | A fold that sees events appended mid-read produces a state that never existed |
| **Resume (validate → lease → execute)** | `REPEATABLE READ` | The pin must be read consistently with the artifact it names |
| **Sweep expired leases** | `SERIALIZABLE` | Reclaiming a lease races other reclaimers; the conflict must be detected |

The general rule: **where a unique constraint provides the guarantee, weak isolation
is correct and cheaper.** Where a *decision* is made from multiple reads, the reads
must be consistent.

---

## Sequence assignment — single writer without a lock service

The Google AX pattern, translated. `seq` is computed **inside the insert**:

```sql
INSERT INTO run_events (tenant_id, run_id, seq, event_type, payload, trace_id)
SELECT $1, $2, COALESCE(MAX(seq), 0) + 1, $3, $4, $5
  FROM run_events WHERE tenant_id = $1 AND run_id = $2
RETURNING seq;
```

Two concurrent appends compute the same `MAX(seq)+1`, both attempt the same primary
key, and **one gets a unique violation and rolls back**. The loser retries. There is
no lock service and no advisory lock.

The caller must treat `23505` (unique violation) on this statement as *retryable*, and
anything else as fatal. That distinction belongs in one place; see §Error mapping.

---

## Transaction boundaries

Stated as explicit units, because "it's all transactional" is how half-applied
mutations happen.

### Appending an event with a state change

```
BEGIN
  INSERT INTO run_events (...) -- with the seq computation above
  UPDATE runs SET state = $new, last_activity_at = now() WHERE ...
COMMIT
```

One transaction. A state that disagrees with the log is not a recoverable condition,
so it must be impossible rather than repaired.

### Claiming and performing an effect — three transactions, deliberately

```
TX1:  claim         INSERT INTO effect_ledger (... status='claimed',
                    lease_expires_at = now() + interval '5 minutes')
                    ON CONFLICT DO NOTHING RETURNING 1
      -- no row returned => someone else owns it. STOP. Do not execute.

(no transaction)    perform the side effect        <-- outside any transaction

TX2:  settle        UPDATE effect_ledger SET status='succeeded'|'failed',
                    completed_at = now(), result_ref = $x
                    WHERE tenant_id=$1 AND idempotency_key=$2
```

**The effect must not run inside a transaction.** Holding a transaction open across a
network call to a third party is how a database gets a lock held for a 30-second
timeout. The gap between TX1 and TX2 is precisely the `indeterminate` window, and it
is why that state exists.

### Resume — validate, then lease, then execute

```
TX1 (REPEATABLE READ):
  SELECT pin, state FROM runs WHERE ...
  SELECT body FROM agent_definitions WHERE digest = pin.definition_digest
  -- verify body hashes to its own key        -> ArtifactCorrupted
  -- compare pin                              -> IncompatibleCheckpoint
  INSERT INTO run_leases (...) ON CONFLICT DO NOTHING RETURNING fence_token
  -- no row                                   -> ConcurrentResume
COMMIT

(no transaction)   invoke the adapter with the RESOLVED body
```

Order is the contract, and it is the order spike 02 proved: **no adapter method is
invoked until all four checks have passed.**

---

## Leases — fenced, not merely timed

A TTL alone is insufficient. The failure: a holder pauses (GC, VM migration, a long
syscall), its lease expires, another worker acquires it, then the original wakes and
writes — believing it still owns the run. This is the classic fencing problem, and it
is the gap spike 02 left open.

### Acquire

```sql
-- fence tokens are monotonic per run
INSERT INTO run_leases (tenant_id, run_id, holder, fence_token, expires_at)
VALUES ($1, $2, $3,
        (SELECT COALESCE(MAX(fence_token), 0) + 1
           FROM run_leases_history WHERE tenant_id=$1 AND run_id=$2),
        now() + $ttl)
ON CONFLICT (tenant_id, run_id) DO NOTHING
RETURNING fence_token;
```

### Every subsequent write carries the token

```sql
UPDATE runs SET state = $new
 WHERE tenant_id = $1 AND run_id = $2
   AND EXISTS (SELECT 1 FROM run_leases
                WHERE tenant_id=$1 AND run_id=$2
                  AND holder=$3 AND fence_token=$4);
```

Zero rows updated means **the caller has been fenced out** — its lease was reclaimed.
It must abandon the run, not retry. A worker that ignores this is the duplicate
execution the lease exists to prevent.

### Reclaim

```sql
BEGIN ISOLATION LEVEL SERIALIZABLE;
  DELETE FROM run_leases
   WHERE tenant_id=$1 AND run_id=$2 AND expires_at < now()
  RETURNING holder, fence_token;      -- record to history for monotonicity
COMMIT;
```

TTL defaults: **run lease 60s with renewal every 20s**; **effect claim 5 min, no
renewal**. An effect claim is short-lived by design — if it expires, the effect is
`indeterminate`, which is a decision requiring a human, not a lease to extend.

### Reclaim does not mean retry

An expired *effect* claim moves to `indeterminate` and **surfaces**. This is invariant
2's uncomfortable half: we dispatched an effect and never learned the outcome, so
retrying risks the double-charge the ledger exists to prevent.

```sql
UPDATE effect_ledger SET status = 'indeterminate'
 WHERE tenant_id=$1 AND status='claimed' AND lease_expires_at < now();
```

---

## One hub per channel: **yes, enforced**

The question spike 01 deferred. AG2's `Hub` keeps passports, rules, channel state,
adapter folds and indexes **in process memory**, and a database-backed WAL does not
make an in-memory authority horizontally safe.

**Decision: exactly one hub instance may serve a channel at a time, enforced by a
lease on the same mechanism as runs.**

```sql
CREATE TABLE channel_leases (
    tenant_id   BIGINT NOT NULL,
    channel_id  TEXT   NOT NULL,
    hub_id      TEXT   NOT NULL,
    fence_token BIGINT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, channel_id)
);
```

A hub must hold the channel lease before calling `post_envelope`. This is a
restriction on *our* usage of AG2, not a change to AG2 — consistent with spike 01's
finding that we integrate by composition.

**What this buys:** AG2's in-memory folds are correct because only one process folds
a given channel. **What it costs:** channel throughput is bounded by one process, and
a hub failure blocks its channels until the lease expires. Accepted for v0.1;
sharding channels across hubs is the scaling path.

---

## Error mapping

One table, so retry logic lives in one place rather than in every call site.

| Postgres | Meaning | Caller action |
|---|---|---|
| `23505` on `run_events` | lost the seq race | **retry** (bounded, jittered) |
| `23505` on `effect_ledger` | someone else claimed it | **do not execute**; read the existing row |
| `23505` on `run_leases` | another worker resumed | raise `ConcurrentResume`; do not retry |
| `23503` foreign key | cross-tenant or missing reference | **bug** — fail loudly, do not retry |
| `23514` check violation | invariant breach (e.g. `temp:` write) | **bug** — fail loudly |
| `40001` serialisation failure | sweeper conflict | retry with backoff |
| `57014` statement timeout | contention or a slow query | retry once, then surface |

**`23503` and `23514` are never retried.** They mean the code attempted something the
schema forbids, and retrying converts a clear bug into an intermittent one.

Retry policy, following Cloudflare: full jitter, 3 attempts, 100 ms base, 3 s cap —
and **overload conditions are excluded from retry**, because retrying a database that
is shedding load makes it worse.

---

## What must be tested, with negative controls

Per [`../spikes/VERIFICATION-RULES.md`](../spikes/VERIFICATION-RULES.md), each of
these needs a test through the public boundary *and* a control proving the test fails
when the guard is removed.

| Invariant | Test | Negative control |
|---|---|---|
| Concurrent appends do not duplicate `seq` | N writers, one run, assert `seq` set is `1..N` | remove the PK ⇒ duplicates appear |
| An effect executes at most once | N claimers, count executions | stub the claim to always succeed ⇒ N executions |
| A fenced worker cannot write | expire lease, reacquire elsewhere, old holder writes | drop the `EXISTS` clause ⇒ write succeeds |
| An expired claim becomes `indeterminate`, not retried | advance clock, run sweeper | make the sweeper retry ⇒ double execution |
| A `temp:` write is rejected | insert `temp:x` | drop the `CHECK` ⇒ it persists |
| Cross-tenant FK is impossible | reference another tenant's row | drop the composite FK ⇒ it succeeds |
| An approval cannot be terminal without an approver | update to `approved` with `decided_by = NULL` | drop the `CHECK` ⇒ it succeeds |
| One hub per channel | two hubs, same channel | remove the channel lease ⇒ both post |
