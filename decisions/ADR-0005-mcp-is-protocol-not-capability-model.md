# ADR-0005 — MCP is a tool protocol; Capability is the platform abstraction

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

MCP is adopted as a transport for tool invocation. The authorisation, policy and approval unit is a Capability, which is protocol-independent and may be implemented by MCP or otherwise.

## Rationale

Policy must outlive protocol churn. Binding governance to MCP server identity couples permissions to an implementation detail.

## Implications

- Capability registry distinct from tool/server registry.
- Capability -> implementation mapping layer required.
- Policy evaluated at capability granularity.
- Same capability can have several implementations.

## Falsification

If MCP's own scoping evolves to express capability-level policy adequately, the extra layer is redundant indirection.

## Deciding probes

`I1`, `I2`, `I8`, `O5`

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | neutral | `libs/langgraph/langgraph/prebuilt @ 3803173` | No capability model; tools are Python callables bound statically. MCP handled outside the runtime. Note vocabulary collision: their `Capability` enum means checkpointer storage ops. |
| OpenHands | confirms | `openhands-agent-server/.../mcp_router.py:699-790 @ 760eea2` | MCP integrated as a protocol with a full OAuth flow, while policy lives elsewhere (PreToolUse hooks, ConfirmationPolicy, SecurityRisk). Exactly the split this ADR proposes. |
| Letta | neutral | `src/tools/schemas/ @ 852ca24` | No MCP in the read tree. Tools are native, with schema and description as separate artifacts. |

## Open questions

-
