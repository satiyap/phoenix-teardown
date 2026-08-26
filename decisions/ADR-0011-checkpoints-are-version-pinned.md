# ADR-0011 — Checkpoints record the definition version that produced them

- **Status:** Provisional (raised by evidence, Phase 2)
- **Date:** 2026-08-26
- **Supersedes:** —
- **Superseded by:** —

## Context

Not part of the original strawman. Raised by the LangGraph teardown, where two
experiments on a suspended run showed silent, unsignalled work loss.

`libs/langgraph @ 3803173`, verified empirically with langgraph 1.2.11:

1. A thread suspended at `interrupt()` under one graph definition, resumed
   against a **structurally identical** graph with a changed node body, ran the
   **new** code. No version is recorded on the checkpoint, so an upgrade silently
   applies to in-flight runs.
2. The same thread resumed against a graph where the node had been **renamed**
   returned `[]` with **no error**. The pending task referenced a node that no
   longer existed, and the work was discarded silently.

The second case is the serious one. An operator renaming a node while approvals
are pending destroys that work with no failure signal — no exception, no log, no
state indicating loss. LangGraph's Platform layer versions Assistant *config*
(`AssistantVersion`) but not graph *topology*, so the hazard survives there too.

Any platform holding runs suspended for hours or days across deploys will hit
this. Our HITL approval gate makes long suspensions the normal case, not the edge
case.

## Decision

Every checkpoint records the identity **and** version of the agent definition
that produced it. On resume, the runtime compares the recorded version against
the current definition and:

- **compatible** → resume normally;
- **incompatible** → fail loudly with a typed error naming what changed;
- **never** → silently drop, silently substitute, or partially apply.

"Compatible" must be defined explicitly rather than left to inference. Initial
proposal: a change is compatible if the set of addressable execution units
(nodes, steps, states — whatever a pending task can reference) is unchanged.
Changes to the body of an existing unit are compatible; adding, removing or
renaming a unit is not.

Resuming a run onto a knowingly-incompatible definition must be possible, but
only as an explicit, audited migration operation — never the default path.

## Rationale

Silent work loss is the worst failure mode available: no signal, no recovery
path, and discovery only when someone asks why an approval never completed. A
loud failure on resume is strictly better, because the pending state still
exists and an operator can decide what to do.

This also interacts with ADR-0002. If Task and Run are separate, a Run made
unresumable by an upgrade can fail while its Task survives and spawns a fresh
Run under the new definition. That is a clean recovery story, and it is only
available because the two are separate resources.

## Implications

- Checkpoint schema carries `definition_id` and `definition_version`.
- A compatibility predicate must be defined per runtime adapter, since each
  harness has its own notion of an addressable execution unit. Adapters that
  cannot report a definition version can only offer best-effort resume, and must
  declare that (ties to ADR-0004 capability negotiation).
- Needs a typed `IncompatibleDefinition` failure and a Run terminal state for it.
- Needs an explicit migration/override path for deliberate upgrades.
- Agent definitions should be immutable and versioned, which strengthens the
  `AgentVersion` node in the domain model.

## Falsification

If in practice suspended runs are always short-lived, or if every harness we
adapt can already resume across arbitrary definition changes, then version
pinning is bookkeeping without benefit. Evidence to watch for: a studied system
that upgrades definitions mid-flight safely and without version comparison.

Also falsifiable in the other direction: if no harness can report a stable
definition version, the decision is unimplementable as stated and must weaken to
"record what is available, warn when unknown."

## Deciding probes

`C12`, `S3`, `D4`, `C11`

## Amendment — 2026-08-26 (Phase 3, Omnigent): the pin is the mechanism, not the version

Omnigent challenged this ADR usefully. It has the only agent versioning in the
study — `Agent.version`, a monotonic counter incremented on every bundle update
over a content-addressed tarball (`stores/agent_store/sqlalchemy_store.py:300 @
ba9e371`) — and it **still cannot detect a mid-flight upgrade**, because a
`Conversation` never records the version it started on. I searched
`entities/conversation.py` for a version field; there is none.

So versioning a definition is necessary but not sufficient. Across six projects:

| Project | Versions the definition | Pins it on the run | Detects mid-flight change |
|---|---|---|---|
| LangGraph | no | no | **no** (verified: renamed node → resume returns `[]`, silent work loss) |
| OpenHands | no | no | no |
| Letta | no | no | no |
| Google AX | **no** | **yes** (harness *identity*) | **yes** (verified: rejects resume) |
| Omnigent | **yes** (monotonic) | **no** | **no** |
| — | — | — | — |

**Nobody does both.** AX pins identity without versions, so it catches
substitution but not upgrade. Omnigent versions without pinning, so it has an
audit trail but no guard.

**Amended decision.** The run record captures, at start:

```text
run.pinned = {
  agent_id,
  agent_version,        # monotonic, from the definition
  agent_digest,         # content hash of the resolved bundle
  adapter_id,           # which adapter (AX's harness identity)
  adapter_version,      # and its version
  checkpoint_schema_version,
}
```

On resume, every field is compared. A mismatch is `INCOMPATIBLE` and refuses to
resume with a message naming *which* field changed and both values — following
AX's example, whose error names the old and new harness id and is pinned by a
test.

The distinction that matters: **the version lives on the definition, the pin
lives on the run.** A version counter alone answers "what changed?" after the
fact; only the pin answers "may this resume?" before work is lost.

## Evidence log

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | raised | `libs/langgraph @ 3803173`; verified 2026-08-26 | Renamed node → resume returns `[]`, no error, work lost. Same-topology change → new code runs silently. |
| OpenHands | confirms | `openhands-sdk/.../conversation/state.py @ 760eea2` | Conversation state stores agent config but carries no version pin and performs no compatibility check on resume. Two of two projects share the hazard. |
| Letta | confirms | `src/agent/system-prompt-versioning.test.ts @ 852ca24` | No version pin on a suspended conversation, despite system-prompt-versioning tests existing. Three for three on this hazard. |
| Google AX | confirms | `internal/controller/controller.go:82-85 @ b777313`; test `TestExec_ResumeExplicitDifferentHarnessRejected` | **Only project that fails loudly**, verified by running its tests: resuming with a different harness is rejected — "resumption not allowed: harness ID changed from harness-a to harness-b". Refines the ADR: AX pins harness *identity* but not *version*, so substitution is caught and upgrade is not. Our pin must cover both. |
| Omnigent | challenges | `omnigent/stores/agent_store/sqlalchemy_store.py:300 @ ba9e371`; `omnigent/entities/conversation.py:215-217` | **The most useful challenge in Phase 3.** Omnigent has what no other project has — a monotonic `Agent.version` incremented on every bundle update over a content-addressed artifact — and **still cannot detect a mid-flight upgrade**, because a `Conversation` never records the version it started on (searched `entities/conversation.py`; no version field). So versioning is *necessary but not sufficient*: **the pin is the mechanism, and it must live on the run.** Google AX pins harness identity without versions; Omnigent versions without pinning. Nobody does both. Our run record must capture `(agent_id, agent_version, adapter_identity)` at start and compare on resume. |

## Open questions

- What is the right compatibility predicate for a harness whose execution units
  are not statically enumerable (a free-form Claude Code session, say)?
- Does LangGraph Platform mitigate this, or inherit it? (OQ-007)
