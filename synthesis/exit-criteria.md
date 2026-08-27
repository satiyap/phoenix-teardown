# Exit Criteria

The teardown is complete only when every question below has a written answer
that cites evidence. `tools/check_exit_criteria.py` parses this file: it counts
a question answered when the `Answer` line is non-empty and does not contain
`TODO`.

Rule: if several of these still say "we'll figure it out later," the teardown
has not gone deep enough. That is the whole reason this file exists.

Answer format — replace the `TODO` and keep the `Answer:` prefix:

```
### Q1. What exactly is an Agent?
Answer: TODO
Evidence: ADR-0001; projects/letta, projects/cloudflare-agents
```

---

## Agent model

### Q1. What exactly is an Agent?
Answer: An Agent is an immutable identity plus a mutable, versioned definition, and it exists so that delegation, policy and audit have something to attach to — not because durability requires it. Concretely three records, following AG2: **Passport** (immutable; changing any field means unregister + re-register and yields a new id), **Definition** (the versioned, content-digested artefact — instructions, tools, capabilities, declared as a manifest), and **Runtime** (cache-only connection state, explicitly not authoritative). Two projects deliver durable execution with no agent identity at all, which is why the rationale is rebased on authority rather than persistence.
Evidence: ADR-0001 (5 confirms, 2 amends, 2 challenges); `ag2/network/identity.py:1-21` (Passport/Resume/AgentRuntime); `aws-agentcore` workload identity; `omnigent` Agent.version; `google-ax` (durable execution, no agent identity)

### Q2. Is an Agent persistent?
Answer: Yes — the identity is, and the compute is not. The addressable identity exists whether or not anything is running, and execution capacity is disposable. Cloudflare is the cleanest proof: the agent *is* a named Durable Object whose storage and sockets survive eviction, and platform naming is the registry, so no separate agent registry is needed. Google AX makes the same split with the conversation as the durable unit and actors suspended between turns.
Evidence: ADR-0001; `cloudflare-agents` (`ctx.id.name` authoritative, hibernation); `google-ax/internal/harness/substrate/substrate.go:86-110`; `letta` (kernel-enforced per-agent memory isolation)

### Q3. What is a Run?
Answer: A Run is one attempt to execute an intent, with a lifecycle richer than success/failure. From HumanLayer's nine-state machine plus MAF: `DRAFT → QUEUED → RUNNING → {SUCCEEDED, FAILED, EXPIRED}`, plus `WAITING_INPUT` (blocked on a human, indexed so it is queryable), `CANCELLING → CANCELLED` (cancellation takes time; a state machine that pretends otherwise lies during the gap), `STUCK`/`INDETERMINATE` (from ADR-0014: an effect dispatched but unconfirmed), `INCOMPATIBLE` (pin mismatch on resume), and `DISCARDED`. A Run also carries the pin (ADR-0011) and may carry a logical rewind marker (ADK).
Evidence: ADR-0002; `humanlayer/hld/store/store.go:274-284` (draft/waiting_input/interrupting/interrupted/discarded); `microsoft-agent-framework` (IDLE_WITH_PENDING_REQUESTS); `google-agent-platform/events/_rewind_events.py`; ADR-0014

### Q4. What is a Task, and how does it differ from a Run?
Answer: A Task is the durable *intent* and survives failed attempts; a Run is one *attempt* at it. Omnigent is the only real precedent and it is two tables: `scheduled_tasks` (prompt, rrule, timezone, lifecycle state, per-firing budget) and `scheduled_task_runs` (status, scheduled_at/fired_at/finished_at, error, and a bounded queryable `error_code` explicitly "for future retry logic"). The `error_code` is the field my strawman Run was missing — a retry policy needs a classification it can branch on, not a stack trace. Caveat: Omnigent applies the split only to scheduled work, so it proves the shape is implementable without proving it should be universal.
Evidence: ADR-0002; `omnigent/db/db_models.py:1434,1546,1573-1575`; `google-ax` (Conversation → Interaction, with a TODO admitting Interaction is not yet a resource)

### Q5. What is a Session, and what is it attached to?
Answer: A Session is the durable conversational container that a Run executes within, attached to a `(tenant, principal)` scope rather than to an agent — so the same session can survive an agent-version change and can be driven from several surfaces. Omnigent and ADK both key it `(app/workspace, user, session)` in the composite primary key. Deleted from the model as separate resources during Phase 2: `Step` (a log entry, not a resource) and a distinct `Conversation` type (Session is sufficient).
Evidence: ADR-0002; `synthesis/domain-model.md`; `google-agent-platform/sessions/schemas/v0.py:146-161`; `omnigent/db/db_models.py:777`

## Runtime

### Q6. Who starts the agent?
Answer: The control plane starts it, always — never the caller directly and never the adapter itself. This is the single-writer position: one component owns the decision to run, so ordering and idempotency have one place to live. Google AX states it outright ("single-writer orchestrator... for managing agentic loops") and enforces it in the database rather than with a lock.
Evidence: ADR-0004; `google-ax/internal/controller/controller.go:15,33`; `google-ax/internal/controller/eventlog/sql.go:38-66` (MAX(step)+1 inside the insert transaction)

### Q7. Where does it run?
Answer: Inside a sandbox supplied by a pluggable provider, and the sandbox covers **three boundaries**, each best answered by a different project: (1) **process/filesystem** — ADK's seven executors (container, GKE, Vertex, Agent Engine, model-native, and a deliberately-named `unsafe_local`) and Omnigent's bwrap/seatbelt plus ten cloud backends; (2) **egress** — Pydantic AI's SSRF guard, which blocks private ranges, CGNAT, Teredo-obfuscated forms and an enumerated cloud-credential list *even when the local-development escape hatch is open*; (3) **storage** — Cloudflare's argument that if the LLM can write SQL, a policy enforced in the same database is a convention rather than a control. A sandbox that isolates the process but lets a tool read IMDS has isolated nothing that matters.
Evidence: ADR-0009 (2 amends); `google-agent-platform/code_executors/`; `pydantic-ai/_ssrf.py:98-120`; `cloudflare-agents/design/rfc-sub-agents.md`; `omnigent/sandbox/`

### Q8. How does it recover from failure?
Answer: By replaying a durable log to derive state, never by reading a separate state table. Google AX is the model: the append-only event log is the only source of truth and `ResumptionState` folds it to recover both the current state and the adapter identity, which eliminates log/state divergence as a class of bug. Recovery of *interrupted* work is Cloudflare's: detect hung work by an `execution_started_at` cutoff, find orphans by outer-joining the ledger against live run rows, and back off exponentially when a recovery scan makes no forward progress so a poison hook cannot wake the system forever.
Evidence: ADR-0004; `google-ax/internal/controller/eventlog/eventlog.go:28-30`, `controller.go:224-241`; `cloudflare-agents/packages/agents/src/index.ts:6500-6600`

### Q9. How does it wake?
Answer: On an event — an inbound request, a message, a timer, or a scheduled trigger — with the platform owning exactly one scheduler per agent so a wakeup cannot double-fire. Cloudflare gets this free (the Durable Object owns its own alarm); Omnigent's in-process RRULE scheduler is the counter-example, correct on one instance and double-firing across replicas, which is why a scheduled Run needs a durable claim (`UPDATE ... WHERE status='scheduled'` on rowcount, or `SELECT ... FOR UPDATE SKIP LOCKED`).
Evidence: ADR-0002; `cloudflare-agents` (alarm-owned scheduling); `omnigent/server/scheduled/scheduler.py:1-24` (in-process, no cross-replica claim); OQ-023

### Q10. How is it cancelled, and does cancellation propagate?
Answer: Cancellation is a *request* with a typed reason, distinct from the *fact* of having cancelled, and it passes through a transitional state. Three findings compose: AX types the reason (`USER_REQUESTED | TIMEOUT | INTERNAL_ERROR`); AG2 separates `EV_TASK_CANCEL_REQUEST` (a peer asks, and "the owner is free to... ignore the request entirely") from `EV_TASK_CANCELLED` (the owner did it) — the only correct model when the canceller does not own the work; HumanLayer supplies the transitional state, `interrupting` ("shutting down") before `interrupted` ("can be resumed"). Propagation to children is ours to build: no project propagates cancellation down a delegation tree, and Pydantic AI shows why a same-process token must be *refused* at a durability boundary rather than silently dropped.
Evidence: ADR-0002; `google-ax/proto/ax.proto:103-109`; `ag2/network/envelope.py:81-91`; `humanlayer/hld/store/store.go:282-283`; `pydantic-ai/durable_exec/_runtime_toolsets.py:38-49`

## Communication

### Q11. How do agents communicate?
Answer: Through durable, addressed envelopes on an append-only per-channel log — and AG2 is the design to follow, because it is the only implementation in thirteen projects and it is richer than my strawman. The envelope carries `channel_id, sender_id, audience, event_type, event_data, envelope_id, task_id, causation_id, trace_id, priority, depth, idempotency_key, created_at, ttl_seconds`. Four fields I had not thought of: `causation_id` (threads replies *and* doubles as the dedupe key), `depth` (hop count the hub increments and policy caps), `ttl_seconds`, and `priority`. Two rules: the authority stamps identity and increments depth — never the sender — and **the log records every accepted envelope in full regardless of who was notified**, because audit scope must exceed delivery scope. MAF offers a cheaper alternative worth noting: if all interaction happens inside an orchestration you already checkpoint, message durability comes free — at the cost of agents that cannot talk outside a graph.
Evidence: ADR-0003 (10 confirms, 2 amends); `ag2/network/envelope.py:5-11,94-131`; `microsoft-agent-framework/_workflows/_checkpoint.py:54`; verified: 39 AG2 tests pass

### Q12. How do agents discover each other?
Answer: By querying a registry that publishes both *claimed* and *observed* capability. AG2's `peers(action="find")` returns claimed capabilities alongside a hub-computed `observed_success_rate` and cost, as "a structured list the LLM can rank" — and observation *expands* the index, so an agent appears under a capability it never claimed if it is seen doing it. One gap to fix: `ObservedStat` is a lifetime counter with no decay and its `p50_latency_ms` is really the last sample, so routing on reputation needs a window or reservoir we would have to add.
Evidence: ADR-0012; `ag2/network/client/tools/peers.py:5-13,29-40`; `ag2/network/hub/core.py:1337-1352`; OQ-026

### Q13. How does one agent delegate to another?
Answer: By an explicit delegation that carries bounded authority and a bounded hop count. Authority comes from AgentCore: a workload identity that obtains a token as itself, for a federated JWT, or for a named user, with `ON_BEHALF_OF_TOKEN_EXCHANGE` as a *named* flow rather than a flag on login. Bounding comes from AG2: `depth` is incremented by the hub on the reply path and capped by `Rule.limits.delegation_depth`, so runaway delegation is stopped by the platform rather than by prompt discipline. Letta adds the scoping lesson — delegation there is restricted to `{self, parent}` and memory access is gated fail-closed on agent id.
Evidence: ADR-0007 (7 confirms, 4 challenges); `aws-agentcore/services/identity.py:140-155`; `aws-agentcore/identity/auth.py:30`; `ag2/network/envelope.py:108-110`; `letta` H4

## Context

### Q14. Who owns memory?
Answer: Nobody owns "memory" because memory is not one thing. Three separate subsystems, settled by strong convergence: **Knowledge** — filesystem/git-backed skills and documents, chosen by seven of thirteen projects and by every project that had a choice; **Recall** — a semantic memory *service* scoped to `(tenant, principal)` whose entries carry an author and an *event* timestamp (ADK) and whose *kind* is declared (`SEMANTIC | SUMMARIZATION | USER_PREFERENCE | CUSTOM`, AgentCore); **State** — four scopes distinguished by key prefix, `app:` / `user:` / session / `temp:`, where `temp:` is never persisted and is filtered out by every backend independently. Scope and kind are orthogonal dimensions and both are needed.
Evidence: ADR-0008 (10 confirms); `google-agent-platform/memory/base_memory_service.py:43-140`, `sessions/state.py:64-66`, `memory/memory_entry.py:26-45`; `aws-agentcore/memory/constants.py:13-35,76-78`

### Q15. Who owns conversation state?
Answer: The Session owns conversation state, and it is the *run-scoped* tier of the four state scopes — schema-validated against a declared type, unlike the open prefixed namespaces. ADK is the only project with typed session state (`StateSchemaError` on an undeclared or mistyped key) and the boundary it draws is right: the closed contract is the part *this* run owns, the open namespaces are shared.
Evidence: ADR-0008; `google-agent-platform/sessions/state.py:24-46,64-66`

### Q16. How is context shared between principals?
Answer: Through explicitly scoped shared state, with the sharing boundary in the key rather than in convention — and mutations recorded durably. AG2 makes channel context changes `EV_CONTEXT_SET` envelopes in the same WAL as messages, so shared-state changes and messages are one ordered mechanism rather than two racing ones. ADK's prefixes decide *who* can see a value; AgentCore's namespaces add hierarchy within that.
Evidence: ADR-0008; `ag2/network/envelope.py:71-76`; `google-agent-platform/sessions/state.py:64-66`; `aws-agentcore/memory/client.py:131-134`

## Humans

### Q17. How does a human intervene in a running agent?
Answer: Through a durable `Approval` resource that names its approver — and, before that, by not needing to. Agent Control's `steer` reframes the question: a policy that can return machine-readable remediation ("Request 2FA code from user, verify it, then retry with `verified_2fa=True`") resolves most violations without interrupting a human, so **approval is the escalation when steering is impossible, not the default response to a violation**. When a human is needed, HumanLayer supplies the shape: a durable `approvals` table with a status `CHECK`, a partial index on pending, `responded_at`, rationale on both approve and deny, `approval_id` denormalised onto the tool-call event, `ErrAlreadyDecided` returning the existing status on a retry, and reconciliation on restart. Its one gap is ours to close: it records *why*, never *who*.
Evidence: ADR-0015; `agent-control/models/controls.py:244-275`; `humanlayer/hld/store/sqlite.go:201-220`, `hld/store/errors.go:13-42`; `google-ax/proto/content.proto:28-47`

### Q18. How do humans and agents collaborate on shared work?
Answer: As the same kind of participant, discriminated by kind rather than separated into subsystems. AG2's `PassportKind = agent | human | remote_agent` is the cleanest expression found: a human has a passport, a rule, an inbox, and is addressable in `audience` exactly like an agent. Every other project either models humans in a separate subsystem or not at all. Omnigent adds the collaboration surface — session ACLs with read/edit/owner levels, a `__public__` sentinel for link sharing, live co-driving, and file-range-anchored review comments.
Evidence: ADR-0007; `ag2/network/identity.py:38,69-71`; `omnigent/entities/permission.py:9-46`, `entities/comment.py:41-49`

## Security

### Q19. What identity does an agent authenticate as?
Answer: As itself — a workload identity distinct from the human's — and that identity is what policy names. AgentCore is the reference: the agent obtains its own access token, and Cedar policies name `principal` as a language primitive, so the agent is nameable in the authorization language rather than bolted onto it. Critically, this study forced a split: **`Principal` (who is acting) and `Credential` (what secrets the action carries) are different subsystems**, because ADK has excellent credentials and no principals, HumanLayer has durable decisions and no approver, Agent Control governs behaviour and cannot express authority, and only AgentCore has both.
Evidence: ADR-0007 (4 challenges, all resolved into the split); `aws-agentcore/services/identity.py:140-155`, `policy/client.py:30-37`; `google-agent-platform/auth/`; `humanlayer`; `agent-control`

### Q20. Whose credentials apply when an agent delegates?
Answer: The delegated authority's, obtained explicitly and scoped narrowly — never the platform's ambient credentials. AgentCore names the three flows (`M2M`, `USER_FEDERATION`, `ON_BEHALF_OF_TOKEN_EXCHANGE`) and separates *obtaining* a credential from *keeping it alive* into distinct exchanger and refresher registries, which is the right split because they have different failure modes. Omnigent adds the containment rule: the secret never enters the sandbox at all — the egress proxy swaps a host-bound single-use placeholder for the real credential, and rejects a placeholder presented to the wrong host with 403.
Evidence: ADR-0007; `aws-agentcore/identity/auth.py:30`, `auth/exchanger/`, `auth/refresher/`; `omnigent/designs/SANDBOX_CREDENTIAL_PROXY.md`

### Q21. Where are policy decisions enforced?
Answer: At named enforcement points in the control plane, never in the agent, with the fail-closed set decided by *position in the enforcement path*. Omnigent's rule is the sharp one: fail closed where the decision is the last line of defence (`PHASE_TOOL_CALL`, `PHASE_REQUEST`), fail open where the harm is already incurred (`PHASE_TOOL_RESULT` — "the tool has already executed"). Policy is Cedar, not a bespoke DSL, so decisions can be *analysed* and not merely executed. Decisions are three-way (`deny | steer | observe`), traced with the deciding policies named, aggregable, and subject to ownership precedence — organisation policy binds agent policy, and the governed cannot edit the governor.
Evidence: ADR-0013 (2 amends); `omnigent/policies/types.py:59-80`; `aws-agentcore/policy/client.py:30-37`; `agent-control/models/actions.py:8-17`; `microsoft-agent-framework/packages/purview/README.md`; `ag2/network/rule.py:12`

## Platform boundary

### Q22. What do we build?
Answer: Four **target-architecture** items, each because the evidence shows no adequate precedent — of which **two ship in v0.1**. **(1) Content-derived version pinning applied to the agent definition** *(v0.1)* — MAF proves the mechanism on workflows (a bytecode digest enforced on restore) and nobody applies it to agents; the clearest differentiator in the study. **(2) The effect ledger** *(v0.1)* — two partial precedents with different keys (Cloudflare's explicit `idempotency_key`, AG2's `causation_id`) and nobody makes it platform-owned; ADK explicitly delegates it to tool authors. **(3) The unified `Capability` + `Extension` model with a two-layer conformance bench** *(v0.1 ships the **offline** layer only; the live probe layer is deferred)* — Omnigent has the bench, Pydantic AI has the composition, nobody has both. **(4) Agent-level revocation and an approver identity on approvals** *(**approver identity** in v0.1; **revocation deferred**, trigger: first multi-tenant deployment)* — thirteen projects, and the best available is credential-level (AgentCore) or attachment-level (Agent Control). **The distinction matters: this answer is the target architecture, not the shipment.** See `synthesis/scope-reconciliation.md` §1.
Evidence: ADR-0011 amendment 3; ADR-0014; ADR-0012 amendment 3; ADR-0015; `synthesis/scope-reconciliation.md` §1; `synthesis/v01-boundary.md`; D9 negative in 10 of 13, `implicit` in 3

### Q23. What do we reuse or integrate?
Answer: **Three** INTEGRATE candidates — one of them contingent — and a longer list of ports. **INTEGRATE: `ag2.network`** *(CONTINGENT)* — Apache-2.0, Python, opt-in, tested; the envelope schema and hub contract solve the one subsystem we would otherwise invent with no prior art, but its file WAL and pruned causation index give its dedupe guarantee a retention horizon, so integration is **gated on a storage spike that has not been run**. If the spike fails, port the `Envelope` schema and build the hub on our own log. **INTEGRATE: Cedar** for policy — with the tested caveat that `cedarpy` exposes schema validation but *not* permissiveness comparison, which lives in Cedar's Rust/Lean crate (ADR-0013 amendment 3). **INTEGRATE: `genai-prices`** for cost data, paired with Omnigent's fail-closed-on-unpriced rule. **NOT integrated — reclassified to PORT: Agent Control.** It carries its own PostgreSQL persistence and its own `namespace_key` tenancy and **has no `Principal` model**, so running it as a dependency would mean a second policy store structurally unable to name the principal ADR-0007 requires on every decision; we take its patterns (`deny|steer|observe`, steer-requires-guidance, recursive condition trees, separate agent/admin credentials, tenancy in composite foreign keys) instead. **PORT:** Pydantic AI's `_ssrf.py` guard list, Omnigent's secretless credential proxy, AX's fold-the-log state derivation and composite-PK single-writer, Cloudflare's hung-work detection and no-progress backoff, MAF's bytecode-digest pin, HumanLayer's `Approval` schema, ADK's in-memory-sibling discipline and four state scopes.
Evidence: `synthesis/scope-reconciliation.md` §3–4; `synthesis/build-reuse-map.md`; ADR-0003; ADR-0013 amendment 3; Q6 verdicts across all 13 facts.yaml

### Q24. What standards do we implement?
Answer: OpenTelemetry with GenAI semantic conventions — declaring the semconv version we emit, supporting one deprecation window with a warning, separating stable from experimental attributes by *module*, namespacing vendor keys and never squatting on another tool's prefix, and asserting cross-boundary propagation with a test rather than a dependency list. Cedar for policy. MCP for tools and A2A/ACP for agent interop, both strictly as *edge adapters* outside a richer internal model — five projects independently confirmed that shape. RFC 8628 for delegated human authorization, OAuth2/OIDC for credentials, RFC 5545 for recurrence, W3C trace context for propagation.
Evidence: ADR-0010 (3 amends), ADR-0005, ADR-0006 (5 independent confirmations), ADR-0013 amendment 1; `cloudflare-agents/observability/genai/attributes.ts:1-9`; `pydantic-ai/docs/logfire.md:294-298`; `google-agent-platform/telemetry/_adk_attributes.py:15-24`

### Q25. What are the hard platform boundaries — what will we never build?
Answer: Five hard boundaries, each backed by evidence rather than preference. **(1) No compensation or rollback engine** — zero positive answers in thirteen projects, including the one whose whole job is control and the one whose whole job is orchestration; Pydantic AI shows why: saga compensation belongs to a durable workflow engine, so we integrate Temporal/DBOS/Prefect rather than reimplement it. **(2) No workflow engine of our own** — MAF and Pydantic AI both demonstrate that orchestration is a separable, better-solved concern. **(3) No model gateway or provider abstraction** — an explicit anti-goal of this study, and a solved commodity. **(4) No _public_ authoring framework** (amended 2026-08-27: we build and operate the agents on vendor SDKs; the adapter boundary remains so the SDK stays swappable) — we do not compete with the frameworks that write them; Cloudflare's coherent alternative (write the agent against our runtime) is rejected because we operate the agents ourselves and keep the adapter boundary to swap SDKs (2026-08-27; supersedes the adapt-anyone rationale). **(5) No bespoke policy DSL, trace format, or messaging protocol** — adopt Cedar, OTel and AG2's envelope instead.
Evidence: L8 negative in 12/13 and `unknown` in the 13th; ADR-0004 (Cloudflare challenge); `pydantic-ai/durable_exec/AGENTS.md`; `microsoft-agent-framework/_workflows/`; PLAN.md anti-goals

---

## The closing statement

The teardown has succeeded when this can be written with confidence, backed by
evidence rather than taste. Draft it here; it becomes the opening of the v0.1
architecture document.

> TODO
