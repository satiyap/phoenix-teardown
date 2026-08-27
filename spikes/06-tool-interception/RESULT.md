# Spike 06 — tool interception on Pydantic AI

**Gate assertions: 26** — the number `README.md` sums. Counts only tests that assert THIS spike's claims through its public boundary; vendored upstream suites are evidence, not our verdict (`VERIFICATION-RULES.md` rule 6).

**Verdict: PASS — OQ-043 is answered, and the mechanism is stronger than the one specified.**

> **Revised 2026-08-27 after review returned FAIL on the verification, not the discovery.** Six
> defects, all fixed: the digest pin was claimed but never asserted (`external.py` could be
> edited with all 18 gates passing); row 30e's `indeterminate` skipped the claim phase that
> `spec/02-consistency.md:326` requires, so the lifecycle it named was absent; gate 6 tested a
> boolean Phoenix invented instead of `pydantic_ai.native_tools`; the mutation table was prose
> and one count was wrong (3 vs the real 7); `make check` never ran this spike; and OQ-043
> pointed at OQ-055 instead of OQ-056. Assertions 18 → **26**.
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
| 6 | row 30c is executable: **every vendor-hosted tool the SDK ships** is refused by name, the refusal list is checked against the installed SDK, and native tools are shown absent from the execution pipeline | PASS |
| 7 | a policy-denied call is ledgered `denied` and never reaches the system | PASS |
| 8 | the **streaming** path is not a side door | PASS |
| 9 | a hallucinated tool name finds no dispatcher | PASS |
| 10 | three calls in one step ⇒ three distinct rows, no `tool_call_id` collision | PASS |
| 11 | a body that ran then raised ⇒ `indeterminate`, never `intended` | PASS |
| 12 | **the claim/fence lifecycle**: `intended → claimed → settled`; `indeterminate` requires a claimed row; a stale token is fenced out; a claim requires prior intent | PASS |

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

### Harness mutations — GENERATED, not asserted

The first version listed these counts as prose and got one wrong: it said "dispatch before
ledgering ⇒ 3 gates fail" when the real answer is **7**. The table was written before gates 10
and 11 existed and never re-measured. It is now produced by `mutate.py`, which is committed and
runnable:

```
$ ../../.venv/bin/python mutate.py --check
baseline: 26 passed, 0 failed
```

| Mutation | Removes | Gates broken |
|---|---|---|
| dispatch before ledgering | intent no longer precedes the effect | **7** — gates 3, 4, 7, 10, 11, 12 |
| ignore the policy verdict | a denied call executes anyway | **1** — gate 7 |
| allow uninterceptable registration | `spec/08` row 30c is unenforced | **2** — gate 6 |
| **route tools through `FunctionToolset`** | **the real bypass: the SDK gets an executable body** | **12** — gates 2, 3, 4, 7, 8, 9, 10, 11, 12 |
| drop the claim before dispatch | an effect is dispatched unclaimed | **3** — gates 11, 12 |
| settle `indeterminate` as `intended` | a crashed effect looks like one that never started | **1** — gate 11 |

`--check` exits non-zero if any mutation survives. A **stale-bytecode trap** is worth naming:
two mutations only reorder lines, so file length is unchanged, and CPython invalidates `.pyc`
files on `(mtime, size)` — restoring with `cp` can reproduce a colliding mtime and the
interpreter silently keeps running the mutated bytecode. That is how a clean tree once reported
6 failures. `mutate.py` deletes `__pycache__` before every run.

## A defect this spike found in Phoenix's own design

Gate 11 was written to document behaviour and instead **found a bug**. The first harness left a
crashed effect's row at `intended`. `intended` is indistinguishable from an effect that never
started — so a charge that fired and then lost its connection would have looked like a charge
that never happened. `spec/02-consistency.md:326-348` already says a dispatched effect must
never be left without a verdict; the harness didn't honour it. Fixed: a raising body settles
`indeterminate`, which is the state that surfaces for a human.

## The version pin — claimed, then actually enforced

`pyproject.toml:5-6` uses `uv-dynamic-versioning` and the clone carries **no git tags**, so the
source tree **cannot state its own version**. The version label is `pydantic-ai-slim==2.35.0`;
the assertion is five SHA-256 digests of the files these gates depend on.

**The first version of this document claimed a digest pin and stored no digests.** Review
disproved it in one move: edit `toolsets/external.py`, run the suite, watch all 18 gates still
pass. A pin that is not asserted is a comment.

Now enforced. `pinned_digests.json` holds the five digests and `conftest.py` fails the **whole
session** before any gate runs if the installed SDK differs:

```
$ ../../.venv/bin/python verify_pin.py
pin holds: 5 files byte-identical to the verified SDK
```

Re-running review's own control now aborts collection:

```
toolsets/external.py: expected 47770d0c19453912… got f128ad7952dea705…
```

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
make spike06              # verify_pin.py, then 26 assertions -- part of `make check`
make spike06-mutations    # all six mutations; non-zero if any survives
```

Or directly:

```bash
cd spikes/06-tool-interception
../../.venv/bin/pip install -r requirements.txt
../../.venv/bin/python verify_pin.py                 # pin holds: 5 files
../../.venv/bin/python -m pytest test_gate.py -q     # 26 passed
../../.venv/bin/python mutate.py --check             # every mutation caught
```

**`make check` now runs this spike.** It previously did not, so a green repository gate was
being presented as evidence for assertions it never executed (review's finding). `conftest.py`
checks the digest pin before collection, so the suite cannot silently run against a different
SDK.

No network, no API key, no database: `TestModel` is Pydantic AI's built-in fake model
(`pydantic_ai/models/test.py`), and it calls every registered tool by default, which is what
puts maximum pressure on the bypass question.

Per **rule 7**, this spike writes only inside pytest's `tmp_path` and touches no shared state —
no database, no fixed-name resource, nothing to clean up.

## Still not verified

- **Vendor-hosted tools** remain **unsupported**, and the reason is now tested against the SDK
  rather than against a flag Phoenix invented. Review was right that the first gate 6 asserted on
  `sdk_executable=True` — our own boolean — which is mechanism-shaped evidence. The real path is
  `pydantic_ai.native_tools` (`WebSearchTool`, `CodeExecutionTool`, `FileSearchTool`,
  `ImageGenerationTool`, `MemoryTool`, `WebFetchTool`, `XSearchTool`, `MCPServerTool`,
  `AdvisorTool`, plus `tool_search`), admitted via `Agent.override(native_tools=...)`
  (`agent/__init__.py:1969`) or agent capabilities (`:762`). Three findings make the refusal
  structural: **`_tool_execution.py` contains no reference to `NativeToolCallPart`** — native
  tools never enter the module that runs tool bodies; `TestModel` raises `UserError('TestModel
  does not support built-in tools')` (`models/test.py:252`), i.e. support is a **model**
  property; and so there is no local body for `ExternalToolset` to withhold. Any admission is
  still *provider-reported use* needing a durable receipt.
- **Native `@agent.tool` functions are never used by Phoenix.** This spike proves they are the
  bypass (`FunctionToolset` control) and that we don't need them. It does **not** prove they are
  safe under any wrapping, because that question is now moot.
- **Concurrency.** Gate 10 covers three calls in one step, single-threaded. Two concurrent runs
  competing for one effect key is spike 03's territory, against real Postgres.
- **The in-process/Go boundary.** This spike is Python end to end. `spec/07` says `sdk_in_process`
  collapses to a function call, which cannot hold across a Go control plane and a Python harness.
  Unresolved and now the most urgent open design question.
