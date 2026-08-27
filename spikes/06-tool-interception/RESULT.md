# Spike 06 — tool interception on Pydantic AI

**Gate assertions: 47** — the number `README.md` sums. Counts only tests that assert THIS spike's claims through its public boundary; vendored upstream suites are evidence, not our verdict (`VERIFICATION-RULES.md` rule 6).

**Verdict: PASS — OQ-043 is answered, and the mechanism is stronger than the one specified.**
The PASS covers the tool boundary and the effect lifecycle only. Nested agents (S9),
compaction (S10), concurrency and the Go/Python process boundary are **not verified**; they
are listed under "Not verified" below, not folded into this verdict.

> **Revised 2026-08-27 (round 3) after review returned FAIL a second time — again on the
> verification, not the discovery.** Six defects, all closed:
> **(1)** the pin covered five files while native-tool admission was decided by an **unpinned**
> `native_tools/__init__.py`; **(2)** the native-tool enumeration wrapped construction in a bare
> `except Exception: pass`, so `AdvisorTool`, `FileSearchTool` and `MCPServerTool` — three real
> vendor-hosted tools — were **silently skipped**, and `ToolSearchTool` was never seen at all;
> **(3)** `build_agent()` returned a **raw `Agent`**, so `agent.override(native_tools=[WebSearchTool()])`
> against `FunctionModel` delivered a vendor-hosted tool to the model with no Phoenix
> involvement — the old gate proved only that `TestModel` lacks built-in tool support;
> **(4)** the ledger used a status `settled` that `spec/01-schema.md:332` does not define,
> allowed `intended → settled` with no claim, owner or token, and had **no run-lease
> predicate**; **(5)** `mutate.py` rewrote the **live** harness in place, a rule-7 ownership
> violation that broke concurrent runs; **(6)** stale counts and framings in `open-questions.md`,
> `synthesis/scope-reconciliation.md` and `spec/07`.
> Assertions 26 → **47**. Mutations 6 → **11**.

**Date:** 2026-08-27 · **SDK:** `pydantic-ai-slim == 2.35.0` (PyPI), verified byte-identical to
the read source at `b48ee38` across **16** files.

## Invariant, stated first

> A registered tool's body executes only after the platform has written an `effect_ledger` row
> for that exact call. There is no path — construction, model-driven call, resume, approval,
> streaming, policy denial, a raising body, or a caller reaching for the SDK's own
> `native_tools` / `toolsets` surface — by which a registered tool reaches a customer system
> without one.

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
monkey-patched: the tool is *declared* to the model and the SDK is given no way to run it.

## What round 2 got wrong about that, and why it mattered

The toolset argument is sound and it is **not sufficient on its own**, because round 2 handed
the caller the `Agent`:

```python
agent = harness.build_agent(model)                       # round 2's public surface
with agent.override(native_tools=[WebSearchTool()]):     # agent/__init__.py:1969
    agent.run_sync("search the web")
```

Against `TestModel` that raises `UserError('TestModel does not support built-in tools')`
(`models/test.py:252`), which is what the old gate 6 asserted — a fact about **`TestModel`**.
`FunctionModel.supported_native_tools()` returns `SUPPORTED_NATIVE_TOOLS`
(`models/function.py:242-244`), and against it the same three lines deliver the tool:

```
DELIVERED: [(WebSearchTool(kind='web_search', ...),)]
```

That is reproduced as gate 13's negative control (`LeakyHarness`), and it is why the harness now
has **no public name that is, or returns, an `Agent`**. The public surface is
`register` / `run` / `resume` / `stream_output` / `resolve`; `native_tools=`, `toolsets=` and
`tools=` are refused at the constructor and at `register()`.

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
| 0 | **the pin**: 16 SDK digests; coverage derived from the spike's own imports by `ast`; a planted digest, a missing file, an empty pin and a mismatched pin aborting **collection** are each asserted | PASS |
| 1 | zero registered tools ⇒ no executable path, no ledger rows | PASS |
| 2 | a registered tool ⇒ run **ends** on the deferred call, body never runs | PASS |
| 3 | the ledger row is written **before** execution, exactly one per call | PASS |
| 4 | **resume** consumes the platform result without re-executing the body | PASS |
| 5 | `ApprovalRequired` halts before execution | PASS |
| 6 | row 30c is executable: **every `AbstractNativeTool` subclass the SDK defines** is instantiated with generated minimal arguments and refused by name; a class that cannot be built is a HARD FAIL; the refusal list is compared to the SDK registry **in both directions** | PASS |
| 7 | a policy-denied call is ledgered `denied`, never claimed, never dispatched | PASS |
| 8 | the **streaming** path is not a side door | PASS |
| 9 | a hallucinated tool name finds no dispatcher ⇒ `abandoned`, never `failed` | PASS |
| 10 | three calls in one step ⇒ three distinct rows, no `tool_call_id` collision | PASS |
| 11 | a raise **after** dispatch ⇒ `indeterminate`; a raise **before** dispatch ⇒ `failed` with an error code | PASS |
| 12 | **the ledger is `spec/01` `effect_status` and `spec/02`'s phases**: eight statuses and no others; settle requires `claimed` **and** owner **and** token; claim requires an unexpired **run lease**; approval, denial and abandonment move only unclaimed rows; the `effect_claim_fields_together` CHECK holds | PASS |
| 13 | **the structural refusal**: no public name on the harness or its `Turn` is, or returns, an `Agent`; `native_tools=`/`toolsets=`/`tools=` are refused at the door; a `FunctionModel` recorder is handed an **empty** native-tool list on the buffered, resume and streaming paths | PASS |

## The oracle is independent (rule 5)

Every tool in the gate writes a line to a **real file** in `tmp_path`. `harness.py` never reads
or writes that file. So every assertion is about an **observable side effect**, not about what
the SDK reports having done.

The pin's *coverage* has its own independent oracle: `verify_pin.sdk_modules_imported_by()`
parses `harness.py` and `test_gate.py` with `ast` and demands that every `pydantic_ai` module
either of them imports from is pinned. A hand-kept list checked against a hand-kept pin would
drift together; import statements cannot.

## Negative controls (rule 4)

| Control | Proves |
|---|---|
| control 0 — the side channel fires on a real call | the detector is not inert |
| **`FunctionToolset` with the same function** ⇒ body runs, **zero ledger rows** | `spec/08` row 30a's bypass, **demonstrated** rather than asserted |
| resume with a fabricated result and **no** platform dispatch ⇒ side channel empty | gate 4's green comes from our dispatch, not from SDK incidentals |
| approval **granted** ⇒ the body does run | gate 5's empty channel was the approval gate, not an inert tool |
| **`LeakyHarness` re-exposes the `Agent`** ⇒ `override(native_tools=[WebSearchTool()])` succeeds and the recorder sees the tool | gate 13's empty recorder is caused by the harness's shape, not by the SDK |
| **a `FakeVendorTool` subclass registered in a child process** ⇒ gate 6 goes red (`2 failed`, naming `fake_vendor_search`) | the enumeration would catch a native tool a future SDK adds |
| a planted digest / a missing file / an empty pin ⇒ `check()` objects; a mismatched pin ⇒ **collection aborts, exit 3** | the pin is asserted, not described |
| `settle()` on an `intended` row, with a wrong token, with no token ⇒ refused | the ledger cannot settle what nobody claimed, or under a claim it does not hold |
| `claim()` with no lease / an expired lease / a foreign holder / another run's lease ⇒ refused, row stays `intended` | `spec/02:245` predicate (b) is present and load-bearing |
| a `SloppyLedger` that skips `indeterminate` ⇒ gate 11 fails | gate 11 discriminates between the two behaviours |

### Harness mutations — GENERATED, not asserted

```
$ ../../.venv/bin/python mutate.py --check
baseline: 47 passed, 0 failed (in /var/folders/.../spike06-mutations-2i5es24b, NOT the live tree)
...
the live tree is byte-identical to where it started
every mutation is caught by at least one gate
```

| Mutation | Removes | Gates broken |
|---|---|---|
| dispatch before ledgering | intent no longer precedes the effect | **9** |
| ignore the policy verdict | a denied call executes anyway | **1** |
| allow uninterceptable registration | `spec/08` row 30c is unenforced | **2** |
| **route tools through `FunctionToolset`** | **the real bypass: the SDK gets an executable body** | **13** |
| **expose the `Agent`** | **the structural refusal: a caller can `override(native_tools=...)`** | **1** |
| accept caller-supplied `native_tools` | vendor-hosted tools reach the model unledgered | **1** |
| drop the claim before dispatch | an effect is dispatched unclaimed | **9** |
| **drop the run-lease predicate** | a worker whose run was reclaimed can still claim and dispatch | **3** |
| drop the settle fence | a stale worker can overwrite the claim holder's verdict | **1** |
| settle `indeterminate` as `intended` | a crashed effect looks like one that never started | **1** |
| call a raise **after** dispatch `failed` | an effect of unknown outcome is reported as one that provably did not happen | **2** |

`--check` exits non-zero if any mutation survives.

**Rule 7, and the bug it caught here.** The previous `mutate.py` rewrote `harness.py` **in the
live tree** and restored it in a `finally`. For the duration of a run, a shared working tree
contained a deliberately broken harness, so a concurrent `make spike06` imported code nobody
wrote — and it also needed a `__pycache__` workaround, because two mutations only reorder lines
(same byte length) and CPython invalidates `.pyc` on `(mtime, size)`, so a restore with a
colliding mtime left the interpreter running **mutated bytecode**. Both problems are gone:
`mutate.py` now copies the spike into a fresh `tempfile.mkdtemp()` directory per mutation,
which it uniquely owns and deletes, and asserts afterwards that the live `harness.py` is
byte-identical to where it started.

Proved, not asserted — mutations and six gate runs, concurrently:

```
$ (python mutate.py --check &) ; for i in 1..6; do make spike06; done
GATE1..6_EXIT=0   (47 passed each)
MUT_EXIT=0        (every mutation caught; live tree unchanged)
```

## Simplifications vs spec

The ledger in `harness.py` now uses `spec/01-schema.md:332`'s statuses and
`spec/02-consistency.md:196-322`'s predicates. It is still a Python object, not Postgres. Every
remaining gap, so none of it is discovered later as a surprise:

| # | Simplification | What the spec says | Consequence |
|---|---|---|---|
| 1 | rows are an in-process list | `INSERT ... ON CONFLICT DO NOTHING RETURNING status` (`spec/02:196`) | the **intent race** — two workers deriving the same key — is not exercised here at all. That is spike 03, against real Postgres. |
| 2 | `tool_call_id` is the row key | `idempotency_key = sha256_hex(canon({tenant, run, logical_step_path, request_digest}))` (`spec/01:403`) | replay determinism is untested here: the same logical step re-run gets a **different** key in this harness. |
| 3 | no `tenant_id` | composite PK and FKs on `(tenant_id, ...)` (`spec/01:367`) | cross-tenant isolation is out of scope for this spike. |
| 4 | approval is a boolean `approved=` argument to `claim()` | the approval is a **join inside the same `UPDATE`** (`spec/02:238-243`) | the spec's actual point — that reading approval status and then claiming is the read-then-act race — cannot be demonstrated in-process. Only the ordering is shown. |
| 5 | the run lease is an object handed to `claim()` | `AND EXISTS (SELECT 1 FROM run_leases ...)` inside the same `UPDATE` (`spec/02:245`) | predicates (a) and (b) are checked in sequence, not atomically. The *predicate* is verified; its *atomicity* is not. |
| 6 | policy denial moves `intended → denied` | `denied` moves an `awaiting_approval` row — an approver refused, or the approval expired (`spec/02:311`) | a deliberate divergence: Phoenix's synchronous policy verdict has no human, so the row never reaches `awaiting_approval`. Both routes end at a never-claimed `denied` row, which is what the invariant needs. |
| 7 | no sweeper | `effect_ledger_stuck` indexes `status='claimed'` by `lease_expires_at`, so an expired claim becomes `indeterminate` (`spec/01:389`) | `indeterminate` is only ever written **by the dispatch path** here. The lease-expiry route to `indeterminate` is unverified. |
| 8 | `abandoned` is written only for "no platform dispatcher" | also for "the run ended, or the intent was superseded" (`spec/02:321`) | the other route has no code and no test. |
| 9 | `completed_at` is `time.monotonic()`; no `attempt`, `request_digest`, `result_ref` indirection | `spec/01:344-364` | the CHECK relating `completed_at` to `succeeded`/`failed` **is** enforced; the columns themselves are stand-ins. |
| 10 | `LedgerRefused` is raised | the real refusal is a **zero-row `UPDATE`** | a caller that ignored the SQL row count would proceed; here it cannot. The in-process version is **stricter** than the deployed one, which is the direction that hides bugs rather than creating them. |
| 11 | single-threaded | — | no two workers ever race for one claim. |

## The version pin — 16 files, and the hole review found

`pyproject.toml:5-6` uses `uv-dynamic-versioning` and the clone carries **no git tags**, so the
source tree **cannot state its own version**. The version label is `pydantic-ai-slim==2.35.0`;
the assertion is SHA-256 digests.

Round 1 claimed a digest pin and stored none. Round 2 stored five — and left
`native_tools/__init__.py` unpinned **while gate 6 reads that module to decide which tools may
be admitted**, so review's original control (edit an SDK file, watch every gate pass) worked
again on the one module that governs admission. The pin now covers `verify_pin.REQUIRED_PINS`:

```
__init__.py  agent/__init__.py  _tool_execution.py  _deferred.py  tools.py  messages.py
exceptions.py  toolsets/{__init__,abstract,external,approval_required,function}.py
native_tools/{__init__,_tool_search}.py  models/{function,test}.py
```

and `test_gate.py` additionally requires that **every SDK module `harness.py` or `test_gate.py`
imports from** is in that set, derived by `ast` from the import statements themselves. The five
digests round 2 recorded are **unchanged** in the new file, which is independent confirmation
that this is the same installed SDK.

```
$ ../../.venv/bin/python verify_pin.py
pin holds: 16 files byte-identical to the verified SDK
```

`conftest.py` fails the **whole session** before any gate runs on any mismatch, and
`test_gate0_negative_control_a_mismatched_pin_aborts_COLLECTION` asserts that in a copy of the
spike it owns:

```
toolsets/external.py: expected 0000000000000000… got 47770d0c19453912…   [exit 3]
```

## A defect this spike found in Phoenix's own design

Gate 11 was written to document behaviour and instead **found a bug**. The first harness left a
crashed effect's row at `intended`. `intended` is indistinguishable from an effect that never
started — so a charge that fired and then lost its connection would have looked like a charge
that never happened. Round 3 completes it in the other direction: a raise **before** the body is
entered is `failed` with an error code, because that outcome **is** known, and sending a human
to investigate an effect that provably did not happen is its own failure.

## Cited claims

| Claim | Citation |
|---|---|
| external tools have no executable body | `toolsets/external.py:44 @ b48ee38` |
| external tools are still advertised to the model | `toolsets/external.py:36 @ b48ee38` |
| a deferred run ends and returns pending calls | `_deferred.py:27,37 @ b48ee38` |
| results are supplied back on resume | `agent/__init__.py:1139 @ b48ee38` |
| approval is checked before delegation | `toolsets/approval_required.py:29 @ b48ee38` |
| **external kinds execute on the resume path** | `_tool_execution.py:399 @ b48ee38` |
| `native_tools=` is admitted by `override` | `agent/__init__.py:1969 @ b48ee38` |
| **`FunctionModel` SUPPORTS every native tool** | `models/function.py:242-244 @ b48ee38` |
| `TestModel` refuses built-in tools (a fact about `TestModel`) | `models/test.py:252 @ b48ee38` |
| every native tool class registers itself by `kind` | `native_tools/__init__.py:107-109 @ b48ee38` |
| `ToolSearchTool` is registered but **not re-exported** | `native_tools/__init__.py:751-756 @ b48ee38` |
| `effect_status` has eight values and no `settled` | `spec/01-schema.md:332` |
| claim requires the run lease | `spec/02-consistency.md:227-247` |
| settle is fenced by owner + token + `status='claimed'` | `spec/02-consistency.md:294-303` |
| `tool` decorator implementation / usage | `agent/__init__.py:2423` / `:2460 @ b48ee38` |

## Reproduce

```bash
make spike06              # verify_pin.py, then 47 assertions -- part of `make check`
make spike06-mutations    # all eleven mutations; non-zero if any survives
```

Or directly:

```bash
cd spikes/06-tool-interception
../../.venv/bin/pip install -r requirements.txt
../../.venv/bin/python verify_pin.py                 # pin holds: 16 files
../../.venv/bin/python -m pytest test_gate.py -q     # 47 passed
../../.venv/bin/python mutate.py --check             # every mutation caught
```

No network, no API key, no database: `TestModel` is Pydantic AI's built-in fake model, and it
calls every registered tool by default, which is what puts maximum pressure on the bypass
question. `FunctionModel` is used where the assertion needs a model that **does** support native
tools.

Per **rule 7**, every write this spike makes is inside a directory the writing process created:
pytest's `tmp_path` for the gates, `tempfile.mkdtemp()` for `mutate.py`. No shared state, no
database, no fixed-name resource. Six `make spike06` runs concurrent with a full mutation run
are all green.

## Not verified

Stated as unverified, not as "probably fine" (`VERIFICATION-RULES.md`, verdict vocabulary).

- **S9 — nested agents. NOT VERIFIED.** `spec/00-overview.md:49` names `toolsets/` (nested
  agents) as one of the Pydantic AI seams Phoenix must have a policy over. This spike registers
  tools on one agent. Whether a **delegated sub-agent** can be constructed inside a Phoenix run
  with a toolset the platform did not supply — and whether its tool calls cross the same ledger
  boundary — is untested. Nothing here rules it out as a bypass.
- **S10 — compaction. NOT VERIFIED.** `spec/00-overview.md:49` names `process_history.py`
  (compaction); `spec/00:76` and `spec/03-canonicalisation.md:263` require that compaction must
  not change the safety guarantee for an unrelated external effect. A history processor sits on
  the message list that carries the pending `ToolCallPart`s and their `tool_call_id`s, i.e.
  exactly what `resume` matches results against. This spike never installs one.
- **Concurrency.** Gate 10 covers three calls in one step, single-threaded. Two concurrent runs
  competing for one effect key is spike 03's territory, against real Postgres.
- **The lease-expiry route to `indeterminate`.** No sweeper (simplification 7).
- **Vendor-hosted tools** remain **unsupported**, and the refusal is now tested against every
  `AbstractNativeTool` subclass the SDK defines, each one instantiated. Three findings make it
  structural: **`_tool_execution.py` contains no reference to `NativeToolCallPart`** — native
  tools never enter the module that runs tool bodies; support is a **model** property
  (`models/{test,function}.py`); and so there is no local body for `ExternalToolset` to
  withhold. Any future admission is still *provider-reported use* needing a durable receipt.
- **Native `@agent.tool` functions are never used by Phoenix.** This spike proves they are the
  bypass (`FunctionToolset` control) and that we don't need them. It does **not** prove they are
  safe under any wrapping, because that question is now moot.
- **The in-process/Go boundary.** This spike is Python end to end. `spec/07` says
  `sdk_in_process` collapses to a function call, which cannot hold across a Go control plane and
  a Python harness. Unresolved: **OQ-056**, the most urgent open design question here.
