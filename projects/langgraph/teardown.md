# Teardown — LangGraph / LangSmith

| | |
|---|---|
| Repo | https://github.com/langchain-ai/langgraph |
| Commit read | `38031739e551638e373fb553453256c23feeb41f` (2026-08-24) |
| Version tested | `langgraph` 1.2.11, `langgraph-checkpoint` 4.2.0, `langgraph-sdk` 0.4.3 |
| Docs | https://langchain-ai.github.io/langgraph/ |
| License | MIT (runtime). LangSmith server and LangGraph Platform are closed. |
| Read on | 2026-08-26 |
| Evidence class | A for the runtime; B for Platform/LangSmith behaviour |
| Depth | deep |
| Runtime class | `worker_queue` (Platform) over an `in_process` graph runtime |

Claims below cite `path:line @ 3803173` or a verified experiment. Three hard
scenarios were tested by execution rather than reading; those are marked
**verified empirically** and the scripts are described inline.

---

## 1. What problem it solves

Developers building multi-step LLM applications need execution to survive
process death, pause for human input, and resume without redoing everything.
LangGraph provides a graph runtime where every super-step boundary is a
persistence point, so a run becomes resumable state rather than a stack frame.
Before it, that meant hand-rolled state machines with ad-hoc persistence.

## 2. Core architectural thesis

Model agent execution as a **Pregel-style super-step loop over versioned
channels**, and make the persistence boundary an explicit, caller-selected
tradeoff. State is not "the conversation"; it is a set of named channels with
monotonic versions, plus a per-node record of which versions each node has
already seen. That `versions_seen` bookkeeping is what makes resume
deterministic rather than heuristic.

The bet: if you get the checkpoint contract right, durability, HITL,
time-travel, and forking all fall out of the same mechanism. Largely vindicated
— the interrupt/resume, fork, and replay features are all the same primitive
viewed differently.

## 3. Resource / object model

Two distinct models, which matters more than any single feature.

**OSS runtime** — no agent, no user, no tenant:

```text
Graph (compiled Pregel)
 ├── Node
 ├── Channel              (named, versioned)
 └── Thread               (identified only by config thread_id)
      └── Checkpoint      (id, ts, channel_values, channel_versions, versions_seen)
           ├── PendingWrite      (task_id, channel, value)
           └── CheckpointMetadata (source, step, parents, run_id)

Store (separate from checkpointer)
 └── Item (namespace tuple, key, value, TTL)
```

**Platform (closed, from SDK schema)** — this is where resources appear:

```text
Assistant                 (assistant_id, graph_id, config, context, version, name)
 └── AssistantVersion     (integer versions)
Thread                    (thread_id, status, values, interrupts)
 └── Run                  (run_id, thread_id, assistant_id, status, multitask_strategy)
Cron                      (scheduled runs)
```

`libs/sdk-py/langgraph_sdk/schema.py:246,300,362,383 @ 3803173`

The root resource in the OSS runtime is the **Thread**, and it is not even a
stored object — it is a `thread_id` string in a config dict that namespaces
checkpoints. Threads only become real resources in the Platform.

Surprise worth noting: `Assistant` is the closest thing to an agent, and it is
a *configuration binding* over a `graph_id`, with integer versions. Code lives
in the graph; identity and config live in the Assistant.

## 4. Runtime model

The OSS runtime is a library: it runs in your process, and you own the event
loop. `B3` is unambiguous — the caller drives, and `invoke`/`stream` are
synchronous from the caller's view even though internals are async-capable.

The Platform wraps this in a queue-worker architecture with an HTTP API, which
is where `worker_queue` applies. Since that layer is closed, its dispatch,
lease, and recovery behaviour is class B evidence at best.

Nothing in the OSS runtime launches, hosts, or attaches to an external agent
process. There is no adapter concept: your agent *is* Python running inside the
graph.

## 5. Execution lifecycle

The super-step loop, per `libs/langgraph/langgraph/pregel/_loop.py @ 3803173`:

```text
  load checkpoint for thread
       ↓
  compute tasks  (channels whose version > node's versions_seen)
       ↓
  execute tasks in parallel  ──→ writes buffered as PendingWrite
       ↓
  apply writes, bump channel versions
       ↓
  persist checkpoint  (timing depends on durability mode)
       ↓
  loop until no tasks remain
```

Run status vocabulary exists only at the Platform layer:
`pending | running | error | success | timeout | interrupted`
(`schema.py:23`), with thread status `idle | busy | interrupted | error`
(`schema.py:34`).

The OSS runtime has **no run state machine at all** — a run is a function call.
This is the sharpest illustration of ADR-0002's problem: with no Task and no
durable Run resource, "retry this work" has nowhere to live.

## 6. Durability model

The strongest area, and the reason this was the Phase 2 anchor.

**Three explicit durability modes** (`libs/langgraph/langgraph/types.py:89`):

| Mode | Semantics |
|---|---|
| `sync` | persisted before the next step starts |
| `async` | persisted while the next step executes |
| `exit` | persisted only when the graph exits |

Making this a caller-visible knob rather than an internal detail is a genuinely
good design decision. The performance/safety tradeoff is real and only the
caller knows which they want.

**What is durable:** channel values, channel versions, `versions_seen`, pending
writes, and metadata recording `source` (`input | loop | update | fork`), `step`,
`parents`, and `run_id` (`base/__init__.py:38-92`). Checkpoint IDs are
"unique and monotonically increasing, so can be used for sorting" (`:97`).

**Recovery mechanism:** deterministic task IDs. Task identity is hashed from
`checkpoint_id_bytes + checkpoint_ns + step + node`, using xxhash for
checkpoint format v>1 and uuid5 below that
(`pregel/_algo.py:550,616,834`). On resume, a completed task's writes are
already in `pending_writes` under that ID, so it is not re-run. There is even a
`task_id_checksum` assertion (`:662`) guarding the invariant.

**Retry** is declarative: `RetryPolicy` with `initial_interval`,
`backoff_factor`, `max_interval` (`types.py:418`), applied per node.

**Delivery semantics: at-least-once at node granularity.** Verified
empirically — see S2 below. Nothing in the runtime provides side-effect
idempotency; `CachePolicy` (`types.py:521`) is a performance cache keyed on node
input, not an idempotency barrier.

### The checkpointer conformance suite

`libs/checkpoint-conformance/` is the single most reusable idea in this project.
It defines a capability enum and splits it into mandatory and optional
(`conformance/capabilities.py @ 3803173`):

```text
BASE (every checkpointer must):  put, put_writes, get_tuple, list, delete_thread
EXTENDED (optional):             delete_for_runs, copy_thread, prune,
                                 delta_channel_history
```

Capabilities are **detected at runtime** by checking whether a method is
overridden from `BaseCheckpointSaver`, then only the applicable spec tests run
(`capabilities.py:_is_overridden`). A storage backend can therefore declare a
partial implementation honestly and still be validated against the parts it
claims.

This is exactly the shape of the problem ADR-0004 has with harness adapters,
where Claude Code can checkpoint and a raw HTTP agent cannot. Base + extended +
runtime detection + conformance tests is a proven answer to capability
negotiation across heterogeneous backends. Steal the pattern.

## 7. Agent identity and lifecycle

Effectively absent in OSS. There is no `Agent`, no `agent_id`, no registry —
grep for `agent_id` in `libs/langgraph/langgraph/` returns nothing.

The Platform's `Assistant` supplies a partial answer: stable `assistant_id`,
integer `version`, `AssistantVersion` history, name and description
(`schema.py:246-275`). But an Assistant is config-over-graph, not a principal:
it holds no credentials, no capabilities, no owner, no tenant.

## 8. Multi-agent communication

No agent-to-agent messaging. Multi-agent means multiple nodes in one graph
sharing channel state, or subgraphs. Communication is shared mutable state, not
messages: no mailbox, no delivery guarantee, no correlation IDs, no ordering
guarantee beyond super-step sequencing.

`Send` (`types.py`) enables dynamic fan-out to nodes within a graph, which is
task spawning rather than messaging.

## 9. Human interaction model

`interrupt()` is a first-class, durable pause (`types.py:851`). It raises
`GraphInterrupt`, surfaces a value to the client, and requires a checkpointer.
Resume uses `Command(resume=...)`, and multiple interrupts in one node are
matched to resume values positionally.

Interrupts are exposed on the Thread as `interrupts: dict[task_id, list[Interrupt]]`
(`schema.py:300`), so a pending approval is queryable rather than lost in
memory. Genuinely good.

The critical caveat is in the docstring itself: "The graph resumes from the
start of the node, **re-executing** all logic" (`types.py:864`). Node-level
granularity is the root cause of the S2 failure below.

Humans are not modelled. There is no Principal, and the auth layer's subject is
a `BaseUser` with `identity`, `is_authenticated`, `permissions`
(`sdk-py/langgraph_sdk/auth/types.py:152-202`). An agent cannot be a principal
here.

## 10. Context and memory

Two clearly separated stores, which supports ADR-0008:

| Concept | Mechanism | Scope |
|---|---|---|
| Working execution state | Checkpointer channels | thread |
| Cross-thread memory | `BaseStore` | arbitrary namespace tuple |
| Node-output cache | `BaseCache` (memory, redis) | cache key |

`BaseStore` is explicitly "shared across threads, scoped to user IDs, assistant
IDs, or other arbitrary namespaces" (`store/base/__init__.py:708`), with
hierarchical namespaces, `TTLConfig` (`refresh_on_read`, `omit_expired`,
`default_ttl`, `sweep_interval_minutes`, `:545`), and optional semantic search
via `IndexConfig` (`:578`).

What is missing: permissions and provenance. Namespaces are a convention, not an
authorization boundary — any code with the store handle can read any namespace.
No provenance field records where an item came from. So this validates the
*separation* in ADR-0008 while leaving H4 and H5 unanswered by precedent.

## 11. Tools and capabilities

Tools are Python callables bound at graph construction. No capability
abstraction, no registry, no versioning, no scoping, no policy interception. MCP
is available via separate LangChain packages, not modelled in the runtime.

Note the vocabulary collision: LangGraph's `Capability` enum is about
*checkpointer storage operations*, not agent capabilities. Different concept,
same word.

## 12. Security and IAM

Present only in the SDK/Platform layer, and it is a resource/action
authorization model with pleasant ergonomics
(`sdk-py/langgraph_sdk/auth/__init__.py:98-225`): a global `@auth.authenticate`
handler runs on every request, then handler resolution falls back from
exact resource+action (`@auth.on.threads.create`), to resource
(`@auth.on.threads`), to global (`@auth.on`). Resources include `threads`,
`assistants`, `store`.

The specificity-based fallback chain is a good pattern worth borrowing for our
policy layer.

But the principal is always a human user. No agent identity, no delegation, no
tenant isolation primitive, no audit log, no secret management. **S1 is
undefined**: with no agent principal, "whose credentials apply when A delegates
to B" cannot be posed.

## 13. Sandboxing

None. Nodes are Python functions in the host process with no isolation
whatsoever. Sandboxing is entirely out of scope, which is a defensible library
choice but means zero evidence for ADR-0009.

## 14. Orchestration

This is what LangGraph *is*. Cyclic graphs with conditional edges, `Send`-based
dynamic fan-out, subgraphs with independently controllable checkpointing
(`Checkpointer = None | bool | BaseCheckpointSaver`, where `None` inherits,
`False` disables — `types.py`), declarative retry, and `Cron` at the Platform
layer.

`MultitaskStrategy = reject | interrupt | rollback | enqueue` (`schema.py:81`)
is a first-class answer to concurrent runs on one thread — a question most
systems leave implicit. Worth adopting the vocabulary.

On L10: could Temporal replace it? Not cleanly. The channel-versioning model is
inseparable from the agent state abstraction. But the durability layer beneath
it is a checkpointer interface, and *that* is replaceable.

## 15. Observability

**No OpenTelemetry.** A grep for `opentelemetry` across `libs/` finds nothing
outside unrelated CLI strings. Telemetry flows to LangSmith through
`LangSmithTracing` config (`schema.py:111`) over a proprietary protocol, and the
LangSmith server is closed.

The runtime does emit a well-structured debug event stream
(`_DebugCheckpointPayload`, `_DebugTaskPayload`, `_DebugTaskResultPayload`,
`RunMetadataPayload` — `schema.py:686-723`), so the event vocabulary exists; it
is simply not standards-based.

Direct support for ADR-0010: the strongest OSS agent runtime in this study
chose proprietary telemetry, and the consequence is that its best observability
is locked behind a commercial product. That is the outcome to avoid.

## 16. Multi-tenancy

Absent from OSS. No organization, workspace, project, or tenant anywhere in the
runtime. Reserved entirely for the Platform (`N8` = commercial tier).

## 17. Protocols and APIs

OSS surface is a Python API: `StateGraph`, `.compile()`, `.invoke()`,
`.stream()`, `.get_state()`, `.update_state()`, plus `Command` for resume.

Platform is HTTP with SSE streaming, resource-oriented around
`/assistants`, `/threads`, `/threads/{id}/runs`, `/crons`, `/store`, mirrored by
`sdk-py` and `sdk-js`. Standards implemented: none of MCP, A2A, ACP, or OTel in
the runtime.

## 18. Storage

Checkpointer implementations: `InMemorySaver`, SQLite, Postgres — plus a
`shallow.py` variant in the Postgres package. Cache backends: memory, Redis.
Store: in-memory base with optional embedding index.

Authoritative state is the checkpoint row keyed by `(thread_id, checkpoint_ns,
checkpoint_id)`. Serialization is pluggable (`serde/`) with msgpack and
jsonplus, and notably an `encrypted.py` — encryption at the serde layer is a
sensible place for it.

## 19. Deployment architecture

OSS: a library inside your process. Platform: containerized service built by
`langgraph_cli` with Postgres and Redis, self-hosted or managed.

## 20. OSS / license / commercial model

MIT for runtime, checkpointers, SDKs, CLI. Closed: LangSmith server, LangGraph
Platform. No copyleft, no SaaS restriction, no trademark constraint beyond the
LangChain marks.

Verdict: **INTEGRATE**. The checkpointer interface and conformance suite are
safely borrowable patterns. The graph model itself is an opinionated agent
framework we should orchestrate, not absorb.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | undefined | No agent principal exists; the question cannot be posed. |
| S2 Torn side effect | **inferable — verified empirically** | Runs twice. See below. |
| S3 Upgrade mid-flight | **inferable — verified empirically** | No version pinning; renamed node silently drops work. See below. |
| S4 Concurrent memory write | undefined | `BaseStore` has no versioning, CAS, or conflict policy. Last-write-wins by implementation default. |
| S5 Cancellation tree | **inferable — verified empirically** | No cooperative cancellation token in sync path. See below. |
| S6 Silent context loss | undefined | No mechanism detects dropped constraints; summarization is user-implemented. |
| S7 Poison message | undefined | No queue in OSS, so no DLQ. `RetryPolicy` retries then surfaces the error. |
| S8 Tenant leak | undefined | No tenant concept. Store namespaces are convention, not enforcement. |
| S9 Runaway spend | absent | No budget, token ceiling, or cost limit in the runtime. `recursion_limit` bounds super-steps only, not spend. |
| S10 Zombie sandbox | n/a | No sandbox. |

### S2 verified — the side effect runs twice

A node appends to a list, then calls `interrupt()`. After first invoke and
resume:

```text
after first invoke, side_effects = ['EFFECT']
after resume,       side_effects = ['EFFECT', 'EFFECT']
=> at-least-once at NODE granularity
```

Confirms the docstring. Practical consequence: **any side effect placed before
an `interrupt()` in the same node executes twice.** Charge a card, then ask for
approval, and you charge twice. The mitigation is discipline — isolate effects
in their own node after the interrupt — but the runtime neither enforces nor
warns. This is the single most important finding for our design: node-level
resume granularity is too coarse when nodes contain side effects.

### S3 verified — no version pinning, and silent work loss

Two experiments on a suspended thread:

1. **Same topology, changed node body** → resumes and runs the *new* code
   (`['V2:yes']`). No version is recorded on the checkpoint, so an upgrade
   silently applies to in-flight runs.
2. **Node renamed** → `invoke` returns `[]` with **no error**. The pending task
   targeted a node that no longer exists, and the work was silently dropped.

The second is a genuine hazard. An operator renaming a node while approvals are
pending loses that work with no failure signal. Contrast with `AssistantVersion`
at the Platform layer, which versions *config* but not graph topology.

Lesson for us: a checkpoint must record the definition version that produced it,
and resume must fail loudly on incompatibility. This is ADR-0002 and C12
territory and needs an explicit answer.

### S5 verified — cancellation is caller-abandonment

A long-running sync node started, the caller abandoned the invocation, and the
worker thread kept running. Post-abandon state showed `log: []` with
`next: ('child',)` — the task remains pending, which is at least honest. But
there is no cancellation token delivered to a sync node, and no durable
"cancelling" state. The async path can propagate `asyncio.CancelledError`;
the sync path cannot interrupt a running node at all.

## 22. Strongest ideas

1. **The checkpointer conformance suite.** Base vs extended capabilities,
   runtime detection by method override, and spec tests gated on detected
   capabilities. Directly applicable to harness adapters (ADR-0004).
2. **Durability as a caller-selected mode.** `sync | async | exit` names a real
   tradeoff instead of hiding it.
3. **Deterministic task IDs** hashed from checkpoint + namespace + step, with a
   checksum assertion. This is what makes resume correct rather than hopeful.
4. **`MultitaskStrategy`.** Naming the concurrent-run policy
   (`reject | interrupt | rollback | enqueue`) is a small thing that removes a
   whole class of ambiguity.
5. **Interrupts as queryable thread state.** A pending approval is data, not a
   suspended coroutine.
6. **Auth handler specificity fallback.** exact resource+action → resource →
   global is clean and predictable.
7. **Store separated from checkpointer**, with TTL and namespaces — the right
   instinct even though permissions are missing.

## 23. Weakest architectural choices

1. **Node-granularity resume with no side-effect protection.** The S2 double
   execution is a footgun in the default path, and the docs treat it as a note
   rather than a warning.
2. **No definition versioning on checkpoints.** S3's silent work loss on rename
   is unacceptable for long-lived suspended runs.
3. **No agent or principal concept**, so no identity, delegation, or audit.
   Everything security-relevant is deferred to the Platform.
4. **Proprietary telemetry.** No OTel means the best observability is
   commercial-only.
5. **Store namespaces without permissions.** Looks like an isolation boundary,
   is not one — an inviting source of future tenant-leak bugs.
6. **No budget controls.** `recursion_limit` bounds steps, not spend, so S9 has
   no answer.
7. **Thread is not a resource in OSS** — just a string in a config dict — so
   lifecycle operations on it have nowhere to live.

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| Conformance-suite pattern for adapters | REUSE (pattern) | Best available answer to heterogeneous capability negotiation |
| Durability mode vocabulary | ADOPT_AS_STANDARD | `sync`/`async`/`exit` is a good public contract |
| Deterministic task ID scheme | REUSE (pattern) | Prerequisite for correct resume |
| `MultitaskStrategy` vocabulary | ADOPT_AS_STANDARD | Names a real decision |
| Auth specificity fallback | REUSE (pattern) | Predictable policy resolution |
| Checkpointer implementations | INTEGRATE | Use LangGraph when hosting LangGraph agents; not our storage layer |
| Graph runtime | INTEGRATE | One harness among several, per ADR-0004 |
| Telemetry approach | reject | Counter-example for ADR-0010 |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | challenges | No agent identity at all, yet the project is widely successful. Durable *thread* state carried the value; durable *agent* identity was not needed for its use case. Our justification for agent identity must rest on delegation, policy, and audit — not on durability, which threads already deliver. |
| ADR-0002 | confirms | The absence of Task and durable Run is precisely why "retry this intent" has nowhere to live. Strong support for the split. |
| ADR-0003 | confirms | Multi-agent via shared mutable channel state gives no ordering, delivery, or correlation guarantees. Supports durable messages. |
| ADR-0004 | confirms | The conformance-suite pattern is a concrete design for adapter capability negotiation. Adopt base/extended + runtime detection. |
| ADR-0005 | neutral | No capability model; MCP handled outside the runtime. |
| ADR-0006 | neutral | No A2A. |
| ADR-0007 | confirms | Auth principal is `BaseUser` only, so agents cannot hold permissions and S1 is unanswerable. Validates making Principal the root abstraction. |
| ADR-0008 | confirms | Checkpointer/Store separation is real and useful. But no permissions or provenance on the Store, so H4/H5 need another source. |
| ADR-0009 | neutral | No sandbox. |
| ADR-0010 | confirms | Proprietary telemetry locks observability behind a commercial product. Exactly the outcome OTel avoids. |

**New decision needed, not currently covered by any ADR:** checkpoints must
record the agent-definition version that produced them, and resume must fail
loudly on incompatible definition change. S3 shows silent work loss otherwise.
Proposing **ADR-0011 — Checkpoints are version-pinned**.

**Amendment to ADR-0002:** the Run state machine needs an explicit
`CANCELLING` state. S5 shows that without one, cancellation is indistinguishable
from abandonment, and a still-executing worker has no way to learn it should
stop.

## 26. Open questions

- Does LangGraph Platform add definition-version pinning on resume, or does it
  inherit the S3 hazard? Class B — needs docs review. (→ OQ-007)
- What is the actual lease/heartbeat mechanism for Platform workers, and how are
  lost workers detected? Closed source. (→ OQ-008)
- Is there any accepted pattern in the ecosystem for side-effect idempotency
  across the node-level resume boundary, or is discipline the whole answer?
  (→ OQ-009)
