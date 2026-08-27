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
agents** on a thin internal harness over the vendor SDKs (Claude Agent SDK, LangGraph, OpenAI
Agents SDK). Customers bring knowledge, connectors and data — **never agent code**.
Deployment is a multi-tenant SaaS control plane plus a **per-customer VPC data plane**, with
only metadata, schedules and approvals crossing the boundary.

The reason to record this rather than silently edit: the previous thesis — "a
framework-neutral control plane that runs other people's agents" — was the *stated
justification* for several decisions. Those decisions mostly survive, but **their reasons
changed**, and a reason that no longer holds is how a design rots.

### The nine consequences, before and after

| # | Consequence | Before | After | Files |
|---|---|---|---|---|
| 1 | **Adapters narrow to SDK in-process** | `integration_mode` had five live modes; "ship with ACP so we adapt Claude Code and Codex on day one" | Enum retained (no migration later), but a `CHECK` restricts it to `sdk_in_process`; the other four are **reserved, not shipped**. First adapter is the **Claude Agent SDK**, second the OpenAI Agents SDK | `spec/01-schema.md` (`integration_mode_shipped`), `spec/00-overview.md:45`, `v01-boundary.md` Tier 1 #4, `DESIGN.md:342` |
| 2 | **Tool execution stays platform-owned** | Normative, with "an adapter cannot bring its own tools" recorded as an accepted **cost** | Unchanged in substance. New normative subsection: an in-process SDK adapter MUST route every tool call through the same typed `ToolCall → ledger → ToolResult/ToolDenied` boundary, and **the SDK's native tool executor is disabled**. The restriction is now **the design**, not a cost — there is no third party asking to bring tools | `spec/07` §"In-process SDK adapters route tool calls the same way"; `spec/08` rows **30a/30b** |
| 3 | **"No agent-authoring framework" softens** | Never #4: "We adapt agents; we do not compete with the frameworks that write them" | "No **public** authoring framework and no bring-your-own agent; we own a thin internal harness over the SDKs." Dated note explains the **Cloudflare lesson no longer binds** — ambient durability costs you the ability to run others' agents, which was fatal only while that was a requirement. ADR-0004 recorded **`amends`, not `challenges`**: the adapter boundary is kept so SDKs stay swappable | `v01-boundary.md` Never #4, `DESIGN.md` §1, `ADR-0004` |
| 4 | **Conformance bench Tier 2 → Tier 3** | Offline bench in Tier 2, justified as catching an untrusted third-party declaration | Purpose narrows to **SDK-version drift**: an SDK bump silently falsifies a declaration. Real but slower, so it ships after the spine. ADR-0012 **stands** (`amends`): declarations still beat discovery, `UNKNOWN` still never degrades to `false` | `v01-boundary.md` Tier 3 #15, `spec/08` purpose note, `ADR-0012` |
| 5 | **`Task` un-deferred** | §2 above: "**No `Task` in v0.1**"; boundary listed it under Deferred with intent | **Tier 2.** Routines (schedule *or* trigger → Run) are the unit customers buy, and the OKF bundle already carries a 10:00 IST daily cadence and a weekly roll-up *as prose* for want of a resource. Shape unchanged: a routine creates Runs, never becomes one; `Run.task_id` nullable FK. ADR-0002 recorded **`confirms`** | §2 (dated reversal), `v01-boundary.md` Tier 2 #16 + Deferred table, `ADR-0002`, `spec/00-overview.md` |
| 6 | **Work-bundle spec owed** | `spikes/04-work-bundle/RESULT.md` referenced `10-work-bundles.md`, which does not exist — a dangling promise | Listed in "Not yet specified" with its required contents: `WorkBundle`, `Resource`, `Action`, `ActionReceipt`, `Verifier`, `effect_class`; **bundle-supplied** type→roles table; verifier pinned by a **different publisher** (spike 04 finding 1); freshness is **evidence**, not bundle state (finding 2); `indeterminate` keeps `external_operation_id` and inspection is a **separate Action** (finding 4). **Not written in this pass** | `spec/00-overview.md` |
| 7 | **AX/SubstrATE is a provider, not the control plane** | Google AX read as architecture only; no decision on where sandbox lifecycle sits | **ADR-0016 raised as Proposed** (not Accepted): placement, suspension, resumption and eviction policy are **control-plane** concerns; process/filesystem/network isolation is a **provider's**. Cites AX's mechanism (actors suspended between turns, resumed on any worker) *and* its anti-pattern (no authN, no principal, no tenancy, no policy; `REFERENCE_ONLY`). **Spike 05 defined** and blocking | `decisions/ADR-0016-*.md`, `open-questions.md` (OQ-019 now blocking, OQ-042 added) |
| 8 | **Go for the control plane** | Unstated; spikes are Python | Recorded as a decision. `spec/03` was already written for a non-Python implementer (UTF-8 byte order, integers-only domain), and the **Node oracle in spike 02** is the existing cross-language check — a Go implementation becomes the third independent one and reuses the 21 accept / 9 reject vectors. **Spikes are not rewritten**: they are executable evidence, not production code | `DESIGN.md` §7a |
| 9 | **Pitch wording** | README: "framework-neutral control plane for persistent AI agents… MCP, A2A and ACP are interoperability protocols". Differentiator #2 phrased as a mechanism | SaaS framing in both. Four differentiators kept; **#2 reworded to the buyer's question** — after a crash, no framework can say whether the effect happened; Phoenix records intent before every effect, keys it by position in the run, and surfaces uncertain cases to a human. The "six of six" style evidence stays in the technical sections | `README.md` §Success condition, `DESIGN.md` §1 |

### Also fixed: eleven defects found in the same review

| Defect | Fix |
|---|---|
| `spec/06-api.md:16` "answer its own approvals" | Now "decide approvals **assigned to it as approver**", with an explicit prohibition on deciding an approval gating its own run's effect. Test **29a** added |
| `spec/07-adapter-protocol.md:379` test row | Close-without-`End` ⇒ `indeterminate` was unconditional; now split on whether an effect is unsettled, matching rule 5 |
| `spec/02-consistency.md:78` | Still claimed the seq-race loser "gets a unique violation and rolls back". It **blocks** (spike 03 finding 1); `statement_timeout` now **mandatory** on the append path, `57014` retryable |
| `spec/04-events.md:21,26` | Entry shape showed `trace_id` and omitted `epoch`; now `traceparent` (full W3C value) and `epoch`, both stated as assigned inside the insert |
| `spec/01-schema.md` missing index | `approvals_pending_one` partial unique index added — spike 03's `schema.sql:145` had it and the spec did not |
| `channel_leases` defined twice | Kept in `01` (with history table); `02` now references it instead of redefining it with different columns |
| `DESIGN.md:140`, `v01-boundary.md:97` | "`pending` row" → "`claimed` row" |
| `DESIGN.md:20` | "messaging is contingent on a spike that has not been run" → spike 01 has run; `Task` note updated |
| README counts | 16 ADRs (15 Accepted + 1 Proposed), 10 spec docs, **124** gate assertions across 4 spikes, 48 invariant rows. Counted, not estimated |
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

### 7a. Redo after verification (2026-08-27)

The verifier returned **FAIL** on `59da08b` with seven ordered items. The headline finding is
the one that matters most: **`tools/validate_spec.py` reported "superseded claims ok" while
five documents still stated the reversed decisions**, because it scanned `spec/*.md` only.
A gate that passes on the thing it exists to catch is worse than no gate, since it converts
"unchecked" into "checked".

#### A decision missing from the original pass: unmediated tools

`spec/07` contradicted itself — it required every tool call to cross the ledger *and* offered
`tools.platform_executed = false` as an escape. Neither half could simply be deleted, because
**vendor-hosted tools (web search, code execution, file search, computer use) execute on the
vendor's side and cannot be intercepted at all.** Forbidding them would have made the rule
unimplementable; ignoring the gap would have made the guarantee false. Permitted narrowly:

| Condition | Mechanism |
|---|---|
| a **declared adapter capability**, never a per-call choice | lives in `declared_capabilities`, so it is inside `adapter_contracts.digest`; changing the answer fails the pin |
| **denied by default**, enabled per tenant by a Cedar `permit` naming the tool | every use still emits `policy.evaluated` |
| **visible**: an `effect_ledger` row, `kind='unmediated'`, status **`observed`** | no claim, no settle — the platform *saw* it, did not *own* it |
| `observed` carries no claim fields | `CHECK effect_claim_fields_together` |
| `observed` ⇔ `kind='unmediated'` | `CHECK observed_iff_unmediated`, so `status <> 'observed'` is a reliable at-most-once filter |
| **never in a pack containing a mutation** | API returns `422 unmediated_tools_with_mutations` |

The third condition carries the reasoning: an unintercepted *observation* costs visibility
into a read; an unintercepted *mutation* costs the entire ledger guarantee. Verified against
real Postgres — **spike 03 scenario 9, 6 assertions**, including that an unmediated effect
cannot be claimed and cannot reach `succeeded`.

#### The seven items

| # | Verifier item | Before | After |
|---|---|---|---|
| 1 | ACP / foreign-agent path still live | `DESIGN.md:215` journey ran `--adapter acp --agent claude-code`; `DESIGN.md:278` "Four methods (AX)"; `spec/06-api.md:161` registered `acp:claude-code` / `acp_subprocess`; `reference-architecture.md:184` argued terminal-scraping is "how you bring an agent with no integration surface under one policy layer"; `:47` diagram had a Codex box | Journey is `phoenix run --agent revenue-analyst --bundle sonyliv-analytics`; "**Two RPCs**; AX's four-method contract is the upstream precedent, not our shape"; example registers `sdk:claude-agent-sdk` / `sdk_in_process`; both `reference-architecture.md` sites carry dated amendments; `spec/07:4` header also said "Four methods" and now says two RPCs |
| 2 | `spec/07` contradicts itself | "the cost is accepted deliberately: an adapter cannot bring its own tools" *and* an escape hatch | Paragraph deleted with a dated note; replaced by the three-condition rule above, stated **once**. `spec/08` rows **30e/30f/30g** added |
| 3 | "`Task` is deferred" still active | `v01-boundary.md:13` "**`Task` is not in v0.1**", `:166` "We defer … and `Task`"; `spec/00-overview.md:17` and `:106` "Deferred" | All four amended with dated notes pointing at §2's reversal. Repo-wide grep for `Task.*defer` / `defer.*Task` now returns only dated amendments and this change log |
| 4 | DESIGN §6 vs Never #4 | `DESIGN.md:327` "We adapt agents. Cloudflare's alternative … at the cost of never running someone else's" | Softened boundary text from `v01-boundary.md:87`, dated, with the one-sentence reason: the Cloudflare cost was losing the ability to run others' agents, and we no longer need to |
| 5 | 124 assertions unexplained | README said 124 | **109** = 12 + 35 + 35 + 27 at the time of the verifier run; now **115**, because scenario 9 added 6 assertions to spike 03 in this same pass. Taken from each spike's own `RESULT.md`, with the counting rule stated next to the number: **vendored upstream suites do not carry the verdict** (`VERIFICATION-RULES.md` rule 6). The 124 came from spike 02's pytest total rather than its `RESULT.md` figure |
| 6 | (same as 1) | — | Confirmed: no "Four methods" and no ACP journey remains in `DESIGN.md` |
| 7 | Counts | `spec/00-overview.md:31` "Six open design questions"; `scope-reconciliation.md:248` "ten defects" | "**Seven**"; "**eleven**", the eleventh being the `09-decisions.md` index itself — §7 was added in the same pass that wrote the row and the count was not updated with it |

#### The tooling gap, closed

| Before | After |
|---|---|
| pattern list hard-coded in `validate_spec.py` | `tools/superseded-patterns.txt`, one regex per line with its date and reason |
| scanned `spec/*.md` only | `spec/`, `synthesis/`, `decisions/`, `DESIGN.md`, `README.md` |
| a hit was a hit | forgiven only near an amendment marker (`superseded\|amended\|(YYYY-MM-DD)`), in a `scope-reconciliation.md` table row, in an ADR **evidence-log** row, or inside a SQL string literal |
| no test of its own | `tools/test_validate_spec.py`, **7 controls**, wired as `make gate-tests` |

Three exclusions are scope decisions rather than loopholes, and are documented in the pattern
file: **evidence about another project** (`projects/`, ADR evidence rows — "OpenHands launches
Claude Code" is true about OpenHands forever), **probe and matrix text** (`capability-matrix.md`
names foreign agents because the probe asks about them), and **retained enum values**
(the reserved modes stay in the `CHECK` so the column never needs a migration; superseded
2026-08-27 as shippable paths). What the gate
polices is a claim in **our** voice about what **we** ship.

#### Two defects found in this pass, by its own controls

- **The negative-control test measured nothing.** Its first version asserted on the
  validator's exit code, but a copied tree legitimately fails unrelated checks (no node, no
  Postgres, no spike venv), so every control "passed" for the wrong reason. Control 0 — *the
  baseline copy must pass* — caught it. The controls now read the superseded result
  specifically.
- **The validator crashed instead of reporting.** `check_postgres_gate()` hard-coded
  `.venv/bin/python`, so running against a copied tree raised `FileNotFoundError` and produced
  **no output at all** rather than one `UNVERIFIED` line. Now falls back to
  `sys.executable`.

Both are the same class as the two defects spike 04 found in itself, and the reason each pass
now writes the control before trusting the green.

### `make check` — verbatim, 2026-08-27 (redo)

```
$ make spec
spec validation
----------------------------------------------------
  canonicalisation vectors   ok
  rewind algorithm           ok
  protobuf compiles          ok
  openapi coverage           ok
  effect lifecycle           ok
  postgres gate              ok
  superseded claims          ok
  cross-references           ok
  placeholders               ok
  foreign-key targets        ok

spec/ valid (all checks executed).
```

```
$ make gate-tests
negative controls for the superseded-claims gate
  ok   baseline copy passes the superseded gate  [0 unexpected: []]
  ok   injecting 'ACP adapter' into DESIGN.md FAILS the gate
  ok   ...and the failure names DESIGN.md  [['DESIGN.md:434 states a claim superseded on 2026-08-27 (replaced by the Claude SDK adapter, then the OpenAI SDK adapter)']]
  ok   a claim in synthesis/ is caught (the old gate scanned spec/ only)  [['v01-boundary.md:191 states a claim superseded on 2026-08-27 (we do not adapt third-party agents)']]
  ok   a dated amendment quoting the old wording is NOT flagged  [[]]
  ok   an empty pattern file does NOT silently pass
  ok   a revived 'Task is deferred' claim is caught  [['00-overview.md:120 states a claim superseded on 2026-08-27 (Task/routines moved to Tier 2; the deferral trigger is met)']]

7 passed, 0 failed
PASS — the gate fails on every injected defect and forgives amendments.
```

```
$ make check
project                    depth        cov  status
------------------------------------------------------------
ag2                        deep      100.0%  ok
agent-control              targeted  100.0%  ok
aws-agentcore              targeted   69.9%  ok
cloudflare-agents          deep      100.0%  ok
google-agent-platform      deep      100.0%  ok
google-ax                  deep      100.0%  ok
groupmind                  recon       0.0%  ok
humanlayer                 targeted  100.0%  ok
langgraph                  deep       99.4%  ok
letta                      deep       99.4%  ok
microsoft-agent-framework  targeted   69.9%  ok
omnigent                   deep      100.0%  ok
openhands                  deep       99.4%  ok
pydantic-ai                deep      100.0%  ok

3 tracked unknown(s) — informational, not a failure:
  i langgraph: 1 tracked unknown(s) (C8) — accounted for in open-questions.md
  i letta: 1 tracked unknown(s) (C5) — accounted for in open-questions.md
  i openhands: 1 tracked unknown(s) (C5) — accounted for in open-questions.md

All facts.yaml valid.
spec validation
----------------------------------------------------
  canonicalisation vectors   ok
  rewind algorithm           ok
  protobuf compiles          ok
  openapi coverage           ok
  effect lifecycle           ok
  postgres gate              ok
  superseded claims          ok
  cross-references           ok
  placeholders               ok
  foreign-key targets        ok

spec/ valid (all checks executed).
wrote synthesis/capability-matrix.md
==================================================================
PHOENIX TEARDOWN — STATUS
==================================================================

Projects (14 scaffolded)

  project                      depth     ev    cov  ADR impact
  --------------------------------------------------------------
  ag2                          deep      A    100%          14
  agent-control                targeted  A    100%          15
  aws-agentcore                targeted  A     70%          15
  cloudflare-agents            deep      A    100%          13
  google-agent-platform        deep      A    100%          14
  google-ax                    deep      A    100%          13
  groupmind                    recon     C      0%           0
  humanlayer                   targeted  A    100%          14
  langgraph                    deep      A     99%          10
  letta                        deep      A     99%          12
  microsoft-agent-framework    targeted  A     70%          15
  omnigent                     deep      A    100%          13
  openhands                    deep      A     99%          11
  pydantic-ai                  deep      A    100%          14

Exit criteria: 25/25 answered

ADRs: 16
  Accepted       15
  Proposed       1

Synthesis deliverables

  D1 capability matrix         generated  synthesis/capability-matrix.md
  D2 ADR log                   16 files   decisions/
  D3 domain model              FINAL      synthesis/domain-model.md
  D4 reference architecture    FINAL      synthesis/reference-architecture.md
  D5 build/reuse map           FINAL      synthesis/build-reuse-map.md
  D6 v0.1 boundary             FINAL      synthesis/v01-boundary.md
     licensing review          FINAL      synthesis/licensing.md
     open questions            FINAL      open-questions.md

9 deep + 4 targeted. Probe set: 173 probes.
==================================================================
```
