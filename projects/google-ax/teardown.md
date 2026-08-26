# Teardown — Google AX (Agent Executor)

| | |
|---|---|
| Repo | https://github.com/google/ax |
| Commit read | `b77731302075b3630b200af5e2cf63ac93b5f315` (2026-08-19) |
| Docs | https://agentexecutor.io |
| License | Apache-2.0 |
| Read on | 2026-08-26 |
| Evidence class | A |
| Depth | deep |
| Runtime class | `durable_actor` (suspendable actors) driven by a single-writer control plane |

**Read against the Phase 2 strawman**, per the falsification design. AX was moved
to the front of Phase 3 because it addresses four of the seven gaps left open by
the anchors: agent versioning, Task/Run separation, side-effect idempotency, and
remote adapter transport.

Build and tests verified locally (`go build ./...`, `go test ./internal/controller/...`).
The repo warns of active development and breaking changes; every claim is pinned
to the commit above.

---

## 1. What problem it solves

Running agent harnesses reliably in a distributed setting. AX is "a distributed
harness runtime" that "dynamically provisions isolated environments from
suspendable/resumable images to execute harnesses and agents" (`README.md @ b777313`).
The problem it targets is not authoring agents but *executing someone else's
agent* durably, with recovery and resumption across machines.

## 2. Core architectural thesis

**Separate the single-writer orchestrator from disposable, suspendable actors, and
make the event log the only source of truth.**

`internal/controller/controller.go:15` states it directly: "Package controller
implements the single-writer orchestrator that coordinates... It acts as a
single-writer system for managing agentic loops."

The bet has three parts:
1. One writer per conversation, so ordering is never ambiguous.
2. An append-only event log from which state is *derived*, never stored separately.
3. Actors keyed by conversation, suspended between turns and resumed onto any
   worker.

This is the closest architecture in the study to what ADR-0001 and ADR-0004
propose together, and it is the first project to combine durable identity with
adapter-based execution.

## 3. Resource / object model

Strikingly small — the whole contract is 235 lines of proto.

```text
Conversation                  (conversation_id; the durable unit)
 └── Interaction              (interaction_id; one execution)
      └── Step                (the atomic unit; typed)
           ├── ContentStep         (text, image, audio, document, video,
           │                        ConfirmationContent)
           ├── ThoughtStep
           ├── ToolCallStep / ToolResultStep
           └── FunctionCallStep / FunctionResultStep

StepEvent                     (log entry: conversation_id, interaction_id,
                               agent_id, agent_config, steps[], state)

Harness                       (registered by id; one may be default)
 └── Execution                (Run, Queue, ID, Close)

Actor                         (substrate; keyed by conversation_id, suspendable)
Skill                         (from registry or local dir; harness-agnostic)
```

A comment in the proto states the concurrency rule plainly: "A conversation cannot
be continued before the last execution is completed or failed"
(`proto/ax.proto:27-29`).

**On `A4` (Task vs Run):** AX has `Conversation → Interaction`, which is the
closest thing yet to the split — Interaction is genuinely a distinct resource with
its own id and terminal state. But Interaction is an *execution*, not an intent
that survives failed attempts, and there is a `TODO` acknowledging the API is
incomplete: "CreateInteraction should return an Interaction message and the
outputs should be polled from the Interaction" (`proto/ax.proto:130-131`). So the
gap narrows but does not close.

## 4. Runtime model

AX launches and resumes actors. The substrate harness
(`internal/harness/substrate/substrate.go:86-133`) does:

```text
CreateActor(conversationID)      idempotent; AlreadyExists is expected
     ↓
ResumeActor(conversationID)      schedules onto a worker, returns routable IP
     ↓
dial workerIP:port
     ↓
waitForHealthy()                 gRPC health protocol, with timeout
     ↓
HarnessService.Connect stream
```

The actor is **suspended between turns** and resumed on demand. Identity is the
conversation; the compute is disposable and may land on any worker. That is
precisely the "durable logical actor, disposable execution" model ADR-0001
describes, and it is the first implementation of it in the study.

Health checking is pragmatic in a way worth noting: a harness that is reachable
but does not implement the health service is "treated as ready," while
`Unavailable` and `NOT_SERVING` are retried (`substrate.go:135-138`). Optional
capability, degraded gracefully — but see §13 for the ADR-0012 tension.

## 5. Execution lifecycle

The state enum is deliberately tiny (`proto/ax.proto:94-101`):

```text
STATE_UNSPECIFIED → STATE_PENDING → STATE_COMPLETED
                                  ↘ STATE_FAILED
                                  ↘ STATE_CANCELED
```

No `WAITING_FOR_HUMAN`, no `STUCK`. Approvals are handled as *content* rather than
as a state (see §9), which is a genuinely different design choice.

**Cancellation carries a reason** (`proto/ax.proto:103-109`), which no anchor had:

```text
CANCEL_REASON_USER_REQUESTED | CANCEL_REASON_TIMEOUT | CANCEL_REASON_INTERNAL_ERROR
```

The harness protocol is a bidirectional stream with a precisely specified shape
(`proto/ax.proto:85-91`): the client sends `HarnessStart` and *may* send one
`HarnessCancel` mid-stream; the server streams zero or more `HarnessOutputs`
frames "terminated by exactly one `HarnessResponse{end}`." Specifying the
terminator count in the service comment is the kind of precision that makes an
adapter implementable without guesswork.

## 6. Durability model

The best-specified durability model in the study, and the simplest.

`internal/controller/eventlog/eventlog.go:28-30`: "EventLog is the persistent,
append-only record of all actions taken in an exec. Every entry is an atomic step:
**replaying the log in order brings the executor back to a consistent state from
which execution can resume.**"

The interface is three methods: `Append`, `Events`, `Close`. That is all.

**State is derived, never stored.** `ResumptionState`
(`internal/controller/controller.go:224-241`) folds the event log to recover both
the current state and the harness id. There is no state column to drift out of
sync with the log — a class of bug simply eliminated.

**Single-writer is enforced by the database**
(`internal/controller/eventlog/sql.go:38-66`):

```sql
CREATE TABLE conversation_log (
  conversation_id TEXT NOT NULL,
  step INTEGER NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (conversation_id, step)
)
```

The step number is computed as `MAX(step)+1` *inside the same transaction* as the
insert. Two concurrent appends collide on the primary key and one rolls back.
Ordering cannot be corrupted, and the guarantee needs no distributed lock.

Backends: SQLite and Postgres, behind an `EventLogBuilder`.

## 7. Agent identity and lifecycle

Identity is the **conversation**, not the agent. `agent_id` on a `StepEvent`
identifies which *harness* served it, and the registry is keyed by harness id
(`internal/controller/registry.go`).

Registration is immutable in one direction — `RegisterHarness` refuses to
overwrite ("harness %q already registered") — but the registry is **in-memory
only**, populated from YAML at startup (`internal/config/config.go:97-102`). No
persistence, no discovery, and critically **no versioning**: `D4` and `D9` remain
absent, now four for four.

There is a candid `TODO` acknowledging the model is unsettled: "We need to
consolidate agents and harness registration. Adding harness registration support
temporarily" (`controller.go:74-76`). AX conflates agent and harness today and
knows it.

## 8. Multi-agent communication

Absent. No agent-to-agent messaging, no mailbox, no channels, no delegation
primitive. The F-section is now **absent in four of four** projects.

AX is a single-conversation executor. Sub-agents are not modelled at all — a
notable omission given all three anchors had them.

## 9. Human interaction model

A genuinely different design, and the most interesting finding for our HITL model.

Approvals are **wire-protocol content**, not an execution state
(`proto/content.proto:28-47`):

```protobuf
message ConfirmationContent {
  string id = 3;
  string question = 4;
  oneof decision {
    ApprovalDecision approval = 5;   // bool approved
    DeclineDecision decline = 6;     // bool declined
  }
}
```

The question and its answer are the *same object*, carrying a stable `id`, and it
flows through the event log like any other content. Consequences:

- A pending approval is durable automatically, because the log is durable. No
  separate approval store (contrast Letta's JSON file, OpenHands' thread state).
- The full approval history is replayable — who was asked what, and what was
  decided, in order.
- No `WAITING_FOR_HUMAN` state is needed; the conversation is `PENDING` and the
  last step is an unanswered `ConfirmationContent`.

This is cleaner than all three anchors. It also means approval is a *content
type* the harness must understand, which pushes semantics into the adapter
contract.

Nothing else, though: no channels, no presence, no notification, no multi-party
collaboration. `G2`–`G4`, `G7`, `G8` are absent.

## 10. Context and memory

Effectively absent. No memory subsystem, no long-term store, no compaction.
Context is whatever the harness maintains internally plus `agent_config` passed
per execution.

**Skills** are the only knowledge mechanism (`internal/skills/`, `config.go:119-133`):
either sourced from the Gemini Enterprise Skill Registry and materialised into a
directory, or read from local dirs containing `<skill-id>/SKILL.md`. Explicitly
"harness-agnostic," feeding "a harness system-instruction pointer."

Third project to choose **git-or-filesystem-backed skills** over a memory store
(with Letta and OpenHands). That convergence is now strong enough to act on.

## 11. Tools and capabilities

Tools appear only as *step types* — `ToolCallStep`, `ToolResultStep`,
`FunctionCallStep`, `FunctionResultStep`. Tool execution is entirely the harness's
business; AX observes it in the log but does not mediate it.

No capability abstraction, no tool registry, no policy interception. `I8` absent —
AX has no policy layer at all.

## 12. Security and IAM

**The weakest area, and a real finding.** The gRPC server installs only logging
interceptors (`internal/server/server.go:82-83`):

```go
grpc.ChainUnaryInterceptor(LoggingInterceptor),
grpc.ChainStreamInterceptor(StreamLoggingInterceptor),
```

There is no authentication interceptor, no authorization, no TLS configuration in
the server path, and no tenancy anywhere. A distributed agent runtime that
provisions sandboxes and executes arbitrary harnesses exposes `InteractionsService`
and `HarnessService` unauthenticated.

For an early-stage project this is a "not yet" rather than a design position, but
it is worth recording plainly: **the most architecturally sophisticated durability
model in the study sits behind no access control at all.** `J1`–`J7`, `J9`, `J10`
are absent.

**S1 remains unanswerable**, and here there is not even an agent principal to
reason about.

## 13. Sandboxing

Sandboxing is delegated to **SubstrATE**, an external actor system
(`github.com/agent-substrate/substrate`), accessed through `internal/ate/client.go`.
AX does not implement isolation; it orchestrates actors that provide it. The
`ActorTemplate` is user-supplied for custom harnesses, so the container image is
the user's concern (`config.go:95-97`).

This is exactly ADR-0009's position — a provider interface rather than an
implementation — arrived at independently.

**ADR-0012 tension.** AX has no capability declaration. Optional behaviour is
handled by treating absence as acceptable: a harness without a health service is
"treated as ready." That is the *opposite* of Letta's fail-closed rule, and it is
defensible only because the fallback is benign. Compare the four projects:

| Project | Optional capability handling |
|---|---|
| LangGraph | Declared enum + override detection + conformance tests |
| OpenHands | `NotImplementedError`, no query, silent no-op on local |
| Letta | Real probe, `backend \| null` + reason, **fails closed** |
| **AX** | No declaration; **absence treated as OK** (fail-open) |

Two fail-open, two fail-closed. The split correlates with what is at stake:
Letta's optional capability guards *memory isolation*, AX's guards *readiness*.
That suggests ADR-0012 needs to distinguish safety-relevant capabilities (must
fail closed) from liveness-relevant ones (may fail open) rather than issuing one
blanket rule.

## 14. Orchestration

Minimal by design. One conversation, one in-flight execution, enforced by the
"cannot be continued before the last execution is completed or failed" rule.

No DAG, no graph, no fan-out, no subagents, no scheduling, no cron. AX is an
executor, not an orchestrator — which is consistent with its name and with
ADR-0014's separation of concerns.

## 15. Observability

**The first project in the study with genuine OpenTelemetry**, breaking a 3-for-3
streak of proprietary or absent telemetry.

`internal/telemetry/telemetry.go` imports `go.opentelemetry.io/otel`, the OTLP
gRPC trace exporter, propagation, and the trace SDK. Spans instrument both the
event log (`eventlog/sql.go:105-108`, tracer `eventlog.sql`) and each harness
adapter (`substrate.go:195`, `antigravity.go:163`). OTLP is enabled in the sample
config (`ax.yaml`).

Direct affirmative evidence for ADR-0010: a Google-authored distributed agent
runtime treats OTel as the default rather than an integration.

The event log doubles as an audit and replay substrate, satisfying `M8` by
construction.

## 16. Multi-tenancy

Absent entirely. No organization, project, tenant, or quota. Five for five on
`J7` and `N3`.

## 17. Protocols and APIs

Two gRPC services, and the northbound/southbound split is explicit — the cleanest
example of ADR-0004's two-API shape in the study:

**Northbound** — `InteractionsService.CreateInteraction(CreateInteractionEvent)
returns (stream CreateInteractionResponse)`. Resumption is implicit: "If the
conversation_id already exists, it will be resumed" (`proto/ax.proto:126-127`).

**Southbound** — `HarnessService.Connect(stream HarnessRequest) returns (stream
HarnessResponse)`. This is the adapter contract, and it answers OQ-012: a remote
harness speaks gRPC, so **adapter and agent need not be co-located**. Contrast
OpenHands' ACP-over-stdio, which forces co-location.

`agent_config` is deliberately `bytes` — "opaque JSON... interpreted by the
harness implementation" (`harness.go:43-46`). The control plane refuses to
understand adapter configuration, which keeps the boundary clean.

No MCP, no A2A, no ACP.

## 18. Storage

One table. `conversation_log (conversation_id, step, payload)` with a composite
primary key, in SQLite or Postgres. Payload is `protojson`-encoded `StepEvent`.

Authoritative state is the log; everything else is derived. Nothing else is
persisted — no registry, no config, no memory.

## 19. Deployment architecture

Single Go binary (`cmd/ax`) with `serve` and a CLI mode. Kubernetes manifests
(`manifests/ax-deployment.yaml`, `ax-postgres.yaml`, `install-ax.sh`), `ko` for
image builds, and a Python sidecar (`internal/pythonsidecar/`) for Python
harnesses. Config is a single YAML file.

## 20. OSS / license / commercial model

Apache-2.0, no enterprise-only components in the tree. Depends on SubstrATE
(separately licensed) for actor hosting, and optionally on Gemini Enterprise for
the skill registry and Vertex for the Antigravity Interactions harness.

Verdict: **REFERENCE_ONLY**. Apache-2.0 permits embedding, but it is Go, pre-1.0
with declared breaking changes, external PRs are paused, and the sandbox depends on
an external actor system. The *design* is the most valuable thing here.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | undefined | No agent principal, no auth at all. Cannot be posed. |
| S2 Torn side effect | **inferable** | Best structural answer so far: every step is an atomic log append, and `CreateActor` is explicitly idempotent. But no idempotency key on *tool* side effects — `C6` still absent. |
| S3 Upgrade mid-flight | **first_class_answer** | **Verified:** resuming with a different harness is rejected — "resumption not allowed: harness ID changed from harness-a to harness-b". First project to fail loudly. Pins harness *identity*, not *version*. |
| S4 Concurrent memory write | n/a | No memory store. |
| S5 Cancellation tree | **inferable** | `HarnessCancel` mid-stream with a typed `CancelReason`. No tree to propagate through (no subagents). |
| S6 Silent context loss | undefined | No compaction in AX; harness-internal. |
| S7 Poison message | undefined | No queue, no DLQ. A failing execution reaches `STATE_FAILED`. |
| S8 Tenant leak | undefined | No tenancy. |
| S9 Runaway spend | undefined | No budget, quota or cost accounting. Six for six unanswered. |
| S10 Zombie sandbox | **inferable** | `waitForHealthy` with timeout detects an unready actor, and actors are suspended between turns so an orphan is bounded. No explicit reaping, and no fencing of a late-returning actor's output. |

## 22. Strongest ideas

1. **State derived by folding the event log, never stored separately.**
   `ResumptionState` recomputes state and harness id from the log, eliminating
   drift between log and state table as a class of bug.
2. **Single-writer enforced by a composite primary key**, with the step number
   computed inside the insert transaction. Ordering safety without a lock.
3. **A three-method durability interface** (`Append`, `Events`, `Close`). The
   smallest durable-execution contract in the study, and sufficient.
4. **Approvals as wire-protocol content** with a stable `id` and a `oneof
   decision`. Question and answer are one durable object; no separate approval
   store, and full replayability.
5. **Refusing to resume across a harness change**, verified by test. The only
   project that fails loudly where ADR-0011 says it must.
6. **Cancellation with a typed reason** (`USER_REQUESTED | TIMEOUT | INTERNAL_ERROR`).
7. **A precisely specified stream contract** — "zero or more outputs frames
   terminated by exactly one end" — stated in the service comment.
8. **`agent_config` as opaque bytes.** The control plane deliberately refuses to
   parse adapter config, keeping the boundary honest.
9. **Explicit northbound/southbound API separation** in one 235-line proto.
10. **gRPC as the adapter transport**, so remote harnesses work without
    co-location.
11. **Idempotent actor creation**, with the reasoning stated in a comment.
12. **OpenTelemetry by default**, instrumenting both storage and adapters.
13. **Harness-agnostic skills** from a registry or local dirs.

## 23. Weakest architectural choices

1. **No authentication or authorization whatsoever.** Logging-only interceptors on
   a service that provisions sandboxes and runs arbitrary harnesses.
2. **In-memory harness registry with no versioning or persistence.** Restart loses
   registrations; YAML is the only source.
3. **Agent and harness are conflated**, acknowledged by `TODO`.
4. **No multi-agent anything** — no subagents, no delegation, no messaging.
5. **No memory or context management.** Entirely the harness's problem.
6. **No policy layer**, so no interception, approval gating by rule, or audit
   beyond the raw log.
7. **Fail-open on capability absence** (health service). Benign here, but the
   opposite of Letta's rule, with no framework distinguishing the two cases.
8. **Interaction is not yet a resource** — acknowledged by `TODO`, so the
   Task/Run gap remains open.
9. **Pre-1.0 with paused external PRs**, so the design is a moving target.

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| Derive state by folding the event log | REUSE (pattern) | Eliminates log/state drift entirely |
| Composite PK + in-transaction step number | REUSE (pattern) | Single-writer without distributed locking |
| Three-method event log interface | ADOPT_AS_STANDARD | Minimal sufficient durability contract |
| Approvals as durable protocol content | ADOPT_AS_STANDARD | Better than all three anchors |
| Refuse resume on definition change | ADOPT_AS_STANDARD | ADR-0011, verified working |
| Typed `CancelReason` | ADOPT_AS_STANDARD | Cancellation should carry why |
| Precisely specified stream terminator | REUSE (pattern) | Makes adapters implementable |
| Opaque `agent_config` bytes | ADOPT_AS_STANDARD | Keeps control-plane/adapter boundary clean |
| gRPC southbound harness contract | REUSE (pattern) | Enables remote adapters; answers OQ-012 |
| Idempotent actor create/resume | REUSE (pattern) | Correct restart semantics |
| OTel setup | REUSE | Direct precedent for ADR-0010 |
| No-auth server design | reject | Must not ship without authN |
| In-memory registry | reject | Registry must be durable and versioned |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | **confirms** | First implementation of the exact model: actors keyed by conversation, suspended between turns, resumed onto any worker, with the control plane as single writer. Identity is durable, compute is disposable. Note the divergence though: AX's durable identity is the **conversation**, not the agent — reinforcing Letta's lesson that agent identity earns its place through delegation and policy, neither of which AX has. |
| ADR-0002 | **amends** | `Conversation → Interaction` is the closest thing to the split yet, and Interaction has its own id and terminal state. But a `TODO` admits it is not yet a first-class resource. Adopt the shape; note that even a Google team found this hard to get right. |
| ADR-0003 | confirms | No agent-to-agent messaging. **Four for four absent.** The case for building it now rests entirely on our own requirements. |
| ADR-0004 | **confirms strongly** | The cleanest adapter contract in the study: `Start → Execution{Run, Queue, ID, Close}`, four methods, with durability held by the *controller* rather than the adapter. My strawman `AgentRuntime` had seven methods including `checkpoint`/`restore`; AX shows those belong in the control plane, not the adapter interface. Simplify accordingly. |
| ADR-0005 | neutral | No MCP; tools are opaque step types the harness owns. |
| ADR-0006 | **amends** | gRPC bidirectional streaming as the southbound contract answers OQ-012: remote adapters do not need co-location. This is a better model than ACP-over-stdio for our A2A adapter, and suggests our southbound API should be gRPC-shaped with ACP as one adapter *behind* it. |
| ADR-0007 | confirms (negatively) | No principals at all, and consequently no auth, no audit, no delegation. Demonstrates what is lost without the abstraction. |
| ADR-0008 | confirms | No memory subsystem; skills are filesystem/registry-backed and harness-agnostic. **Third project to choose filesystem-or-git skills over a memory store.** Strong convergence for the Knowledge node. |
| ADR-0009 | **confirms strongly** | AX delegates isolation entirely to SubstrATE and lets users supply their own `ActorTemplate`. A provider interface, not an implementation — independently arrived at. |
| ADR-0010 | **confirms strongly** | First project in the study with real OTel: OTLP exporter, propagation, spans on both storage and adapters. Breaks the 3-for-3 gap and shows the standard is viable for agent runtimes. |
| ADR-0011 | **confirms strongly** | Only project that fails loudly on definition change, verified by test: "harness ID changed from harness-a to harness-b". Refines the ADR: AX pins harness *identity* but not *version*, so it catches substitution but not upgrade. Our pin must cover both. |
| ADR-0012 | **amends** | AX has no capability declaration and treats absence as acceptable (a harness lacking the health service is "treated as ready"). That is fail-open, opposite Letta's fail-closed rule. The correlation is instructive: Letta's optional capability guards memory isolation, AX's guards readiness. **The ADR needs to distinguish safety-relevant capabilities (fail closed) from liveness-relevant ones (may fail open).** |
| ADR-0013 | neutral | No policy engine, so nothing to trace. |

**Amendment to ADR-0004, worth acting on immediately.** The strawman adapter
interface in the original plan had `start / send / events / cancel / checkpoint /
restore / terminate`. AX's is four methods, and durability lives in the
controller's event log rather than in the adapter. Since ADR-0012 establishes
that not every harness *can* checkpoint, putting checkpoint/restore in the
adapter interface guarantees a lowest-common-denominator problem. Moving
durability to the control plane, with the adapter merely streaming steps, avoids
it. **Proposing the adapter interface be narrowed to roughly
`Start → {Run, Queue, Cancel, Close}` with the control plane owning the log.**

## 26. Open questions

- Does AX intend Interaction to become a pollable resource (per its `TODO`), and
  would that make it a Task or still a Run? (→ OQ-017)
- Is the absence of authN a "not yet" or a deliberate deployment assumption (mesh
  or sidecar auth)? Nothing in the repo says. (→ OQ-018)
- How does SubstrATE handle actor eviction under memory pressure, and does a
  suspended actor expire? Affects whether suspend/resume is a durability
  mechanism or only a cost optimisation. (→ OQ-019)
