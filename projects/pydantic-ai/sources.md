# Sources — Pydantic AI

## Repository

- repo: https://github.com/pydantic/pydantic-ai
- commit: `b48ee3808631ea8796a7c3b6941863bde47e10be`
- commit date: 2026-08-26
- cloned on: 2026-08-26 (`--depth 1` to `~/dev/_teardown_src/pydantic-ai`)
- size: 351MB
- language: Python
- license: MIT
- packages: `pydantic_ai_slim`, `pydantic_graph`, `pydantic_evals`, `clai`

**Recon correction:** Phase 1 recorded this as version 1.0. The installed package
is **2.35.0**. This is the second stale-recon finding of Phase 3 (AG2 was recorded
pre-1.0 too), and both mattered — see the methodological note in the AG2 teardown.

## Verification

```
python3 -m venv .venv && ./.venv/bin/pip install pydantic-ai-slim
```

Clean first try. Then queried the live objects:

```python
import pydantic_ai; pydantic_ai.__version__          # 2.35.0
from pydantic_ai.tools import DeferredToolRequests
[f.name for f in dataclasses.fields(DeferredToolRequests)]
                                                     # ['calls','approvals','metadata']
from pydantic_ai.capabilities.abstract import CapabilityPosition
CapabilityPosition                                   # Literal['outermost','innermost']
len([n for n in dir(pydantic_ai.capabilities) if n[0].isupper()])   # 63
```

And confirmed the SSRF guard contents by inspection: `is_private`, `169.254`,
cloud-metadata handling, and `_BOUNDED_ACCEPT_ENCODING` all present.

## Key source files

| Path | Why it matters |
|---|---|
| `pydantic_ai/_ssrf.py:1-6,24-30,98-120` | The SSRF and credential-endpoint guard; bounded downloads; Teredo decoding |
| `pydantic_ai/_ssrf.py:101-104` | "always blocked, even with `allow_local=True`" — the scoped escape hatch |
| `pydantic_ai/_ssrf.py:105-118` | Per-provider metadata IP enumeration (AWS IMDS/ECS/EKS, Azure, Alibaba, Oracle, Scaleway) |
| `pydantic_ai/_otel_messages.py:1-4` | OTel GenAI message-part types, pinned to a specific spec commit |
| `pydantic_ai/models/instrumented.py:63-75` | `InstrumentationSettings`, including the `version` parameter |
| `docs/logfire.md:294-298` | Semconv 1.37.0; versions 2–4 deprecated with a warning |
| `pydantic_ai/_cost.py:1-27` | `genai-prices` integration, `preload_pricing_data`, `CostCalculationFailedWarning` |
| `pydantic_ai/_deferred.py:27-61` | `DeferredToolRequests{calls, approvals, metadata}`, `build_results(approve_all=...)` |
| `docs/capabilities/handle-deferred-tool-calls.md` | The handler chain: decline with `None`, fall through, bubble up as output |
| `pydantic_ai/capabilities/AGENTS.md` | "Prefer a capability over a new `Agent` constructor kwarg"; the serializability rule |
| `pydantic_ai/capabilities/abstract.py` | `CapabilityPosition`, `CapabilityOrdering`, seven `Wrap*Handler` types |
| `pydantic_ai/capabilities/__init__.py` | 63 capability exports |
| `pydantic_ai/durable_exec/AGENTS.md` | Durable engines as "first-class compatibility targets, not peripheral adapters" |
| `pydantic_ai/durable_exec/_base.py:38-45` | `BaseDurabilityCapability`; `model_id` crosses the boundary, not the `Model` |
| `pydantic_ai/durable_exec/_runtime_toolsets.py:38-49` | `cancellation_token_unsupported_error` — the best fail-closed message in the study |
| `pydantic_ai/_spec.py:1-5` | `NamedSpec`, shared by the evaluator and capability systems |
| `docs/agent-spec.md` | Declarative YAML/JSON agents including capabilities; `Agent.from_file` |
| `pydantic_ai/_agent_graph.py` | The agent loop as a graph |
| `pydantic_evals/pydantic_evals/` | Datasets, evaluators, online evaluation, OTel emission |

## Negative findings

| Searched for | Result |
|---|---|
| durable execution owned by the library | **Nothing, deliberately** — Temporal, DBOS, Prefect integrations instead |
| agent identity, registry, versioning, revocation | Nothing (Agent Specs are definitions, not identities) |
| principals, auth, authorization, tenancy | Nothing |
| agent-to-agent messaging | Nothing |
| effect ledger / idempotency key | Nothing — delegated to the durable engine |
| memory subsystem | Nothing; `ProcessHistory` hook only |
| compaction strategy | Hook exists (`HistoryProcessor`), no strategy shipped |
| policy engine | Nothing; typed wrap points and `Hooks` are the seams |
| process sandbox | Nothing — but `_ssrf.py` is real egress control |
| budget enforcement | `UsageLimits` caps requests/tokens; cost is measured, not gated |

## Documentation

| Path | Read on | Notes |
|---|---|---|
| `docs/agent-spec.md` @ b48ee38 | 2026-08-26 | Declarative agents in YAML/JSON |
| `docs/logfire.md` @ b48ee38 | 2026-08-26 | Semconv version policy and deprecation |
| `docs/capabilities/handle-deferred-tool-calls.md` @ b48ee38 | 2026-08-26 | Handler chain semantics |
| `pydantic_ai/capabilities/AGENTS.md` @ b48ee38 | 2026-08-26 | Capability design rules |
| `pydantic_ai/durable_exec/AGENTS.md` @ b48ee38 | 2026-08-26 | Durable integration rules |
