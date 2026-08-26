# Plan

A comparative architecture exercise, not a feature survey. The output is enough
design evidence to make platform decisions with confidence.

Every subsystem should end with one decision: **REUSE** / **INTEGRATE** /
**ADOPT AS STANDARD** / **BUILD**.

## Three mechanics that make this work

**1. Extraction is machine-readable.** Each project produces `facts.yaml`
against a locked schema with a controlled vocabulary, alongside narrative
`teardown.md`. The capability matrix is generated from those files, never
hand-maintained. Without this it drifts from the teardowns by about project four.

**2. Synthesis is continuous, not terminal.** Three deep teardowns → strawman
domain model + provisional ADRs → the remaining seven run as falsification
passes against that strawman. Every pass records `confirms` / `amends` /
`challenges` / `neutral` against named ADRs in its `adr_impact`. This is the
mechanism that prevents ten unrelated product reviews.

**3. Depth follows evidence.** Phase 1 triages all 14 by evidence class before
allocating reading time. A project with no readable source cannot support a deep
teardown; substitute a system that answers the same architectural question.

## Phases

| Phase | Work | Output | Est. | Status |
|---|---|---|---|---|
| 0 | Scaffold, probe set, schema, tooling, provisional ADRs | This repo | 0.5–1d | ✅ done |
| 1 | Recon and triage all 14; licence review | `synthesis/recon.md`, `synthesis/licensing.md`, revised depth budget | 1d | ✅ done — 13/14 inspectable |
| 2 | Three deep probes: LangGraph, OpenHands, Letta | 3 teardowns @ 99.4% coverage, revised domain model, ADR-0011/0012/0013 raised | ~6d | ✅ done |
| 3 | Six falsification passes | 6 teardowns @ 100% coverage, ADR evidence logs, 13 amendments, ADR-0014 raised | ~7d | **complete** |
| 4 | Four targeted validations | 4 teardowns; ADR-0015 raised; Cedar and `observe` found | ~2d | **complete** |
| 5 | Synthesis | Matrix, domain model, reference architecture, build/reuse map, v0.1 boundary; ADRs → Accepted; exit criteria answered | 3–4d | **complete** |
| 6 | Handoff | v0.1 architecture & design document, ideal developer journey | 1–2d | **complete** |

~22–25 working days solo. Roughly two weeks with three people, but only if
Phase 0 lands first.

### Phase 2 — why these three

Chosen for maximum divergence, so the strawman is stressed early rather than
confirmed:

| Project | Answers |
|---|---|
| Letta | Durable actor identity, memory ownership, the H-section split |
| OpenHands | Sandbox, harness adaptation, execution isolation |
| LangGraph / LangSmith | Durable orchestration, checkpointing, telemetry schema |

### Phase 3 — falsification, not survey

**Order revised after Phase 2:** Google AX and Omnigent go first. AX addresses
four of the seven open gaps (agent versioning, Task/Run, idempotency, remote
transport); Omnigent is the closest existing analogue to our own design and
therefore the most important falsification target. See
`synthesis/phase2-findings.md` §8.

Google AX, Omnigent, AG2, Cloudflare Agents, Pydantic AI, Google Agent Platform,
GroupMind.

Read each *against* the strawman. A pass that changes no ADR gets flagged:
either it was too shallow, or the product genuinely duplicates ground already
covered. Record which — an unflagged no-op pass is a research failure hiding as
a completed task.

### Phase 4 — targeted only

| Project | Scope |
|---|---|
| Microsoft Agent Framework | Agent-to-agent semantics, workflow model |
| AWS AgentCore | Identity, gateway, sandbox as managed primitives |
| HumanLayer ACP | Approval and HITL semantics, durable pause |
| Agent Control | Policy enforcement points |

## Working rules

- **Evidence or `unknown`.** Every claim cites `path/file.py:120 @ sha` or
  `URL (read YYYY-MM-DD)`. No citation means the verdict is `unknown`.
- **`absent` ≠ `unknown`.** `absent` means you read the source and it does not
  do this. `unknown` means you do not know. Conflating them manufactures false
  confidence.
- **DX is timeboxed and inline.** 60–90 minutes hands-on per project, logged in
  `dx-log.md` as it happens. Not a separate phase, not reconstructed later.
- **Teardowns cap at 10 pages.** Cross-product synthesis beats exhaustive
  documentation.
- **No LLM-sourced claims.** The gateway may summarise text you gathered. It is
  never the origin of a fact about a system's architecture.
- **Anything unresolved goes in `open-questions.md`** with an owner and a
  decide-by date.

## Anti-goals

Model provider counts, prompt syntax, default planner quality, UI polish,
benchmark claims, tool counts, multi-agent demos, GitHub stars.

The questions that matter: What is durable? Who owns state? Who owns execution?
What are the resource boundaries? What fails? How does it recover? What is the
security principal? How do components communicate?

## Definition of done

`./.venv/bin/python tools/check_exit_criteria.py` shows 25/25 exit criteria
answered, ten ADRs Accepted with evidence logs, six deliverables drafted, and
`open-questions.md` holds no blocking `open` entries.

Then the next artifact is a v0.1 architecture document — not another round of
market research.
