# 04 — Event registry
<!-- status: final -->

The log is the source of truth: run state is **derived by folding it**, never stored in
a parallel column that can drift (Google AX). That makes the event schema a contract,
not an implementation detail.

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
| `run.rewound` | `{before_seq, reason}` | see below |

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
2. **Apply rewinds first.** For each `run.rewound{before_seq}`, drop that event and
   every event with `seq >= before_seq`, then continue. ADK's rule: one function is
   "the single source of truth for which events are live".
3. **Unknown `event_type` is an error.** A reducer that skips unknown events silently
   computes a state that never existed. Fail with the type name.
4. **A terminal event ends the fold.** Events after a terminal state are a bug; log
   loudly and stop rather than continuing.
5. **The fold is pure.** Same events in, same state out — no clock, no randomness, no
   I/O. This is what makes it testable and what makes replay meaningful.

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
| Rewind drops the right range | rewind mid-log, assert live set | skip rewind handling ⇒ dropped events reappear |
| Unknown type fails loudly | inject `run.invented` | skip unknowns ⇒ silently wrong state |
| `approval.decided` requires `decided_by` | omit it | drop the check ⇒ an anonymous approval |
| Post-terminal events are rejected | append after `run.succeeded` | allow them ⇒ a resurrected run |
