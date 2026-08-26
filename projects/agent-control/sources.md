# Sources — Agent Control

## Repository

- repo: https://github.com/agentcontrol/agent-control
- commit: `7cb21af33e46ae5122288acc92d8ce5b3f7159e7`
- commit date: 2026-08-21
- cloned on: 2026-08-26 (`--depth 1` to `~/dev/_teardown_src/agentcontrol`)
- size: 13MB
- language: Python 3.12+ (server, engine, models, evaluators) + TypeScript (UI, SDK)
- license: Apache-2.0
- packages: `agent-control-sdk` (PyPI), `agent-control` (npm)
- structure: `server/`, `engine/`, `models/`, `evaluators/{builtin,contrib}`, `ui/`, `sdks/`, `telemetry/`

## Scope of this pass

**Targeted**: `I8` (policy interception), `J10` (enforcement), `N` (multi-tenancy),
and `L8` (compensation — the last remaining universal gap).

Unlike the other two targeted passes, this reached **100% probe coverage** with no
`unknown` verdicts. The codebase is small and readable, and its scope is narrow
enough that "out of scope" is a genuine `absent` — read and confirmed — rather than
a gap in my reading.

## Verification

```
python3 -m venv .venv && ./.venv/bin/pip install agent-control-sdk
```

Live inspection of the action vocabulary:

```python
from agent_control_models.actions import validate_action, normalize_action
[validate_action(a) for a in ('deny','steer','observe')]   # canonical
{a: normalize_action(a) for a in ('allow','warn','log')}   # all -> 'observe'
validate_action('allow')  # ValueError: Invalid action 'allow'. Must be one of:
                          # deny, steer, observe
from agent_control_models.controls import SteeringContext
list(SteeringContext.model_fields)                          # ['message']
```

Engine test suite:

```
pytest engine/tests -q          -> 64 failed, 51 passed   (missing pytest-asyncio)
pip install pytest-asyncio
pytest engine/tests -q          -> 115 passed in 0.63s
```

The 64 initial failures were all `async def functions are not natively supported` —
a missing dev dependency, not real failures. Worth recording because a fresh clone
looks broken.

## Key source files

| Path | Why it matters |
|---|---|
| **`models/src/agent_control_models/actions.py:8-17`** | `ActionDecision = Literal["deny", "steer", "observe"]` — **`observe` is a canonical action** |
| `models/actions.py:19-58` | `validate_action` (strict, API boundary) vs `normalize_action` (lenient, internal reads), with the reasoning in both docstrings |
| **`models/controls.py:244-275`** | `SteeringContext.message` and the two procedure-shaped examples (2FA retry; manager-approval steps) |
| `models/controls.py:539-543` | Composite steer controls **require** `steering_context` |
| **`models/controls.py:546-625`** | `ConditionNode` — recursive `leaf`/`and`/`or`/`not` with a `validate_shape` validator enforcing exactly one kind and rejecting empty groups |
| `models/controls.py:960-962` | `steering_context` surfaced on the evaluation response |
| **`server/src/agent_control_server/models.py:41-80`** | `policy_controls` and `agent_policies` association tables — **"Composite FKs enforce same-namespace references on both sides"** |
| `models/server.py:768-800` | `GetControlBindingResponse` / `ListControlBindingsResponse` with `namespace_key`, `enabled`, pagination |
| `models/observability.py:30-460` | `ControlExecutionEvent`, `BatchEventsRequest/Response`, `EventQueryRequest/Response`, `ControlStats`, `StatsRequest`, `TimeseriesBucket` |
| **`engine/src/agent_control_engine/core.py:662-780`** | Concurrent control evaluation under a semaphore; `deny_found` event for early cancellation; per-control timeouts and error capture |
| `engine/src/agent_control_engine/selectors.py:7-45` | Dot-notation selection (`input.query`, `context.user_id`) with dict-then-attribute fallback |
| `README.md:33-90` | The thesis, the four-step quickstart, and the **explicit unsafe-default warning** |
| `evaluators/builtin`, `evaluators/contrib` | regex, list, JSON, SQL evaluators plus a contribution path |
| `server/tests/test_*_alembic_migration.py` | Dedicated migration test suites per schema change |

## Negative findings

| Searched for | Result |
|---|---|
| **principals / end-user identity / on-behalf-of** | **Nothing.** Governs behaviour, not authority — the ADR-0007 half it lacks |
| approval resource | Nothing — but `steer` reframes the need (see teardown §9) |
| agent versioning / revocation | Nothing (a `ControlBinding` can be `enabled=false`, which revokes an *attachment*) |
| **compensation / rollback (`L8`)** | **Nothing** — completing fifteen of fifteen, including this project and MAF |
| policy *analysis* (comparing two policy sets statically) | Nothing — empirical shadow only; Cedar supplies the static kind |
| cost / quota model | Nothing |
| agent execution, memory, sandbox, messaging | Out of scope by design, and confirmed absent by reading |
| row-level security | Nothing — tenancy is composite PKs and FKs plus application scoping |

## Documentation

| Path | Read on | Notes |
|---|---|---|
| `README.md` @ 7cb21af | 2026-08-26 | Thesis, quickstart, env vars, the unsafe-default warning |
| `TESTING.md` @ 7cb21af | 2026-08-26 | Test layout |
| `evaluators/README.md` @ 7cb21af | 2026-08-26 | Evaluator contract |
| https://docs.agentcontrol.dev/ | not fetched | Hosted docs; web tooling unavailable this session |
