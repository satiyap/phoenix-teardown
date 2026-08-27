# Reference architecture — v0.1
<!-- status: final -->
<!-- status: frozen 2026-08-27 -->
Frozen as of 2026-08-26 (Phase 5). Scope is governed by [`v01-boundary.md`](v01-boundary.md) / [`scope.yaml`](scope.yaml); where this document disagrees, the boundary wins.

Derived from 13 teardowns, 16 ADRs (15 Accepted, 1 Proposed) and the canonical domain model. Each
component names the evidence that shaped it. Where a component exists because
*nobody* does it, that is stated.

---

## Shape

```text
                    ┌───────────────────────────────────────────┐
   clients          │  NORTHBOUND API  (resource-oriented, /v1)  │
   CLI / web /      │  + event stream (SSE/WS)                   │
   SDK / Slack      │  + capability catalogue  GET /adapters     │
                    └────────────────────┬──────────────────────┘
                                         │  admin credentials ≠ agent credentials
┌────────────────────────────────────────▼──────────────────────────────────┐
│ CONTROL PLANE                            single writer per Run            │
│                                                                            │
│  ┌────────────┐  ┌──────────────┐  ┌────────────┐  ┌──────────────────┐  │
│  │ Scheduler  │  │ Run Engine   │  │ Policy     │  │ Approval Service │  │
│  │ rrule + tz │→ │ folds the log│← │ Cedar      │  │ durable, with an │  │
│  │ DURABLE    │  │ derives state│  │ deny/steer │  │ approver         │  │
│  │ CLAIM      │  │ pins on      │  │ /observe   │  │ reconciles on    │  │
│  │            │  │ resume       │  │ traced +   │  │ restart          │  │
│  └────────────┘  └──────┬───────┘  │ aggregable │  └──────────────────┘  │
│                         │          └────────────┘                        │
│  ┌────────────┐  ┌──────▼───────┐  ┌────────────┐  ┌──────────────────┐  │
│  │ Identity   │  │ Effect       │  │ Channel Hub│  │ Conformance Bench│  │
│  │ Principal  │  │ Ledger       │  │ envelopes  │  │ offline: every    │  │
│  │ +Credential│  │ idempotency  │  │ on a WAL   │  │   commit          │  │
│  │ exchanger/ │  │ BEFORE the   │  │ depth caps │  │ live: gated       │  │
│  │ refresher  │  │ effect       │  │ audit ⊃    │  │ DRIFT = failure   │  │
│  └────────────┘  └──────────────┘  │ delivery   │  └──────────────────┘  │
│                                    └────────────┘                        │
└────────────────────────────────┬──────────────────────────────────────────┘
                                 │  SOUTHBOUND (gRPC bidi stream)
                                 │  Run(stream) + Describe()
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
   ┌─────────┐            ┌─────────┐             ┌─────────┐
   │ Adapter │            │ Adapter │             │ Adapter │
   │ ACP     │            │ in-proc │             │ native  │
   │ (Claude,│            │ (our    │             │ TUI     │
   │ SDK)    │            │  SDK)   │             │(reserved)│
   └────┬────┘            └────┬────┘             └────┬────┘
        └──────────────────────┼───────────────────────┘
                               ▼
                    ┌──────────────────────┐
                    │ SANDBOX  3 boundaries│
                    │  process/filesystem  │
                    │  egress (SSRF guard  │
                    │    + cred proxy)     │
                    │  storage (LLM cannot │
                    │    reach control DB) │
                    └──────────────────────┘

   external, integrated not built:  Temporal / DBOS / Prefect  (durable workflow,
                                    compensation, sagas)
```

---

## Components

### Northbound API
Resource-oriented `/v1` over the domain model, plus an event stream and a
**published capability catalogue** so callers can degrade deliberately rather than
discover limits by failure (Omnigent's `GET /v1/harnesses`).

**Admin and agent credentials are separate** — the only project that does this is
Agent Control, and it is the whole point of a control plane: an agent subject to
policy must not be able to edit policy.

### Run Engine — single writer, log-derived state
One writer per Run. State is **derived by folding an append-only log**, never
stored in a parallel table, which eliminates log/state divergence as a class of bug
(Google AX: `ResumptionState` recomputes both state and adapter identity).

Single-writer is enforced by the database, not a lock service: composite primary key
with the sequence computed inside the insert transaction, so concurrent appends
collide and one rolls back (AX, `eventlog/sql.go:38-66`).

**On resume the pin is compared and a mismatch is `INCOMPATIBLE`.** The pin is a
content digest, not a declared counter (MAF's bytecode hash), because a counter
nobody increments provides nothing — Omnigent has the study's only monotonic agent
version and still cannot detect a mid-flight upgrade.

Recovery of interrupted work follows Cloudflare: hung detection by an
`execution_started_at` cutoff, orphan detection by outer-joining the ledger against
live run rows, and **exponential backoff when a recovery scan makes no forward
progress** so a poison hook cannot wake the system indefinitely.

### Effect Ledger — BUILD
`idempotency_key UNIQUE` on a durable ledger, **written before the effect is
attempted**, with the key deterministic from `(run_id, logical_step_path,
request_digest)`. A duplicate returns the recorded outcome and reports that it was a
replay (Cloudflare's `accepted: false`). Conflicting identity inputs raise rather
than guess.

Two key kinds, because two projects use different ones: explicit keys for
externally-triggered effects (Cloudflare) and **causation keys for reply-shaped
work** (AG2 — the reply *is* the dedupe record, so no key needs generating). The
guard is checked **before** any ownership or turn test.

A `claimed` row older than a lease threshold is `INDETERMINATE`, not retryable, and
must surface. That is the uncomfortable honest part: if we crashed after dispatching
an effect but before recording its outcome, we do not know whether it happened, and
retrying is the double-charge bug this exists to prevent.

### Policy — Cedar, three-way, aggregable
Cedar rather than a bespoke DSL, for the same reason we take OTel over a proprietary
trace format: a formal semantics and an existing analysis toolchain mean "is policy
set B more permissive than A" is a decidable question (AgentCore).

Decisions are `deny | steer | observe` (Agent Control):
- **`steer`** returns machine-readable remediation and is invalid without it — a
  policy that repairs rather than refuses, which converts most would-be approvals
  into self-service corrections.
- **`observe`** is shadow mode: evaluated on live traffic alongside enforced
  controls, recorded, never affecting the outcome. **Exempt from short-circuit
  cancellation**, or the shadow sample is biased away from denied traffic — exactly
  the cases a candidate policy most needs.

Fail-closed is decided by **position in the enforcement path**: closed where the
decision is the last line of defence, open where the harm is already incurred
(Omnigent's `PHASE_TOOL_RESULT` reasoning). Decisions name the deciding policies
(Omnigent), refusals are as observable as successes (AG2), and both are aggregable
into stats and timeseries (Agent Control).

**Organisation policy binds agent policy** and an agent cannot weaken it
(MAF/Purview).

### Identity — Principal and Credential, separately
Two subsystems, because four projects have exactly one half.

**Principal**: who is acting, with `kind: human | agent | service | remote` so
humans and agents are the same type with a discriminator (AG2's `PassportKind`).
The agent has a **workload identity of its own** and can obtain a token as itself,
for a federated JWT, or for a named user, with `ON_BEHALF_OF_TOKEN_EXCHANGE` as a
named flow (AgentCore). Delegation depth is bounded by policy (AG2).

**Credential**: obtained by an `Exchanger`, kept alive by a **separate**
`Refresher` — different failure modes, different interfaces (ADK). And it never
enters the sandbox: the egress proxy swaps a host-bound single-use placeholder for
the real secret and rejects a placeholder presented to the wrong host (Omnigent).

### Approval Service
A durable resource, not a Run status: correlated both ways to the gated action,
status-constrained, partial-indexed on pending, rationale on approve *and* deny,
`ErrAlreadyDecided` returning the existing decision on retry, reconciled on restart
keyed by run and non-fatal on failure (HumanLayer). **Plus `decided_by → Principal`,
which no project has.**

Dangerous overrides carry a TTL and emit an event on expiry, so a bypass cannot
become permanent by neglect (HumanLayer's `dangerously_skip_permissions_expires_at`).

### Channel Hub
AG2's envelope on a per-channel append-only WAL, with `audience` addressing,
at-least-once delivery, causation dedupe, `depth` incremented by the authority and
capped by rule, per-envelope TTLs, and inbox backpressure. **The log records every
accepted envelope in full regardless of audience** — audit scope must exceed
delivery scope.

Channel *protocols* (conversation, discussion, consulting, workflow) declare turn
expectations the hub enforces, so "who speaks next" is not emergent from prompts.

### Adapters — two RPCs, southbound gRPC
`Run(stream ControlFrame) returns (stream AdapterFrame)` and `Describe()`. *(Amended 2026-08-27: this read `start → {run, send, cancel, close}`; AX's four-method contract is the upstream precedent, not our shape.)* Durability lives in the control plane, **not**
in the adapter: putting `checkpoint`/`restore` in the adapter interface guarantees a
lowest-common-denominator problem, since not every harness can checkpoint (AX +
ADR-0012).

Adapter config is **opaque bytes** the control plane refuses to parse (AX). The
stream contract specifies its terminator exactly — "zero or more output frames
terminated by exactly one end frame" — which is what makes **a second adapter implementable
from the contract alone** (amended 2026-08-27: this said "a third-party adapter", and no third
party writes adapters for us).

Transport is gRPC bidirectional streaming, so a remote adapter needs no
co-location. The integration-mode taxonomy comes from Omnigent: `SDK_IN_PROCESS`,
`CLI_SUBPROCESS`, `ACP_SUBPROCESS`, `NATIVE_TUI`, `NATIVE_SERVER` — of which only `SDK_IN_PROCESS` ships (amended 2026-08-27; the rest are retained so the column never needs a migration).

> **Amended 2026-08-27.** Only **`SDK_IN_PROCESS` is shipped** — the enum is retained so the
> column never needs a migration, with a `CHECK` enforcing the restriction
> (`spec/01-schema.md`). The sentence removed here argued that scraping a terminal UI is "how
> you bring an agent with no integration surface under one policy layer"; that was a
> justification for a foreign-agent path (superseded 2026-08-27), and we build every agent ourselves. ACP is no
> longer a shipped path at all. See `synthesis/scope-reconciliation.md` §7.

### Conformance Bench
Two layers (Omnigent's actual CI split):
- **Offline, every commit**: every registered adapter has a complete capability
  declaration, every declared capability has a probe, and declaration coverage is
  reported. Costs nothing, so the table cannot silently rot.
- **Live, gated**: probes run against real adapters and **DRIFT fails the build**.

Plus continuous observed statistics from production terminal events (AG2), because
a bench answers "does it work" and observation answers "how often, how fast". Both.

### Sandbox — three boundaries
Process/filesystem via a pluggable provider **that ships a local implementation**
(ADK's discipline). Egress via a mandatory guard: private ranges, link-local, CGNAT,
Teredo-obfuscated forms, and an enumerated cloud-credential blocklist that **no
configuration option can disable** (Pydantic AI). Storage: the LLM must have no SQL
path to the control plane's database (Cloudflare) — enforcement must be structural,
not conventional.

### Observability
OTel with GenAI semantic conventions, a declared semconv version with one
deprecation window, stability tiers separated **by module** so an import path
reveals stability (ADK), a declared vendor namespace, and **a test asserting one
trace id spans client → control plane → adapter** — because Omnigent depends on six
OTel packages and its own audit found dead propagation code.

---

## Deliberately external

| Concern | Why not us | Evidence |
|---|---|---|
| Durable workflow, sagas, **compensation** | Zero positive answers in 13 projects; saga compensation is the workflow engine's job | `L8` 12/13 negative + 1 unknown; Pydantic AI's Temporal/DBOS/Prefect integration |
| Graph/DAG orchestration | Separable and better solved elsewhere | MAF's Pregel engine; Pydantic AI's delegation |
| Model gateway / provider abstraction | Explicit anti-goal; commodity | PLAN.md |
| **Public** authoring framework, or customer-supplied agent code (amended 2026-08-27) | Thin internal harness over the vendor SDKs; customers bring knowledge, connectors and data. **Amended 2026-08-27** — the Cloudflare objection (ambient durability costs you the ability to run others' agents) no longer binds, because running others' agents is no longer a requirement | ADR-0004 (amended); `scope-reconciliation.md` §7 |

## The four things nobody does

Everything above is assembled from prior art except these, which are the
differentiators and the risk. **These are target-architecture items** — two ship in
v0.1, one ships partially, one is deferred with a trigger
([`scope-reconciliation.md`](scope-reconciliation.md) §1):

1. **Content-derived pinning applied to the agent definition.** MAF proves the
   mechanism on workflows; nobody applies it to agents.
2. **A platform-owned effect ledger.** Two partial precedents; ADK explicitly
   delegates idempotency to tool authors.
3. **`Capability` + `Extension` unified with a two-layer bench.** Omnigent has the
   bench, Pydantic AI has the composition, nobody has both.
4. **Agent-level revocation and an approver identity on approvals.** Thirteen
   projects; best available is credential-level revocation and an anonymous
   decision.
