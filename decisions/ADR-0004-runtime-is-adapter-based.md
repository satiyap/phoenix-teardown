# ADR-0004 — Agent runtime is adapter-based; the platform does not author agents

- **Status:** Provisional (pre-evidence, Phase 0)
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

Execution is delegated to pluggable harness adapters behind one interface. Claude Code, Codex, OpenHands, LangGraph, A2A endpoints and raw containers are all adapters.

## Rationale

Framework neutrality is the product thesis. Owning an agent framework means competing with every framework instead of orchestrating them.

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

Google AX's equivalent is four methods
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
   third-party adapter implementable without reading the reference
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

## Open questions

-
