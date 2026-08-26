# 05 — Run state machine and transition authorization
<!-- status: final -->

`domain-model.md` gave the edges. This gives **who may trigger each one**, which is the
part that blocks an implementer: an edge without an authorized actor is an invitation to
let anyone call it.

---

## States

```
        draft ──────────────────────────────► discarded
          │
          ▼
       queued ──► running ──────────────────► succeeded
                    │  ▲                      failed
                    │  └── (resume, leased) ── expired
                    ├──► waiting_input ──┘
                    ├──► cancelling ─────────► cancelled
                    ├──► indeterminate
                    └──► incompatible
```

| State | Meaning | Terminal |
|---|---|---|
| `draft` | composed, not started | no |
| `queued` | admitted, awaiting a worker | no |
| `running` | a worker holds the lease | no |
| `waiting_input` | blocked on a human — **indexed**, so "what needs attention" is a query | no |
| `cancelling` | cancel requested, shutdown in progress | no |
| `succeeded` / `failed` / `expired` / `cancelled` | ordinary terminals | **yes** |
| `indeterminate` | an effect was dispatched, outcome unknown | **yes** |
| `incompatible` | pin mismatch on resume | **yes** |
| `discarded` | abandoned before starting | **yes** |

`cancelling` exists because cancellation takes time, and a machine that pretends
otherwise reports a lie during the gap (HumanLayer's `interrupting`/`interrupted` is the
only precedent in 13 projects).

`indeterminate` is terminal **on purpose**. It is not a retry state — it is a state that
requires a human, because retrying an effect we may already have performed is the
double-charge bug the ledger exists to prevent.

---

## Actors

| Actor | Is |
|---|---|
| **owner** | the principal in `runs.created_by` |
| **operator** | a principal with tenant-level admin authority |
| **worker** | the platform component holding a valid, unfenced lease |
| **system** | a sweeper or timer; no principal |
| **adapter** | the agent process, via the southbound stream |

An **agent** principal may be an owner. That is the point of ADR-0007: agents and humans
are the same type with a discriminator, so an agent-initiated run has an accountable
owner exactly as a human-initiated one does.

---

## Transition table

**No transition may be triggered by an actor absent from its row.** This table is the
authorization spec; the API in §06 enforces it.

| From | To | Trigger | Authorized | Notes |
|---|---|---|---|---|
| — | `draft` | create run | owner, operator | pin computed and recorded here |
| `draft` | `queued` | submit | owner, operator | |
| `draft` | `discarded` | discard | owner, operator | |
| `queued` | `running` | claim | **worker only** | requires winning the lease |
| `queued` | `discarded` | discard | owner, operator | only while unclaimed |
| `running` | `waiting_input` | request approval | worker, adapter | |
| `waiting_input` | `running` | approval decided | **worker only** | after `approval.decided`; the *human* decides the approval, the *worker* resumes the run |
| `running` | `succeeded` / `failed` | adapter terminates | worker | must carry `error_code` on failure |
| `running` | `cancelling` | request cancel | owner, operator | a **request**, not a fact |
| `waiting_input` | `cancelling` | request cancel | owner, operator | |
| `cancelling` | `cancelled` | adapter acknowledges | worker, system | system on lease expiry |
| `running` | `expired` | deadline passes | **system only** | |
| `running` | `indeterminate` | effect claim expires unsettled | **system only** | never a retry |
| `queued`/`running` | `incompatible` | pin mismatch on resume | **worker only** | before any adapter call |
| any terminal | — | — | **nobody** | terminal is terminal |

### Three deliberate asymmetries

**Only a worker may enter `running`.** Not the owner, not an operator. Entering
`running` means holding the lease, and the lease is what prevents duplicate execution
— so the transition and the lease acquisition are the same act.

**Only the system may set `expired` or `indeterminate`.** Both are consequences of time
passing, not of anyone's request. Exposing them to an API caller would let a client
declare an effect indeterminate, which is a way to skip a safety check.

**A human decides an approval; a worker resumes the run.** `waiting_input → running` is
worker-only even though a *human* made the decision. The decision is recorded as
`approval.decided`; the resumption is a separate, leased act. Conflating them is how you
get two workers resuming on one approval.

---

## Preconditions, enforced

Beyond the actor, each transition has conditions that must be checked **inside the same
transaction** as the state change.

| Transition | Precondition |
|---|---|
| `queued → running` | lease acquired **and** pin matched **and** artifact resolved and verified |
| `waiting_input → running` | a matching `approvals` row is terminal with `decided_by` set |
| `cancelling → cancelled` | no `effect_ledger` row for this run is still `claimed`, **or** the lease has expired |
| `* → succeeded` | no `effect_ledger` row for this run is `claimed` — an unsettled effect means the run is not done |
| `* → any terminal` | `ended_at` set in the same statement (schema `CHECK` enforces) |
| `* → failed` | `error_code` non-null (schema `CHECK` enforces) |

The `succeeded` precondition is easy to miss and it matters: a run that reports success
while an effect is still claimed has an outcome nobody knows.

---

## Ordering guarantee for resume

Normative, and proven in spike 02:

```
1. load run + pin
2. resolve the artifact from the registry BY DIGEST   → ArtifactMissing
3. verify the artifact hashes to its own key          → ArtifactCorrupted
4. compare the pin, field by field                    → Incompatible (names the field)
5. acquire the fenced lease                           → ConcurrentResume
6. THEN invoke the adapter, passing the RESOLVED artifact
```

**No adapter method may be invoked before step 6.** Spike 02 tests this with a tripwire
adapter that raises if touched, and asserts `calls == []` on every failure path. That
test is required in the implementation, not optional.

Step 6 passes the **resolved** artifact, not the caller's object. That is what closes
the check/use gap: the thing that executes is the thing whose digest was checked.

---

## Tests, with negative controls

| Invariant | Test | Negative control |
|---|---|---|
| Only a worker enters `running` | owner attempts it via API | drop the actor check ⇒ succeeds |
| Only the system sets `indeterminate` | operator attempts it | drop the check ⇒ a client can skip a safety gate |
| Terminal states are final | attempt any transition from `succeeded` | drop the guard ⇒ a resurrected run |
| `succeeded` requires no claimed effects | leave one claimed, try to finish | drop the precondition ⇒ silent unknown outcome |
| Resume order holds | tripwire adapter, all four failure paths | reorder to lease-before-pin ⇒ adapter runs on a mismatch |
| `cancelling` is observable | request cancel, read state before ack | collapse to `cancelled` ⇒ the state lies during shutdown |
