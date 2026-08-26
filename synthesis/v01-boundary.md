# Deliverable 6 — v0.1 Product Boundary

> Status: **strawman**. This is the most useful final outcome of the teardown:
> without it the platform becomes a three-year infrastructure project that ships
> nothing. Finalise at Phase 5.

Both lists are load-bearing. The DOES NOT list is what protects the DOES list.

## v0.1 DOES

Each line needs an owning ADR before Phase 5 promotes it.

| Capability | ADR | Confidence |
|---|---|---|
| Agent registry | ADR-0001 | low |
| Stable agent identity | ADR-0001 | low |
| Runtime adapter interface | ADR-0004 | low |
| Claude Code adapter | ADR-0004 | low |
| Codex adapter | ADR-0004 | low |
| External A2A agent support | ADR-0006 | low |
| Durable Tasks and Runs | ADR-0002 | low |
| Message inbox | ADR-0003 | low |
| Channels | ADR-0003 | low |
| Task delegation | ADR-0002, ADR-0007 | low |
| Checkpoint / resume | ADR-0004 | low |
| Human approval gate | ADR-0007 | low |
| Sandbox provider abstraction | ADR-0009 | low |
| MCP capability gateway | ADR-0005 | low |
| OTel traces | ADR-0010 | low |
| Basic policy enforcement | — | low |
| CLI + API | — | low |

## v0.1 DOES NOT

| Excluded | Why |
|---|---|
| Build models | Not our layer |
| Build a vector database | Mature vendors exist |
| Build a full workflow engine | Temporal / Restate exist; ADR pending |
| Build container orchestration | Kubernetes exists |
| Build a sandbox runtime | ADR-0009 |
| Build an IDE | Not the product |
| Build an enterprise knowledge system | Scope explosion |
| Visual flow builder | UI investment before the model is proven |
| Autonomous planner framework | Belongs to harnesses, not the control plane |
| Multi-region / HA | Premature |
| Billing and metering | Telemetry substrate first (ADR-0010) |

## Deliberate v0.1 weaknesses

Known-inadequate choices, recorded so they are decisions rather than surprises.

| Weakness | Accepted because | Revisit when |
|---|---|---|
| | | |

## Ideal developer journey

The product constraint that should exist before implementation starts. Written
from the DX logs, not imagined.

```bash
platform init

platform agent add claude

platform run research-agent --task "research competitors"
```

For each command: what must be true for it to work, and what must the user
already understand. If the answer to the second is "more than three concepts,"
the design is not finished.

| Command | Preconditions | Concepts required |
|---|---|---|
| `init` | | |
| `agent add` | | |
| `run` | | |
