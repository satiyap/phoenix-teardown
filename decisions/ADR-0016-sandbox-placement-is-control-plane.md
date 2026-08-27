# ADR-0016 — Sandbox lifecycle and placement are a control-plane concern; isolation is a provider's

- **Status:** **Proposed** (2026-08-27) — raised by the SaaS repositioning. **Not Accepted:** it depends on spike 05 and on OQ-019, which is still open.
- **Date:** 2026-08-27
- **Supersedes:** —
- **Superseded by:** —

## Context

The SaaS shape is a multi-tenant control plane plus a per-customer VPC data plane, and we
run the agents. That makes *where an agent executes* our problem in a way it was not under
the previous thesis, when execution was expected to live inside a third party's harness
(superseded 2026-08-27).

Google AX is the only project in the study that separates an orchestrator from disposable
execution: actors are "suspendable/resumable images" keyed by conversation, **suspended
between turns and resumed onto any worker**
(`projects/google-ax/teardown.md:29,45 @ b777313`). That is the right shape for a data plane
where compute is fungible and a customer's run may outlive any single machine.

It is also the project with the least governance in the study: **no authentication, no
principal, no tenancy, no policy** — logging-only gRPC interceptors on a service that
provisions sandboxes (`projects/google-ax/teardown.md`, and the reason `S6`/`D-section`
probes came back negative). Licensing is `REFERENCE_ONLY`
(`synthesis/licensing.md:27`): read for architecture, take no code.

So the question is not "should we use SubstrATE". It is **which side of the boundary
sandbox lifecycle sits on.**

## Decision

**Placement, suspension, resumption and eviction policy are control-plane concerns.
Process, filesystem and network isolation are a provider's.**

Concretely:

1. A **sandbox provider** exposes: create, suspend, resume, destroy, and a health signal.
   It knows nothing about runs, principals, tenants, policies or approvals.
2. The **control plane** decides *when* to suspend, *whether* a run may resume, *which*
   tenant's data plane it resumes in, and *what happens* when a provider loses a sandbox.
3. **A resumed sandbox is not a resumed run.** Run resumption keeps every existing gate:
   the definition pin is compared, the fenced lease is acquired, and no adapter method is
   invoked before both pass (`spec/05-state-machine.md` §Ordering guarantee for resume).
4. **Losing a sandbox mid-effect is `indeterminate`**, decided by the effect ledger, not by
   the provider. A provider reporting "actor evicted" is evidence, never a verdict.
5. **Tool interception survives placement.** An agent resumed onto a fresh sandbox still
   routes every tool call through `ToolCall → ledger → ToolResult` (`spec/07`).

## Rationale

AX demonstrates that suspend/resume is separable from orchestration, which is the useful
half. It also demonstrates what happens when the same component owns isolation *and*
lifecycle with no principal model: there is nothing to attach a policy to, and nothing to
audit. Splitting the concern keeps the mechanism and refuses the omission.

The alternative — let the execution substrate own lifecycle — would put "may this run
continue?" inside a component that cannot name the tenant asking.

## Implications

- The sandbox provider interface gains suspend/resume beyond the three boundaries already
  specified in ADR-0009.
- `spec/09` (or a successor) must state that sandbox identity is **not** run identity, so a
  recycled sandbox cannot be mistaken for a resumed run.
- We may adopt SubstrATE, another provider, or a plain container runtime behind this
  interface. That choice is deliberately **not** made here.
- Eviction semantics are unknown and load-bearing: see OQ-019.

## Falsification criteria

This ADR is wrong if any of the following turn out to be true:

- Suspend/resume cannot be made **transparent to the run state machine** — i.e. resuming
  onto a fresh sandbox requires relaxing the pin comparison or the lease.
- A provider cannot report sandbox loss without also asserting the effect outcome.
- Tool interception cannot be preserved across a sandbox move, which would mean placement
  and execution ownership are not separable after all.

## Spike 05 — the gate before this becomes Accepted

**Invariant, stated first:** *an agent's run survives the destruction of the sandbox it was
executing in, with no weakening of the resume gates and no loss of tool interception.*

1. Start an SDK-backed agent in sandbox A; let it emit one `ToolCall` and settle the effect.
2. Checkpoint. **Kill sandbox A.**
3. Resume on a **fresh** sandbox B.
4. **Gate 1 — the resume gates still hold.** Use the `TripwireAdapter` from spike 02:
   assert `calls == []` on every failure path (artifact missing, artifact corrupted, pin
   mismatch, concurrent resume). Sandbox replacement must not become a way to skip a gate.
5. **Gate 2 — tool calls remain platform-intercepted on this path.** The post-resume tool
   call produces an `effect_ledger` row. Negative control: let the SDK execute a tool
   directly on the fresh sandbox and assert **no row appears**.
6. **Negative control for the invariant itself:** resume with a *changed* definition digest
   and confirm `IncompatibleCheckpoint`, so the test cannot pass by ignoring the pin.

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| Google AX | confirms | `projects/google-ax/teardown.md:29,45 @ b777313` | Supplies the mechanism: actors as suspendable images keyed by conversation, resumed onto any worker, with a single-writer control plane kept separate. Also supplies the anti-pattern — zero authN, no principal, no tenancy, no policy on the service that provisions sandboxes — which is why lifecycle must sit on the governed side. `REFERENCE_ONLY` (`synthesis/licensing.md:27`). |
