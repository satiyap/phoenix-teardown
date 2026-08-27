# ADR-0011 — Checkpoints record the definition version that produced them

- **Status:** Accepted (2026-08-26, Phase 5) — 12 projects. Entered as unprecedented, left as derivative of MAF's bytecode-digest pin. Agent-definition pinning remains ours to build.
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

## Amendment 3 — 2026-08-26 (Phase 4, Microsoft Agent Framework): derive the pin from content

**This ADR spent the whole study as the strongest differentiator on the grounds
that nobody did it. That is now false, and the prior art is better than my design.**

Microsoft Agent Framework stamps `graph_signature_hash` on every
`WorkflowCheckpoint` and refuses to restore across a mismatch
(`_workflows/_functional.py:987-992 @ e34bf48`):

```
Checkpoint '…' was created by a different version of workflow '…' and is not
compatible with the current version. The workflow's step structure may have
changed since this checkpoint was saved.
```

And the hash is **derived from the code** (`_functional.py:1210-1230`):

```python
sig_data = {
    "workflow":  self.name,
    "steps":     sorted(self._step_names),
    "co_code":   sha256(code.co_code).hexdigest(),   # BYTECODE digest
    "co_names":  sorted(code.co_names),
}
return sha256(json.dumps(sig_data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
```

Verified by reproducing it: identical function body → same hash; changed body →
different hash.

### Why this beats Amendment 2's design

Amendment 2 specified a pin of six declared fields:

```text
agent_id, agent_version, agent_digest, adapter_id, adapter_version,
checkpoint_schema_version
```

Four of those depend on somebody maintaining them. **Omnigent is the proof that
this fails**: it has the only monotonic `Agent.version` in the study and still
cannot detect a mid-flight upgrade, because a counter that nobody increments — or
that increments without the run recording it — provides nothing.

A content digest cannot drift from the thing it describes. There is no bump to
forget, no version field to leave stale, and no way for the recorded version and
the actual code to disagree.

The MAF comment also captures a subtlety I would have missed: the digest covers
**bytecode**, not just discovered step names, because "the code digest catches body
changes that step-name discovery misses (e.g. attribute-access step references)".
Static discovery of a graph's nodes is incomplete whenever a node is reached
through an attribute; hashing the code is complete by construction.

### Amended decision

**Pins are content digests wherever the pinned thing has content. Declared versions
exist for human communication, never for compatibility checks.**

```text
run.pinned = {
  definition_digest        sha256 of the canonicalised agent/workflow definition
                           (structure + code + declared tools + instructions)
  adapter_identity         which adapter (AX's lesson)
  adapter_digest           sha256 of the adapter's declared contract
  checkpoint_schema_version   OUR envelope format — a real version, ours to bump
  definition_version       INFORMATIONAL only; never compared
}
```

Three rules:

1. **Canonicalise before hashing.** MAF sorts step names and `co_names` and uses
   `json.dumps(sort_keys=True, separators=(",", ":"))`. A pin that varies by
   dict ordering or whitespace is worse than no pin, because it fails randomly.
2. **Compare on resume and refuse loudly**, naming the field that differed and the
   likely cause — MAF's message says *"the workflow's step structure may have
   changed"*, which tells the operator what to look at.
3. **The only hand-maintained version is our own checkpoint envelope format**,
   because that is the one thing whose compatibility rules we define rather than
   discover.

### The tradeoff, stated

A content digest is **brittle in the safe direction**: a comment-only edit that
changes bytecode invalidates checkpoints, even though nothing semantic changed.
MAF appears to accept that with no escape hatch (OQ-037), and for v0.1 so should
we — a false incompatibility costs a restart, while a false compatibility costs
silent corruption of the kind LangGraph exhibits (verified: renamed node → resume
returns `[]`, no error, work lost).

If an escape hatch becomes necessary, it must be an explicit operator assertion
recorded on the run ("I certify digest A is compatible with digest B"), not a
loosening of the default.

### What remains genuinely unprecedented

MAF pins **workflows**. It does not pin **agents** — no agent version, no agent
digest, no revocation. ADK versions its storage and telemetry schemas but not its
agents; Cloudflare versions its schema but leaves user snapshots unversioned;
AgentCore has no version at all.

So the remaining gap is narrower and clearer than before: **applying content-derived
pinning to the agent definition, not just the orchestration graph.** That is still
ours to build, but it is now derivative work on a proven mechanism rather than
invention.

## Evidence log

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | raised | `libs/langgraph @ 3803173`; verified 2026-08-26 | Renamed node → resume returns `[]`, no error, work lost. Same-topology change → new code runs silently. |
| OpenHands | confirms | `openhands-sdk/.../conversation/state.py @ 760eea2` | Conversation state stores agent config but carries no version pin and performs no compatibility check on resume. Two of two projects share the hazard. |
| Letta | confirms | `src/agent/system-prompt-versioning.test.ts @ 852ca24` | No version pin on a suspended conversation, despite system-prompt-versioning tests existing. Three for three on this hazard. |
| Google AX | confirms | `internal/controller/controller.go:82-85 @ b777313`; test `TestExec_ResumeExplicitDifferentHarnessRejected` | **Only project that fails loudly**, verified by running its tests: resuming with a different harness is rejected — "resumption not allowed: harness ID changed from harness-a to harness-b". Refines the ADR: AX pins harness *identity* but not *version*, so substitution is caught and upgrade is not. Our pin must cover both. |
| Omnigent | challenges | `omnigent/stores/agent_store/sqlalchemy_store.py:300 @ ba9e371`; `omnigent/entities/conversation.py:215-217` | **The most useful challenge in Phase 3.** Omnigent has what no other project has — a monotonic `Agent.version` incremented on every bundle update over a content-addressed artifact — and **still cannot detect a mid-flight upgrade**, because a `Conversation` never records the version it started on (searched `entities/conversation.py`; no version field). So versioning is *necessary but not sufficient*: **the pin is the mechanism, and it must live on the run.** Google AX pins harness identity without versions; Omnigent versions without pinning. Nobody does both. Our run record must capture `(agent_id, agent_version, adapter_identity)` at start and compare on resume. |
| Cloudflare Agents | amends | `packages/agents/src/index.ts:1197,2253 @ 2f957bc` | Versions its **own** storage schema carefully (`CURRENT_SCHEMA_VERSION = 11`, stored as a row, checked on wake to skip DDL, forward-only idempotent migrations) but leaves **user** checkpoint payloads unversioned: `snapshot TEXT` on both `cf_agents_fibers` and `cf_agents_runs`, with no version column anywhere. So `onFiberRecovered` receives an unversioned blob possibly written by older code. **Adds a third dimension to the pin**: checkpoint payloads need their own version, separate from agent version and adapter identity, because the recovery hook must know which shape it is being handed. |
| AG2 | confirms | `ag2/network/identity.py:62-68 @ 90f490a`; `ag2/task.py:21-27` | Confirms negatively, and completes the count. Immutable passports sidestep *part* of the problem — any change yields a fresh `agent_id`, so an agent cannot silently mutate under a running task — but there is no version field and `Task.resumed_state` is owner-defined and unversioned. **Eight projects: Omnigent versions without pinning, AX pins without versions, nobody does both.** |
| Pydantic AI | confirms | `pydantic_ai_slim/pydantic_ai/durable_exec/_base.py:38-45 @ b48ee38` | Indirect but useful. The durable boundary forces the same problem the pin solves: a `Model` instance "can't be serialized into an activity/step/task, so a request carries a `model_id` string" resolved through a registry on the far side. **A pin should be an identifier plus a resolver, never a serialized object** — which also makes pins comparable across versions rather than opaque. |
| Google Agent Platform | confirms | `src/google/adk/sessions/schemas/ @ 85b52f6`; `src/google/adk/telemetry/_schema_version.py` | Confirms negatively, and completes the count at **ten projects**. ADK versions its session *storage* schema with migrations (`schemas/v0.py`, `v1.py`) **and** makes its *telemetry* schema deployment-pinnable — so this team plainly understands schema pinning — yet nothing pins the *agent definition* to an in-flight invocation. **The consistency of this gap across projects that version other things carefully is now the strongest argument that ADR-0011 is a real differentiator rather than an oversight I am overweighting.** |
| HumanLayer | neutral | `hld/store/sqlite.go @ 99abe67` | No version pinning of any kind. Eleven projects. |
| AWS AgentCore | confirms | `src/bedrock_agentcore/services/identity.py:94-104 @ 826416a` | Confirms negatively at **twelve projects**. No agent version and no pin. Revocation *does* exist — `delete_oauth2_credential_provider` / `delete_api_key_credential_provider`, asynchronously via `wait_until_deleted` — but at the **credential** level: you can revoke what an agent *reaches*, not the agent itself. Best `D9` answer in the study, and still not agent-level. |
| Microsoft Agent Framework | confirms | `python/packages/core/agent_framework/_workflows/_functional.py:987-992,1210-1230 @ e34bf48`; verified: graph_signature_hash reproduced locally — identical body → same hash, changed body → different hash | **The first and only precedent for this ADR in thirteen projects — and a better mechanism than the one I designed.** A `WorkflowCheckpoint` carries `graph_signature_hash`, and restore raises if it differs: *"Checkpoint '…' was created by a different version of workflow '…' and is not compatible… The workflow's step structure may have changed since this checkpoint was saved."* The hash is a SHA-256 over canonical JSON of `{workflow name, sorted step names, sha256(__code__.co_code), sorted co_names}` — **the version is derived from the bytecode**, with a comment explaining that the code digest "catches body changes that step-name discovery misses (e.g. attribute-access step references)". **Verified by reproducing it.** Because the version comes from the code there is nothing to forget to bump — precisely the failure that defeats Omnigent's monotonic `Agent.version`. Also: the checkpoint binds to a workflow *definition* rather than an instance, so it is portable across runs of the same definition. |
| Agent Control | neutral | `models/src/agent_control_models/ @ 7cb21af` | No versioning or pinning. |

## Open questions

- What is the right compatibility predicate for an SDK whose execution units are not
  statically enumerable — a free-form conversational session, say? *(Amended 2026-08-27:
  originally "a free-form Claude Code session"; the question survives the repositioning
  because a Claude-Agent-SDK-backed agent has the same property.)*
- Does LangGraph Platform mitigate this, or inherit it? (OQ-007)
