# Scope reconciliation
<!-- status: final -->

Six ambiguities found in external review of the Phase 5/6 output. All six are real.
This file is the adjudication; the affected documents are corrected to match it.

The root cause of five of them is one word doing two jobs: **"v0.1" meant both the
target architecture and the first shipment**, and I used it interchangeably.

---

## 1. Target architecture ≠ v0.1 shipment

**The contradiction.** `README.md` says we BUILD agent revocation and a two-layer
conformance bench. `v01-boundary.md` defers agent revocation and the live bench
layer. Both are accurate about different things and the documents never said which.

**Resolution — two distinct scopes, named differently from here on.**

| | **Target architecture** | **v0.1 shipment** |
|---|---|---|
| Question it answers | What is this platform, when finished? | What do we build first? |
| Agent revocation | in scope — it is one of the four BUILDs | **deferred** (trigger: first multi-tenant deployment) |
| Conformance bench | two layers, offline + live | **offline layer only** |
| Recall (memory service) | in scope | deferred (Knowledge + State suffice) |
| Messaging | in scope | **contingent** — see §4 |
| Task resource | in the domain model | **not shipped** — see §2 |

The four BUILD items in the README are **target-architecture** claims: they are the
things no project does, so they are ours to invent *eventually*. Two of the four
(pinning, effect ledger) are in the v0.1 shipment; two (revocation, live bench) are
deferred with named triggers.

**Correction applied:** the README's "BUILD — four things nobody does" is relabelled
"Target architecture — four things nobody does", with the v0.1 subset marked.

## 2. Does v0.1 contain a `Task` resource? No.

**The contradiction.** The domain model and ADR-0002 retain `Task → Run`. The
boundary defers "`Task` as a universal spine". `DESIGN.md` calls it speculative
generality. And `Task` appears in **none** of the three v0.1 tiers — verified by
grep, zero mentions.

**Resolution.** **v0.1 creates `Run`s directly. There is no `Task` table.**

- A `Run` carries its own intent fields (prompt, trigger, pin, budget) and does not
  require a parent.
- `Task` enters the schema when scheduled or recurring work becomes a requirement —
  the trigger already recorded in the boundary. At that point `Run.task_id` becomes
  nullable-FK, which is an additive migration.
- ADR-0002 stands as a **target-architecture** decision. Its evidence is one project
  (Omnigent), applying it only to scheduled work, which is exactly the strength of
  evidence that justifies "model it, don't ship it".

This is the ADR-0003 lesson applied in the opposite direction. There I nearly cut a
subsystem with strong precedent; here I nearly shipped one with weak precedent. The
asymmetry is deliberate: **absence across many projects is not proof of
impossibility, but presence in one project is not proof of necessity either.**

## 3. "Integrate Agent Control" — resolved to PORT, not RUN

**The contradiction, and the worst of the six.** `build-reuse-map.md` lists Agent
Control under INTEGRATE ("the whole control plane") *and* lists its individual
patterns under PORT in the same document. Those are materially different
architectures.

**Resolution: PORT the patterns, do not run the service.**

The deciding evidence is in the teardown itself. Agent Control has:

- **its own PostgreSQL persistence** — controls, bindings, execution events;
- **its own tenancy model** (`namespace_key`), which would sit beside ours;
- **no `Principal` model at all** — it governs behaviour and cannot express
  authority.

Running it as a dependency would mean two policy stores, two tenancy schemes, and a
policy engine that structurally cannot reference the principal our ADR-0007 requires
on every decision. That is not integration, it is a second control plane.

**What we take instead** (all recorded as ADOPT_AS_STANDARD, which is the correct
verdict):

- `deny | steer | observe` as the decision vocabulary
- `steer` invalid without remediation guidance, enforced at validation
- recursive condition trees with shape validation
- separate agent vs admin credentials
- `tenant_id` in composite **foreign** keys
- policy binding as a queryable resource with an `enabled` flag
- stats and timeseries over decisions
- observe-mode exempt from short-circuit cancellation (their bug, our fix)

**Correction applied:** Agent Control moves from INTEGRATE to PORT in
`build-reuse-map.md`, leaving three genuine INTEGRATE candidates — `ag2.network`,
Cedar, `genai-prices`.

## 4. `ag2.network` is contingent, not approved

**The contradiction.** Messaging sits in v0.1 Tier 3 as INTEGRATE, while both
`DESIGN.md` and the boundary require a storage spike *before committing*. No spike
artefact exists (`spikes/` does not exist).

**Resolution.** `ag2.network` is **conditionally approved, gated on a spike that has
not been run.** Its v0.1 status is `CONTINGENT`, not `IN`.

The gate, stated as a pass/fail test:

> Replace AG2's file-based WAL with our append-only log, keeping the `Envelope`
> schema and hub contract intact, and demonstrate that causation dedupe survives
> channel termination — i.e. that `find_envelope_by_causation` does not degrade into
> "cannot tell" once terminal-channel pruning clears the index (OQ-024).

**If it passes:** integrate, and messaging is in v0.1.
**If it fails:** port the `Envelope` schema only (it is a data shape, and the best
one found in 13 projects) and implement the hub against our own log. That is a larger
build, and it is the reason this must be settled before Tier 1 rather than during it.

## 5. What "complete" means for validation — fixed in tooling

**The finding.** `make check` exited 2 while the README claimed completion and
presented that command as the verification step.

**Root cause.** `--strict` was written as a pre-phase gate against *unexamined*
probes and could not distinguish those from *deliberately tracked* unknowns. Its
warning text — "each needs an open-questions.md entry" — implied missing work when the
entries already existed.

**Resolution, already implemented** (`c32350a`): the validator now parses
`open-questions.md` for `(slug, probe)` pairs and splits unknowns in two.

- **Untracked unknown** → warning, and failure under `--strict`. Indistinguishable
  from a probe nobody examined, so it must fail.
- **Tracked unknown** → informational note. A legitimate finding.

Verified both directions: injecting `omnigent/A7` fails with "unknown and UNTRACKED
(A7)"; the three real ones pass and `make check` exits 0.

The three tracked unknowns and why they are legitimate:

| Probe | Reason |
|---|---|
| `langgraph/C8` | LangGraph Platform's lease/heartbeat is closed source |
| `letta/C5` | No documented delivery semantics for tool-call replay after crash |
| `openhands/C5` | Same, for tool execution replay |

**The completion claim stands, with its scope stated:** 13 of 14 projects read (the
14th does not exist), 25/25 exit criteria answered, 15/15 ADRs accepted, three
unknowns tracked with reasons. The claim was never "everything is known" — it was
"everything is examined and the gaps are named".

## 6. Next deliverable is a specification, not implementation

**The finding, and I agree without reservation.** The architecture is sufficient for
*direction* and insufficient for *independent implementation*. What is missing:

| Gap | Why it blocks a second implementer |
|---|---|
| Concrete resource schemas | `domain-model.md` gives fields, not types, nullability, indexes or constraints |
| Transition authorization | The Run state machine shows edges, not who may trigger each |
| API / IDL | "resource-oriented `/v1`" is a shape, not a contract |
| Event types | The log is central and its entry schema is unspecified |
| Database choice + consistency boundaries | Single-writer is asserted; the isolation level and transaction boundaries are not |
| Adapter stream protocol | "zero or more frames terminated by exactly one end" is quoted from AX, not specified for us |

**Resolution.** The next deliverable is an **implementation specification**, not
code. Roughly: SQL DDL with constraints, the OpenAPI document, the adapter `.proto`,
the event-type registry, and the state-transition authorization table.

Two spikes gate it because they can invalidate the spec before it is written:

1. **The AG2 storage swap** (§4) — decides whether messaging is integrate or build.
2. **The pin, end to end** — digest a definition, checkpoint, edit, resume, confirm
   `INCOMPATIBLE`. This is the headline differentiator and should be provable in a
   day.

The Cedar analysis question is already answered and does not need a spike: I tested
`cedarpy` and its validator catches a typo'd attribute statically (`riskLevel` vs
`risk` — `validation_passed=False`), but **equivalence and permissiveness comparison
are not exposed in the Python binding.** They exist in Cedar's Rust/Lean tooling. So
ADR-0013's *static* shadow half is a Rust-boundary dependency, and v0.1 gets
*empirical* shadow via `observe` mode. That correction belongs in ADR-0013 and
OQ-033.

---

## Summary of corrections

| # | Ambiguity | Resolution |
|---|---|---|
| 1 | "v0.1" meant two things | Split into **target architecture** and **v0.1 shipment**, tabulated |
| 2 | `Task` in v0.1? | **No.** Runs are created directly; `Task` is target-architecture, additive later |
| 3 | Integrate Agent Control? | **PORT the patterns, do not run the service** — it has no `Principal` model |
| 4 | `ag2.network` approved? | **CONTINGENT** on a storage spike with a stated pass/fail test |
| 5 | Strict validation vs tracked unknowns | Fixed in tooling; tracked unknowns are informational, untracked ones fail |
| 6 | Next deliverable | **Implementation specification**, gated by two spikes |
