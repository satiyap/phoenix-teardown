# Teardown — Microsoft Agent Framework

| | |
|---|---|
| Repo | https://github.com/microsoft/agent-framework |
| Commit read | `e34bf48fa369a5b8d1f66a1558d8e03498153633` (2026-08-26) |
| Version tested | `agent-framework-core` (Python), installed from PyPI |
| License | MIT |
| Read on | 2026-08-26 |
| Evidence class | A |
| Depth | targeted (`F` messaging, `L` orchestration, `D9` revocation, `D10` manifests) |
| Runtime class | `hybrid` — in-process agents plus a Pregel workflow engine |

A **targeted pass**, scoped as the Phase 3 findings directed: read for messaging and
orchestration, and as the best remaining hope for a revocation lifecycle.

It answers the orchestration question emphatically and delivers something I did not
expect and had concluded nobody had: **a checkpoint pinned to a hash of the workflow
code, enforced on restore.** Thirteen projects in, ADR-0011 finally has a precedent —
and a better mechanism than the one I designed.

---

## 1. What problem it solves

Building agents and multi-step agent workflows on Microsoft's stack, in three
languages (Python, .NET, Go), with a very wide provider surface. The Python tree
alone has 35 packages: model providers, hosting adapters, memory backends, and
governance integrations.

## 2. Core architectural thesis

**A multi-agent system is a typed graph executed in Pregel supersteps, and a
checkpoint is only valid for the exact graph that produced it.**

`_runner.py:46` — "A class to run a workflow in Pregel supersteps." Execution
advances in discrete supersteps with a checkpoint at each boundary, which is
LangGraph's model. The difference is what the checkpoint carries: MAF stamps a
`graph_signature_hash` and refuses to restore a checkpoint whose graph no longer
matches.

## 3. Resource / object model

```text
Agent                        with hooks, middleware, skills, tools
Session                      _sessions.py
Workflow                     built via WorkflowBuilder
 ├── Executor                a node (agent, function, or nested workflow)
 ├── EdgeGroup               typed topology:
 │    ├── SingleEdgeGroup
 │    ├── FanOutEdgeGroup
 │    ├── FanInEdgeGroup
 │    └── SwitchCaseEdgeGroup  (+ Case, + Default)
 ├── superstep               Pregel iteration; checkpoint boundary
 └── RequestInfo             HITL request/response mid-workflow

WorkflowCheckpoint           (verified live)
  workflow_name
  graph_signature_hash       ← hash of the workflow CODE; validated on restore
  checkpoint_id
  previous_checkpoint_id     ← chain, so checkpoints form a history
  timestamp
  messages                   messages exchanged between executors
  state                      committed only; pending changes excluded
  pending_request_info_events   unanswered HITL requests survive the checkpoint
  iteration_count            superstep boundary
  metadata
  version

DeclarativeAgent (YAML)      kind, name, instructions, model, tools[]
```

## 4. Runtime model

In-process agents, with the workflow engine driving executors through supersteps.
An enormous hosting surface: `hosting`, `hosting-a2a`, `hosting-mcp`,
`hosting-responses`, `hosting-telegram`, `foundry_hosting`, `foundry_local`, plus
`hyperlight` (Microsoft's micro-VM technology) and `devui`.

## 5. Execution lifecycle

Pregel supersteps with `superstep_started` / superstep-completed events, and a
checkpoint at each boundary. The documentation is careful about a subtlety:
`iteration_count` "is not guaranteed to be unique across a workflow's lifecycle. It
marks the superstep boundary the checkpoint sits on, and the same boundary can carry
more than one checkpoint" — for example a run that pauses at
`IDLE_WITH_PENDING_REQUESTS`.

`IDLE_WITH_PENDING_REQUESTS` as a named state is the `WAITING_INPUT` idea again
(HumanLayer's), reached independently.

## 6. Durability model

**This is the finding of the pass.**

`WorkflowCheckpoint` (`_workflows/_checkpoint.py:31-82`) is deliberately *not* tied
to a workflow instance:

> Note that a checkpoint is not tied to a specific workflow instance, but rather to
> a workflow **definition** (identified by `workflow_name` and
> `graph_signature_hash`)... This allows checkpoints to be shared and restored across
> different workflow instances of the same workflow definition.

And the hash is **enforced on restore** (`_workflows/_functional.py:987-992`):

```python
if checkpoint.graph_signature_hash != self.graph_signature_hash:
    raise ValueError(
        f"Checkpoint '{checkpoint_id}' was created by a different version of workflow "
        f"'{checkpoint.workflow_name}' and is not compatible with the current version. "
        f"The workflow's step structure may have changed since this checkpoint was saved."
    )
```

**How the hash is computed is the part worth stealing**
(`_functional.py:1210-1230`):

```python
sig_data = {
    "workflow":  self.name,
    "steps":     sorted(self._step_names),
    "co_code":   sha256(code.co_code).hexdigest(),   # BYTECODE digest
    "co_names":  sorted(code.co_names),
}
return sha256(json.dumps(sig_data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
```

It hashes the workflow function's **bytecode**, with a comment explaining why:
"The code digest catches body changes that step-name discovery misses (e.g.
attribute-access step references)." Step-name discovery reads `co_names` and
globals, which misses `my_steps.fetch`; the bytecode digest catches it anyway.

**Verified empirically.** I reproduced the hash computation and confirmed it is
stable for an identical body and differs for a changed one:

```
same name, different body -> DIFFERENT hash   (2113619054c85e6b / 917aa3374149af7d)
identical body            -> SAME hash
```

**Why this beats my design.** ADR-0011 required a pin on
`(agent_id, agent_version, agent_digest, adapter_id, …)`, which depends on someone
incrementing a version. Omnigent has a monotonic `Agent.version` and *still* cannot
detect mid-flight upgrade, because nothing pins it to the run. MAF derives the
version **from the code itself**, so:

- there is no version to forget to bump;
- a semantically irrelevant edit still invalidates (a false positive, which is the
  safe direction);
- and a checkpoint is portable across *instances* of the same definition, which is
  a property I had not thought to want.

Two other good properties: `previous_checkpoint_id` chains checkpoints into a
history, and **only committed state is checkpointed** — "pending state changes are
not included" — so a checkpoint never captures a half-applied mutation.

## 7. Agent identity and lifecycle

Agents are objects with names; `declarative-agents/` provides YAML manifests
(§17). No agent id, no registry, no version counter, and **no revocation** — `D9`
stays absent at thirteen projects.

Note the asymmetry with §6: MAF versions and pins *workflows* rigorously and does
nothing for *agents*. The same split as ADK (versions storage and telemetry
schemas, not agents).

## 8. Multi-agent communication

Within a workflow, executors exchange **messages along typed edges**, and those
messages are part of the checkpoint (`messages: Messages exchanged between
executors`). So intra-workflow agent messaging is durable — but it is durable
*because the workflow is*, not as an independent messaging substrate. There is no
mailbox, no addressing, no delivery guarantee between agents outside a graph.

That is a meaningfully different answer from AG2's, and worth stating precisely:
**AG2 has durable messages between peers; MAF has durable messages between nodes of
a graph.** AG2's envelope survives independently of any orchestration; MAF's
messages exist only within a workflow's checkpointed state. For our ADR-0003, AG2
remains the model, but MAF shows a cheaper option: if all agent interaction happens
inside an orchestration you already checkpoint, message durability comes free.

`orchestrations/` is a separate package, and `a2a`/`ag-ui` are edge protocols — the
fifth independent instance of that pattern.

## 9. Human interaction model

`RequestInfoMixin` and `pending_request_info_events` on the checkpoint, so a
workflow can pause mid-graph to ask a human and **the unanswered request survives
the checkpoint**. Combined with `IDLE_WITH_PENDING_REQUESTS`, that is durable HITL
integrated into the orchestration rather than bolted alongside it.

No approval resource, no approver identity, no elicitation surface model. ADR-0015
stands.

## 10. Context and memory

`_compaction.py` in core, plus memory backends as packages: `azure-cosmos-memory`,
`mem0`, `redis`, `azure-ai-search`. So compaction is first-class and memory is
pluggable — third project shipping a compaction strategy (with AG2 and ADK).

`_skills.py` and `_filesystem.py` continue the filesystem-skills pattern.

## 11. Tools and capabilities

`_tools.py`, `_mcp.py`, a `tools` package, and `_middleware.py`. The declarative
manifest (§17) scopes tools explicitly with `allowedTools` and `approvalMode`.

`_feature_stage.py` is a nice touch — an explicit feature-stability marker in code,
the same instinct as ADK putting stability in the module path.

## 12. Security and IAM

No principals or agent identity in the framework. But `agent-framework-purview`
provides something no other project has: **bidirectional content policy**.

From its README: it "enforce[s] data security / governance policies on both the
*prompt* (user input + conversation history) and the *model response* before they
proceed further", with "**Blocks or allows content at both ingress (prompt) and
egress (response)**", via "centrally managed policies without rewriting agent
logic", backed by Microsoft Purview DLP.

Two middlewares — `PurviewPolicyMiddleware` (agent level) and
`PurviewChatPolicyMiddleware` (chat-client level) — plus caching with TTL for
protection scopes and background processing for offline evaluation.

**Why this matters for ADR-0013.** Omnigent gave us per-*phase* fail-closed
decisions; Purview gives the same idea a different axis: policy at *ingress* and
*egress* of the model call, enforced by a central authority the agent author does
not control. An agent developer cannot opt out of an org DLP policy by editing
their agent. That is what "centrally managed" has to mean, and it is the first
instance of it.

## 13. Sandboxing

`hyperlight` is a package — Microsoft's micro-VM technology for running untrusted
code with very low startup cost. I did not read its integration depth, but its
presence means the sandbox story is a real VM boundary rather than a process one.
Recorded as `implicit` rather than claimed.

## 14. Orchestration

**The most complete workflow engine in the study.**

- **Typed edge groups**: `SingleEdgeGroup`, `FanOutEdgeGroup`, `FanInEdgeGroup`,
  `SwitchCaseEdgeGroup` with explicit `Case` and `Default` types. So fan-out,
  fan-in and conditional branching are *declared topology*, not emergent control
  flow — `L5` is `first_class` for the first time.
- **Pregel supersteps** with checkpoints at boundaries.
- **`WorkflowExecutor`**, so a workflow is itself a node — composable nesting.
- **`_validation.py`** validates the graph before running.
- **`_viz.py`** renders it.
- **`EdgeGroup.register()`** for custom topologies.

Validating and visualising a graph before execution is the kind of tooling that
only exists when the topology is genuinely declarative. LangGraph has graphs; MAF has graphs
you can check and draw.

No compensation (`L8` — eleven projects).

## 15. Observability

`_telemetry.py` in core, `_evaluation.py`, `devui` for local inspection. OTel is
present in the dependency surface; I did not audit convention adherence in this
targeted pass, so I record `implicit` rather than guessing.

## 16. Multi-tenancy

Not modelled in the framework; Azure provides it, and Purview provides central
policy across tenants.

## 17. Protocols and APIs

Very wide: A2A, AG-UI, MCP (client and hosting), OpenAI Responses hosting, ChatKit,
Telegram, CopilotStudio, GitHub Copilot, and Foundry.

**Declarative agents** (`declarative-agents/agent-samples/**.yaml`) are a real
manifest format:

```yaml
kind: Prompt
name: MicrosoftLearnAgent
instructions: You answer questions by searching the Microsoft Learn content only.
model:
    id: =Env.FOUNDRY_MODEL
    options: { temperature: 0.9, topP: 0.95 }
    connection: { kind: remote, endpoint: =Env.FOUNDRY_PROJECT_ENDPOINT }
tools:
  - kind: mcp
    name: microsoft_learn
    url: https://learn.microsoft.com/api/mcp
    approvalMode: { kind: never }
    allowedTools: [ microsoft_docs_search ]
```

`kind`-discriminated, with `=Env.` expressions for deployment-time values, and —
importantly — **`approvalMode` and `allowedTools` in the manifest**. Tool scoping
and approval policy are part of the declared agent, not runtime configuration. Also
`workflow-samples/`, so workflows are declarable too.

## 18. Storage

Pluggable via packages: `azure-cosmos`, `redis`, `azure-ai-search`, `mem0`.
Checkpoint storage is an injected `storage` with `load(checkpoint_id)`.

## 19. Deployment architecture

Three language SDKs and many hosting targets, including `foundry_hosting`,
`foundry_local`, and `hyperlight`.

## 20. OSS / license / commercial model

MIT, with Azure and Foundry as the commercial gravity. `purview` requires an Azure
Purview subscription. Better than AgentCore's position — the core framework and
workflow engine are fully usable standalone — though not as clean as ADK's
in-memory-implementation-of-everything.

Verdict: **REUSE (targeted).** MIT, Python, and the `graph_signature_hash` mechanism
plus the typed edge groups port directly. The 35-package provider surface does not.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | undefined | No principals in the framework; Azure identity externally. |
| S2 Torn side effect | **inferable** | Only *committed* state is checkpointed and pending changes are excluded, so a checkpoint never captures a half-applied mutation. No effect ledger for tool calls. |
| S3 Upgrade mid-flight | **first_class_answer** | **The best answer in the study, and the only one that needs no manual versioning.** A checkpoint carries `graph_signature_hash` — a digest of the workflow's *bytecode*, step names and globals — and restore raises if it differs: *"created by a different version of workflow … The workflow's step structure may have changed."* Verified by reproducing the hash: identical body → same hash, changed body → different hash. |
| S4 Concurrent memory write | undefined | Not examined in this targeted pass. |
| S5 Cancellation tree | unknown | Not examined. |
| S6 Silent context loss | **inferable** | `_compaction.py` makes compaction a first-class configured operation; no loss signal examined. |
| S7 Poison message | unknown | Not examined. |
| S8 Tenant leak | undefined | Not modelled in the framework. |
| S9 Runaway spend | unknown | Not examined. |
| S10 Zombie sandbox | unknown | `hyperlight` exists; integration not read. |

## 22. Strongest ideas

1. **`graph_signature_hash` on the checkpoint, enforced on restore** — the only
   working version-and-pin in thirteen projects.
2. **Deriving the version from a bytecode digest**, so there is no version to forget
   to bump and no drift between the recorded version and the actual code.
3. **Explaining *why* the bytecode digest is needed** — it catches body changes that
   step-name discovery misses, e.g. attribute-access step references.
4. **A canonical JSON digest** (`sort_keys`, tight separators) so the hash is stable
   across runs and machines.
5. **Binding a checkpoint to a workflow *definition*, not an instance**, so
   checkpoints are portable across instances of the same definition.
6. **`previous_checkpoint_id`** chaining checkpoints into a history.
7. **Only committed state is checkpointed**; pending changes are excluded by design.
8. **`pending_request_info_events` on the checkpoint**, so an unanswered human
   request survives a restart.
9. **Documenting that `iteration_count` is not unique**, with the concrete case that
   breaks the assumption.
10. **Typed edge groups** — single, fan-out, fan-in, switch-case with explicit
    `Case` and `Default` — making topology declared rather than emergent.
11. **`EdgeGroup.register()`** for custom topologies.
12. **Graph validation and visualisation** (`_validation.py`, `_viz.py`) — possible
    only because the topology is data.
13. **A workflow as an executor** (`WorkflowExecutor`), giving composable nesting.
14. **`IDLE_WITH_PENDING_REQUESTS`** as a named state.
15. **Bidirectional content policy** (Purview): blocking at both prompt ingress and
    response egress, from a centrally managed policy the agent author cannot edit.
16. **`_feature_stage.py`** — an explicit feature-stability marker in code.
17. **Declarative agent manifests carrying `approvalMode` and `allowedTools`**, so
    tool scoping and approval policy are part of the declared agent.
18. **`=Env.` expressions** in manifests for deployment-time values.

## 23. Weakest architectural choices

1. **No agent identity, version or revocation** — while versioning *workflows* with
   real rigour. The same asymmetry as ADK.
2. **No agent-to-agent messaging outside a workflow graph.**
3. **Enormous surface**: 35 Python packages plus .NET and Go trees, with `lab/` and
   `monty/` shipped alongside stable code.
4. **Purview requires an Azure subscription**, so the best governance story is not
   independently usable.
5. **A bytecode hash is brittle in the safe direction** — a comment-only edit that
   changes bytecode invalidates checkpoints. Correct default, but it needs an
   escape hatch for deliberate compatible changes, and I did not find one.
6. **No compensation or rollback.**

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| `graph_signature_hash` pinned on the checkpoint, enforced on restore | **ADOPT_AS_STANDARD** | The only working precedent for ADR-0011 in thirteen projects |
| Version derived from a code digest, not a manual counter | **ADOPT_AS_STANDARD** | Removes the "forgot to bump" failure entirely |
| Canonical JSON digest for stability | REUSE (pattern) | Hash must be reproducible across machines |
| Checkpoint bound to a definition, not an instance | **ADOPT_AS_STANDARD** | Makes checkpoints portable across runs of the same definition |
| `previous_checkpoint_id` chaining | REUSE | A checkpoint history, not just a latest |
| Checkpoint only committed state | **ADOPT_AS_STANDARD** | Never persist a half-applied mutation |
| Pending HITL requests inside the checkpoint | **ADOPT_AS_STANDARD** | Durable approval for free, via ADR-0015 |
| Typed edge groups (single/fan-out/fan-in/switch-case) | REUSE (pattern) | Declared topology enables validation and visualisation |
| Graph validation + visualisation | REUSE | Only possible when topology is data |
| Workflow-as-executor nesting | REUSE (pattern) | Composability without a second abstraction |
| Bidirectional (ingress + egress) content policy | **ADOPT_AS_STANDARD** | Centrally managed policy the agent cannot bypass |
| Feature-stability marker in code | REUSE (practice) | Same instinct as ADK's module-path stability |
| Manifest carrying `approvalMode` + `allowedTools` | **ADOPT_AS_STANDARD** | Tool scope and approval policy belong to the declared agent |
| 35-package provider surface | BUILD | Reject as a scope model |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | neutral | Agents are objects with names; no identity, registry or lifecycle. |
| ADR-0002 | **confirms** | `IDLE_WITH_PENDING_REQUESTS` is `WAITING_INPUT` reached independently, and the note that `iteration_count` is not unique per boundary is a precision our Run model needs — a checkpoint marks a boundary, and a boundary can carry several. |
| ADR-0003 | **amends** | A genuinely different answer from AG2's. Messages between *executors* are part of the workflow checkpoint, so intra-graph agent messaging is durable **because the workflow is**. AG2's envelope is durable independently of any orchestration. Both are valid; the amendment is that **if all agent interaction happens inside an orchestration we already checkpoint, message durability is free** — which is a cheaper v0.1 option than a full messaging substrate, at the cost of agents that cannot talk outside a graph. |
| ADR-0004 | neutral | Not an adapter contract; agents are written against the framework. |
| ADR-0005 | confirms | MCP as protocol, with `allowedTools` scoping in the manifest rather than a capability model. |
| ADR-0006 | **confirms** | **Fifth independent instance** of A2A/AG-UI as edge packages beside a different internal model. Settled beyond doubt. |
| ADR-0007 | neutral | No principals in the framework; Azure identity is external. |
| ADR-0008 | confirms | `_skills.py` and `_filesystem.py` for knowledge, plus pluggable memory backends (Cosmos, Redis, mem0, AI Search) and first-class `_compaction.py`. Consistent with the settled split. |
| ADR-0009 | neutral | `hyperlight` suggests a micro-VM boundary; integration depth not read in this pass. |
| ADR-0010 | neutral | `_telemetry.py` and `devui` exist; convention adherence not audited in a targeted pass. |
| ADR-0011 | **confirms — the first and only precedent** | **This changes the ADR from unprecedented to derivative-of-better-prior-art.** Thirteen projects: AX pins adapter identity without versions, Omnigent versions agents without pinning, ADK versions storage and telemetry but not agents, Cloudflare versions its schema but leaves snapshots unversioned. **MAF does the whole thing** — `graph_signature_hash` computed from the workflow's *bytecode*, stamped on the checkpoint, compared on restore, raising with a message that names the likely cause. And it is *better than my design*: deriving the version from code removes the manual-bump failure mode that defeated Omnigent. Amend ADR-0011 to derive pins from content digests wherever possible. |
| ADR-0012 | neutral | No declared capability model; `_feature_stage.py` is a stability marker, not a capability. |
| ADR-0013 | **amends** | Purview adds an axis Omnigent's per-phase model lacks: policy at **ingress and egress of the model call**, evaluated against a **centrally managed** DLP policy that the agent author cannot edit or bypass. Omnigent answers *where* in the enforcement path to fail closed; Purview answers *who owns the rule*. Both belong: our policy engine needs org-level policies that an agent-level policy cannot override. |
| ADR-0014 | **confirms (weakly)** | No effect ledger, but checkpointing only *committed* state is the same instinct — never persist a half-applied mutation. |
| ADR-0015 | **confirms** | `pending_request_info_events` inside the checkpoint means an unanswered human request survives a restart *by virtue of the checkpoint*, without a separate approval store. A second route to ADR-0015 rule 1, alongside HumanLayer's reconciler. |

**Two amendments to make.**

1. **ADR-0011 derives pins from content, not counters.** My design pinned
   `(agent_id, agent_version, agent_digest, adapter_id, adapter_version,
   checkpoint_schema_version)` — six fields, several requiring discipline to
   maintain. MAF computes one hash from the code itself and gets a stronger
   guarantee. Wherever a pin can be a digest of the thing rather than a declared
   version *of* the thing, use the digest: it cannot drift from what it describes.
   Keep declared versions for human communication, not for compatibility checks.

2. **ADR-0013 gains policy ownership levels.** Purview's central DLP policy is not
   just another rule in the same engine — it is a rule the agent author *cannot
   override*. Our policy model needs an explicit precedence: organisation policies
   bind agent policies, and an agent cannot weaken one. Omnigent's scoping
   (`default` vs `session`) is close but is about *reach*, not *authority*.

**One note on scope.** This was a targeted pass and several sections are marked
`unknown` rather than `absent` (`S5`, `S7`, `S9`, `S10`, parts of `K`/`M`) because I
did not read them. With a 75MB three-language repo that discipline matters more than
usual: it would have been easy to record absences I never checked.

## 26. Open questions

- Is there an escape hatch for a deliberate compatible workflow change — a way to
  declare "this edit does not invalidate checkpoints"? A bytecode hash has no notion
  of a semantically-null edit. (→ OQ-037)
- Does MAF's telemetry follow GenAI semantic conventions with a declared vendor
  namespace, as ADR-0010 now requires? Not audited in this pass. (→ OQ-038)
- How deep is the `hyperlight` integration — is a micro-VM the default execution
  boundary for tool code, or an opt-in package? (→ OQ-039)
