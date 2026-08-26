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

## Amendment — 2026-08-26 (Phase 3, ADK): principals and credentials are different subsystems

This ADR has been treating "who is acting" and "what secrets the action carries"
as one concern. ADK proves they are separable, because it has one and not the
other.

**What ADK has** (`src/google/adk/auth/ @ 85b52f6`): five typed credential kinds
(`apiKey`, `http`, `oauth2`, `openIdConnect`, `serviceAccount`), OpenAPI-derived
auth schemes, OIDC discovery, **exchange and refresh as separate registries**
(`BaseCredentialExchanger` / `BaseCredentialRefresher`, each with an OAuth2
implementation and a registry), a `credential_manager`, an `auth_preprocessor`
that injects credentials into tool calls, and a pluggable `BaseCredentialService`
with in-memory and session-state backends.

**What ADK does not have**: any principal. No caller identity, no authentication
of an inbound request, no authorization model. The storage layer prevents
*accidental* cross-tenant reads via a composite primary key, but nothing verifies
that a caller is entitled to the `user_id` it passes.

Across the study the two concerns separate cleanly:

| Project | Principals (inbound authority) | Credentials (outbound secrets) |
|---|---|---|
| Omnigent | **strong** — users, `SessionPermission` levels, RFC 8628 delegated grants with revocation | **strong** — secretless proxy, host-bound placeholders |
| AG2 | **strong** — `Passport` with `kind: agent \| human \| remote_agent`, hub-enforced rules | weak — `AuthBlock.scheme` is `"none" \| future schemes` |
| **ADK** | **absent** | **strongest in the study** |
| Cloudflare | absent (a developer hook) | absent |
| Pydantic AI | absent | absent (but blocks credential *theft* via SSRF guard) |

Omnigent and AG2 have principals; ADK has credentials; none has both well.

**Amended decision.** Two subsystems, specified separately:

**1. `Principal`** — who is acting.

```text
Principal
  id, kind: human | agent | service | delegated
  authenticated_by      how identity was established
  granted               what this principal may do (policy input)
  delegation_chain      on_behalf_of, with depth bounded (AG2's `depth`)
  revoked_at            revocation is a lifecycle state, not a delete
```

Every request carries a principal. Policy decisions (ADR-0013) take it as input.
Audit records it. Following AG2, humans and agents are the *same* type with a
`kind` discriminator, each addressable and each subject to rules.

**2. `Credential`** — what an action carries outward.

```text
Credential
  kind: api_key | http | oauth2 | oidc | service_account
  scheme, issuer, audience
  obtained_by     an Exchanger (separate interface)
  kept_alive_by   a Refresher (separate interface)
  stored_in       a CredentialService (pluggable; session-scoped is valid)
  never enters a sandbox in plaintext (Omnigent's proxy, ADR-0009)
```

**The rule taken from ADK: exchange and refresh are separate interfaces.**
Obtaining a credential and keeping it alive have different failure modes,
different triggers, and different retry semantics. Systems that model them as one
"get a token" call push refresh onto every tool author.

**The relationship between them.** A principal *authorises* the use of a
credential; a credential is never itself an identity. Conflating them is how
systems end up treating possession of an API key as proof of identity, which is
precisely the failure the SSRF guard in ADR-0009 exists to prevent — an agent that
can read IMDS gains the instance's credentials, and if credentials are identity, it
gains the instance's identity.

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
| Pydantic AI | neutral | `pydantic_ai_slim/pydantic_ai/ @ b48ee38` | No principals of any kind. |
| Google Agent Platform | challenges | `src/google/adk/auth/ @ 85b52f6`; `src/google/adk/auth/auth_credential.py:232-252` | **Splits this ADR in a way I had not considered.** ADK has an excellent model of **credentials the agent carries outward** — five typed kinds (`apiKey`, `http`, `oauth2`, `openIdConnect`, `serviceAccount`), OIDC discovery, exchange and refresh as *separate* registries, a credential manager, an `auth_preprocessor` injecting into tool calls, and a pluggable credential service — and **no model of authority flowing inward**: no principals, no authorization. Our ADR conflates these. **A `Principal` model (who is acting, how they authenticated, what they may do) and a `Credential` model (what secrets an action carries outward, how they are obtained and refreshed) are different subsystems**, and a platform can have one without the other. ADK proves it. |
| HumanLayer | challenges | `hld/store/sqlite.go:201-217 @ 99abe67` | **Sharpens the split ADK prompted, from the opposite side.** HumanLayer has the best approval *record* in the study — durable, status-constrained, idempotent, indexed, with a rationale — and **no approver identity at all**. The `comment` column says *why* a decision was made, never *who* made it, because a 0600 Unix socket makes the operator implicit. So a system can have durable, well-designed human decisions and still be unable to answer "which human approved this". **Our `Approval` must reference a `Principal`, not merely carry a note.** Together with ADK (credentials without principals) this makes the principal model the clearest hole in the field. |
| AWS AgentCore | confirms | `src/bedrock_agentcore/services/identity.py:140-155 @ 826416a`; `src/bedrock_agentcore/identity/auth.py:30` | **Closes the loop this ADR's amendment opened.** The amendment split `Principal` from `Credential` because ADK had credentials without principals and HumanLayer had decisions without principals. **AgentCore has both halves properly**: a *workload identity* (the principal) and *credential providers* as CRUD resources (the credential), joined by three named flows — `M2M`, `USER_FEDERATION`, `ON_BEHALF_OF_TOKEN_EXCHANGE`. Plus `UserTokenIdentifier`/`UserIdIdentifier` as distinct types so "which user" is never a bare string. **This is the reference shape for our ADR-0007.** |
| Microsoft Agent Framework | neutral | `python/packages/core/agent_framework/ @ e34bf48` | No principals in the framework; identity is Azure's, externally. |

## Open questions

-
