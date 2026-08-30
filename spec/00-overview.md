# Implementation specification — v0.1
<!-- status: final -->

The handoff from analysis to construction. `DESIGN.md` states *what* and *why*; this
states *exactly what to build*.

> **This is the EXECUTION SPINE, not the whole v0.1 shipment.** Review correctly found
> that an earlier version of this line overclaimed. What is specified here is the
> spine — identity, definitions, runs, the log, effects, approvals, policy records,
> the adapter contract, and the invariants that bind them. What v0.1 *also* ships and
> this spec does **not** yet cover is listed in §Not yet specified below, with an owner
> for each.

**Scope: the v0.1 shipment**, not the target architecture. See
[`../synthesis/scope-reconciliation.md`](../synthesis/scope-reconciliation.md) §1 for
the difference — agent revocation, the live conformance-bench layer and `Recall` are
deferred. **Amended 2026-08-27:** `Task` was listed here as deferred and is now **Tier 2**
(`scope-reconciliation.md` §2, §7); routines are the unit customers buy.

## Documents

| # | Document | Settles |
|---|---|---|
| 01 | [`01-schema.md`](01-schema.md) | SQL DDL: types, nullability, keys, indexes, constraints |
| 02 | [`02-consistency.md`](02-consistency.md) | Database, isolation levels, transaction boundaries, leases |
| 03 | [`03-canonicalisation.md`](03-canonicalisation.md) | The digest profile, written for a non-Python implementer |
| 04 | [`04-events.md`](04-events.md) | Event-type registry and log entry schema |
| 05 | [`05-state-machine.md`](05-state-machine.md) | Run states and **who may trigger each transition** |
| 06 | [`06-api.md`](06-api.md) | The northbound HTTP contract |
| 07 | [`07-adapter-protocol.md`](07-adapter-protocol.md) | The southbound stream contract |
| 08 | [`08-conformance.md`](08-conformance.md) | The offline bench, what CI enforces, and the required invariant tests |
| 09 | [`09-decisions.md`](09-decisions.md) | **Seven** design questions, decided with reasoning |
| 10 | [`10-work-bundles.md`](10-work-bundles.md) | Work bundles: the six nouns, the compiled package, and how an Action lands on the effect ledger |
| 11 | [`11-routines.md`](11-routines.md) | Routines/`Task`: schedule or trigger → Run, firing idempotency, delegation |
| 12 | [`12-harness.md`](12-harness.md) | The policy over Pydantic AI's seams: history, delegation, hooks, context assembly, checkpoint payload |
| 13 | [`13-adapter-sdk-subprocess.md`](13-adapter-sdk-subprocess.md) | The `sdk_subprocess` adapter: driver/harness process model, record framing, resume checks |
| 14 | [`14-credentials.md`](14-credentials.md) | `Credential`, the three flows, exchanger/refresher, the secretless egress contract |
| 15 | [`15-sandbox.md`](15-sandbox.md) | Sandbox: provider interface, the three boundaries, sandbox identity, loss |
| 16 | [`16-knowledge.md`](16-knowledge.md) | Knowledge packages and `state_entries`: layers, compilation, digest participation, scopes |
| 17 | [`17-messaging.md`](17-messaging.md) | Messaging: the compatibility layer over `ag2.network`, the Envelope as data, channel leases |
| 18 | [`18-cost.md`](18-cost.md) | Usage capture, pricing from a pinned `genai-prices` snapshot, fail-closed-on-unpriced, attribution |
| 19 | [`19-telemetry.md`](19-telemetry.md) | OTel: the `phoenix.*` namespace, span and metric inventory, the version pins, propagation, sampling |

## Not yet specified — the rest of the v0.1 shipment

**None, as of 2026-08-30.** All ten areas this table listed are settled by documents 10-19
above, and `synthesis/scope.yaml`'s `owed_specs` is empty to match. What remains open is
recorded question by question in [`../open-questions.md`](../open-questions.md), and in
each document's own *What this does not guarantee* section — which is a different claim
from "unspecified", and is made where the specification that raises it lives.

For the ten rows this table used to carry and the document that closed each,
see `synthesis/scope-reconciliation.md` §8.

**Sequencing note.** Documents 01–08 are the spine because everything above depends on
them: a credential is held by a `Principal`, a sandbox is entered by a `Run`, a cost is
attributed to a `Run`, and messaging needs the channel lease from §02. Specifying the
spine first is deliberate; claiming it was everything was not.

## Non-negotiables

These are invariants the schema and code must make *impossible to violate*, not
guidelines. Each traces to evidence; several were learned the hard way in the spikes.

1. **`tenant_id` is in every composite primary key and every composite foreign key.**
   An unscoped lookup finds nothing; a cross-tenant *relationship* cannot be created.
   (Omnigent + ADK for PKs, Agent Control for FKs.)
2. **Every side effect is claimed atomically before it is attempted.** Two distinct
   mechanisms, not one:
   - **intent** is deduplicated by a unique-index `INSERT ... ON CONFLICT DO NOTHING`
     on the deterministic effect key;
   - **the claim** is a conditional `UPDATE` that must simultaneously find the effect
     claimable, the approval granted, and the worker still holding the run lease.

   A read-then-act check is not a dedupe primitive — proven in spike 01, where
   read-then-act double-executed (`['w1','w2']`). An earlier version of this list
   described only the insert, which is the intent half.
3. **The effect ledger does not depend on message-log retention.** Channel deletion or
   compaction must not change the safety guarantee for an unrelated external effect.
4. **A run's pin is compared before any adapter code runs**, and a mismatch is a
   terminal `INCOMPATIBLE`, never a silent continuation.
5. **Resume acquires a fenced lease before reaching the adapter.** Pin correctness does
   not prevent duplicate execution.
6. **The artifact that executes is the artifact whose digest was checked** — resolved
   from the registry, never taken from the caller.
7. **Only committed state is checkpointed.** A checkpoint can never hold a half-applied
   mutation. (MAF.)
8. **Every terminal approval names its approver.** (ADR-0015; the gap HumanLayer left.)
9. **`temp:`-prefixed state is never persisted**, enforced in the storage layer rather
   than in application code. (ADK.)
10. **Refusals are as observable as successes**, and aggregable. (AG2 + Agent Control.)

## Verification standard

[`../spikes/VERIFICATION-RULES.md`](../spikes/VERIFICATION-RULES.md) is binding. In
particular: every invariant above needs a test that goes through the public boundary,
plus a **negative control** proving the test fails when the guard is removed.

Two review rounds found the same defect class in my own work — testing the mechanism I
had built rather than the claim I was making. The rules exist to break that, and they
apply to the implementation as much as to the spikes.

## What is deliberately unspecified

| Area | Why |
|---|---|
| Model/provider integration | Explicit anti-goal; commodity |
| Workflow/DAG orchestration | External engine (Temporal/DBOS/Prefect) |
| Compensation/saga | Zero precedent in 13 projects; the engine's job |
| UI | Not a platform concern for v0.1 |
| ~~`Task` resource~~ | **No longer excluded (2026-08-27).** Moved to Tier 2 as `tasks`/`routines`; see "Not yet specified" above for the owed schema. `Run` still carries its own intent fields, and `Run.task_id` is a nullable FK |

## Open questions this spec must not paper over

| # | Question | Handling |
|---|---|---|
| OQ-024 | AG2's causation index has a retention horizon | Resolved: we own dedupe, AG2's lookup is never used for correctness (spike 01) |
| OQ-033 | Cedar static analysis is Rust-only | v0.1 uses empirical shadow (`observe`); static comparison deferred |
| OQ-037 | No escape hatch for a compatible edit | Accepted: brittle in the safe direction. If needed, an explicit recorded operator assertion — never a loosened default |
| — | One hub per channel? | §02 decides |
| — | Lease expiry | §02 specifies a fenced TTL lease |
