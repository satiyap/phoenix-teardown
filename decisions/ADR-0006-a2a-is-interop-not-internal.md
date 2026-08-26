# ADR-0006 — A2A is an interoperability protocol, not the internal state model

- **Status:** Accepted (2026-08-26, Phase 5) — 13 projects. Five independent confirmations of A2A-as-edge-adapter; southbound amended to gRPC-shaped.
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

A2A (and ACP) are implemented at the edge for external agent interop. Internal state, messaging and task lifecycle use our own model and are not defined by these wire protocols.

## Rationale

Wire protocols are consensus artifacts that move slowly and encode others' compromises. Letting one define internal state surrenders architectural control.

## Implications

- Translation layer at the boundary.
- Some A2A semantics may not map cleanly; document the gaps.
- We can support several external protocols without internal churn.

## Falsification

If A2A becomes a genuinely universal substrate and our internal model adds no expressive power, adopt it natively instead.

## Deciding probes

`O5`, `F11`, `E2`, `E3`

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | neutral | `libs/sdk-py/langgraph_sdk/schema.py @ 3803173` | No A2A, ACP or MCP in the runtime. |
| OpenHands | neutral | `src/constants/acp-providers.ts @ f48eca6` | No A2A. ACP occupies the adapter role instead, over stdio. |
| Letta | neutral | `src/ @ 852ca24` | No A2A, ACP or MCP. Letta is its own harness rather than a host for others — the inverse of OpenHands. |
| Google AX | amends | `proto/ax.proto:85-91 @ b777313` | **Answers OQ-012.** gRPC bidirectional streaming as the southbound contract means a remote harness needs no co-location, unlike OpenHands' ACP-over-stdio. Suggests our southbound API should be gRPC-shaped with ACP as one adapter *behind* it rather than as the transport itself. |
| Omnigent | confirms | `omnigent/harness_capabilities.py:27 @ ba9e371`; `omnigent/acp_cli_harnesses.py` | ACP is exactly one `IntegrationMode` among five, not the internal contract. Interop at the edge, own model inside — the ADR's position, implemented. |
| Cloudflare Agents | neutral | `packages/agents/src/agent-routing.ts @ 2f957bc` | No A2A. Interop is HTTP, WebSocket, email and MCP. |
| AG2 | confirms | `ag2/a2a/__init__.py:5-22 @ 90f490a`; `ag2/acp/__init__.py:5-12` | **Clearest independent confirmation in the study.** AG2 has a richer *internal* envelope/hub/channel model and treats A2A as an **optional-dependency edge adapter** (agent cards, gRPC transports, push notifications), degrading via `missing_optional_dependency` when uninstalled. Same for ACP. Own model inside, standard protocols at the boundary — exactly this ADR. |
| Pydantic AI | neutral | `pydantic_ai_slim/pydantic_ai/ @ b48ee38` | No A2A. UI protocols (AG-UI, Vercel AI) are the only interop surface. |
| Google Agent Platform | confirms | `src/google/adk/a2a/ @ 85b52f6` | **Second independent confirmation after AG2.** `a2a/` is a converter-and-executor interop layer (`a2a/agent`, `a2a/converters`, `a2a/executor`) marked `experimental`, wrapping A2A agents as ADK agents at the edge. The internal model is agents, sessions and events. Interop at the boundary, own model inside. |
| HumanLayer | neutral | `hld/PROTOCOL.md @ 99abe67` | No A2A. Interop is JSON-RPC 2.0 over a Unix socket, plus MCP. |
| AWS AgentCore | confirms | `src/bedrock_agentcore/runtime/a2a.py @ 826416a`; `runtime/ag_ui.py` | **Fourth independent instance** (with AG2, ADK, and AG-UI here too) of A2A as an optional edge adapter alongside a different internal model. This ADR is settled. |
| Microsoft Agent Framework | confirms | `python/packages/a2a/ @ e34bf48`; `python/packages/ag-ui/` | **Fifth independent instance** (with AG2, ADK, AgentCore, and AG-UI here) of A2A as a separate edge package beside a different internal model. Settled beyond doubt. |
| Agent Control | neutral | `sdks/ @ 7cb21af` | No A2A; integration is REST plus SDKs plus framework adapters. |

## Open questions

-
