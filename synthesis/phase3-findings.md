# Phase 3 findings — interim (after Google AX and Omnigent)

Written after the two front-loaded Phase 3 passes, before AG2, Cloudflare Agents,
Pydantic AI, and Google Agent Platform. These two were read first because they
addressed the largest gaps and because Omnigent is the closest analogue to the
platform being designed.

Both reached **100% probe coverage with zero unknowns** — the first projects to do
so. AX because its whole contract is 235 lines of proto; Omnigent because its
`designs/` directory states intent explicitly and its capability model is
introspectable at runtime.

---

## 1. The headline: six of sixteen universal gaps closed

Computed from `facts.yaml`, not by hand
(`probes where all three anchors were absent/undefined`):

| Probe | What it is | Closed by | Verdict |
|---|---|---|---|
| `A4` | Task ≠ Run | Omnigent | `first_class` — separate `scheduled_tasks` / `scheduled_task_runs` tables |
| `C12` | Upgrade mid-flight | Google AX | `first_class` — refuses resume on harness change, verified by test |
| `F11` | Capability routing | Omnigent | `implicit` — routes spawns to models/harnesses, not agents |
| `J6` | Impersonation / delegation | Omnigent | `first_class` — RFC 8628 delegated grants, revocable |
| `J7` | Tenant isolation | Omnigent | `first_class` — `workspace_id` in every composite PK |
| `N3` | Quotas / cost limits | Omnigent | `first_class` — cost policy with soft checkpoints and hard downgrade gate |

**Omnigent alone closed five.** It is the single most valuable project in the study
so far, and the one whose absence would have left the largest holes in the design.

## 2. The eight gaps that survive all five projects

Excluding `Q3`/`Q5` (licensing artefacts of Apache-2.0/MIT, not design gaps):

| Probe | Gap | Status after five projects |
|---|---|---|
| `C6` | **Tool-call idempotency** | No project has an idempotency key on tool side effects. AX is closest structurally (atomic per-step appends, idempotent actor create); Omnigent fixed an adjacent lost-update race (bug #9) but not this. **Confirmed industry gap.** |
| `D9` | **Agent revocation / deprecation** | Six for six. Omnigent hard-deletes agents — though its *device grants* have a full revocation lifecycle, proving the team knows how, just not for agents. |
| `F1` | Agent-to-agent messaging | Six for six absent |
| `F2` | Channels / pub-sub between agents | Six for six absent |
| `F5` | Mailbox | Six for six absent |
| `F6` | Inter-agent delivery guarantees | Six for six absent |
| `F8` | Inter-agent acknowledgement | Six for six absent |
| `L8` | **Compensation / rollback** | Six for six absent |

**The entire F-section is absent in six of six projects**, including two products
explicitly built for multi-agent work (Omnigent supervises 26 harnesses; AG2 is
next and is the last real test). This is now the most robust negative finding in
the study. See §5.

## 3. What Phase 3 changed about the ADRs

Five ADRs moved. Two amendments I wrote earlier were superseded by better designs
found hours later, which is exactly what the falsification design was for.

| ADR | Movement | What changed |
|---|---|---|
| ADR-0002 | strawman → **confirmed with precedent** | Omnigent's `scheduled_tasks`/`scheduled_task_runs` split is the first real Task/Run separation. The `error_code` field for retry classification was missing from my strawman `Run`. |
| ADR-0004 | **narrowed** | AX's four-method adapter contract, with durability in the control plane rather than the adapter. My seven-method strawman including `checkpoint`/`restore` would have created a lowest-common-denominator problem. |
| ADR-0010 | **criterion changed** | Two projects now have real OTel (AX, Omnigent), so it is viable. But Omnigent's own audit found dead propagation helpers and disabled instrumentors. The exit criterion became "one trace id spans client → control plane → adapter, asserted by a test" rather than "OTel is adopted". |
| ADR-0011 | **challenged, then sharpened** | AX pins harness identity without versions; Omnigent versions agents without pinning. Nobody does both. **The pin lives on the run, not the definition** — a distinction I did not have before. |
| ADR-0012 | **amended twice; second supersedes first** | I split fail-closed by capability *category* (safety vs liveness) after AX. Omnigent splits by *position in the enforcement path* — fail closed where the decision is the last enforcement point, fail open where the harm is already incurred — which is decidable from architecture rather than judgement, and explains Letta and AX as one rule instead of two. |

**Process note.** ADR-0012's first amendment being superseded within the same day
is the clearest evidence the continuous-synthesis approach works. Had I written all
seven Phase 3 teardowns before revisiting ADRs, I would have recorded the weaker
categorical rule and probably never revisited it.

## 4. Capability signalling: the design is now settled

Six projects, six approaches. This was the study's most productive axis.

| Project | Declaration | Verification | Absence means |
|---|---|---|---|
| LangGraph | declared enum + override detection | conformance test suite | unsupported |
| OpenHands | none (`NotImplementedError`) | none | silent no-op |
| Letta | real probe, `backend \| null` + reason | n/a | **fail closed** |
| Google AX | none | health protocol | **fail open** (treated as ready) |
| **Omnigent** | **16 typed axes, tri-state, public API** | **live bench, reports DRIFT** | **UNKNOWN, never "unsupported"** |

Omnigent wins decisively and contributes four ideas now adopted into ADR-0012:

1. **Capabilities are published API** (`GET /v1/harnesses`), so callers degrade
   deliberately instead of discovering limits by failure.
2. **A conformance bench reconciles declared against observed and reports DRIFT**,
   making the table self-enforcing: "you can't lie in `_BUILTIN_CAPABILITIES`
   without the bench catching it."
3. **`None` = "makes no claim", reported UNKNOWN, never assumed unsupported.** The
   same `absent` ≠ `unknown` discipline this study runs on.
4. **Verified is tracked separately from asserted** — only 4 of 26 harnesses are
   probe-verified, and the docs forbid treating the other 19 as ground truth.

With one honest caveat, verified live: all four of Omnigent's optional axes are
`None` for all 26 harnesses. The mechanism is proven, the data unpopulated. Hence
the new requirement that our bench report **declaration coverage**, not just drift.

## 5. Agent-to-agent messaging: the verdict

Six projects, zero implementations, including:

- **Omnigent**, whose headline feature is supervising multiple agents across 26
  harnesses, and which has sub-agents, a spawn routing gate, and shared session
  state — but no messaging. Agents relate through *parentage* and *shared state*.
- **Google AX**, a distributed harness runtime with no sub-agent concept at all.
- All three anchors.

The convergent pattern is unmistakable: **multi-agent coordination is done through
a shared durable substrate (parentage + session state + transcript), not through
message passing.** Every project that needed agents to coordinate reached for
shared state.

**Decision implication for ADR-0003.** Durable agent-to-agent messaging is
speculative generality and must not be in v0.1. AG2 remains the last test; if AG2
also lacks it, the ADR should be rewritten to specify the shared-substrate pattern
instead. I expect AG2 to have *conversational* multi-agent patterns rather than a
durable messaging primitive, which would not change this conclusion.

## 6. New ideas worth stealing, ranked

From two projects, in rough order of value to v0.1:

1. **Secretless credential proxy** (Omnigent). Swap-on-access at the egress MITM so
   nothing credential-shaped enters the sandbox; host-bound single-use placeholders
   for clients that refuse to run without seeing a credential; 403 on cross-host
   replay. The only design in the study where a sandboxed agent authenticates
   without holding a secret. **Port this.**
2. **State derived by folding the event log** (AX). No state table means no
   log/state divergence — a class of bug eliminated rather than managed.
3. **Single-writer via composite PK with the sequence computed in-transaction**
   (AX). Ordering safety with no lock service.
4. **Declared capabilities + conformance bench + DRIFT** (Omnigent).
5. **`workspace_id` in the composite primary key** (Omnigent). An unscoped query
   finds nothing rather than leaking. Tenancy that fails safe by construction.
6. **Approvals as durable protocol content** (AX). `ConfirmationContent{id,
   question, oneof decision}` — question and answer are one object in the log, so
   pending approvals are durable for free and fully replayable.
7. **Per-phase fail-closed sets, defined once** (Omnigent).
8. **Refuse to resume across a definition change** (AX), combined with **versioned
   definitions** (Omnigent). Neither alone is sufficient.
9. **The strictly-decreasing timeout ladder** (Omnigent). In any layered fail-open
   path, each hop's budget must strictly exceed the hop it waits on, or the inner
   hop's fail-open branch never runs. I had not seen this stated anywhere.
10. **Typed `CancelReason`** (AX). Cancellation should carry why.
11. **`deciding_policies` on a composed verdict** (Omnigent). First implementation
    of ADR-0013's traceability.
12. **Response id *is* the trace id** (Omnigent). No lookup table to go from an id
    to its trace.
13. **Template vs session-scoped agents** (Omnigent). A distinction our domain
    model lacked.
14. **Opaque adapter config** (AX). The control plane refuses to parse it.
15. **Precisely specified stream terminators** (AX). "Zero or more outputs frames
    terminated by exactly one end" is what makes a third-party adapter
    implementable without reading the reference implementation.

## 7. Anti-patterns confirmed

- **No authentication on a distributed agent runtime** (AX). Logging-only gRPC
  interceptors on a service that provisions sandboxes and executes arbitrary
  harnesses. The most sophisticated durability model in the study sits behind no
  access control.
- **Versioning without pinning** (Omnigent). An audit trail that cannot prevent the
  failure it documents.
- **In-process scheduling with no cross-replica claim** (Omnigent). Correct on one
  instance, double-fires horizontally. A trap for any scale-out control plane.
- **Mutable rows as source of truth** (Omnigent). Durability by transaction rather
  than replay; its own docs note an append-only log is "tracked separately".
- **Designing a tri-state nobody populates** (Omnigent). 26 of 26 harnesses make no
  claim on four axes.
- **Enormous surface for an alpha** (Omnigent). 111MB, 72 API paths, desktop app,
  web UI, Slack bot, 26 harnesses, and its own docs call it "heavily vibe-coded"
  and lacking "a clear mental map". A direct caution for our v0.1 boundary.

## 8. Convergences now strong enough to act on

| Pattern | Count | Status |
|---|---|---|
| **Filesystem/git-backed skills over a memory store** | 4 of 6 (Letta, OpenHands, AX, Omnigent) | **Settled for v0.1.** No project chose a memory service for knowledge. |
| Sandboxing as a provider interface, not an implementation | 5 of 6 | Settled. ADR-0009 confirmed. |
| Policy enforced at an explicit, named interception point | 4 of 6 | Settled. |
| No agent-to-agent messaging | 6 of 6 | Settled (as an omission). |
| Adapter/harness abstraction over third-party agents | 5 of 6 | Settled. ADR-0004 confirmed. |
| No compensation/rollback | 6 of 6 | Accept as out of scope for v0.1. |

## 9. Revised priorities for the rest of Phase 3/4

What is left to learn has narrowed considerably.

**Still genuinely unanswered, and worth targeted reading:**

1. **Tool-call idempotency (`C6`)** — the one universal gap with real design
   consequences. Cloudflare Agents (durable objects, at-least-once delivery) is
   the best remaining hope. If it too lacks this, it is a confirmed BUILD with no
   precedent.
2. **Agent revocation (`D9`)** — check Google Agent Platform and AWS AgentCore,
   both enterprise-oriented.
3. **Lost-worker detection / lease-based claims** — Cloudflare Agents and AX's
   SubstrATE dependency. Omnigent's in-process scheduler showed the failure mode.
4. **Shadow-mode policy comparison** — ADR-0013's second half, unprecedented after
   six projects. Probably a BUILD.

**Downgraded in value:**

- **AG2** was to be the decisive test for ADR-0003. After six absences the
  question is nearly settled; AG2 now serves to confirm rather than decide. Keep
  the pass, reduce the budget.
- **Pydantic AI** and **Google Agent Platform** are in-process/SDK-shaped and
  unlikely to speak to durability, tenancy, or delegation. Keep at 1.0d each,
  focused on their type-safety and evaluation stories.

**OQ-021 resolved during this pass.** Omnigent's bench has two layers
(`tests/harness_bench/test_bench.py`): an **offline** layer on every PR (registry
membership, profile completeness, reconciliation semantics, matrix rendering — no
network or credentials) and a **live** layer gated on credentials plus a runnable
harness CLI that asserts no DRIFT on P0 dimensions. That split is now adopted into
ADR-0012: live probes cost money and cannot gate every commit, but *declaration
completeness* costs nothing and should, so the table cannot silently rot when a new
adapter lands undeclared.
