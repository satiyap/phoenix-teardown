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

## Amendment — 2026-08-26 (Phase 3, Cloudflare Agents): conventions, not just adoption

"Uses OpenTelemetry" is too weak a bar, and two projects proved it in opposite
directions.

Omnigent depends on **six** OTel packages and instruments FastAPI, httpx and
SQLAlchemy — yet its own design audit found trace context "never propagated over
the wire", `HTTPXClientInstrumentor` "a declared dependency but **never wired**",
`FastAPIInstrumentor` "gated off by default", and `get_traceparent_env()` as
"**dead code** — zero call sites". A dependency list is not telemetry.

Cloudflare shows the real bar (`observability/genai/attributes.ts:1-9 @ 2f957bc`):

> `gen_ai.*` keys follow OpenTelemetry GenAI semantic conventions where they
> exist... Keys with no semconv home live under the `cloudflare.agents.*` vendor
> namespace — **never bare top-level keys, never `ai.*`** (the Vercel AI SDK's
> de-facto namespace).

Plus two details worth copying: spans may be `boundToInvocation` so a span "cannot
outlive the native invocation that owns its tracing context" (a real hazard in any
hibernating or resuming runtime), and a refusal to invent an `otel.status_code`
attribute because "status is span state in OTel" — declining to model as an
attribute what the protocol already models as state.

**Amended decision.** Adopting OTel means all four of:

1. **Follow GenAI semantic conventions** wherever a `gen_ai.*` key exists. Do not
   invent a local name for something already named.
2. **Declare one vendor namespace** for everything else. Never bare top-level
   keys, and never squat on another tool's prefix.
3. **Propagate context across every boundary**, and *assert it with a test*: one
   trace id must span client → control plane → adapter. This is the criterion
   Omnigent's audit shows a project can otherwise believe it meets while it does
   not.
4. **Bind span lifetimes to the invocation that owns them**, so a resumed or
   hibernated run cannot leak a span into the next invocation.

Exit criteria change accordingly: the OTel question is answered by a passing
propagation test, not by an inventory of dependencies.

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | confirms | grep `opentelemetry` across `libs/` returns nothing @ 3803173 | Chose proprietary LangSmith telemetry. Consequence: the best observability for the most popular OSS agent runtime is locked behind a closed commercial product. Exactly the outcome OTel avoids. |
| OpenHands | amends | `openhands-sdk/.../observability/laminar.py:400-430 @ 760eea2` | OTel reachable only indirectly via the Laminar vendor SDK, and integration required working around Laminar's own isolated ContextVar diverging from opentelemetry.context. Subagent traces need explicit parent re-linking (delegate.parent_trace_id) after deliberately severing the span. |
| Letta | confirms | `src/telemetry/ @ 852ca24` | Third deep teardown, third with no OpenTelemetry. `src/telemetry/` is error reporting and product analytics with batched flushing. The gap is industry-wide rather than a per-project oversight, which strengthens adopting OTel as a differentiator rather than a checkbox. |
| Google AX | confirms | `internal/telemetry/telemetry.go:23-28 @ b777313`; `internal/controller/eventlog/sql.go:105-108` | **First project in the study with real OpenTelemetry**, breaking a 3-for-3 gap. OTLP gRPC exporter, propagation, trace SDK, with spans instrumenting both the event log (tracer `eventlog.sql`) and every harness adapter. Proves the standard is viable for agent runtimes. |
| Omnigent | confirms | `pyproject.toml:93,145-150 @ ba9e371`; `designs/OBSERVABILITY.md` | Second real OTel and the most thorough: both OTLP exporters plus FastAPI, httpx and **SQLAlchemy** instrumentation — the only project tracing its own database. **But a caution that changes our exit criteria**: its own design doc audits the gaps — trace context "never propagated over the wire", `HTTPXClientInstrumentor` "never wired", `FastAPIInstrumentor` "gated off by default", `get_traceparent_env()` "dead code — zero call sites". Adopting OTel is not the same as wiring it. **Our criterion must be a propagation test asserting one trace id spans client → control plane → adapter, not a dependency check.** Also worth stealing: `trace_id_from_response_id`, where the response id *is* the trace id. |
| Cloudflare Agents | confirms | `packages/agents/src/observability/genai/attributes.ts:1-9 @ 2f957bc`; `packages/agents/src/observability/tracing/tracer.ts:24-31,298` | **Third real OTel, and the best on convention adherence.** `gen_ai.*` keys follow OpenTelemetry GenAI semantic conventions where they exist; keys with no semconv home live under `cloudflare.agents.*`, "**never bare top-level keys, never `ai.*`**" (the Vercel AI SDK's de-facto namespace). Span lifetimes can be `boundToInvocation` so a span "cannot outlive the native invocation that owns its tracing context". And it declines to invent an `otel.status_code` attribute because "status is span state in OTel". **Raises this ADR's bar from *uses OTel* to *follows the conventions and declares a vendor namespace*.** |
| AG2 | amends | `pyproject.toml:107,196 @ 90f490a`; `ag2/network/hub/core.py:1861-1866` | OTel is an **optional extra** (`tracing = ["opentelemetry-sdk>=1.20"]`), which is weaker than AX or Cloudflare shipping it by default. But `HubListener` contributes something they lack: **`on_envelope_rejected` fires for every attempt** on any pre-WAL failure, so *refusals* are observable, not just successes — plus `on_inbox_pressure` for backpressure and `envelope.trace_id` as a first-class field so trace context rides the message. **Amend: rejected operations must be as observable as successful ones.** Most systems tell you what happened, not what was refused. |

## Open questions

-
