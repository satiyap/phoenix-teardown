# 12 — Agent harness (Pydantic AI)
<!-- status: draft -->

This settles the **policy over Pydantic AI's seams**, not the seams. The seams exist and
are read: `capabilities/hooks.py`, `_history_processor.py` with the `ProcessHistory`
capability, `toolsets/`, and `CapabilityPosition`
([`00-overview.md`](00-overview.md) §Documents, row 12, for the seam list;
`projects/pydantic-ai/teardown.md:58,195-198,210-213,218-221 @ b48ee38` for the types).
What is ours is which are installed, in what order, with what inputs, and what each is
forbidden to do.

It does **not** restate the frame contract ([§07](07-adapter-protocol.md)), the ledger
([§01](01-schema.md), [§02](02-consistency.md)), the run states
([§05](05-state-machine.md)), or the digest profile ([§03](03-canonicalisation.md)). It
does not specify the bundle model — that is `10-work-bundles.md` — only how a compiled
bundle becomes the context of one model request. It does not specify OTel attribute names
([`19-telemetry.md`](19-telemetry.md)) or the sandbox ([`15-sandbox.md`](15-sandbox.md)).

Two seams named here are **NOT VERIFIED** by any spike and are marked where they appear:
nested agents and compaction (`spikes/06-tool-interception/RESULT.md:502-511`). Those are
spike 06's own S9/S10 labels; the teardown's matrix numbers S9 and S10 differently
(`projects/pydantic-ai/teardown.md:382-383 @ b48ee38`), so they are not reused here.

---

## 1. Where the harness sits

`integration_mode = 'sdk_subprocess'` ([`01-schema.md`](01-schema.md) §Adapter contracts). The Go driver is PID 1
of the run's container and spawns the Python harness as its child, handing it one end of an
`AF_UNIX` socketpair; the §07 frames travel on that pair, and `run_token` on `Start` is the
protocol authentication (`spec/07-adapter-protocol.md` §Transport; spike 05 T2, which measured
that two containers cannot share a Unix socket under gVisor).

The harness is therefore **one process on one side of one socket**. Everything it knows, it
was told on that socket, read from the read-only knowledge mount the driver verified against
`manifest.json` before the spawn (§8), or computed from those two. **No frame carries a
credential field other than `Start.run_token`** (`spec/07-adapter-protocol.md:50-66`);
`Start.config` is opaque bytes and this document forbids a credential in it — the credential
document ([`14-credentials.md`](14-credentials.md)) owes the enforcement. The harness holds
**no database handle**, because no frame carries one (§10). It is also expected to have **no
egress path of its own**, but that is the sandbox's guarantee, not this document's — the
egress guard is owed by the sandbox document ([`15-sandbox.md`](15-sandbox.md) §5) and is
`unknown — OQ` here.

Spike 06 is one Python process; the shipment is three parties. The SDK-touching surface —
`register` / `run` / `resume` / `stream_output` (`harness.py:514,580,583,596 @ 42c4032`) —
ships in the **harness**; `intend` / `dispatch` / `resolve` (`:630,635,772`) ship in the
**control plane**, because they write the ledger and neither the harness nor the driver may
(`spec/02-consistency.md:174-306`; the driver's relay-only role is
[`13-adapter-sdk-subprocess.md`](13-adapter-sdk-subprocess.md) §5, "It reports; the
system decides those two").
`PhoenixHarness` holds every half only because it is a single-process stand-in (`RESULT.md`
simplification 1). The boundary it proves — *declaring* a tool versus *running* one —
survives the split, and its scoping (the invariant holds against a **cooperating** in-process
caller, because `h._PhoenixHarness__build()` still returns the `Agent`, simplification 13) is
exactly what the split closes: the driver never has a Python object to reach for.

## 2. The seams, and who decides

| SDK seam | Phoenix policy | Section |
|---|---|---|
| `toolsets/` — tool declaration | `ExternalToolset` only; no executable body ever reaches the SDK | §3 |
| `_history_processor.py` / `ProcessHistory` | at most one processor, chosen by the pinned definition; compaction declared `FALSE` in v0.1 | §4 |
| `toolsets/` — nested agents | delegation is a platform-created child Run, never an in-process sub-agent | §6 |
| `capabilities/hooks.py` — lifecycle hooks | emit frames and spans; **never** write the ledger | §7 |
| `CapabilityPosition` — ordering | fixed, declared, and asserted at startup | §11 |
| checkpoint payload | the SDK message history, opaque, pinned by `payload_schema_digest` | §9 |

## 3. Tool declaration is `ExternalToolset`, and only that

Tools are **declared**, never supplied. The harness builds one `ExternalToolset` from the
`ToolDefinition`s in the pinned definition and passes it as the agent's only toolset, with
`output_type=[str, DeferredToolRequests]` (`harness.py:566-569 @ 42c4032`).
`ExternalToolset.call_tool` raises unconditionally (`toolsets/external.py:46 @ b48ee38`)
while `get_tools` still advertises the tool (`:36`), so the model's behaviour is unchanged
and the SDK holds nothing it could run.

Four constructor and registration arguments are refused **by name**, whatever their value:
`native_tools`, `toolsets`, `tools`, `capabilities` (`harness.py:423,426-449 @ 42c4032`).
The fourth is not decoration — `capabilities=` delivers both provider-native tools and
executable local bodies (spike 06 gate 13, round 4).

`capabilities=` is refused **from a caller**; no capability may be supplied across the
boundary. The harness itself installs exactly one, `Instrumentation`, built from constants in
the harness image with the settings [`19-telemetry.md`](19-telemetry.md) pins: `version=5`,
`include_content=False`, `include_binary_content=False`. Those are not defaults — both flags
are `True` in the SDK (`models/instrumented.py:76-77 @ b48ee38`), so leaving them alone would
put prompts and tool arguments on the span path.

**The harness never executes a tool.** No executable body reaches the SDK
(`toolsets/external.py:46 @ b48ee38`; spike 06 gates 2 and 13), and the §11 startup
self-check asserts the toolset chain bottoms out in `ExternalToolset`. That the harness
*image* ships no platform tool package is a packaging rule, stated and not verified. A tool
call leaves as `Output{ToolCall}` and the answer arrives as
`ControlFrame{ToolResult|ToolDenied}` (`spec/07-adapter-protocol.md` §Who executes a tool); tool
implementations live on the platform side, with the ledger, the policy engine and the
approval record.

A tool the boundary cannot express **cannot be declared**: registration raises
(`UninterceptableTool`, `harness.py:53,514-537 @ 42c4032`; spike 06 gate 6;
`spec/08-conformance.md:127` row 30c). That covers every `AbstractNativeTool` the SDK ships,
which execute provider-side where no toolset can gate them — vendor-hosted tools are
unsupported in v0.1 (`spec/07-adapter-protocol.md` §Who executes a tool). A duplicate registration is
refused too: one name, one declaration, because a ledger row names only the name
(`harness.py:531-534 @ 42c4032`, spike 06 gate 2b).

## 4. History: which strategy runs, and when

**v0.1 installs no compaction strategy, and says so in its contract.** The SDK ships none
either — `ProcessHistory` is a transformation hook nothing fills
(`projects/pydantic-ai/teardown.md:195-198,431 @ b48ee38`), the teardown grades S6 silent
context loss `undefined` (`:379`), and spike 06 records compaction **NOT VERIFIED**
(`spikes/06-tool-interception/RESULT.md:507-511`). An unverified transformation over the
message list carrying the pending `ToolCallPart`s and their `tool_call_id`s — the list
`resume` matches results against (`harness.py:592-594 @ 42c4032`) — would put silent work
loss on the path the approval gate makes normal (ADR-0011's LangGraph finding).

So the normative rules are:

1. **At most one history processor is installed per run**, named by the pinned definition.
   Installing a second is a construction-time refusal, not a runtime surprise: a checkpoint
   is pinned to a definition digest (ADR-0011), and the digest pins the processor named in
   the definition, never the order in which two of them composed.
2. A processor is a **pure function of the message list**. It may not perform I/O, read the
   clock, or consult anything outside its argument — `ProcessHistory` is a transformation
   hook over that list and nothing else
   (`projects/pydantic-ai/teardown.md:195-198,431 @ b48ee38`).
3. A processor **may not remove, reorder, or rewrite** any `ToolCallPart` or its matching
   result while the corresponding `effect_ledger` row for this run is not settled.
4. **Compaction is declared `FALSE`** — `capabilities['compaction'] = {value: FALSE,
   confidence: VERIFIED}` in `AdapterContract` (`spec/07-adapter-protocol.md` §Capability declaration). An
   undeclared capability reads `UNKNOWN`, never `FALSE` (`:445-447`;
   `spec/08-conformance.md:132` row 23), which is why the declaration is explicit. `FALSE`
   here is `Capability.Value`; the tri-state `effect_ledger_participation ∈ {verified,
   asserted, unsupported}` at `:416-418` is a different declaration and is not what this
   rule sets.
5. A run that would exceed the model's context window ends
   `End{FAILED, error_code = context_exhausted}`. Loud truncation, never silent: dropping
   history to keep going is the failure ADR-0011 exists to prevent.

When compaction does ship it must be **step-preserving** in the sense of §5, and it must
carry a loss signal in the log. Neither is verified today; the strategy and its
verification are `unknown — OQ`.

## 5. `step_id`, and why compaction cannot move it

`Output.step_id` feeds `logical_step_path` in the effect key, so an id that shifts breaks
idempotency (`spec/07-adapter-protocol.md:406-413`;
`spec/03-canonicalisation.md:297-305`). The harness derives it from **position in its own
plan**, never from the message list:

```
step_id = "<turn_ordinal>.<call_ordinal>"
```

`turn_ordinal` is a counter the harness **seeds from a value the platform supplies on
`Start`**, re-supplied on every resume, and increments once per model request; it is never
derived from the length or content of the message list. `Start.turn_ordinal_seed` is the
count of **live** `cost.usage.recorded` events (`spec/04-events.md`, §Cost) for
`(tenant_id, run_id)` — events superseded by a rewind (`spec/04-events.md` §Rewind) are not
counted — with the resume replaying from the checkpoint's own position, so a turn recorded
after the checkpoint is re-derived rather than re-counted. The predicate is expressible over
the log **alone**: no component parses `resumed_payload`, which is opaque bytes the control
plane never reads (`spec/07-adapter-protocol.md:394-400`). A harness killed mid-turn
therefore re-derives the same `turn_ordinal` on resume — the failure
`spec/07-adapter-protocol.md:411` names in terms, where a counter reset on resume breaks
idempotency. The authority stays in the log
(`spec/02-consistency.md:130-137`) and the harness holds only a seeded counter (§10).
`call_ordinal` is the index of the call within that turn's `DeferredToolRequests`, in the
order the SDK returned them. A transformation of an in-memory list can move neither.

The field that carries the seed is `Start.turn_ordinal_seed`, **tag 9**
(`spec/07-adapter-protocol.md:50-66`; `spec/contracts/adapter.proto`), assigned 2026-08-30
alongside `run_token` at tag 8
([`13-adapter-sdk-subprocess.md`](13-adapter-sdk-subprocess.md) §3).

The platform's count is taken over **live** events only: an event superseded by a rewind
(epoch ≤ `to_epoch` with `seq >= from_seq`, `spec/04-events.md:210-232`) is not counted, so a
rewound run that re-reaches the same position re-derives the same `turn_ordinal`. Because
`effect_key` carries no epoch component (`spec/03-canonicalisation.md:297-305`), a rewound
run that re-reaches the same step with identical arguments derives the **same** key and the
effect is not re-executed — "Position, not time", at `:300-305`. Whether a rewind *should* be
able to re-execute a step it has already settled is `unknown — OQ`: the consequence is
mechanical, the intent is undecided.

Three calls in one turn get three distinct ids and three distinct rows. Spike 06 gate 10
shows that, but keyed by `tool_call_id` rather than by this derivation — replay determinism
for a re-run logical step is **NOT VERIFIED** there
(`spikes/06-tool-interception/RESULT.md:331`, simplification 2: "the same logical step
re-run gets a **different** key in this harness"). This is the property compaction must not
break, and why the derivation is specified here rather than left to implementers.

## 6. A delegated agent is a child Run, not a sub-agent

**NOT VERIFIED** (`spikes/06-tool-interception/RESULT.md:502-506`): nothing in spike 06
constructs a delegated agent, and nothing there rules it out as a bypass. The rules below
make the gap a checkable claim rather than an omission.

Delegation is already an effect kind (`effect_ledger.kind`, [`01-schema.md`](01-schema.md) §Effect ledger), so it
crosses the same boundary as any other effect: the harness emits a `ToolCall` for the
delegation, the platform ledgers it, and the platform creates the child. The harness never
constructs a second `Agent`, and it could not smuggle one in anyway — `toolsets=` is
refused at the door (§3).

The child inherits, and the inheritance is computed by the platform:

| What | Rule |
|---|---|
| `Principal` | a principal with `kind='agent'`, `on_behalf_of` = the parent run's acting principal, `delegation_depth` = parent + 1 ([`01-schema.md`](01-schema.md) §Identity) |
| depth | capped at 8 by the `CHECK`, so a runaway chain is refused by the database, not by policy code that might not run |
| bundle | the child run pins a definition digest **at creation**, exactly as any run does (`runs.pinned_definition_digest`, [`01-schema.md`](01-schema.md) §Run) |
| default | the parent's `pinned_definition_digest`, unless the delegation names another, which must resolve at delegation time or the effect settles `failed` |
| lease | **never inherited.** The child acquires its own `run_leases` row with its own fence token (`spec/02-consistency.md:378-399`) |
| approval | not inherited. An approval is bound to `(tenant_id, action_ref, run_id)` and cannot gate an effect of another run ([`01-schema.md`](01-schema.md) §Approval) |

The parent's delegation effect settles `succeeded` when the child run **exists**, with
`result_ref` = the child `run_id` ([`11-routines.md`](11-routines.md) §Delegation between
Runs is a ledgered effect). It does **not** wait for the child's terminal state: the effect
lease is five minutes (`spec/02-consistency.md:235`) and a child may take an hour, so waiting
would sweep a knowable outcome to `indeterminate`. The parent reads the child run for its
outcome, not the ledger.

## 7. Hooks write frames, never the ledger

**No hook writes to the effect ledger.** The harness has no ledger client and no database
credential; the only writer is the control plane, in the five phases of
`spec/02-consistency.md:174-306`. This is the whole reason the tool boundary survives the
process split: a hook that could write the ledger could settle an effect nobody dispatched.

In v0.1 Phoenix installs exactly one of these — `Instrumentation` (§3, §11). For the other
three the table is the constraint a capability must satisfy before it may be installed, not
a description of running code. All four are Pydantic AI capabilities
(`projects/pydantic-ai/teardown.md:210-213 @ b48ee38`), and the display-only `Output` bodies
row 1 permits are `text` and `thought` (`spec/07-adapter-protocol.md` `message Output`). **Who emits
the run's spans is settled**: the harness emits `phoenix.harness` and
`phoenix.tool_registration`, the installed `Instrumentation` emits `invoke_agent` and `chat`
([`19-telemetry.md`](19-telemetry.md) §Span inventory), and the `traceparent` comes from the
control plane, relayed by the driver ([`13-adapter-sdk-subprocess.md`](13-adapter-sdk-subprocess.md) §3) on `Start`
(`spec/07-adapter-protocol.md:55-58`).

| Seam | May do | May not |
|---|---|---|
| lifecycle `Hooks` | emit display-only `Output` bodies and OTel spans | emit `ToolCall`, or any ledger-shaped statement |
| `ProcessHistory` | transform the in-memory list (§4) | I/O, clock reads, dropping unsettled calls |
| `ProcessEventStream` | drive the streaming `Output` path | branch behaviour on whether a human was involved |
| `Instrumentation` — **installed** (§3) | emit spans under the traceparent carried on `Start`, with content and binary content off | start a new trace, or carry prompt, tool-argument or result content |
| `Instrumentation` / model-request boundary | emit one `Output{Usage}` per model request ([`18-cost.md`](18-cost.md)) | report money, or price anything |
| `WrapToolExecuteHandler` | **not installed** | — there is no local body to wrap |

The last row is the point. Every interception seam in the SDK is typed
(`projects/pydantic-ai/teardown.md:230-234 @ b48ee38`), and the tool-execution one is the
seam Phoenix deliberately leaves empty, because installing anything there would imply a body
to intercept. Nor can the harness tell a fast approval from no approval, and it must not try
(`spec/07-adapter-protocol.md` §Who executes a tool): approval state is a platform fact, and the harness
sees only `ToolResult` or `ToolDenied`.

## 8. Context assembly: symbolic closure first, search only nominates

The context of a model request is drawn from the **compiled knowledge package**
([`16-knowledge.md`](16-knowledge.md) §Compilation), which overlays the pinned bundle's
content nodes with the tenant and agent layers — so the universe is the package, not the
bundle: a tenant- or agent-layer file is reachable from no bundle edge, and a bundle path a
higher layer overrode is not in `manifest.json` at all. Two sets enter. The
**always-resident set** is every `system/**` path in `manifest.json`, in every model
request, whatever the closure says; a `system/` tree that does not fit ends the run
`End{FAILED, error_code = context_exhausted}` (§4 rule 5) rather than dropping files. The
**symbolic closure** is the set of package nodes reachable from the step's declared entry
nodes by declared edges. The **bytes** are the compiled knowledge package, materialised read-only into the run's container and
verified against `manifest.json` before the spawn ([`16-knowledge.md`](16-knowledge.md)
§Materialisation, [`15-sandbox.md`](15-sandbox.md) §6 Boundary 3 — storage). `Start.config` carries only
the **closure selection** — the entry nodes and the admitted digests, a projection of
`manifest.json` — and stays opaque to the control plane
(`spec/07-adapter-protocol.md:394-400`). **Amended 2026-08-30 (OQ-080): the term is owned by
[`16-knowledge.md`](16-knowledge.md), beside `manifest.json`**, which this document names
without defining — see [`16-knowledge.md`](16-knowledge.md) §Closure selection. The package does not travel in a frame: the ceiling is 4 MiB
(`spec/07-adapter-protocol.md` §Limits and backpressure) and spike 04's real bundle is 133 nodes. The harness
never resolves, fetches, or crawls at run time; it reads the mount and the selection.

Retrieval is allowed, and it is subordinate:

1. Search is a **tool**, so it is platform-executed and ledgered like any other
   (`effect_class = observation`, defined by `10-work-bundles.md` and named in
   [`10-work-bundles.md`](10-work-bundles.md) §The six nouns).
2. It returns **nominations** — node identifiers with their digests — not prose to splice
   into a prompt.
3. A nominated path enters context **only if it is listed in `manifest.json` with a
   matching digest AND is named by the closure selection or by the always-resident set**.
   Anything else is refused with `error_code = node_outside_closure`. Both conjuncts are
   the *package's*, not the bundle's, which is what lets a tenant-layer file and an
   overridden path be decided correctly. The manifest can carry this weight because it is
   the canonical projection of the package in full (`spec/03-canonicalisation.md:272`) and
   the materialised tree is verified against it in both directions before any process
   exists (`spec/05-state-machine.md:177`, resume step 4b); admitting an undeclared node
   would be discovery where ADR-0012 requires declaration.
4. A node whose verification status is absent grades `UNVERIFIED` and is never silently
   trusted or silently degraded to `false` — spike 04 found a real instance of this in the
   corpus (`spikes/04-work-bundle/RESULT.md`, finding 3; ADR-0012).

Rule 3 is what makes the assembly checkable, and why the bundle is compiled rather than
queried: the platform must be able to say, from the pin alone, what could have been in
context. Retrieval **filtering by authorisation**, before content reaches a model or an
embedding index, was `unknown — OQ`: spike 04 names it the largest untested area and this
document cannot close it by assertion. **Amended 2026-08-30 (OQ-103): owner named** —
[`16-knowledge.md`](16-knowledge.md) owes a Cedar `read`-on-classification amendment before
the analytics pack, not this document; see [`16-knowledge.md`](16-knowledge.md) §Retrieval
authorisation.

## 9. The checkpoint payload

The payload is the **SDK message history and nothing else**: `result.all_messages()` as the
harness already returns it (`harness.py:577 @ 42c4032`), plus the pending
`DeferredToolRequests` correlation ids needed to match results on resume
(`harness.py:592-594 @ 42c4032`). It is **opaque bytes** to the control plane, which stores
a reference and the format digest (`adapter.checkpointed{payload_ref,
payload_schema_digest}`, `spec/04-events.md:132`) and pins the format on the run
(`runs.pinned_payload_schema`, [`01-schema.md`](01-schema.md) §Run).

A `ToolCall` **ends the turn**: the SDK run returns on the deferred request (spike 06 gate 2,
`spikes/06-tool-interception/RESULT.md:165`; `harness.py:566-577 @ 42c4032`, where
`all_messages()` is captured at exactly that point), so the checkpoint is emitted **before**
the harness waits for `ToolResult|ToolDenied`. That is what makes checkpoint-and-kill during
`waiting_input` lossless (ADR-0016:76-77): there is no live turn to lose.

Rules:

1. **Only committed state is checkpointed** (non-negotiable 7). The harness emits
   `Output{Checkpoint}` when its turn ends; the **platform** persists it only when no
   `effect_ledger` row for this `(tenant_id, run_id)` is `claimed`
   (`spec/02-consistency.md:174-306`). The harness cannot evaluate that predicate (§10),
   and neither can the driver, which reads no ledger. The turn ends at the deferred
   request, so the checkpoint is emitted after the last `Output{ToolCall}` of a `step_id`
   and before the harness awaits any answer
   ([`13-adapter-sdk-subprocess.md`](13-adapter-sdk-subprocess.md) §4).
2. **Identifiers cross the boundary, objects do not.** No `Model` instance, no
   `cancellation_token`, no credential, no open handle of any kind appears in the payload —
   the SDK refuses those at its own durable boundaries and gives the reason
   (`projects/pydantic-ai/teardown.md:119-136 @ b48ee38`), and the model is named by the
   pinned definition, not carried.
3. `payload_schema_digest` is derived under `nfc+intjson/v1` from a declared payload-schema
   document naming the SDK label (`pydantic-ai-slim == 2.35.0`) and the envelope version.
   It does not name the twenty-two pinned file digests: spike 06 closed which bytes of a
   dependency ship as a release-pipeline concern, resolved by a hashed lockfile
   (`spikes/06-tool-interception/RESULT.md`, "The SDK pin stops here", OQ-063/064).
4. Any change to the message serialisation changes the digest, and a mismatch on resume is
   terminal `incompatible` before any harness code runs (non-negotiable 4;
   `spec/02-consistency.md:351-366`).

## 10. What the harness may keep in memory

**Nothing durable.** The rule, stated so it is checkable: *no fact may exist only in
harness memory.* Every value the harness holds is either recomputable from the pinned
definition and `Start.config`, or present in the last checkpoint, or already in the log.

| May hold, for the life of the process | Must never hold |
|---|---|
| the built `Agent`, its `ExternalToolset`, the tool declarations | any tool implementation |
| the current turn's message list and pending call ids | a cached ledger row, approval, or policy verdict |
| the closure selection from `Start.config`, and the read-only package mount | a credential, bearer token beyond `run_token`, or connection string |
| the current model request's `Usage` counts, until the frame is emitted | a running total of usage, cost, or money |
| the socket, `run_token`, `traceparent` | anything written outside the sandbox's own scratch |

Caching a policy verdict or an approval would make the harness a second authority on a
decision the platform owns; every call asks again, across the socket. The harness keys
nothing more narrowly than `(tenant_id, run_id)` — the declaration map is keyed
`(tenant_id, run_id, tool_name)` — so a process that somehow served two runs could still not
blend them. The non-durable convention is enforced one layer down: `temp:`-prefixed keys have
no row and the `CHECK` refuses them ([`01-schema.md`](01-schema.md) §Effect ledger).

## 11. Capability ordering, and the startup self-check

Composition order is load-bearing in this SDK and is documented as such
(`projects/pydantic-ai/teardown.md:217-222 @ b48ee38`). Phoenix therefore fixes the order,
declares it, and **asserts it before the first model request** rather than trusting it.

In v0.1 the set Phoenix installs has **one element**: `Instrumentation` (§3), installed at
`CapabilityPosition = 'outermost'` — one of the two legal values,
`Literal['outermost','innermost']` (`projects/pydantic-ai/teardown.md:58 @ b48ee38`) — so
that it observes every model request rather than a subset. The position is declared in the
definition body's `extensions` array as the `position` field of an `ExtensionBinding`, and
`extensions` is an array of objects **in declared order** included in the `agent_definition`
digest (`spec/03-canonicalisation.md:200-201`; the binding shape and the ordering rationale
at `:245-255`). A capability with no `extensions` entry has no declared position and is
refused at construction — an unstated position is how ordering becomes implicit.
`capabilities=` remains refused at the door, and no history processor runs (§4).

`Agent.__init__` auto-injects capabilities the harness never asked for — `ToolSearch` and
`PendingMessageDrainCapability` — and `ToolSearch` always wraps the boundary toolset in
`ToolSearchToolset`, which has a local execution branch
(`agent/__init__.py:630`, `capabilities/_tool_search.py:191-196`,
`toolsets/_tool_search.py:435-437 @ b48ee38`; `harness.py:539-564 @ 42c4032`). It fails
closed here only because no `ToolDefinition` Phoenix builds sets `defer_loading` — a fact
about the SDK's bytes, not about our code (spike 06 simplification 15, gate 13c).

So on `Start`, before any model request, the harness asserts: the toolset chain bottoms out
in its own `ExternalToolset`; the model was handed an **empty** native-tool list; the tool
names advertised equal the names in the pinned definition; and the constructed
`Instrumentation` reads `include_content = False` and `include_binary_content = False` — the
flags checked on the object, not trusted from the constructor call. Any failure ends the run
`End{FAILED, error_code = harness_boundary_unverified}` with nothing dispatched.

## Tests, with negative controls

| Invariant | Test | Negative control |
|---|---|---|
| No tool body is reachable from the harness | drive a full run and a resume; assert the process holds no callable for any declared tool | install one through a `FunctionToolset` ⇒ the body runs with **zero** ledger rows (spike 06's measured bypass) |
| The four SDK surfaces are refused by name | pass each of `native_tools`, `toolsets`, `tools`, `capabilities` at construction and at registration, including `=None` | drop the name check and keep the catch-all ⇒ `capabilities=` is admitted and delivers a provider-native tool |
| An unroutable tool cannot be declared | declare every `AbstractNativeTool` the SDK ships | allow registration ⇒ an effect path the ledger never sees |
| At most one history processor | construct with two processors named in the pinned definition | accept the second ⇒ two transformations compose in an order the digest does not pin |
| Compaction is declared `FALSE` | read `Describe`; assert `capabilities['compaction'].value = FALSE` | omit the declaration ⇒ it reads `UNKNOWN` and a caller may treat it as supported |
| `step_id` survives a history transformation | install a processor that deletes half the messages; compare effect keys before and after | derive `turn_ordinal` from `len(messages)` ⇒ the same logical step yields a different key |
| Context exhaustion fails loudly | drive past the window | truncate silently ⇒ work loss with no signal (ADR-0011) |
| No hook writes the ledger | construct each of the four capability types against the harness image and assert none can obtain a ledger client or a connection string | give a hook a ledger client ⇒ an effect settles with nothing dispatched |
| A delegation effect settles on the child's existence | delegate to a child that outlives the effect lease; assert the parent's row settled `succeeded` at creation | settle on the child's terminal state ⇒ the lease expires and a knowable outcome sweeps to `indeterminate` |
| `Instrumentation` carries no content | read the constructed capability; assert `include_content` and `include_binary_content` are `False` | leave the SDK defaults ⇒ prompts and tool arguments leave through the span path (`models/instrumented.py:76-77 @ b48ee38`) |
| One `Usage` body per model request | drive three model requests; count `Output{Usage}` frames | emit one per run ⇒ per-request attribution is unrecoverable and a pricing interval cannot be reconstructed |
| A delegated child gets its own lease and depth+1 | delegate twice; read `principals.delegation_depth` and `run_leases` | pass the parent's fence token to the child ⇒ two runs write under one lease |
| Depth is capped by the database | delegate nine deep | remove the `CHECK` ⇒ an unbounded chain |
| Only closure-selection nodes enter context | nominate a node absent from the selection, and one present in the selection but absent from `manifest.json` | admit nominations directly ⇒ retrieval becomes an unpinned second definition |
| A checkpoint carries no unsettled effect | leave one row `claimed`, emit `Output{Checkpoint}`; assert the **platform** refuses to persist it | allow it ⇒ a half-applied mutation is restored |
| A serialisation change is caught before resume | change one field of the payload schema; resume against a run pinned to the old digest | derive the digest from the SDK version string alone ⇒ a patch release that changes `all_messages()` resumes silently against an incompatible payload |
| No fact exists only in harness memory | SIGKILL the harness mid-turn; resume from the last checkpoint and assert the run completes with identical effect keys | seed `turn_ordinal` from the harness's own message list instead of `Start.turn_ordinal_seed` ⇒ the resumed run derives a different key for the replayed step |
| The harness caches no platform decision | drive two calls of one tool through one process; assert each crosses the socket | cache the policy verdict across calls ⇒ the second call acts on a stale decision |
| The harness blends no two runs | drive two runs through one process; assert the declaration map is keyed `(tenant_id, run_id, tool_name)` | key it by `tool_name` alone ⇒ one run's declaration answers the other's |
| The payload carries identifiers, not objects | serialise a checkpoint; assert no `Model` and no handle | embed the model object ⇒ the payload cannot cross the boundary |
| The startup self-check is real | patch the toolset chain so `ExternalToolset` is not the leaf | skip the assertion ⇒ the run proceeds against a wrapper with a local branch |

## What this does not guarantee

- **Nested agents are unverified** (`spikes/06-tool-interception/RESULT.md:502-506`). §6
  states the inheritance rules; no gate proves a delegated agent cannot be constructed in
  the harness process with a toolset the platform did not supply.
- **Compaction is unverified** (`:507-511`). §4 declares it `FALSE`, a refusal rather than a
  solution: a long-running agent will need one.
- **Replay determinism of `step_id` is unverified.** Gate 10 keys its rows by
  `tool_call_id`, and a re-run logical step gets a different key there (`:331`,
  simplification 2). Nothing exercises §5's `<turn_ordinal>.<call_ordinal>` derivation.
- **The `payload_schema_digest` derivation is asserted, not verified.** It excludes the
  twenty-two pinned file digests by design (`RESULT.md`, "The SDK pin stops here",
  OQ-063/064); nothing proves the `incompatible` guard fires on a patch-level change.
- **"No egress path of its own" is the sandbox's claim, not this document's.** §1 states the
  expectation; the egress guard is unspecified ([`15-sandbox.md`](15-sandbox.md) §5).
- **The sandbox scratch boundary is not defined here.** §10 forbids the harness to write
  outside the sandbox's own scratch; what that scratch is, and what survives a
  checkpoint-and-kill, is the sandbox document's ([`15-sandbox.md`](15-sandbox.md) §6, storage-boundary).
- **Import reachability of a tool body is unconstrained here.** §3 verifies that no
  executable body reaches the SDK; that the image ships no platform tool package is a
  packaging rule §11's self-check does not test.
- **The boundary is proven against a cooperating caller only.** Spike 06's scoping
  (simplification 13) is closed *by construction* in `sdk_subprocess`, not *by test*: no gate
  drives the Go driver against a hostile Python harness in one container.
- **Retrieval authorisation is untested** (spike 04). §8 constrains what may enter context;
  it does not constrain who may see a node's content.
- **`Start.config` is unvalidated by the control plane, by design.** A malformed closure
  selection is a harness-side failure the control plane cannot distinguish from a harness
  bug. The package bytes are different: those the driver verifies against `manifest.json`
  before the spawn ([`16-knowledge.md`](16-knowledge.md) §Materialisation).
- **Cost and OTel semantics are not here.** Both belong to other documents
  ([`18-cost.md`](18-cost.md) and [`19-telemetry.md`](19-telemetry.md), landed 2026-08-30).
