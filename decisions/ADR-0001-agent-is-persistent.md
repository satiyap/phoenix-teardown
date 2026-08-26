# ADR-0001 — Agent identity is persistent; Run is not the Agent

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

An Agent is a durable, addressable logical actor whose identity survives process restart. Execution happens in disposable Runs on interchangeable workers. `Run != Agent`.

## Rationale

Provisional, pre-evidence. The prior is that durable actor identity is the abstraction that makes registry, delegation, policy attachment and audit coherent. Letta, Cloudflare Agents and AG2 are expected to supply the supporting evidence; LangGraph is expected to show the cost of not having it.

## Implications

- Runtime workers stay stateless and disposable.
- Agent record is authoritative, strongly consistent state.
- Requires an agent registry as a core control-plane service.
- Agent state must be separable from any single execution.

## Falsification

If mature systems converge on ephemeral agents with identity living entirely in an external orchestrator, and durable identity shows no operational benefit, this collapses into ADR-0004.

## Deciding probes

`D1`, `D2`, `D3`, `A3`, `B10`

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | challenges | `libs/langgraph/langgraph/` @ 3803173 — no `agent_id` anywhere | 40k-star runtime shipped with NO agent identity and succeeded. Durable *thread* state delivered the value. Rebase our justification on delegation, policy and audit — not durability. |
| OpenHands | challenges | `src/types/settings.ts:110 @ f48eca6` | Second system succeeding with no durable agent identity. An agent is a KIND plus a launch command (`AgentKind = openhands|acp`); identity lives on the Conversation. Two of two projects deliver value without it. |
| Letta | confirms | `src/permissions/memory-paths.ts:115-129 @ 852ca24`; `letta agents list --shared` | **Affirmative evidence at last.** Agents are addressable (`--agent`/`AGENT_ID` with documented resolution precedence), listable, fuzzy-searchable, tag-filterable and shareable. Critically, identity is a SECURITY BOUNDARY: `AGENT_ID` determines which memory tree a process may read or write, kernel-enforced. That is work a durable conversation cannot do. |
| Google AX | confirms | `internal/controller/controller.go:15,33 @ b777313`; `internal/harness/substrate/substrate.go:86-110` | First implementation of the exact model: actors keyed by conversation, suspended between turns, resumed onto **any** worker, control plane as single writer. Durable identity, disposable compute. Divergence worth noting: AX's durable identity is the *conversation*, not the agent — reinforcing that agent identity earns its place through delegation and policy, neither of which AX has. |
| Omnigent | amends | `omnigent/entities/agent.py:31-38 @ ba9e371` | Durable identity is the `Conversation`; `Agent` is a versioned *definition* bound to it (content-addressed bundle + monotonic version). Adds a distinction our model lacked: **template agents** (`session_id=None`, reusable) vs **session-scoped agents** created inline by `POST /v1/sessions`. Our `Agent` needs both. |
| Cloudflare Agents | confirms | `design/durable-object-lifecycle.md @ 2f957bc` | **Cleanest affirmative case in the study.** Identity is the Durable Object name, `ctx.id.name` is authoritative, and Lifecycle "never writes a duplicate name" (reading a legacy key only as a migration fallback). The named object exists with its storage intact whether or not it is running. And **no separate agent registry is needed, because platform naming *is* the registry** — `getAgentByName(binding, name)` resolves anything. Hibernation makes eviction routine rather than exceptional. |
| AG2 | amends | `ag2/network/identity.py:1-21,62-68 @ 90f490a` | **Best identity model in the study.** Three records back every agent: **`Passport`** — immutable, hub-stamped `agent_id`, where "mutating any field requires unregister + re-register, which yields a fresh `agent_id`"; **`Resume`** — mutable capability claims plus a hub-derived observed track record; and **`AgentRuntime`** — explicitly "cache-only" bookkeeping for the current connection. Our `Agent` should split into exactly these three: immutable identity, mutable declared+observed capability, disposable connection state. |
| Pydantic AI | neutral | `pydantic_ai_slim/pydantic_ai/agent/ @ b48ee38` | No agent identity — an `Agent` is a Python object. Appropriate for a library, uninformative for a platform. |
| Google Agent Platform | neutral | `src/google/adk/agents/ @ 85b52f6` | Agents are Python objects with a `name`; no id, registry, persistence or lifecycle. Identity of *scope* is strong — everything keyed `(app_name, user_id, session_id)` — but that is tenancy, not agent identity. |

## Open questions

- **Challenged by LangGraph (2026-08-26).** A 40k-star agent runtime shipped
  with no agent identity at all and succeeded commercially. Its durability comes
  from the *thread* (conversation/execution state), not from a persistent agent.
  This does not overturn the decision, but it removes durability as a valid
  justification for it: threads deliver resumability without any agent concept.

  The decision now has to stand on what threads cannot do — hold credentials, be
  granted capabilities, delegate authority, appear in an audit log, or be
  revoked. LangGraph corroborates this negatively: because its only principal is
  a human `BaseUser`, the S1 delegated-authority scenario cannot even be
  expressed.

  Action: restate the rationale in terms of delegation, policy and audit before
  promoting to Accepted. Watch Cloudflare Agents and Letta for whether durable
  agent identity buys anything beyond what a durable thread already provides.

- **Challenged a second time by OpenHands (2026-08-26).** Independent
  corroboration from a different architecture. Agent Canvas is explicitly a
  framework-neutral control plane, and its agent abstraction is
  `AgentKind = "openhands" | "acp"` plus a launch command
  (`src/types/settings.ts:110 @ f48eca6`). Durable identity lives on the
  **Conversation**; the agent itself is a disposable subprocess.

  Two of two deep teardowns, with quite different designs, deliver production
  value with no persistent agent. The pattern is now strong enough that this ADR
  cannot be promoted on its current rationale.

  What *both* projects lack is equally consistent: S1 (delegated authority) is
  `undefined` in both, because neither has an agent principal that could hold or
  delegate authority. In OpenHands a sub-agent simply inherits the parent's
  workspace and secrets wholesale. That is the affirmative case for this ADR, and
  it is the only case the evidence supports so far.

  Revised position to test in Phase 3: **agent identity is required for
  delegation, policy attachment and audit — not for durability.** Cloudflare
  Agents (durable actors) and Letta (stateful agents with identity) are the
  projects most likely to either supply the missing affirmative evidence or
  confirm that identity is only worth it once delegation is in scope.

- **RESOLVED by Letta (2026-08-26).** The revised position holds, and the
  evidence is affirmative rather than inferred.

  Letta's agents are addressable (`--agent <id>`, `AGENT_ID`, with a documented
  resolution precedence), listable, fuzzy-searchable, tag-filterable and
  shareable across users. More importantly, identity is a **security boundary**:
  `AGENT_ID` determines which memory tree a process may read or write, and the
  enforcement point is a kernel filesystem sandbox that fails closed rather than
  degrading (`src/permissions/memory-paths.ts:115`,
  `src/memory-confinement.ts:14-21 @ 852ca24`).

  That is work a durable conversation cannot do. A thread can carry state; only
  an identity can be granted authority, be scoped against another identity, and
  appear in an audit record as the actor. Letta is also the only project in the
  study where S1 (delegated authority) is answerable at all — a subagent's
  authority is exactly `{self, parent}`, derived from `LETTA_PARENT_AGENT_ID` and
  unbypassable by policy modes.

  **Rationale is therefore restated** (see Decision/Rationale above, which should
  be edited on promotion): agent identity exists to support delegation, policy
  attachment and audit. Durability of execution state is a separate concern,
  adequately served by a durable Task/Run and conversation state. Two projects
  succeeded without agent identity precisely because they never needed delegated
  authority; the moment Letta did, it needed identity.

  Ready for promotion to Accepted at Phase 5 on these grounds. Remaining gap:
  none of the three deep projects has agent *versioning* or *revocation*, so
  `AgentVersion` and the revocation lifecycle in the domain model still lack
  precedent (watch Cloudflare Agents and Google AX).
