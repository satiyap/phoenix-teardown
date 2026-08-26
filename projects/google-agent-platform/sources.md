# Sources — Google Agent Platform (ADK)

## Repository

- repo: https://github.com/google/adk-python
- commit: `85b52f6a307598eb0bc20a6ab2a6780bb9efe7c1`
- commit date: 2026-08-25
- cloned on: 2026-08-26 (`--depth 1` to `~/dev/_teardown_src/adk`)
- size: 59MB
- language: Python
- license: Apache-2.0
- package: `google-adk` **2.7.1**

**Recon correction:** Phase 1 triaged this **class B** ("SDK-shaped, unlikely to
speak to durability or tenancy") and budgeted 1.0 day. It is **class A**: the only
memory service in the study, the best credential subsystem, the only typed session
state, the widest sandbox range, and the most carefully structured telemetry.
Third stale-recon correction of Phase 3.

## Verification

```
python3 -m venv .venv && ./.venv/bin/pip install google-adk
```

Clean first try. Then queried live:

```python
from google.adk.version import __version__                      # 2.7.1
from google.adk.sessions.state import State
State.APP_PREFIX, State.USER_PREFIX, State.TEMP_PREFIX          # 'app:' 'user:' 'temp:'
from google.adk.auth.auth_credential import AuthCredentialTypes
[t.value for t in AuthCredentialTypes]
# ['apiKey', 'http', 'oauth2', 'openIdConnect', 'serviceAccount']
from google.adk.memory import BaseMemoryService
[m for m in dir(BaseMemoryService) if not m.startswith('_')]
# ['add_events_to_memory', 'add_memory', 'add_session_to_memory', 'search_memory']
```

## Key source files

| Path | Why it matters |
|---|---|
| `memory/base_memory_service.py:43-140` | The only real memory service interface in the study; four methods, scoped `(app_name, user_id)` |
| `memory/base_memory_service.py:64-95` | `add_events_to_memory` as an optional delta method whose `NotImplementedError` names the fallback; `custom_metadata` as a documented staging area |
| `memory/memory_entry.py:26-45` | `MemoryEntry{content, id, author, timestamp}` — timestamp is *event* time |
| `memory/vertex_ai_memory_bank_service.py`, `vertex_ai_rag_memory_service.py` | Managed implementations behind the same ABC |
| `sessions/state.py:64-66` | `APP_PREFIX`/`USER_PREFIX`/`TEMP_PREFIX` |
| `sessions/state.py:24-46` | `StateSchemaError`; prefixed keys bypass validation |
| `sessions/schemas/v0.py:146-161` | **`StorageSession` with `app_name`, `user_id`, `id` all `primary_key=True`** — tenancy enforced in the PK |
| `sessions/_restricted_pickle.py` | Allow-listed unpickler for session state |
| `sessions/migration/`, `sessions/schemas/{v0,v1}.py` | Versioned storage schema with migrations |
| `apps/_configs.py:29-47` | `ResumabilityConfig` — pause on long-running call, resume from last event, **"tool call to resume needs to be idempotent because we only guarantee an at-least-once behavior once resumed"** |
| `apps/_configs.py:49-60` | `EventsCompactionConfig` with a pluggable summarizer |
| `apps/compaction.py`, `llm_event_summarizer.py` | Compaction implementation |
| `events/_rewind_events.py` | `_apply_rewinds` — "the single source of truth for which events are live after rewinds" |
| `auth/auth_credential.py:232-252` | Five typed credential kinds |
| `auth/exchanger/`, `auth/refresher/` | **Separate** interfaces and registries for obtaining vs renewing |
| `auth/credential_service/` | `BaseCredentialService`: in-memory and session-state backends |
| `auth/auth_preprocessor.py` | Injects credentials into tool calls |
| `auth/oauth2_discovery.py` | OIDC discovery |
| `code_executors/` | Seven executors: container, GKE, Vertex, Agent Engine sandbox, built-in, **`unsafe_local`** |
| `plugins/base_plugin.py:114-396` | Sixteen lifecycle hooks incl. four distinct error callbacks |
| `plugins/_reflect_retry_model_plugin.py`, `reflect_retry_tool_plugin.py` | Reflect-and-retry |
| `telemetry/_stable_semconv.py`, `_experimental_semconv.py` | Stability tiers as separate modules |
| `telemetry/_adk_attributes.py:15-24` | Vendor namespace; `adk.experimental.*` "carries no compatibility guarantee" |
| `telemetry/_schema_version.py:15-20` | Deployment-pinnable telemetry schema version |
| `telemetry/sqlite_span_exporter.py` | Local trace inspection |
| `a2a/` | A2A interop: `agent`, `converters`, `executor`, `experimental.py` |
| `evaluation/` | `BaseEvalService`, eval sets, scenario generation |
| `constraints-3.10.txt` … `constraints-3.14.txt` | Per-interpreter reproducible installs |

## Negative findings

| Searched for | Result |
|---|---|
| agent identity / registry / versioning / revocation | **Nothing** — despite versioning session *storage* schemas and *telemetry* schemas |
| principals, inbound authentication, authorization | **Nothing.** Outbound credentials are excellent; inbound authority is unmodelled |
| durable agent-to-agent messaging | Nothing; shared `State` and LLM-driven transfer |
| effect ledger / idempotency key | Nothing — stated as a *developer contract* instead |
| cancellation model | Nothing found |
| egress control / SSRF guard | **Nothing**, and ADK ships web-fetching tools |
| quotas / cost enforcement | Nothing; `_token_usage.py` measures only |
| policy decision object / shadow mode | Nothing; plugin callbacks are the seams |
| version pinned to an in-flight invocation | Nothing |

## Documentation

| Path | Read on | Notes |
|---|---|---|
| `llms.txt`, `llms-full.txt` @ 85b52f6 | 2026-08-26 | Machine-readable docs — an unusual and useful artefact |
| `AGENTS.md` @ 85b52f6 | 2026-08-26 | Repo conventions |
| `docs/` @ 85b52f6 | 2026-08-26 | User documentation |
