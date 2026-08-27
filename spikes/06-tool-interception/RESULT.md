# Spike 06 — tool interception on Pydantic AI

**Gate assertions: 18** — the number `README.md` sums. Counts only tests that assert THIS spike's claims through its public boundary; vendored upstream suites are evidence, not our verdict (`VERIFICATION-RULES.md` rule 6).

**Verdict: PASS — OQ-043 is answered, and the mechanism is stronger than the one specified.**
**Date:** 2026-08-27 · **SDK:** `pydantic-ai-slim == 2.35.0` (PyPI), verified byte-identical to
the read source at `b48ee38`.

## Invariant, stated first

> A registered tool's body executes only after the platform has written an `effect_ledger` row
> for that exact call. There is no path — construction, model-driven call, resume, approval,
> streaming, policy denial, or a raising body — by which a registered tool reaches a customer
> system without one.

## The question was framed wrongly, and the answer is better than asked for

OQ-043 and `spec/07:256-261` asked *"can native execution be disabled, by wrapping
`@agent.tool` so the boundary is a decorator rather than a fork?"* That framing assumes Phoenix
must **intercept an executor that wants to run**. It doesn't. Pydantic AI 2.35.0 already has the
shape Phoenix needs, as a first-class supported mechanism:

| Mechanism | Source | What it gives Phoenix |
|---|---|---|
| `ExternalToolset.call_tool` raises `NotImplementedError('External tools cannot be called directly')` **unconditionally** | `toolsets/external.py:44` | a registered tool with **no executable body inside the SDK** |
| `get_tools` stamps `kind='external'` | `toolsets/external.py:36` | the model still sees the tool, so behaviour is unchanged |
| `DeferredToolRequests` as an `output_type` **ends the run** and returns pending `ToolCallPart`s | `_deferred.py:27,37` | the `ToolCall` frame of `spec/07`, natively |
| `deferred_tool_results=` supplies platform results on resume | `agent/__init__.py:1139` | the `ToolResult` frame, natively |
| `ApprovalRequiredToolset` raises `ApprovalRequired` **before** `super().call_tool` | `toolsets/approval_required.py:29` | fail-closed approval, natively |

**So the boundary is a TOOLSET, not a decorator.** Nothing is disabled, wrapped, forked or
monkey-patched: the tool is *declared* to the model and the SDK is given no way to run it. That
is a materially stronger guarantee than interception, because there is no executor to race with
and no wrapper that a future SDK version could route around.

`spec/07:256-261` and OQ-043 should be corrected: the decorator framing is wrong, and
`@agent.tool` is not the boundary.

## The finding that mattered most, from reading rather than testing

`_tool_execution.py:399` — on the **resume** path, when `tool_call_results` is supplied:

```python
self.executable_function_kinds = ('function', 'unknown', 'external', 'unapproved')
```

External and unapproved kinds **do flow through the regular execution pipeline on resume**. If a
body could run anywhere, it is here, and the spec did not mention it. Gate 4 exists solely
because the source said this. It passes — resume consumes the platform-supplied result and the
side channel stays empty — but that was not safe to assume.

## Gates

| # | Gate | Result |
|---|---|---|
| 0 | the side-channel oracle detects a real effect | control |
| 1 | zero registered tools ⇒ no executable path, no ledger rows | PASS |
| 2 | a registered tool ⇒ run **ends** on the deferred call, body never runs | PASS |
| 3 | the ledger row is written **before** execution, exactly one per call | PASS |
| 4 | **resume** consumes the platform result without re-executing the body | PASS |
| 5 | `ApprovalRequired` halts before execution | PASS |
| 6 | row 30c is executable: an uninterceptable tool **cannot be registered** | PASS |
| 7 | a policy-denied call is ledgered `denied` and never reaches the system | PASS |
| 8 | the **streaming** path is not a side door | PASS |
| 9 | a hallucinated tool name finds no dispatcher | PASS |
| 10 | three calls in one step ⇒ three distinct rows, no `tool_call_id` collision | PASS |
| 11 | a body that ran then raised ⇒ `indeterminate`, never `intended` | PASS |

## The oracle is independent (rule 5)

Every tool in the gate writes a line to a **real file** in `tmp_path`. `harness.py` never reads
or writes that file. So every assertion is about an **observable side effect**, not about what
the SDK reports having done — a test that trusted the SDK's own accounting would pass even if
the SDK were lying about what it executed.

## Negative controls (rule 4)

| Control | Proves |
|---|---|
| control 0 — the side channel fires on a real call | the detector is not inert |
| **`FunctionToolset` with the same function** ⇒ body runs, **zero ledger rows** | `spec/08` row 30a's bypass, **demonstrated** rather than asserted |
| resume with a fabricated result and **no** platform dispatch ⇒ side channel empty | gate 4's green comes from our dispatch, not from SDK incidentals |
| approval **granted** ⇒ the body does run | gate 5's empty channel was the approval gate, not an inert tool |
| `settle()` on a never-intended call ⇒ refused | the ledger cannot settle what it never saw |
| a `SloppyLedger` that skips `indeterminate` ⇒ gate 11 fails | gate 11 discriminates between the two behaviours |

### Harness mutations, each proven to break the gate

| Mutation | Effect |
|---|---|
| dispatch before ledgering | 3 gates fail |
| ignore the policy verdict | gate 7 fails |
| allow `sdk_executable=True` registration | gate 6 fails |
| **route tools through `FunctionToolset`** (the real bypass) | **7 gates fail** |
| drop the `indeterminate` settle on a raising body | gate 11 fails |

## A defect this spike found in Phoenix's own design

Gate 11 was written to document behaviour and instead **found a bug**. The first harness left a
crashed effect's row at `intended`. `intended` is indistinguishable from an effect that never
started — so a charge that fired and then lost its connection would have looked like a charge
that never happened. `spec/02-consistency.md:326-348` already says a dispatched effect must
never be left without a verdict; the harness didn't honour it. Fixed: a raising body settles
`indeterminate`, which is the state that surfaces for a human.

## The version pin, and how it was fixed

`pyproject.toml:5-6` uses `uv-dynamic-versioning` and the clone carries **no git tags**, so the
source tree **cannot state its own version**. Resolved by digest instead of by declaration:
`pydantic-ai-slim==2.35.0` from PyPI, then `shasum -a 256` on the five files this spike depends
on against the clone at `b48ee38` — `agent/__init__.py`, `_tool_execution.py`,
`toolsets/external.py`, `toolsets/approval_required.py`, `_deferred.py`. **All five identical.**

So the pin `pydantic-ai-slim == 2.35.0` is now **fixed, not a placeholder**, and `spec/07:256`
should be updated. The five digests are the real assertion; the version string is a label for
them.

## Cited claims

| Claim | Citation |
|---|---|
| external tools have no executable body | `toolsets/external.py:44 @ b48ee38` |
| external tools are still advertised to the model | `toolsets/external.py:36 @ b48ee38` |
| a deferred run ends and returns pending calls | `_deferred.py:27,37 @ b48ee38` |
| results are supplied back on resume | `agent/__init__.py:1139 @ b48ee38` |
| approval is checked before delegation | `toolsets/approval_required.py:29 @ b48ee38` |
| **external kinds execute on the resume path** | `_tool_execution.py:399 @ b48ee38` |
| `tool` decorator implementation / usage | `agent/__init__.py:2423` / `:2460 @ b48ee38` |

## Reproduce

```bash
cd spikes/06-tool-interception
../../.venv/bin/pip install -r requirements.txt
../../.venv/bin/python -m pytest test_gate.py -q     # 18 passed
```

No network, no API key, no database: `TestModel` is Pydantic AI's built-in fake model
(`pydantic_ai/models/test.py`), and it calls every registered tool by default, which is what
puts maximum pressure on the bypass question.

Per **rule 7**, this spike writes only inside pytest's `tmp_path` and touches no shared state —
no database, no fixed-name resource, nothing to clean up.

## Still not verified

- **Vendor-hosted tools** (web search, code execution) remain **unsupported**, unchanged by this
  spike. They execute on the vendor's side, so `ExternalToolset` cannot express them: there is no
  local body to withhold. Any admission is still *provider-reported use* needing a durable
  receipt.
- **Native `@agent.tool` functions are never used by Phoenix.** This spike proves they are the
  bypass (`FunctionToolset` control) and that we don't need them. It does **not** prove they are
  safe under any wrapping, because that question is now moot.
- **Concurrency.** Gate 10 covers three calls in one step, single-threaded. Two concurrent runs
  competing for one effect key is spike 03's territory, against real Postgres.
- **The in-process/Go boundary.** This spike is Python end to end. `spec/07` says `sdk_in_process`
  collapses to a function call, which cannot hold across a Go control plane and a Python harness.
  Unresolved and now the most urgent open design question.
