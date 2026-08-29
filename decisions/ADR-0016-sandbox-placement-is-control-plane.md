# ADR-0016 — Sandbox lifecycle and placement are a control-plane concern; isolation is a provider's

- **Status:** **Proposed** (2026-08-27) — raised by the SaaS repositioning. **Not Accepted:** it depends on spike 05. *(Amended 2026-08-27: OQ-019 no longer blocks; the v0.1 provider is decided below.)*
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
- The sandbox unit is the **pod**, holding **one container in which the Go driver is PID 1 and
  spawns the Python harness as its child** *(amended 2026-08-29; superseded wording: "Go-side driver plus the Python harness sidecar",
  i.e. two containers, which spike 05 T2 showed cannot share a Unix socket under gVisor)*. The channel is an **`AF_UNIX` socketpair the driver creates
  and passes to the child by fd inheritance** — there is no filesystem socket, so no later process
  in the container (a `kubectl exec`, a same-UID sibling) has anything to connect to. *(Amended
  2026-08-29, same day: an earlier wording said a `0700` directory and `0600` ownership "backed by
  process lineage"; that was wrong — Unix permissions check UID, not ancestry, and a same-UID
  sibling connected in the verifier's counterexample; superseded.)* Protocol authentication is
  `run_token` on `Start`. `kubectl exec` authorisation remains a Kubernetes RBAC boundary, not
  ours. Checkpoint-and-kill deletes and recreates that pod as one unit.
- `spec/09` (or a successor) must state that sandbox identity is **not** run identity, so a
  recycled sandbox cannot be mistaken for a resumed run.
- **v0.1 provider decided 2026-08-27 (amended; this bullet previously left the choice open):
  Kubernetes with a gVisor `RuntimeClass`, and *suspend* implemented as checkpoint-and-kill** —
  the pod is deleted when a run enters `waiting_input` past a configurable warm window and
  rebuilt from the run log and the adapter checkpoint on resume. Chosen because it needs no
  KVM (runs on any customer's nodes), no second control plane, and no pre-1.0 dependency;
  idle cost is zero and resume is seconds, which is invisible behind a human wait. Warm-tier
  policy (keep the pod for short waits), a small warm pool, and pre-pull are scheduler
  configuration under this ADR, never visible to the harness.
- **No upgrade provider is named** (amended 2026-08-27: an earlier bullet listed candidates;
  removed — that is a future decision, taken on evidence when utilisation becomes a
  measured problem). What *is* fixed now is the rule that keeps the choice open: **the
  harness never relies on process memory surviving; the log and the adapter checkpoint are
  the only durability**, and spike 05 gate 4 tests it.
- OQ-019/OQ-042 (SubstrATE internals) no longer block this ADR and are parked until a provider change is on the table.

## Falsification criteria

This ADR is wrong if any of the following turn out to be true:

- Suspend/resume cannot be made **transparent to the run state machine** — i.e. resuming
  onto a fresh sandbox requires relaxing the pin comparison or the lease.
- A provider cannot report sandbox loss without also asserting the effect outcome.
- Tool interception cannot be preserved across a sandbox move, which would mean placement
  and execution ownership are not separable after all.

## Spike 05 — the gate before this becomes Accepted

*(Reshaped 2026-08-27: runs on the decided v0.1 provider, sequenced after spike 06, and
gains the fallback and cost gates. The earlier text targeted an unnamed provider and repeated
spike 06's interception claim.)*

**Invariant, stated first:** *an agent's run survives the destruction of the sandbox it was
executing in — and of its checkpoint artefact — with no weakening of the resume gates, no
loss of tool interception, and no compute consumed while it waits.*

Provider under test: Kubernetes + gVisor `RuntimeClass`, checkpoint-and-kill. Harness: the
Pydantic AI adapter from spike 06 (**complete 2026-08-28, PASS, 64 assertions (amended 2026-08-28)** *(corrected 2026-08-28 from `spikes/06-tool-interception/RESULT.md`; was "2026-08-27, 18 assertions", the round-1 count, then "53", the round-4 count)*), with its
boundary reused, not re-proven.

1. Start the harness in pod A; let it emit one `ToolCall` and settle the effect; drive the run
   to `waiting_input` on an approval.
2. **Gate 1 — idle costs nothing.** After the warm window, pod A is gone (`kubectl get pod`
   returns nothing for the run); the run row is still `waiting_input` with no lease.
3. Approve. Resume lands in a **fresh** pod B on a different node (taint A's node).
4. **Gate 2 — the resume gates still hold.** `TripwireAdapter` from spike 02: `calls == []` on
   every failure path (artifact missing, corrupted, pin mismatch, concurrent resume). Sandbox
   replacement must not become a way to skip a gate.
5. **Gate 3 — sandbox identity is not run identity.** Recreate a pod with A's name and
   labels; assert it cannot be mistaken for a resumed run (no lease, no adapter call).
6. **Gate 4 — the fallback.** Delete the adapter checkpoint artefact *and* any provider
   snapshot; resume; assert the run rebuilds from the log alone and continues — or fails
   loudly as `artifact_missing`, never silently as a fresh run. This is the test that keeps
   every upgrade provider swappable.
7. **Negative controls:** resume with a changed definition digest ⇒ `IncompatibleCheckpoint`;
   let the harness keep state in process memory only ⇒ gate 4 goes red; shorten the warm
   window to zero and skip pod deletion ⇒ gate 1 goes red.

Tool interception after resume is covered by spike 06's boundary running unchanged in pod B;
one assertion that its ledger row appears is enough here. *(Spike 06 gate 4 already proves the
resume path does not re-execute a body in-process — `_tool_execution.py:399` makes `external`
kinds executable on resume — so what remains here is only that the same boundary holds when the
process is a different pod.)*

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| Google AX | confirms | `projects/google-ax/teardown.md:29,45 @ b777313` | Supplies the mechanism: actors as suspendable images keyed by conversation, resumed onto any worker, with a single-writer control plane kept separate. Also supplies the anti-pattern — zero authN, no principal, no tenancy, no policy on the service that provisions sandboxes — which is why lifecycle must sit on the governed side. `REFERENCE_ONLY` (`synthesis/licensing.md:27`). |
| **Spike 05 T2 (2026-08-29)** | amends | `spikes/05-*/T2-FINDING.md` @ `9f21e88` | A Unix socket on a shared `emptyDir` does **not** propagate across containers under gVisor release-20260817.0 (systrap): the inode never appears in the second container; regular files do; the identical pod without `runtimeClassName` connects. Bisected against start races, overlay, mount coherence. Within one container the UDS works at `0600`. Consequence: one container, driver spawns harness. Fallback if two containers are ever required: an abstract-namespace socket in the shared netns, at the cost of `0600`. |
