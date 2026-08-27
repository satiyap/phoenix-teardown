# Implementation specification — v0.1
<!-- status: final -->

*SOURCE OF TRUTH: [`synthesis/scope.yaml`](../synthesis/scope.yaml) — `make check` asserts these tables match it.*

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

## Not yet specified — the rest of the v0.1 shipment

Each is in `v01-boundary.md` Tier 1–3 and is **not** covered by documents 01–08. Listing
them is the difference between an incomplete spec and a spec that pretends otherwise.

| Area | Boundary tier | Needs |
|---|---|---|
| `Credential` with separate exchanger/refresher | 1 | resource schema, OAuth2 flows, the secretless egress-proxy contract |
| Sandbox — three boundaries | 2 | provider interface, egress guard blocklist, storage-boundary rule |
| Knowledge (filesystem skills) | 2 | layout, resolution order, digest participation |
| Messaging (`ag2.network`) | 3 | the compatibility layer's public surface, channel-lease integration |
| Cost measurement (`genai-prices`) | 3 | usage capture, the fail-closed-on-unpriced rule |
| **Pydantic AI adapter** | 1 | the concrete mapping from §07 frames onto Pydantic AI, with its native tool executor disabled. One harness, not two (amended 2026-08-27) |
| OTel semantics | 2 | span names, attribute namespace, semconv version |
| **`tasks` / `routines`** | 2 | schedule *or* trigger → Run. The unit customers buy, un-deferred 2026-08-27. Owner: spec 10 or 11. Needs the resource, the trigger taxonomy, and the rule that a routine creates Runs but never becomes one |
| **Agent harness (Pydantic AI)** (spec 12) | 1 | **the policy over Pydantic AI's seams**, not the seams themselves. It supplies `capabilities/hooks.py`, `process_history.py` (compaction), `wrapper.py`, `toolsets/` (nested agents) and `CapabilityPosition` (ordering). We own: which history strategy runs and when, how a delegated agent inherits a `Principal` and a pinned bundle, which hooks write to the effect ledger, and context assembly from the compiled bundle. *(Corrected 2026-08-27: this said these primitives are "ours to build"; they exist — the integration policy is ours.)* |
| **Work bundles** (`10-work-bundles.md`) | 1–2 | `WorkBundle`, `Resource`, `Action`, `ActionReceipt`, `Verifier`, and `effect_class ∈ {observation, idempotent_mutation, non_idempotent_mutation, long_running_operation}`. The domain-`type` → behavioural-role table is **bundle-supplied**, never core. A verifier must be pinned by a **different publisher** than the bundle it verifies (spike 04 finding 1). Freshness is **evidence**, not bundle state (finding 2). `indeterminate` retains `external_operation_id` as a recovery handle and inspection is a **separate Action** (finding 4) |

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
