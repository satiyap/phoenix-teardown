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
| — → `draft`, `draft` → `queued` | | **routine firing** | **system** | amended 2026-08-30 by [`11-routines.md`](11-routines.md): only inside the transaction that inserts the `task_firings` row; `runs.created_by` is `tasks.created_by` |
| `draft` | `discarded` | discard | owner, operator | |
| `queued` | `running` | claim | **worker only** | requires winning the lease |
| `queued` | `discarded` | discard | owner, operator | only while unclaimed |
| `running` | `waiting_input` | request approval | worker, adapter | |
| `waiting_input` | `running` | approval **approved** | **worker only** | the *human* decides, the *worker* resumes |
| `waiting_input` | `running` | approval **denied** | **worker only** | resumes carrying a **denial result**; see below |
| `waiting_input` | `failed` | approval denied **and** the adapter cannot proceed | worker | `error_code = approval_denied` |
| `waiting_input` | `failed` | approval **expired** | system | `error_code = approval_expired` |
| `waiting_input` | `waiting_input` | approval **superseded** | worker | a new approval replaces it; still blocked |
| `running` | `succeeded` / `failed` | adapter terminates | worker | must carry `error_code` on failure |
| `running` | `cancelling` | request cancel | owner, operator | a **request**, not a fact |
| `waiting_input` | `cancelling` | request cancel | owner, operator | |
| `cancelling` | `cancelled` | adapter acknowledges | worker, system | system on lease expiry |
| `running` | `expired` | deadline passes | **system only** | |
| `running` | `indeterminate` | **an effect claim for this run is unsettled** and the adapter is gone | **system only** | never a retry; see below |
| `running` | `failed` | adapter stream closed abnormally with **no unsettled effect** | worker, system | `error_code = adapter_disconnected` |
| `queued`/`running` | `incompatible` | pin mismatch on resume | **worker only** | before any adapter call |
| `queued` | `failed` | a **resume-ladder** rung fails, or the spawn does | worker, system | amended 2026-09-04: the ladder below runs BEFORE any adapter call, so every failure it reports lands on a run that is still `queued` — artifact missing or corrupted, knowledge package missing or corrupted, and the worker failing to start the process at all. The rows were missing, not the behaviour: the failures were always written, and nothing consulted this table, so the undeclared edge went unnoticed until the event log's append path began enforcing it |
| `cancelling` | `indeterminate` | an effect claim is unsettled and the adapter is gone | **system only** | amended 2026-09-04: a run cancelled with an effect still claimed is not `cancelled` — what happened out in the world is unknown, and claiming either outcome is a claim nobody can support. Without this row, enforcing the table stranded exactly the runs cancellation was built to release |
| any terminal | — | — | **nobody** | terminal is terminal |

**Enforcement, amended 2026-09-04.** This table is the authorization spec, and §06 enforces
it on the API — but the API is not the only writer. `runs.state` is a projection of the
event log, rebuilt by the fold on every append, and that path consulted no table at all: it
wrote whatever the events implied. So an edge with no row here was reachable in practice,
and one was taken routinely — a run in `cancelling` whose adapter failed was moved to
`failed`, which this table has never permitted. The append path now refuses a state change
with no row. Reads stay permissive: refusing to *fold* a historical log would turn a bad
write in the past into a run nobody can look at, which is worse than the bad write.

### Three deliberate asymmetries

**Only a worker may enter `running`.** Not the owner, not an operator. Entering
`running` means holding the lease, and the lease is what prevents duplicate execution
— so the transition and the lease acquisition are the same act.

**Indeterminacy is about unresolved *effects*, not about an abnormal *stream close*.**
§07 says a stream that closes without `End` makes the run indeterminate. That is too
broad: if the adapter died before claiming any effect, nothing external happened and we
know it. The rule is therefore:

```
adapter gone, and some effect_ledger row for this run is still 'claimed'
    -> indeterminate      (we may have caused something; a human must look)

adapter gone, and no effect for this run is unsettled
    -> failed, error_code = adapter_disconnected   (we know nothing happened)
```

Manufacturing uncertainty is not free — every `indeterminate` run costs human attention,
so the state must be reserved for cases where uncertainty is real.

**Only the system may set `expired` or `indeterminate`.** Both are consequences of time
passing, not of anyone's request. Exposing them to an API caller would let a client
declare an effect indeterminate, which is a way to skip a safety check.

**Denial resumes the run; it does not fail it.** A denied approval is an *answer*, and the
adapter is entitled to receive it and decide what to do — retry differently, take a
compliant path, or give up. So `waiting_input → running` accepts a denial, and the worker
sends the adapter a **`ToolDenied{call_id, reason: APPROVAL_DENIED, guidance}`** control
frame (§07).

`ToolDenied` is a distinct frame rather than `ToolResult{ok:false}` because "an approver
refused" and "the tool errored" call for different adapter behaviour, and an earlier draft
of this section named a frame the protocol could not carry at all — `ControlFrame` had only
opaque `Input`.

The run only reaches `failed` if the adapter then terminates, with
`error_code = approval_denied`. Treating denial as an automatic run failure would be
wrong twice over: it discards the adapter's ability to adapt, and it makes "the human said
no" indistinguishable from "the tool crashed".

Expiry and supersession are different again: expiry is a **system** transition to `failed`
(nobody answered), and supersession leaves the run in `waiting_input` because a *new*
question is now outstanding.

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
| `waiting_input → running` | a matching `approvals` row is terminal (`approved` **or** `denied`) with `decided_by` set |
| `cancelling → cancelled` | no `effect_ledger` row for this run is still `claimed`, **or** the lease has expired |
| `* → succeeded` | no `effect_ledger` row for this run is `claimed` **or `indeterminate`** — an unsettled **or uncertain** effect means the run is not done (amended 2026-08-30: [`10-work-bundles.md`](10-work-bundles.md) §Settlement moves a timeout or lost-contact effect out of `claimed` into `indeterminate`, so excluding `claimed` alone let a run succeed carrying an outcome nobody knows) |
| `* → any terminal` | `ended_at` set in the same statement (schema `CHECK` enforces) |
| `* → failed` | `error_code` non-null (schema `CHECK` enforces) |

The `succeeded` precondition is easy to miss and it matters: a run that reports success
while an effect is still claimed — or has settled `indeterminate` — has an outcome nobody
knows. `indeterminate` is not a resolution; it is the platform recording that it cannot
tell, and a run must not report success over it.

---

## Ordering guarantee for resume

Normative, and proven in spike 02:

```
1. load run + pin
2. resolve the artifact from the registry BY DIGEST   → ArtifactMissing
3. verify the artifact hashes to its own key          → ArtifactCorrupted
4. compare the pin, field by field: definition, adapter, payload schema,
   the bundle digest where the run pins one (10), and the knowledge
   package digest THROUGH the definition body (16)    → Incompatible (names the field)
4b. verify the materialised knowledge tree against manifest.json in
   both directions, before any process exists (16)    → KnowledgeMissing | KnowledgeCorrupted
5. (future) check the digest against revoked_definitions → DefinitionRevoked
6. acquire the fenced lease                           → ConcurrentResume
7. THEN invoke the adapter, passing the RESOLVED artifact
```

**The comparison in step 4 is against `run.pinned_definition_digest`, never against
`agent.current_digest`.** Repointing an agent does not block an in-flight run: the pin is a
statement about the artifact *this run executes*, and that artifact is still verified on
every resume. Blocking in-flight work is a separate, audited revocation (step 5), which
**v0.1 does not ship** — see [§09](09-decisions.md) 2. Until it does, the way to stop a run
is to cancel it.

**No adapter method may be invoked before the final step.** Spike 02 tests this with a tripwire
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
