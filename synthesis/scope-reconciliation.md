# Scope reconciliation
<!-- status: final -->

Six ambiguities found in external review of the Phase 5/6 output. All six are real.
This file is the adjudication; the affected documents are corrected to match it.

The root cause of five of them is one word doing two jobs: **"v0.1" meant both the
target architecture and the first shipment**, and I used it interchangeably.

---

## 1. Target architecture ≠ v0.1 shipment

**The contradiction.** `README.md` says we BUILD agent revocation and a two-layer
conformance bench. `v01-boundary.md` defers agent revocation and the live bench
layer. Both are accurate about different things and the documents never said which.

**Resolution — two distinct scopes, named differently from here on.**

| | **Target architecture** | **v0.1 shipment** |
|---|---|---|
| Question it answers | What is this platform, when finished? | What do we build first? |
| Agent revocation | in scope — it is one of the four BUILDs | **deferred** (trigger: first multi-tenant deployment) |
| Conformance bench | two layers, offline + live | **offline layer only** |
| Recall (memory service) | in scope | deferred (Knowledge + State suffice) |
| Messaging | in scope | **contingent** — see §4 |
| Task resource | in the domain model | **not shipped** — see §2 |

The four BUILD items in the README are **target-architecture** claims: they are the
things no project does, so they are ours to invent *eventually*. Two of the four
(pinning, effect ledger) are in the v0.1 shipment; two (revocation, live bench) are
deferred with named triggers.

**Correction applied:** the README's "BUILD — four things nobody does" is relabelled
"Target architecture — four things nobody does", with the v0.1 subset marked.

## 2. Does v0.1 contain a `Task` resource? No.

> **REVERSED 2026-08-27 — the deferral trigger is met.** §7 below repositions Phoenix as a
> SaaS platform where we build and operate the agents, and **routines (schedule *or* trigger →
> Run) are the unit customers buy**. The trigger recorded in `v01-boundary.md` was "scheduled
> or recurring agent work becoming a product requirement"; it is now a product requirement,
> not a hypothesis. `Task`/routines move to **Tier 2**.
>
> The *shape* below is unchanged and is what makes the reversal cheap: a routine **creates**
> Runs and never becomes one, so `Run.task_id` is a nullable FK — additive exactly as
> planned. Everything in this section about why `Task` is not a Run still holds; only the
> question "does v0.1 ship it" flipped. Schema owed by spec 10 or 11
> (`spec/00-overview.md` "Not yet specified").


**The contradiction.** The domain model and ADR-0002 retain `Task → Run`. The
boundary defers "`Task` as a universal spine". `DESIGN.md` calls it speculative
generality. And `Task` appears in **none** of the three v0.1 tiers — verified by
grep, zero mentions.

**Resolution.** **v0.1 creates `Run`s directly. There is no `Task` table.**

- A `Run` carries its own intent fields (prompt, trigger, pin, budget) and does not
  require a parent.
- `Task` enters the schema when scheduled or recurring work becomes a requirement —
  the trigger already recorded in the boundary. At that point `Run.task_id` becomes
  nullable-FK, which is an additive migration.
- ADR-0002 stands as a **target-architecture** decision. Its evidence is one project
  (Omnigent), applying it only to scheduled work, which is exactly the strength of
  evidence that justifies "model it, don't ship it".

This is the ADR-0003 lesson applied in the opposite direction. There I nearly cut a
subsystem with strong precedent; here I nearly shipped one with weak precedent. The
asymmetry is deliberate: **absence across many projects is not proof of
impossibility, but presence in one project is not proof of necessity either.**

## 3. "Integrate Agent Control" — resolved to PORT, not RUN

**The contradiction, and the worst of the six.** `build-reuse-map.md` lists Agent
Control under INTEGRATE ("the whole control plane") *and* lists its individual
patterns under PORT in the same document. Those are materially different
architectures.

**Resolution: PORT the patterns, do not run the service.**

The deciding evidence is in the teardown itself. Agent Control has:

- **its own PostgreSQL persistence** — controls, bindings, execution events;
- **its own tenancy model** (`namespace_key`), which would sit beside ours;
- **no `Principal` model at all** — it governs behaviour and cannot express
  authority.

Running it as a dependency would mean two policy stores, two tenancy schemes, and a
policy engine that structurally cannot reference the principal our ADR-0007 requires
on every decision. That is not integration, it is a second control plane.

**What we take instead** (all recorded as ADOPT_AS_STANDARD, which is the correct
verdict):

- `deny | steer | observe` as the decision vocabulary
- `steer` invalid without remediation guidance, enforced at validation
- recursive condition trees with shape validation
- separate agent vs admin credentials
- `tenant_id` in composite **foreign** keys
- policy binding as a queryable resource with an `enabled` flag
- stats and timeseries over decisions
- observe-mode exempt from short-circuit cancellation (their bug, our fix)

**Correction applied:** Agent Control moves from INTEGRATE to PORT in
`build-reuse-map.md`, leaving three genuine INTEGRATE candidates — `ag2.network`,
Cedar, `genai-prices`.

## 4. `ag2.network` is contingent, not approved

> **RESOLVED — spike 01 has run** (`spikes/01-ag2-storage/RESULT.md`). The verdict split by
> route: a *clean* `ag2.network` integration **FAILED** (fixing OQ-024 would require changing
> public dedupe semantics), while AG2 **behind an owned compatibility layer PASSED** — 480 of
> AG2's own tests through our `SqlKnowledgeStore`, plus 12 gate tests using only public
> composition. We own dedupe entirely; `find_envelope_by_causation` is never used for
> correctness. The "CONTINGENT" label below is therefore historical.


**The contradiction.** Messaging sits in v0.1 Tier 3 as INTEGRATE, while both
`DESIGN.md` and the boundary require a storage spike *before committing*. No spike
artefact exists (`spikes/` does not exist).

**Resolution.** `ag2.network` is **conditionally approved, gated on a spike that has
not been run.** Its v0.1 status is `CONTINGENT`, not `IN`.

The gate, stated as a pass/fail test:

> Replace AG2's file-based WAL with our append-only log, keeping the `Envelope`
> schema and hub contract intact, and demonstrate that causation dedupe survives
> channel termination — i.e. that `find_envelope_by_causation` does not degrade into
> "cannot tell" once terminal-channel pruning clears the index (OQ-024).

**If it passes:** integrate, and messaging is in v0.1.
**If it fails:** port the `Envelope` schema only (it is a data shape, and the best
one found in 13 projects) and implement the hub against our own log. That is a larger
build, and it is the reason this must be settled before Tier 1 rather than during it.

## 5. What "complete" means for validation — fixed in tooling

**The finding.** `make check` exited 2 while the README claimed completion and
presented that command as the verification step.

**Root cause.** `--strict` was written as a pre-phase gate against *unexamined*
probes and could not distinguish those from *deliberately tracked* unknowns. Its
warning text — "each needs an open-questions.md entry" — implied missing work when the
entries already existed.

**Resolution, already implemented** (`c32350a`): the validator now parses
`open-questions.md` for `(slug, probe)` pairs and splits unknowns in two.

- **Untracked unknown** → warning, and failure under `--strict`. Indistinguishable
  from a probe nobody examined, so it must fail.
- **Tracked unknown** → informational note. A legitimate finding.

Verified both directions: injecting `omnigent/A7` fails with "unknown and UNTRACKED
(A7)"; the three real ones pass and `make check` exits 0.

The three tracked unknowns and why they are legitimate:

| Probe | Reason |
|---|---|
| `langgraph/C8` | LangGraph Platform's lease/heartbeat is closed source |
| `letta/C5` | No documented delivery semantics for tool-call replay after crash |
| `openhands/C5` | Same, for tool execution replay |

**The completion claim stands, with its scope stated:** 13 of 14 projects read (the
14th does not exist), 25/25 exit criteria answered, 15/15 ADRs accepted, three
unknowns tracked with reasons. The claim was never "everything is known" — it was
"everything is examined and the gaps are named".

## 6. Next deliverable is a specification, not implementation

**The finding, and I agree without reservation.** The architecture is sufficient for
*direction* and insufficient for *independent implementation*. What is missing:

| Gap | Why it blocks a second implementer |
|---|---|
| Concrete resource schemas | `domain-model.md` gives fields, not types, nullability, indexes or constraints |
| Transition authorization | The Run state machine shows edges, not who may trigger each |
| API / IDL | "resource-oriented `/v1`" is a shape, not a contract |
| Event types | The log is central and its entry schema is unspecified |
| Database choice + consistency boundaries | Single-writer is asserted; the isolation level and transaction boundaries are not |
| Adapter stream protocol | "zero or more frames terminated by exactly one end" is quoted from AX, not specified for us |

**Resolution.** The next deliverable is an **implementation specification**, not
code. Roughly: SQL DDL with constraints, the OpenAPI document, the adapter `.proto`,
the event-type registry, and the state-transition authorization table.

Two spikes gate it because they can invalidate the spec before it is written:

1. **The AG2 storage swap** (§4) — decides whether messaging is integrate or build.
2. **The pin, end to end** — digest a definition, checkpoint, edit, resume, confirm
   `INCOMPATIBLE`. This is the headline differentiator and should be provable in a
   day.

The Cedar analysis question is already answered and does not need a spike: I tested
`cedarpy` and its validator catches a typo'd attribute statically (`riskLevel` vs
`risk` — `validation_passed=False`), but **equivalence and permissiveness comparison
are not exposed in the Python binding.** They exist in Cedar's Rust/Lean tooling. So
ADR-0013's *static* shadow half is a Rust-boundary dependency, and v0.1 gets
*empirical* shadow via `observe` mode. That correction belongs in ADR-0013 and
OQ-033.

---

## Summary of corrections

| # | Ambiguity | Resolution |
|---|---|---|
| 1 | "v0.1" meant two things | Split into **target architecture** and **v0.1 shipment**, tabulated |
| 2 | `Task` in v0.1? | **No.** Runs are created directly; `Task` is target-architecture, additive later |
| 3 | Integrate Agent Control? | **PORT the patterns, do not run the service** — it has no `Principal` model |
| 4 | `ag2.network` approved? | **CONTINGENT** on a storage spike with a stated pass/fail test |
| 5 | Strict validation vs tracked unknowns | Fixed in tooling; tracked unknowns are informational, untracked ones fail |
| 6 | Next deliverable | **Implementation specification**, gated by two spikes |

---

## 7. SaaS, we run the agents (2026-08-27)

A business-shape decision, arriving after the spec had survived three review rounds.
**Phoenix is a SaaS platform an enterprise buys.** The customer onboards knowledge as signed
bundles (OKF v0.2 profile) plus connectors to their systems; **we build and operate the
agents** on one internal harness on **Pydantic AI** (amended 2026-08-27: the first draft named a
multi-SDK plan; superseded by the harness decision in §7a). Customers bring knowledge, connectors and data — **never agent code**.
Deployment is a multi-tenant SaaS control plane plus a **per-customer VPC data plane**, with
only metadata, schedules and approvals crossing the boundary.

The reason to record this rather than silently edit: the previous thesis — "a
framework-neutral control plane that runs other people's agents" — was the *stated
justification* for several decisions. Those decisions mostly survive, but **their reasons
changed**, and a reason that no longer holds is how a design rots.

### The nine consequences, before and after

| # | Consequence | Before | After | Files |
|---|---|---|---|---|
| 1 | **Adapters narrow to SDK in-process** | `integration_mode` had five live modes; "ship with ACP so we adapt Claude Code and Codex on day one" | Enum retained (no migration later), but a `CHECK` restricts it to `sdk_in_process`; the other four are **reserved, not shipped**. One adapter, `sdk:pydantic-ai` (amended 2026-08-27: a two-SDK plan was superseded by §7a) | `spec/01-schema.md` (`integration_mode_shipped`), `spec/00-overview.md:45`, `v01-boundary.md` Tier 1 #4, `DESIGN.md:342` |
| 2 | **Tool execution stays platform-owned** | Normative, with "an adapter cannot bring its own tools" recorded as an accepted **cost** | Unchanged in substance. New normative subsection: an in-process SDK adapter MUST route every tool call through the same typed `ToolCall → ledger → ToolResult/ToolDenied` boundary, and **the SDK is never given an executable body** — tools are declared through `ExternalToolset` *(corrected 2026-08-27 by spike 06; this row first said "the SDK's native tool executor is disabled", which described a mechanism we do not use)*. The restriction is now **the design**, not a cost — there is no third party asking to bring tools | `spec/07` §"In-process SDK adapters route tool calls the same way"; `spec/08` rows **30a/30b** |
| 3 | **"No agent-authoring framework" softens** | Never #4: "We adapt agents; we do not compete with the frameworks that write them" | "No **public** authoring framework and no bring-your-own agent; we own an internal harness on Pydantic AI." Dated note explains the **Cloudflare lesson no longer binds** — ambient durability costs you the ability to run others' agents, which was fatal only while that was a requirement. ADR-0004 recorded **`amends`, not `challenges`**: the adapter boundary is kept so SDKs stay swappable | `v01-boundary.md` Never #4, `DESIGN.md` §1, `ADR-0004` |
| 4 | **Conformance bench Tier 2 → Tier 3** | Offline bench in Tier 2, justified as catching an untrusted third-party declaration | Purpose narrows to **SDK-version drift**: an SDK bump silently falsifies a declaration. Real but slower, so it ships after the spine. ADR-0012 **stands** (`amends`): declarations still beat discovery, `UNKNOWN` still never degrades to `false` | `v01-boundary.md` Tier 3 #15, `spec/08` purpose note, `ADR-0012` |
| 5 | **`Task` un-deferred** | §2 above: "**No `Task` in v0.1**"; boundary listed it under Deferred with intent | **Tier 2.** Routines (schedule *or* trigger → Run) are the unit customers buy, and the OKF bundle already carries a 10:00 IST daily cadence and a weekly roll-up *as prose* for want of a resource. Shape unchanged: a routine creates Runs, never becomes one; `Run.task_id` nullable FK. ADR-0002 recorded **`confirms`** | §2 (dated reversal), `v01-boundary.md` Tier 2 #16 + Deferred table, `ADR-0002`, `spec/00-overview.md` |
| 6 | **Work-bundle spec owed** | `spikes/04-work-bundle/RESULT.md` referenced `10-work-bundles.md`, which does not exist — a dangling promise | Listed in "Not yet specified" with its required contents: `WorkBundle`, `Resource`, `Action`, `ActionReceipt`, `Verifier`, `effect_class`; **bundle-supplied** type→roles table; verifier pinned by a **different publisher** (spike 04 finding 1); freshness is **evidence**, not bundle state (finding 2); `indeterminate` keeps `external_operation_id` and inspection is a **separate Action** (finding 4). **Not written in this pass** | `spec/00-overview.md` |
| 7 | **AX/SubstrATE is a provider, not the control plane** | Google AX read as architecture only; no decision on where sandbox lifecycle sits | **ADR-0016 raised as Proposed** (not Accepted): placement, suspension, resumption and eviction policy are **control-plane** concerns; process/filesystem/network isolation is a **provider's**. Cites AX's mechanism (actors suspended between turns, resumed on any worker) *and* its anti-pattern (no authN, no principal, no tenancy, no policy; `REFERENCE_ONLY`). **Spike 05 defined** and blocking | `decisions/ADR-0016-*.md`, `open-questions.md` (OQ-019 now blocking, OQ-042 added) |
| 8 | **Go for the control plane** | Unstated; spikes are Python | Recorded as a decision. `spec/03` was already written for a non-Python implementer (UTF-8 byte order, integers-only domain), and the **Node oracle in spike 02** is the existing cross-language check — a Go implementation becomes the third independent one and reuses the 21 accept / 9 reject vectors. **Spikes are not rewritten**: they are executable evidence, not production code | `DESIGN.md` §7a |
| 9 | **Pitch wording** | README: "framework-neutral control plane for persistent AI agents… MCP, A2A and ACP are interoperability protocols". Differentiator #2 phrased as a mechanism | SaaS framing in both. Four differentiators kept; **#2 reworded to the buyer's question** — after a crash, no framework can say whether the effect happened; Phoenix records intent before every effect, keys it by position in the run, and surfaces uncertain cases to a human. The "six of six" style evidence stays in the technical sections | `README.md` §Success condition, `DESIGN.md` §1 |

### Also fixed: eleven defects found in the same review

| Defect | Fix |
|---|---|
| `spec/06-api.md:16` "answer its own approvals" | Agents **do not decide approvals** in v0.1 (§7a D-A; an interim "assigned approver" wording was retracted 2026-08-27). Test **29a**: agent token on `/decide` ⇒ 403 |
| `spec/07-adapter-protocol.md:379` test row | Close-without-`End` ⇒ `indeterminate` was unconditional; now split on whether an effect is unsettled, matching rule 5 |
| `spec/02-consistency.md:78` | Still claimed the seq-race loser "gets a unique violation and rolls back". It **blocks** (spike 03 finding 1); `statement_timeout` now **mandatory** on the append path, `57014` retryable |
| `spec/04-events.md:21,26` | Entry shape showed `trace_id` and omitted `epoch`; now `traceparent` (full W3C value) and `epoch`, both stated as assigned inside the insert |
| `spec/01-schema.md` missing index | `approvals_pending_one` partial unique index added — spike 03's `schema.sql:145` had it and the spec did not |
| `channel_leases` defined twice | Kept in `01` (with history table); `02` now references it instead of redefining it with different columns |
| `DESIGN.md:140`, `v01-boundary.md:97` | "`pending` row" → "`claimed` row" |
| `DESIGN.md:20` | "messaging is contingent on a spike that has not been run" → spike 01 has run; `Task` note updated |
| README counts | 16 ADRs (15 Accepted + 1 Proposed), 10 spec docs, gate assertions and invariant rows **derived** from the `RESULT.md` headlines and `spec/08`, asserted by `make check` (the hand-counted 124 was wrong twice) |
| `DESIGN.md:254` adapter shape | Five-method Python class replaced with the `spec/07` **two-RPC** gRPC service, scoped to `sdk_in_process` |
| `spec/00-overview.md:31` said `09-decisions.md` holds "Six open design questions" | It holds **seven** — the multi-party approval refusal was added as §7 in the same pass that wrote the row, and the index was not updated with it |

### What did NOT change, and why that matters

The repositioning touched the *justifications* far more than the *mechanisms*:

- the schema, consistency model, canonicalisation profile, event log, epoch semantics,
  effect lifecycle and state machine are **untouched**;
- ADR-0004's adapter boundary **survives** with a different job;
- ADR-0012's tri-state capability model **survives** with a narrower purpose;
- **no ADR was reversed**, and the one raised is Proposed rather than Accepted.

A design that only survives its original business case is not a design. This one moved from
"run other people's agents" to "run our own agents on their knowledge" and lost nothing
structural — the strongest evidence yet that the mechanisms were chosen for the right
reasons.

### Corrections to the corrections

Two things in §1–§6 are now stale and are marked at their source rather than quietly edited:
§2's "**No `Task` in v0.1**" is reversed above, and §4's "`ag2.network` CONTINGENT" was
resolved by spike 01. Both carry dated notes in place.

### 7a. Decisions made while propagating it (2026-08-27)

Propagation took eight further commits and four verifier rounds. The transcripts of those
rounds (before/after tables, verbatim `make check` output, redo narratives — ~850 lines) were
removed from this file on 2026-08-27; `git log abfb206..0447506` holds them. What survives here
is what was *decided*, because those are the things a reader needs and cannot recover from
prose diffs.

| Decision | Position | Why | Where it lives |
|---|---|---|---|
| **Harness** | One internal harness on **Pydantic AI**. Not the vendor SDKs (two harnesses), not LangGraph (its checkpointer is a second state authority, and its silent resume across a changed graph is the failure ADR-0011 exists to prevent). Adapter boundary kept so a second SDK can be added | model-agnostic, no durable state of its own, tools are registered functions so the ledger boundary is a decorator — *corrected 2026-08-27 by spike 06: the boundary is a **toolset**, not a decorator. Phoenix declares tools through `ExternalToolset`, whose `call_tool` raises unconditionally (`toolsets/external.py:44 @ b48ee38`) while `get_tools` still advertises them to the model (`:36`), so the SDK is never given an executable body and `@agent.tool` is not used at all. The `FunctionToolset` control shows the decorator **is** the bypass. Declaring the tool is necessary but not sufficient: the harness must also expose no `Agent`, or a caller can `override(native_tools=...)` past it.* | ADR-0004 amendment; `v01-boundary.md` Tier 1; `spec/07` |
| **Unmediated tools** | **Unsupported in v0.1.** An adapter that cannot disable native execution for a tool must not register it. Spike 06 (OQ-043) decides admission; any future admission is "provider-reported use", needs a durable provider receipt for anything stronger, and carries egress/confidentiality constraints | a narrow permission was granted in `793828b` and **retracted** in `3026e38`: "every use is recorded" is a guarantee the platform cannot keep across a vendor boundary, and its only test inserted the row by hand | `spec/07` one dated paragraph; `spec/08` rows 30e–g removed |
| **D-A · Approvals** | Agent credentials **cannot decide approvals**. `POST /v1/approvals/{id}/decide` with an agent token ⇒ `403 wrong_credential_class`; deciders are `human`/`admin` principals, enforced by a schema CHECK on `decided_by`'s kind | an interim "assigned approver" wording invented an assignee model with no column, and §09 7 defers the self-approval rule | `spec/06`; `spec/01`; `spec/08` 29a (HTTP) and 29b (DB) |
| **D-B · Remote transport** | mTLS / Unix-socket / run-scoped bearer in `spec/07` are **retained as a design commitment, not shipped** | the reasoning came from AX's unauthenticated harness runtime and must not be rediscovered | `spec/07` dated heading |
| **Verification rule 7** | A verifier must not destructively mutate state it does not *uniquely own*; rollback preferred | a by-database DDL check dropped shared tables; an overbroad first wording ("no destructive statement at all") was corrected the same day | `spikes/VERIFICATION-RULES.md` |
| **Scope source of truth** | `synthesis/scope.yaml` holds tier/deferred/never/owed-spec lists and headline counts; `make check` asserts the boundary, README and `spec/00` tables match it | every scope claim lived in ~8 documents and each round missed one | `tools/validate_spec.py` `check_scope_source_of_truth` |
| **Counts** | Spike assertions and invariant rows are **derived** from `RESULT.md` headlines and `spec/08`, never hand-written | 124 → 115 → 116 → 117 by hand, each wrong | `check_counts` |
| **Phase-5 artefacts** | `reference-architecture.md` and `exit-criteria.md` frozen 2026-08-26; where they disagree with the boundary, the boundary wins. They **stay in** the superseded-claims scan | a freeze is a statement about editing, not a reason to stop checking | top of each file |
| **Superseded-claims gate** | Sentence-level, case-insensitive, repo-wide incl. contracts and diagram blocks; a sentence is exempt only with a date **and** `superseded\|amended\|reversed\|retracted`; quoting is not an exemption; self-test mutations in `tools/test_validate_spec.py` | it reported "ok" while five documents contradicted the change | `tools/superseded-patterns.txt` |

### 7b. Closure (2026-08-27)

Commits `59da08b` → `0447506` (eleven, on top of `abfb206`). `make check` exits 0 with
Postgres up and every check executed. **The SaaS repositioning is closed; further findings
are filed as OQs, not redone.**

Residue filed: OQ-042 (read SubstrATE source; blocks ADR-0016), OQ-043 (Pydantic AI tool
interception; spike 06), OQ-044 (multi-party approval as a buyer requirement), OQ-045–047
(spike-03 docstring, `make check` reproducibility, Postgres-gate isolation), OQ-048/049
(resolved same day), OQ-050–054 (patterns-file rationale, gate stderr heuristic, two counts
still hand-compared, what "frozen" means to a tool, whether `scope.yaml` asserts the harness).
