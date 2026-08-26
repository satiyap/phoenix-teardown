# Sources — Omnigent

## Repository

- repo: https://github.com/omnigent-ai/omnigent
- commit: `ba9e371464695018c8362967a6c23e8725f0cc8c`
- commit date: 2026-08-26
- cloned on: 2026-08-26 (`--depth 1` to `~/dev/_teardown_src/omnigent`)
- size: 111MB
- language: Python (server, runner, harnesses) + TypeScript (web, SDKs)
- status: alpha, declared in the README
- license: Apache-2.0, with DCO and NOTICE

## Verification

Installed the published package in a throwaway venv, 2026-08-26:

```
python3 -m venv .venv && ./.venv/bin/pip install omnigent
./.venv/bin/omni --version   → omnigent 0.11.0 (built 2026-08-25T17:27:41Z)
```

Then queried the capability model and policy constants live:

```python
from omnigent.harness_plugins import harness_capabilities
len(harness_capabilities())                     # 26 harnesses
# optional axes with no claim (None), per axis:
#   steering 26, live_queue 26, images 26, compaction 26

from omnigent.policies.types import FAIL_CLOSED_PHASES
# ('PHASE_TOOL_CALL', 'PHASE_REQUEST')

from omnigent.spec.types import PolicyAction
# ['allow', 'ask', 'deny']

import dataclasses; from omnigent.harness_capabilities import HarnessCapabilities
len(dataclasses.fields(HarnessCapabilities))    # 16 axes
```

Sample of declared capabilities (verified, not read from docs):

| harness | integration_mode | resume | interrupt | streaming | subagents | compaction |
|---|---|---|---|---|---|---|
| `pi` | cli-subprocess | cold-only | True | True | False | **None** |
| `claude-native` | native-tui | warm-reattach | True | True | True | **None** |
| `codex` | cli-subprocess | warm-reattach | True | True | False | **None** |
| `acp` | acp-subprocess | cold-only | True | True | False | **None** |

The all-`None` compaction column is the finding: the tri-state is designed and
plumbed but unpopulated across every harness.

## Design documents (read before the code, per the Phase 3 plan)

`designs/` holds 5,700 lines across 19 documents. Four were directly relevant:

| Document | Status | Why it matters |
|---|---|---|
| `harness-capabilities-bench-seam.md` (169 lines) | capability model landed as PR #1847; bench wiring proposed | The declare-then-reconcile contract. DRIFT semantics, the static-vs-runtime layer distinction, the confidence caveat |
| `harness-plugin-interface.md` (222 lines) | implemented | Entry-point plugin contract, `HarnessContribution` fields, import rules, rejection of builtin overrides |
| `SANDBOX_CREDENTIAL_PROXY.md` (338 lines) | **IMPLEMENTED** | Secretless credential proxy: swap-on-access, host-bound placeholders, leak guard |
| `DEVICE_AUTH.md` (433 lines) | **IMPLEMENTED** | RFC 8628 device grant, delegated scope, revocation |
| `OBSERVABILITY.md` (459 lines) | **Proposed** | Audits its own telemetry layer, including dead code and disabled instrumentors |

Reading design docs first was the right call: they name the *intent* and, unusually,
the gap between intent and implementation. I verified each claim against the code
rather than trusting the status line.

## Key source files

| Path | Why it matters |
|---|---|
| `omnigent/harness_capabilities.py` (161 lines) | The 16-axis declared capability model. `IntegrationMode`, `Elicitation`, `Resume`, `EffortFamily`, `ModelFamily`, `AuthModel`, `ForkHistory` enums. Tri-state optional fields with `None` = no claim |
| `omnigent/harness_plugins.py:324` | `_BUILTIN_CAPABILITIES` for all builtin harnesses |
| `tests/harness_bench/bench.py:44-66` | `CellResult{observed, declared, verdict}` and `is_drift` — the reconciliation |
| `omnigent/policies/types.py:59-80` | `FAIL_CLOSED_PHASES` with per-phase reasoning; why `PHASE_TOOL_RESULT` fails open |
| `omnigent/policies/types.py:222-268` | `PolicyResult` with `deciding_policies`, `data` transformation, `state_updates` |
| `omnigent/spec/types.py:1168-1181` | `PolicyAction` = ALLOW / ASK / DENY |
| `omnigent/policies/builtins/cost.py:1-52` | Cost budget: soft ASK checkpoints, hard `max_cost_usd` downgrade gate, fails closed on unpriced models, documents its own overshoot limit |
| `omnigent/db/db_models.py:216-238` | `current_workspace_id()` and `workspace_scope()` — tenancy via `ContextVar` |
| `omnigent/db/db_models.py:1434,1546` | `scheduled_tasks` and `scheduled_task_runs` — the Task/Run split |
| `omnigent/db/db_models.py:1570-1575` | `error` (compressed blob) + `error_code` (bounded, queryable, "for future retry logic") |
| `omnigent/stores/agent_store/sqlalchemy_store.py:300` | `row.version = row.version + 1` — the only agent versioning in the study |
| `omnigent/entities/agent.py:31-38` | `Agent` with `bundle_location`, `version`, and `session_id` (template vs session-scoped) |
| `omnigent/entities/permission.py:9-46` | `SessionPermission`, `ResolvedAccess`, `__public__` sentinel |
| `omnigent/server/auth.py:70-81` | `delegated_path_allowed` — fail-closed allow-list, prefix-confusion handled |
| `omnigent/inner/egress/proxy.py:714,1125-1128` | Placeholder host binding and the 403 leak guard |
| `omnigent/runner/subagent_routing.py:1-45` | Advisory spawn gate and the strictly-decreasing timeout ladder (12s>8s>7s>6s>5s) |
| `omnigent/server/scheduled/scheduler.py:1-26` | In-process RRULE scheduler: SKIP overlap, 30s misfire grace, 24-day timer cap, injectable clock |
| `omnigent/stores/conversation_store/__init__.py:1035-1049` | `SELECT FOR UPDATE` / `BEGIN IMMEDIATE`; the lost-update race from bug #9 |
| `omnigent/runtime/telemetry.py:508-540` | `trace_id_from_response_id` — the response id *is* the trace id |
| `omnigent/suspend_watch.py:1-30` | Laptop-sleep detection by monotonic-vs-wall-clock divergence |
| `omnigent/spec/AGENTSPEC.md` | Agent image format: `config.yaml`, `AGENTS.md`, `skills/`, `tools/{python,typescript,mcp}/`, recursive `agents/` |
| `omnigent/sandbox/{bwrap,seatbelt}.py` | Local isolation implementations |
| `openapi.json` | 72 API paths |

## Negative findings

| Searched for | Result |
|---|---|
| agent-to-agent messaging, mailbox, channels | **Nothing.** `comments.py:send_to_agent` is human→agent (formats file-anchored review notes) |
| version pinned on a conversation | **Nothing** in `entities/conversation.py`. This is the ADR-0011 challenge |
| idempotency key on tool calls | Nothing. The usage-delta race was fixed, but tool effects are unprotected |
| vector store | Nothing; transcript search is SQL full-text |
| memory subsystem | Nothing; skills are directories in the agent image |
| `SELECT FOR UPDATE` / `skip_locked` in `scheduled_task_store` | **Nothing** — the scheduler is in-process, so replicas would double-fire |
| agent revocation / deprecation | Nothing; `delete()` is a hard delete. Device *grants* do have revocation |
| compensation / rollback | Nothing |
| database foreign keys | **Deliberately absent** — "Rule R032; cascade is app-owned" |
| `get_traceparent_env` call sites | Still zero outside `telemetry.py`, as its own design doc says. But `inject_trace_context` now has two real call sites (`host/frames.py:927`, `server/routes/sessions/routes_core.py:1267`), so propagation is partially wired |

## Documentation

| URL / path | Read on | Notes |
|---|---|---|
| `README.md` @ ba9e371 | 2026-08-26 | "open-source meta-harness", 26 harnesses, ten cloud sandbox providers, policies |
| https://omnigent.ai | 2026-08-26 | Product site |
| `omnigent/spec/AGENTSPEC.md` @ ba9e371 | 2026-08-26 | Agent image format |
| `designs/CLI_CONTRACT.md` @ ba9e371 | 2026-08-26 | CLI surface contract |
