# Teardown — AG2

| | |
|---|---|
| Repo | https://github.com/ag2ai/ag2 |
| Commit read | `90f490a1b72b27ab4c219dd3586e94d42383a016` (2026-08-25) |
| Version tested | `ag2 1.0.2` (PyPI) |
| License | Apache-2.0 |
| Read on | 2026-08-26 |
| Evidence class | A |
| Depth | deep |
| Runtime class | `hybrid` — in-process agents plus an opt-in durable messaging hub |

Read against the strawman as amended by AX, Omnigent, and Cloudflare Agents.
AG2 was scheduled last of the four Phase 3 deep passes and its budget had been
*reduced*, on the reasoning that after seven absences the agent-messaging question
was nearly settled and AG2 would only confirm it.

**That reasoning was wrong, and this is the most important correction in the
study.** AG2 1.0's `ag2.network` package is "agent registry, durable messaging, and
protocol-driven channels" — a complete, tested, durable agent-to-agent messaging
layer. It closes the entire F-section single-handedly.

Note this is not the AutoGen-era codebase the Phase 1 recon assumed. AG2 1.0.2 has
`network/`, `a2a/`, `acp/`, `task.py`, `hitl.py`, `policies/`, and `_replay.py`.

---

## 1. What problem it solves

Multi-agent collaboration where the agents are peers rather than a parent and its
children. AG2 provides a hub that agents register with, channels they converse in,
and typed conversation *protocols* (conversation, discussion, consulting,
workflow) that constrain who speaks when.

## 2. Core architectural thesis

**Agent-to-agent conversation is a protocol problem, and the protocol belongs in
an addressable channel governed by a hub — never in the agents.**

Two supporting commitments make this work:

1. **The hub is the authority.** Access and limits are "enforced at the **hub**,
   never the client" (`ag2/network/rule.py:12`). The hub "never calls `Agent.ask`,
   executes tenant transforms, or imports tenant modules — the trust boundary runs
   through `HubClient`" (`hub/core.py:24-25`).
2. **The network is opt-in.** "Importing it is opt-in — bare `Agent` continues to
   work standalone with no behavioural change when this package is not imported"
   (`network/__init__.py`). A single agent pays nothing for the distributed
   machinery.

That second property is the one I most want to copy: the durable, governed,
multi-agent path is *additive*, so the simple case stays simple.

## 3. Resource / object model

The richest agent-messaging model in the study, and the only one at all.

```text
Hub                              the authority; owns WAL, audit, arbiter
 ├── Passport                    IMMUTABLE identity + billing.
 │                               kind: agent | human | remote_agent
 ├── Resume                      MUTABLE capability claims + OBSERVED record
 │    ├── claimed_capabilities   what the agent says it can do
 │    └── observed[cap]          ObservedStat{n, completed, failed,
 │                               expired, p50_latency_ms} — hub-derived
 ├── SKILL.md                    markdown + frontmatter, per agent
 ├── Rule (per hub, per agent)   access + limits, enforced hub-side
 │    ├── AccessBlock            who may talk to whom, channel types
 │    └── LimitsBlock            max_concurrent_channels / _tasks,
 │                               channel_ttl_default 2h, task_ttl 15m,
 │                               delegation_depth 5, RateBlock, InboxBlock
 ├── Channel                     manifest, participants, state, expectations
 │    └── WAL                     append-only per-channel envelope log
 └── AuditLog                    append-only audit.jsonl, open kind set

Envelope                         the wire shape for every A2A message
Task                             agent-owned lifecycle + checkpoint/resume
```

Verified live against 1.0.2:

```text
Envelope fields: channel_id, sender_id, audience, event_type, event_data,
                 envelope_id, task_id, causation_id, trace_id, priority,
                 depth, idempotency_key, created_at, ttl_seconds
delegation_depth: 5 | task_ttl: 15m | inbox max_pending: 1000 | overflow: reject
passport kinds: ('agent', 'human', 'remote_agent')
```

**The `Envelope` carries everything my strawman ADR-0003 proposed, plus four
fields I had not thought of**: `depth` (delegation hop count, capped by rule),
`priority`, `ttl_seconds`, and `causation_id`.

## 4. Runtime model

In-process agents (`Agent.ask`) with an optional hub. The hub may be in-process or
remote, and a `remote_agent` passport kind means "a participant that lives on
another hub; the local hub holds the passport as a cache and dispatches to it via a
registered `RemoteAgentProxy`" — federation as a first-class identity kind.

`AgentRuntime` is explicitly "hub-owned bookkeeping for the current connection
(transport binding, last heartbeat)... readers should treat it as cache-only."
Separating durable identity from connection cache is the distinction our
`AgentRuntime` node needs.

## 5. Execution lifecycle

`Task` is a first-class framework primitive (`ag2/task.py`), and notably **agent-
owned**: "Tasks are agent-owned. The framework does not assign or schedule them."

Events: `TaskStarted`, `TaskProgress`, `TaskCompleted`, `TaskFailed`,
`TaskExpired`, `TaskCancelled`. `TaskExpired` as a distinct terminal state from
`TaskFailed` is right and rare.

Checkpointing is explicit: `Task.checkpoint()` persists owner-defined state under
`task_id` via a `checkpoint_store`, and construction with
`resume_from=prior_task_id` reads it back and exposes `resumed_state` "so the owner
can pick up mid-flow after a restart."

Cancellation is modelled as *cooperative across a trust boundary*, which no other
project does. `EV_TASK_CANCEL_REQUEST` is a peer asking the owner to cancel, and
"the owner is free to honour by calling `Task.cancel` or to **ignore the request
entirely**." A separate `EV_TASK_CANCELLED` is the owner's terminal emission.
Distinguishing *request* from *fact* is exactly right when the canceller does not
own the work.

## 6. Durability model

Per-channel **append-only WAL** of envelopes, plus a hub `audit.jsonl` for
"hub-cross-cutting events that are not visible on per-channel WALs" — identity
changes, channel lifecycle, task terminations, expectation violations, and
notify-handler crashes "so operators can correlate with channel WALs".

The audit kind set is deliberately **open**: "subclasses and tenants may append
records with their own `kind` values... the built-in constants below are
conveniences for the hub's own emissions, not a closed enum."

**Delivery is at-least-once, stated plainly, with a real dedupe mechanism**
(`hub/core.py:2626-2644`):

```text
find_envelope_by_causation(channel_id, sender_id, causation_id) -> Envelope | None
```

> Handlers use this to short-circuit duplicate work after an at-least-once
> redelivery: when the same sender re-posts an envelope with the same
> `causation_id` (typical on retry), the prior accepted envelope is returned so the
> handler can **skip the side effect**.

The reply handler checks this *before* the turn-ownership probe, "so a redelivery
is a no-op regardless of whose turn it now is" (`client/handlers.py:198-211`).

**This is a second, independent precedent for ADR-0014, and it uses a different
key.** Cloudflare dedupes on an explicit `idempotency_key`; AG2 dedupes on
`causation_id` — the reply *is* the idempotency record, because a reply caused by
envelope X proves X was already handled. No extra key to generate or propagate.
See §25.

Ordering: a per-channel lock makes `validate_send` / `fold` / `on_accepted` "see a
consistent state", with dispatch outside the lock to avoid deadlocking on
`EV_CHANNEL_CLOSED` broadcast. Single-writer per channel, as with AX per
conversation.

**Verified**: `pytest test/network/test_at_least_once.py test/network/test_hub_invariants.py` → **39 passed**.

## 7. Agent identity and lifecycle

The best agent identity model in the study, and the answer to a question open
since Phase 2.

**`Passport` is immutable** — "Mutating any field requires unregister +
re-register, which yields a fresh `agent_id`." Immutability by construction rather
than by convention.

**`Resume` is mutable and dual-sourced.** Tenant code provides
`claimed_capabilities`, `domains`, `summary`, `examples`; **the hub mutates
`observed` on terminal task events**. So each capability accumulates an
`ObservedStat{n, completed, failed, expired, p50_latency_ms}`.

That is Omnigent's declared-vs-verified insight, generalised from harness
capabilities to *agent* capabilities, and made continuous rather than a test run.
`peers(action="find")` then exposes both to the calling LLM, including a computed
`observed_success_rate` (`client/tools/peers.py:29-40`).

`AuthBlock` describes "how the hub validates this identity at the connection
handshake" with `scheme`, `issuer`, `audience`, `key_fingerprint`, `claim` — JWT-
shaped, though `scheme` is currently `"none" | future schemes`.

**Revocation, finally.** `unregister` exists and is audited alongside `register`
and `set_resume`. It is a hard removal rather than a deprecation lifecycle, and
re-registering yields a new `agent_id`, but it is the first agent revocation
primitive in eight projects. `D9` moves from `absent` to `implicit`.

No version counter on the passport, so **still nobody has versioning *and*
pinning** — Omnigent versions, AX pins, AG2 does neither but has immutable
identity, which sidesteps part of the problem.

## 8. Multi-agent communication

**The F-section, closed.** After seven projects of `absent`, everything the
strawman proposed exists here and mostly goes further.

**Envelope** (`network/envelope.py`) — "the wire shape for every message between
agents... hub-stamped at `post_envelope`, and persisted to the per-channel WAL.
`audience` is the addressing primitive: `None` broadcasts within the channel, a
list targets a subset."

Details worth noting:

- **The WAL stores the full envelope regardless of addressing** ("audit + debug"),
  while `notify` lands only on listed peers. Delivery scope and audit scope are
  deliberately different — an audit trail that only recorded what was delivered
  would be useless for investigating what was *withheld*.
- **`depth` is a delegation hop count** the hub auto-increments on the reply path,
  capped by `Rule.limits.delegation_depth` (default 5). Runaway delegation is
  bounded by the platform, not by prompt discipline.
- **`causation_id`** threads replies to prompts and doubles as the dedupe key.
- **Stable event-type names** as a fixed set (`ag2.msg.text`, `ag2.packet`,
  `ag2.channel.invite`, `ag2.context.set`, …) with the rule stated: "new names are
  added in code, not at runtime. User-defined event types may be posted with
  arbitrary strings — the framework only special-cases the names below." An open
  namespace with a closed set of *meaningful* names.

**Channel protocols** are the genuinely novel part. `ChannelAdapter`
implementations — `ConversationAdapter`, `DiscussionAdapter`, `ConsultingAdapter`,
`WorkflowAdapter` — each carry state and an `ExpectedTurn` notion, with
`ORDERING_ROUND_ROBIN` and `default_expected_next`. Violations surface as
`EV_EXPECTATION_VIOLATED`, and `Expectation` on a manifest can declare
`max_silence` for idle detection.

So "who speaks next" is a property of the channel's declared protocol, enforced by
the hub, rather than emergent from prompts. `can_send(channel_id, agent_id)` is a
public probe so a handler "doesn't need to reach into adapter internals".

**Capability routing** (`F11`, first genuine instance): `peers(action="find")`
matches on `query`/`capability`/`sort_by` and returns claimed capabilities
alongside observed success rate and cost, "a structured list the LLM can rank".
`peers(action="describe")` returns passport, resume and SKILL.md verbatim, with a
rendered fallback when no SKILL.md exists.

**Inbox** (`InboxBlock`): `max_pending: 1000`, `overflow: reject`, and a
`high_water` soft threshold that fires `on_inbox_pressure` for backpressure
signalling, defaulting to 80% of `max_pending`. It is honest about its own state:
"Only `reject` is enforced today; `drop_oldest`/`drop_newest` are recognised but
treated as `reject` until the dispatch path grows the alternate behaviours."

## 9. Human interaction model

`hitl.py` provides `HumanInputRequest`/`HumanMessage` events with hooks accepting
sync or async callables returning either a `HumanMessage` or a plain string, and
`HumanInputNotProvidedError` when none is supplied.

More interesting: **`kind="human"` is a passport kind** — "an out-of-band non-LLM
participant driven by an external UI". A human is a first-class network
participant with an identity, a rule, and an inbox, addressable in `audience` like
any agent.

**That is the cleanest expression of ADR-0007 found anywhere.** Every other project
either models humans separately from agents (Omnigent) or not at all. AG2 makes
them the same kind of thing with a discriminator, which is precisely what "humans
and agents are both principals" should mean in a schema.

## 10. Context and memory

No memory *service*, but the best context-management story in the study.
`ag2/policies/` holds `token_budget`, `sliding_window`, `episodic_memory`,
`working_memory`, `conversation`, `alert`, and `compact.py` defines a
`CompactStrategy` protocol.

Two comments worth keeping:

- `compact.py`: "Compaction protects runtime stability. It is the
  constraint-respecting operation: triggered when measurable limits (event count,
  token count) are approached... **Compaction removes. Aggregation creates. They
  are separate concerns.**"
- `token_budget.py`: "The budget is a target, **not a guarantee**: events the cut
  orphaned are dropped from the span, and a span that would reduce to nothing
  widens past the budget instead."

The second is the honest-limitation discipline again, and the first is a
conceptual separation I had conflated.

There is also a `knowledge/` package and `KnowledgeStore` backing the hub's audit
root, plus SKILL.md per agent — continuing the filesystem-skills pattern for the
sixth consecutive project.

## 11. Tools and capabilities

`ag2/tools/` with a `@tool` decorator, `mcp/` and `mcp_ui/` packages, and an ACP
`tool_gateway` with `MCPCapabilityError`. Network capability is `peers()` — tools
that let an agent discover and describe other agents.

Agent capability declaration is the `Resume` (§7). There is no *runtime* capability
model like Omnigent's, because AG2 does not adapt third-party harnesses in the
same way — though `acp/config.py` names `ClaudeCodeConfig`, `CodexConfig`,
`KiloCodeConfig`, `OpenCodeConfig`, so it does drive external agents over ACP.

## 12. Security and IAM

Stronger than everything except Omnigent.

**The trust boundary is architectural**: "The hub never calls `Agent.ask`, executes
tenant transforms, or imports tenant modules — the trust boundary runs through
`HubClient`." A hub cannot be compromised by tenant code because it never runs
tenant code.

**Rules are enforced hub-side**, never client-side, with `AccessBlock` (who may
talk to whom, which channel types) and `LimitsBlock` (concurrency, TTLs,
delegation depth, rate, inbox).

**The arbiter is a replaceable decision point**: "Access / limits decisions go
through `arbiter` so federation / custom permission protocols can replace the
default rule-based behavior **without forking the hub**."

**Auth** is `AuthAdapter` with `ApiKeyAuth`, `NoAuth`, and an `AuthRegistry`, plus
`AuthBlock` on the passport for handshake validation. `network/security.py` and
`a2a/security.py` exist. Weaker than Omnigent's RFC 8628 delegation, and `scheme`
is still `"none" | future schemes`, but real.

**Rate limiting is declared but not enforced in-process**: `RateBlock` is "stored
on the rule but not enforced by the in-process hub — `per_minute = 0` keeps the
limiter disabled by default." Honest, and a gap.

Tenancy: "tenant" appears throughout as the trust-boundary term, but there is no
tenant *resource* — no `tenant_id` on rows. `J7` stays absent outside Omnigent.

## 13. Sandboxing

Not AG2's concern. No sandbox provider interface, no isolation model. Code
execution is a tool concern. `K1`–`K9` largely absent.

## 14. Orchestration

`WorkflowAdapter` with a `handoff.py`, `transitions.py`, and `rule.py` in the
network package; `EV_PACKET` captures "one agent's full `Agent.ask` round, captured
atomically" including `routing{kind: handoff|text, tool, reason, target}` and
`context_updates{set, delete}`.

Recording *why* a handoff happened (`reason`) and *which tool* triggered it
alongside the resolved target is better routing observability than any other
project's.

Channel-scoped context variables mutate via `EV_CONTEXT_SET` with
`{"set": {...}, "delete": [...]}` — shared state changes are themselves durable
envelopes in the WAL, so the shared-substrate pattern and the messaging pattern are
unified rather than parallel.

No scheduling (Omnigent and Cloudflare own that), no compensation (`L8`, eight for
eight).

## 15. Observability

OTel is an optional extra (`tracing = ["opentelemetry-sdk>=1.20"]`) exposed via
`ag2.opentelemetry`/`ag2.middleware`, plus `_telemetry_consts.py`,
`hub/telemetry.py`, and `hub/_envelope_tracing.py`. Fourth project with OTel, but
optional rather than default, and weaker on convention than Cloudflare.

The `HubListener` interface is the real strength: `on_envelope_posted`,
`on_envelope_rejected`, `on_inbox_pressure`, terminal task events, expectation
violations. **Rejections are observable, not just successes** — "Hub fires
`on_envelope_posted` (success) or `on_envelope_rejected` (any pre-WAL failure) for
**every attempt**." Most systems only tell you what happened, not what was refused.

`envelope.trace_id` is a first-class field, so trace context rides the message.

## 16. Multi-tenancy

Absent as a resource. "Tenant" is the trust-boundary term for user code, not an
isolation unit. No quotas beyond per-agent rule limits, no cost accounting beyond
`CostProfile` hints (explicitly "None of these fields are validated by V1").

## 17. Protocols and APIs

**A2A and ACP are optional-dependency interop adapters**, not the internal model:
`ag2/a2a/` has `card.py` (agent cards), `server.py`, gRPC transports, `push.py`,
`security.py`; `ag2/acp/` drives Claude Code, Codex, KiloCode and OpenCode. Both
degrade with `missing_optional_dependency` when not installed.

**This independently confirms ADR-0006 exactly.** AG2 has its own richer internal
envelope model and treats A2A as an edge protocol — interop, not internals. Also
`ag_ui/`, `a2ui/`, `mcp_ui/`, and `textual.py` for UI surfaces.

## 18. Storage

Per-channel WAL plus `audit.jsonl` under a `KnowledgeStore` root — file-based
append-only logs rather than a database. `HubBackedCheckpointStore` persists task
checkpoints by `task_id`. `layout.py` defines on-disk structure.

Simpler than SQL and appropriate for an append-only model, but no query surface
beyond in-memory indexes (`_causation_index`), and terminal-channel pruning clears
those indexes — noted in the docstring as a reason `find_envelope_by_causation` may
return `None`.

## 19. Deployment architecture

Library-first. Hub in-process or remote (`network/remote.py`, `transport/`,
`client/`), with `remote_agent` passports for cross-hub federation. `live/` and
`streams/` for streaming. No deployment manifests; you embed it.

## 20. OSS / license / commercial model

Apache-2.0, `NOTICE.md`, a `license_original` (AutoGen provenance), and a
`TRANSPARENCY_FAQS.md`. Optional extras keep the base install small.

Verdict: **INTEGRATE-candidate — the only one in the study.** It is Python,
Apache-2.0, actively developed at 1.0.2, and `ag2.network` is a well-factored,
tested, opt-in package solving the one problem we would otherwise build from
scratch with no precedent. Adopting the *envelope schema and hub contract* is
plausible even if we do not adopt the agent runtime. This is a materially
different verdict from the six REFERENCE_ONLYs before it.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | **inferable** | `AuthBlock` describes handshake validation (`issuer`, `audience`, `key_fingerprint`, `claim`); a replaceable `arbiter` allows custom permission protocols; `depth` caps delegation hops. But `scheme` is still `"none" \| future schemes`, so no working delegated-credential flow. Omnigent remains the only `first_class` answer. |
| S2 Torn side effect | **first_class_answer** | Second independent precedent, different key: `find_envelope_by_causation` returns a prior reply so a handler can "skip the side effect" on at-least-once redelivery, checked *before* turn ownership so it is a no-op regardless of whose turn it is. **Verified: 39 tests pass.** |
| S3 Upgrade mid-flight | undefined | Passport is immutable and has no version; `Task.resumed_state` is owner-defined and unversioned. Nothing detects a definition change across resume. |
| S4 Concurrent memory write | **inferable** | Per-channel lock serialises `validate_send`/`fold`/`on_accepted`, and context mutations are `EV_CONTEXT_SET` envelopes in the WAL — so concurrent shared-state writes are ordered by the same mechanism as messages. |
| S5 Cancellation tree | **first_class_answer** | **Best answer in the study.** `EV_TASK_CANCEL_REQUEST` (a peer *asks*) is distinct from `EV_TASK_CANCELLED` (the owner *did*), and "the owner is free to honour... or to ignore the request entirely". Cooperative cancellation across a trust boundary, which is the only correct model when the canceller does not own the work. |
| S6 Silent context loss | **inferable** | `CompactStrategy` triggers on measurable limits, and `TokenBudgetPolicy` documents that the budget "is a target, not a guarantee" with defined behaviour when a span would reduce to nothing. Loss is bounded and explained rather than silent, though not signalled as an event. |
| S7 Poison message | **inferable** | `InboxBlock` caps pending at 1000 with `overflow: reject` and an 80% `high_water` backpressure signal; `TaskExpired` and channel TTLs age work out; `on_envelope_rejected` makes refusals observable. No DLQ. |
| S8 Tenant leak | undefined | No tenant resource. "Tenant" means user code, not an isolation unit. |
| S9 Runaway spend | **inferable** | `LimitsBlock` caps concurrent channels and tasks and delegation depth, with TTL defaults (channel 2h, task 15m) — real resource bounds. But `RateBlock` is "not enforced by the in-process hub" and `CostProfile` fields are "not validated by V1", so there is no money-denominated limit. |
| S10 Zombie sandbox | undefined | No sandbox model. Channel/task TTLs and `max_silence` expectations bound *logical* work, not compute. |

## 22. Strongest ideas

1. **A durable envelope with `causation_id`, `depth`, `priority`, `ttl_seconds`,
   `trace_id`, and `audience`** — the complete A2A message shape, and richer than
   my strawman.
2. **Dedupe by `causation_id` instead of a generated key.** A reply caused by
   envelope X proves X was handled; no key to generate or propagate.
3. **Checking the redelivery guard before the turn-ownership probe**, so a
   redelivery is a no-op regardless of whose turn it now is.
4. **The WAL stores the full envelope regardless of addressing**, so audit scope is
   deliberately wider than delivery scope.
5. **`depth` auto-incremented by the hub and capped by rule**, bounding runaway
   delegation in the platform rather than in prompts.
6. **Immutable `Passport`, mutable `Resume`** — identity you cannot edit,
   capability claims you can.
7. **Hub-derived `observed` stats per capability** (`n`, `completed`, `failed`,
   `expired`, `p50_latency_ms`): declared-vs-verified capability, continuous rather
   than a test run.
8. **Capability routing that shows the LLM both claim and observed success rate.**
9. **`kind: agent | human | remote_agent`** — humans and remote agents are
   participant kinds, not separate subsystems.
10. **Channel *protocols* as adapters** (conversation, discussion, consulting,
    workflow) with expected-turn enforcement and `EV_EXPECTATION_VIOLATED`.
11. **`can_send()` as a public probe**, so handlers never reach into adapter
    internals.
12. **Cancel *request* distinct from cancel *fact***, with the owner free to
    ignore.
13. **`TaskExpired` as a terminal state distinct from `TaskFailed`.**
14. **The hub never imports or executes tenant code** — a trust boundary enforced
    by architecture.
15. **A replaceable `arbiter`** so custom permission protocols do not require
    forking the hub.
16. **Rejections are observable**: `on_envelope_rejected` fires for every attempt,
    not just successes.
17. **An open audit `kind` set** with built-ins as conveniences, not a closed enum.
18. **Opt-in network**: importing it changes nothing about a standalone agent.
19. **Context mutations are envelopes in the same WAL**, unifying shared-state and
    messaging.
20. **Routing observability**: `EV_PACKET` records the triggering tool, a
    human-readable `reason`, and the resolved target.
21. **`InboxBlock` with a `high_water` backpressure signal** defaulting to 80%.
22. **Honest self-documentation**: "only `reject` is enforced today"; "the budget
    is a target, not a guarantee"; `RateBlock` "not enforced by the in-process
    hub"; `CostProfile` "not validated by V1".
23. **"Compaction removes. Aggregation creates. They are separate concerns."**
24. **`AgentRuntime` explicitly cache-only**, separating durable identity from
    connection state.

## 23. Weakest architectural choices

1. **No tenancy.** "Tenant" names the trust boundary but there is no tenant
   resource or row-level isolation.
2. **`RateBlock` declared but unenforced** in the in-process hub.
3. **`AuthBlock.scheme` is `"none" | future schemes`** — the shape of auth without
   a working scheme beyond API keys.
4. **No passport versioning**, so no mid-flight upgrade detection.
5. **No sandboxing or isolation model** at all.
6. **File-based WAL with in-memory indexes**, and terminal-channel pruning drops
   the causation index — so the dedupe guarantee has a retention horizon.
7. **`CostProfile` unvalidated**, so no real cost control.
8. **OTel is optional** rather than default, and without Cloudflare's convention
   discipline.
9. **`InboxBlock` overflow modes partially implemented** (`drop_oldest`/
   `drop_newest` silently behave as `reject`) — documented, but a config that
   does not do what it says.
10. **No compensation or rollback.**

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| `Envelope` schema | **INTEGRATE** | The complete A2A message shape; adopt nearly verbatim |
| Dedupe by `causation_id` | **ADOPT_AS_STANDARD** | Cheaper than a generated key; refines ADR-0014 |
| Guard checked before turn ownership | ADOPT_AS_STANDARD | Redelivery must be a no-op unconditionally |
| WAL records full envelope regardless of audience | ADOPT_AS_STANDARD | Audit scope ⊃ delivery scope |
| Hub-incremented `depth` capped by rule | ADOPT_AS_STANDARD | Platform-bounded delegation |
| Immutable Passport + mutable Resume | **ADOPT_AS_STANDARD** | Resolves the identity-mutability question |
| Hub-derived `observed` stats per capability | **ADOPT_AS_STANDARD** | Continuous declared-vs-verified |
| Capability routing exposing claim + observed rate | ADOPT_AS_STANDARD | First real `F11` answer |
| `kind: agent \| human \| remote_agent` | **ADOPT_AS_STANDARD** | Cleanest ADR-0007 expression found |
| Channel protocol adapters + expectations | INTEGRATE | Turn-taking as declared protocol, hub-enforced |
| Cancel request vs cancel fact | ADOPT_AS_STANDARD | Correct across a trust boundary |
| `TaskExpired` distinct from `TaskFailed` | ADOPT_AS_STANDARD | Different causes need different states |
| Hub never imports tenant code | ADOPT_AS_STANDARD | Architectural trust boundary |
| Replaceable arbiter | REUSE (pattern) | Custom policy without forking |
| `on_envelope_rejected` for every attempt | ADOPT_AS_STANDARD | Refusals must be observable |
| Open audit `kind` set | REUSE (pattern) | Extensible without schema change |
| Opt-in network package | **ADOPT_AS_STANDARD** | The distributed path must be additive |
| Context mutations as WAL envelopes | REUSE (pattern) | Unifies shared state with messaging |
| `high_water` backpressure signal | REUSE (pattern) | Pressure before overflow |
| File WAL + in-memory index | BUILD | Reject; dedupe must not have a retention horizon |
| Declared-but-unenforced rate limits | BUILD | Reject; unenforced config is worse than absent |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | **amends** | Best identity model in the study: **immutable `Passport`** (mutation requires unregister + re-register, yielding a fresh `agent_id`) plus **mutable `Resume`**, plus `AgentRuntime` marked explicitly cache-only. Our `Agent` should split into exactly these three: immutable identity, mutable declared+observed capability, and disposable connection state. |
| ADR-0002 | **confirms** | `Task` is a first-class framework primitive with its own event set including `TaskExpired` distinct from `TaskFailed`, plus `checkpoint()`/`resume_from`. And it is **agent-owned**: "the framework does not assign or schedule them" — a division of labour worth copying. |
| ADR-0003 | **confirms strongly — reverses the Phase 3 conclusion** | After seven `absent` verdicts I was about to rewrite this ADR around shared state and drop messaging from v0.1. AG2 has the whole thing: hub-stamped envelopes on per-channel append-only WALs, `audience` addressing, at-least-once delivery with causation dedupe, `depth`-capped delegation, TTLs, priorities, inbox backpressure, and hub-enforced access rules. **The ADR stands, and the design should follow AG2's envelope closely.** |
| ADR-0004 | neutral | No harness adapter contract in the AX/Omnigent sense, though `acp/` drives Claude Code, Codex, KiloCode and OpenCode. |
| ADR-0005 | confirms | MCP as protocol via `mcp/`, `mcp_ui/`, and an ACP `tool_gateway`, separate from the capability model (which is the `Resume`). |
| ADR-0006 | **confirms strongly** | The clearest independent confirmation: AG2 has a richer *internal* envelope model and treats A2A as an optional-dependency **edge adapter** with agent cards and gRPC. Interop at the boundary, own model inside — precisely the ADR. |
| ADR-0007 | **confirms strongly** | `kind: agent \| human \| remote_agent` makes humans and agents the same kind of thing with a discriminator, each with a passport, a rule, and an inbox, addressable in `audience`. This is what "humans and agents are both principals" should mean in a schema, and no other project does it. |
| ADR-0008 | **confirms** | SKILL.md per agent with frontmatter, plus a `knowledge/` package and `KnowledgeStore`. **Sixth consecutive project** with filesystem/markdown skills and no memory service. Beyond settled. |
| ADR-0009 | neutral | No sandbox model. |
| ADR-0010 | **amends (weakly)** | OTel is an *optional extra*, which is weaker than AX/Cloudflare. But `HubListener` contributes something they lack: **`on_envelope_rejected` fires for every attempt**, so refusals are observable, and `envelope.trace_id` is a first-class field so trace context rides the message. Amend ADR-0010 to require that *rejected* operations are as observable as successful ones. |
| ADR-0011 | confirms (negatively) | Immutable passports sidestep part of the problem, but there is no passport version and `Task.resumed_state` is owner-defined and unversioned, so nothing detects a definition change across resume. **Eight projects, still nobody has versioning *and* pinning.** |
| ADR-0012 | **confirms and extends** | Extends the ADR from harnesses to *agents*, and from a test-run to a continuous signal: `claimed_capabilities` versus hub-maintained `observed{n, completed, failed, expired, p50_latency_ms}`, updated on every terminal task event. Omnigent verifies claims in a bench; AG2 verifies them in production. **Both belong: bench for correctness, observation for reliability.** |
| ADR-0013 | **confirms** | Access and limits "enforced at the **hub**, never the client", with a **replaceable arbiter** so custom permission protocols do not require forking, and `on_envelope_rejected` making every refusal observable. Still no shadow-comparison mode after eight projects — that half of the ADR remains unprecedented. |
| ADR-0014 | **confirms** | Second independent precedent, with a *better key*. See below. |

**Three things to change now.**

1. **ADR-0003 is vindicated; do not weaken it.** This is the single most important
   correction in Phase 3. I had drafted a rewrite around the shared-substrate
   pattern on the strength of seven absences, and reduced AG2's budget on the
   assumption it would only confirm that. Had I acted on the seven-project
   consensus before reading the eighth, I would have cut the one subsystem with a
   strong, tested precedent and no good substitute. **A convergence across N
   projects is evidence about what is common, not proof about what is possible.**

2. **ADR-0014 gains causation-based dedupe.** AG2's key is better than
   Cloudflare's for the reply case: rather than generating and propagating an
   `idempotency_key`, look up whether *this sender* already posted an envelope
   whose `causation_id` is the triggering envelope. The reply is the idempotency
   record. Our effect ledger should support both — explicit keys for
   externally-triggered effects, causation keys for reply-shaped work — and must
   check the guard **before** any ownership or turn test, as AG2 does.

3. **ADR-0012 gains an observation channel.** Omnigent verifies capability claims
   against a bench; AG2 accumulates `observed` stats from real terminal events. A
   bench answers "does it work?", observation answers "how often, and how fast?".
   Add `observed` to our capability record, hub-maintained and not writable by the
   declaring party.

**One methodological correction, recorded against myself.** The Phase 3 interim
findings called AG2 "downgraded in value" and said "the question is nearly settled;
AG2 now serves to confirm rather than decide." That judgement was made from a
six-project count and a Phase 1 recon that predated AG2 1.0. It was wrong on both
counts, and it nearly cost the study its answer to the F-section. The lesson for
the remaining passes: **a project's budget should be set by what it is *architected
to answer*, not by how confident the current tally makes me.**

## 26. Open questions

- What happens to the dedupe guarantee after terminal-channel pruning clears
  `_causation_index`? The docstring notes `find_envelope_by_causation` returns
  `None` "either it was never accepted or its channel has already closed", which
  conflates "no duplicate" with "cannot tell". (→ OQ-024)
- Is there a federation story for WAL consistency across hubs, given
  `remote_agent` passports are "a cache"? (→ OQ-025)
- **Answered while reading.** `ObservedStat` is a **lifetime counter** with no
  decay: `record_observation` increments `n`/`completed`/`failed`/`expired` on each
  terminal event, and `latency_ms` "replaces the prior `p50_latency_ms`
  (single-sample stand-in for a future reservoir)" — so the "p50" is not a
  percentile at all, just the last sample. Two details worth keeping: `task_id`
  dedupes double-counting ("a single task contributing twice... e.g. cascade
  EXPIRED + owner-emitted COMPLETED is recorded only once"), and observation
  **expands the capability index** so "the agent appears under that capability even
  if it wasn't in their original `claimed_capabilities`". That last behaviour is
  the interesting one: capabilities can be *discovered* by observation, not only
  declared. For our design the gap is decay — a lifetime counter never forgets an
  early failure, so a fixed reservoir or windowed rate is needed before routing
  decisions depend on it. **Resolved.** (→ OQ-026)
