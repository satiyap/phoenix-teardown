# Phase 1 — Recon and Triage

Shallow pass over all 14. Purpose: allocate reading depth according to available
evidence, and catch licence blockers before investing days of reading.

**Completed 2026-08-26.** Evidence: GitHub REST API (`/repos`, `/contents`,
`/readme`) queried directly; star counts and `pushed_at` as of that date.

> Tooling note: the `web_search` / `web_fetch` tools were unavailable (no local
> Ollama), so recon used the GitHub REST API over `curl`. The GitHub *search* API
> was rate-limited throughout (IP-level, unauthenticated), so projects were
> resolved by probing candidate repo paths directly. On re-check, the **npm and
> PyPI registries** proved a more reliable discovery path and located Agent
> Control. GroupMind was confirmed absent across all three registries.

## Evidence class

| Class | Meaning | Implication |
|---|---|---|
| A | Source and docs both readable | Eligible for deep teardown |
| B | Docs only, no usable source | Deep teardown possible but `implicit` verdicts unavailable; mark confidence lower |
| C | Announcements, marketing, or nothing substantive | Cannot support deep work — substitute or downgrade to targeted |

## Triage table

| Project | Slug | Depth | Class | Repo | Stars | License | Q6 | Last push | Notes |
|---|---|---|---|---|---|---|---|---|---|
| Google AX | `google-ax` | deep | **A** | `google/ax` | 1,970 | Apache-2.0 | REFERENCE_ONLY | 2026-08-20 | Go. "Distributed harness runtime". Single-writer + event log + resumption. Has `proto/`, `manifests/`. Early, breaking changes expected, external PRs paused. |
| Omnigent | `omnigent` | deep | **A** | `omnigent-ai/omnigent` | 9,290 | Apache-2.0 | INTEGRATE | 2026-08-26 | Explicit "meta-harness" over Claude Code, Codex, Cursor, OpenCode, Hermes, Pi. Has `designs/`, `sdks/`, `integrations/`. Alpha. |
| AG2 | `ag2` | deep | **A** | `ag2ai/ag2` | 4,890 | Apache-2.0 | REFERENCE_ONLY | 2026-08-25 | Formerly AutoGen. Self-describes as "Open-Source AgentOS". |
| Letta | `letta` | deep | **A** | `letta-ai/letta-code` | 3,122 | Apache-2.0 | REFERENCE_ONLY | 2026-08-26 | **Repo moved.** See finding below. TypeScript. Has `src/`, `docs/`, `.skills/`. |
| OpenHands | `openhands` | deep | **A** | `OpenHands/OpenHands` | 85,139 | MIT | INTEGRATE | 2026-08-26 | Org renamed from `All-Hands-AI`. Largest project in the set. |
| Cloudflare Agents | `cloudflare-agents` | deep | **A** | `cloudflare/agents` | 5,488 | MIT | REFERENCE_ONLY | 2026-08-26 | Durable-Objects-backed actor model. |
| LangGraph | `langgraph` | deep | **A** | `langchain-ai/langgraph` | 40,479 | MIT | INTEGRATE | 2026-08-26 | `libs/checkpoint-conformance` is a durability spec — unusually strong C-section evidence. LangSmith SDK separate (`langchain-ai/langsmith-sdk`, MIT); LangSmith server is closed. |
| Pydantic AI | `pydantic-ai` | deep | **A** | `pydantic/pydantic-ai` | 19,505 | MIT | INTEGRATE | 2026-08-26 | |
| Google Agent Platform | `google-agent-platform` | deep | **B** | `google/adk-python` (21,292★, Apache-2.0) + `googleapis/python-aiplatform` | — | Apache-2.0 | INTEGRATE | 2026-08-26 | ADK is open; the hosted Vertex Agent Engine control plane is closed. Managed-service behaviour is docs-only. |
| GroupMind | `groupmind` | **recon** | **C** | not found | — | — | — | — | No substantive public repo. Confirmed absent on GitHub, npm and PyPI. **Substituted.** |
| Microsoft Agent Framework | `microsoft-agent-framework` | targeted | **A** | `microsoft/agent-framework` | 13,122 | MIT | REFERENCE_ONLY | 2026-08-26 | Successor to Semantic Kernel + AutoGen lineage. |
| AWS AgentCore | `aws-agentcore` | targeted | **B** | `aws/bedrock-agentcore-sdk-python` (755★) + `aws/agentcore-cli` (267★) + starter-toolkit (505★) | — | Apache-2.0 | REFERENCE_ONLY | 2026-08-26 | SDK/CLI open; the managed control plane is closed. Identity/gateway/sandbox primitives are docs-only. |
| HumanLayer | `humanlayer` | targeted | **A** | `humanlayer/humanlayer` | 11,337 | Apache-2.0 | INTEGRATE | 2026-06-19 | GitHub reports `NOASSERTION`; LICENSE file is Apache-2.0 verbatim (header not auto-detected). Oldest push in the set. |
| Agent Control | `agent-control` | targeted | **A** | `agentcontrol/agent-control` | 299 | Apache-2.0 | ~~INTEGRATE~~ → **PORT** | 2026-08-24 | **Located on re-check via npm registry.** "Centralized agent control plane for governing runtime." TypeScript SDK at `sdks/typescript`, npm `agent-control` v3.1.0, 13 published versions. Restored to `targeted`. **Phase 1 predicted INTEGRATE; the Phase 4 reading overturned it** — it has no `Principal` model, so running it would mean a second policy store unable to name the principal every decision must reference. Patterns ported instead (`scope-reconciliation.md` §3). |

## Key findings

**1. Letta's source moved, and the thing I planned to tear down is retired.**
`letta-ai/letta` is now a landing page. Active source is
[`letta-ai/letta-code`](https://github.com/letta-ai/letta-code) — the agent
harness, terminal UI, App Server, channels, and the runtime behind the desktop
and web apps. The Python V1 API server is preserved unsupported on the `archive`
branch.

Consequences for Phase 2: Letta is now a *harness plus app server* in
TypeScript, not a Python memory server. That actually widens its relevance —
`channels` speaks to ADR-0003 and ADR-0007, not just ADR-0008 — but the H-section
memory architecture may now be partly behind Letta Cloud. Read `letta-code`
`src/` for the live design; consult the `archive` branch only where the V1 memory
model is needed and note the branch explicitly in citations, since it is retired
code and cannot support claims about current behaviour.

**2. Google AX is the most directly relevant project in the set.** It
self-describes as "a distributed harness runtime" that "dynamically provisions
isolated environments from suspendable/resumable images", with single-writer
architecture, a durable event log, and stated resumption protocols. That is
ADR-0001, ADR-0004 and ADR-0009 territory in one codebase, with `proto/` and
`manifests/` directories that should answer the O- and D10 probes directly.
Caveat: early development, "major breaking changes" expected, external PRs
paused — so treat its design as a moving target and cite commit SHAs strictly.

**3. Omnigent has already built ADR-0004's thesis.** A "meta-harness" giving a
common orchestration layer over Claude Code, Codex, Cursor, OpenCode, Hermes and
Pi, with policy enforcement, sandboxing (Modal, Daytona, Blaxel), session
portability across devices, and session sharing/forking. It is the closest thing
in the set to what we are proposing, which makes it the single most important
falsification target: if the adapter interface is achievable, its shape is here;
if it leaks, the leaks are here too. It also has a `designs/` directory — read
that before the code.

**4. One shortlist entry does not exist; the other was found on re-check.**
GroupMind returned nothing substantive across GitHub, npm and PyPI (three
independent registries) and is downgraded to `recon` with its questions
reassigned. **Agent Control was located on the second attempt** at
`agentcontrol/agent-control` (Apache-2.0, 299★, "Centralized agent control plane
for governing runtime") by querying the npm registry after the GitHub search API
proved unusable. It is restored to `targeted` depth for the policy-enforcement
questions. Lesson recorded: package registries are a better discovery path than
GitHub search when the latter is rate-limited, because they carry the canonical
repository URL.

**5. Nothing in the set is licence-blocked.** All located projects are Apache-2.0
or MIT. No AGPL, SSPL, or BSL anywhere, so no copyleft constraint on a product
that is both SaaS and customer-deployed. `REFERENCE_ONLY` verdicts above are
therefore *architectural* judgements (wrong language, wrong runtime, or too
early), not legal ones.

## Substitutions

GroupMind's and Agent Control's questions are reassigned rather than dropped.

| Original | Question it was to answer | Reassigned to |
|---|---|---|
| GroupMind | Human-agent workspace, shared rooms, presence, collaboration graph (G-section) | **Omnigent** (session sharing, co-driving, fork-to-continue, multi-device) + **HumanLayer** (approvals, escalation) |

Agent Control's questions are **no longer reassigned** — the project was located
on re-check and keeps its own targeted pass.

G-section coverage is now the weakest area in the study. Neither substitute is a
purpose-built collaboration product, so the human-agent workspace model has the
thinnest external evidence — which is consistent with it being a differentiation
opportunity, but it means ADR-0007 will rest more on reasoning than on precedent.
Recorded as OQ-003.

## Revised depth budget

Twelve inspectable projects, not fourteen. Deep teardowns ~2 days each does not
fit alongside synthesis, so depth is now weighted by architectural proximity.

| Project | Days | Rationale |
|---|---|---|
| Google AX | 2.5 | Closest architectural analogue: durable execution + harness runtime + manifests |
| Omnigent | 2.5 | Direct precedent for ADR-0004; primary G-section substitute |
| LangGraph | 2.0 | Phase 2 anchor. `checkpoint-conformance` is the best durability evidence available |
| OpenHands | 2.0 | Phase 2 anchor. Sandbox and harness isolation |
| Letta (`letta-code`) | 2.0 | Phase 2 anchor. Memory + channels; account for the repo move |
| Cloudflare Agents | 1.5 | Durable actor identity, ADR-0001 |
| AG2 | 1.5 | Agent-to-agent communication, F-section |
| Pydantic AI | 1.0 | Type-driven agent definition; smaller surface |
| Google Agent Platform | 1.0 | Class B; managed-plane behaviour from docs only |
| Microsoft Agent Framework | 0.5 | Targeted: F, L |
| AWS AgentCore | 0.5 | Targeted: D, I, J, K |
| HumanLayer | 0.5 | Targeted: G, C11 |
| Agent Control | 0.5 | Targeted: I8, J10, N |
| **Total** | **18.0** | Plus Phase 5 synthesis 3–4d, Phase 6 handoff 1–2d |

Phase 2 anchors stay LangGraph + OpenHands + Letta. Google AX and Omnigent move
to the **front of Phase 3** rather than into Phase 2: they are close enough to
our own design that reading them before a strawman exists risks anchoring on
their choices instead of testing ours.

## Targeted-pass scope

| Project | Probe sections in scope |
|---|---|
| Microsoft Agent Framework | F (a2a comms), L (orchestration) |
| AWS AgentCore | D (identity), I (capabilities), J (security), K (sandbox) |
| HumanLayer | G (human collaboration), C11 (durable pause/resume) |
| Agent Control | I8, J10 (policy enforcement points), N (multi-tenancy) |

## Notes for Phase 2

- Pin a commit SHA per project before reading; several push daily.
- Google AX and Omnigent are pre-1.0. Date every claim; their designs will move.
- LangSmith server and the AgentCore/Vertex control planes are closed. Managed
  behaviour is class B evidence at best — mark confidence `low` and never record
  `absent` for something merely undocumented.
- Letta citations must state which repo and branch (`letta-code` main vs
  `letta` archive).
