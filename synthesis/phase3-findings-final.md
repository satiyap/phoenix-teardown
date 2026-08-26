# Phase 3 findings — final

Nine deep teardowns complete, all at **100% probe coverage** (173/173 each, zero
`unknown`). Supersedes `phase3-findings.md`, which was written after two of six
Phase 3 passes and got two significant things wrong; that document is kept with
inline corrections because the errors are themselves findings.

| Project | Runtime class | Verdict | Closed what nothing else did |
|---|---|---|---|
| LangGraph | `durable_actor` | REFERENCE_ONLY | (Phase 2 anchor) |
| OpenHands | `attached_harness` | REFERENCE_ONLY | (Phase 2 anchor) |
| Letta | `durable_actor` | REFERENCE_ONLY | (Phase 2 anchor) |
| Google AX | `durable_actor` | REFERENCE_ONLY | `C12` upgrade rejection, verified by test |
| Omnigent | `meta_harness` | REFERENCE_ONLY | `J6` delegation, `J7` tenancy, `N3` cost, `K4` egress-ish |
| Cloudflare Agents | `durable_actor` | REFERENCE_ONLY | **`C6` idempotency**, `S10` lost-worker |
| AG2 | `hybrid` | **INTEGRATE-candidate** | **`F1 F2 F5 F6 F8` — the whole F-section**, `F11` |
| Pydantic AI | `in_process` | REUSE (targeted) | `K4` egress guard, semconv versioning |
| Google Agent Platform | `hybrid` | REUSE (targeted) | **`H1` memory service**, `H5` provenance, `P5`, `S6` |

---

## 1. The gap picture, closed

Phase 2 ended with **16 probes absent or undefined in all three anchors**. After
nine projects:

**Still absent in all nine — the genuine BUILD surface:**

| Probe | Gap | Assessment |
|---|---|---|
| `L8` | **Compensation / rollback** | The only real design gap surviving nine projects. ADK's event *rewind* undoes the record, not the side effects. Under Temporal (Pydantic AI's route) saga compensation is the engine's job — which is probably the answer: **compensation belongs to a workflow engine, not to an agent platform.** |
| `Q3`, `Q5` | SaaS restriction, network copyleft | Not design gaps. Artefacts of every project being Apache-2.0 or MIT. |

**Closed during Phase 3 (13 of 16):**

`A4` Task≠Run (Omnigent, AG2) · `C6` idempotency (**Cloudflare**, AG2) ·
`C12` upgrade detection (**AX**) · `D9` revocation (AG2, weakly) ·
`F1 F2 F5 F6 F8` messaging (**AG2**) · `F11` capability routing (**AG2**) ·
`J6` delegation (**Omnigent**) · `J7` tenancy (**Omnigent**, ADK) ·
`N3` cost limits (**Omnigent**)

So the study's central negative claim collapsed almost entirely, and it collapsed
because of projects I had ranked lowest. See §5.

## 2. ADR movement

Across 9 projects × 14 ADRs = 126 recorded impacts:

```
confirms 70   amends 16   challenges 7   neutral 21
```

| ADR | Trajectory | State entering Phase 4 |
|---|---|---|
| ADR-0001 Agent is persistent | 3 confirm, 2 amend, 2 challenge | **Amended twice.** AG2's immutable `Passport` + mutable `Resume` + cache-only `AgentRuntime` is the model. Two projects showed durable execution without agent identity, so the rationale is rebased on delegation/policy/audit. |
| ADR-0002 Task ≠ Run | 5 confirm, 2 amend | **Confirmed with precedent at last** (Omnigent's `scheduled_tasks`/`scheduled_task_runs`). Amended: add a queryable `error_code`, and a **logical rewind marker** (ADK). |
| ADR-0003 Messages are durable | 8 confirm, 1 amend | **Vindicated after nearly being abandoned.** Seven absences, then AG2 implements it better than the strawman. Now the best-specified ADR in the set. |
| ADR-0004 Runtime is adapter-based | 6 confirm, 1 amend, 1 challenge | **Narrowed to four methods** (AX), durability moved to the control plane, extended to *every* stateful concern with an in-memory sibling (ADK). Challenged by Cloudflare, which has no adapter at all. |
| ADR-0005 MCP is protocol | 6 confirm, 3 neutral | Uncontested. Cloudflare adds: persist MCP connection state. |
| ADR-0006 A2A is interop | 3 confirm, 1 amend, 5 neutral | Confirmed independently twice (AG2, ADK): own model inside, A2A as an optional edge adapter. Amended: southbound should be gRPC-shaped (AX). |
| ADR-0007 Principals | 6 confirm, 2 challenge | **Split into two subsystems.** ADK has credentials without principals; AG2 and Omnigent have principals. `Principal` and `Credential` are now specified separately. |
| ADR-0008 Memory is not one thing | 8 confirm, 1 amend | **Settled, and now has a mechanism.** Seven projects chose filesystem skills; ADK supplies the missing structure — Knowledge (files) + Recall (a service with event-time provenance) + State (four scopes, one non-durable). |
| ADR-0009 Sandbox is pluggable | 4 confirm, 2 amend, 1 challenge | **Widened to three boundaries**: process (ADK, Omnigent), **egress** (Pydantic AI), **storage** (Cloudflare). Each best-answered by a different project. |
| ADR-0010 OTel is canonical | 6 confirm, 3 amend | **Amended three times, and now the most precisely specified ADR.** Follow semconv (Cloudflare) → version adherence (Pydantic AI) → separate stability tiers into modules and let deployments pin the schema (ADK). Plus: rejections must be observable (AG2). |
| ADR-0011 Checkpoints are version-pinned | 6 confirm, 1 amend, 1 challenge | **Strongest differentiator in the study.** Ten projects; AX pins identity without versions, Omnigent versions without pinning, ADK versions storage *and* telemetry schemas but not agents. **Nobody does both.** Amended: the pin lives on the run, is an identifier plus a resolver, and covers checkpoint payload version. |
| ADR-0012 Capabilities are declared | 4 confirm, 2 amend, 1 neutral | **Amended three times.** Fail-closed by enforcement *position* not category (Omnigent); a two-layer conformance bench with DRIFT; `unknown` ≠ unsupported; verified vs asserted; and **split `Capability` from `Extension`** (Pydantic AI). |
| ADR-0013 Policy is traced + shadow-comparable | 2 confirm, 4 neutral | **Half-precedented.** AG2 and Omnigent give traceability (`deciding_policies`, `on_envelope_rejected`). **Shadow-comparison mode has no precedent in ten projects** — either a genuine differentiator or a bad idea; Phase 5 must decide. |
| ADR-0014 Effect ledger (new) | 3 confirm | Raised from evidence mid-Phase 3. Two independent precedents with *different keys*: explicit `idempotency_key` (Cloudflare) and `causation_id` (AG2). ADK states the requirement precisely and delegates it. |

**Zero ADRs were abandoned.** Two came close — ADR-0003 (drafted for deletion,
then vindicated) and ADR-0011 (still no precedent, but now clearly a gap rather
than a misunderstanding).

## 3. What to build, reuse, or integrate

The evidence now supports concrete decisions rather than preferences.

**BUILD (no adequate precedent):**

1. **Version-and-pin for resumption** (ADR-0011). Ten projects, nobody does both.
   The single clearest differentiator found.
2. **The effect ledger** (ADR-0014). Two partial precedents, neither
   platform-owned; ADK explicitly delegates it to tool authors.
3. **Shadow-mode policy comparison** (ADR-0013). No precedent at all.
4. **A unified `Capability` + `Extension` model** with a two-layer conformance
   bench. Omnigent has the bench, Pydantic AI has composition, nobody has both.

**INTEGRATE:**

- **AG2's `ag2.network`** — envelope schema, hub contract, channel protocols. The
  only INTEGRATE-candidate in the study: Apache-2.0, Python, opt-in, tested, and it
  solves the one subsystem we would otherwise invent.
- **`genai-prices`** (via Pydantic AI) for cost data, paired with Omnigent's
  fail-closed-on-unpriced rule.

**REUSE (port the pattern):**

- Pydantic AI's `_ssrf.py` guard list and its scoped-escape-hatch rule.
- Cloudflare's hung-work detection and no-progress backoff.
- AX's fold-the-log state derivation and composite-PK single-writer.
- Omnigent's secretless credential proxy.
- ADK's in-memory-sibling-per-interface discipline and four state scopes.

**ADOPT_AS_STANDARD (cross-cutting rules):** tenancy in the composite primary key
(Omnigent + ADK, converged independently); typed cancellation reasons (AX); cancel
*request* vs cancel *fact* (AG2); positional fail-closed sets (Omnigent);
`unknown` never degrading to `false` (Omnigent); every refusal naming its
alternative (Pydantic AI, ADK).

## 4. Convergences strong enough to stop questioning

| Pattern | Count | Status |
|---|---|---|
| Filesystem/git-backed skills over a memory *service* for knowledge | 7 of 9 | **Settled.** ADK adds a *recall* service alongside, not instead. |
| Sandboxing as a provider interface | 6 of 9 | Settled. |
| A2A/ACP as edge interop, own model inside | 4 of 4 that speak it | Settled. |
| Tenancy in the composite primary key | 2 of 2 that have tenancy | Settled — independent convergence. |
| No compensation/rollback | 9 of 9 | Accept as out of scope; belongs to a workflow engine. |
| No shadow-mode policy comparison | 9 of 9 | Unprecedented; decide in Phase 5. |
| In-memory implementation of every pluggable interface | 4 explicit | Settled as a DX requirement. |

## 5. The methodological finding

**Three of six Phase 3 passes found substantially more than Phase 1 recon
predicted, and in each case I had ranked the project low for a bad reason.**

| Project | My error | What it cost |
|---|---|---|
| **AG2** | Downgraded its budget on a seven-project tally, reasoning the messaging question was "nearly settled" | Nearly cut the entire F-section from v0.1 and replaced a tested design with a weaker pattern |
| **Pydantic AI** | Recon recorded 1.0; actual 2.35.0 | Would have missed the SSRF guard and semconv versioning |
| **ADK** | Triaged class B on README and package shape; budgeted 1 day | Would have missed the only memory service, the best credential subsystem, and typed session state |

Three distinct failure modes, one root cause: **trusting a cheap signal over the
source.** A star count, a README, a version string in a spreadsheet, and — worst —
my own running tally.

The tally error is the one worth naming precisely. After seven projects with no
agent-to-agent messaging I treated the pattern as evidence that messaging was
unnecessary. It was evidence that *seven systems built for adjacent purposes did
not need it*. **A convergence across N projects is evidence about what is common,
not proof about what is possible.** Absence is only informative when the projects
were architected to answer the question, and AG2 was.

Two process rules follow, and both apply to Phase 4:

1. **Budget a project by what it is architected to answer**, not by triage class,
   stars, or how confident the current tally has made me.
2. **Read before concluding, and re-read before publishing a negative.** I twice
   wrote a claim (`ADK tenancy is convention-only`; `no agent revocation anywhere`)
   that the source contradicted. Both were caught by checking; neither would have
   been caught by inference.

## 6. Phase 4 targeted passes — revised

Four remain, each scoped to specific probes rather than a full sweep. Per §5, each
gets read against what it is *architected* to answer, and its recon class is
treated as a hypothesis rather than a budget.

| Project | Read for | Why |
|---|---|---|
| **Microsoft Agent Framework** | `F` (messaging), `L` (orchestration), `D9` | Enterprise-oriented and actor-shaped; the second-best candidate after AG2 for messaging, and the best remaining hope for a real revocation lifecycle. Given §5, do **not** assume AG2 settled the F-section. |
| **AWS AgentCore** | `D` (identity/versioning/revocation), `I` (tools), `J` (IAM), `K` (sandbox) | The only AWS-native entry, and IAM is AWS's core competence. Best remaining hope for `D9` and for a principal model to pair with ADK's credential model. |
| **HumanLayer** | `G` (human interaction), `C11` (durable approval) | Purpose-built for HITL, so it is *architected to answer* the one section where our design is assembled from fragments. Likely the highest-yield targeted pass. |
| **Agent Control** | `I8`, `J10`, `N` (multi-tenancy), `L8` | Control-plane-shaped; the only remaining candidate for `L8` and for a tenancy model beyond composite keys. |

**GroupMind** stays `recon` — confirmed absent from GitHub, npm and PyPI in
Phase 1.

## 7. Phase 5 must decide

Questions the evidence has sharpened but not answered:

1. **Is shadow-mode policy comparison a differentiator or a bad idea?** Zero
   precedent in nine projects. Either nobody needed it, or nobody could make it
   work.
2. **Does `L8` belong to us at all?** Nine absences plus Pydantic AI's argument
   that saga compensation is the workflow engine's job suggests deferring it
   permanently.
3. **Can we adopt AG2's envelope without adopting AG2?** The INTEGRATE decision
   needs a spike, not more reading.
4. **What is the minimum viable pin?** ADR-0011 is the strongest differentiator and
   the most expensive to get right. `(agent_id, agent_version, agent_digest,
   adapter_id, adapter_version, checkpoint_schema_version)` may be more than v0.1
   needs.
5. **Where does the effect ledger live** relative to an external durable engine, so
   two idempotency mechanisms do not fight (Pydantic AI's warning)?
