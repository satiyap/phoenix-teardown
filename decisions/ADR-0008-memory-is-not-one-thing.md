# ADR-0008 — Agent memory, task context and workspace knowledge are separate

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

Context is decomposed into ephemeral execution context, task context, agent memory, workspace knowledge, user context and enterprise knowledge. Each has its own owner, lifetime and permission model. None of these is called 'memory' generically.

## Rationale

Ownership and permissions differ per type. One 'memory' bucket makes sharing and expiry policy impossible to express, and is the most common conflation in this product category.

## Implications

- Six context types to specify, with an owner named for each.
- Cross-type retrieval needs an assembly step at prompt time.
- Permissions attach per type, not globally.
- Provenance tracking required to keep types from bleeding together.

## Falsification

If Letta and others show a unified store with typed views is sufficient, the split is a modelling exercise with no payoff.

## Deciding probes

`H1`, `H2`, `H3`, `H4`, `H5`, `S4`, `S6`

## Amendment — 2026-08-26 (Phase 3, ADK): the mechanism, at last

Seven projects reported "no memory service", which made this ADR's claim easy to
assert and impossible to specify. ADK is the eighth, it *has* one, and it confirms
the claim by dividing memory more finely than the ADR did.

**Two independent subsystems, not one:**

**1. A memory service for semantic recall** (`memory/base_memory_service.py`):

```text
BaseMemoryService
  add_session_to_memory(session)
  add_events_to_memory(app_name, user_id, events, session_id, custom_metadata)
  add_memory(...)
  search_memory(app_name, user_id, query) -> SearchMemoryResponse
```

Scoped `(app_name, user_id)` on every call. Implementations: in-memory, Vertex AI
Memory Bank, Vertex AI RAG. And `MemoryEntry` carries **`author`** and
**`timestamp`**, the latter documented as "when the original content of this memory
happened" — *event* time, not storage time. That is the provenance the Knowledge
node needed and had no precedent for.

**2. Four state scopes, distinguished by key prefix** (`sessions/state.py:64-66`):

| Prefix | Scope | Lifetime |
|---|---|---|
| `app:` | application-wide, all users | durable |
| `user:` | one user, across sessions | durable |
| *(none)* | one session | durable, **and schema-validated** |
| `temp:` | one invocation | **never persisted** |

I verified the `temp:` exclusion is independently enforced in three backends
(`firestore_session_service.py:565`, `_redis_session_service.py:128,214`), not just
documented.

**Amended decision.** Our memory model has these parts, and they are not
interchangeable:

1. **Knowledge** — filesystem/git-backed skills and documents. Settled by seven
   projects of convergence (Letta, OpenHands, AX, Omnigent, Cloudflare, AG2,
   Pydantic AI all chose files over a service).
2. **Recall** — a semantic memory *service* behind an interface, scoped to
   `(tenant, principal)`, whose entries carry `author` and *event* timestamp. ADK is
   the only precedent; adopt its interface shape.
3. **State**, in four scopes: tenant-wide, principal-wide, run-scoped, and
   **explicitly non-durable**.

Three rules follow:

- **Mark non-durable state in the key.** `temp:` makes "this will be lost on
  resumption" visible at the point of use rather than in documentation. ADK pairs
  this with `ResumabilityConfig`'s warning that "any temporary / in-memory state
  will be lost upon resumption" — the prefix is what makes that warning actionable.
- **Validate the run's own state against a declared schema**, while leaving the
  scoped namespaces open. ADK raises `StateSchemaError` for an undeclared or
  mistyped key in unprefixed state, and deliberately exempts prefixed keys. The
  closed contract is the part *this* run owns; the open namespaces are shared.
- **Distinguish event time from storage time** on every recall entry. A memory that
  only knows when it was written cannot be ordered against the conversation it came
  from.

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | confirms | `libs/checkpoint/langgraph/store/base/__init__.py:708,545 @ 3803173` | Checkpointer (execution state) vs BaseStore (cross-thread memory) vs BaseCache is a real, useful separation with TTL and namespaces. BUT no permissions (H4) and no provenance (H5) — namespaces look like an isolation boundary and are not one. |
| OpenHands | amends | `openhands-agent-server/.../skills_router.py:62-125 @ 760eea2` | Condensation-only context management with no long-term or shared memory. But org-level skills loaded from a git repository suggest organizational knowledge may be better served by versioned git-backed instructions than by a memory store. |
| Letta | confirms | `src/tools/descriptions/Memory.md @ 852ca24`; `src/memory-confinement.ts:14-21 @ 852ca24` | **Strongest H-section evidence in the study.** Memory separated by RESIDENCY COST (`system/**` always in prompt vs metadata-only-until-read) and by OWNERSHIP (one git repo per agent, cross-agent access hard-denied). First `first_class` H4: permissions are kernel-enforced and fail-closed. Provenance is free from git, plus a required `reason` on every mutation. |
| Google AX | confirms | `internal/skills/ @ b777313`; `internal/config/config.go:119-133` | No memory subsystem at all; skills are registry- or filesystem-sourced and explicitly harness-agnostic. **Third project to choose filesystem/git-backed skills over a memory store** (with Letta and OpenHands). Strong convergence for the Knowledge node. |
| Omnigent | confirms | `omnigent/spec/AGENTSPEC.md @ ba9e371` | No memory subsystem. Knowledge is `skills/<dir>/SKILL.md` plus `AGENTS.md` inside a portable, versioned agent image. **Fourth consecutive project** to choose filesystem/git-backed skills over a memory store (with Letta, OpenHands, Google AX). Strongest positive convergence in the study — I consider this settled for v0.1. |
| Cloudflare Agents | confirms | `design/skills.md @ 2f957bc`; `packages/agents/src/index.ts:8132` | **Fifth consecutive project** with filesystem-style skills and no memory store. `getSharedMemory` turns out to be a *user-defined* RPC method in a docstring example, not an SDK primitive — so even the closest thing to memory is explicitly shared *state*, not a semantic memory service. |
| AG2 | confirms | `ag2/network/identity.py:15-16 @ 90f490a`; `ag2/policies/` | `SKILL.md` — "Markdown document with Anthropic-style frontmatter" — per agent, plus a `knowledge/` package. **Sixth consecutive project** with filesystem/markdown skills and no memory service. Also the best *context* layer in the study (`token_budget`, `sliding_window`, `episodic_memory`, `working_memory`, `CompactStrategy`), reinforcing that context management and knowledge storage are different problems. |
| Pydantic AI | confirms | `pydantic_ai_slim/pydantic_ai/_history_processor.py @ b48ee38` | No memory service — only a history-processing hook (`ProcessHistory`) where compaction would live, with no strategy shipped. **Seventh consecutive project.** |
| Google Agent Platform | confirms | `src/google/adk/memory/base_memory_service.py:43-140 @ 85b52f6`; `src/google/adk/sessions/state.py:64-66` | **The only real memory service in the study, and it validates this ADR's central claim rather than contradicting it.** Memory is explicitly *not one thing*: a `BaseMemoryService` for semantic recall (`add_session_to_memory`, `add_events_to_memory`, `add_memory`, `search_memory`, scoped `(app_name, user_id)`, backed by Vertex Memory Bank or Vertex RAG) and **separately** a four-scope state model by key prefix — `app:` (application-wide), `user:` (per-user, cross-session), `temp:` (**never persisted**, filtered independently by three backends I checked), and unprefixed session state that is **schema-validated** against a declared Pydantic model. Also `MemoryEntry{author, timestamp}` where the timestamp is "when the original content of this memory happened" — event time, giving our Knowledge node the provenance it needed. **Adopt both the split and the prefix mechanism.** |
| HumanLayer | neutral | `hld/store/sqlite.go @ 99abe67` | No memory or knowledge subsystem; the transcript is stored for display and correlation, not recall. |
| AWS AgentCore | confirms | `src/bedrock_agentcore/memory/constants.py:13-35,76-78 @ 826416a` | Second real memory service, and it adds a dimension ADK did not have. ADK gave four **scopes** (`app:`/`user:`/`temp:`/session — who sees it, how long it lives); AgentCore adds orthogonal **kinds**: `SEMANTIC`, `SUMMARIZATION`, `USER_PREFERENCE`, `CUSTOM` (plus `*_OVERRIDE`). `USER_PREFERENCE` as a distinct kind is new to the study — durable preferences have different write patterns and privacy consequences from semantic recall. **Scope and kind are independent dimensions and our Recall interface needs both.** Namespaces (`/org/MyOrg/`, `/actor/Jane/`) are more flexible than fixed scopes and correspondingly less safe, though wildcards are refused. |

## Open questions

-
