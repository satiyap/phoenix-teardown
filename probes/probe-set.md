# The Probe Set

Fixed, numbered questions asked of **every** project in the same order. Never
renumber: `facts.yaml` and the ADRs cite these ids. To retire a probe, mark it
`DEPRECATED` in place and add a new id.

Consistency is the whole point. Ten products answering the same 60 questions is
a comparative study; ten products answering whatever seemed interesting is ten
blog posts.

## How to answer

Every probe gets one of four verdicts. The distinction between the first three
is the most valuable signal in the entire teardown, so be strict about it.

| Verdict | Meaning |
|---|---|
| `first_class` | The system has an explicit, named concept for this. It appears in the API, schema, or docs as a thing you can point at. |
| `implicit` | The behaviour exists but is emergent or undocumented. You inferred it by reading source. Say which source. |
| `absent` | Read the source and it genuinely does not do this. Not "I didn't find it." |
| `unknown` | Not yet determined, or evidence not accessible. Legitimate — but every `unknown` on a primary project needs a line in `open-questions.md`. |

`absent` and `unknown` are different claims. Conflating them is how a teardown
produces false confidence.

## Evidence requirement

Each answer carries a citation: `path/to/file.py:120 @ a1b2c3d` or
`https://docs.example.com/runtime (read 2025-08-26)`. An answer without a
citation is a guess wearing a verdict's clothing.

---

## A. Core abstraction and object model (A1–A9)

- **A1** What does this system think an agent *is*? State it in one sentence, in their vocabulary.
- **A2** What is the root resource — the thing everything else hangs off?
- **A3** Is `Agent` persistent or ephemeral? Can it exist while not executing?
- **A4** Is `Task` a separate resource from `Run`? If not, which concept is missing and what fills the gap?
- **A5** What is a `Session` attached to: user, agent, task, or execution?
- **A6** Are messages first-class durable resources, or transient function arguments?
- **A7** Are artifacts (files, outputs, deliverables) first-class?
- **A8** Can multiple agents participate in one task? How is that represented?
- **A9** Draw the object model as a tree. Only nodes that exist in their code or API.

## B. Runtime model (B1–B10)

- **B1** Does the platform launch agents, host them, or attach to external ones?
- **B2** Execution substrate: process, container, microVM, serverless, in-process library, remote HTTP?
- **B3** Who owns the event loop — platform or agent?
- **B4** Who decides when an agent wakes?
- **B5** Can an agent run indefinitely? What is the actual ceiling?
- **B6** Are there background or unattended agents?
- **B7** Is execution synchronous or asynchronous from the caller's view?
- **B8** Can in-flight work migrate between workers?
- **B9** Can an agent survive a machine restart? Automatically, or with operator action?
- **B10** Classify: worker/queue, durable actor, attached harness, or in-process library.

## C. Durability and failure semantics (C1–C12)

- **C1** What state is durable, and what is lost on crash?
- **C2** *When* is state persisted — every step, every tool call, on checkpoint, never?
- **C3** Checkpointing or event sourcing? Can state be rebuilt from a log?
- **C4** Retry semantics, and at what granularity: run, step, tool call?
- **C5** At-least-once or exactly-once? What do the docs claim versus what the code does?
- **C6** Is there an idempotency model for tool side effects?
- **C7** Process crash recovery: what resumes, and from where?
- **C8** Node loss: is work re-dispatched, and how is it detected?
- **C9** Context-window overflow: truncation, summarisation, or failure?
- **C10** Timers, scheduled execution, long sleeps — durable across restart?
- **C11** Human-in-the-loop pause and resume: durable, or in-memory only?
- **C12** Can a definition be upgraded while runs are in flight? What happens to them?

## D. Agent identity and lifecycle (D1–D10)

- **D1** Is an agent globally addressable? By what identifier?
- **D2** Does identity survive process restart?
- **D3** Is identity distinct from runtime instance?
- **D4** Are agents versioned? Immutable or mutable definitions?
- **D5** Is there a registry or catalog?
- **D6** Can agents discover each other at runtime?
- **D7** Can agents advertise capabilities? In what format?
- **D8** Is there an owner, team, or tenant on the agent record?
- **D9** Can an agent be suspended, revoked, or deprecated?
- **D10** Is there anything resembling a declarative agent manifest?

## E. Harness and runtime interoperability (E1–E9)

- **E1** What is the minimum interface an agent implementation must satisfy?
- **E2** Transport: stdin/stdout, HTTP, gRPC, WebSocket, in-process, ACP, A2A?
- **E3** Can it host a foreign agent (Claude Code, Codex, OpenHands, LangGraph, ADK)?
- **E4** Is there an event stream out of a running agent? What granularity?
- **E5** Are tool calls externally observable, or internal to the agent?
- **E6** How is context injected at start?
- **E7** Is cancellation supported? Cooperative or forced? Does it propagate to subagents?
- **E8** Can a run be checkpointed and restored by the platform, or only by the agent?
- **E9** Which of these would be hard to adapt, and why?

## F. Agent-to-agent communication (F1–F11)

- **F1** Direct messages between agents?
- **F2** Channels, topics, or pub/sub?
- **F3** Task delegation as a distinct mechanism from messaging?
- **F4** Synchronous RPC between agents?
- **F5** Asynchronous inbox or mailbox?
- **F6** Is delivery durable? Survives restart of sender and receiver?
- **F7** Is message ordering guaranteed? Per what scope?
- **F8** Acknowledgement or delivery receipts?
- **F9** Correlation ids for request/response pairing?
- **F10** Conversation threading?
- **F11** Capability-based routing — address by what an agent *can do* rather than who it is?

## G. Human-agent collaboration (G1–G10)

- **G1** Is a human modelled as a special kind of agent, a distinct principal type, or not modelled?
- **G2** Shared rooms, channels, or workspaces?
- **G3** Task threads humans can read and post into?
- **G4** Mentions or directed addressing?
- **G5** Approval gates. Blocking or advisory? Durable while pending?
- **G6** Mid-run intervention: can a human redirect without restarting?
- **G7** Agent status and presence visible to humans?
- **G8** Notifications or escalation when an agent is blocked?
- **G9** Shared scratchpad or working surface?
- **G10** Can a human see the context an agent is operating on?

## H. Context and memory (H1–H11)

Resist the word "memory." Force each distinct thing into its own row.

- **H1** Which of these exist as *separate* concepts: prompt context, working state, session history, long-term agent memory, shared workspace knowledge, org knowledge, artifacts?
- **H2** Who owns memory: agent, human, workspace, task, or tenant?
- **H3** Can memory be shared between agents? At what granularity?
- **H4** Are there permissions on memory?
- **H5** Is provenance tracked — where a memory came from?
- **H6** Expiry, TTL, or forgetting?
- **H7** Summarisation or compaction. Automatic or explicit?
- **H8** Retrieval mechanism: vector, keyword, structured, agent-driven?
- **H9** Can an agent mutate its own memory mid-run?
- **H10** Conflict resolution on concurrent writes?
- **H11** Is memory in the same store as execution state, or separate?

## I. Tools and capabilities (I1–I10)

- **I1** Are tools bound to agents statically, or resolved dynamically?
- **I2** Is there a capability abstraction distinct from tool implementation?
- **I3** Is there a registry of available tools?
- **I4** Tool scoping — can an agent be restricted to a subset?
- **I5** Are tools versioned?
- **I6** How are credentials supplied to a tool?
- **I7** OAuth or delegated user credentials?
- **I8** Can policy intercept a tool call before execution?
- **I9** Approval gates on specific tools?
- **I10** Do tools execute inside or outside the agent's sandbox?

## J. Security and identity (J1–J10)

- **J1** What identity does an agent authenticate as?
- **J2** Authentication mechanism for agent-to-platform?
- **J3** Authorisation model: RBAC, ABAC, capability tokens, none?
- **J4** Secret storage and injection?
- **J5** Per-agent credentials, or shared platform credentials?
- **J6** Can an agent act as a user? Is that impersonation or delegation?
- **J7** Tenant isolation: logical, or enforced at runtime?
- **J8** Network and filesystem isolation?
- **J9** Is there an audit log? Is it tamper-evident?
- **J10** Where are policy decisions enforced — control plane, runtime, or tool gateway?

## K. Sandbox and isolation (K1–K9)

- **K1** Is there a workspace or sandbox concept? What is its lifecycle?
- **K2** Persistent filesystem across runs?
- **K3** Snapshot and restore?
- **K4** Network egress rules?
- **K5** Container, microVM, or none?
- **K6** Resource quotas: CPU, memory, disk, wall clock?
- **K7** How are secrets injected without landing in the image or logs?
- **K8** Arbitrary code execution? Browser execution?
- **K9** Is the sandbox pluggable, or a fixed implementation?

## L. Orchestration and scheduling (L1–L10)

- **L1** Does it distinguish agent coordination from workflow orchestration?
- **L2** Topology: DAG, cyclic graph, supervisor, planner, event-driven, queue?
- **L3** Cron or scheduled triggers?
- **L4** Dynamic task spawning at runtime?
- **L5** Fan-out / fan-in?
- **L6** Subagents. Are they first-class, or just nested calls?
- **L7** Retry and backoff policy — declarative or hand-rolled?
- **L8** Compensation or rollback on failure?
- **L9** Does cancellation propagate through the whole tree?
- **L10** Could this be replaced by Temporal or Restate, or is orchestration inseparable from the agent model?

## M. Observability (M1–M8)

- **M1** Which of these are modelled as telemetry objects: trace, run, step, LLM call, tool call, message, handoff, task, artifact?
- **M2** Is telemetry keyed to agent, run, model, task, user, or tenant?
- **M3** OpenTelemetry, proprietary, or none?
- **M4** Is there a documented, stable event schema?
- **M5** Cost and token accounting. Per what unit?
- **M6** Latency breakdown by phase?
- **M7** Error taxonomy?
- **M8** Can the event stream reconstruct a run after the fact — replay or audit?

## N. Multi-tenancy and enterprise (N1–N8)

- **N1** Resource hierarchy: org, workspace, project, environment?
- **N2** RBAC model and its granularity?
- **N3** Quotas and cost limits. Enforced or advisory?
- **N4** dev / staging / prod separation?
- **N5** Deployment promotion path?
- **N6** Agent catalog scoped to a tenant?
- **N7** Audit retention controls?
- **N8** Is multi-tenancy in the OSS core, or reserved for a commercial tier?

## O. API and protocol surface (O1–O7)

- **O1** List the actual primary endpoints or SDK entry points. Verbatim.
- **O2** Is the API resource-oriented or RPC-flavoured?
- **O3** Streaming: SSE, WebSocket, long-poll, gRPC stream?
- **O4** Webhooks or outbound callbacks?
- **O5** Which standards are implemented: MCP, A2A, ACP, OTel, OpenAI-compatible?
- **O6** Is the API versioned? Stability commitment?
- **O7** Is there a separate northbound (client) and southbound (runtime) API?

## P. Storage (P1–P6)

- **P1** What datastores are required to run it?
- **P2** What is treated as authoritative, strongly consistent state?
- **P3** What is event-stream or append-only?
- **P4** Where do large artifacts go?
- **P5** Is there a vector store? Required or optional?
- **P6** Is storage pluggable, or hardcoded?

## Q. Licensing and commercial (Q1–Q6)

Answer during Phase 1 recon, before investing reading time.

- **Q1** Exact license, including any per-directory variation.
- **Q2** Are there enterprise-only components missing from the OSS repo?
- **Q3** SaaS or hosted-service restrictions?
- **Q4** Trademark constraints on derived works?
- **Q5** Network copyleft (AGPL, SSPL) implications for a hosted product?
- **Q6** Verdict: `USE` / `INTEGRATE` / `REFERENCE_ONLY` / `AVOID`, with reasoning.

## R. Developer experience (R1–R7)

Timeboxed to 60–90 minutes of genuine hands-on. Log friction as it happens in
`dx-log.md`; do not reconstruct it afterwards from memory.

- **R1** Time from clone to a running agent. Actual elapsed minutes.
- **R2** How many concepts before "hello world"?
- **R3** Is there a local dev loop? Hot reload?
- **R4** How do you debug a stuck run?
- **R5** Can an agent be unit tested? Is there a test harness?
- **R6** Deployment story?
- **R7** CLI ergonomics — try the equivalent of `init`, `agent add`, `run`.

---

## S. Hard scenarios

Prose descriptions of behaviour under stress. These separate systems with a
real design from systems with a demo. Answer each as: **first-class answer** /
**inferable from source** / **undefined**.

- **S1 — Delegated authority.** Agent A delegates task X to Agent B, on behalf of human H. When B calls a tool, whose credentials execute it? A's, B's, H's, the intersection, or an explicit delegation token? What is the audit record?

- **S2 — Torn side effect.** A run dies after a tool call causes an external side effect but before that outcome is persisted. On retry, does the side effect happen twice? Is there any dedupe key?

- **S3 — Upgrade mid-flight.** A run is suspended awaiting human approval. The agent definition is updated. On resume: old version, new version, or hard failure?

- **S4 — Concurrent memory write.** Two agents write the same memory key at the same time. Last-write-wins, versioned, merged, or rejected?

- **S5 — Cancellation tree.** A parent run is cancelled while three subagents are mid-tool-call. Does cancellation reach them? Is the cancellation itself durable if the control plane restarts mid-cancel?

- **S6 — Silent context loss.** An agent's context is compacted, dropping a constraint stated 40 turns ago. Does anything detect that the constraint was lost?

- **S7 — Poison message.** A malformed message crash-loops a consumer. Dead-letter queue, backoff, or infinite loop?

- **S8 — Tenant leak.** Tenant A's agent is passed a resource id belonging to Tenant B. Is that caught at the control plane, the runtime, the tool gateway, or not at all?

- **S9 — Runaway spend.** An agent loops, calling a model 10,000 times. What stops it, and how quickly?

- **S10 — Zombie sandbox.** The control plane loses contact with a running sandbox that keeps executing. How is the orphan detected and reaped? Does its eventual output get accepted?

---

## Anti-goals

Do not spend teardown budget on: number of model providers, prompt syntax,
default planner quality, UI polish, benchmark claims, tool count, multi-agent
demos, GitHub stars.

If a note would not change a design decision, it does not belong in the
teardown.
