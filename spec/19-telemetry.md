# 19 — OpenTelemetry semantics
<!-- status: draft -->

What Phoenix emits over OpenTelemetry: the vendor attribute namespace and its stability
tiers, the span and metric inventory, the three version pins (the GenAI semantic conventions
we follow, the instrumentation format the harness emits, and our own schema version), how W3C trace context crosses
the three process boundaries between a client and the harness that calls the model, what a
policy decision and a refusal look like when they must be *counted* rather than read, and which
spans a sampler may never drop. The changes it needed in `spec/01`, `06`, `07` and `08` landed
on 2026-08-30 and are cited in the present tense; what remains unowned is recorded as an open
question, not as an owed edit.

It does not settle the backend — collector endpoint, storage, retention and dashboards are
deployment configuration, not contract. It does not settle per-tenant sample ratios
(unknown — OQ). And it does not make telemetry durable: audit, billing and every safety
decision read `run_events`, `effect_ledger`, `policy_decisions` and `approvals` from
[§01](01-schema.md), never a span. ADR-0010's own Implications say OTel "may not give" the
durability audit needs; the log and the adapter checkpoint are the only durability we have.

Hops 3 and 4 below, the `phoenix.driver` span kind, and the resume-links-rather-than-continues
rule all inherit ADR-0016, which is **Proposed**, gated on spike 05
(`ADR-0016-sandbox-placement-is-control-plane.md:3`). If checkpoint-and-kill or the PID-1 driver
changes, hop 3's carrier and rule 4 change with it.

---

## Namespace, and the two tiers inside it

| Rule | |
|---|---|
| Follow `gen_ai.*` wherever the GenAI semantic conventions define a key | ADR-0010 amendment 1, rule 1 |
| Everything else lives under `phoenix.*` | one vendor namespace, declared once |
| `phoenix.experimental.*` carries **no** compatibility guarantee — renamed, restructured or removed in any release | ADK's `_adk_attributes.py:15-24 @ 85b52f6` |
| Never a bare top-level key, and never another tool's prefix | `cloudflare-agents/observability/genai/attributes.ts:1-9 @ 2f957bc`: "never bare top-level keys, never `ai.*`" |
| Never invent an attribute for something the protocol models as span state | `tracing/tracer.ts:298 @ 2f957bc` declines an `otel.status_code` attribute |

Phoenix code MUST NOT write `ai.*`, `adk.*`, `cloudflare.agents.*`, `logfire.*` or
`pydantic_ai.*`. Three keys under the last two prefixes arrive anyway: the harness emits
`logfire.json_schema` (`_instrumentation.py:485 @ b48ee38`), `pydantic_ai.tool.deferral.name`
and `pydantic_ai.tool.failure_stage` (`:674,678`). **Harness-emitted spans pass through
unaltered** — rewriting another project's attributes would destroy the semconv adherence
that is the reason we chose it — so the harness allowlist is **those three named keys**, not
the two prefixes: a prefix would admit every future key under `pydantic_ai.*` sight unseen,
which is the content claim at the end of this document signed over to the next SDK release. A
fourth key is a deliberate decision, and the key test below stays red until someone makes it.

The namespace string is a deployment-wide constant. Renaming it is a breaking change for
every consumer, which is what rule 2 of ADR-0010 exists to prevent.

## Three version pins, and what each one covers

| Pin | Value | Where it is stated | Confidence |
|---|---|---|---|
| GenAI semantic conventions | **1.37.0** | `pydantic-ai/docs/logfire.md:294 @ b48ee38` | `ASSERTED` |
| SDK instrumentation format | **`version=5`** | `models/instrumented.py:79 @ b48ee38`, default `DEFAULT_INSTRUMENTATION_VERSION = 5` (`_instrumentation.py:32`) | `VERIFIED` |
| Phoenix telemetry schema | integer, a Resource attribute `phoenix.telemetry.schema_version` | this document | ours to keep true |

`ASSERTED` and `VERIFIED` are [§07](07-adapter-protocol.md)'s vocabulary and the distinction
is load-bearing here. The semconv number is stated in the SDK's **documentation**, which is
not among the twenty-two file digests spike 06 pins; the format version is a literal in code
we can read. Only the second is checkable by a gate today.

`version` accepts 2–6 (`models/instrumented.py:90 @ b48ee38`). We emit 5. Passing 2, 3 or 4
raises `PydanticAIDeprecationWarning` (`:158-160`) and reverts to the pre-semconv names —
`agent run`, `running tool`, `tool_arguments` (`_instrumentation.py:692-697`). Version 6
re-roles a part a consumer already receives: a `tool_call_response` takes the `tool` role where
earlier versions keep it on `user` (`models/instrumented.py:416,432`), so it is not emitted
until a consumer asks for it. Being selectable per deployment through
`InstrumentationSettings.version` (`:90`) is ADR-0010 amendment 2 rule 5's "make it selectable";
message-part types pinned by the SDK to spec commit `eccd1f8` (`_otel_messages.py:1-4`) are the
rest of rule 5, satisfied upstream rather than by us.

**One deprecation window.** At most two Phoenix telemetry schema versions are accepted at a
time: the current one and its immediate predecessor, which logs one warning per process —
ADR-0010 amendment 2, rule 5. ADK's `_schema_version.py:15-20 @ 85b52f6` is the shape, a
deployment-pinnable telemetry schema covering span names, span/log attributes and metrics
(`projects/google-agent-platform/teardown.md:277-295 @ 85b52f6`). A third version is a
migration, not a compatibility mode.

## Span inventory

| Span name | Emitted by | Kind | Parent |
|---|---|---|---|
| `{http.request.method} {http.route}` | control plane | SERVER | the client's `traceparent`, when present |
| `phoenix.run` | control plane | INTERNAL | the API entry span, or a sweeper root |
| `phoenix.sandbox` | control plane | CLIENT | `phoenix.run` |
| `phoenix.driver` | driver | CONSUMER | remote parent from the container environment |
| `phoenix.harness` | harness | SERVER | remote parent from `Start.traceparent` |
| `invoke_agent {gen_ai.agent.name}` | Pydantic AI | INTERNAL | `phoenix.harness` |
| `chat {gen_ai.request.model}` | Pydantic AI | CLIENT | `invoke_agent …` |
| `execute_tool {tool_name}` | Pydantic AI | INTERNAL | — **not emitted for a Phoenix tool; see below** |
| `phoenix.tool_call {tool_name}` | control plane | INTERNAL | `phoenix.run` — see *The tool span the SDK does not emit* |
| `phoenix.policy_decision` | control plane | INTERNAL | `phoenix.tool_call …`, or `phoenix.run` for the `request` phase |
| `phoenix.approval` | control plane | INTERNAL | `phoenix.tool_call …` |
| `phoenix.effect` | whoever settles the row | INTERNAL | the claim's context, or a link (below) |
| `phoenix.tool_registration` | harness | INTERNAL | `phoenix.harness` — created **only on a refusal**, after the outcome |

`phoenix.driver` is CONSUMER, not SERVER: the driver is PID 1 and receives no request
(`ADR-0016:63-71`), its context arriving out-of-band in the environment. `phoenix.harness` is
SERVER because it does receive a `Start` frame.

The three SDK names are read out of the installed harness, not guessed:
`invoke_agent` at `_instrumentation.py:701,719`, `execute_tool {tool_name}` at `:703,732`,
`chat {model_name}` at `:474-475` — all at instrumentation format 5. The tool name is listed
because a consumer must know it will *not* see it.

**Span names are a closed set added in code**, the rule [§04](04-events.md) already applies
to event types. Exactly three suffixes are composed at runtime. `tool_name` is bounded by the
pinned definition, which §07 requires it to match (`07-adapter-protocol.md` `message ToolCall`).
`gen_ai.agent.name` and `gen_ai.request.model` are bounded because we build and operate the
agents and the definition is pinned per run — §01 fixes that definition by digest and declares
no model column, so this bound is ours to keep, not one the schema enforces. No identifier ever
enters a span name.

## Attributes

| Key | On | Value |
|---|---|---|
| `phoenix.tenant_id` | every Phoenix span | §01's scope, on every span for the same reason it is in every composite key |
| `phoenix.run_id` | every Phoenix span | |
| `phoenix.run.state` | `phoenix.run` | §01's `run_state` |
| `phoenix.run.error_code` | `phoenix.run` | §01's `error_code`; a span attribute only, because its value set is not closed (see *Metrics*) |
| `phoenix.run.epoch`, `phoenix.run.seq` | `phoenix.run` | the fold position the span was taken at ([§04](04-events.md)) |
| `phoenix.pin.definition_digest`, `phoenix.pin.adapter_identity` | `phoenix.run` | the pin compared before any adapter code runs |
| `phoenix.adapter.integration_mode` | `phoenix.driver` | §01's enum |
| `phoenix.tool.name` | `phoenix.tool_call …` | mirrors `gen_ai.tool.name` where the consumer is semconv-shaped |
| `phoenix.tool.call_id` | `phoenix.tool_call …` | the §07 correlation id |
| `phoenix.effect.idempotency_key`, `phoenix.effect.request_digest` | `phoenix.effect` | §01's deterministic key and [§03](03-canonicalisation.md)'s digest |
| `phoenix.effect.status` | `phoenix.effect` | §01's status, **set at creation** |
| `phoenix.policy.decision` | `phoenix.policy_decision` | `deny` \| `steer` \| `observe`, **set at creation** |
| `phoenix.policy.enforced` | `phoenix.policy_decision` | `false` is a shadow verdict (§01) |
| `phoenix.policy.phase` | `phoenix.policy_decision` | `request` \| `tool_call` \| `tool_result` |
| `phoenix.policy.deciding_policy_ids` | `phoenix.policy_decision` | the ordered list §04's `policy.evaluated` carries |
| `phoenix.approval.id`, `phoenix.approval.status`, `phoenix.approval.decided_by` | `phoenix.approval` | `decided_by` is invariant 8 |
| `phoenix.denial.reason` | `phoenix.tool_call …` | §07's `ToolDenied.Reason`, **set at creation** of the refusal record |
| `phoenix.tool.uninterceptable` | `phoenix.tool_registration` | `true` when a tool in the pinned definition cannot be routed through the ledger and registration is refused (`07-adapter-protocol.md` §Who executes a tool, `UninterceptableTool`, gate 6), **set at creation** |
| `phoenix.experimental.cost.amount_nanos` | the cost span | int; nano-units of the currency's major unit ([`18-cost.md`](18-cost.md) §Telemetry) |
| `phoenix.experimental.cost.currency` | the cost span | ISO 4217 (`18-cost.md` §Telemetry) |
| `phoenix.experimental.cost.unpriced_reason` | the cost span | `model_not_in_snapshot` \| `snapshot_unresolved` \| `usage_incomplete` (`18-cost.md` §Telemetry) |
| `phoenix.experimental.cost.price_snapshot_digest` | the cost span | sha256 hex of the pinned dataset (`18-cost.md` §Telemetry) |
| `error.type` | any span that failed | the OTel convention; `phoenix.*` never re-models it |

The four cost keys take the `phoenix.experimental.*` tier deliberately: their pricing path is
still an open question in [`18-cost.md`](18-cost.md) §Pricing, and that tier carries no
compatibility guarantee (ADK's `adk.experimental.*`, `_adk_attributes.py:15-24 @ 85b52f6`).
Naming them here rather than in §18 keeps one namespace with one owner.

Resource attributes, per process: `service.name` and `service.version` (OTel resource semconv),
with `service.name` ∈ {`phoenix-control-plane`, `phoenix-driver`, `phoenix-harness`} — three
processes, matching `ADR-0016:63-71`'s one container running the driver plus its child — and
`phoenix.telemetry.schema_version` (the pin above; ADK's `_schema_version.py:15-20 @ 85b52f6`).

**Cardinality.** ADR-0010's Implications require discipline on agent and tenant ids. The rule
is a boundary, not a judgement: identifiers that name one run, one effect, one decision, one
approval or one principal, and every digest, are **span attributes only**. Metric attribute
sets are closed and enumerated per instrument, below.

## Propagation — the exit criterion

| # | Hop | Carrier |
|---|---|---|
| 1 | client → control plane | `traceparent` / `tracestate` request headers, W3C Trace Context, read on every route ([§06](06-api.md) §Request headers read on every route, added 2026-08-30); §07 fields 5-6 fix the same shape on `Start` |
| 2 | control plane → the log | `run_events.traceparent`, the full header (`01-schema.md` §The log, `run_events.traceparent`, §04) |
| 3 | control plane → driver | `TRACEPARENT` / `TRACESTATE` in the run container's environment, carried in `CreateSpec.Bootstrap` ([`15-sandbox.md`](15-sandbox.md) §1) — which the provider sets into the container's environment **without parsing it**, alongside `run_token` — because the plane places the sandbox, the driver is PID 1, and there is no inbound RPC to carry a header (`ADR-0016:63-71`). The shape is Omnigent's `get_traceparent_env()` made live rather than dead (`projects/omnigent/teardown.md:420-425 @ ba9e371`) |
| 4 | driver → harness | `Start.traceparent` / `Start.tracestate`, over the inherited socketpair (§07) |
| 5 | harness → SDK | the hop-4 context, installed as the remote parent of `invoke_agent …` |

`run_events.traceparent` is `TEXT NOT NULL` (`01-schema.md` §The log, `run_events.traceparent`, amended 2026-08-30 by this
document): a sweeper-originated event opens its own root span, so every append can supply one.
The schema enforces the invariant; the test below is the second line of defence, not the only
one.

Four rules bind these.

1. **The full W3C header, never a bare id.** Without the parent span and the sampled flag the
   receiver starts a new trace (§04, §07). The banned shape is a bare 32-hex value in a field
   named for a trace.
2. **Trace context is never an authorization input.** Protocol authentication is `run_token`
   on `Start` (`ADR-0016:71`) and `tenant_id` is never read from a request (§06). A forged
   `traceparent` joins a trace and buys nothing else.
3. **A carrier that is set but never read is not propagation.** Hop 3 is the exact shape of
   Omnigent's defect — `get_traceparent_env()` audited as "dead code — zero call sites"
   alongside an instrumentor "never wired" (`omnigent/designs/OBSERVABILITY.md`, quoted in
   `projects/omnigent/teardown.md:420-425 @ ba9e371`). The test asserts the *receiving* span has
   a remote parent, not that the variable was written. The carrier the control asserts is
   `CreateSpec.Bootstrap`'s two environment entries, which is a field a test can drop.
4. **One trace per invocation; links between them.** Suspend is checkpoint-and-kill
   (ADR-0016), so a resumed run is a new container: the resuming request opens a new trace and
   its `phoenix.run` span carries an OTel **link** to the previous invocation's context, read
   from the most recent `run_events.traceparent`. Cloudflare's `boundToInvocation` closes a span
   so that "it cannot outlive the native invocation that owns its tracing context"
   (`tracing/tracer.ts:24-31 @ 2f957bc`; ADR-0010 amendment 1, rule 4). A run resumed five times
   has five traces and one `phoenix.run_id`.

### The tool span the SDK does not emit

**The SDK emits no tool-execution span for a Phoenix tool.** Tools are declared through
`ExternalToolset`, which stamps `kind='external'` (`toolsets/external.py:32-40 @ b48ee38`);
`_execute_tool_call_impl` raises `RuntimeError('External tools cannot be called')` for that kind
at `tool_manager.py:976-977`, *before* the instrumentation capability's `wrap_tool_execute`
(`capabilities/instrumentation.py:499-521`), which is the only creator of a tool span. On the
outbound path an external call never reaches tool execution at all — it is batched into
`DeferredToolRequests` (`_tool_execution.py:926-951`) — and on the resume path a
platform-supplied result is returned by the `else: tool_result = tool_call_result` branch at
`_tool_execution.py:696`, again without an execution span.

**No spike observed this.** Spike 06's sixty-four gate assertions
(`spikes/06-tool-interception/RESULT.md:3`) are about the tool boundary and the effect ledger;
none creates a tracer, and no negative control there could have gone red on a span appearing
(VERIFICATION-RULES rules 2 and 4). The paragraph above is a reading of the installed SDK, so it
is `ASSERTED` in §07's vocabulary, not `VERIFIED`: `toolsets/external.py`, `tool_manager.py` and
`_tool_execution.py` are among the twenty-two pinned digests, but
`capabilities/instrumentation.py` — the file that creates the tool span, and so the one the
argument turns on — is not. The `execute_tool` row in the test table below is the only thing
that would establish the claim.

So `phoenix.tool_call …` is the **only** span for a mediated tool call, parented on
`phoenix.run`. There is no `execute_tool` parent to lose, and nothing is owed to §07 here:
§07's `ToolCall` has three fields — `tool_name`, `arguments`, `call_id`
(`07-adapter-protocol.md` `message ToolCall`) — and the enclosing `Output` adds `step_id` (`:118`); none of
the four is trace context, and adding one would buy a parent edge that does not exist.

## Policy decisions and refusals

ADR-0013 requires every decision to be explainable "to the operator and to the agent without
reading source". AG2 requires refusals to be as observable as successes
(`ag2/network/hub/core.py:1861-1866 @ 90f490a`, `on_envelope_rejected` fires for every
attempt). Agent Control requires them to be **aggregable** — a modelled, queryable dataset
rather than log lines (`models/src/agent_control_models/observability.py:30-460 @ 7cb21af`).
Three obligations, three carriers:

| Carrier | Holds |
|---|---|
| `policy_decisions` (§01) | the authority: every evaluation, enforced or shadow, with `latency_ms` and the partial index on `enforced = false` |
| `phoenix.policy_decision` span | the explanation, joined to the run that caused it |
| `phoenix.policy.decisions` counter | the aggregate, unaffected by sampling |

A `deny` is a **successful evaluation**, so the span's status is unset, not `ERROR` — the
decision is an attribute and status stays span state (Cloudflare's refusal to invent
`otel.status_code`). The span for the *tool call* that was refused does carry `error.type`,
because that operation did not complete.

**A span whose sampling depends on its outcome is created after the outcome**, with an explicit
start timestamp captured before the operation began. That is what makes the forced list below
implementable: `Sampler.ShouldSample` is called once, at span creation, and sees only the
attributes passed there (the OTel tracing SDK specification — `ASSERTED` in §07's vocabulary,
because no digest we pin covers it, which is why the test at the end asserts the sampler's view
directly rather than trusting the claim). `phoenix.policy_decision` is therefore created when
Cedar returns, and its authoritative latency is `policy_decisions.latency_ms` (§01), not the
span duration.

`phoenix.effect` follows the same rule and adds one case: the worker that dispatched an effect
may be gone. The span is emitted by **whoever settles the row** — the dispatching worker on
success or failure, the sweeper on `indeterminate` ([§02](02-consistency.md), phase 5) — with
start = `claimed_at`. The sweeper is in another invocation, so it links rather than parents,
using the `traceparent` recorded on the `effect.claimed` event. Without this the one status a
human must look at is the one status nothing emits.

**A never-claimed row gets no `phoenix.effect` span.** Denial, expiry and abandonment all move
a row that was never claimed (`02-consistency.md` §Denial, expiry, abandonment), so there is no `claimed_at`, no
lease holder, no settling worker and no sweeper — and §04's effect registry has no denial event
to carry a `traceparent` (`04-events.md` §Effects). A denied effect is carried instead by
`phoenix.denial.reason` on the tool-call span and by the `phoenix.effects` counter's `status`
dimension. This is why `denied` is absent from the forced list below.

## Metrics

| Instrument | Type | Closed attribute set |
|---|---|---|
| `phoenix.policy.decisions` | counter | `decision`, `enforced`, `phase`, `policy_id`, `tenant_id` |
| `phoenix.tool_calls` | counter | `outcome` ∈ {`ok`,`denied`,`failed`}, `denial_reason`, `tool_name`, `tenant_id` |
| `phoenix.effects` | counter | `status`, `tenant_id` |
| `phoenix.runs.terminal` | counter | `state`, `tenant_id` |
| `phoenix.api.refusals` | counter | `error` (§06's closed code set), `tenant_id` |

Refusals and successes are dimensions of **one** instrument, not separate instruments — that
is AG2's contribution made countable. `tool_name` is admissible because the tool set is closed
by the pinned definitions and we build every bundle. `tenant_id` is admissible because
per-tenant aggregation is a product requirement; its ceiling
(tenants × policies × decision × phase × enforced) is unknown — OQ. Nothing else from the
cardinality rule above may appear.

`error_code` is **not** an attribute of `phoenix.runs.terminal`, because nothing closes its
value set: `01-schema.md` §Run declares `error_code TEXT` with only a
`CHECK (state <> 'failed' OR error_code IS NOT NULL)` (§Run), §05 names values inline without
making them exhaustive, and §07 has the adapter supply it on a failed `End`. It rides
`phoenix.run` as a span attribute and is omitted from the metric until the run error vocabulary
is a closed set added in code — §04's naming rule applied to error codes, an *owed edit* to §01
and §05.

Token usage is `gen_ai.client.token.usage`, emitted by the harness
(`models/instrumented.py:170 @ b48ee38`) with the boundaries the semconv advises
(`_instrumentation.py:64-67 @ b48ee38`; `TOKEN_HISTOGRAM_BOUNDARIES` at `:67`). We do not
re-emit it under `phoenix.*`.

## Sampling

1. **`ParentBased` head sampling.** A remote parent's sampled flag is honoured at every hop.
2. **v0.1 root ratio is 1.0.** A ratio nobody exercises is the same class of untested
   configuration as the `FastAPIInstrumentor` Omnigent found "gated off by default"
   (`projects/omnigent/teardown.md:418-425 @ ba9e371`; ADR-0010 amendment 1); lowering it is a
   deployment change with its own test.
3. **The forced list.** These are `RECORD_AND_SAMPLE` whatever the parent flag says:
   `phoenix.policy.decision ∈ {deny, steer}` at either `enforced` value; any span carrying
   `phoenix.denial.reason`; `phoenix.effect.status = indeterminate`;
   `phoenix.run.state ∈ {indeterminate, incompatible}`; any span carrying
   `phoenix.tool.uninterceptable = true`.

   Membership rule: an outcome that costs human attention and that no client asked for.
   `indeterminate` is **system only** and never a retry (`05-state-machine.md:86-87`), and the
   sweeper's means "a human is now investigating" (`02-consistency.md` §Claiming and performing an effect, the sweeper); `incompatible` is a
   pin mismatch the worker decides before any adapter call (`:89`); a `deny` or `steer` "must be
   explainable to the operator and to the agent without reading source" (ADR-0013
   Decision:48-54); `uninterceptable` is a refused registration. `expired` is **system only**
   too (`:86`) but is deliberately **excluded**: a deadline passing is the configured outcome of
   a run nobody stopped, and forcing it samples every timeout at whatever rate timeouts occur.
4. **The deciding attribute is set at creation.** An attribute added afterwards cannot change a
   decision already made, which is why rule 3 depends on the after-the-outcome creation rule
   above. This has a negative control and it is the rule most likely to rot.
5. **A sampler never reads content**, only the closed attribute set.
6. **Sampling never touches the log or the tables.** A shadow deny that was not sampled is
   still a row in `policy_decisions` and still increments `phoenix.policy.decisions`.

**What head sampling cannot do.** An HTTP refusal — §06's `403`, `404`, `409`, `422` — is not
known when the SERVER span is created, so it cannot be forced into its own trace. Those
refusals are carried by `phoenix.api.refusals` and by the error body. A collector-side tail
sampler would close the gap; whether v0.1 runs one is unknown — OQ.

## Content is off

`InstrumentationSettings.include_content` and `include_binary_content` both default to
**`True`** (`models/instrumented.py:76-77 @ b48ee38`) — prompts, completions, tool call
arguments and tool results become span attributes. Phoenix sets both to `False`, so no prompt,
completion, tool argument or tool result is emitted as a span attribute. The default being
permissive is exactly why this is a normative line with a test rather than an assumption.

**Recorded exceptions are the second content path**, and the two flags do not close it: OTel
exception recording carries `exception.message` and `exception.stacktrace`, and a tool-argument
validation error or a model client error puts customer text in both. So `phoenix.*` spans record
`error.type` only, never `exception.message` or `exception.stacktrace`, and harness-emitted
spans — which otherwise pass through unaltered — have their exception events dropped at the
exporter. The third path is the attribute allowlist, closed rather than a prefix (above): every
emitted key is `gen_ai.*`, a stable OTel convention, `phoenix.*`, or one of three named harness
keys, none of which carries content. On those three mechanisms together — the two flags, the
dropped exception events, the closed key list — the bounded claim: **no customer data leaves
through the span path.** It does not survive a prefix allowlist, which is why there is not one.

## Tests, with negative controls

| Invariant | Test | Negative control |
|---|---|---|
| One trace id spans client → plane → driver → harness (§08 test 26, amended 2026-08-30 to this four-participant form together with `07-adapter-protocol.md` §Who executes a tool and §07's own `One trace id end to end` test row, all three of which read `client → plane → adapter` before — under `sdk_subprocess` the driver hop is a fourth participant with its own carrier, hop 3, and is not part of "the adapter". ADR-0010 amendment 1 rule 3 still states the three-participant form and is the older text) | drive a run through all three process boundaries; assert one distinct trace id and one span per participant, the receiving span carrying a REMOTE parent | drop the hop-3 environment carrier (`CreateSpec.Bootstrap`'s two entries) ⇒ two trace ids |
| The carrier is *read*, not merely written | assert `phoenix.driver` has a **remote** parent equal to the plane's span id | start a root instead ⇒ empty parent; the `get_traceparent_env()` case |
| A bare trace id does not propagate | supply 32 hex characters where the header belongs | accept it ⇒ the harness starts a second trace |
| Every appended event carries a traceparent | append through §02's protocol with a NULL `traceparent`; assert Postgres `23502` | drop the `NOT NULL` inside a transaction rolled back unconditionally, append NULL, and show §04's fold cannot reconstruct a trace — then assert the constraint is still present. Rule 7: prefer rollback, and prove the unrelated state survived |
| Resume links, never continues | suspend, resume, assert two trace ids and a link between them | reuse the first context ⇒ a span outlives its invocation |
| A denied tool call is sampled under an unsampled parent | set the incoming sampled flag to 0, then deny | `ParentBased` alone ⇒ the deny is dropped |
| A sampled-out shadow deny still counts | ratio 0, run an `observe` policy that would deny | derive the count from spans ⇒ the number moves with the ratio |
| Deciding attributes exist at creation | assert the sampler's view carries `phoenix.policy.decision` | set it after `start_span` ⇒ the forced span is dropped |
| An `indeterminate` effect produces a span | kill the worker after the claim; let the sweeper settle | emit only from the dispatching worker ⇒ nothing records it |
| No bare or foreign keys | assert every emitted key is `gen_ai.*`, a stable OTel convention, `phoenix.*`, or one of the three named harness keys (`logfire.json_schema`, `pydantic_ai.tool.deferral.name`, `pydantic_ai.tool.failure_stage`) | add a fourth `pydantic_ai.*` key ⇒ the assertion goes red; and drop the assertion ⇒ a bare `run_id`, or `ai.*`, passes |
| Content stays out | assert no prompt, argument or tool result appears in an exported span | leave `include_content` at its default ⇒ all three are exported |
| Exceptions carry no content | raise inside a tool with both content flags off; assert no exported span carries `exception.message` or `exception.stacktrace` | keep exception events ⇒ the tool argument appears in `exception.message` with the flags off |
| The SDK emits no `execute_tool` span for a mediated call | run a tool call end to end; assert no span named `execute_tool …` | register the same tool as a function tool ⇒ the span appears and the inventory is wrong |
| At most two schema versions, one warning per process | run with the predecessor pinned; assert acceptance and exactly one warning per process | accept a third version ⇒ two deprecation windows open at once, and no consumer knows which names it is reading |
| The pinned instrumentation format is the one emitted | assert `version == 5` and no deprecation warning | pass 2, 3 or 4 ⇒ `PydanticAIDeprecationWarning` and `agent run` / `running tool` names |
| Metric attribute sets are closed | check each instrument's keys against its declared list | admit `run_id` ⇒ unbounded time series |

## What this does not guarantee

- **Spans are not durable.** A dropped exporter batch is silent and nothing retries it. Every
  claim that must survive is read from §01's tables, per ADR-0010's own Implications.
- **One trace id is not a complete trace.** Forcing a late span into a trace whose earlier
  spans were dropped yields a span with ancestors that never arrived. It shows the deny, which
  is the point, and it will look broken in a UI.
- **HTTP-level refusals are not in the forced list** (above).
- **A denied or abandoned effect produces no `phoenix.effect` span.** The row was never
  claimed, so nothing settles it and no event carries its context; the denial is visible on the
  tool-call span and in the `phoenix.effects` counter, and nowhere else in the trace.
- **Content is bounded to the span path.** What a component writes to its own stdout or logs is
  outside this document.
- **Nothing re-checks the SDK's telemetry surface on a version bump.**
  `_instrumentation.py`, `models/instrumented.py` and `capabilities/instrumentation.py` — the
  last the only creator of a tool span, and so the file the *no `execute_tool` span* argument
  rests on — are not among spike 06's twenty-two pinned digests, so a bump could rename every
  span in the inventory, or change the attribute set the harness emits, with every gate green.
  The content flags are guarded by the content test above; the *names* are guarded by nothing.
  Same unpinned-module class of defect spike 06 found twice while narrowing its own pin.
- **The semconv version is `ASSERTED`.** It is stated in documentation outside the digest pin,
  so `1.37.0` is a claim we carry, not one a gate proves.
- **Sampling is per-invocation.** A run resumed many times may be sampled in some invocations
  and not others; the run is complete in the log regardless.
