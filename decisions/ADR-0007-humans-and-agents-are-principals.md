# ADR-0007 — Humans and agents are distinct subtypes of Principal

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

Principal is the root security and participation abstraction, with Human, Agent and Service as subtypes. A human is not modelled as a kind of agent, but both participate in the same collaboration graph and both can hold permissions.

## Rationale

Humans and agents differ in authentication, availability, accountability and consent. Flattening them into one type makes the IAM model wrong in ways that surface late.

## Implications

- Shared participation model; separate authN paths.
- Approval and escalation are Human-specific affordances.
- Audit must distinguish human from agent action.
- Delegation across subtypes needs explicit semantics (see S1).

## Falsification

If uniform treatment demonstrably simplifies the graph without weakening audit or consent, collapse the hierarchy.

## Deciding probes

`G1`, `G5`, `J1`, `J6`, `S1`

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | confirms | `libs/sdk-py/langgraph_sdk/auth/types.py:152-202 @ 3803173` | Auth subject is `BaseUser` only. Agents cannot hold permissions, so S1 (delegated authority) is literally unposable. Validates Principal as root abstraction. |
| OpenHands | confirms | `openhands-agent-server/.../config.py:23-51 @ 760eea2` | Shared SESSION_API_KEY per agent-server, no principal model, sub-agents inherit parent workspace and secrets wholesale. S1 undefined for the second time. |
| Letta | confirms | `src/channels/access-control.ts:23-95 @ 852ca24` | Two principal types with genuinely different mechanisms. Humans: allowed/admin user lists, `dm|group` scope, and an access decision of `allow|deny|PAIR` (pending authorisation). Agents: `AGENT_ID` with kernel-enforced memory boundaries. Supports Principal as root with distinct subtypes. |
| Google AX | confirms | `internal/server/server.go:82-83 @ b777313` | Confirms negatively and starkly: no principals of any kind, and consequently **no authentication interceptor at all** — only logging. A distributed runtime that provisions sandboxes and executes arbitrary harnesses is exposed unauthenticated. Demonstrates exactly what is lost without the abstraction. |
| Omnigent | confirms | `omnigent/server/auth.py:70-81 @ ba9e371`; `designs/DEVICE_AUTH.md` | **Fullest principal model in the study**: users, accounts, `SessionPermission` levels (read/edit/owner), a `__public__` sentinel for link sharing, admin flags, and **RFC 8628 device grants** minting scope-limited delegated tokens with revocation checked per request. Delegated tokens fail closed against a path allow-list, with prefix confusion handled (`/v1/hosts/h1/runners` passes, `/v1/hostsX` does not). First answer to S1 anywhere. |
| Cloudflare Agents | challenges | `packages/agents/src/agent-routing.ts:73-84 @ 2f957bc`; `packages/agents/src/sub-routing.ts:489-491` | Ships **no principals at all**: auth is `onBeforeConnect`/`onBeforeRequest`, hooks the developer implements. Defensible for an SDK where the developer owns the edge, and unusually honest — it documents its own bypasses (`getSubAgentByName` "does not run `onBeforeSubAgent`... The caller is assumed to have performed whatever access checks are needed"). But it means every consumer reimplements authorization, which is exactly what a platform should not delegate. Confirms the ADR by demonstrating the cost of omitting it. |
| AG2 | confirms | `ag2/network/identity.py:38,69-71 @ 90f490a` | **Cleanest expression of this ADR found anywhere.** `PassportKind = agent | human | remote_agent`, where `human` is "an out-of-band non-LLM participant driven by an external UI". A human therefore has a passport, a rule, an inbox, and is addressable in `audience` exactly like an agent. Every other project either models humans in a separate subsystem or not at all; AG2 makes them the same kind of thing with a discriminator, which is what this ADR should mean in a schema. |

## Open questions

-
