# v0.1 product boundary
<!-- status: final -->

The scope decision the study exists to support. Three lists: **in v0.1**,
**deferred with intent**, and **never**. Every line cites the evidence that put it
there.

> **This document is the v0.1 *shipment*, not the target architecture.** The two
> differ — agent revocation, the live conformance-bench layer and `Recall` are
> all target-architecture items deferred out of v0.1. The difference is tabulated in
> [`scope-reconciliation.md`](scope-reconciliation.md) §1.
>
> **`Task`/routines ARE in v0.1 (Tier 2).** **Amended 2026-08-27**: this read "`Task` is not
> in v0.1". The deferral trigger — scheduled or recurring agent work becoming a product
> requirement — is met, because routines (schedule *or* trigger → Run) are the unit customers
> buy. A routine **creates** Runs and never becomes one, so `Run.task_id` is a nullable FK and
> the migration stays additive exactly as planned. See
> [`scope-reconciliation.md`](scope-reconciliation.md) §2 (dated reversal) and §7.

The governing rule comes from Cloudflare's `channels.md`, which deleted its own
durable messaging host because it "never delivered exactly-once ingress… so the
guarantee it appeared to offer was not one it could keep":

> **A guarantee you cannot keep is worse than an honest limitation.**

---

## In v0.1

Ordered by dependency: each item is buildable once the ones above it exist.

### Tier 1 — the spine (nothing works without these)

| # | Capability | Why v0.1 | Evidence |
|---|---|---|---|
| 1 | **Tenant, Principal, Credential** — `tenant_id` in every composite primary *and* foreign key; `Principal.kind ∈ {human, agent, service, remote}`; `Credential` with separate exchanger/refresher | Retrofitting tenancy is a rewrite. Four projects have half the principal model and none can audit properly without both halves. | ADR-0007; Omnigent + ADK (PKs), Agent Control (FKs), AgentCore (both halves) |
| 2 | **Agent identity + versioned definition + content digest** | The pin (item 5) is meaningless without a digest to pin. Immutable identity is cheap now and impossible later. | ADR-0001; AG2 Passport; MAF digest |
| 3 | **Run engine: single writer, log-derived state** | Every durability property depends on this. Composite PK with in-transaction sequence, state folded from the log, no parallel state table. | ADR-0004; Google AX |
| 4 | **Adapter contract + one SDK adapter** | We build and operate the agents, so ship the **Claude Agent SDK** adapter first and the OpenAI Agents SDK second. `sdk_in_process` is the only mode shipped; the SDK's native tool executor is disabled and every tool call crosses the typed `ToolCall → ledger → ToolResult` boundary. The adapter contract is kept so SDKs stay swappable. | ADR-0004 (amended 2026-08-27), ADR-0006; AX contract, Omnigent integration modes |
| 5 | **Version-and-pin on resume** → `INCOMPATIBLE` | The clearest differentiator in the study, and the failure it prevents is verified: LangGraph resumes a renamed node returning `[]` with no error and silent work loss. | ADR-0011; MAF (mechanism), LangGraph (the bug) |
| 6 | **Effect ledger** with both key kinds | The platform performs the replay, so it owns the hazard. ADK delegates this to tool authors; we take it back. | ADR-0014; Cloudflare + AG2 |

### Tier 2 — the platform (what makes it usable by others)

| # | Capability | Why v0.1 | Evidence |
|---|---|---|---|
| 7 | **Policy in Cedar: `deny \| steer \| observe`** | `steer` removes most approval prompts; `observe` is how a policy change ships safely. Both are cheap only if the decision type is three-way from the start. | ADR-0013; AgentCore (Cedar), Agent Control (three-way) |
| 8 | **`Approval` resource with `decided_by`** | Durable HITL is table stakes (4 of 4 anchors had it), and an approval that cannot name its approver fails audit. | ADR-0015; HumanLayer + the gap it leaves |
| 9 | **Sandbox: three boundaries, one provider each** | Process isolation alone is insufficient — an agent with a fetch tool reads IMDS. Egress guard is ~200 lines and closes a credential-theft path. | ADR-0009; ADK, Pydantic AI, Cloudflare |
| 11 | **Knowledge (files) + State (four scopes)** | Settled by 7-of-13 convergence, and `temp:` prevents a whole class of "why did my state vanish" bug. | ADR-0008; ADK prefixes |
| 12 | **OTel with GenAI semconv + a propagation test** | Cheap now, and Omnigent proves that adopting OTel without asserting propagation yields dead code. | ADR-0010; Cloudflare, Pydantic AI, ADK |
| 16 | **`Task` / routines: schedule *or* trigger → Run** | **Un-deferred 2026-08-27.** The named trigger — "scheduled or recurring agent work becoming a product requirement" — is now met: routines are the unit customers buy, and the OKF bundle already carries a 10:00 IST daily cadence and a weekly roll-up as *content*. A routine creates Runs and never becomes one, so `Run.task_id` stays a nullable FK exactly as `scope-reconciliation.md` §2 planned. | ADR-0002 (confirms); Omnigent (the only precedent); product requirement, §7 below |

### Tier 3 — integrate rather than build

| # | Capability | Decision | Evidence |
|---|---|---|---|
| 13 | **Agent-to-agent messaging** | **INTEGRATE `ag2.network` behind an owned compatibility layer.** The spike has run and split the verdict: clean integration FAILED (fixing OQ-024 requires changing public dedupe semantics), the compatibility route PASSED (12 tests, public composition only). We own dedupe entirely — AG2's `find_envelope_by_causation` is never used for correctness. | ADR-0003; `spikes/01-ag2-storage/RESULT.md` |
| 14 | **Cost measurement** | INTEGRATE `genai-prices`, with Omnigent's fail-closed-on-unpriced rule | Omnigent, Pydantic AI |
| 15 | **Capability declarations + offline bench** | **Moved from Tier 2 on 2026-08-27.** We build every adapter, so the bench is no longer about third-party honesty — nobody declares capabilities to us. Its purpose narrows to **SDK-version drift**: an SDK bump silently falsifies a declaration. Real, but slower and cheaper to absorb than an untrusted declaration, so it ships after the spine. ADR-0012 stands — declarations still beat discovery and `UNKNOWN` never degrades to `false`. | ADR-0012 (amended); Omnigent's CI split |

---

## Deferred with intent

Not "forgotten" — each has a named trigger that would pull it forward.

| Capability | Why deferred | What would pull it in |
|---|---|---|
| **Live conformance-bench layer** (probes + DRIFT) | Needs credentials and money per run; the offline layer catches rot | The third adapter, or the first capability-related production incident |
| **Continuous observed capability statistics** | Needs traffic to be meaningful, and AG2's lifetime-counter design needs a windowing fix first | Capability-based routing becoming a real feature |
| **Recall (semantic memory service)** | Only 2 of 13 projects have one; Knowledge + State covers the common case | A user needing cross-session semantic recall that files cannot serve |
| **Agent-level revocation lifecycle** | `D9` absent in 13 projects, so no urgency signal from the field — but we have the identity model to add it cleanly | First multi-tenant deployment, or first compromised-agent incident |
| **Static policy comparison** (Cedar analysis) | `observe` mode gives empirical comparison, which is sufficient early | A policy change large enough that empirical evidence is too slow |
| **Channel protocols** (turn expectations) | AG2's messaging works without them | Multi-agent conversations where turn order actually matters |
| **Multi-surface collaboration** (session sharing, co-driving, comments) | Product surface, not platform | A customer with more than one human per session |
| **Native TUI adapter** | Out of scope under the SaaS/SDK-only shape (amended 2026-08-27): we operate the agents on vendor SDKs, so there is no third-party TUI to scrape. The earlier reason (superseded 2026-08-27) rested on ACP covering the agents we cared about, which no longer applies because ACP is not a shipped path either | A first-party need to drive a terminal-only tool, which would be a connector rather than an adapter |

---

## Never

Five hard boundaries. These are not "later" — they are architectural commitments,
and each is backed by evidence rather than preference.

| # | Boundary | Evidence |
|---|---|---|
| 1 | **No compensation / rollback / saga engine.** We integrate Temporal, DBOS or Prefect. | **Zero positive answers in 13 projects** — 12 negative, 1 `unknown` only because a client SDK cannot show it — including the project whose whole job is control and the one whose whole job is orchestration. Pydantic AI supplies the reason: saga compensation is the workflow engine's job. |
| 2 | **No workflow / DAG engine of our own.** | MAF's Pregel engine and Pydantic AI's Temporal integration both demonstrate orchestration is separable and better solved elsewhere. Building one competes with a solved problem. |
| 3 | **No model gateway or provider abstraction.** | Explicit anti-goal of this study, and a commodity: MAF ships 35 provider packages, which is exactly the surface we should not own. |
| 4 | **No _public_ authoring framework, and no customer-supplied agent code** (amended 2026-08-27). We own a thin internal harness over the vendor SDKs (Claude Agent SDK, LangGraph, OpenAI Agents SDK). Customers bring knowledge, connectors and data — never agent code. | ADR-0004 (amended 2026-08-27). **The Cloudflare lesson no longer binds (superseded 2026-08-27).** Its cost was the ability to run a third party's agent; that was fatal when adapting third-party agents was a hard requirement, and it is not one any more, because we build and operate the agents. What we keep is the *adapter boundary* — not to admit foreign agents, but so the SDK underneath stays swappable. What we still refuse is publishing an authoring framework for customers to write against. |
| 5 | **No bespoke policy DSL, trace format, or messaging protocol.** Cedar, OTel, AG2's envelope. | ADR-0013, ADR-0010, ADR-0003. Every project that invented one of these ended up with a worse version and no ecosystem. |

---

## What v0.1 explicitly does not guarantee

Stating these is the point of the governing rule.

- **Not exactly-once effects.** At-most-once where the effect target cooperates,
  and *detected indeterminacy* where it does not. A `claimed` ledger row past its
  lease is `INDETERMINATE` and surfaces to a human — it is never silently retried.
- **Not exactly-once message delivery.** At-least-once with causation dedupe, as
  AG2 has it. Cloudflare deleted a component for claiming better.
- **Not automatic compatibility across an agent edit.** A content digest is brittle
  in the safe direction: a comment-only change invalidates checkpoints. A false
  incompatibility costs a restart; a false compatibility costs the silent
  corruption LangGraph exhibits.
- **Not a cost *cap*, only cost measurement.** Enforcement needs a budget gate we
  have deferred; Omnigent is honest that "a single very expensive turn can still
  overshoot before the next check."
- **Not cross-tenant authorization.** Composite keys prevent accidental leaks;
  preventing deliberate impersonation needs the full principal model in use, which
  is item 1 but only enforced where callers are authenticated.

---

## The riskiest decisions in this boundary

Recorded so they can be revisited against reality rather than rediscovered.

1. **Integrating `ag2.network` rather than building messaging.** ~~Mitigation: spike the
   storage swap before committing.~~ **Done — see `spikes/01-ag2-storage/RESULT.md`.**
   The residual risk changed shape: we now depend on `post_envelope`'s signature and the
   `Envelope` schema rather than on internal index behaviour, which is a smaller surface,
   but the compatibility layer is ours to maintain across AG2 releases.
2. **`Task` as a distinct resource on one precedent.** Omnigent separates Task from
   Run only for scheduled work. If interactive runs never need it, `Task` is
   speculative generality — the exact mistake ADR-0003 nearly made in the other
   direction.
3. **Content-derived pins with no escape hatch.** MAF appears to have none (OQ-037),
   and we are copying that. If operators hit false incompatibilities often, the fix
   must be an explicit recorded assertion, never a loosened default.
4. **Cedar as a hard dependency for policy.** It buys the analysis story; it also
   means our policy expressiveness is bounded by Cedar's, and a requirement Cedar
   cannot express becomes a real problem.

---

## Success test

The study set this condition in Phase 0: a statement of this form, written from
evidence rather than taste. Stated twice, because **the target architecture and the
v0.1 shipment are different scopes** (§1 of `scope-reconciliation.md`).

### Target architecture

> **We build** content-derived version pinning on the agent definition, a
> platform-owned effect ledger, a unified capability-and-extension model with a
> two-layer conformance bench, and agent-level revocation with attributable
> approvals — because 13 projects show nobody does these, and one of the failures
> (silent work loss on resume across a definition change) is verified rather than
> hypothesised.
>
> **We integrate** AG2's envelope and hub for messaging, Cedar for policy, and
> `genai-prices` for cost — because each is permissively licensed, independently
> useful, and better than what we would write. **We port, but do not run,** Agent
> Control: it has no `Principal` model, so running it would mean a second policy
> store unable to name the principal every decision must reference.
>
> **We never build** a compensation engine, a workflow engine, a model gateway, a
> **public** agent-authoring framework (amended 2026-08-27: we own an internal harness over
> the vendor SDKs), or a bespoke policy/trace/message format — because the
> evidence says those are either solved elsewhere or absent everywhere for a reason.

### v0.1 shipment

> **We build** content-derived pinning and the effect ledger, plus the **offline**
> conformance-bench layer and **attributable approvals**.
>
> **We defer** agent revocation, the live probe layer, and `Recall` — each with a named
> trigger, not forgotten. **Amended 2026-08-27:** `Task` was in this list and is now **Tier
> 2**, its trigger having been met (§7).
>
> **We integrate** Cedar, `genai-prices`, and `ag2.network` **behind a compatibility
> layer we own** — the spike proved the hub runs on our storage (480 upstream tests, 201
> channel WALs through our `append()`) and that dedupe is ours to own by public
> composition, because `post_envelope` never consults the causation lookup.
>
> **We port** Agent Control's `deny | steer | observe` vocabulary, Omnigent's
> positional fail-closed rule, Pydantic AI's SSRF guard, ADK's four state scopes and
> in-memory-sibling discipline, HumanLayer's `Approval` schema, AX's fold-the-log
> derivation, MAF's bytecode-digest pin, and Cloudflare's hung-work detection.

All 25 exit criteria are answered with citations; 16 ADRs exist — 15 Accepted, 1 Proposed (amended 2026-08-27) — with
evidence from 13 projects. Three probes remain `unknown` and are tracked with reasons
(`langgraph/C8` closed source; `letta/C5` and `openhands/C5` undocumented delivery
semantics) — `make check` exits 0 with them present, and fails on any *untracked*
unknown.
