# ADR-0004 — Agent runtime is adapter-based; the platform does not publish an authoring framework

> **Title amended 2026-08-27.** It read "…the platform does not author agents", which is now
> false: we build and operate the agents. What the platform still does not do is *publish an
> authoring framework* for customers to write against, and it still runs every agent behind an
> adapter so the vendor SDK stays swappable. The filename is unchanged deliberately — the
> decision did not change, only two of its reasons. See `synthesis/scope-reconciliation.md` §7.

- **Status:** Accepted (2026-08-26, Phase 5) — 13 projects. Narrowed to two RPCs with durability in the control plane (amended 2026-08-27; four methods was AX's shape); extended to every stateful concern shipping an in-memory sibling.
- **Amended:** 2026-08-27 — `sdk_in_process` only; boundary retained for SDK swappability, not third-party adoption. See `synthesis/scope-reconciliation.md` §7.
- **Amended:** 2026-08-27 (redo 4) — **one harness, on Pydantic AI 2.35.0**; the two-SDK plan is superseded. See §7d.
- **Date:** 2025-08-26
- **Supersedes:** —
- **Superseded by:** —

## Context

Written before the teardown as a strawman to be attacked. Phase 2 drafts these
from three deep probes; Phase 3 runs the remaining projects against them. Each
pass must record `confirms`, `amends`, `challenges` or `neutral` in its
`facts.yaml` `adr_impact`.

A provisional ADR is a hypothesis with a falsification condition, not a
commitment.

## Decision

Execution is delegated to pluggable adapters behind one interface. *(Amended 2026-08-27: the adapter boundary is retained so the vendor SDK underneath stays swappable, not to admit foreign agents. The original list named four third-party harnesses and raw containers (superseded 2026-08-27); only `sdk_in_process` ships.)* Vendor SDKs, A2A endpoints and raw containers are all adapters.

## Rationale

*(Amended 2026-08-27: this read "Framework neutrality is the product thesis." It is not — the thesis is a SaaS platform where we build and operate the agents. The adapter boundary survives for a narrower reason: it keeps the vendor SDK underneath swappable. The decision stands; its justification changed.)* Owning an agent framework means competing with every framework instead of orchestrating them.

## Implications

- The adapter interface is one of the most important in the system.
- Lowest-common-denominator risk: not all harnesses can checkpoint.
- Capability negotiation needed so adapters can declare what they support.
- Cancellation and resume semantics must degrade gracefully.

## Falsification

If harness capabilities diverge so far that the common interface becomes useless, a narrower supported set beats a leaky abstraction.

## Deciding probes

`E1`, `E2`, `E3`, `E7`, `E8`, `B1`

## Amendment — 2026-08-26 (Phase 3, Google AX): narrow the adapter interface

The strawman interface sketched in the original plan was:

```python
class AgentRuntime:
    async def start(...)      async def send(...)
    async def events(...)     async def cancel(...)
    async def checkpoint(...) async def restore(...)
    async def terminate(...)
```

Google AX's equivalent has four methods (upstream precedent; ours is two RPCs, amended 2026-08-27)
(`internal/harness/harness.go:42-63 @ b777313`):

```go
type Harness interface {
    Start(ctx, conversationID string, config []byte) (Execution, error)
}
type Execution interface {
    Run(ctx, handler Handler) error       // streams events
    Queue(ctx, steps ...*proto.Step) error // send
    ID() string
    Close(ctx) error
}
```

No `checkpoint`, no `restore`. Durability lives in the controller's append-only
event log, and the adapter merely streams typed steps into it. State is
reconstructed by replaying the log, so the adapter never needs to serialise
itself.

This matters because of ADR-0012: not every harness *can* checkpoint. Putting
`checkpoint`/`restore` in the adapter interface guarantees a
lowest-common-denominator problem — either most adapters declare the capability
unsupported, or the platform cannot rely on it. Moving durability to the control
plane removes the question entirely.

**Amended target interface:**

```text
Adapter:      start(run_context, opaque_config) -> Execution
Execution:    run(handler)        stream typed events to the control plane
              send(inputs)        queue new inputs for the next turn
              cancel(reason)       typed cancellation reason
              close()
```

With two supporting rules taken from AX:

1. **Adapter config is opaque to the control plane.** AX passes `agent_config` as
   `bytes`, "opaque to the controller and interpreted by the harness
   implementation". The control plane must not parse adapter configuration.
2. **Specify the stream contract precisely.** AX documents that the server streams
   "zero or more `HarnessResponse{outputs}` frames terminated by exactly one
   `HarnessResponse{end}`". Stating the terminator count is what makes a
   a second adapter implementable from the contract alone (2026-08-27) without reading the reference
   implementation.

Checkpoint/restore may still exist as a *declared optional capability*
(ADR-0012) for harnesses that support it as an optimisation, but the platform's
correctness must not depend on it.

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | confirms | `libs/checkpoint-conformance/.../capabilities.py @ 3803173` | Supplies the capability-negotiation pattern: BASE vs EXTENDED capabilities, runtime detection via method-override check, spec tests gated on detected set. Adopt this shape for harness adapters. |
| OpenHands | confirms | `src/constants/acp-providers.ts:82-92 @ f48eca6` | Strongest evidence yet: own agent is a peer of foreign ACP agents behind one enum, with a registry of launch commands. Plus a concrete failure mode - a plausible but wrong ACP command silently DEADLOCKS the handshake, so adapters need validation not just configuration. |
| Letta | amends | `src/permissions/canonical.ts @ 852ca24`; `src/permissions/cross-agent-guard.ts:6-8 @ 852ca24` | Letta is a harness not a host, yet still pays adapter tax: `canonicalToolName` must map Codex/Gemini aliases onto one vocabulary INSIDE the policy layer. Tool-name canonicalisation is a prerequisite for policy under adapter neutrality, not an afterthought. |
| Google AX | confirms | `internal/harness/harness.go:42-63 @ b777313` | **Cleanest adapter contract in the study:** `Harness{Start}` → `Execution{Run, Queue, ID, Close}`. Four methods, and durability is held by the *controller's event log*, not the adapter. Our strawman `AgentRuntime` had seven methods including `checkpoint`/`restore`; AX shows those belong in the control plane. Narrow the interface accordingly. |
| Omnigent | confirms | `omnigent/harness_capabilities.py:24-31 @ ba9e371` | `IntegrationMode`'s five values are the clearest statement of the adapter problem found anywhere: `SDK_IN_PROCESS`, `CLI_SUBPROCESS`, `ACP_SUBPROCESS`, `NATIVE_TUI`, `NATIVE_SERVER`. **`NATIVE_TUI` extends the space I had considered** — you can bring an agent with *no* integration surface under one policy layer by wrapping its terminal and mirroring its approval pane (`Elicitation.APPROVAL_MIRROR`). Our adapter taxonomy should carry this enum. |
| Cloudflare Agents | challenges | `design/durable-object-lifecycle.md @ 2f957bc` | **The one genuine challenge to this ADR in the study.** There is *no* adapter contract, because the premise is that you write the agent as an `Agent` subclass; extension happens through `Lifecycle` capability composition, not adaptation. This is a coherent alternative, and a strong one: it buys enormous integration depth — durability, hibernation, storage and tracing all ambient — at the cost of never being able to run someone else's agent. **Our justification must therefore be that adapting existing agents is a hard requirement, not a preference.** If it is merely a preference, this design is better. |
| AG2 | neutral | `ag2/acp/config.py @ 90f490a` | No harness adapter contract in the AX/Omnigent sense. `ChannelAdapter` is a *protocol* adapter (conversation, discussion, consulting, workflow), not a runtime adapter — though `acp/` does drive Claude Code, Codex, KiloCode and OpenCode. |
| Pydantic AI | confirms | `pydantic_ai_slim/pydantic_ai/durable_exec/AGENTS.md @ b48ee38`; `durable_exec/_base.py:38-45` | **Confirms from the other direction.** Every other project adapts *agents*; Pydantic AI adapts *durability engines*, treating Temporal/DBOS/Prefect/Restate as "first-class compatibility targets... **not peripheral adapters**", with written rules requiring run context, deps, message history, retries, model selection and toolset lifecycle to survive the boundary. Two transferable lessons: **cross a boundary with an identifier, not an object** (a `Model` is unserializable, so a `model_id` crosses and resolves through a registry), and **make serializability a project rule** so new features cannot quietly break the boundary. |
| Google Agent Platform | confirms | `src/google/adk/memory/base_memory_service.py @ 85b52f6`; `src/google/adk/sessions/base_session_service.py` | **Most consistent application of the pattern in the study, generalised beyond runtimes.** `BaseSessionService`, `BaseMemoryService`, `BaseArtifactService`, `BaseCredentialService`, `BaseCodeExecutor`, `BaseEvalService`, `BaseCredentialExchanger`, `BaseCredentialRefresher`, `BaseEventsSummarizer` — each with an `InMemory*` implementation **and** a managed one. The transferable lesson is the in-memory sibling: **if every pluggable interface ships a working local implementation, the development path and the production path are the same code with a different injection** — not a mock, not a separate mode. |
| HumanLayer | confirms | `hld/session/claudecode_wrapper.go @ 99abe67`; `claudecode-go/` | An `attached_harness` wrapping Claude Code behind a `ClaudeSession` interface, with **the daemon owning durability on the agent's behalf** — the transcript, the approvals, the reconciliation. Same split AX established: control plane owns the log, the adapter streams events. One vendor rather than a general contract, so the seam is real but narrow. |
| AWS AgentCore | neutral | `src/bedrock_agentcore/runtime/ @ 826416a` | A client SDK over managed services, not an adapter contract. |
| Microsoft Agent Framework | neutral | `python/packages/ @ e34bf48` | Not an adapter contract for agents — `Executor` is the node abstraction and agents are written against the framework. The wide provider surface (anthropic, gemini, bedrock, ollama, mistral, copilotstudio…) adapts *models*, not agents. |
| Agent Control | confirms | `README.md @ 7cb21af` | The adapter thesis applied to *policy* rather than execution: framework adapters for LangChain, CrewAI, Google ADK and AWS Strands mean it governs runtimes it did not author, via a `@control()` decorator. **The only project in the study built on the assumption that it is not the whole platform** — which is exactly why it is integrable. |
| **Product decision 2026-08-27** | amends | `synthesis/scope-reconciliation.md` §7 | SaaS repositioning: we build and operate the agents on a thin internal harness over the vendor SDKs, so `integration_mode` narrows to `sdk_in_process` and the other four modes are reserved-not-shipped. Recorded as **amends, not challenges**: the adapter boundary is *kept*, because its remaining job is to keep the SDK underneath swappable (Claude Agent SDK → OpenAI Agents SDK) rather than to admit foreign agents. The Cloudflare objection — ambient durability costs you the ability to run others' agents — no longer binds, since running others' agents is no longer a requirement. |
| **Product decision 2026-08-27 (redo 4)** | amends | `projects/pydantic-ai/teardown.md:45-50,58,218,245 @ b48ee38`; `pydantic_ai_slim/pydantic_ai/agent/__init__.py:2423`; `models/`, `providers/`, `capabilities/` | **One harness, on Pydantic AI 2.35.0**, replacing "Claude Agent SDK then OpenAI Agents SDK". Five reasons, each checked against the source rather than the recon: (1) one harness to build, spec and adapt instead of two; (2) **model-agnostic** — **16 provider model modules** in `models/` (anthropic, bedrock, cerebras, cohere, crusoe, google, groq, huggingface, mistral, ollama, openai, openrouter, snowflake, xai, zai, bedrock_mantle) alongside **36 files in `providers/`**, with the remaining `models/*.py` being private helpers or wrappers (`_abstract`, `fallback`, `instrumented`, `wrapper`, `test`, `function`) — so model choice is a tenant/bundle setting and the "no model gateway" boundary holds because we do not own the abstraction. *(Corrected 2026-08-27: an earlier version said "30 provider modules", which was a file count of `models/*.py` and included non-providers.)*; (3) **no durable-state authority of its own** — it integrates Temporal, DBOS and Prefect as "first-class compatibility targets, not peripheral adapters", so it cannot compete with our run log. LangGraph was rejected for the opposite reason: its checkpointer *is* a second authority, and its silent resume across a changed graph is the failure I verified by running it, which ADR-0011 exists to prevent; (4) tools are **registered Python functions** — the `tool` decorator's implementation is at `agent/__init__.py:2423`, with `@agent.tool` usage documented at `:2460`; `:2399` is an `@overload` type stub, cited in error in the first version of this row — so the `ToolCall → ledger` boundary looked like a **decorator**. **Corrected 2026-08-27 by spike 06: it is a TOOLSET.** `ExternalToolset.call_tool` raises unconditionally (`toolsets/external.py:44`) while the tool is still advertised to the model (`:36`), so the SDK is never given an executable body — nothing to wrap, nothing to disable. `@agent.tool` is never used by Phoenix; the spike's negative control shows it *is* the bypass; (5) three of its patterns are **already ported**: `TestModel` as the in-memory sibling, the `_ssrf.py` guard, and `CapabilityPosition`. **Cost, stated precisely:** Pydantic AI already supplies the **seams** — `capabilities/hooks.py`, `capabilities/process_history.py` (the compaction seam), `capabilities/wrapper.py`, `toolsets/` for nested agents, and `CapabilityPosition` for ordering. What Phoenix owns is the **policy over those seams**: which history-processing strategy runs and when, how a delegated agent inherits a `Principal` and a pinned bundle, which hooks fire into the effect ledger, and how context is assembled from the compiled bundle. That is control-plane integration, not reimplementation. *(Corrected 2026-08-27: an earlier version said compaction, subagent orchestration and hooks are "ours to build", which overstated it — the primitives exist.)* The harness remains a **component** rather than a thin shim (spec 12). The adapter boundary is retained so a second SDK can be added later. |

## Open questions

-
