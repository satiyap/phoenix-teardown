# ADR-0003 — Messages are first-class durable resources

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

Inter-principal messages are persisted, addressable, ordered within a scope, and independently retrievable — not transient function arguments.

## Rationale

Durable messages are the substrate for audit, replay, human-visible collaboration and asynchronous delegation. In-memory messaging cannot support any of those.

## Implications

- Message store needed with defined ordering guarantees.
- Requires a delivery-semantics decision (at-least-once assumed).
- Needs dead-letter handling (see S7).
- Message volume becomes a storage sizing concern.

## Falsification

If durable messaging proves to be write-amplification with no consumer, a lighter event log plus ephemeral delivery may suffice.

## Deciding probes

`A6`, `F5`, `F6`, `F7`, `F9`, `S7`

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | confirms | `libs/checkpoint/langgraph/checkpoint/base/__init__.py:92 @ 3803173` | Multi-agent = shared mutable channel state. No mailbox, ordering, delivery guarantee or correlation ids. |
| OpenHands | confirms | `openhands-agent-server/.../sub_agents_router.py:117 @ 760eea2` | Delegation is a nested conversation, not a message. No mailbox, no ordering, no delivery guarantee between agents. |
| Letta | amends | `src/channels/ @ 852ca24` vs `src/agent/subagents/ @ 852ca24` | Excellent HUMAN channels (Slack/Discord/Telegram with access control, threads, mentions, durable approvals) and ZERO agent-to-agent messaging. Suggests human collaboration surfaces and agent transport are different problems; one `Channel` resource for both may be a modelling error. |
| Google AX | confirms | `proto/ax.proto @ b777313` | No agent-to-agent messaging, and no subagents at all. **Four for four absent.** The case for building durable agent messaging now rests entirely on our own requirements, with zero prior art. |

## Open questions

-
