# Teardown — Cloudflare Agents

| | |
|---|---|
| Repo | https://github.com/cloudflare/agents |
| Commit read | `2f957bc2a3ffb7aee14792bb3cb658ad3176ed93` (2026-08-26) |
| License | MIT |
| Read on | 2026-08-26 |
| Evidence class | A |
| Depth | deep |
| Runtime class | `durable_actor` — one agent = one Durable Object with its own SQLite |

Read against the Phase 2 strawman as amended by AX and Omnigent. **Promoted ahead
of AG2** because it was the best remaining hope for the two gaps with real design
consequences: tool-call idempotency (`C6`) and lost-worker detection. Both paid off.

**This project closes `C6`, the last substantive universal gap** — verified by
running its tests, not by reading them.

---

## 1. What problem it solves

Making an agent a durable, addressable, single-threaded object. Cloudflare has a
primitive — the Durable Object, with hibernation, alarms, embedded SQLite, and a
globally unique addressable id — and the Agents SDK is the argument that this
primitive is the right shape for an agent.

## 2. Core architectural thesis

**One agent is one Durable Object: a single-threaded, addressable actor with its
own private SQLite database, that hibernates when idle and wakes on demand.**

Everything else follows. Durability is not a subsystem, it is the substrate:
`this.sql` writes to storage that survives eviction, so there is no separate
checkpoint step. Concurrency is not managed, it is absent — one DO processes one
request at a time, so the lost-update races Omnigent had to fix with
`BEGIN IMMEDIATE` cannot arise. Identity is not assigned, it is the object's name.

The bet's cost is portability: this design is inseparable from Cloudflare's
runtime.

## 3. Resource / object model

```text
Agent                       = one Durable Object (addressable by name)
 ├── state                  single-row JSON, versioned schema (v11)
 ├── this.sql               private embedded SQLite
 ├── Connection             hibernatable WebSocket
 ├── cf_agents_schedules    time / cron / interval, with retry_options
 ├── cf_agents_queues       durable queue with retry_options
 ├── cf_agents_fibers       durable execution ledger — fiber_id PK,
 │                          IDEMPOTENCY_KEY UNIQUE, status, snapshot
 ├── cf_agents_runs         in-flight run rows (orphan detection)
 ├── McpServer              persisted MCP connections with per-server retry
 ├── Workflow               handles to Cloudflare Workflows
 └── SubAgent               child DO facet, own SQLite, typed RPC
```

The distinctive resources are `cf_agents_fibers` and `cf_agents_runs`. A **fiber**
is a durable unit of execution registered in SQLite *before* it runs,
checkpointable during execution via `ctx.stash()`, and recoverable after eviction
through `onFiberRecovered`. That is a genuine durable-execution primitive inside
an actor, which no other project has.

## 4. Runtime model

Hibernation is the core mechanic. An idle agent is evicted from memory; its
SQLite and its WebSockets survive. It wakes on an incoming request, a WebSocket
message, or an alarm. `keepAlive()` refs prevent eviction while work is in flight.

WebSockets always use the Hibernation API — "There is no in-memory WebSocket
mode" (`design/durable-object-lifecycle.md`). Connection metadata lives in socket
attachments and `Connection` objects are reconstructed after waking. Refusing to
offer the non-durable path is the kind of constraint that prevents a whole class
of production surprise.

`Lifecycle` composes capabilities into ordered phases (`onStart`, `onRequest`,
`onAlarm`), each running capability hooks before the host's. Capability hooks
deliberately run *outside* the host's `AsyncLocalStorage` context "so behavior
does not depend on the entrypoint that triggered the phase" — a subtle
determinism guarantee.

## 5. Execution lifecycle

Fibers have a real state machine: `pending → running → {completed, error,
aborted, interrupted}`. `interrupted` is the interesting one: it means the
process died mid-fiber, and the row survives for recovery.

`startFiber` returns `{ ...inspection, accepted: boolean }`. `accepted: false`
means "this work already exists, here it is" — the dedupe signal.

Cancellation is real: `cancelFiber` flips status to `aborted` **and** aborts the
in-memory `AbortController`, with a guarded `WHERE status IN ('pending',
'running')` so a terminal fiber cannot be re-cancelled.

No Task/Run separation for agent work generally, though `cf_agents_fibers` versus
`cf_agents_runs` comes close: the ledger row is the durable intent, the run row is
the live attempt, and an orphaned run row is the detection signal.

## 6. Durability model

The strongest in the study, and the only one where durability is *ambient* rather
than a subsystem.

**Idempotency — `C6`, closed.** `cf_agents_fibers` declares
`idempotency_key TEXT UNIQUE` (`packages/agents/src/index.ts:2282`), and
`startFiber` checks it before doing any work (`:5522-5590`):

```text
existingByKey = _readFiberByKey(idempotencyKey)
if (existing) return { ...inspection, accepted: false }   // no re-execution
INSERT INTO cf_agents_fibers (fiber_id, idempotency_key, ...)
```

It also refuses ambiguity: if `fiberId` and `idempotencyKey` point at different
fibers, it throws `"fiberId and idempotencyKey refer to different fibers"` rather
than guessing.

**Verified by running the tests** (`src/tests/run-fiber.test.ts:578-595`, all 48
pass):

```
✓ should dedupe managed fibers by idempotency key
    first.accepted  === true
    second.accepted === false
    second.fiberId  === first.fiberId
    executionLog    === ["managed:first"]      // ran ONCE
```

The execution log assertion is what makes this real: the second call did not
merely return early, the side effect never happened twice. Six prior projects had
nothing comparable.

**Lost-worker / hung-work detection.** `_scheduleNextAlarmBody`
(`index.ts:6520-6600`) is the best recovery logic in the study:

- Overdue schedules are found and run, because "the SQLite row survives but the
  in-memory alarm does not" after a restart.
- A running interval schedule whose `execution_started_at` is older than
  `hungScheduleTimeoutSeconds` (default 30) is treated as **hung** and becomes
  eligible again.
- Interval schedules that are running but *not yet* hung still get a future alarm
  "so the runtime can re-check them once they cross the hung timeout" — the
  liveness case most implementations forget.
- Orphaned fibers (a `cf_agents_fibers` row with no `cf_agents_runs` row, or an
  `interrupted` row) are recovered by an alarm-driven scan.
- The scan yields at a deadline and **backs off exponentially while it makes no
  forward progress**, so a poison recovery hook cannot wake the DO forever. A
  scan that recovers anything resets the streak.

That last point is a poison-message answer arrived at from the liveness side
rather than the queue side, and it is the only such mechanism in the study.

**Retries — first structured retry policy anywhere in this study.**
`design/retries.md` plus `src/retries.ts`: `tryN` as the single retry loop, full
jitter per the AWS analysis, `RetryOptions{maxAttempts, baseDelayMs, maxDelayMs}`
configurable per call site and per agent class, **validated eagerly at
schedule/enqueue time** so `{baseDelayMs: 5000}` against `maxDelayMs: 3000` throws
immediately "instead of failing minutes later at execution time". Options are
stored in a `retry_options TEXT` column precisely because in-memory config "would
be lost when the DO hibernates".

And it knows when *not* to retry: `isErrorRetryable` excludes overloaded-DO errors
because they "indicate the DO is rejecting work to protect itself. Retrying would
make congestion worse."

**Storage schema is versioned.** `CURRENT_SCHEMA_VERSION = 11`, stored as a row
and checked on wake to skip DDL on established objects (`index.ts:1197,2081-2087`).

## 7. Agent identity and lifecycle

Identity is the Durable Object name, and `ctx.id.name` is authoritative
(`design/durable-object-lifecycle.md`). Lifecycle "never writes a duplicate name",
reading a legacy `__ps_name` key only as a migration fallback. Agents are
addressed by `getAgentByName(binding, name)`.

This is the cleanest affirmative evidence for ADR-0001 in the study: durable
identity that exists whether or not the agent is running, with no separate agent
registry, because the platform's naming *is* the registry.

Sub-agent identity is versioned in an interesting way — `pathV2IdentityName`
composes a logical name with a SHA-256 digest, so a sub-agent's identity encodes
a content digest rather than a counter.

**No agent versioning or revocation.** No `AgentVersion`, no deprecation, no
revoke. `D4`/`D9` remain absent — now seven for seven on revocation.

## 8. Multi-agent communication

**Absent, seven for seven** — and this project had the most reason to have it.

There is a `@cloudflare/channels` package and a `channels` design doc, which I
read expecting the first F-section evidence. It is **human↔agent messaging**:
Slack, Telegram, email, and voice adapters that normalise provider input, choose
a route, and deliver output. `ChannelIdentity{channelKey, scope, subject}`
identifies a *human* correspondent.

Sub-agents communicate by **typed RPC** — `await searcher.search(query)` — not by
messages. And `getSharedMemory` on a parent agent (`index.ts:8132`) is the
coordination path: a child reads shared facts from its parent's storage.

So Cloudflare independently arrived at the same pattern as all six prior
projects: **coordination through a shared durable substrate plus direct calls,
never durable message passing.** Seven for seven is no longer a gap. It is the
industry's answer.

`channels.md` is also the best-reasoned design document I read in this study, for
a reason directly relevant to ADR-0003 — see §25.

## 9. Human interaction model

Tool approval is a wire protocol message type (`cf_agent_tool_approval`) with
`toolApprovalUpdate` state transitions in `chat/tool-state.ts`. Because the agent
is a DO with durable storage and hibernatable sockets, a pending approval
survives eviction by construction — the same "durability is ambient" property as
AX's log-based approvals, reached differently.

There are `readonly-connections.md` (observers who cannot drive) and a
`think-execute-hitl.md` design. No multi-user permission model, no session
sharing, no roles: a single-tenant SDK, not a collaboration product.

## 10. Context and memory

No memory subsystem. There is a `skills/` directory in the package and a
`design/skills.md`, continuing the pattern.

**Fifth consecutive project with filesystem-style skills and no memory store.**
Combined with `getSharedMemory` being explicit shared *state* rather than a
semantic memory service, ADR-0008 is now settled beyond doubt.

## 11. Tools and capabilities

MCP is first-class and, distinctively, **persisted**: server options live in a
`server_options` JSON column "so it persists across hibernation", with per-server
retry config and OAuth reconnection (`_restoreServer`, `establishConnection`).
Every other project treats MCP connections as ephemeral.

`codemode` (a separate package) and `agent-tools.ts` provide tool definition;
`x402-tests` suggests payment-gated tools.

No declared capability model for agents themselves — nothing comparable to
Omnigent's 16 axes. Capability here means "which tools does this agent have", not
"what can this runtime do".

## 12. Security and IAM

The weakest area, and a deliberate framing rather than an oversight.

Auth is a **hook the developer implements**: `onBeforeConnect` and
`onBeforeRequest` on `routeAgentRequest` may return a `Response` to reject
(`agent-routing.ts:73-84`). The SDK ships no authentication, no authorization
model, no principals, and no tenancy.

What it does do well is **document exactly which paths bypass the hook**:
`getSubAgentByName` "does not run `onBeforeSubAgent` on the parent — analogous to
`getAgentByName` not running `onBeforeConnect`. The caller is assumed to have
performed whatever access checks are needed" (`sub-routing.ts:489-491`). Naming
your own auth bypass in the docstring is better than most projects manage.

Isolation, however, is genuinely strong and comes from the platform: each agent is
a separate DO with a *private* SQLite database. `rfc-sub-agents.md` makes this an
explicit architectural argument — a gatekeeper agent should hold data in a child
DO so that enforcement is "structural" rather than "a convention (*don't call
`this.sql` directly*)", because otherwise "the LLM can bypass the queue by writing
SQL."

**That is the sharpest security insight in the study**: with an LLM inside your
trust boundary, a storage boundary is an enforcement mechanism and a code
convention is not.

## 13. Sandboxing

Not the SDK's concern — the DO *is* the isolate. Sandboxing for untrusted code is
delegated (a `sandbox` example exists, and `rfc-coding-agent.md` covers a coding
agent). No pluggable sandbox provider interface, because V8 isolates and separate
DOs provide the boundary.

Notably this is the only project where the *agent runtime itself* is the isolation
unit, rather than the agent running inside a separately-provisioned sandbox.

## 14. Orchestration

Rich, and all durable:

- **Schedules**: `schedule()` (time or cron), `scheduleEvery()` (intervals),
  backed by SQLite and alarms, with hung detection and retries.
- **Queues**: `queue()` with a durable table and per-task retry options.
- **Fibers**: durable execution with checkpointing and recovery.
- **Workflows**: handles into Cloudflare Workflows with `pause`, `resume`,
  `restart`, `terminate`, `sendEvent` — each retried with `isErrorRetryable`.
- **Sub-agents**: child DO facets with isolated SQLite, typed RPC, and
  `rfc-sub-agent-routing.md` for routing.

The scheduling story is the best in the study: Omnigent had rrules but an
in-process scheduler that would double-fire across replicas; here the alarm is
owned by the DO itself, so there is exactly one scheduler per agent by
construction. **Single-writer by platform, not by discipline.**

No compensation or rollback (`L8`, seven for seven).

## 15. Observability

**Third project with real OTel, and the best on convention adherence.**

`observability/genai/attributes.ts` states a namespacing discipline I have not
seen elsewhere:

> `gen_ai.*` keys follow OpenTelemetry GenAI semantic conventions where they
> exist... Keys with no semconv home live under the `cloudflare.agents.*` vendor
> namespace — **never bare top-level keys, never `ai.*`** (the Vercel AI SDK's
> de-facto namespace).

So it follows the GenAI semconv where one exists, uses an explicit vendor prefix
where none does, and refuses to squat on another tool's namespace. AX and Omnigent
have OTel; only Cloudflare has *semantic convention hygiene*.

Also of note: a comment refuses to "invent an `otel.status_code` attribute:
status is span state in OTel" (`tracing/tracer.ts:298`) — declining to model
something as an attribute when the protocol already models it as span state.

There is a structured event stream (`observability?.emit()`) with typed events
including `queue:retry` and `schedule:retry` carrying `attempt` and `maxAttempts`,
and the retry design doc notes these fire only for attempts > 1 "since the first
attempt is not a retry".

Spans are lifetime-managed: `withSpan` guarantees closure, and
`boundToInvocation` closes a span "no later than the end of the surrounding
invocation, so it cannot outlive the native invocation that owns its tracing
context" — a real hazard in a hibernating runtime.

## 16. Multi-tenancy

Absent as a modelled concern, but obtainable: one DO per tenant per agent gives
storage-level isolation for free, which is arguably stronger than Omnigent's
`workspace_id` in a shared table. There is no org/project hierarchy, no quotas,
and no cost accounting (`N3` absent — Omnigent remains the only answer).

## 17. Protocols and APIs

HTTP and WebSocket via `routeAgentRequest`, native DO RPC, email
(`email.ts`, `email-send.ts`), and MCP. React hooks (`ai-react.tsx`, `react.tsx`)
and a client (`client.ts`) for the northbound side.

The southbound story is inverted relative to every other project: there is no
adapter interface for third-party agents, because the SDK's premise is that *you
write the agent* as a subclass of `Agent`. Extension happens through the
`Lifecycle` capability system, not through an adapter contract.

Wire protocol messages are typed and named (`cf_agent_tool_approval`,
`cf_agent_*`), which is a small thing that makes protocol evolution tractable.

## 18. Storage

Per-agent embedded SQLite via `this.sql`, plus a single-row JSON state
optimisation with a versioned schema (v11) and legacy-key backward compatibility.
Tables are created with `CREATE TABLE IF NOT EXISTS` and columns added with
`ADD COLUMN IF NOT EXISTS`, so migrations are forward-only and idempotent.

No pluggable storage backend, and none is possible — the whole design is DO
storage.

## 19. Deployment architecture

Cloudflare Workers plus Durable Objects, `wrangler` bindings, `nx` monorepo,
`worker-bundler` package. Deployment is `wrangler deploy`; there is no self-hosted
path.

## 20. OSS / license / commercial model

MIT — the most permissive licence in the study. Multiple packages
(`agents`, `channels`, `ai-chat`, `codemode`, `hono-agents`, `shell`, `think`,
`voice`, `worker-bundler`), an `experimental/` tree, and extensive `design/` RFCs.

Verdict: **REFERENCE_ONLY, unavoidably.** MIT permits anything, and the patterns
are the most directly stealable in the study, but every line assumes Durable
Objects. The *ideas* port; the code cannot.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | undefined | No principals; auth is a developer-supplied hook. Omnigent remains the only answer. |
| S2 Torn side effect | **first_class_answer** | **Best answer in the study, verified by running the test.** `idempotency_key UNIQUE` on the fiber ledger; a duplicate `startFiber` returns `accepted: false` and the side effect log shows one execution. Plus: single-threaded DO (no concurrent writers), fiber registered before execution, `ctx.stash()` checkpoints, `onFiberRecovered` for eviction mid-flight. |
| S3 Upgrade mid-flight | inferable | Storage schema is versioned (v11) and migrated forward on wake, but agent *code* version is not pinned to in-flight fibers. Better than most: a fiber's `snapshot` and recovery hook give the new code a defined entry point. |
| S4 Concurrent memory write | **inferable** | Structurally impossible within one agent: a DO is single-threaded, so read-modify-write cannot interleave. This is the cleanest resolution of the scenario — not solved, *dissolved*. |
| S5 Cancellation tree | **inferable** | `cancelFiber` flips durable status *and* aborts the in-memory `AbortController`, guarded so a terminal fiber cannot be re-cancelled. No documented propagation to sub-agent fibers. |
| S6 Silent context loss | undefined | No compaction in the SDK. |
| S7 Poison message | **inferable** | Approached from liveness: a recovery scan that makes no forward progress **backs off exponentially** so a poison hook cannot wake the DO forever, and a `fiberRecoveryMaxAgeMs` ages rows out. No DLQ, but the failure mode is bounded. |
| S8 Tenant leak | inferable | Not modelled, but one DO per tenant gives private-database isolation — arguably stronger than a shared-table `workspace_id`. |
| S9 Runaway spend | undefined | No budget or cost accounting. Seven for seven except Omnigent. |
| S10 Zombie sandbox | **first_class_answer** | **Best answer in the study.** Hung schedules detected via `execution_started_at <= now - hungScheduleTimeoutSeconds` (default 30s); orphaned fibers found by joining `cf_agents_fibers` against `cf_agents_runs` where the run row is gone; overdue schedules run after restart because "the SQLite row survives but the in-memory alarm does not"; running-but-not-yet-hung intervals still get a re-check alarm. |

## 22. Strongest ideas

1. **`idempotency_key UNIQUE` on a durable execution ledger**, checked before
   execution, returning `accepted: false` for a duplicate. Closes `C6`.
2. **Refusing ambiguity**: `fiberId` and `idempotencyKey` disagreeing throws
   rather than guessing.
3. **Hung-work detection via `execution_started_at` cutoff**, plus a re-check
   alarm for work that is running but not yet hung.
4. **Orphan detection by outer join** — a ledger row with no run row means a dead
   process.
5. **Exponential backoff on recovery scans that make no forward progress**, reset
   by any successful recovery. A poison-message answer from the liveness side.
6. **Eager validation of retry options at enqueue time**, so bad config throws
   immediately "instead of failing minutes later at execution time".
7. **Knowing when not to retry**: overloaded-DO errors are excluded because
   "retrying would make congestion worse".
8. **Retry config stored in the row, not memory**, because hibernation would lose
   it.
9. **A storage boundary as an enforcement mechanism** — if the LLM can write SQL,
   a queue in the same database is a convention, not a control.
10. **No in-memory WebSocket mode.** Refusing the non-durable path.
11. **OTel GenAI semantic conventions with explicit vendor namespacing**, and a
    refusal to squat on `ai.*`.
12. **Span lifetimes bound to invocations**, so a span cannot outlive the
    invocation owning its trace context.
13. **Single-writer by platform**: one alarm owner per agent, so scheduling cannot
    double-fire.
14. **Versioned storage schema checked on wake**, with forward-only idempotent
    migrations.
15. **Capability hooks run outside host context** so behaviour does not depend on
    which entrypoint triggered a phase.
16. **Documenting your own auth bypasses** in the docstring of the method that
    bypasses them.
17. **Sub-agent identity as logical name + content digest.**
18. **Persisted MCP connections** with per-server retry surviving hibernation.
19. **A design doc that describes no API** so it cannot go stale
    (`channels.md`) — and states that explicitly.
20. **Rejecting a durable wrapper until a consumer proves the interface** —
    "not rejected, deferred... Speculatively adding it would re-import every
    problem above."

## 23. Weakest architectural choices

1. **Total platform lock-in.** Every mechanism assumes Durable Objects,
   hibernation, alarms, and embedded SQLite. Unportable by design.
2. **No authentication, authorization, or principals.** Auth is a hook the
   developer must write.
3. **No tenancy, quotas, or cost accounting.**
4. **No agent versioning or revocation.**
5. **No adapter contract for third-party agents.** You write the agent; a
   meta-harness cannot be built on this without inverting it.
6. **No declared capability model.**
7. **A 13,000-line `index.ts`.** The `Agent` class is enormous — fibers,
   schedules, queues, MCP, workflows, sub-agents, state, and RPC all in one file.
8. **Agent code version is not pinned to in-flight fibers**, so recovery hands a
   pre-upgrade snapshot to post-upgrade code.
9. **No compensation or rollback.**

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| `idempotency_key UNIQUE` on the run/fiber ledger, checked pre-execution | **ADOPT_AS_STANDARD** | Closes `C6`; the only working precedent in seven projects |
| `accepted: false` return for a deduped start | ADOPT_AS_STANDARD | Honest signal: "already exists, here it is" |
| Throw when two identity keys disagree | ADOPT_AS_STANDARD | Refuse ambiguity rather than guess |
| Hung detection via `execution_started_at` cutoff + re-check alarm | ADOPT_AS_STANDARD | Best lost-worker answer in the study |
| Orphan detection by ledger-vs-run outer join | REUSE (pattern) | Cheap dead-process detection |
| Backoff on recovery scans making no progress | ADOPT_AS_STANDARD | Bounds poison-work cost without a DLQ |
| Eager validation of retry config at enqueue | ADOPT_AS_STANDARD | Fail at configuration time, not execution time |
| `isErrorRetryable` excluding overload errors | ADOPT_AS_STANDARD | Retrying a self-protecting service worsens congestion |
| Retry options persisted in the row | REUSE (pattern) | Survives eviction |
| Storage boundary as LLM enforcement boundary | ADOPT_AS_STANDARD | Sharpest security insight in the study |
| OTel GenAI semconv + vendor namespace discipline | ADOPT_AS_STANDARD | Directly strengthens ADR-0010 |
| Span lifetime bound to invocation | REUSE (pattern) | Prevents cross-invocation span leakage |
| Versioned storage schema checked on wake | REUSE (pattern) | Forward-only idempotent migrations |
| Design docs that describe no API | REUSE (practice) | Cannot go stale |
| Defer the durable wrapper until a consumer exists | ADOPT_AS_STANDARD | Anti-speculative-generality discipline |
| Durable Object as the substrate | BUILD | Cannot adopt; we are not on Workers |
| Auth as a developer hook | BUILD | Reject; the platform must own authN |
| 13k-line god class | BUILD | Reject as structure |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | **confirms strongly** | The cleanest affirmative case in the study. Identity is the DO name (`ctx.id.name` authoritative, never duplicated), it exists whether or not the agent runs, and *no separate registry is needed because platform naming is the registry*. Durable identity, disposable compute, with hibernation making eviction routine rather than exceptional. |
| ADR-0002 | neutral | No general Task/Run split, though `cf_agents_fibers` (durable intent) vs `cf_agents_runs` (live attempt) is the same shape for one subsystem — and the orphan join between them is exactly why the split is useful. |
| ADR-0003 | **confirms decisively** | I expected the first counter-evidence here: a `channels` package and a channels design doc. It is **human↔agent** transport (Slack/Telegram/email/voice), with `ChannelIdentity` naming a human correspondent. Sub-agents use typed RPC; `getSharedMemory` is the coordination path. **Seven for seven.** Durable agent-to-agent messaging is not in v0.1, and ADR-0003 should be rewritten around the shared-substrate pattern. |
| ADR-0004 | **challenges** | The one ADR this project genuinely challenges. There is *no* adapter contract, because the premise is that you write the agent as a subclass. Extension is `Lifecycle` capability composition, not adaptation. This is a coherent alternative I should be able to argue against: it buys enormous integration depth (durability, hibernation, tracing all ambient) at the cost of never running someone else's agent. Our answer must be that adapting existing agents is a *requirement*, not a preference — otherwise this design is better. |
| ADR-0005 | **confirms and extends** | MCP as protocol, plus something no other project does: **persisted** MCP connections with per-server retry and OAuth re-establishment surviving hibernation. If MCP servers are long-lived resources, connection state belongs in durable storage. |
| ADR-0006 | neutral | No A2A. |
| ADR-0007 | **challenges (weakly)** | Ships no principals at all; auth is `onBeforeConnect`. Defensible for an SDK where the developer owns the edge, and it is honest about which paths bypass the hook. But it means every consumer reimplements authorization, which is precisely what a platform should not delegate. Confirms the ADR by demonstrating the cost of omitting it. |
| ADR-0008 | **confirms** | Fifth consecutive project with filesystem-style skills and no memory store, and `getSharedMemory` is explicitly shared *state*, not semantic memory. Settled. |
| ADR-0009 | **challenges** | No pluggable sandbox provider, because the DO *is* the isolate. The insight to keep: `rfc-sub-agents.md` argues a child DO's private SQLite makes a policy **structural** rather than conventional, because "the LLM can bypass the queue by writing SQL". Our sandbox interface should therefore also be a *storage* boundary, not only a process boundary. |
| ADR-0010 | **confirms strongly** | Third real OTel and the best on convention: GenAI semconv where it exists, `cloudflare.agents.*` where it does not, "never bare top-level keys, never `ai.*`". Plus invocation-bound span lifetimes and a refusal to invent `otel.status_code` when status is span state. **Amend ADR-0010 to require semconv adherence and a declared vendor namespace, not merely OTel adoption.** |
| ADR-0011 | **amends** | Storage schema is versioned (v11) and migrated forward on wake, but agent *code* version is not pinned to in-flight fibers, so recovery hands a pre-upgrade snapshot to post-upgrade code. Adds a third dimension to the pin: **checkpoint payloads need their own version**, separate from the agent version and the adapter identity, because the recovery hook must know which shape it is being handed. |
| ADR-0012 | neutral | No declared capability model for runtimes. |
| ADR-0013 | neutral | No policy engine. |

**Two amendments to make now.**

1. **ADR-0006/ADR-0003 rewrite (raised, decided later).** After seven projects
   with zero durable agent-to-agent messaging and *four* independently choosing
   shared-substrate coordination, ADR-0003 as written defends something nobody
   builds. It should be restated: *agents coordinate through durable shared state
   and direct typed calls; there is no message bus in v0.1.*

2. **ADR-0010 gains a convention requirement.** "Uses OpenTelemetry" is too weak a
   bar — Omnigent showed a project can depend on six OTel packages and still have
   dead propagation code. Cloudflare shows the real bar: follow GenAI semantic
   conventions where they exist, declare a vendor namespace for everything else,
   and never squat on another tool's prefix.

**One methodological note.** `channels.md` is the best-argued design document in
this study and its argument is one I should apply to my own v0.1. It refuses to
own durability *because the application already owns a durable store*, and a
second private store "ends up competing with the first: two records of the same
conversation, two ideas of what was delivered, and no clear answer about which one
is true after a crash." It then rejects its own previous durable implementation
for a devastating reason: it "never delivered exactly-once ingress — a crash
between the callback and its receipt write replays the callback anyway — so the
guarantee it appeared to offer was not one it could keep."

**A guarantee you cannot keep is worse than an honest limitation.** That is the
sentence I want governing our v0.1 boundary.

## 26. Open questions

All three were resolved while reading; recording the answers rather than the
questions.

- **Does a fiber's `snapshot` carry a version?** **No.** Both `cf_agents_fibers`
  and `cf_agents_runs` declare `snapshot TEXT` with no version column
  (`index.ts:2253,2285`), and there is no snapshot-schema constant. So
  `onFiberRecovered` receives an unversioned blob written by a possibly-older code
  version. This is the concrete form of the ADR-0011 amendment: the platform
  versions its *own* schema (v11) carefully but leaves *user* checkpoint payloads
  unversioned. Our checkpoint envelope must carry a payload version. (→ OQ-024)
- **Is `cf_agents_runs` durable?** **Yes** — a real SQLite table
  (`id, name, snapshot, created_at`), so the orphan join is durable-vs-durable. A
  v5 addition is more interesting: a **root-side index of descendant facet
  fibers**, because "the fiber's authoritative row stays in the facet's own
  `cf_agents_runs` table; this table only lets the root alarm owner know which
  facets need recovery checks while they are idle" (`index.ts:2258-2261`). That
  answers a question our design will hit — *who checks on a sleeping child?* — with
  an index at the root that holds no authority, only a wakeup list. **Resolved.**
- **Does `getSharedMemory` serialise concurrent access?** It is not an SDK
  primitive at all: it appears only in a docstring example as a *user-defined* RPC
  method on a parent agent (`index.ts:8133`). Serialisation is free regardless,
  because the parent DO is single-threaded, so concurrent child calls queue. The
  real primitive is `parentAgent()`, which returns a typed stub and throws a clear
  error when called on a non-facet — with a comment explaining that the direct
  parent is the *last* entry of a root-first path, since destructuring the first
  entry "silently routes to the wrong DO" for chains deeper than one level.
  **Resolved.**
