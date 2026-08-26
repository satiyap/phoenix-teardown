# Teardown — Pydantic AI

| | |
|---|---|
| Repo | https://github.com/pydantic/pydantic-ai |
| Commit read | `b48ee3808631ea8796a7c3b6941863bde47e10be` (2026-08-26) |
| Version tested | `pydantic_ai 2.35.0` (Phase 1 recon said 1.0 — stale) |
| License | MIT |
| Read on | 2026-08-26 |
| Evidence class | A |
| Depth | deep (focused: capabilities, durability, security, telemetry) |
| Runtime class | `in_process` — a library, with durability delegated to external engines |

A focused pass rather than a full sweep, targeted at what this project is
*architected to answer*: type-safe composition, capability design, and integration
with established durable-execution engines. That framing is a direct application of
the lesson AG2 taught — budget by what a project can answer, not by a running
tally.

It answers more than expected in two areas nobody else covers well: **SSRF and
credential-endpoint defence**, and **versioned OTel semantic-convention
adherence**.

---

## 1. What problem it solves

Bringing typed, validated, testable engineering discipline to LLM agents. The
premise is that an agent is a Python function with a validated output type, and
everything else — tools, streaming, retries, durability — composes around that.

## 2. Core architectural thesis

**Cross-cutting behaviour belongs in composable, ordered capabilities rather than
in constructor arguments, and durability belongs to a workflow engine that already
solved it.**

The first half is stated as a project rule
(`pydantic_ai/capabilities/AGENTS.md`):

> Prefer a capability over a new `Agent` constructor kwarg when behavior
> contributes instructions, settings, tools, native tools, wrappers, lifecycle
> hooks, or event/history processing.

The second half is the more interesting architectural claim, and it is the
opposite of every other project in this study: rather than building durable
execution, Pydantic AI integrates **Temporal, DBOS, and Prefect** and treats them
as "first-class compatibility targets... **not peripheral adapters**"
(`durable_exec/AGENTS.md`).

## 3. Resource / object model

Deliberately thin — this is a library, not a platform.

```text
Agent[DepsT, OutputT]        typed agent; output_type drives validation
 ├── Capability              63 exported; composable, ordered
 │    └── CapabilityPosition  Literal['outermost', 'innermost']
 ├── Toolset                 FunctionToolset | MCPToolset | DynamicToolset
 ├── Model                   provider abstraction; resolved by model_id
 ├── RunContext[DepsT]       deps + usage + run state
 └── DeferredToolRequests    HITL/external work, as an OUTPUT TYPE
      ├── calls              tool calls needing external execution
      ├── approvals          tool calls needing human approval
      └── metadata           keyed by tool_call_id

pydantic_graph                separate package: graph execution
pydantic_evals                separate package: datasets, evaluators, online evals
```

There is no Agent resource, no registry, no channel, no tenancy. Nothing is
persisted by the library itself.

**Verified live** (2.35.0): `DeferredToolRequests` fields are
`['calls', 'approvals', 'metadata']`; `CapabilityPosition` is
`Literal['outermost', 'innermost']`; 63 capability names are exported.

## 4. Runtime model

In-process. `agent.run()` executes a graph (`_agent_graph.py`) inside the caller's
process. Under a durable engine, the *same agent* runs inside a Temporal workflow,
a DBOS step, or a Prefect flow, with the library owning the boundary crossing.

The hard part of that boundary is honestly documented: a `Model` instance "can't be
serialized into an activity/step/task, so a request carries a `model_id` string"
resolved through a registry on the far side (`durable_exec/_base.py:38-45`). That
is exactly the problem AX solved with opaque `agent_config` bytes, solved
differently — by making the *identifier* crossable rather than the object.

## 5. Execution lifecycle

No Task or Run resource. A run is a function call returning a typed result, and
under a durable engine the *engine's* workflow is the durable run.

**HITL is an output type, not a state.** If the model calls a deferred tool, the
run *returns* `DeferredToolRequests` with `calls` and `approvals` lists. The
caller resolves them and passes `DeferredToolResults` into the next run, matched by
`tool_call_id`. `build_results(..., approve_all=False)` constructs the reply.

This is the cleanest small-scale HITL design in the study, and it is worth
understanding why: **by making the pending state the return value, durability
becomes the caller's problem and therefore free.** The library never needs an
approval store, because the approval request is a value the caller already holds.
AX achieved a similar result by making approvals log content; Pydantic AI achieves
it with a type.

The tradeoff is that it only works while someone is holding the value. There is no
"come back in three days and find the pending approval" unless the caller persists
it — which is precisely what the durable-execution integrations are for.

## 6. Durability model

**The library has none, on purpose, and this is a genuine architectural position
rather than a gap.**

`durable_exec/` integrates Temporal, DBOS and Prefect (with Restate named as a
target), and the guidelines set out what the integration must preserve:

> Preserve run context, dependencies, message history, retries, model/profile
> selection, and toolset lifecycle across durable boundaries.
> Avoid hidden ordering assumptions, non-serializable state, and runtime-only
> closures unless the durable wrapper explicitly owns them.

**Unsupported combinations are rejected at the boundary with the best error
message in the study** (`durable_exec/_runtime_toolsets.py:38-49`):

```
`cancellation_token` cannot be used with {engine} durable execution because it is
a same-process handle and cannot cross the durable execution boundary. Cancel the
durable workflow or flow instead.
```

That message does three things at once: refuses the operation, explains *why* it
is impossible (a same-process handle cannot cross a serialization boundary), and
names the correct alternative. `reject_unsupported_runtime_toolsets` does the same
for toolsets that cannot be durably wrapped.

This is ADR-0012's fail-closed rule applied to *composition* rather than to
capability queries: an impossible combination fails at configuration time with an
actionable explanation, rather than at runtime with a serialization error.

## 7. Agent identity and lifecycle

No agent *identity*: no id, no registry, no persistence, no versioning, no
revocation. `D1`–`D4`, `D9` absent, appropriately for a library.

But there **is** a real agent *definition* artefact, which I nearly missed.
**Agent Specs** (`docs/agent-spec.md`) define an agent declaratively in YAML or
JSON — model, instructions, capabilities, settings — loaded with
`Agent.from_file('agent.yaml')` or `Agent.from_spec(dict)`:

```yaml
model: anthropic:claude-opus-4-6
instructions: You are a helpful research assistant.
model_settings:
  max_tokens: 8192
capabilities:
  - WebSearch:
      local: duckduckgo
  - Thinking:
      effort: high
```

The stated motivations include "separating agent configuration from application
code", "letting non-developers (prompt engineers, domain experts) configure
agents", and "storing agent definitions alongside other config files". So `D10`
(agent manifest) is `first_class`, and notably **capabilities are part of the
manifest** — a declared agent carries its declared extensions.

This also explains the serializability discipline. `_spec.py` provides `NamedSpec`
and registry/loading utilities shared between the evaluator and capability systems,
and `capabilities/AGENTS.md` makes it a rule: "Check durable execution, agent
specs, and serialized configuration before adding non-serializable state or hidden
runtime dependencies."

**A project rule that new features must not break serializability** is a
discipline our capability model needs, because a spec that cannot round-trip is a
spec that silently diverges from the running agent.

## 8. Multi-agent communication

Absent. Agents call other agents as functions, or via tools. No messaging, no
channels, no hub. Unsurprising for a library, and it leaves AG2 as the sole
F-section answer.

## 9. Human interaction model

`DeferredToolRequests.approvals` as described in §5, plus `ToolApproved` /
`ToolDenied` results and `approve_all`. Clean, typed, and caller-owned.

No principals, no permissions, no multi-user model, no notification.

## 10. Context and memory

No memory subsystem. `_history_processor.py` and a `ProcessHistory` capability
allow message-history transformation, which is where compaction would live, but
the library ships no compaction strategy of its own (contrast AG2's
`CompactStrategy` and four policies).

Seventh consecutive project with no memory service.

## 11. Tools and capabilities

The most sophisticated *composition* model in the study, and a genuinely different
answer to ADR-0012 than Omnigent's.

Where Omnigent's capability is **declared metadata about what a harness can do**,
Pydantic AI's is **an installable object that changes what the agent does**. 63
exports including `MCP`, `NativeTool`, `NativeOrLocalTool`, `WebSearch`,
`WebFetch`, `XSearch`, `ImageGeneration`, `Thinking`, `Instrumentation`,
`PrefixTools`, `PrepareTools`, `ProcessHistory`, `ProcessEventStream`,
`RaiseContentFilterError`, `HandleDeferredToolCalls`, `ToolSearch`,
`SelectModel`, `ResolveModelId`, `ThreadExecutor`, `Hooks`.

Three design points worth taking:

1. **Composition order is explicit and load-bearing.** `CapabilityOrdering`,
   `CapabilityPosition = Literal['outermost', 'innermost']`, `_ordering.py`, and
   `CombinedCapability`. The guidelines warn: "Preserve composition order. If a
   capability wraps model/tool/output/event behavior, check how it interacts with
   `CombinedCapability` and adjacent capabilities." Most middleware systems leave
   ordering implicit and are debugged by surprise.

2. **`NativeOrLocalTool` names the real problem.** Some capabilities exist natively
   in a provider (web search as a server-side tool) and locally otherwise. A
   single capability that resolves to either is the correct abstraction, and
   `provider-agnostic unless explicitly modeling a provider-native feature` is the
   stated rule for keeping that honest.

3. **Wrap-points are typed**: `WrapModelRequestHandler`, `WrapNodeRunHandler`,
   `WrapOutputProcessHandler`, `WrapOutputValidateHandler`, `WrapRunHandler`,
   `WrapToolExecuteHandler`, `WrapToolValidateHandler`. Every interception point in
   the pipeline has a named type, so a capability author knows exactly what they
   can hook and what shape it has.

**Both meanings of "capability" belong in our design**, and conflating them would
be a mistake: Omnigent/AG2 answer *"what can this thing do?"* (metadata, for
routing and fail-closed decisions), Pydantic AI answers *"what behaviour is
installed here?"* (composition, for extension). See §25.

## 12. Security and IAM

No IAM — no principals, no auth, no tenancy, no policy engine.

But `_ssrf.py` is **the most security-aware code in the entire study**, and it
addresses a threat every other project ignores: an agent that fetches a URL is an
SSRF primitive pointed at your own infrastructure.

**Cloud credential endpoints are blocked unconditionally**
(`_ssrf.py:101-118`):

> Cloud metadata / credential endpoints — always blocked, **even with
> `allow_local=True`**. When `allow_local=True` we skip the private-IP check, so
> these must be caught explicitly. Most are also covered by the private ranges
> above, but `168.63.129.16` (Azure) is a **public IP**, so the metadata guard is
> the only thing that blocks it.

Enumerated per provider: `169.254.169.254` (AWS IMDS, GCP, Azure, OCI,
DigitalOcean, Hetzner, IBM, OpenStack), `169.254.170.2` (**AWS ECS task IAM role
credentials**), `169.254.170.23` (**AWS EKS Pod Identity Agent**),
`168.63.129.16` (Azure WireServer), `100.100.100.200` (Alibaba),
`192.0.0.192` (Oracle Classic), `169.254.42.42` (Scaleway), plus IPv6 equivalents
(`fd00:ec2::254`) and CGNAT `100.64.0.0/10` "includes Alibaba Cloud metadata".

Two details that mark this as written by someone who has thought about bypasses:

- **Teredo prefix decoding** (`2001::/32`), because "the raw low-32 bytes are
  meaningless, so it needs its own decode" — an obfuscated-address bypass.
- **Decompression-bomb defence**: `Accept-Encoding` is restricted to
  `identity, gzip` and brotli/zstd/deflate are *rejected even if returned*,
  because "Brotli/Zstandard can expand a few compressed bytes into multi-MiB
  output in one decoder step, and `deflate` has to be buffered whole before its
  zlib-wrapped vs raw framing can be told apart".

**The design principle to steal is the escape hatch that cannot open the worst
hole.** `allow_local=True` exists for legitimate local development, and it
deliberately does *not* grant access to credential endpoints. Most escape hatches
are all-or-nothing; this one is scoped so the dangerous case stays closed.

## 13. Sandboxing

Absent, except that `_ssrf.py` is effectively egress control for URL fetching. No
process isolation.

## 14. Orchestration

`pydantic_graph` is a separate package for graph execution, and `_agent_graph.py`
runs the agent loop as a graph. Durable orchestration is delegated to Temporal,
DBOS or Prefect.

`L10` is answered affirmatively and deliberately: **do not build a workflow
engine, integrate the ones that exist.** This is the strongest evidence in the
study for keeping orchestration external, because it is the only project that
treats the integration as a first-class compatibility contract with its own
guidelines and workflow-level tests.

No compensation (`L8`, eight for eight — though under Temporal, saga
compensation is the engine's job, which is arguably the correct answer to the gap).

## 15. Observability

**The best OTel semantic-convention story in the study, ahead of Cloudflare's.**

Cloudflare follows GenAI semconv. Pydantic AI *versions its adherence*
(`docs/logfire.md:294-298`):

> Pydantic AI follows the OpenTelemetry Semantic Conventions for Generative AI
> systems, specifically **version 1.37.0** of the conventions. The instrumentation
> format can be configured using the `version` parameter of
> `InstrumentationSettings`.
>
> Versions 2, 3, and 4 are **deprecated compatibility formats**. Passing one of
> these versions emits a `PydanticAIDeprecationWarning`; use version 5 unless you
> are temporarily preserving an older telemetry pipeline.

So a telemetry pipeline built against an older convention keeps working, with a
deprecation path, while new users get current semconv. `_otel_messages.py` pins
its message-part types to a *specific spec commit* for traceability.

This solves a problem I had not considered: **semantic conventions change, and a
telemetry consumer is a downstream dependency you cannot break.** Our ADR-0010
requires semconv adherence; it did not say what happens when the conventions move.

`Instrumentation` is also a capability (composable), and `Agent.instrument_all()`
is a global switch. `_instrumentation.py` and `models/instrumented.py` carry the
implementation.

**Cost tracking is real**: `_cost.py` uses `genai-prices`, a separately maintained
pricing dataset, with `CostCalculationFailedWarning` when a price cannot be
determined and `preload_pricing_data()` to keep the one-time snapshot load off the
event loop. Second project with cost accounting (after Omnigent), and the only one
sourcing prices from a maintained external dataset rather than a local table.

## 16. Multi-tenancy

Absent, as expected for a library.

## 17. Protocols and APIs

MCP as a capability and a toolset (`_mcp.py`, `_mcp_compat.py`, `capabilities/mcp.py`).
Native provider tools where they exist. `clai` is a CLI. No A2A, no ACP, no server.

`pydantic_evals` deserves mention as an interface: datasets, evaluators, online
evaluation (`_online.py`, `online_capability.py`), and OTel emission
(`_otel_emit.py`). Evaluation as a first-class package with its own spec system is
something no other project ships.

## 18. Storage

None. The library persists nothing; durability is the engine's.

## 19. Deployment architecture

A library plus a CLI. Deployment is whatever hosts your Python, or a Temporal /
DBOS / Prefect worker.

## 20. OSS / license / commercial model

MIT. `pydantic_ai_slim` keeps the dependency surface small, with extras per
provider. Commercial alignment is Logfire (the company's observability product),
but instrumentation is plain OTel and works with any backend — a clean way to
monetise adjacent to an open core without holding the core hostage.

Verdict: **REUSE (targeted).** MIT and Python, so genuinely usable. Two components
are worth taking almost verbatim: **`_ssrf.py`'s guard list and reasoning**, and
the **versioned-semconv instrumentation pattern**. The capability composition model
is worth copying as a *design*, though ours must cross a network boundary theirs
does not.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | undefined | No principals or auth. |
| S2 Torn side effect | **inferable** | The library has no ledger, but under Temporal/DBOS/Prefect this is the *engine's* guarantee, and the integration guidelines require preserving retries across the boundary. Delegated, not solved — a legitimate answer, and the honest one. |
| S3 Upgrade mid-flight | **inferable** | No agent version, but the durable integration confronts the same problem: a `Model` cannot cross the boundary, so a `model_id` string is resolved through a registry on the far side. That is the identifier-not-object pattern our pin needs. Temporal's own versioning would carry the rest. |
| S4 Concurrent memory write | undefined | No memory store. |
| S5 Cancellation tree | **first_class_answer** | Not for tree propagation, but for something no other project does: it **refuses** a same-process `cancellation_token` at a durable boundary with an error explaining why it cannot cross and naming the alternative. Recognising that a cancellation primitive is scope-bound is the insight. |
| S6 Silent context loss | undefined | `ProcessHistory` allows history transformation, but no compaction strategy ships and no loss signal exists. |
| S7 Poison message | undefined | Delegated to the engine. |
| S8 Tenant leak | undefined | No tenancy. |
| S9 Runaway spend | **inferable** | Real cost calculation via a maintained `genai-prices` dataset, with usage aggregated on `RunUsage` and a warning when pricing fails. But it *measures* rather than *enforces* — no budget gate. Omnigent remains the only enforcement answer. |
| S10 Zombie sandbox | undefined | No sandbox. |

## 22. Strongest ideas

1. **Cloud credential endpoints blocked even when the local-access escape hatch is
   open.** An escape hatch scoped so it cannot open the worst hole.
2. **A per-provider enumerated metadata blocklist**, including AWS ECS task-role
   and EKS Pod Identity credential endpoints, and Azure's *public-IP* metadata
   service that no private-range check would catch.
3. **Teredo obfuscated-address decoding** as an SSRF bypass defence.
4. **Decompression-bomb defence by restricting `Accept-Encoding` to what can be
   size-limited while streaming**, and rejecting other encodings even if returned.
5. **Versioned OTel semantic-convention adherence** with deprecated compatibility
   formats and a warning, so telemetry consumers get a migration path.
6. **OTel message types pinned to a specific spec commit** for traceability.
7. **Refusing an impossible composition at configuration time** with an error that
   explains the mechanism and names the alternative.
8. **HITL as a typed output** (`DeferredToolRequests`), making pending state the
   caller's value and therefore durable for free.
9. **Explicit, load-bearing composition order** (`CapabilityPosition`,
   `CapabilityOrdering`, `CombinedCapability`) rather than implicit middleware
   stacking.
10. **Every interception point has a named type** (seven `Wrap*Handler` types).
11. **`NativeOrLocalTool`** — one capability that resolves to a provider-native
    implementation or a local one.
12. **Treating durable engines as first-class compatibility targets**, with their
    own guidelines and workflow-level tests, rather than as adapters.
13. **Crossing a boundary with an identifier, not an object** (`model_id` +
    registry) because the object is unserializable.
14. **A project rule that new features must not break serializability**, checked
    against durable execution and agent specs.
15. **Cost from a separately maintained pricing dataset** (`genai-prices`) rather
    than a hardcoded table, with an explicit warning when calculation fails.
16. **A shared spec system** (`NamedSpec`) reused by both evaluators and
    capabilities.
17. **Evaluation as a first-class package** with online evaluation and OTel
    emission.
18. **`AGENTS.md` per package** stating design rules for that directory.

## 23. Weakest architectural choices

1. **No durability of its own**, so every durability property depends on adopting
   Temporal, DBOS or Prefect. Correct for a library, insufficient for a platform.
2. **No agent identity, registry, versioning or revocation.**
3. **No principals, auth, policy or tenancy.**
4. **No agent-to-agent messaging.**
5. **HITL works only while the caller holds the value**, unless a durable engine
   persists it.
6. **No memory or compaction**, only a history-processing hook.
7. **Cost is measured, not enforced** — no budget gate.
8. **63 capabilities is a large surface** for a composition system whose ordering
   is load-bearing; the guidelines acknowledge the interaction risk.

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| `_ssrf.py` guard list + reasoning | **REUSE (port)** | Most security-aware code in the study; the threat is ours too |
| Escape hatch that cannot open the worst hole | **ADOPT_AS_STANDARD** | `allow_local` never grants credential-endpoint access |
| Restricted `Accept-Encoding` for bounded downloads | ADOPT_AS_STANDARD | Decompression-bomb defence |
| Versioned semconv adherence + deprecation path | **ADOPT_AS_STANDARD** | Amends ADR-0010; telemetry consumers are dependencies |
| Pinning message types to a spec commit | REUSE (practice) | Traceable convention drift |
| Refuse impossible composition at config time, with the reason and the alternative | **ADOPT_AS_STANDARD** | Best fail-closed message in the study |
| HITL as a typed output | REUSE (pattern) | Free durability at small scale |
| Explicit composition position + ordering | ADOPT_AS_STANDARD | Ordering must be declared, not discovered |
| Named types for every wrap point | REUSE (pattern) | Makes extension points discoverable |
| `NativeOrLocalTool` resolution | ADOPT_AS_STANDARD | Correct abstraction for provider-native features |
| Identifier-not-object across a boundary | ADOPT_AS_STANDARD | Reinforces ADR-0011's pin design |
| Serializability as a project rule | ADOPT_AS_STANDARD | Our capabilities cross a network boundary |
| External maintained pricing dataset | **INTEGRATE** (`genai-prices`) | Cost data is a maintenance burden worth outsourcing |
| Durable engines as compatibility targets | REUSE (pattern) | ADR-0004/L10 evidence |
| Per-package `AGENTS.md` design rules | REUSE (practice) | Keeps a large surface coherent |
| Library-owned durability | BUILD | We must own durability; delegation is not available to a platform |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | neutral | No agent identity; an `Agent` is a Python object. Appropriate for a library, uninformative for us. |
| ADR-0002 | neutral | No Task or Run resource. Under a durable engine, the engine's workflow is the run — which is itself an argument that Run belongs to whoever owns durability. |
| ADR-0003 | confirms | No agent-to-agent messaging. AG2 remains the sole answer. |
| ADR-0004 | **confirms strongly, from the other direction** | Every other project adapts *agents*; Pydantic AI adapts *durability engines*, treating Temporal/DBOS/Prefect/Restate as "first-class compatibility targets... not peripheral adapters", with rules requiring run context, deps, history, retries, model selection and toolset lifecycle to survive the boundary. Two transferable lessons: **cross a boundary with an identifier, not an object** (`model_id` + registry, because a `Model` is unserializable), and **make serializability a project rule** so new features cannot quietly break the boundary. |
| ADR-0005 | confirms | MCP as both a capability and a toolset, with native provider tools distinguished via `NativeOrLocalTool`. Protocol, not capability model. |
| ADR-0006 | neutral | No A2A. |
| ADR-0007 | neutral | No principals. |
| ADR-0008 | confirms | No memory service; only a history-processing hook. **Seventh consecutive project.** |
| ADR-0009 | **amends** | No process sandbox, but `_ssrf.py` is *egress* sandboxing and it identifies a threat our ADR-0009 does not mention: **an agent that fetches URLs is an SSRF primitive aimed at your own infrastructure and your cloud credential endpoints.** Add to ADR-0009: any URL-fetching capability must go through a guard that blocks private ranges, link-local, CGNAT, and an enumerated cloud-metadata list — and the local-development escape hatch must not open the credential-endpoint hole. |
| ADR-0010 | **amends** | **Best semconv story in the study.** Pinned to GenAI semconv 1.37.0, with versions 2–4 as deprecated compatibility formats that emit a warning. Cloudflare taught us to *follow* conventions; Pydantic AI shows conventions *move*, and a telemetry consumer is a downstream dependency you cannot break. Amend ADR-0010: declare the semconv version, support one deprecation window, warn on deprecated formats. Also `_otel_messages.py` pins types to a specific spec commit. |
| ADR-0011 | **confirms** | Indirect but useful. The durable boundary forced the same problem our pin solves: a `Model` object cannot cross, so a `model_id` string crosses and is resolved through a registry on the far side. **A pin should be an identifier plus a resolver, never a serialized object** — which also makes the pin comparable across versions. |
| ADR-0012 | **amends — two meanings of "capability"** | This is the most conceptually useful finding of the pass. Omnigent and AG2 mean *declared metadata about what a thing can do*, used for routing and fail-closed decisions. Pydantic AI means *an installed object that changes behaviour*, composed with explicit ordering. **Both belong in our design and must not share a name.** Proposal: `Capability` = declared, queryable, verified metadata (ADR-0012 as written); `Extension` = installable composed behaviour with declared position and ordering. Also adopt Pydantic AI's discipline that every wrap point is a named type, and that ordering is declared rather than emergent. |
| ADR-0013 | neutral | No policy engine. |
| ADR-0014 | **confirms (by delegation)** | Has no effect ledger, and does not pretend to: idempotency is the durable engine's job, and the integration guidelines require retries to survive the boundary. A legitimate answer for a library, and a reminder that our ledger must interoperate with an engine that has its own — if a caller runs us inside Temporal, two idempotency mechanisms must not fight. |

**Two amendments and one new distinction.**

1. **ADR-0009 gains egress guarding.** The sandbox ADR is about process isolation
   and says nothing about outbound requests. Any agent with a fetch tool can reach
   `169.254.169.254` and exfiltrate cloud credentials. Port Pydantic AI's guard
   list, including the rule that the local-access escape hatch never opens
   credential endpoints.

2. **ADR-0010 gains semconv versioning.** Declare which GenAI semconv version we
   emit, support exactly one deprecation window with a warning, and pin our
   message-part types to a spec commit.

3. **`Capability` and `Extension` are different things.** ADR-0012 conflates
   declared metadata with installed behaviour. Splitting them removes an ambiguity
   I had not noticed across five projects that use the same word for both.

## 26. Open questions

- **Partly answered while reading.** There are *two* composable modes for deferred
  calls, which changes the picture. By default the agent "pauses and returns
  `DeferredToolRequests` as output" (caller-owned durability). Alternatively the
  `HandleDeferredToolCalls` capability "intercepts those calls, invokes your
  handler to resolve them, and continues the run automatically" — and the handler
  may **decline by returning `None`, in which case the next
  `HandleDeferredToolCalls` capability in the chain gets a chance, and unhandled
  calls bubble up as `DeferredToolRequests` output as usual"**
  (`docs/capabilities/handle-deferred-tool-calls.md`). That chain-with-decline-and-
  fallback is a good pattern: a policy handler can auto-approve what it recognises
  and let anything unrecognised fall through to a human. Whether a *durable engine*
  persists a pending `DeferredToolRequests` across workflow suspension I did not
  verify. (→ OQ-027)
- Is `genai-prices` maintained on a cadence that makes it safe to depend on for
  budget enforcement, or only for reporting? Relevant if we adopt it for ADR-0013
  cost gates. (→ OQ-028)
