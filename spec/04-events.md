# 04 — Event registry
<!-- status: final -->

The log is the **authority**: run state is derived by folding it. `runs.state` is a
named, rebuildable **projection** of that fold, not a second authority — see
[§02](02-consistency.md#runsstate-is-a-projection-not-a-second-authority) for the
obligations that come with it. An earlier version of this document claimed no parallel
column existed, which contradicted the schema.

---

## Entry shape

```json
{
  "tenant_id": 1,
  "run_id": "01J8...",
  "seq": 42,
  "event_type": "run.tool_call.requested",
  "payload": { },
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "created_at": "2026-08-26T17:35:05.029075Z"
}
```

`seq` is assigned inside the insert (§02). `trace_id` rides the event so a trace can be
reconstructed from the log alone (AG2's contribution).

## Naming rule

`<domain>.<subject>.<past-tense-verb>`

Names are a **closed set added in code, never at runtime** (AG2's rule). A payload may
carry arbitrary user data; the *type* may not be invented by a caller. An unknown
`event_type` on read is an error, not a shrug — see §Forward compatibility.

---

## The registry

### Run lifecycle

| `event_type` | payload | folds to |
|---|---|---|
| `run.created` | `{agent_id, prompt, created_by, pin{...}}` | `state=draft` |
| `run.queued` | `{}` | `state=queued` |
| `run.started` | `{adapter_identity, lease_fence}` | `state=running`, `started_at` |
| `run.progressed` | `{note?}` | `last_activity_at` |
| `run.succeeded` | `{result_ref?}` | `state=succeeded`, `ended_at` |
| `run.failed` | `{error_code, error_detail}` | `state=failed`, `ended_at` |
| `run.expired` | `{deadline}` | `state=expired`, `ended_at` |
| `run.cancel_requested` | `{reason, requested_by}` | `state=cancelling` |
| `run.cancelled` | `{reason}` | `state=cancelled`, `ended_at` |
| `run.discarded` | `{reason}` | `state=discarded`, `ended_at` |
| `run.rewound` | `{to_epoch, from_seq, reason}` | opens a new epoch; see §Rewind |

`run.cancel_requested` and `run.cancelled` are **separate events**, from AG2: a request
is not a fact, and the owner may decline. `state=cancelling` is the honest interval
between them (HumanLayer's `interrupting`).

### Pin and compatibility

| `event_type` | payload | folds to |
|---|---|---|
| `run.incompatible` | `{field, pinned_value, current_value}` | `state=incompatible`, `ended_at` |
| `run.artifact_missing` | `{digest}` | `state=failed`, `error_code=artifact_missing` |
| `run.artifact_corrupted` | `{digest, recomputed}` | `state=failed`, `error_code=artifact_corrupted` |

Three distinct events because the operator remedies differ — restore the prior
definition, restore the artifact, or re-fetch after an integrity incident.

### Effects

| `event_type` | payload |
|---|---|
| `effect.claimed` | `{idempotency_key, kind, request_digest}` |
| `effect.succeeded` | `{idempotency_key, result_ref}` |
| `effect.failed` | `{idempotency_key, error_code}` |
| `effect.replayed` | `{idempotency_key, original_seq}` |
| `effect.indeterminate` | `{idempotency_key, claimed_at}` |

`effect.replayed` records that a duplicate was **recognised and not executed** — the
`accepted: false` signal from Cloudflare, made durable. Without it, a replay is
invisible in the log and looks like nothing happened.

### Human interaction

| `event_type` | payload |
|---|---|
| `approval.requested` | `{approval_id, action_ref, requested_by_rule, request_payload}` |
| `approval.decided` | `{approval_id, status, decided_by, rationale}` |
| `approval.expired` | `{approval_id}` |
| `approval.superseded` | `{approval_id, by}` |

`approval.decided` **must** carry `decided_by` (invariant 8). A writer that omits it
produces an event the reducer rejects.

### Policy

| `event_type` | payload |
|---|---|
| `policy.evaluated` | `{policy_id, phase, decision, enforced, deciding_policies[], latency_ms}` |
| `policy.steered` | `{policy_id, guidance}` |

`enforced: false` is a shadow (`observe`) verdict. It is recorded identically to an
enforced one, which is what makes shadow mode measurable rather than merely
non-blocking.

`deciding_policies` is a list, from Omnigent: on a deny it names the short-circuiting
policy; on an ask it names every policy that asked, in order.

### Adapter

| `event_type` | payload |
|---|---|
| `adapter.frame` | `{kind, data}` — one frame from the stream (§07) |
| `adapter.checkpointed` | `{payload_ref, payload_schema_digest}` |
| `adapter.ended` | `{terminal_state, error?}` |

---

## Folding rules

Deriving state from the log, precisely.

1. **Order is `(tenant_id, run_id, seq)` ascending.** `created_at` is *not* an ordering
   key — clocks are not monotonic and coarse timers produce ties.
2. **Resolve epochs before folding** (see §Rewind). A single backward pass computes the
   live set; the fold then runs forward over it in **`seq` order**. One function owns
   this, following ADK's rule that there is "a single source of truth for which events
   are live".

   `seq` order and `(epoch, seq)` order are the same order, because `seq` is globally
   monotonic per run and `epoch` never restarts it — enforced by the trigger in
   [§01](01-schema.md#epoch--who-may-set-it-and-to-what), not assumed. An earlier draft
   said "global seq order" here and "(epoch, seq) order" below; they agree only because
   monotonicity is enforced, so the enforcement is the load-bearing part.
3. **Unknown `event_type` is an error.** A reducer that skips unknown events silently
   computes a state that never existed. Fail with the type name.
4. **A terminal event ends the fold.** Events after a terminal state are a bug; log
   loudly and stop rather than continuing.
5. **The fold is pure.** Same events in, same state out — no clock, no randomness, no
   I/O. This is what makes it testable and what makes replay meaningful.

---

## Rewind — epochs, not deletion

The naive rule ("drop the rewind event and everything at or after `from_seq`") is wrong:
it also drops every event appended *after* the rewind, so a run could rewind but never
continue. That was a real defect in the first version of this document.

**Every event carries an `epoch`**, stored in `run_events.epoch` and assigned by the
database, never by the caller (§01, §02). A run starts at epoch 0. `run.rewound{to_epoch,
from_seq}` opens epoch *n+1* and declares that events in epochs ≤ `to_epoch` with
`seq >= from_seq` are **superseded**.

```
epoch 0:  seq 1  2  3  4  5          <- 4 and 5 superseded by the rewind
                       └──────── run.rewound{to_epoch:0, from_seq:4}  (seq 6, epoch 1)
epoch 1:  seq 7  8  9                <- the new branch, live
```

### The algorithm, normatively

```
live(events):
    # 1. collect supersession ranges, newest epoch first
    cuts = [(e.payload.to_epoch, e.payload.from_seq)
            for e in events if e.event_type == 'run.rewound']

    # 2. an event is live unless some cut supersedes it
    return [e for e in events
            if e.event_type != 'run.rewound'
            and not any(e.epoch <= to_epoch and e.seq >= from_seq
                        for (to_epoch, from_seq) in cuts)]
```

Then fold `live(events)` in **`seq` order**, which is identical to `(epoch, seq)` order
because `seq` is globally monotonic per run (§01 enforces this with a trigger). If
monotonicity were merely conventional, sorting by `(epoch, seq)` could *reorder history*
— which is why it is a constraint and not a convention.

Three properties this gives, all of which the naive rule lacked:

- **Continuation works** — events after the rewind are in a later epoch and survive.
- **Rewinds compose** — a rewind of a rewind is just another cut.
- **Nothing is deleted** — `run_events` stays append-only, so the full history is
  auditable even where it is not live. A superseded event is still evidence of what was
  attempted.

`seq` remains globally monotonic per run across epochs; `epoch` only partitions it.

### What the store guarantees, so the algorithm can be simple

The algorithm above is only sound because the persistence protocol cannot produce an
invalid history. §01 enforces, in the database:

| Rule | Mechanism |
|---|---|
| an ordinary event carries exactly `runs.current_epoch` | trigger; and §02's insert reads it from `runs` rather than accepting a parameter |
| only `run.rewound` changes the epoch, and only to `current_epoch + 1` | trigger |
| `to_epoch` cannot name an epoch that does not exist yet | trigger |
| epoch assignment is atomic under concurrency | `SELECT ... FOR UPDATE` on the `runs` row |
| `seq` strictly increases per run | primary key + trigger |
| epochs are dense | `+ 1` only |

Without these, `live()` is a function over histories that the store is free to violate.

---

## Forward compatibility

Adding an event type is a code change plus a migration entry in the registry table.
Reading an unknown type is an error by rule 3, which means **a reader must not be older
than a writer**. Deployment order is therefore: readers first, then writers.

That is a real operational constraint and it is stated here rather than discovered
during a rollout.

---

## Tests, with negative controls

| Invariant | Test | Negative control |
|---|---|---|
| Fold is deterministic | same log ⇒ same state, 100 runs | introduce `now()` into the fold ⇒ flaky |
| Ordering is by `seq`, not time | shuffle `created_at`, keep `seq` | order by `created_at` ⇒ wrong state |
| Rewind supersedes the right range | rewind mid-log, assert the live set | skip epoch handling ⇒ superseded events reappear |
| **A run can continue after a rewind** | rewind, append, fold | use the naive `seq >=` rule ⇒ post-rewind events vanish |
| Rewinds compose | rewind a rewind | handle only the last cut ⇒ wrong live set |
| Unknown type fails loudly | inject `run.invented` | skip unknowns ⇒ silently wrong state |
| `approval.decided` requires `decided_by` | omit it | drop the check ⇒ an anonymous approval |
| Post-terminal events are rejected | append after `run.succeeded` | allow them ⇒ a resurrected run |
