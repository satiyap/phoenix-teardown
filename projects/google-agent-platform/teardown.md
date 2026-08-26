# Teardown — Google Agent Platform (ADK)

| | |
|---|---|
| Repo | https://github.com/google/adk-python |
| Commit read | `85b52f6a307598eb0bc20a6ab2a6780bb9efe7c1` (2026-08-25) |
| Version tested | `google-adk 2.7.1` |
| License | Apache-2.0 |
| Read on | 2026-08-26 |
| Evidence class | **A** (recon said B — wrong) |
| Depth | deep (focused: memory, auth/credentials, state scoping, telemetry) |
| Runtime class | `hybrid` — in-process agents with pluggable service backends |

The final Phase 3 pass. Phase 1 triaged this as **class B** ("SDK-shaped, unlikely
to speak to durability or tenancy") and budgeted 1.0 day. That triage was wrong,
and it is the **third stale-recon correction in Phase 3** after AG2 and Pydantic AI.

ADK 2.7.1 has a real memory *service* interface, a full OAuth2 credential
lifecycle, three-tier state scoping, seven pluggable code executors, resumability
with pause/resume and event rewind, event compaction, and the most carefully
structured OpenTelemetry implementation in the study. It answers several probes
nothing else does.

---

## 1. What problem it solves

Building agents on Google's stack with the option to run them anywhere. Every
subsystem is an abstract base class with an in-memory implementation for local
development and a Vertex/GCP implementation for production — sessions, memory,
artifacts, credentials, code execution, and evaluation all follow that shape.

## 2. Core architectural thesis

**Every stateful concern is a swappable service behind an abstract interface, with
an in-memory implementation for development and a managed implementation for
production.**

This is the most consistently applied architectural pattern in the study.
`BaseSessionService`, `BaseMemoryService`, `BaseArtifactService`,
`BaseCredentialService`, `BaseCodeExecutor`, `BaseEvalService`,
`BaseCredentialExchanger`, `BaseCredentialRefresher`, `BaseEventsSummarizer` — each
with `InMemory*` and Vertex/GKE/container variants.

The consequence worth stealing: **the local development path and the production
path are the same code with a different service injected.** Not a mock, not a
separate mode — the same interface.

## 3. Resource / object model

```text
App                          is_resumable, compaction config, plugins
 └── Agent (BaseAgent)       LlmAgent | Sequential | Parallel | Loop
      └── Invocation         one run; resumable, rewindable
           └── Event         actions{rewind_before_invocation_id, ...}

Session                      (app_name, user_id, session_id)
 ├── State                   THREE SCOPES by key prefix:
 │    ├── "app:"             application-wide
 │    ├── "user:"            per-user, cross-session
 │    ├── "temp:"            never persisted
 │    └── (unprefixed)       session-scoped, schema-VALIDATED
 └── Event[]                 the transcript

MemoryEntry                  content, author, timestamp, id, custom_metadata
AuthCredential               apiKey | http | oauth2 | openIdConnect | serviceAccount
Artifact                     versioned, per-session or per-user
Skill                        skills/ package
```

**Verified live** (2.7.1): state prefixes `app:` / `user:` / `temp:`; credential
types `['apiKey', 'http', 'oauth2', 'openIdConnect', 'serviceAccount']`; memory
service methods `['add_events_to_memory', 'add_memory', 'add_session_to_memory',
'search_memory']`.

## 4. Runtime model

In-process agents driven by a `Runner`, with flows (`flows/llm_flows/`) handling the
LLM loop. Composition via `SequentialAgent`, `ParallelAgent`, `LoopAgent`, and
agent-as-tool. Deployment targets Agent Engine, Cloud Run, GKE, or your own host.

## 5. Execution lifecycle

**`ResumabilityConfig` is the find of this pass** (`apps/_configs.py:29-47`):

> The "resumability" in ADK refers to the ability to:
> 1. **pause an invocation upon a long-running function call.**
> 2. **resume an invocation from the last event**, if it's paused or failed midway
>    through.
>
> Note: ADK resumes the invocation in a best-effort manner:
> 1. **Tool call to resume needs to be idempotent because we only guarantee an
>    at-least-once behavior once resumed.**
> 2. Any temporary / in-memory state will be lost upon resumption.

That second note is **the clearest statement of ADR-0014's requirement found
anywhere in the study**, and it is stated as a *contract the developer must
satisfy* rather than a guarantee the platform provides. See §25 — it is honest in
exactly the way Cloudflare's channels doc demands, and it also explains why `temp:`
state exists as a separate scope: state that cannot survive resumption is marked as
such in the key.

**Event rewind is first-class.** An event carrying
`actions.rewind_before_invocation_id == X` drops itself and everything back to the
earliest event of invocation `X`, and `_apply_rewinds` is documented as "the single
source of truth for 'which events are live' after rewinds"
(`events/_rewind_events.py`). So history is append-only on disk but *logically*
rewindable — a middle path between mutable history and a pure event log that no
other project takes.

## 6. Durability model

Sessions are the durable unit, with backends for SQLite, generic SQL databases,
Firestore, Redis, Vertex AI, and in-memory. `sessions/migration/` and
`sessions/schemas/` handle schema evolution — the second project after Cloudflare
to version its own storage schema.

`_restricted_pickle.py` is worth noting: an allow-listed unpickler, because session
state must round-trip arbitrary Python without becoming a deserialization RCE.
Nobody else in the study confronts that.

Resumability is best-effort and says so (§5). At-least-once on resume, with
idempotency pushed to the tool author.

## 7. Agent identity and lifecycle

Agents are Python objects with a `name`. No agent id, no registry, no versioning,
no revocation — `D1`, `D2`, `D4`, `D9` absent.

But identity of *scope* is strong: everything is keyed by `(app_name, user_id,
session_id)`, so memory, artifacts, credentials and state are all consistently
scoped to an application and a user. That is not agent identity, but it is the
tenancy-shaped keying that seven other projects lacked (see §16).

## 8. Multi-agent communication

No durable messaging. Multi-agent composition is `SequentialAgent`,
`ParallelAgent`, `LoopAgent`, agent-as-tool, and LLM-driven transfer between
agents. Coordination is through shared session `State`.

`a2a/` provides the A2A protocol as an **interop layer** — `a2a/agent`,
`a2a/executor`, `a2a/converters`, and an `experimental.py` marker. Same position as
AG2: A2A at the edge, own model inside.

## 9. Human interaction model

Long-running function calls plus resumability give real durable HITL: an invocation
pauses on a long-running tool and resumes from the last event, so an approval can
outlive the process. Combined with the `plugins/` callback surface
(`before_tool_callback`, `after_tool_callback`) this is a working approval
mechanism, though it is a *pattern* rather than a named `Approval` resource.

No principals, no multi-user permissions, no notification.

## 10. Context and memory

**The only real memory service in the study**, and the reason this pass mattered.

`BaseMemoryService` (`memory/base_memory_service.py`) has four methods:
`add_session_to_memory`, `add_events_to_memory`, `add_memory`, `search_memory`,
all scoped by `(app_name, user_id)`. Implementations: in-memory, **Vertex AI Memory
Bank**, and **Vertex AI RAG**.

`MemoryEntry` carries `content`, `id`, `author`, and `timestamp` — the timestamp
documented as "when the original content of this memory happened", not when it was
stored. So `H5` (provenance) is `first_class` for the first time: a memory knows who
said it and when it actually happened.

Two design details worth adopting:

1. **`add_events_to_memory` is an optional delta method** whose default raises
   `NotImplementedError` with a message naming the fallback: "This memory service
   does not support adding event deltas. Call `add_session_to_memory(session)` to
   ingest the full session." That is ADR-0012's fail-closed-with-actionable-message
   rule, applied correctly — contrast OpenHands' silent `pause()` no-op.
2. **`custom_metadata` is the extension point with a stated migration path**:
   "Prefer this for service-specific fields (e.g., TTL) that may later become
   first-class API parameters." An escape hatch that acknowledges it is a staging
   area for future API surface.

**Three-tier state scoping** (`sessions/state.py:64-66`) is the direct answer to
ADR-0008's claim that memory is not one thing:

| Prefix | Scope | Persisted |
|---|---|---|
| `app:` | application-wide | yes |
| `user:` | per-user, across sessions | yes |
| `temp:` | this invocation only | **no** — filtered out by every backend |
| *(none)* | session-scoped | yes, and **schema-validated** |

I verified the `temp:` exclusion is real in three independent backends
(`firestore_session_service.py:565`, `_redis_session_service.py:128,214`).

**Unprefixed state is validated against a declared Pydantic schema**, raising
`StateSchemaError` if a key is undeclared or mistyped — the only typed session state
in the study. Prefixed keys bypass validation, which is a sensible boundary: the
scoped namespaces are open, the session's own contract is closed.

**Compaction is real**: `apps/compaction.py`, `EventsCompactionConfig`,
`BaseEventsSummarizer`, `llm_event_summarizer.py`. Configurable summarisation of
event history, which with AG2's policies makes two projects that ship a strategy
rather than only a hook.

## 11. Tools and capabilities

A large `tools/` surface, MCP support, OpenAPI tool generation, and
`_reflect_retry_tool_plugin` (reflect on a tool failure and retry — a repair
strategy nobody else ships).

No declared capability *metadata* model. In Pydantic AI's terms ADK has
extensions (plugins, callbacks, services) but not capabilities-as-claims.

## 12. Security and IAM

**The best tool-credential story in the study**, and the area where class-B triage
failed hardest.

`auth/` is a complete subsystem:

```text
AuthCredentialTypes    apiKey | http | oauth2 | openIdConnect | serviceAccount
auth_schemes.py        OpenAPI-derived scheme definitions
oauth2_discovery.py    OIDC discovery
exchanger/             BaseCredentialExchanger + OAuth2 + a registry
refresher/             BaseCredentialRefresher + OAuth2 + a registry
credential_service/    BaseCredentialService: in-memory | session-state
credential_manager.py  lifecycle orchestration
auth_preprocessor.py   injects credentials into tool calls
auth_tool.py           tools that need auth declare it
```

Verified live: all five credential types present.

The important architecture is that **exchange and refresh are separate registries
behind separate interfaces**. Obtaining a credential and keeping it alive are
different problems with different failure modes, and most systems conflate them
into "get a token". A refresher registry means an expired OAuth2 token is renewed
by the platform rather than by every tool author.

No principals, no authorization model, no tenancy enforcement, no policy engine.
`J1`–`J3`, `J6`, `J10` absent. So ADK secures *outbound* tool credentials
thoroughly and models *inbound* authority not at all.

## 13. Sandboxing

**Seven pluggable code executors**, the widest range in the study:
`BaseCodeExecutor` with `container_code_executor`, `gke_code_executor`,
`vertex_ai_code_executor`, `agent_engine_sandbox_code_executor`,
`built_in_code_executor` (model-native), and `unsafe_local_code_executor`.

Naming the dangerous one **`unsafe_local`** is the right call — a developer cannot
select it without reading the word "unsafe". Compare Cloudflare's refusal to ship an
in-memory WebSocket mode: both are cases of making the unsafe path visible rather
than convenient.

Strong ADR-0009 evidence for the *process* boundary. No egress guard (Pydantic AI
remains the only one), and no storage-boundary argument (Cloudflare's).

## 14. Orchestration

`SequentialAgent`, `ParallelAgent`, `LoopAgent`, `workflow/`, and `planners/`.
Composition is agent-shaped rather than graph-shaped. No scheduling, no
compensation (`L8` — nine for nine absent).

`_reflect_retry_model_plugin` and `_reflect_retry_tool_plugin` implement
reflect-and-retry on failure, which is a genuine recovery strategy beyond backoff.

## 15. Observability

**The most carefully structured OTel implementation in the study.** Pydantic AI
versions its semconv adherence; ADK goes further and separates stability tiers into
distinct modules:

```text
_stable_semconv.py         conventions with compatibility guarantees
_experimental_semconv.py   incubating gen_ai attributes
_adk_attributes.py         ADK-owned names, in an adk.* namespace
_schema_version.py         deployment-pinnable telemetry schema version
```

`_adk_attributes.py` states the contract plainly:

> These attributes are defined by ADK itself; they are not part of any
> OpenTelemetry semantic convention... Everything named `adk.experimental.*` is
> emitted only when experimental telemetry is enabled and **carries no
> compatibility guarantee**: an attribute may be renamed, restructured, or removed
> in any release.

And `_schema_version.py` lets "a deployment **pin** which version of the ADK
telemetry format (span names, span/log attributes, metrics) it emits."

That completes a picture the study built across three projects: Cloudflare said
*follow the conventions*, Pydantic AI said *version your adherence*, ADK says
*separate stable from experimental, namespace what you own, mark experimental
attributes as unguaranteed, and let the deployment pin the version.*

Plus `_metrics.py`, `_token_usage.py`, `sqlite_span_exporter.py` (local trace
inspection), `node_tracing.py`, and an `auto_tracing_plugin`.

`evaluation/` is a full package with `BaseEvalService`, eval sets, and scenario
generation — the third project with first-class evaluation after Pydantic AI and
Omnigent's bench.

## 16. Multi-tenancy

Not a tenancy *model*, but **consistent `(app_name, user_id)` scoping across every
service** — sessions, memory, artifacts, credentials, and `app:`/`user:` state
prefixes — applied uniformly rather than in one subsystem.

**And it is enforced at the storage layer, not merely by convention.** I initially
recorded this as convention-only and was wrong; checking the schema
(`sessions/schemas/v0.py:146-161`) shows `app_name`, `user_id` and `id` are all
`primary_key=True` on `StorageSession`:

```python
class StorageSession(Base):
    __tablename__ = "sessions"
    app_name: Mapped[str] = mapped_column(..., primary_key=True)
    user_id:  Mapped[str] = mapped_column(..., primary_key=True)
    id:       Mapped[str] = mapped_column(..., primary_key=True, default=new_uuid)
```

That is **the same mechanism as Omnigent's `workspace_id`**: a lookup that omits or
mistakes the scope fails to find the row rather than returning someone else's. Two
independent projects converging on tenancy-in-the-primary-key is strong enough to
settle the question for our design.

What is still missing is an *authorization* check — nothing verifies that the caller
is entitled to the `user_id` it passes. So the storage layer prevents accidental
cross-tenant reads, and an authenticated principal model would be needed to prevent
deliberate ones. Which is precisely the ADR-0007 split described in §25.

No quotas, no cost limits (`N3` — Omnigent still the only answer).

## 17. Protocols and APIs

A2A (interop), MCP, OpenAPI tool generation, a CLI with a dev UI, and Agent Engine
deployment. `platform/` and `integrations/` hold provider specifics.

## 18. Storage

Pluggable per concern: sessions (SQLite, SQL, Firestore, Redis, Vertex,
in-memory), artifacts (versioned, GCS or in-memory), memory (Vertex Memory Bank,
Vertex RAG, in-memory), credentials (in-memory or session-state). Schema migrations
under `sessions/migration/`.

The `session-state` credential service is a nice touch: credentials can live in the
session so they follow the conversation rather than requiring separate
infrastructure.

## 19. Deployment architecture

Agent Engine, Cloud Run, GKE, or self-hosted. Per-Python-version constraints files
(`constraints-3.10.txt` … `3.14.txt`) — an unusual and welcome supply-chain
practice.

## 20. OSS / license / commercial model

Apache-2.0. Google-managed services (Vertex Memory Bank, Vertex RAG, Agent Engine,
Vertex Sessions) are the commercial layer, but every one sits behind an abstract
base class with a working local implementation.

**This is the healthiest open-core model in the study.** Nothing is withheld: the
interfaces and the in-memory implementations are complete enough to build and test
against, and the managed services are optional performance-and-scale upgrades.
Compare Pydantic AI (Logfire as an adjacent product) — both avoid holding the core
hostage, but ADK does it for six subsystems at once.

Verdict: **REUSE (targeted).** Apache-2.0 and Python. The service-interface pattern,
the credential exchange/refresh split, three-tier state scoping, and the telemetry
stability tiers are all worth taking. The rest is Google-stack-shaped.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | **inferable** | The strongest *credential* story in the study — OAuth2 exchange and refresh with typed schemes and a pluggable credential service — but there is no agent principal, so the agent acts with credentials rather than *as* an identity. Omnigent's RFC 8628 remains the only `first_class` answer. |
| S2 Torn side effect | **inferable** | No effect ledger, but the requirement is stated explicitly as a developer contract: "Tool call to resume needs to be idempotent because we only guarantee an at-least-once behavior once resumed." Honest, and the clearest articulation in the study — but it delegates the work rather than doing it. |
| S3 Upgrade mid-flight | **inferable** | Session storage schema is versioned with migrations, and telemetry schema is pinnable — but nothing pins the *agent* definition to an in-flight invocation. Ten projects, still nobody has versioning *and* pinning. |
| S4 Concurrent memory write | **inferable** | Best answer in the study, by decomposition rather than locking: `app:` / `user:` / `temp:` / session scopes separate what is shared from what is not, and unprefixed session state is schema-validated so a stray key is rejected. Reduces the surface where a conflict can occur, rather than resolving conflicts. |
| S5 Cancellation tree | undefined | No cancellation model found. |
| S6 Silent context loss | **first_class_answer** | Two mechanisms and both are explicit. `EventsCompactionConfig` with a pluggable `BaseEventsSummarizer` performs compaction deliberately, and event **rewind** (`rewind_before_invocation_id`) makes history reduction a first-class, inspectable operation with `_apply_rewinds` as "the single source of truth for which events are live". Loss is a modelled operation, not a side effect. |
| S7 Poison message | **inferable** | `_reflect_retry_model_plugin` / `_reflect_retry_tool_plugin` reflect on a failure and retry differently rather than repeating the same call, plus three distinct error callbacks (`on_model_error`, `on_tool_error`, `on_agent_error`, `on_run_error`). No DLQ or quarantine. |
| S8 Tenant leak | **first_class_answer** | **Enforced in the schema**, which I had to check rather than assume: `StorageSession` declares `app_name`, `user_id` and `id` all as `primary_key=True` (`sessions/schemas/v0.py:146-161`), so a query that omits or mistakes the scope finds nothing. Same mechanism as Omnigent's `workspace_id` — **second independent convergence on tenancy-in-the-primary-key.** Caveat: nothing authorizes the caller's claim to a `user_id`, so this prevents accidental leaks, not deliberate impersonation. |
| S9 Runaway spend | undefined | `_token_usage.py` measures; nothing enforces. |
| S10 Zombie sandbox | undefined | Executors are pluggable but lifecycle reaping is the backend's concern. |

## 22. Strongest ideas

1. **Every stateful concern behind an abstract base class with an in-memory
   implementation**, so the local path and the production path are the same code
   with a different service injected.
2. **Three-tier state scoping by key prefix** (`app:`, `user:`, `temp:`), with
   `temp:` filtered out by every persistence backend independently.
3. **Unprefixed session state validated against a declared Pydantic schema**, with
   prefixed namespaces deliberately exempt.
4. **A memory entry that records the author and when the content actually
   happened**, not when it was stored.
5. **Exchange and refresh as separate registries** — obtaining a credential and
   keeping it alive are different problems.
6. **An optional interface method whose `NotImplementedError` names the fallback**
   ("Call `add_session_to_memory(session)` to ingest the full session").
7. **`custom_metadata` as a documented staging area** for fields "that may later
   become first-class API parameters".
8. **Stating the idempotency requirement as a developer contract**, with the
   guarantee named: "we only guarantee an at-least-once behavior once resumed".
9. **Marking non-durable state in the key** (`temp:`), so "will be lost upon
   resumption" is visible at the point of use.
10. **Event rewind with a single documented source of truth** for which events are
    live.
11. **Naming the dangerous executor `unsafe_local_code_executor`.**
12. **Telemetry stability tiers as separate modules** — stable semconv,
    experimental semconv, and vendor-owned attributes.
13. **`adk.experimental.*` attributes explicitly carrying no compatibility
    guarantee.**
14. **A deployment-pinnable telemetry schema version.**
15. **An allow-listed unpickler** for session state, treating deserialization as an
    attack surface.
16. **Reflect-and-retry** rather than retry-identically.
17. **Sixteen named lifecycle hooks including four distinct error callbacks.**
18. **Per-Python-version constraints files** for reproducible installs.
19. **A credential service backed by session state**, so credentials follow the
    conversation.
20. **Six managed services, every one behind an interface with a local
    implementation** — open core without withholding.

## 23. Weakest architectural choices

1. **No agent identity, registry, versioning or revocation.**
2. **Tenancy by convention, not enforcement** — `(app_name, user_id)` is threaded
   everywhere but nothing prevents passing someone else's id.
3. **No principals, authorization model, or policy engine.** Outbound credentials
   are excellent; inbound authority is unmodelled.
4. **Idempotency delegated to tool authors**, honestly but entirely.
5. **No durable agent-to-agent messaging.**
6. **No cancellation model.**
7. **No egress control** — the SSRF hazard Pydantic AI addresses is open here, and
   ADK ships web-fetching tools.
8. **No quotas or cost enforcement.**
9. **Large surface**, with `labs/`, `features/`, `experimental` markers and
   `optimization/` all in the shipped package.

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| Service interface + in-memory impl for every stateful concern | **ADOPT_AS_STANDARD** | Local and production paths become the same code |
| Three-tier state scoping (`app:`/`user:`/`temp:`) | **ADOPT_AS_STANDARD** | Direct ADR-0008 mechanism |
| `temp:` filtered by every backend | ADOPT_AS_STANDARD | Non-durable state marked at the point of use |
| Schema-validated session state | **ADOPT_AS_STANDARD** | Only typed session state in the study |
| `MemoryEntry{author, timestamp}` with event-time semantics | ADOPT_AS_STANDARD | First real memory provenance |
| Credential exchange / refresh split | **ADOPT_AS_STANDARD** | Two problems, two interfaces |
| Optional method whose error names the fallback | ADOPT_AS_STANDARD | Correct form of ADR-0012 fail-closed |
| `custom_metadata` as declared staging area | REUSE (pattern) | Honest extension point with a migration path |
| Idempotency stated as a contract with the guarantee named | ADOPT_AS_STANDARD | Feeds ADR-0014 |
| Event rewind + single source of truth | REUSE (pattern) | Logical history reduction over an append-only store |
| `unsafe_local` naming | ADOPT_AS_STANDARD | Make the unsafe path visible |
| Telemetry stability tiers as modules | **ADOPT_AS_STANDARD** | Completes ADR-0010 |
| Pinnable telemetry schema version | ADOPT_AS_STANDARD | Consumers pin, producers evolve |
| Allow-listed unpickler | REUSE | Deserialization is an attack surface |
| Reflect-and-retry | REUSE (pattern) | Better than identical retry |
| Per-Python-version constraints | REUSE (practice) | Reproducible installs |
| Tenancy by convention | BUILD | Reject; use Omnigent's composite PK |
| Idempotency delegated to tool authors | BUILD | Reject; the platform replays, so it owns the hazard |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | neutral | Agents are Python objects with a `name`; no identity, registry or lifecycle. |
| ADR-0002 | **amends** | `Invocation` is a run with real lifecycle semantics — pausable, resumable "from the last event", and **rewindable**. No separate Task, but rewind is a Run-level operation my model lacked: our `Run` should support a logical rewind marker rather than only forward progress. |
| ADR-0003 | confirms | No durable agent-to-agent messaging; coordination via shared `State`. AG2 remains the sole precedent. |
| ADR-0004 | **confirms strongly** | The most consistent application of the pattern in the study, generalised beyond runtimes: **every stateful concern is a service interface with an in-memory implementation and a managed implementation.** The lesson for our adapter design is the in-memory sibling — if every pluggable interface ships a working local implementation, the development path and the production path are the same code with a different injection. |
| ADR-0005 | confirms | MCP plus OpenAPI tool generation as protocols, with no capability-claim model. |
| ADR-0006 | **confirms** | `a2a/` is a converter-and-executor interop layer marked `experimental`, separate from the internal agent model. Second independent confirmation after AG2. |
| ADR-0007 | **challenges (partially)** | Splits the ADR in a way I had not: ADK has an excellent model of **credentials the agent carries outward** (five typed schemes, OAuth2 exchange and refresh, a pluggable credential service) and **no model of authority flowing inward** (no principals, no authorization). Our ADR-0007 conflates these. A principal model and a credential model are different subsystems, and a platform needs both. |
| ADR-0008 | **confirms strongly — the mechanism, at last** | Seven projects said "no memory service"; this one has one, and it validates the ADR's central claim rather than contradicting it. Memory is explicitly **not one thing**: a `BaseMemoryService` for semantic recall (scoped `(app_name, user_id)`, with Vertex Memory Bank and RAG backends), and **separately** a four-scope state model (`app:`, `user:`, `temp:`, session). Adopt both the split and the prefix mechanism. Also `MemoryEntry.author`/`timestamp` gives the provenance our Knowledge node needs. |
| ADR-0009 | **confirms strongly** | Seven pluggable code executors — container, GKE, Vertex, Agent Engine sandbox, model-native, and `unsafe_local_code_executor`. Widest range in the study, and the naming of the unsafe option is itself a design decision worth copying. Note the gap: no egress guard, so ADK ships web-fetching tools with the SSRF hazard Pydantic AI closes. **Our three-boundary sandbox (process, egress, storage) needs all three; ADK has one, Pydantic AI has another, Cloudflare argues the third.** |
| ADR-0010 | **confirms and completes** | The final piece. Cloudflare: follow the conventions. Pydantic AI: version your adherence. **ADK: separate stable from experimental into distinct modules, namespace what you own, declare that `adk.experimental.*` "carries no compatibility guarantee", and let the deployment pin the telemetry schema version.** Adopt all four. |
| ADR-0011 | confirms (negatively) | Session storage schema is versioned with migrations and telemetry schema is pinnable — so this team clearly understands schema pinning — yet nothing pins the agent definition to an in-flight invocation. **Ten projects: nobody versions and pins.** The consistency of this gap across every project, including two that version other things carefully, is now itself the strongest argument for ADR-0011 being a differentiator. |
| ADR-0012 | **confirms (the error-message half)** | No capability-claim model, but the best example of the *fail-closed message* rule: an unsupported optional method raises `NotImplementedError` naming the fallback — "This memory service does not support adding event deltas. Call `add_session_to_memory(session)` to ingest the full session." Compare OpenHands' silent `pause()` no-op. Same situation, opposite handling. |
| ADR-0013 | neutral | Sixteen plugin callbacks are real interception seams, but there is no policy decision object to trace. Still **no shadow-comparison mode after ten projects.** |
| ADR-0014 | **confirms — and states the requirement better than I did** | No effect ledger, but `ResumabilityConfig` documents the exact hazard: "**Tool call to resume needs to be idempotent because we only guarantee an at-least-once behavior once resumed.**" That is a platform naming its guarantee precisely and pushing the remaining obligation to the developer. Our ADR should quote it, and then explain why we take the obligation *back*: a platform that replays owns the hazard, and asking every tool author to be idempotent is asking each of them to solve a distributed-systems problem correctly. |

**Two amendments to make.**

1. **ADR-0007 splits into principals and credentials.** ADK proves these are
   separable: it has a thorough outbound-credential subsystem and no inbound
   authority model at all. Our ADR should specify a `Principal` model (who is
   acting, how they authenticated, what they may do) *and* a `Credential` model
   (what secrets an action carries outward, how they are obtained and refreshed) as
   distinct subsystems, because a system can have one without the other.

2. **ADR-0008 gains a concrete mechanism.** The ADR said memory is not one thing
   but did not say how to divide it. ADK's answer: a semantic memory *service* for
   recall, and *four state scopes* — application, user, session, and explicitly
   non-durable — distinguished by key prefix and enforced by every backend. Adopt
   the four scopes, and adopt `temp:` in particular: marking non-durable state at
   the point of use is what makes "this will be lost on resumption" visible to the
   person writing the key.

**A methodological note, and the third of its kind.** Phase 1 triaged this project
as class B on the basis of its README and package shape. It has the only memory
service in the study, the best credential subsystem, the only typed session state,
the widest sandbox range, and the most careful telemetry structure. Together with
AG2 (dismissed on a tally) and Pydantic AI (stale version), **three of Phase 3's
six passes found substantially more than recon predicted, and in each case the
error was mine for trusting a cheap signal over the source.** Phase 4's targeted
passes should assume the same, and read before concluding.

## 26. Open questions

- **Answered by checking, after I initially assumed wrong.** `(app_name, user_id,
  id)` is a genuine **composite primary key** on `StorageSession`
  (`sessions/schemas/v0.py:146-161`), so scoping is enforced by the storage layer
  exactly as in Omnigent. My first read recorded it as convention-only; the schema
  says otherwise. Worth noting as a process point: I nearly published a wrong
  `absent`-style claim about a project I had already downgraded once. **Resolved.**
- Does Vertex AI Memory Bank support TTL or deletion, given `custom_metadata`
  mentions TTL as a service-specific field that "may later become first-class"?
  Relevant to `H6`. (→ OQ-030)
