# Spike 06 — tool interception on Pydantic AI

**Gate assertions: 53** — the number `README.md` sums. Counts only tests that assert THIS spike's claims through its public boundary; vendored upstream suites are evidence, not our verdict (`VERIFICATION-RULES.md` rule 6).

**Verdict: PASS — OQ-043 is answered, and the mechanism is stronger than the one specified.**
The PASS covers the tool boundary and the effect lifecycle only. Nested agents (S9),
compaction (S10), concurrency and the Go/Python process boundary are **not verified**; they
are listed under "Not verified" below, not folded into this verdict.
**Scoped 2026-08-28 (round 4):** the boundary is verified against a **cooperating in-process
caller**. `h._PhoenixHarness__build()` still returns the `Agent`, and
`override(native_tools=...)` / `override(toolsets=...)` on it bypass the ledger entirely —
gate 13's stated limitation, asserted rather than left absent. A boundary against a **hostile**
in-process caller requires the process split of **OQ-056**.

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

> **Revised 2026-08-28 (round 4) after review returned FAIL a third time.** Nine defects, all
> closed: **(1)** `harness.py` claimed "THE AGENT IS NOT REACHABLE" — it is, through
> `h._PhoenixHarness__build()`, the idiom this spike's own `LeakyHarness` and `mutate.py` use,
> and the scanner skips every `_`-prefixed name so it was blind to the only route that exists;
> **(2)** the headline invariant below claimed *no* path including "the SDK's own `native_tools`
> / `toolsets` surface", which that route falsifies; **(3)** the pin covered sixteen files and
> omitted `models/__init__.py`, where native-tool **admission** is actually decided
> (`resolve_request_tools`), so the admission filter could be neutered with all 47 gates green;
> **(4)** the pin's "independent" coverage oracle never added ancestor package `__init__.py`
> files, so it returned a strict **subset** of the hand-kept list and could not have caught (3);
> **(5)** `capabilities=` is a **third** SDK surface that delivers both native tools and
> executable local bodies, refused only by a catch-all with no gate on it; **(6)** argument
> **binding** happened inside the dispatch `try`, so a call that never dispatched was recorded
> `indeterminate`; **(7)** `RunLease.fence_token` was stored and never read — the fence half of
> `spec/02:248` predicate (b) was absent; **(8)** `append()` had no primary key, so a duplicate
> intent left a second, permanently unreachable row stuck at `intended`; **(9)** a native-tool
> negative control ran a child pytest at `cwd=HERE`, writing caches into a tree it does not own,
> plus stale counts and a wrong `external.py` line number propagated across nine sites.
> Assertions 47 → **53**. Mutations 11 → **14**. Pin 16 → **19** files.

**Date:** 2026-08-28 · **SDK:** `pydantic-ai-slim == 2.35.0` (PyPI), verified byte-identical to
the read source at `b48ee38` across **19** files *(amended 2026-08-28: was "16"; round 4 added
`models/__init__.py`, `profiles/__init__.py` and `capabilities/__init__.py`)*.

## Invariant, stated first

> A registered tool's body executes only after the platform has written an `effect_ledger` row
> for that exact call. There is no path **through the harness's public surface** —
> construction, `register()`, run, resume, approval, streaming, policy denial or a raising
> body — by which a registered tool reaches a customer system without one.
>
> The boundary is scoped to a **cooperating in-process caller**: `h._PhoenixHarness__build()`
> still returns the `Agent`, and `override(native_tools=...)` / `override(toolsets=...)` on it
> bypass the ledger entirely (gate 13's stated limitation). A boundary against a **hostile**
> in-process caller requires the process split of **OQ-056**.

*Amended 2026-08-28 (round 4), superseding — not erasing — the round-3 wording, which read:*
*"There is no path — construction, model-driven call, resume, approval, streaming, policy*
*denial, a raising body, or a caller reaching for the SDK's own `native_tools` / `toolsets`*
*surface — by which a registered tool reaches a customer system without one."* Under rule 1 an
invariant must be checkable by an outsider, and that one was checkable and **false**: review
reached the `Agent` through the ordinary name-mangling idiom, called
`override(toolsets=[FunctionToolset with 'send_email'])`, and the registered tool's **body ran**
with `led.rows == []`. The gate-13 row below was already correctly scoped to "no public name";
the headline was not, so the document contradicted itself.

## The question was framed wrongly, and the answer is better than asked for

OQ-043 and `spec/07` (that text superseded 2026-08-27, now quoted at `spec/07:272-274`) asked
*"can native execution be disabled, by wrapping
`@agent.tool` so the boundary is a decorator rather than a fork?"* That framing assumes Phoenix
must **intercept an executor that wants to run**. It doesn't. Pydantic AI 2.35.0 already has the
shape Phoenix needs, as a first-class supported mechanism:

| Mechanism | Source | What it gives Phoenix |
|---|---|---|
| `ExternalToolset.call_tool` raises `NotImplementedError('External tools cannot be called directly')` **unconditionally** | `toolsets/external.py:46` | a registered tool with **no executable body inside the SDK** |
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
| 0 | **the pin**: 19 SDK digests *(amended 2026-08-28: was 16)*, including `models/__init__.py` and `profiles/__init__.py` — where native-tool **admission** is decided — and `capabilities/__init__.py`; coverage derived from the spike's own imports by `ast`, **ancestor package `__init__.py` files included**; the one-level transitive frontier is recorded and compared, so a pinned file growing a new import fails rather than widening the unexamined surface; a planted digest, a missing file, an empty pin, a doctored frontier and a mismatched pin aborting **collection** are each asserted | PASS |
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
| 11 | a raise **after** dispatch ⇒ `indeterminate`; a raise **before** dispatch ⇒ `failed` with an error code — including *(added 2026-08-28)* arguments that do not **bind** to the impl, the branch a model actually reaches | PASS |
| 12 | **the ledger is `spec/01` `effect_status` and `spec/02`'s phases**: eight statuses and no others; settle requires `claimed` **and** owner **and** token; claim requires an unexpired **run lease** *and, added 2026-08-28, the **fence token** that lease carries (`spec/02:248`)*; a duplicate intent is `ON CONFLICT DO NOTHING`, never a second row *(added 2026-08-28)*; approval, denial and abandonment move only unclaimed rows; the `effect_claim_fields_together` CHECK holds | PASS |
| 13 | **the structural refusal**: no public name on the harness or its `Turn` is, or returns, an `Agent`; `native_tools=`/`toolsets=`/`tools=`/`capabilities=` are refused at the door *(`capabilities=` added 2026-08-28 — the third such surface, and the one that also carries executable **local** bodies)*; a `FunctionModel` recorder is handed an **empty** native-tool list on the buffered, resume and streaming paths | PASS |
| 13b | **the stated limitation**, asserted rather than left absent *(added 2026-08-28)*: `h._PhoenixHarness__build()` **does** return the `Agent`, and `override(toolsets=[...])` on it runs a body with zero ledger rows. Name mangling is not access control | PASS (as a limitation) |

## The oracle is independent (rule 5)

Every tool in the gate writes a line to a **real file** in `tmp_path`. `harness.py` never reads
or writes that file. So every assertion is about an **observable side effect**, not about what
the SDK reports having done.

The pin's *coverage* has its own independent oracle: `verify_pin.sdk_modules_imported_by()`
parses `harness.py` and `test_gate.py` with `ast` and demands that every `pydantic_ai` module
either of them imports from is pinned. A hand-kept list checked against a hand-kept pin would
drift together; import statements cannot.

> **Amended 2026-08-28 (round 4).** That claim was true of the *design* and false of the
> round-3 *implementation*. The oracle mapped each dotted name to a single relpath and never
> added the ancestor package `__init__.py` files Python must execute to perform an import, so
> `from pydantic_ai.models.function import FunctionModel` yielded only `models/function.py`.
> Measured at round 3 it returned exactly **ten** modules — `__init__.py, exceptions.py,
> messages.py, models/function.py, models/test.py, native_tools/__init__.py, tools.py,
> toolsets/{approval_required,external,function}.py` — a strict **subset** of the sixteen
> hand-written `REQUIRED_PINS`, with `'models/__init__.py' in imported` **False**. It therefore
> asserted nothing the hand-kept list did not already assert, and **could not have caught** the
> `models/__init__.py` hole. It now adds every ancestor `__init__.py`, which makes it catch that
> hole on its own (`test_gate0_the_import_oracle_reaches_the_admission_path_on_its_own`).

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
| a frontier entry **dropped** and a frontier entry **invented** ⇒ `frontier_problems()` objects, one problem each | what is deliberately OUT of the pin is checked, not just described |
| `settle()` on an `intended` row, with a wrong token, with no token ⇒ refused | the ledger cannot settle what nobody claimed, or under a claim it does not hold |
| `claim()` with no lease / an expired lease / a foreign holder / another run's lease / **a superseded fence token** / **no fence at all** ⇒ refused, row stays `intended` | `spec/02:246-248` predicate (b) is present and load-bearing |
| a second `resolve()` of the same call ⇒ **one** row, still `succeeded`, body not re-run; a different key still appends | `spec/02:202`'s `ON CONFLICT ... DO NOTHING`, and the guard is a key comparison rather than a blanket refusal |
| `h._PhoenixHarness__build()` + `override(toolsets=[...])` ⇒ the body **runs**, `led.rows == []` | the in-process limitation is real and recorded, not assumed away |
| a `SloppyLedger` that skips `indeterminate` ⇒ gate 11 fails | gate 11 discriminates between the two behaviours |

### Harness mutations — GENERATED, not asserted

```
$ ../../.venv/bin/python mutate.py --check
baseline: 53 passed, 0 failed (in /var/folders/.../spike06-mutations-aaqbmpjs, NOT the live tree)
...
the live tree is byte-identical to where it started
every mutation is caught by at least one gate
```

| Mutation | Removes | Gates broken |
|---|---|---|
| dispatch before ledgering | intent no longer precedes the effect | **10** |
| ignore the policy verdict | a denied call executes anyway | **1** |
| allow uninterceptable registration | `spec/08` row 30c is unenforced | **2** |
| **route tools through `FunctionToolset`** | **the real bypass: the SDK gets an executable body** | **14** |
| **expose the `Agent`** | **the structural refusal: a caller can `override(native_tools=...)`** | **1** |
| accept caller-supplied `native_tools` | vendor-hosted tools reach the model unledgered | **1** |
| drop the claim before dispatch | an effect is dispatched unclaimed | **11** |
| **drop the run-lease predicate** | a worker whose run was reclaimed can still claim and dispatch | **4** |
| drop the settle fence | a stale worker can overwrite the claim holder's verdict | **1** |
| settle `indeterminate` as `intended` | a crashed effect looks like one that never started | **1** |
| **bind arguments inside the dispatch `try`** *(added 2026-08-28)* | a call that never dispatched is reported as uncertain | **1** |
| **drop the intent conflict guard** *(added 2026-08-28)* | the ledger has no primary key: one call, two rows | **1** |
| **drop the fence-token comparison** *(added 2026-08-28)* | a worker holding a superseded fence token can still claim | **1** |
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
GATE1..6_EXIT=0   (53 passed each)
MUT_EXIT=0        (every mutation caught; live tree unchanged)
```

## Simplifications vs spec

The ledger in `harness.py` now uses `spec/01-schema.md:332`'s statuses and
`spec/02-consistency.md:196-322`'s predicates. It is still a Python object, not Postgres. Every
remaining gap, so none of it is discovered later as a surprise:

| # | Simplification | What the spec says | Consequence |
|---|---|---|---|
| 1 | rows are an in-process list | `INSERT ... ON CONFLICT DO NOTHING RETURNING status` (`spec/02:196`) | the **intent race** — two workers deriving the same key — is not exercised here at all. That is spike 03, against real Postgres. *(Amended 2026-08-28: `append()` now honours the KEY — a duplicate intent is a no-op per `spec/02:202-204` — so what is missing is only the concurrent race, not uniqueness itself. Before round 4 it appended unconditionally, so one call could leave two rows, and this row disclosed only the concurrent case.)* |
| 2 | `tool_call_id` is the row key | `idempotency_key = sha256_hex(canon({tenant, run, logical_step_path, request_digest}))` (`spec/01:403`) | replay determinism is untested here: the same logical step re-run gets a **different** key in this harness. |
| 3 | no `tenant_id` | composite PK and FKs on `(tenant_id, ...)` (`spec/01:367`) | cross-tenant isolation is out of scope for this spike. |
| 4 | approval is a boolean `approved=` argument to `claim()` | the approval is a **join inside the same `UPDATE`** (`spec/02:238-243`) | the spec's actual point — that reading approval status and then claiming is the read-then-act race — cannot be demonstrated in-process. Only the ordering is shown. |
| 5 | the run lease is an object handed to `claim()` | `AND EXISTS (SELECT 1 FROM run_leases ...)` inside the same `UPDATE` (`spec/02:246`) | predicates (a) and (b) are checked in sequence, not atomically. The *predicate* is verified; its *atomicity* is not. *(Corrected 2026-08-28: the citation was `spec/02:245`, the prose comment above the SQL; `:246` is the `AND EXISTS` line, matching `harness.py`.)* |
| 6 | policy denial moves `intended → denied` | `denied` moves an `awaiting_approval` row — an approver refused, or the approval expired (`spec/02:311`) | a deliberate divergence: Phoenix's synchronous policy verdict has no human, so the row never reaches `awaiting_approval`. Both routes end at a never-claimed `denied` row, which is what the invariant needs. |
| 7 | no sweeper | `effect_ledger_stuck` indexes `status='claimed'` by `lease_expires_at`, so an expired claim becomes `indeterminate` (`spec/01:389`) | `indeterminate` is only ever written **by the dispatch path** here. The lease-expiry route to `indeterminate` is unverified. |
| 8 | `abandoned` is written only for "no platform dispatcher" | also for "the run ended, or the intent was superseded" (`spec/02:321`) | the other route has no code and no test. |
| 9 | `completed_at` is `time.monotonic()`; no `attempt`, `request_digest`, `result_ref` indirection | `spec/01:344-364` | the CHECK relating `completed_at` to `succeeded`/`failed` **is** enforced; the columns themselves are stand-ins. |
| 10 | `LedgerRefused` is raised | the real refusal is a **zero-row `UPDATE`** | a caller that ignored the SQL row count would proceed; here it cannot. The in-process version is **stricter** than the deployed one, which is the direction that hides bugs rather than creating them. |
| 11 | single-threaded | — | no two workers ever race for one claim. |
| 12 | the run lease is **minted by the claimant** on the default dispatch route (`_lease_for`) | a `run_leases` row written by whoever won the run | *(added 2026-08-28)* on that route predicate (b) cannot fail: `dispatch` sets `owner = lease.holder` and passes `fence = lease.fence_token` from the lease it just minted, so run-id, holder and fence all hold **by construction**. The predicate is load-bearing only for a caller that volunteers a lease — which is what every negative control does, explicitly. Proposed **OQ-057**. |
| 13 | the boundary is enforced against a **cooperating** in-process caller | — | *(added 2026-08-28)* `h._PhoenixHarness__build()` returns the `Agent` through the ordinary name-mangling idiom — the same one `LeakyHarness` and `mutate.py` use — and `override(native_tools=...)` / `override(toolsets=...)` on it deliver a native tool to the model, or run a registered body, with **zero** ledger rows. `agents_reachable_from` skips every `_`-prefixed name, so gate 13's scan is a statement about PUBLIC names only. Name mangling is not access control. Asserted as a limitation by `test_gate13_the_mangled_accessor_is_a_known_limitation`; a hostile-caller boundary needs the process split of **OQ-056**. |

## The version pin — 19 files, and the holes review found

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
native_tools/{__init__,_tool_search}.py  models/{__init__,function,test}.py
profiles/__init__.py  capabilities/__init__.py
```

and `test_gate.py` additionally requires that **every SDK module `harness.py` or `test_gate.py`
imports from** is in that set, derived by `ast` from the import statements themselves. The five
digests round 2 recorded are **unchanged** in the new file, which is independent confirmation
that this is the same installed SDK.

> **Round 4 found the same hole one level up, 2026-08-28.** Sixteen files still omitted
> `models/__init__.py`, which is where native-tool **admission** is actually decided:
> `ModelRequestParameters.native_tools` (`models/__init__.py:179`) is the exact object gate 13's
> recorder asserts is empty, and `resolve_request_tools` (`:1812-1930`) is what filters native
> tools against `supported_native_tools` and raises
> `UserError('Native tool(s) ... not supported by this model')` at `:1849`. Review reproduced
> the round-2 defect verbatim, in a **scratch copy** of the SDK (live `site-packages` untouched,
> rule 7): replace the admission filter with `supported_natives = list(params.native_tools)` and
> `verify_pin.py` still printed *"pin holds: 16 files"* while `pytest test_gate.py -q` printed
> *"47 passed"*. `profiles/__init__.py` (the source of `supported_native_tools`) and
> `capabilities/__init__.py` (the third tool-delivering surface, gate 13) are pinned for the
> same reason.
>
> **What is deliberately OUT of the pin is now stated and checked.** A one-level transitive walk
> from the pinned files reaches 106 further modules; the full closure is effectively the whole
> distribution (284 modules, including every vendor model adapter — `models/anthropic.py`,
> `models/bedrock.py` and the rest — reached only because `models/__init__.py` names them, and
> none of which any assertion here touches). Pinning those would turn the gate red for edits
> that cannot affect the boundary. Instead `pinned_digests.json:_coverage_frontier` records that
> edge and `check()` compares it on every run, so a **pinned file growing a new import** into a
> module nobody has examined is a decision someone has to make rather than a silent widening.

```
$ ../../.venv/bin/python verify_pin.py
pin holds: 19 files byte-identical to the verified SDK
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
| external tools have no executable body | `toolsets/external.py:46 @ b48ee38` |
| external tools are still advertised to the model | `toolsets/external.py:36 @ b48ee38` |
| a deferred run ends and returns pending calls | `_deferred.py:27,37 @ b48ee38` |
| results are supplied back on resume | `agent/__init__.py:1139 @ b48ee38` |
| approval is checked before delegation | `toolsets/approval_required.py:29 @ b48ee38` |
| **external kinds execute on the resume path** | `_tool_execution.py:399 @ b48ee38` |
| `native_tools=` is admitted by `override` | `agent/__init__.py:1969 @ b48ee38` |
| **native-tool ADMISSION is decided in `models/`, not `native_tools/`** | `models/__init__.py:179` (the `native_tools` parameter) and `:1812-1930` / `:1849` (`resolve_request_tools`) `@ b48ee38` |
| **`capabilities=` is a third public route that delivers tools** | `agent/__init__.py:618-631`, auto-injection at `:630` / `_inject_auto_capabilities` `@ b48ee38` |
| `capabilities` exports carry LOCAL executable bodies (`Toolset`, `MCP(local=True)`, `WebSearch(local=...)`) | `capabilities/__init__.py @ b48ee38` |
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
make spike06              # verify_pin.py, then 53 assertions -- part of `make check`
make spike06-mutations    # all fourteen mutations; non-zero if any survives
```

Or directly:

```bash
cd spikes/06-tool-interception
../../.venv/bin/pip install -r requirements.txt
../../.venv/bin/python verify_pin.py                 # pin holds: 19 files
../../.venv/bin/python -m pytest test_gate.py -q     # 53 passed
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

> **Corrected 2026-08-28 (round 4).** That paragraph was categorically false as written, and
> the counter-example was in this spike: `test_gate6_negative_control_a_new_native_tool_subclass_turns_the_gate_red`
> spawned its child pytest with `cwd=HERE` — the **live** spike directory — so the child wrote
> `__pycache__/` and `.pytest_cache/` into a tree the test does not uniquely own while the
> parent session was running there too. Non-destructive, and six concurrent runs were green, so
> it was never a cross-interference failure; but the two neighbouring controls
> (`..._a_mismatched_pin_aborts_COLLECTION`, `test_rule7_the_mutation_runner_never_writes_to_the_live_tree`)
> already ran in an owned `copy_spike(tmp_path / "spike")` for exactly this reason, and the
> asymmetry was undocumented. That child now runs in an owned copy too, which makes the
> paragraph above true rather than aspirational.

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
