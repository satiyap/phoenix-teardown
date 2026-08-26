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

## Open questions

-
