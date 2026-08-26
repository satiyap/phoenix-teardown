# Capability map
<!-- status: final -->

Eleven capabilities across 12 torn-down projects. **This replaces an earlier
version that used a ●/◐/○ scale, which was the wrong instrument** — see
[why](#why-not-a-presence-scale) at the end.

Instead of rating presence, each cell records **the mechanism chosen**. Two
capabilities can both "exist" and be architecturally opposite; the mechanism is the
part that informs a design decision.

**GroupMind is omitted.** Phase 1 confirmed it absent from GitHub, npm and PyPI, so
it was never torn down and has no evidence to report.

Full grid: [`capability-matrix.md`](capability-matrix.md) (173 probes, generated).
Per-component verdicts: [`build-reuse-map.md`](build-reuse-map.md).

---

## 1. Mechanism map

`—` means genuinely absent (read and confirmed). `?` means not inspectable.
**Bold** marks the project worth copying for that capability.

| Capability | Google AX | Omnigent | AG2 | Letta | OpenHands | Cloudflare | LangGraph | Pydantic AI |
|---|---|---|---|---|---|---|---|---|
| **Stable agent identity** | conversation, not agent | agent + monotonic version | **immutable passport + mutable resume** | agent id gates memory | conversation | **DO name = registry** | thread id | — |
| **Durable execution** | **fold an event log** | mutable rows + tx | append-only WAL per channel | **git commit history** | event tree w/ movable HEAD | ambient DO storage | snapshot + pending writes | delegated to Temporal/DBOS |
| **Mailbox** | — | — | **hub + WAL envelopes, at-least-once** | — | — | — | — | — |
| **Checkpoint/resume** | **refuses on identity change** | warm reattach \| cold rebuild | task checkpoint + resume_from | git restore | per-mode, declared | fiber + `ctx.stash()` | replay, **no version check** | boundary-crossing by id |
| **HITL** | **approval as log content** | 5 elicitation surfaces | cancel req ≠ cancel fact | pending-approval file | thread state + risk policy | protocol message | `interrupt()` | **typed output value** |
| **Sandbox** | delegated to SubstrATE | bwrap/seatbelt + 10 clouds | — | **kernel, fail-closed** | Docker workspace | **the DO *is* the isolate** | — | — |
| **Agent registry** | in-memory, from YAML | **entry-point plugins** | hub w/ capability index | agent store | ACP provider list | platform naming | — | spec files |
| **Shared memory** | — | session state + labels | **context set = WAL envelope** | git-backed markdown | thread state | `getSharedMemory` RPC | channels | — |
| **A2A** | — | — | **edge adapter, optional dep** | — | — | — | — | — |
| **MCP** | — | declarations + proxy pool | client + gateway | — | **with OAuth** | **persisted across hibernation** | via LangChain | client + compat |
| **Governance** | **none at all** | **per-phase fail-closed** | hub-side rules + arbiter | permission modes | `ConfirmRisky` fail-safe | — | auth fallback chain | typed wrap points |

### The five projects the eight-column view omits

They hold four of the study's most consequential findings.

| Capability | Google Agent Platform | AWS AgentCore | MS Agent Framework | HumanLayer | Agent Control |
|---|---|---|---|---|---|
| **Stable agent identity** | name only | **workload identity + 3 token variants** | name only | — | registered as a policy target |
| **Durable execution** | events + mutable JSON state | ? server-side | checkpoint chain over Pregel supersteps | append events, mutable rows | event stream + mutable rows |
| **Mailbox** | — | — | messages **inside** the checkpoint | — | — |
| **Checkpoint/resume** | resume + **event rewind** | ? | **bytecode digest, enforced on restore** | reconciler on restart | — |
| **HITL** | long-running call + pause | OAuth consent only | pending requests in checkpoint | **durable `Approval` table** | **`steer` = repair, not refuse** |
| **Sandbox** | **7 executors incl. `unsafe_local`** | ? | hyperlight micro-VM | — | — |
| **Agent registry** | none (bindings by name) | **credential providers, CRUD** | declarative YAML | — | control bindings |
| **Shared memory** | **memory service + 4 state scopes** | **typed kinds + namespaces** | pluggable backends | — | — |
| **A2A** | edge adapter | edge adapter | edge adapter | — | — |
| **MCP** | + OpenAPI generation | gateway service | client + hosting | **as the approval surface** | — |
| **Governance** | 16 plugin hooks | **Cedar, formally analysable** | **ingress + egress, org-owned** | decision record, no approver | **`deny\|steer\|observe`** |

---

## 2. Decision map

The column you actually fill in. Two axes, both already recorded in the study:
**what we do about it**, and **how confident the evidence makes us**.

| Capability | Best prior art | Our decision | Confidence | Basis |
|---|---|---|---|---|
| Stable agent identity | AG2 (passport/resume/runtime) | | High | 5 confirms, 2 amends. Rationale rebased: identity is for delegation/policy/audit, not durability |
| Durable execution | Google AX (fold the log) | | High | 13/13 have durability; AX's derived-state model eliminates log/state drift as a class |
| Mailbox | AG2 (`ag2.network`) | | **Medium** | **1 of 13.** Only precedent, and its file WAL has a retention horizon we must replace |
| Checkpoint/resume + pin | MAF (bytecode digest) | | High | 1 of 13 does version-and-pin; mechanism proven, only the target (agents) is new |
| HITL / approval | HumanLayer + Agent Control `steer` | | High | 12/13 have durable HITL; the `Approval` resource and `steer` are single-source |
| Sandbox (3 boundaries) | ADK + Pydantic AI + Cloudflare | | High | Each boundary has a different best answer; no project has all three |
| Agent registry | Omnigent (entry points) | | Medium | Several viable; low architectural risk either way |
| Shared memory / state | ADK (4 scopes) + AgentCore (kinds) | | High | 7/13 chose files for knowledge; scope and kind are orthogonal and both needed |
| A2A | AG2 (optional edge adapter) | | High | 5 independent confirmations of edge-adapter shape |
| MCP | Cloudflare (persisted connections) | | High | 8/13; uncontested as protocol-not-capability-model |
| Governance | Cedar + Agent Control + Purview | | **Medium** | Cedar's static analysis unverified (OQ-033); bounded by Cedar's expressiveness |

---

## 3. Where the evidence is strongest and weakest

The dimension a presence scale cannot show at all.

| | Capability |
|---|---|
| **Verified by execution** (not just read) | Checkpoint/resume — LangGraph's silent work-loss reproduced; MAF's digest recomputed; AG2's at-least-once and Cloudflare's idempotency test suites run |
| **Broad convergence** (safe to follow) | Filesystem knowledge (7/13), A2A as edge adapter (5/5 that speak it), tenancy in composite keys (2/2 that have tenancy), no compensation (13/13) |
| **Single source** (copy carefully) | Mailbox (AG2), content pin (MAF), memory service (ADK), `Approval` (HumanLayer), `observe`/`steer` (Agent Control), Cedar + workload identity (AgentCore) |
| **No precedent at all** (ours to invent) | Agent-level revocation, approver identity on approvals, platform-owned effect ledger, unified capability+extension model |

114 of 2,249 probe cells cite verification by execution rather than reading. Those
are the claims to trust most.

---

## Why not a presence scale

The first version of this file used ●/◐/○. It was wrong for three reasons, and the
third is the one that matters.

**1. It collapsed opposite designs into identical cells.** All 13 projects scored the
same glyph on durable execution. The mechanisms are: event sourcing (AX), mutable
rows plus transactions (Omnigent), git commit history (Letta), a branching event tree
with a movable HEAD (OpenHands), ambient object storage (Cloudflare), snapshots
(LangGraph), and total delegation to Temporal (Pydantic AI). A reader choosing a
durability model learns nothing from a column of identical marks.

**2. It read as a scorecard.** ● looks like a pass. But Google AX scores ● on durable
execution *and ships zero authentication*; LangGraph scores ● on checkpoint/resume
*and silently loses work* when the graph changes. I wrote "● is not an endorsement"
in the caveats — which is a sign the notation was fighting the content.

**3. It answered a question nobody asked.** "Does project X have capability Y" is
not a design input. The useful questions are *what mechanism did they pick*, *should
we take it*, and *how much does the evidence support that*. Those are three
different columns, and the study already recorded all three — 203 component verdicts
and 173 ADR impacts — so compressing them into one glyph threw away work that had
already been done.

If a single-glyph view is ever wanted for a slide,
[`capability-matrix.md`](capability-matrix.md) already provides it at full 173-probe
resolution, generated rather than hand-maintained.
