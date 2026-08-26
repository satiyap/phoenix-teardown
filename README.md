# Phoenix Teardown

A comparative architecture teardown of 14 agent platforms, run to produce one
thing: enough design evidence to freeze a v0.1 architecture for our own platform.

Not a feature survey. The exercise answers three questions:

1. Which agent abstractions have already proven useful?
2. Which responsibilities belong in our platform versus external infrastructure?
3. Where is there still meaningful product differentiation?

Read [`PLAN.md`](PLAN.md) for phases and working rules.
Read [`probes/probe-set.md`](probes/probe-set.md) for the 173 questions every
project answers.

## Layout

```text
PLAN.md                        phases, rules, definition of done
probes/probe-set.md            163 probes + 10 hard scenarios (authoritative)
schema/facts.schema.yaml       LOCKED extraction schema + vocabularies
schema/teardown-template.md    the 26-section narrative template
projects/<slug>/
  facts.yaml                   machine-readable extraction
  teardown.md                  narrative, capped at ~10 pages
  sources.md                   URLs, file paths, commit SHAs, dates read
  dx-log.md                    timeboxed hands-on friction log
decisions/ADR-*.md             10 provisional ADRs with falsification criteria
synthesis/
  recon.md                     Phase 1 triage and depth budget
  licensing.md                 licence review, USE/INTEGRATE/REFERENCE/AVOID
  capability-matrix.md         GENERATED — do not hand-edit
  domain-model.md              D3
  reference-architecture.md    D4
  build-reuse-map.md           D5
  v01-boundary.md              D6
  exit-criteria.md             the 25 questions that define "done"
open-questions.md              register with owners and decide-by dates
tools/                         validation, matrix generation, status
```

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install pyyaml==6.0.2
cp .env.example .env      # then add LLM_API_KEY
```

## Commands

```bash
make status        # coverage, ADR state, deliverable progress
make validate      # check every facts.yaml against the schema
make matrix        # regenerate synthesis/capability-matrix.md
make check         # validate --strict + matrix + status — MUST exit 0
make probes        # print the probe set summary

./.venv/bin/python tools/new_project.py <slug> "<Name>" [deep|targeted|recon]
./.venv/bin/python tools/llm.py       # gateway health check
```

**On `unknown` verdicts.** `make check` exits non-zero for an `unknown` probe that
is *not* accounted for in [`open-questions.md`](open-questions.md), because an
untracked `unknown` is indistinguishable from a probe nobody examined. An `unknown`
that names its reason in the log — closed source, undocumented semantics, a
non-inspectable managed surface — is a legitimate finding and reported as
informational. Three exist today (`langgraph/C8`, `letta/C5`, `openhands/C5`) and
`make check` exits 0 with them present.

This is the `absent` ≠ `unknown` distinction the study is built on, enforced by
tooling rather than by discipline.

## Evidence rules

These are the difference between a teardown and a set of opinions.

- Every architectural claim cites `path/file.py:120 @ commit-sha` or
  `URL (read YYYY-MM-DD)`.
- `absent` means you read the source and it does not do this. `unknown` means
  you do not know. Never substitute one for the other.
- A `verdict: unknown` on a deep project needs an entry in `open-questions.md`.
- No claim originates from an LLM. The gateway in `tools/llm.py` may help
  process text you already gathered; it is not a source.
- Teardowns cap at ~10 pages. Synthesis matters more than volume.

## Verdict vocabulary

| Verdict | Meaning |
|---|---|
| `first_class` | Explicit named concept, visible in API, schema, or docs |
| `implicit` | Behaviour exists but is emergent or undocumented; cite source |
| `absent` | Read the source; genuinely does not do this |
| `unknown` | Not determined, or evidence inaccessible |

The distinction between the first three is the most useful signal in the whole
exercise.

## Status

**Phases 0–5 complete.** 13 projects read, 15 ADRs Accepted, 25/25 exit criteria
answered, all six synthesis deliverables final.

| Phase | State |
|---|---|
| 0 Scaffold | 14 projects, 173 probes, locked schema, tooling verified |
| 1 Recon | 13/14 inspectable; no copyleft anywhere; depth budget set |
| 2 Deep probes | LangGraph, OpenHands, Letta — the three anchors |
| 3 Falsification | + Google AX, Omnigent, Cloudflare Agents, AG2, Pydantic AI, Google Agent Platform |
| 4 Targeted | + HumanLayer, AWS AgentCore, Microsoft Agent Framework, Agent Control |
| 5 Synthesis | domain model, reference architecture, build/reuse map, v0.1 boundary |
| 6 Handoff | `DESIGN.md` + developer journey |
| 7 Spikes | AG2 storage swap, definition pin — 47 gate tests, verification rules |
| 8 Spec | 8 documents, 30 required invariant tests with negative controls |

**173 recorded ADR impacts**: 96 confirms, 19 amends, 10 challenges, 48 neutral.
Four ADRs did not exist before the evidence (0011 pinning, 0012 capabilities,
0013 policy, 0014 effect ledger) and one was raised in Phase 4 (0015 approvals).
**No ADR was abandoned**, though ADR-0003 came within one project of deletion.

### What the evidence decided

> **Scope note.** "Target architecture" is what the platform is when finished;
> **v0.1 shipment** is what we build first. They differ, and
> [`synthesis/scope-reconciliation.md`](synthesis/scope-reconciliation.md) tabulates
> the difference. Two of the four items below are in v0.1; two are deferred with
> named triggers.

**Target architecture — four things nobody does:**
1. **Content-derived pinning on the agent definition.** *(in v0.1)* MAF proves the mechanism on
   *workflows* (a bytecode digest enforced on restore); nobody applies it to agents.
   13 projects: AX pins adapter identity without versions, Omnigent versions agents
   without pinning, ADK versions storage and telemetry schemas but not agents.
2. **A platform-owned effect ledger.** *(in v0.1)* Cloudflare and AG2 each solve half with
   different keys; ADK states the requirement precisely and delegates it to tool
   authors.
3. **Unified `Capability` + `Extension` with a two-layer conformance bench.**
   *(v0.1 ships the offline layer only)*
   Five projects use one word for two different concepts.
4. **Agent-level revocation and an approver identity on approvals.** *(approver
   identity in v0.1; revocation deferred)* HumanLayer has
   the only real `Approval` resource and records *why*, never *who*.

**INTEGRATE — three, down from four:** AG2's `ag2.network` envelope and hub (the only
durable agent messaging in 13 projects, and **contingent on a storage spike**), Cedar
for policy, `genai-prices` for cost data. *Agent Control was reclassified from
integrate to port: it has no `Principal` model, so running it would mean a second
policy store that cannot reference the principal ADR-0007 requires on every
decision.*

**NEVER:** compensation/saga engine (zero positive answers in 13 projects), workflow
engine, model gateway, agent-authoring framework, or any bespoke policy DSL, trace
format or message protocol.

### The verified failure that justifies the headline decision

LangGraph resumes a checkpoint whose graph has changed by returning `[]` with **no
error and silent work loss** — confirmed by running it, not inferred. That is the
bug ADR-0011 exists to prevent, and 13 projects show nobody prevents it for agents.

### A methodological correction worth reading

Three of six Phase 3 passes found substantially more than recon predicted, each
because I trusted a cheap signal over the source — a stale version string, a README
shape, and worst, my own running tally. After seven projects with no agent-to-agent
messaging I had drafted an ADR rewrite abandoning it; the eighth implements it better
than my strawman did.

**A convergence across N projects is evidence about what is common, not proof about
what is possible.** Recorded in full in
[`synthesis/phase3-findings-final.md`](synthesis/phase3-findings-final.md) §5.

Three further times, reading a *schema* overturned an inference drawn from an API
surface (ADK's composite primary key, Agent Control's composite foreign keys). For
any claim about tenancy, uniqueness or referential integrity, the table definition is
the only evidence that counts.

### Read next

**To build: [`spec/`](spec/)** — the implementation specification (8 documents).
**To understand why: [`DESIGN.md`](DESIGN.md)** — the v0.1 architecture and design document,
including the ideal developer journey. It is the handoff artefact; everything below is
the evidence behind it.

| Document | What it answers |
|---|---|
| [`synthesis/scope-reconciliation.md`](synthesis/scope-reconciliation.md) | **Read first if anything below seems to contradict:** six ambiguities adjudicated |
| [`synthesis/v01-boundary.md`](synthesis/v01-boundary.md) | What ships, what waits, what we never build |
| [`synthesis/reference-architecture.md`](synthesis/reference-architecture.md) | The component shape and why each piece exists |
| [`synthesis/domain-model.md`](synthesis/domain-model.md) | The canonical model, its invariants, and the strawman nodes deleted |
| [`synthesis/build-reuse-map.md`](synthesis/build-reuse-map.md) | 203 component decisions: integrate, port, build, reject |
| [`synthesis/exit-criteria.md`](synthesis/exit-criteria.md) | All 25 questions, answered with citations |
| [`synthesis/capability-map.md`](synthesis/capability-map.md) | The condensed 11-capability view, one page |
| [`synthesis/capability-matrix.md`](synthesis/capability-matrix.md) | 173 probes × 13 projects, generated from `facts.yaml` |

## Success condition

The teardown has succeeded when a statement of this form can be written from
evidence rather than taste:

> Our platform is a framework-neutral control plane for persistent AI agents.
> Agents are stable security principals and logical actors; Tasks represent
> intent and Runs represent execution. Agents communicate through durable
> messages and delegated tasks. Runtime execution is provided by pluggable
> harness adapters and sandbox providers. Context is divided into task state,
> agent memory and shared workspace knowledge. MCP, A2A and ACP are
> interoperability protocols rather than internal architecture. The control
> plane owns identity, registry, task lifecycle, messaging, policy and
> observability; distributed execution, sandboxing, workflow engines and model
> inference are pluggable infrastructure.

That paragraph is currently a hypothesis. The teardown exists to earn it or
replace it.
