# 09 — Open design questions, decided
<!-- status: final -->

Seven questions raised in review of the first spec draft. Each gets a decision and its
reasoning, because leaving them implicit means an implementer guesses — and two of them
have answers that are not obvious. *(Amended 2026-08-30: this said "Six" over seven
numbered sections; `00-overview.md` said seven. The count was wrong, not the document.)*

---

## 1. Is `runs.state` a projection or a second authority?

**A named, rebuildable projection.** The log is the authority.

The first draft claimed state was "never stored in a parallel column" while the schema
stored `runs.state` and §02 updated it. Both could not be true.

Folding a long log on every read is not viable, and `WHERE state = 'waiting_input'` needs
an index — so the projection stays. What changes is that it now carries obligations
(§02): written in the same transaction as its event, advanced by compare-and-swap on the
expected prior state, rebuildable by a documented function, and **never read as truth in a
correctness decision**. The pin comparison, the effect claim and the lease all read
authoritative rows.

CI asserts `projection == fold(log)` over a fixture corpus. A drift is a bug in the
writer, not a state to reconcile at runtime.

---

## 2. Does moving an agent pointer block a run whose pinned artifact still exists?

**No. Reversed after review.** Ordinary pointer changes affect new runs only; existing runs
resume against their own pinned artifact.

The earlier decision said yes, on the argument that an operator editing away a dangerous
instruction should not have in-flight runs quietly continue with the old behaviour. Review
pushed back on three grounds, and all three hold:

1. **A pointer update and a security invalidation are different operations.** Overloading
   one to mean the other makes pinning a *global change detector*: any edit, however
   cosmetic, refuses resume for every in-flight run.
2. **The suggested remedy was unsafe.** "Repoint backwards, let old runs finish, repoint
   forward" leaves the supposedly dangerous definition live for new runs during the
   interval — strictly worse than the problem it solved.
3. **The LangGraph analogy did not transfer.** LangGraph silently resumes against *changed*
   behaviour, having lost the original. Here the run possesses and verifies the exact
   immutable artifact it started with. Resuming a verified pinned artifact is not the same
   failure; it is the pin working.

### What resume actually compares

```
run.pinned_definition_digest  ==  the digest of the artifact being loaded
```

Not `agent.current_digest`. The pin is a statement about *the artifact this run executes*,
and it is still checked on every resume — a corrupted or missing artifact still yields
`ArtifactCorrupted` / `ArtifactMissing`, and a checkpoint from a different definition still
yields `IncompatibleCheckpoint`.

| Operation | In-flight runs | New runs |
|---|---|---|
| `PATCH /v1/agents/{id}` (repoint) | unaffected; resume their pinned artifact | use the new digest |
| digest **revocation** (below) | refuse to resume, `error_code = definition_revoked` | refuse to start |
| explicit `POST /v1/runs/{id}/cancel` | stop, per the state machine | — |

### Stopping a dangerous definition — the operation v0.1 does NOT ship

Blocking in-flight work needs its own audited mechanism:

```
revoked_definitions(tenant_id, digest, revoked_by -> principals, reason, revoked_at)
```

Resume consults it; a hit refuses. It names a principal, carries a reason, and is a
deliberate act rather than a side effect of editing a name.

**v0.1 does not ship this, and that is a stated limitation rather than a silent one.**
Until it exists, the only ways to stop in-flight work are cancelling the affected runs
(supported, audited, and precise) or letting them finish. Overloading pointer movement as
covert revocation would have given the *appearance* of a safety mechanism with none of its
properties: no approver, no reason, no record, and trivially reversed.

Tracked as the follow-on to ADR-0011 alongside agent-level revocation, which
`v01-boundary.md` already defers.

## 3. What happens after approval denial, expiry, or supersession?

Three different answers, because the remedies differ (§05).

| Outcome | Run goes to | Why |
|---|---|---|
| **denied** | `running` | A denial is an *answer*. The worker sends `ToolDenied{call_id, reason: APPROVAL_DENIED, guidance}` and the adapter decides what to do — retry differently, take a compliant path, or stop. A distinct frame, not `ToolResult{ok:false}`, because "refused" and "errored" call for different behaviour. |
| **expired** | `failed`, `error_code=approval_expired` | Nobody answered. A system transition, since no principal acted. |
| **superseded** | stays `waiting_input` | A *new* approval is now outstanding; the run is still blocked, on a different question. |

Denial resuming the run rather than failing it is the non-obvious one. Failing
automatically would discard the adapter's ability to adapt, and would make "the human said
no" indistinguishable from "the tool crashed" — two conditions with nothing in common
operationally.

---

## 4. What are the exact rewind semantics?

**Epochs with supersession ranges, never deletion.** Specified normatively in §04 and
verified by `epoch_algorithm_test.py`, which runs in `make check`.

The first draft said "drop the rewind event and everything with `seq >= before_seq`". That
also drops every event appended *after* the rewind, so a run could rewind but never
continue — a defect found by review and reproduced as the test's negative control.

Each event carries an `epoch`. `run.rewound{to_epoch, from_seq}` opens a new epoch and
supersedes events in epochs ≤ `to_epoch` with `seq >= from_seq`. Continuation works
because new events land in a later epoch; rewinds compose because a rewind of a rewind is
just another cut; and nothing is deleted, so `run_events` stays append-only and superseded
events remain evidence of what was attempted.

---

## 5. Is this the complete v0.1 spec, or the execution spine?

**The execution spine.** §00 now says so, and lists the seven areas still unspecified with
what each needs.

The spine is first because everything else depends on it: a credential is held by a
`Principal`, a sandbox is entered by a `Run`, a cost is attributed to a `Run`, messaging
needs the channel lease from §02. Specifying it first was right; describing it as the
whole v0.1 specification was not.

---

## 6. Which adapter messages must be typed?

**Exactly five, and no more.** §07 gives the shapes; this is the rule for deciding.
*(Amended 2026-08-30: this said "Exactly four" before [`18-cost.md`](18-cost.md) added the
`Usage` frame under this section's own test; the rule is unchanged, the count is not.)*

A frame must be typed **iff the control plane makes a decision about it.**

| Frame | Typed? | The decision |
|---|---|---|
| `ToolCall` | **yes** | evaluate policy, derive `request_digest`, **claim the effect atomically**, verify the tool is in the pinned definition |
| `ToolResult` | **yes** | settle the claim |
| `ToolDenied` (outbound) | **yes** | tell the adapter it was refused, and why |
| `Checkpoint` **envelope** | **yes** | pin `payload_schema_digest` |
| `Usage` (outbound) | **yes** | price the model call against the pinned snapshot: neither the provider, the model identifier nor the token classes are derivable from opaque bytes (spec/18) |
| `Checkpoint` **payload** | no | opaque — the adapter's own format |
| `text`, `thought` | no | display only |
| `Start.config` | no | opaque — the control plane must not parse adapter config |

The first draft made tool calls, approvals and checkpoints undifferentiated `bytes`, which
is incompatible with the platform owning effects: with opaque bytes there is no way to
claim an effect before it runs, because the control plane cannot tell an effect is
happening.

The counter-pressure is real and worth naming: **every typed field is a field a new adapter
author must satisfy**, and AX's opaque-config discipline exists because a control plane
that understands adapter internals needs a change for every new adapter. So the boundary
is drawn at platform *decisions*, which is narrow, stable, and justifiable line by line.

---

## 7. Does v0.1 support multi-party approval or separation of duties?

**No, and it must not approximate one.** Recorded as a **refusal**, not a gap.

> **Multi-party approval and separation of duties are unsupported in v0.1.** The current
> `Approval` represents **one attributable terminal decision**. Workloads requiring quorum
> must delegate authorization to an external governed system, or must not run through
> Phoenix.

**Amended 2026-08-30 (OQ-044): that delegation now has a binding.** `decided_by` may name a
`service` principal standing for the external system, carrying its ticket reference in
`decision_rationale` ([`01-schema.md`](01-schema.md) §Approval, `decided_by_kind` widened to
`human | service`; [`06-api.md`](06-api.md) §Approval authority). Still **one** attributable
decision, never m-of-n — the widening records who made it when that "who" is a governed
system rather than a person, and does not reopen any question in the table above. Trigger for
a real quorum engine: the first finance/legal pack.

### Why restraint, when the requirement is real

The requirement is real. The *design* is not available from evidence, and building it anyway
would be the first subsystem in this project not grounded in a working system.

The corpus contains **one** real approval implementation — HumanLayer — and it has one
terminal decision maker. There is no evidence for m-of-n quorum, role-based requirements,
requester/approver separation, veto semantics, escalation, partial approval, or what happens
when policy changes while a decision is pending.

**Multi-party is not merely cardinality.** The naive schema —
`approval_decisions(approval_id, principal_id, decision)` plus `required_count = 2` —
answers none of the questions that decide correctness:

- Must approvers hold *different* roles, and are roles evaluated at request time or at
  decision time?
- May the requester participate?
- Does one denial veto, or does approval merely need to reach a count?
- Do two accounts belonging to one human satisfy quorum?
- What happens when an approver's access is revoked mid-decision?
- Does changing the action invalidate decisions already cast?
- May the *requirement* change while approval is pending?
- Which system wins when an external approval authority and Phoenix disagree?
- Is approving a deployment also approving its later rollback?

Until a real system and a real organisational policy answer those, `required_count = 2` is
false confidence with a schema attached.

**It may not belong here at all.** Enterprises usually already run a change-management,
access-request or transaction-approval system. A second quorum engine inside Phoenix creates
**two authorities and an audit reconciliation problem** — the identical reason Agent Control
was reclassified INTEGRATE → PORT (`synthesis/scope-reconciliation.md` §3). Integrating with
an existing authority and recording its signed result is a plausible direction, but it is a
hypothesis to investigate, not a decision to encode.

### What Phoenix can honestly claim today

| Supported | Not supported |
|---|---|
| one attributable human decision | four-eyes financial controls |
| approval bound to a specific effect | regulated separation of duties |
| `approve` / `deny` / `expire` / `supersede` | production change needing multiple teams |
| policy decides *whether* approval is required | dual-control security operations |
| no execution before the decision | |
| durable rationale and approver identity | |

Enough for analytics query review, low-risk internal operations, supervised pilots, and
organisations whose policy genuinely requires one approver. **Not** enough for the right-hand
column, and Phoenix must not claim compliant finance posting or production change control on
the strength of this model.

### The trigger, and the gate

The trigger is **the first concrete deployment whose governing policy requires more than one
distinct authorizer, or prohibits requester self-approval.** At that point the next work is a
**focused teardown, not an implementation**, producing:

1. at least **two** working-system precedents;
2. one real organisational policy expressed as executable scenarios;
3. a BUILD-vs-INTEGRATE decision;
4. failure cases for races, revocation and changed actions;
5. a negative control proving an action **cannot** run on partial authorization;
6. a decision about the authoritative system of record.

### Why the scalar does not trap us

`approvals.decided_by` being scalar is not a permanent constraint. If evidence later supports
native multi-party approval: introduce an approval-requirement resource, add append-only
individual decisions, backfill each existing terminal approval as one decision, keep
`approvals.status` as a projection, and redefine the scalar field deliberately. The event log
already preserves enough to migrate single-party decisions.

We accept that migration cost instead of paying a semantic cost now for an unproven
abstraction. **No empty quorum tables today.**
