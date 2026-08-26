# Teardown — OpenHands (Agent Canvas + Software Agent SDK)

| | |
|---|---|
| Repos | `OpenHands/OpenHands` (Agent Canvas) + `OpenHands/software-agent-sdk` |
| Commits read | Canvas `f48eca6ab9149b3aa532e86842c85da43e370108` (2026-08-25)<br>SDK `760eea2845509ceb446db11f73ca5aa666bd01bb` (2026-08-25) |
| Version tested | `openhands-sdk` 1.43.1; Canvas `@openhands/agent-canvas` 1.15.0 |
| Docs | https://docs.openhands.dev |
| License | MIT (both) |
| Read on | 2026-08-26 |
| Evidence class | A |
| Depth | deep |
| Runtime class | `attached_harness` over a pluggable sandbox |

**Repo has changed identity since the shortlist was drawn.** `OpenHands/OpenHands`
is no longer the Python agent; it is now **Agent Canvas**, "the self-hosted
developer control center for coding agents and automations," which runs
"OpenHands, Claude Code, Codex, Gemini, or any ACP-compatible agent across local,
remote, and cloud backends" (`README.md @ f48eca6`). The agent, sandbox and
runtime moved to `OpenHands/software-agent-sdk`.

That makes this project far more relevant than planned: it is a
framework-neutral control plane with harness adapters and a sandbox provider
abstraction — the two things ADR-0004 and ADR-0009 propose. Both repos were read.

---

## 1. What problem it solves

Teams accumulate several coding agents (Claude Code, Codex, Gemini CLI, OpenHands)
and have nowhere to run them uniformly. Canvas provides one self-hosted control
center: pick an agent, pick a backend (local, Docker, VM, cloud), run
conversations and scheduled automations, and manage credentials and MCP servers
in one place. Before it, each agent had its own CLI, credentials, and no shared
history.

## 2. Core architectural thesis

**The control plane owns the workspace, the event log and the policy; the agent is
a replaceable subprocess speaking a standard protocol.** Canvas treats an external
agent as a stdio ACP server it launches with a declared command, streams typed
events from, and can pause, interrupt or block mid-action.

The clearest statement of the bet is `AgentKind = "openhands" | "acp"`
(`src/types/settings.ts:110 @ f48eca6`). The project's *own* agent and every
foreign agent are peers behind the same enum. That is ADR-0004's thesis in
production, from a team that had every incentive to privilege its own harness.

## 3. Resource / object model

```text
Backend                      (id, name, host, apiKey, kind: local|cloud)
 └── Conversation            (UUID; the unit of work)
      ├── Event              (append-only tree, parent_id + movable HEAD)
      │    ├── ActionEvent        (carries security_risk)
      │    ├── ObservationEvent
      │    ├── MessageEvent
      │    ├── ACPToolCallEvent
      │    ├── HookExecutionEvent (carries blocked flag)
      │    ├── PauseEvent / InterruptEvent
      │    ├── CondensationSummaryEvent
      │    └── ConversationStateUpdateEvent
      ├── ConversationState  (execution_status, stats, secret_registry,
      │                       confirmation_policy, agent, leaf_event_id)
      ├── Workspace          (Local | Docker | Apptainer | RemoteAPI | Cloud)
      ├── SubAgent           (delegation)
      └── Secrets            (SecretRegistry, masked in output)

AgentProfile / Manifest      (automations: requires.features, triggers)
MCPServer                    (with OAuth flow)
Hook                         (PreToolUse, PostToolUse, SessionStart/End, Stop)
```

Root resource is the **Backend**, and the unit of work is the **Conversation**.
There is still no `Agent` resource with durable identity — an agent is a *kind*
plus a launch command, configured per conversation.

Notable: the event log is a **tree**, not a list. `leaf_event_id` is a "movable
HEAD of the conversation tree ... Moving it re-roots the active branch"
(`openhands-sdk/openhands/sdk/conversation/state.py:175 @ 760eea2`), so
forking and navigating history are first-class.

## 4. Runtime model

Canvas launches agents; it does not host them in-process. For `agent_kind: "acp"`
it spawns a stdio subprocess from a registry-declared command
(`src/constants/acp-providers.ts @ f48eca6`). Execution happens inside a
Workspace, which may be a local directory, a Docker container, an Apptainer
container, a remote API-managed sandbox, or cloud infrastructure.

Who owns the event loop: the agent-server (FastAPI) owns it, and Canvas is a
client. Provider credentials are supplied "through the Secrets panel
(`request.secrets`), never through a per-agent env channel"
(`src/types/settings.ts:107 @ f48eca6`) — a deliberate choice worth copying.

## 5. Execution lifecycle

A real state machine, unlike LangGraph
(`openhands-sdk/.../agent_server/../base/common.ts:67 @ f48eca6`, mirrored in
Python):

```text
IDLE → RUNNING → FINISHED
          ↓
        PAUSED
        WAITING_FOR_CONFIRMATION
        STUCK
        ERROR
```

Two states deserve attention:

- **`WAITING_FOR_CONFIRMATION`** — HITL is a first-class execution state, not an
  exception mechanism.
- **`STUCK`** — a state for "running but not progressing." Almost no system in
  this study models this. Long-running agents genuinely do get stuck without
  failing, and having a state for it is the difference between an operator seeing
  the problem and a run burning budget silently.

Goal loops have their own status vocabulary: `running | complete | capped |
interrupted` (`src/types/.../conversation-state-event.ts:85 @ f48eca6`).
`capped` is an explicit budget-exhaustion outcome.

## 6. Durability model

Event-sourced, with a branching tree rather than snapshots.

`append_event` is documented as the "single storage chokepoint: stamp parent_id,
append, advance HEAD" (`state.py:315 @ 760eea2`). Stamping happens there
"not only at the emit callback" so "no event enters the log unstamped, even one a
hook swaps in downstream." That is careful design: one chokepoint, and the
invariant is stated where it is enforced.

State replay is incremental — appending "replays only the new tail — O(k),
preserving the incremental" view (`state.py:341`), so reconstructing the active
branch does not rescan the whole log.

Where it is weaker than LangGraph: there is no equivalent of `Durability =
sync|async|exit`, no declared persistence-timing contract, and no conformance
suite for storage backends. Crash recovery is implied by the event log rather
than specified.

## 7. Agent identity and lifecycle

Still largely absent, though closer than LangGraph. There is an `AgentProfile`
and a `profiles_router`, plus a registry of ACP providers keyed by a "stable
registry key, also stored on conversations as `tags.acpserver`"
(`acp-providers.ts:80 @ f48eca6`). So an agent *kind* has stable identity; an
agent *instance* does not.

No agent versioning, no agent-as-principal, no revocation. `AgentProfile` is
configuration, like LangGraph's `Assistant`.

## 8. Multi-agent communication

Delegation exists via `sub_agents_router` and a `TaskManager` that constructs a
sub-agent conversation inside the parent's `task` TOOL span
(`observability/laminar.py:412 @ 760eea2`). But there is no mailbox, no
channels, no durable inter-agent messaging. Delegation is a nested conversation,
not a message exchange.

One genuinely useful detail: delegate trace linkage is explicit. The parent span
is deliberately *severed* and re-linked via `delegate.parent_trace_id` /
`delegate.parent_span_id` so the sub-agent starts its own trace rather than
inheriting the parent's. The code cites the bug that motivated it
(`software-agent-sdk#4365`). Anyone building subagent tracing will hit this.

## 9. Human interaction model

The strongest human-interaction model seen so far.

**Pause vs interrupt are separate operations**, and the distinction is precise
(`agent_server/conversation_router.py:236-268 @ 760eea2`):

> "Unlike `/pause`, which waits for the current LLM call to finish,
> `/interrupt` cancels the in-flight request so the effect is instant. The
> conversation transitions to *paused* and can be resumed later."

Both end in `paused` and both are resumable. This is exactly the graceful-vs-
immediate distinction our ADR-0002 `CANCELLING` amendment needs, and it is
better than LangGraph, where the sync path cannot be interrupted at all.

**Confirmation policy is a first-class, pluggable object** with three
implementations (`openhands-sdk/openhands/sdk/security/confirmation_policy.py
@ 760eea2`): `AlwaysConfirm`, `NeverConfirm`, `ConfirmRisky(threshold,
confirm_unknown=True)`.

Verified by execution:

```text
AlwaysConfirm   UNKNOWN=CONFIRM  LOW=CONFIRM  MEDIUM=CONFIRM  HIGH=CONFIRM
NeverConfirm    UNKNOWN=auto     LOW=auto     MEDIUM=auto     HIGH=auto
ConfirmRisky    UNKNOWN=CONFIRM  LOW=auto     MEDIUM=auto     HIGH=CONFIRM
threshold=UNKNOWN correctly rejected: ValidationError
```

Two things right here: **fail-safe on unknown risk** (`confirm_unknown=True` by
default), and a validator forbidding `threshold=UNKNOWN` so the policy cannot be
configured into an incoherent state. Adopt both.

## 10. Context and memory

Weaker than Letta or LangGraph. Context management is **condensation** —
`CondensationSummaryEvent` and a configurable condenser compress history when it
grows. There is no long-term cross-conversation agent memory, no shared knowledge
store, no namespaced memory with TTL.

`skills_router` loads "organization-level skills" from a git repository
(`agent_server/skills_router.py:62,96 @ 760eea2`), which is the closest thing
to shared organizational knowledge: versioned, git-backed, org-scoped. Sensible,
but it is instruction-sharing, not memory.

Notably, no mechanism detects that condensation dropped a constraint (S6).

## 11. Tools and capabilities

MCP is a first-class integration with a full OAuth flow:
`start_mcp_oauth`, `get_mcp_oauth_status`, `submit_mcp_oauth_callback`,
`test_mcp_server` (`agent_server/mcp_router.py:632-790 @ 760eea2`). That is a
real answer to I7 (delegated credentials), which LangGraph lacked entirely.

There is no Capability abstraction separate from tool implementation for *agent*
tools. But the **automation manifest** system has one, and it is good — see §22.

## 12. Security and IAM

Better than LangGraph in mechanism, still not an IAM model.

**Per-action risk assessment.** `ActionEvent.security_risk` is a
`SecurityRisk` of `UNKNOWN | LOW | MEDIUM | HIGH`, "predicted by LLM when LLM
risk analyzer is enabled" (`src/types/.../action-event.ts:46,61 @ f48eca6`).
Risk assessment by model rather than static rule is an unusual choice: flexible,
but the security boundary now depends on a model's judgement, and `UNKNOWN`
exists precisely because that judgement can be unavailable. The fail-safe default
is what makes it defensible.

**Hooks can block actions.** `PreToolUse` hooks run before tool execution and
`HookExecutionEvent` carries a `blocked` flag; the code logs "Hook blocked action
{tool_name}" (`hooks/conversation_hooks.py:92,164 @ 760eea2`). Hook types are
`COMMAND` (subprocess), `PROMPT` (single LLM completion) or `AGENT` (agent-based
evaluation with tool access) (`hooks/config.py:39 @ 760eea2`). A genuine policy
interception point, and one that can itself be an LLM or an agent.

**Secrets are properly handled.** `SecretRegistry` resolves lazily, tracks
exported values, and masks them in output including per-ACP-chunk
(`conversation/secret_registry.py:35,143,161 @ 760eea2`). Rotated secrets still
mask their previous values.

**But:** authentication is a shared `SESSION_API_KEY` per agent-server
(`agent_server/config.py:23-51 @ 760eea2`), not a per-agent identity. No
tenant isolation, no per-agent credentials, no audit log distinct from the event
log. **S1 remains undefined**: a sub-agent runs with the parent's workspace and
secrets; no delegation token, no permission intersection.

## 13. Sandboxing

The best sandbox evidence in the study so far, and the reason this was an anchor.

`BaseWorkspace` is an ABC (`openhands-sdk/openhands/sdk/workspace/base.py:27
@ 760eea2`) with abstract `execute_command`, `file_upload`, `file_download`,
`git_changes`, `git_diff`, plus optional `pause` / `resume`. Five providers:

```text
BaseWorkspace
├── LocalWorkspace
├── DockerWorkspace
├── ApptainerWorkspace      (HPC / rootless)
├── RemoteAPIWorkspace
└── CloudWorkspace
```

Apptainer support is a real signal — someone needed rootless containers on HPC,
which is exactly the kind of requirement that proves an abstraction rather than
decorating one.

**The capability-signalling flaw.** `pause()` and `resume()` are optional and
signalled by raising `NotImplementedError` from the base
(`base.py:261-281`). Verified by execution:

```text
LocalWorkspace methods: ['pause', 'resume', 'execute_command']
capability-query attributes: NONE
local pause(): no-op, succeeded
```

There is no way to ask whether a workspace supports pausing — a caller must try
and catch. Worse, `LocalWorkspace.pause()` silently succeeds as a no-op, so a
caller who "pauses" a local workspace to conserve resources gets a false success.
Three of five providers implement it (Docker, RemoteAPI, Cloud).

Contrast directly with LangGraph's conformance suite, which declares capabilities
and detects them by override. **Same problem, two solutions, and LangGraph's is
clearly better.** Together they make the case for ADR-0004's capability
negotiation concrete: declare, detect, and never let an unsupported operation
silently succeed.

**Isolation is thin.** Docker workspace passes `--ulimit nofile=65536` and
nothing else (`openhands-workspace/.../docker/workspace.py:240-258 @ 760eea2`).
No CPU, memory or pid quota. Network is configurable (`--network`) and volumes are
explicit, but there is no egress policy. So `K6` is largely absent and S9
(runaway spend) has no infrastructure-level answer — only the goal-loop `capped`
status.

## 14. Orchestration

Automations with triggers, scheduled runs, and goal loops with a `capped` bound.
Sub-agents provide delegation. Cancellation propagates through the conversation,
and the pause/interrupt split gives two grades of stop.

No DAG, no graph topology — orchestration is conversational and hook-driven
rather than declarative. Could Temporal replace it? Not applicable; there is no
workflow engine to replace.

## 15. Observability

OTel present but indirect, via Laminar (`observability/laminar.py @ 760eea2`).
The code imports `opentelemetry.trace` and manipulates span context, but the
integration is Laminar-specific, including working around Laminar's own isolated
`ContextVar` diverging from standard `opentelemetry.context`.

Cost accounting is attached to the **workspace**, registered on close and posted
to an automation callback with `conversation_id` and `cost`
(`workspace/base.py:65-100 @ 760eea2`). Interesting placement: cost belongs to
the sandbox run, not the agent.

The event taxonomy is strong — 17 event classes including `TokenEvent`,
`LLMCompletionLogEvent`, `HookExecutionEvent`. Better than most, though not a
published stable schema.

## 16. Multi-tenancy

Minimal. Org-level skills configuration exists (`skills_router.py:62-125`) and
Canvas has an `orgId` on backend selection with a `use-cloud-organizations` hook,
but organizations belong to the cloud offering. No RBAC, no quotas, no
environment separation in OSS.

## 17. Protocols and APIs

Canvas: React client over the agent-server REST API.
Agent-server: FastAPI with an OpenAPI spec (`agent_server/openapi.py`) and
routers for conversation, event, file, tool, mcp, hooks, sub_agents, settings,
profiles, agent_profiles, skills, llm, vscode, provider_connections, auth.

Conversation endpoints are explicit and well-shaped:
`POST /conversations`, `/{id}/pause`, `/{id}/interrupt`, `/{id}/run`,
`/{id}/goal` start/stop/resume, `/{id}/secrets`,
`/{id}/confirmation_policy`, `DELETE /{id}`.

Standards: **ACP** (stdio, for agent adaptation), **MCP** (with OAuth), OTel
indirectly. No A2A. There is an explicit REST contract-stability practice — an
`oasdiff` check flags breaking changes, and a comment explains that a field is
kept non-nullable specifically to avoid breaking the published contract
(`hooks/config.py:47-58 @ 760eea2`).

## 18. Storage

Agent-server persists conversations and events (SQLAlchemy-backed per
`conversation_service.py`, `models.py`). Workspace filesystem is provider-owned.
Events are the authoritative append-only record; `ConversationState` is derived
and cached.

## 19. Deployment architecture

Canvas ships as npm package, Docker image, Electron desktop app, and a Helm chart
(`helm/agent-canvas`). Agent-server runs in the workspace container, binding
`0.0.0.0:8000` and authenticating with session API keys forwarded as env vars.
Self-hosting is the default and documented path (`docs/SELF_HOSTING.md`).

## 20. OSS / license / commercial model

MIT for both repos. OpenHands Cloud and OpenHands Enterprise are the commercial
offerings; `CloudWorkspace` is in the OSS tree as a client. No copyleft, no SaaS
restriction.

Verdict: **INTEGRATE**. The workspace abstraction and ACP adapter approach are
patterns to borrow; the agent itself is one harness among several.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | undefined | Sub-agent inherits parent workspace and secrets. No delegation token, no permission intersection, no per-agent identity. |
| S2 Torn side effect | undefined | Event log records the action, but no idempotency key on tool calls and no documented replay contract. |
| S3 Upgrade mid-flight | undefined | Conversations store `agent` config in state, but no version pin and no compatibility check on resume. |
| S4 Concurrent memory write | n/a | No shared memory store to contend on. |
| S5 Cancellation tree | **first_class_answer** | `pause` (graceful, waits for LLM call) vs `interrupt` (immediate, cancels in-flight). Both durable, both resumable, both emit typed events. Best in study. |
| S6 Silent context loss | undefined | Condensation compresses history; `CondensationSummaryEvent` records that it happened but nothing detects a lost constraint. |
| S7 Poison message | undefined | No queue; hook failures logged and skipped. |
| S8 Tenant leak | undefined | No tenant boundary in OSS. |
| S9 Runaway spend | **inferable** | Goal loops have a `capped` status and cost is accumulated per workspace, but no hard budget enforcement and no CPU/memory quota. |
| S10 Zombie sandbox | **inferable** | Containers run with `--rm` and Canvas polls backend health (`use-backends-health`), so orphans are detectable. No documented reaping of a workspace whose control plane vanished. |

## 22. Strongest ideas

1. **`AgentKind = "openhands" | "acp"`.** The project's own agent and foreign
   agents are peers behind one enum. Proof that ADR-0004's neutrality is
   achievable, from a team that could have privileged its own harness.
2. **Pause vs interrupt as distinct operations**, both durable and resumable,
   with the semantic difference documented at the endpoint. Directly solves the
   gap LangGraph left.
3. **`ConfirmRisky` with `confirm_unknown=True` and a validator forbidding
   `threshold=UNKNOWN`.** Fail-safe by default, and impossible to configure
   incoherently.
4. **Manifest capability assessment where "unknown" is a distinct outcome.**
   From `manifest-capabilities.ts:14 @ f48eca6`: *"'unknown' is a real outcome,
   not an error: a deployment that cannot be asked must not be treated as one
   that answered no."* That is precisely the `absent` vs `unknown` distinction
   this teardown's own methodology insists on, arrived at independently. The
   function also returns *which* requirements were unmet, so a refusal can
   explain itself.
5. **`STUCK` execution status.** A state for "running but not progressing."
   Nearly unique in this study and obviously necessary in hindsight.
6. **`SecretRegistry` with output masking**, including per-ACP-chunk masking and
   masking of rotated secrets' previous values.
7. **Hooks that can block, with `COMMAND | PROMPT | AGENT` implementations.**
   Policy interception where the policy can itself be an LLM or an agent.
8. **Event log as a tree with a movable HEAD**, making fork and history
   navigation first-class rather than bolted on.
9. **Single storage chokepoint** for event append, with the invariant documented
   where it is enforced.
10. **Apptainer support** — evidence the sandbox abstraction is load-bearing, not
    decorative.
11. **`oasdiff` REST contract checking**, with code comments explaining why a
    field shape is preserved.

## 23. Weakest architectural choices

1. **Optional workspace capabilities signalled by `NotImplementedError`, with no
   query method.** Verified: no capability-query attributes exist, and
   `LocalWorkspace.pause()` silently succeeds as a no-op — a false success is
   worse than a refusal.
2. **Thin container isolation.** Only `--ulimit nofile`; no CPU, memory or pid
   quotas, no egress policy. For a product whose selling point is running
   untrusted agent code, this is the weakest link.
3. **Security boundary depends on an LLM's risk prediction.** Defensible with the
   fail-safe default, but it means the enforcement point has a probabilistic
   input.
4. **Shared `SESSION_API_KEY` rather than per-agent identity**, so S1 cannot be
   answered.
5. **No durability-timing contract.** No `sync|async|exit` equivalent and no
   conformance suite for storage backends.
6. **No definition version pinning** on conversations, so ADR-0011's hazard
   applies here too.
7. **Weak memory model.** Condensation only; no long-term or shared memory, and
   no detection of constraints lost to compaction.
8. **Two object models across two repos** (Canvas Backend/Conversation vs SDK
   Conversation/Workspace) with no single published domain model.

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| `AgentKind` peer-adapter pattern | REUSE (pattern) | Validates ADR-0004; own harness as one adapter among many |
| ACP as adapter protocol | ADOPT_AS_STANDARD | Working stdio protocol with real Claude Code / Codex / Gemini adapters |
| pause vs interrupt semantics | ADOPT_AS_STANDARD | Two grades of stop, both durable |
| `ConfirmRisky` + `confirm_unknown` | REUSE (pattern) | Fail-safe approval policy |
| Manifest capability assessment (`unknown` ≠ `no`) | REUSE (pattern) | Combine with LangGraph's declared-capability detection |
| `STUCK` status | ADOPT_AS_STANDARD | Add to our Run state machine |
| `SecretRegistry` masking | REUSE (pattern) | Output masking incl. rotated values |
| Blocking hooks (`PreToolUse`) | REUSE (pattern) | Interception point for capability gateway |
| `BaseWorkspace` provider set | INTEGRATE | Provider list and method surface inform our SandboxProvider |
| Workspace capability signalling | reject | Use declared capabilities instead |
| Container isolation config | reject | Insufficient; specify quotas ourselves |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | challenges | Second successful system with no durable agent identity. An agent here is a *kind* plus a launch command; identity lives on the Conversation. The pattern is now consistent enough to take seriously: two of two projects deliver value without agent identity. Our justification must be delegation, policy and audit — and S1 being undefined in both is exactly that evidence. |
| ADR-0002 | confirms | `WAITING_FOR_CONFIRMATION` and `STUCK` show the value of a rich execution state machine. Add `STUCK`. The pause/interrupt split refines the `CANCELLING` amendment into two operations, not one. |
| ADR-0003 | confirms | Delegation is a nested conversation with no mailbox or durable messaging, so sub-agent coordination has no delivery or ordering guarantees. |
| ADR-0004 | confirms | Strongest supporting evidence yet: `AgentKind` treats the native agent as a peer of foreign ACP agents, with a provider registry of launch commands. Also supplies a concrete failure mode — the Codex comment documenting a silent ACP handshake deadlock when a plausible-looking command is not a real ACP server. Adapters need validation, not just configuration. |
| ADR-0005 | confirms | MCP integrated as a protocol with a full OAuth flow, while policy lives elsewhere (hooks, confirmation policy, risk levels). Exactly the split ADR-0005 proposes. |
| ADR-0006 | neutral | No A2A. ACP occupies the adapter role instead. |
| ADR-0007 | confirms | No principal model; sub-agents inherit parent credentials wholesale. S1 undefined for the second time. |
| ADR-0008 | amends | Condensation-only context management is a counter-example: without long-term or shared memory, agents cannot accumulate knowledge across conversations. Supports separating the types, but shows org knowledge may be better served by versioned git-backed *skills* than by a memory store. |
| ADR-0009 | confirms | `BaseWorkspace` with five providers including Apptainer is direct precedent for a SandboxProvider interface. Also proves the negative: optional capabilities must be *declared*, not discovered by exception, and a no-op must never masquerade as success. |
| ADR-0010 | amends | OTel is reachable only through a vendor SDK (Laminar), and integrating it required working around a non-standard context propagation path. Adopting OTel directly is right, but expect vendor integrations to fight the standard. The `delegate.parent_trace_id` re-linking pattern is needed for subagent traces. |
| ADR-0011 | confirms | No version pinning on conversations either. Two of two projects share the hazard. |

**New decision needed:** capability negotiation must be *declarative and
queryable*. LangGraph declares and detects; OpenHands raises
`NotImplementedError` and lets a local no-op silently succeed. The two together
specify the requirement precisely enough to write it down. Proposing
**ADR-0012 — Adapter and provider capabilities are declared, not discovered**,
with the rule that an unsupported optional operation must fail explicitly rather
than no-op.

## 26. Open questions

- Does the agent-server define crash-recovery semantics for a conversation
  interrupted mid-action, or is the event log the only contract? (→ OQ-010)
- How does OpenHands Cloud enforce quotas that the OSS Docker workspace lacks?
  Closed. (→ OQ-011)
- Is ACP's stdio transport sufficient for a remote agent, or does it force
  co-location of adapter and agent? Relevant to whether our A2A adapter and ACP
  adapter can share a code path. (→ OQ-012)
