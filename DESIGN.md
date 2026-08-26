# v0.1 architecture and design
<!-- status: final -->

The output of a 13-project comparative teardown. Every decision below is traceable
to evidence: `decisions/` holds the 15 accepted ADRs, `projects/*/teardown.md` the
source readings, and `synthesis/` the cross-project analysis.

This document is the handoff. It states what we are building, why each piece is
shaped the way it is, and — equally important — what we are deliberately not
building.

---

## 1. The thesis

**A control plane that runs other people's agents durably, under policy, with
attributable authority.**

Four commitments distinguish it, and each exists because 13 projects showed nobody
does it:

1. **Resumption is version-safe.** A run records a content digest of the agent
   definition it started on and refuses to resume across a change.
2. **Side effects are the platform's problem.** An effect ledger, written before the
   effect, keyed deterministically.
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
                                │ SOUTHBOUND gRPC bidi
                                │ start → {run, send, cancel, close}
                    ┌───────────┼───────────┐
                 Adapter     Adapter     Adapter
                 (ACP)       (in-proc)   (native TUI)
                    └───────────┼───────────┘
                                ▼
                       SANDBOX  process │ egress │ storage

   external:  Temporal / DBOS / Prefect   (durable workflow, sagas, compensation)
```

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
rather than guess; and a `pending` row past its lease is **`INDETERMINATE`, not
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

### Minute 2 — run someone else's agent

```bash
ourplatform run --adapter acp --agent claude-code "fix the failing test"
```

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

### Minute 20 — write an adapter

```python
class MyAdapter(Adapter):
    async def start(self, run_ctx, config: bytes) -> Execution: ...
    # Execution: run(handler), send(inputs), cancel(reason), close()

    capabilities = Capabilities(
        streaming=Verified(True),      # a probe proves it
        interrupt=Asserted(True),      # declared, unproven — and marked so
        compaction=Unknown(),          # no claim; never read as False
    )
```

Four methods (AX), because durability lives in the control plane — putting
`checkpoint`/`restore` in the adapter guarantees a lowest-common-denominator problem
when not every harness can checkpoint. Config is opaque bytes the control plane
refuses to parse. The stream contract states its terminator exactly, which is what
makes a third-party adapter implementable without reading our source.

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
| Agent-authoring framework | We adapt agents. Cloudflare's alternative — write the agent against our runtime — buys ambient durability at the cost of never running someone else's |
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

## 8. Sequencing

Three tiers, ordered by dependency. Detail and deferral triggers in
[`synthesis/v01-boundary.md`](synthesis/v01-boundary.md).

**Tier 1 — the spine.** Tenant/Principal/Credential → agent identity and versioned
definition → run engine (single writer, log-derived state) → adapter contract with
one ACP adapter → version-and-pin on resume → effect ledger.

**Tier 2 — the platform.** Cedar policy with three-way decisions → `Approval` with
`decided_by` → three-boundary sandbox → capability declarations with the offline bench
→ knowledge and four state scopes → OTel with an asserted propagation test.

**Tier 3 — integrate.** `ag2.network` for messaging, `genai-prices` for cost.

## 9. The riskiest decisions

Recorded so they are revisited against reality rather than rediscovered.

1. **Integrating `ag2.network`** is the largest single dependency and the only
   precedent for messaging. Its file WAL and index pruning give its dedupe guarantee a
   retention horizon we must replace. **Spike the storage swap before committing.**
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
