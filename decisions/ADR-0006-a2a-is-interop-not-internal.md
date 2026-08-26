# ADR-0006 — A2A is an interoperability protocol, not the internal state model

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

## Open questions

-
