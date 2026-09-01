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
  "epoch": 0,
  "event_type": "run.tool_call.requested",
  "payload": { },
  "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
  "created_at": "2026-08-26T17:35:05.029075Z"
}
```

*(Amended 2026-08-27: this entry showed `trace_id` and no `epoch`. `traceparent` replaced the
bare id because propagation needs the parent span and sampled flag, and `epoch` was added with
the rewind model.)*

`seq` and `epoch` are both assigned **inside the insert** (§02); a caller supplies
neither. `traceparent` is the full W3C header value, not a bare trace id — the parent span
and sampled flag are what make propagation work — and it rides the event so a trace can be
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
| `run.created` | `{agent_id, prompt, created_by, pin{...}, task_id?, firing_key?}` | `state=draft` |
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

`task_id` and `firing_key` are present on `run.created` exactly when the Run was created by
a routine firing ([`11-routines.md`](11-routines.md) §Idempotent firing), and absent
otherwise — absent, never `null`.

### Pin and compatibility

| `event_type` | payload | folds to |
|---|---|---|
| `run.incompatible` | `{field, pinned_value, current_value}` | `state=incompatible`, `ended_at` |
| `run.artifact_missing` | `{digest}` | `state=failed`, `error_code=artifact_missing` |
| `run.artifact_corrupted` | `{digest, recomputed}` | `state=failed`, `error_code=artifact_corrupted` |
| `run.knowledge_missing` | `{digest}` | `state=failed`, `error_code=knowledge_missing` |
| `run.knowledge_corrupted` | `{digest, path, recomputed}` | `state=failed`, `error_code=knowledge_corrupted` |

Five distinct events because the operator remedies differ — restore the prior
definition, restore the artifact, re-fetch after an integrity incident, recompile and
re-register the knowledge package, or re-materialise the mount and investigate it
([`16-knowledge.md`](16-knowledge.md) §Materialisation).

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

### Credentials

| `event_type` | payload |
|---|---|
| `credential.exchanged` | `{credential_id, issuance_id, flow, subject_principal_id, delegation_depth}` |
| `credential.refreshed` | `{credential_id, issuance_id, refresh_count}` |
| `credential.placeholder_rejected` | `{placeholder_prefix, host, reason}` |

Three types and not one, because the operator remedies differ: re-exchange, re-refresh, or
investigate a placeholder presented where it was not minted to be used
([`14-credentials.md`](14-credentials.md)). All three are **run-scoped**, so they fit
`run_events`' foreign key. Credential *creation* and *revocation* have no run and therefore
have no home here; **amended 2026-08-30 (OQ-078): they are `admin_events` rows**
(`action = 'credential.created' | 'credential.revoked'`, [§01](01-schema.md) §Admin audit),
a tenant-scoped log parallel to this one for exactly the writes that have no run to attach to
— routine pause/resume/disable (`action = 'task.paused'` etc., [§11](11-routines.md)) and the
missed-tick summary (`action = 'task.catchup_skipped'`, `detail = {from, to, count}`,
[§11](11-routines.md) §Missed ticks) land there too, never as `run_events` rows. No payload
names `secret_ref`, `material_ref`, or a placeholder's value — only its prefix, which is what
makes the rejection diagnosable without making the log a place to find secrets.

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
| `adapter.frame` | `{kind, data}` — one frame from the stream (§07). `data` excludes `Start.run_token`, which is minted per spawn and is never an input to the fold ([`13-adapter-sdk-subprocess.md`](13-adapter-sdk-subprocess.md) §3) |
| `adapter.checkpointed` | `{payload_ref, payload_schema_digest}` |
| `adapter.ended` | `{terminal_state, error?}` |

### Cost

| `event_type` | payload |
|---|---|
| `cost.snapshot.pinned` | `{price_snapshot_digest, source, source_version, fence_token}` |
| `cost.usage.recorded` | `{fence_token, step_id, provider, model_ref, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, requests}` |
| `cost.usage.priced` | `{usage_seq, price_snapshot_digest, amount_nanos, currency}` |
| `cost.usage.unpriced` | `{usage_seq, price_snapshot_digest?, unpriced_reason}` |

Usage and price are separate events because usage is a fact the harness observed and a
price is a judgement made against a dataset that changes — the same split as
`run.cancel_requested` / `run.cancelled`. Exactly one of `cost.usage.priced` /
`cost.usage.unpriced` follows each `cost.usage.recorded`, in the same transaction.
`snapshot_unresolved` is the only `unpriced_reason` that carries no digest, because there
is none to carry. All money in a payload is an integer ([§03](03-canonicalisation.md)
rejects non-integral floats), and no cost event folds onto `runs.state`
([`18-cost.md`](18-cost.md)).

### Sandbox

| `event_type` | payload | folds to |
|---|---|---|
| `sandbox.created` | `{sandbox_id, provider, target}` | — |
| `sandbox.suspended` | `{sandbox_id, reason}` | — |
| `sandbox.resumed` | `{sandbox_id, from_sandbox_id}` | — |
| `sandbox.destroyed` | `{sandbox_id}` | — |
| `sandbox.lost` | `{sandbox_id, provider_detail}` | — |

Every sandbox event folds to **nothing** in run state ([`15-sandbox.md`](15-sandbox.md) §2).
A folding rule here would make run state depend on sandbox identity, which is the dependency
ADR-0016 forbids: a resumed sandbox is not a resumed run.

### Messaging

| `event_type` | payload |
|---|---|
| `message.refused` | `{code}` |

**Amended 2026-08-30 (OQ-125).** `code` is one of the nine refusals
[`17-messaging.md`](17-messaging.md) §Public surface names (`channel_lease_not_held`,
`channel_closed`, `unknown_channel`, `channel_exists`, `stamped_field_supplied`,
`expectation_violated`, `depth_exceeded`, `unknown_event_type`, `not_a_member`), appended
when the refused `post` names a `run_id` — the only case `run_events`' foreign key admits.

### State

| `event_type` | payload |
|---|---|
| `state.written` | `{scope, scope_key, key, value_digest}` |
| `state.deleted` | `{scope, scope_key, key}` |

Neither folds onto `runs.state`, and the payload carries the value's **digest**, not the
value — the `state_entries` row is the value ([`16-knowledge.md`](16-knowledge.md) §State).

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
