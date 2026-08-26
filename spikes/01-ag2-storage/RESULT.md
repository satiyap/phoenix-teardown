# Spike 01 — AG2 storage swap

**Verdict: CONDITIONAL PASS — integrate with a documented replacement of one
method.** Not the unqualified PASS I first claimed.
**Date:** 2026-08-26 · **Revised** after external review found the first verdict
unsupported.

## What was wrong with the first attempt

The original `test_oq024.py` **never called `Hub.find_envelope_by_causation()`**. It
fabricated JSONL, cleared a local dict I had created myself, and scanned the WAL by
hand. That is a tautology dressed as a gate. The reviewer was right, and the
`RESULT.md` reproduce command also omitted the one file that was failing
(`test_gate.py`, which passed strings where AG2 wants `Agent` objects).

Both files are deleted. `test_gate_real.py` replaces them and uses the public API
only. **5/5 pass**, and they produced a finding the fake test could not.

## Criterion 1 — does the hub run on our storage? **Yes.**

`Hub.open(store, ...)` takes a `KnowledgeStore`, a `runtime_checkable` `Protocol`
with eight methods. `SqlKnowledgeStore` (SQLite, ~90 lines) satisfies it structurally
— no fork, no subclass.

AG2's **own** network suite, with `MemoryKnowledgeStore` swapped for a counting
subclass of ours:

```
480 passed, 1 deselected in 8.80s
append() 1789 · read() 332 · write() 3731 · 201 distinct channel WALs
```

The counters prove the swap took effect rather than being bypassed. The deselected
test is a source-linter that reads AG2's own file by relative path, broken by copying
tests out of the repo.

**Caveat the review is right about:** this proves *`KnowledgeStore` compatibility*,
not that our production log is ready. `sqlstore.py` keeps each WAL as one growing
BLOB and rewrites it per append — fine for a compatibility proof, wrong for
production. Row-oriented storage, Postgres contention, indexing, retention and
transaction boundaries are **untested**. There is no concurrent-writer test.

## Criterion 2 — causation after termination: **the defect is worse than documented, and the fix is not free**

Tested against the real method, five scenarios:

| Scenario | `find_envelope_by_causation` | Durable WAL |
|---|---|---|
| Channel open | **FOUND** (correct) | — |
| After `close_channel` | `None` | — |
| After Hub restart on same store | `None` | 6 envelopes readable |
| Two hubs that hydrated **before** close | **FOUND** (both) | — |
| Fresh hub started **after** close | `None` | **reply present, 1 causation match** |

The mechanism, in AG2's own comment (`hub/core.py:2907-2911`):

```python
# Repopulate the causation index for active channels; terminal
# channels have already had their entries pruned when they
# closed and shouldn't reappear here.
if not metadata.is_terminal() and envelope.causation_id and envelope.envelope_id:
```

So the horizon is **not** merely "process-local cache lost on restart". Hydrate
**deliberately refuses** to rebuild the index for terminal channels. The last row is
the one that matters: the index says `None` while the durable log contains exactly
one matching envelope. `None` therefore means "no duplicate **or** cannot tell", and
the caller cannot distinguish them — the `absent`/`unknown` conflation, inside the
dedupe path.

Test 4 is instructive about my own reasoning: it passed, and for the wrong reason.
Both hubs hydrated *before* the close. Test 5 exists because I did not trust that.

## What this means for the integration decision

The gate required keeping the hub contract **intact**. Satisfying OQ-024 requires
**changing the public semantics** of one method from `Envelope | None` to three
valued. So the honest verdict is not "integrate unmodified":

**Integrate `ag2.network` for the `Envelope` schema, hub contract, channel protocols
and delivery machinery — and replace `find_envelope_by_causation` with our own
log-backed implementation returning `FOUND | NOT_FOUND | INDETERMINATE`.**

That is a **maintained adapter**, not a clean dependency, and it carries an ongoing
cost: AG2 may change the pruning behaviour or the index shape under us. Recorded as
a risk rather than waved away.

The alternative — port the `Envelope` schema and build the hub ourselves — remains
open and is more expensive. The deciding factor is that 480 passing tests represent
delivery, cursor, replay, expectation and adapter machinery we would otherwise write.

## What is still untested (the review's point 4, which stands)

Storage is one part of the risk. AG2's hub also owns passports, rules, channel state,
adapter folds, tasks, indexes and dispatch, all in process memory. **Not tested:**

- concurrent causation duplicates across two live hubs
- tenant scoping (AG2 has none — our `tenant_id` must wrap it)
- coexistence with our `Principal`, Cedar policy, and effect-ledger authority
- write contention on one store from two hubs
- whether two hubs can safely serve the *same* channel at all

**A database-backed WAL does not make an in-memory authority horizontally safe.**
That question is deferred to the implementation spec, which must decide whether one
hub per channel is an invariant we enforce.

## Reproduce

```bash
cd spikes/01-ag2-storage
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m pytest test_gate_real.py -q --asyncio-mode=auto -s   # 5 passed
```

`requirements.txt` pins `ag2==1.0.2` and records the source commit
(`90f490a1b72b27ab4c219dd3586e94d42383a016`). The 480-test upstream run additionally
needs AG2's `test/` tree copied in, which is **not** reproducible from this checkout
alone — a real weakness of that evidence, and the reason the 5-test public-API gate
is the one that carries the verdict.

## Files

| File | What it is |
|---|---|
| `sqlstore.py` | `SqlKnowledgeStore` — the 8-method Protocol over SQLite |
| `test_gate_real.py` | **The gate.** Public API only, 5 scenarios |
| `conftest.py` | Swaps AG2's store for a counting subclass (upstream-suite run) |
| `requirements.txt` | Pinned deps + AG2 source commit |
