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
make check         # validate --strict + matrix + status
make probes        # print the probe set summary

./.venv/bin/python tools/new_project.py <slug> "<Name>" [deep|targeted|recon]
./.venv/bin/python tools/llm.py       # gateway health check
```

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

**Phases 0–2 complete.** Phase 3 (seven falsification passes) is next, starting
with Google AX and Omnigent.

| Phase | State |
|---|---|
| 0 Scaffold | 14 projects, 173 probes, locked schema, tooling verified |
| 1 Recon | 13/14 inspectable; no copyleft anywhere; depth budget revised |
| 2 Deep probes | LangGraph, OpenHands, Letta — all at 99.4% coverage |

13 ADRs, three of which did not exist before the evidence (0011 version-pinned
checkpoints, 0012 declared capabilities, 0013 traced policy).

Read [`synthesis/phase2-findings.md`](synthesis/phase2-findings.md) for the
cross-anchor comparison. Headline: **the entire agent-to-agent messaging section
is absent in all three projects**, as are Task/Run separation, side-effect
idempotency, agent revocation, tenant isolation and cost quotas.

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
