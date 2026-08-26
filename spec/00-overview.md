# Implementation specification — v0.1
<!-- status: final -->

The handoff from analysis to construction. `DESIGN.md` states *what* and *why*;
this states *exactly what to build*, at the level a second implementer could work
from without asking questions.

**Scope: the v0.1 shipment**, not the target architecture. See
[`../synthesis/scope-reconciliation.md`](../synthesis/scope-reconciliation.md) §1 for
the difference — `Task`, agent revocation, the live conformance-bench layer and
`Recall` are all deferred.

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
| 08 | [`08-conformance.md`](08-conformance.md) | The offline bench, and what CI must enforce |

## Non-negotiables

These are invariants the schema and code must make *impossible to violate*, not
guidelines. Each traces to evidence; several were learned the hard way in the spikes.

1. **`tenant_id` is in every composite primary key and every composite foreign key.**
   An unscoped lookup finds nothing; a cross-tenant *relationship* cannot be created.
   (Omnigent + ADK for PKs, Agent Control for FKs.)
2. **Every side effect is claimed atomically before it is attempted**, by unique-index
   insert. A read-then-act check is not a dedupe primitive — proven in spike 01,
   where read-then-act double-executed.
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
| `Task` resource | Deferred; `Run` carries its own intent fields |

## Open questions this spec must not paper over

| # | Question | Handling |
|---|---|---|
| OQ-024 | AG2's causation index has a retention horizon | Resolved: we own dedupe, AG2's lookup is never used for correctness (spike 01) |
| OQ-033 | Cedar static analysis is Rust-only | v0.1 uses empirical shadow (`observe`); static comparison deferred |
| OQ-037 | No escape hatch for a compatible edit | Accepted: brittle in the safe direction. If needed, an explicit recorded operator assertion — never a loosened default |
| — | One hub per channel? | §02 decides |
| — | Lease expiry | §02 specifies a fenced TTL lease |
