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
| Google AX | neutral | `proto/ax.proto:165-211 @ b777313` | No MCP. Tools appear only as opaque step types the harness owns; AX observes but does not mediate them. |
| Omnigent | confirms | `omnigent/runner/proxy_mcp_manager.py @ ba9e371`; `omnigent/harness_capabilities.py:124-141` | MCP appears as declarations in the agent image plus a manager and a proxying manager, while capabilities are modelled in a completely separate 16-axis type. The clearest separation of protocol from capability model in the study. |
| Cloudflare Agents | confirms | `design/retries.md @ 2f957bc`; `packages/agents/src/mcp/` | MCP as protocol, and extended in a way no other project manages: connection state is **persisted** in a `server_options` JSON column "so it persists across hibernation", with per-server retry config and OAuth re-establishment on reconnect. If MCP servers are long-lived resources, their connection state belongs in durable storage. |
| AG2 | confirms | `ag2/acp/tool_gateway.py @ 90f490a`; `ag2/network/identity.py:144-160` | MCP appears as `mcp/`, `mcp_ui/`, and an ACP `tool_gateway`, while the capability model is the `Resume` — an entirely separate structure with claimed and observed capabilities. Protocol and capability model cleanly distinct. |

## Open questions

-
