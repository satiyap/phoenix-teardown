# ADR-0010 — OpenTelemetry is the canonical telemetry transport

- **Status:** Provisional (pre-evidence, Phase 0)
- **Date:** 2025-08-26
- **Supersedes:** —
- **Superseded by:** —

## Context

Written before the teardown as a strawman to be attacked. Phase 2 drafts these
from three deep probes; Phase 3 runs the remaining projects against them. Each
pass must record `confirms`, `amends`, `challenges` or `neutral` in its
`facts.yaml` `adr_impact`.

A provisional ADR is a hypothesis with a falsification condition, not a
commitment.

## Decision

Our canonical event schema is emitted over OpenTelemetry wherever it fits. Domain events carry stable names and become the substrate for audit and billing as well as debugging.

## Rationale

OTel is the industry consensus and buys an ecosystem of backends for free. A proprietary transport buys nothing in return.

## Implications

- Event schema must be defined and versioned deliberately.
- Audit and billing need durability guarantees OTel may not give; may require a separate durable path for those.
- Span/event mapping for long-running agent runs needs care.
- Cardinality discipline required on agent and tenant ids.

## Falsification

If OTel cannot express long-lived, resumable runs without abuse, keep OTel for tracing and use a dedicated event log for audit.

## Deciding probes

`M1`, `M2`, `M3`, `M4`, `M5`, `M8`

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | confirms | grep `opentelemetry` across `libs/` returns nothing @ 3803173 | Chose proprietary LangSmith telemetry. Consequence: the best observability for the most popular OSS agent runtime is locked behind a closed commercial product. Exactly the outcome OTel avoids. |
| OpenHands | amends | `openhands-sdk/.../observability/laminar.py:400-430 @ 760eea2` | OTel reachable only indirectly via the Laminar vendor SDK, and integration required working around Laminar's own isolated ContextVar diverging from opentelemetry.context. Subagent traces need explicit parent re-linking (delegate.parent_trace_id) after deliberately severing the span. |
| Letta | confirms | `src/telemetry/ @ 852ca24` | Third deep teardown, third with no OpenTelemetry. `src/telemetry/` is error reporting and product analytics with batched flushing. The gap is industry-wide rather than a per-project oversight, which strengthens adopting OTel as a differentiator rather than a checkbox. |
| Google AX | confirms | `internal/telemetry/telemetry.go:23-28 @ b777313`; `internal/controller/eventlog/sql.go:105-108` | **First project in the study with real OpenTelemetry**, breaking a 3-for-3 gap. OTLP gRPC exporter, propagation, trace SDK, with spans instrumenting both the event log (tracer `eventlog.sql`) and every harness adapter. Proves the standard is viable for agent runtimes. |
| Omnigent | confirms | `pyproject.toml:93,145-150 @ ba9e371`; `designs/OBSERVABILITY.md` | Second real OTel and the most thorough: both OTLP exporters plus FastAPI, httpx and **SQLAlchemy** instrumentation — the only project tracing its own database. **But a caution that changes our exit criteria**: its own design doc audits the gaps — trace context "never propagated over the wire", `HTTPXClientInstrumentor` "never wired", `FastAPIInstrumentor` "gated off by default", `get_traceparent_env()` "dead code — zero call sites". Adopting OTel is not the same as wiring it. **Our criterion must be a propagation test asserting one trace id spans client → control plane → adapter, not a dependency check.** Also worth stealing: `trace_id_from_response_id`, where the response id *is* the trace id. |

## Open questions

-
