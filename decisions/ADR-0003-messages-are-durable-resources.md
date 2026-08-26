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

## Amendment — 2026-08-26 (Phase 3, AG2): from no precedent to a design to copy

This ADR spent most of the study as the weakest in the set. Phase 2 recorded that
the entire F-section was `absent` in all three anchors, so it had to be justified
from requirements rather than precedent. Google AX, Omnigent and Cloudflare Agents
each made that worse — seven projects, zero implementations, including two products
built specifically for multi-agent work. I had drafted a rewrite that abandoned
durable messaging in favour of the shared-substrate pattern every project actually
used, and reduced AG2's reading budget on the assumption it would only confirm the
consensus.

**AG2 1.0's `ag2.network` implements the entire thing, and better than this ADR
specified.**

### The precedent

`ag2/network/envelope.py:5-11 @ 90f490a`:

> Every Agent-to-Agent exchange happens inside a channel and the carrier is an
> `Envelope`. Envelopes are JSON-serialisable, hub-stamped at `post_envelope`, and
> persisted to the per-channel WAL. `audience` is the addressing primitive: `None`
> broadcasts within the channel, a list targets a subset.

The envelope shape, verified live against 1.0.2:

```text
channel_id, sender_id, audience, event_type, event_data,
envelope_id, task_id, causation_id, trace_id, priority,
depth, idempotency_key, created_at, ttl_seconds
```

Four fields I had not thought to include:

| Field | Why it matters |
|---|---|
| `causation_id` | Threads replies to prompts, **and doubles as the dedupe key** (ADR-0014) |
| `depth` | Delegation hop count, hub-incremented on the reply path, capped by `Rule.limits.delegation_depth` (default 5). **Runaway delegation bounded by the platform, not by prompts.** |
| `ttl_seconds` | Per-envelope expiry, deferring to the channel's `expires_at` when unset |
| `priority` | `background \| normal \| urgent` |

And three properties of the surrounding system worth adopting wholesale:

1. **The WAL stores the full envelope regardless of addressing** — "audit + debug"
   — while `notify` lands only on listed peers. **Audit scope is deliberately
   wider than delivery scope**, because a log that only recorded deliveries could
   never show what was withheld from whom.
2. **Delivery is at-least-once and says so**, with a real dedupe mechanism rather
   than a hopeful guarantee (see ADR-0014).
3. **The network is opt-in.** "Importing it is opt-in — bare `Agent` continues to
   work standalone with no behavioural change when this package is not imported."
   The durable multi-agent path is *additive*.

### Amended decision

Messages remain durable resources, and the design now follows AG2's envelope
closely rather than being invented:

```text
Envelope
  channel_id       the addressable conversation
  sender_id        principal (agent OR human — see ADR-0007)
  audience         null = broadcast in channel; list = targeted subset
  event_type       from a closed set of meaningful names; open for user types
  event_data       typed per event_type
  envelope_id      stamped by the authority on accept, never by the sender
  causation_id     what this responds to; also the reply dedupe key
  task_id          links the message to durable work
  trace_id         trace context rides the message
  depth            hop count, incremented by the authority, capped by policy
  priority         background | normal | urgent
  ttl_seconds      per-message expiry, defaulting to the channel's
  idempotency_key  for externally-triggered effects (ADR-0014)
  created_at       stamped on accept
```

Plus four rules taken from AG2:

1. **The authority stamps identity and increments depth**, never the sender. A
   sender cannot forge an envelope id or reset its own hop count.
2. **The log records every accepted envelope in full**, independent of who was
   notified.
3. **Event type names are a closed set in code** — "new names are added in code,
   not at runtime" — while arbitrary user-defined types may be *carried*. An open
   namespace with a closed set of *meaningful* names.
4. **Channels declare a protocol** (conversation, discussion, consulting,
   workflow) with expected-turn enforcement, so "who speaks next" is a channel
   property the authority enforces, not an emergent property of prompts. Violations
   are events (`EV_EXPECTATION_VIOLATED`), and `can_send()` is a public probe.

### The methodological lesson, recorded against myself

The Phase 3 interim findings called AG2 "downgraded in value" and said "the
question is nearly settled; AG2 now serves to confirm rather than decide." That
judgement rested on a seven-project tally and a Phase 1 recon that predated AG2
1.0. Acting on it would have cut the one subsystem with a strong, tested precedent
and replaced it with a weaker pattern.

**A convergence across N projects is evidence about what is common, not proof
about what is possible.** Absence in seven systems built for adjacent purposes
said those systems did not need durable agent messaging — not that it is
unbuildable or unnecessary. Budget a project by what it is *architected to answer*,
not by how confident the running tally has made me.

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | confirms | `libs/checkpoint/langgraph/checkpoint/base/__init__.py:92 @ 3803173` | Multi-agent = shared mutable channel state. No mailbox, ordering, delivery guarantee or correlation ids. |
| OpenHands | confirms | `openhands-agent-server/.../sub_agents_router.py:117 @ 760eea2` | Delegation is a nested conversation, not a message. No mailbox, no ordering, no delivery guarantee between agents. |
| Letta | amends | `src/channels/ @ 852ca24` vs `src/agent/subagents/ @ 852ca24` | Excellent HUMAN channels (Slack/Discord/Telegram with access control, threads, mentions, durable approvals) and ZERO agent-to-agent messaging. Suggests human collaboration surfaces and agent transport are different problems; one `Channel` resource for both may be a modelling error. |
| Google AX | confirms | `proto/ax.proto @ b777313` | No agent-to-agent messaging, and no subagents at all. **Four for four absent.** The case for building durable agent messaging now rests entirely on our own requirements, with zero prior art. |
| Omnigent | confirms | `omnigent/server/routes/comments.py:343-360 @ ba9e371` | No agent-to-agent messaging — **six for six**, and this from a product whose headline feature is supervising multiple agents. Agents relate through parentage (`parent_conversation_id`) and shared `session_state`, never by sending messages. `send_to_agent` is human→agent (formats file-anchored review comments for a person to send). **Decisive: durable agent messaging must not be in v0.1.** |
| Cloudflare Agents | confirms | `packages/channels/src/identity.ts:1-8 @ 2f957bc`; `design/channels.md`; `design/rfc-sub-agents.md` | **I expected the first counter-evidence here** — there is a `@cloudflare/channels` package and a channels design doc. It is **human↔agent** transport: Slack, Telegram, email and voice adapters, with `ChannelIdentity{channelKey, scope, subject}` naming a *human* correspondent. Sub-agents communicate by **typed RPC** (`await searcher.search(q)`), and coordination goes through shared parent state. **Seven for seven absent.** Four projects have now independently chosen shared-substrate coordination. ADR-0003 should be rewritten around that pattern rather than defending a message bus nobody builds. |
| AG2 | confirms | `ag2/network/envelope.py:5-11,94-131 @ 90f490a`; `ag2/network/hub/core.py:2626-2644`; verified: 39 tests pass | **This reverses the seven-project consensus and vindicates the ADR.** `ag2.network` is "agent registry, durable messaging, and protocol-driven channels": hub-stamped `Envelope`s persisted to per-channel **append-only WALs**, `audience` as the addressing primitive (`None` broadcasts, a list targets), at-least-once delivery with causation-based dedupe, `depth` delegation caps, per-envelope TTLs, priorities, inbox backpressure, and access rules enforced hub-side. The envelope carries `causation_id`, `depth`, `priority`, `ttl_seconds`, `trace_id` and `idempotency_key` — **richer than my strawman**. Verified: 39 tests pass. **I had drafted a rewrite dropping messaging from v0.1 on the strength of seven absences; that would have been a serious error.** |
| Pydantic AI | confirms | `pydantic_ai_slim/pydantic_ai/agent/ @ b48ee38` | No agent-to-agent messaging; agents call agents as functions or tools. AG2 remains the sole precedent. |
| Google Agent Platform | confirms | `src/google/adk/agents/ @ 85b52f6` | No durable agent-to-agent messaging. Composition is `SequentialAgent`/`ParallelAgent`/`LoopAgent`, agent-as-tool, and LLM-driven transfer, with coordination through shared session `State`. AG2 remains the sole precedent. |
| HumanLayer | confirms | `hld/store/sqlite.go:373-405 @ 99abe67` | No agent-to-agent messaging. `parent_tool_use_id` (migration 6, "for sub-task tracking") gives a sub-task tree within a session. AG2 remains the sole F-section answer. |
| AWS AgentCore | confirms | `src/bedrock_agentcore/runtime/a2a.py @ 826416a` | No durable agent-to-agent messaging; A2A appears only as an edge adapter. AG2 remains the sole precedent. |
| Microsoft Agent Framework | amends | `python/packages/core/agent_framework/_workflows/_checkpoint.py:54 @ e34bf48` | **A genuinely different answer from AG2's, and worth stating precisely.** Messages between *executors* are a named part of the workflow checkpoint, so intra-graph agent messaging is durable **because the workflow is**. AG2's envelope is durable independently of any orchestration; MAF's messages exist only inside a checkpointed graph. There is no mailbox, addressing, or delivery guarantee outside one. **The amendment: if all agent interaction happens inside an orchestration we already checkpoint, message durability comes free** — a cheaper v0.1 option than a full messaging substrate, at the cost of agents that cannot talk outside a graph. |

## Open questions

-
