# v0.1 architecture and design
<!-- status: final -->

The output of a 13-project comparative teardown. Every decision below is traceable
to evidence: `decisions/` holds 16 ADRs (15 Accepted, 1 Proposed), `projects/*/teardown.md` the
source readings, and `synthesis/` the cross-project analysis.

This document is the handoff. It states what we are building, why each piece is
shaped the way it is, and — equally important — what we are deliberately not
building.

> **The implementation specification is in [`spec/`](spec/)** — ten documents
> settling schemas, consistency, canonicalisation, events, transition authorization,
> the API, the adapter protocol, conformance, and the decided design questions. This document is the *why*; the spec
> is the *exactly what*.
>
> **Two scopes, named separately.** This document describes the **target architecture**; the
> **v0.1 shipment** is a subset, and what is in it, deferred from it, or never built is stated
> once in [`synthesis/v01-boundary.md`](synthesis/v01-boundary.md) — asserted against
> `synthesis/scope.yaml` by `make check` — with the ambiguities adjudicated in
> [`synthesis/scope-reconciliation.md`](synthesis/scope-reconciliation.md).
> *(**Amended 2026-08-27:** this note restated the deferral list, so the same scope change had
> to be edited here and in the boundary. Nothing is dropped — every sentence it carried is in
> the boundary, dated.)*

---

## 1. The thesis

**A SaaS platform an enterprise buys, where we build and operate the agents against the
customer's own knowledge, connectors and data.**

The customer onboards knowledge as **signed bundles** (OKF v0.2 profile) plus connectors to
their systems. **They never bring agent code.** We build and run the agents on a thin
internal harness on **Pydantic AI** (amended 2026-08-27: a two-SDK plan over the Claude Agent
SDK and OpenAI Agents SDK is superseded — one harness, five reasons in ADR-0004).
Deployment is a multi-tenant SaaS control plane plus a **per-customer VPC data plane**; only
metadata, schedules and approvals cross that boundary.

> **This superseded an earlier thesis on 2026-08-27** — one describing a neutral control plane for third-party
> people's agents" — on 2026-08-27. The architecture survives the change almost intact,
> which is the useful part: see `synthesis/scope-reconciliation.md` §7 for what moved and
> what did not.

Four commitments distinguish it, and each exists because 13 projects showed nobody does it:

1. **Resumption is version-safe.** A run records a content digest of the agent definition it
   started on and refuses to resume across a change.
2. **Side effects are the platform's problem.** Phoenix records **intent before every
   effect** and keys it by the effect's **position in the run**, so after a crash it knows
   which effects are settled and which are uncertain — and hands the uncertain ones to a
   human rather than retrying blind. No framework in the study does this. A double refund and
   a missed refund are different failures, and guessing turns one into the other.
3. **Capability is declared, verified, and separated from behaviour.**
4. **Authority is attributable.** Every policy decision and every approval names the
   principal behind it.

Everything else is assembled from prior art, deliberately.

## 2. What the evidence settled

Six questions I expected to argue about turned out to have answers.

| Question | Answer | Basis |
|---|---|---|
| Where does knowledge live? | Files, git-backed. Not a memory service. | 7 of 13 projects, including every one with a choice |
| Is A2A/ACP the internal model? | No — an edge adapter outside a richer internal model. | 5 independent confirmations |
| Do we own orchestration? | No. Separable, better solved by MAF/Temporal-class engines. | ADR-0004; Pydantic AI treats durable engines as first-class compatibility targets |
| Do we own compensation? | No. Zero positive answers in 13 projects. | `L8`: 12 negative, 1 unknown |
| How is tenancy enforced? | `tenant_id` in every composite primary **and** foreign key. | Omnigent + ADK (PK), Agent Control (FK) |
| Is agent identity needed for durability? | No — it is needed for *delegation, policy and audit*. | Two projects deliver durable execution with no agent identity |

That last one is the study's most useful correction. I began assuming identity was a
durability requirement; AX and Cloudflare disprove it, and AgentCore shows what
identity is actually for — being nameable as a Cedar `principal`.

## 3. Architecture

```text
                 NORTHBOUND  /v1 (resources) + event stream + GET /adapters
                 admin credentials ≠ agent credentials
                                    │
┌───────────────────────────────────▼─────────────────────────────────────┐
│ CONTROL PLANE                        single writer per Run              │
│                                                                          │
│  Scheduler ──► Run Engine ◄── Policy (Cedar: deny│steer│observe)         │
│  durable       folds the log   traced, aggregable, org binds agent       │
│  claim         derives state                                             │
│                pins on resume  Approval Service (durable, with approver) │
│                     │                                                    │
│  Identity      Effect Ledger   Channel Hub      Conformance Bench        │
│  Principal +   idempotent      envelopes on a   offline: every commit    │
│  Credential    BEFORE the      WAL, depth caps  live: gated, DRIFT fails │
│  (exchanger/   effect          audit ⊃ delivery                          │
│   refresher)                                                             │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ SOUTHBOUND frame boundary
                                │ Run(stream) + Describe()
                                │ in-process: a function call
                                │
                            Adapter
                        (sdk:pydantic-ai)
                                │
                                ▼
                       SANDBOX  process │ egress │ storage

   external:  Temporal / DBOS / Prefect   (durable workflow, sagas, compensation)
```

> **Transport, precisely.** The southbound boundary is a **logical frame boundary**, not a
> network hop. For the shipped `sdk_in_process` mode it **collapses to a function call**
> (`spec/07`): the frames are real, the transport is not. gRPC is the **deferred remote**
> transport, retained as a design commitment for the first out-of-process adapter and marked
> not-shipped in `spec/07` §Transport.
>
> **Diagram amended 2026-08-27.** It showed three adapter boxes — `(ACP)`, `(in-proc)` and
> `(native TUI)`. Only one ships: **one internal harness on Pydantic AI**, registered as
> `sdk:pydantic-ai`, in process. The adapter boundary is retained so a **second** SDK can be
> added later without touching the control plane; ACP and terminal-scraping are superseded as
> shipped paths.

Full component reasoning in
[`synthesis/reference-architecture.md`](synthesis/reference-architecture.md).

## 4. The four differentiators, specified

### 4.1 Version-safe resumption

**The problem, verified rather than assumed.** LangGraph resumes a checkpoint whose
graph has changed by returning `[]` — no error, silent work loss. I confirmed this
by running it. Across 13 projects nobody prevents it for agents: Google AX pins
adapter identity but has no versions, Omnigent has the only monotonic agent version
but never pins it to a run, ADK versions its storage and telemetry schemas but not
its agents.

**The mechanism**, taken from MAF and applied where nobody applies it:

```text
run.pin = {
  definition_digest          sha256 of the canonicalised definition
                             (structure + instructions + tools + capabilities)
  adapter_identity           which adapter
  adapter_digest             sha256 of its declared contract
  checkpoint_schema_version  OUR envelope format — the one real version
}
```

Rules: canonicalise before hashing (sorted keys, tight separators) so the digest is
reproducible; compare every field on resume; a mismatch is `INCOMPATIBLE` with an
error naming which field changed. Declared versions exist for humans and are never
compared — a counter nobody increments provides nothing.

**The tradeoff, accepted deliberately.** A digest is brittle in the safe direction: a
comment-only edit invalidates checkpoints. A false incompatibility costs a restart; a
false compatibility costs the LangGraph bug. If an escape hatch becomes necessary it
is an explicit operator assertion recorded on the run, never a loosened default.

### 4.2 The effect ledger

```text
effect_ledger
  run_id, idempotency_key UNIQUE, kind, status, attempt,
  request_digest, result_ref, error, error_code, timestamps
```

Five rules: the key is deterministic from `(run_id, logical_step_path,
request_digest)`; the row is written **before** the effect; a duplicate returns the
recorded outcome and reports that it was a replay; conflicting identity inputs raise
rather than guess; and a `claimed` row past its lease is **`INDETERMINATE`, not
retryable** — it surfaces to a human, because retrying it is the double-charge bug
this exists to prevent.

Two key kinds, because two projects use different ones: explicit keys for
externally-triggered effects (Cloudflare), and causation keys for reply-shaped work
(AG2 — the reply *is* the dedupe record). The guard is checked before any ownership
or turn test.

### 4.3 Capability and Extension

Five projects use one word for two concepts. Splitting them was the study's most
useful conceptual correction.

- **`Capability`** — declared metadata about what a thing *can do*. Tri-state
  (`true | false | unknown`), classified by enforcement position, carrying a
  confidence (`verified | asserted`), published on the API, and verified by a
  two-layer bench: **offline every commit** (declaration completeness — costs
  nothing, so the table cannot rot) and **live gated** (probes; DRIFT fails the
  build). `unknown` never degrades to `false`.
- **`Extension`** — installed behaviour. Declared position and ordering, typed wrap
  points, and serializability enforced as a project rule so it survives a durability
  boundary.

### 4.4 Attributable authority

`Principal` and `Credential` are separate subsystems, because four projects have
exactly one half: ADK has excellent credentials and no principals, HumanLayer has
durable decisions and no approver, Agent Control governs behaviour and cannot express
authority, and only AgentCore has both.

The agent has a **workload identity of its own** and obtains tokens as itself, for a
federated JWT, or for a named user — with `ON_BEHALF_OF_TOKEN_EXCHANGE` as a named
flow rather than a flag. Delegation depth is incremented by the authority and capped
by policy. Credentials are obtained by an `Exchanger` and renewed by a **separate**
`Refresher`, and never enter the sandbox: the egress proxy swaps a host-bound
single-use placeholder for the real secret.

Every `Approval` names `decided_by → Principal`. That field is what makes the
difference between a durable decision and an auditable one.

## 5. The ideal developer journey

Written as the acceptance criteria for v0.1 DX. Each step names the project that
taught the lesson.

### Minute 0 — install

```bash
pip install ourplatform
ourplatform dev            # starts control plane + SQLite + UI, no Docker required
```

**One command, no infrastructure.** ADK's discipline: every pluggable interface ships
an in-memory or local implementation, so the development path and the production path
are *the same code with a different injection* — not a mock, not a separate mode. Four
projects confirm this is what makes a platform testable (ADK's `InMemory*` for six
subsystems, LangGraph's `InMemorySaver`, AX's `eventlogtest`, Pydantic AI's
`TestModel`).

### Minute 2 — run an agent we built, on the customer's knowledge

```bash
phoenix run --agent revenue-analyst --bundle sonyliv-analytics \
            "why did VOD ad coverage drop on Android last Tuesday?"
```

> **Amended 2026-08-27.** This step previously read "run someone else's agent" and invoked
> an ACP adapter with a third-party agent (both superseded 2026-08-27). Both are gone: we build and operate the agents, and
> the customer supplies the **bundle**, not the agent. See
> [`synthesis/scope-reconciliation.md`](synthesis/scope-reconciliation.md) §7.

Four concepts to get here: agent, run, adapter, sandbox. HumanLayer and Agent Control
both reach a working state in under five concepts; that is the bar.

### Minute 5 — see what happened

```bash
ourplatform runs                    # includes WAITING_INPUT as an indexed state
ourplatform show <run-id>           # transcript with approval state inline
ourplatform trace <run-id>          # one trace id, client → control plane → adapter
```

Approval state is denormalised onto the tool-call event (HumanLayer), so reading the
transcript shows what was gated without a join. The trace assertion is a *test* in our
CI, not a dependency in our lockfile — Omnigent depends on six OTel packages and its
own audit found dead propagation code.

### Minute 10 — add a policy, safely

```yaml
# policy.cedar + binding
decision: observe        # ← shadow mode first, always
```

```bash
ourplatform policy add ./policy.cedar --mode observe
ourplatform policy stats <policy-id>     # what it WOULD have done, aggregated
ourplatform policy promote <policy-id>   # observe → steer → deny
```

`observe` is a first-class decision, not a flag (Agent Control), and observe-mode
evaluations are **exempt from short-circuit cancellation** so the shadow sample is not
biased away from denied traffic. Aggregation matters as much as evaluation: knowing a
candidate policy fired 4,102 times is actionable, knowing it fired once is not.

### Minute 20 — bind a new SDK (us, not the customer)

Customers never write adapters. We do, once per SDK, and the adapter boundary exists so
the SDK underneath stays swappable (ADR-0004). The contract is the gRPC service in
[`spec/07`](spec/07-adapter-protocol.md) — **two RPCs**, not a five-method Python class:

```protobuf
service Adapter {
  rpc Run(stream ControlFrame) returns (stream AdapterFrame);
  rpc Describe(DescribeRequest) returns (AdapterContract);
}
```

`integration_mode = sdk_in_process` is the only mode shipped. An in-process SDK adapter
still speaks these frames: `ToolCall` comes **out**, `ToolResult`/`ToolDenied` go **in**,
and the SDK's own tool executor is **disabled**. A capability declaration accompanies it:

```
streaming    = VERIFIED(true)     # a probe proves it
interrupt    = ASSERTED(true)     # declared, unproven -- and marked so
compaction   = UNKNOWN            # no claim; never read as false
```

**Two RPCs** (`Run`, `Describe`), and durability lives in the control plane — putting
`checkpoint`/`restore` in the adapter guarantees a lowest-common-denominator problem when
not every SDK can checkpoint. Config is opaque bytes the control plane refuses to parse, and
the stream contract states its terminator exactly.

> **Amended 2026-08-27.** This read "Four methods (AX)"; AX's contract is the upstream
> precedent, not our shape (superseded 2026-08-27) — `spec/07` specifies two RPCs carrying typed frames.
> The reason for the terminator precision also changed: it is no longer "so a third party can
> implement an adapter without reading our source", because we write every adapter. It is so
> *we* cannot quietly depend on undocumented stream behaviour when the next SDK lands.

```bash
ourplatform bench my-adapter     # offline: is the declaration complete?
ourplatform bench my-adapter --live   # probes; DRIFT fails
```

### Minute 30 — deploy

```bash
ourplatform deploy --tenant acme
```

Single-tenant is tenant `0` — the same code path with one value (Omnigent), not a
separate mode that drifts.

### Every error, in three parts

The rule taken from Pydantic AI and ADK, and applied to every refusal we emit:
**what was refused, the mechanism that makes it impossible, and the correct
alternative.**

```
Cannot resume run r_8f2a: definition digest changed
  (a1b2c3… → d4e5f6…). The agent's tools or instructions were edited after this
  run checkpointed. Start a new run, or restore the prior definition from
  version 4.
```

Not:

```
IncompatibleCheckpointError
```

Our errors are read by an agent before a human sees them, so an error that names the
retry parameter is worth more than one that names the exception class.

## 6. What we deliberately do not build

| Boundary | Evidence |
|---|---|
| Compensation / saga engine | Zero positive answers in 13 projects — including the one whose whole job is control and the one whose whole job is orchestration. Saga compensation belongs to the workflow engine. |
| Workflow / DAG engine | MAF and Pydantic AI both show orchestration is separable and better solved elsewhere |
| Model gateway / provider abstraction | Explicit anti-goal; MAF ships 35 provider packages, which is the surface we should not own |
| **Public** authoring framework, or customer-supplied agent code | We own an internal harness on Pydantic AI (amended 2026-08-27, superseded "over the vendor SDKs"); customers bring knowledge, connectors and data, not agent code. **Amended 2026-08-27**, superseding a row that justified this by neutrality toward third-party agents. **That lesson no longer binds (superseded 2026-08-27):** its cost was losing the ability to run a third party's agents, which is no longer a requirement. What we still refuse is *publishing* an authoring framework for customers to write against. (`v01-boundary.md:91`) |
| Bespoke policy DSL, trace format, or message protocol | Cedar, OTel, AG2's envelope. Every project that invented one got a worse version and no ecosystem |

## 7. What v0.1 does not guarantee

Stating these is the point. From Cloudflare's `channels.md`, which deleted its own
durable messaging host because it "never delivered exactly-once ingress… so the
guarantee it appeared to offer was not one it could keep":

> **A guarantee you cannot keep is worse than an honest limitation.**

- **Not exactly-once effects.** At-most-once where the target cooperates; *detected
  indeterminacy* where it does not.
- **Not exactly-once delivery.** At-least-once with causation dedupe.
- **Not automatic compatibility across an agent edit.** Brittle in the safe
  direction, by choice.
- **Not a cost cap.** Measurement in v0.1; enforcement deferred.
- **Not protection from deliberate cross-tenant impersonation.** Composite keys
  prevent accidents; preventing intent requires the principal model in force at every
  entry point.

## 7a. Implementation language — Go for the control plane

**Decided 2026-08-27.** The control plane is written in **Go**.

The spec was already written for a non-Python implementer, which is why this costs nothing
to adopt now:

- `spec/03-canonicalisation.md` specifies the profile in terms of **UTF-8 byte order** and an
  integers-only number domain, precisely so it does not depend on one language's `json`
  module. Go's `sort.Slice` over `[]byte` and `encoding/json` satisfy it directly.
- The cross-language check already exists: **spike 02 ships a Node oracle**
  (`spikes/02-definition-pin/canon_ref.mjs`) written from the normative text, and `make spec`
  compares fixture ↔ Python ↔ JavaScript. A Go implementation becomes the third
  independent implementation and reuses the same 21 accept / 9 reject vectors unchanged.
- The Postgres statements in `spec/02` are plain SQL with no ORM assumptions, and spike 03
  ran them against a real server.

**The spikes are not being rewritten.** They are executable evidence for design claims, not
production code, and rewriting them in Go would cost the falsification value they already
earned. Python remains the language of the spikes and the verification tooling.

## 8. Sequencing

Three tiers, ordered by dependency — Tier 1 the spine, Tier 2 the platform, Tier 3 integrate.
The items in each tier, and the trigger that would pull a deferred one forward, are in
[`synthesis/v01-boundary.md`](synthesis/v01-boundary.md), which `make check` asserts against
`synthesis/scope.yaml`.

*(**Amended 2026-08-27:** the three tier lists were restated here and each had to be corrected
by hand when the boundary moved. They are a pointer now. Nothing is dropped — every item and
every dated amendment this section carried is in the boundary.)*

## 9. The riskiest decisions

Recorded so they are revisited against reality rather than rediscovered.

1. **Integrating `ag2.network`** is the largest single dependency and the only
   precedent for messaging. Its file WAL and index pruning give its dedupe guarantee a
   retention horizon we must replace. **~~Mitigation: spike the storage swap~~ — done 2026-08-26** (`spikes/01-ag2-storage`), so this mitigation is superseded; the residual risk is maintaining the compatibility layer across AG2 releases.**
2. **`Task` as a distinct resource** rests on one precedent, and Omnigent applies it
   only to scheduled work. If interactive runs never need it, it is speculative
   generality — the mistake ADR-0003 nearly made in the other direction.
3. **Content pins with no escape hatch.** MAF appears to have none, and we are
   copying that.
4. **Cedar as a hard dependency.** It buys the analysis story and bounds our policy
   expressiveness to Cedar's.

## 10. How to challenge this document

Every claim is traceable, so disagreement should be cheap to resolve:

- A decision → `decisions/ADR-00NN-*.md`, including its amendment history and a
  13-row evidence log.
- A claim about a project → `projects/<slug>/teardown.md` with `file:line @ commit`,
  and `sources.md` recording what was verified by execution versus by reading.
- A cross-project count → `synthesis/capability-matrix.md`, generated from
  `facts.yaml`, never hand-edited.
- An open question → `open-questions.md` (39 entries, resolutions inline).

**One caution the study earned the hard way.** Three of six Phase 3 passes found
substantially more than recon predicted, each because a cheap signal was trusted over
the source. The worst instance: after seven projects with no agent-to-agent messaging
I had drafted an ADR rewrite abandoning it, and the eighth implements it better than
my strawman. **A convergence across N projects is evidence about what is common, not
proof about what is possible.** If you intend to overturn something here, read the
source rather than the tally — and if the claim concerns tenancy, uniqueness or
referential integrity, read the schema rather than the API.
