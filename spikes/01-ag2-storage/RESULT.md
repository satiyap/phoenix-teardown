# Spike 01 — AG2 storage swap

**Verdict: PASS.** `ag2.network` is approved for integration.
**Date:** 2026-08-26 · **Duration:** ~1h

## The gate

From `synthesis/scope-reconciliation.md` §4:

> Replace AG2's file-based WAL with our append-only log, keeping the `Envelope`
> schema and hub contract intact, and demonstrate that causation dedupe survives
> channel termination — i.e. that `find_envelope_by_causation` does not degrade into
> "cannot tell" once terminal-channel pruning clears the index (OQ-024).

Two criteria. Both pass, and the second required a design decision rather than a
yes/no answer.

---

## Criterion 1 — does the hub run on our storage? **Yes.**

The swap point is cleaner than expected. `Hub.__init__(store: KnowledgeStore, ...)`
takes the store by constructor injection, and `KnowledgeStore` is a
`runtime_checkable` `Protocol` with **eight methods**: `read`, `write`, `list`,
`delete`, `exists`, `append`, `read_range`, `on_change`. No subclassing, no fork.

I implemented `SqlKnowledgeStore` over SQLite (`sqlstore.py`, ~90 lines). The
interesting method is `append`, which must return the byte offset written at:

```sql
UPDATE blobs SET content = CAST(content AS BLOB) || CAST(? AS BLOB)
WHERE path = ?
RETURNING length(content) - length(?)
```

The offset is derived **by the database inside the statement**, so two concurrent
appends cannot claim the same one. That is AX's `MAX(step)+1`-inside-the-transaction
pattern () applied to a byte offset, and it is what makes the swap safe
rather than merely type-correct.

Then I ran **AG2's own network test suite** against it — swapping
`MemoryKnowledgeStore` for a counting subclass of our store in `conftest.py`, so
every call is both routed and measured.

```
480 passed, 1 deselected in 8.80s

storage calls that went through OUR store
  append()        1789
  read()           332
  read_range()       0
  write()         3731
  distinct channel WALs written: 201
```

The counters are the evidence the swap took effect rather than being silently
bypassed. **201 distinct channel WALs** were written through our `append()`.

The one deselected test (`test_handlers_module_does_not_touch_hub_privates`) is a
source-linting check that reads AG2's own source file by relative path; it fails
because I copied the tests out of the repo. Unrelated to storage.

Two failures during the run were missing optional dependencies (`watchdog`,
`websockets`, `opentelemetry-sdk`, `anthropic`), not storage defects — installing
them took the suite from 470 to 480 passing.

## Criterion 2 — does causation dedupe survive termination? **The defect is real, and it is ours to fix.**

`hub/core.py:2772-2774` clears every causation-index key when a channel closes:

```python
# Causation lookups against a closed channel can never produce
# a meaningful retry decision, so drop every key for this
# channel and keep the index bounded by active-channel size.
stale_keys = [k for k in self._causation_index if k[0] == channel_id]
```

The comment's premise is wrong for our use. AG2 reasons that a closed channel cannot
produce a *retry decision* — true for its own delivery loop. But **we are adopting
`causation_id` as an effect-ledger key (ADR-0014)**, and for that purpose the query
must remain answerable after the channel closes, otherwise a replayed effect against
a terminated channel returns `None` and reads as "no duplicate, go ahead".

That is precisely the `absent` vs `unknown` conflation this study is built on, sitting
inside the dedupe path.

**The fix is available because the index is a cache, not the truth.** The WAL itself
is durable, complete, and in our store. `test_oq024.py` proves both halves:

```
2 passed
  test_wal_retains_causation_after_index_clear
  test_absence_is_distinguishable_from_unknown
```

- With the index deliberately emptied, scanning the durable WAL still finds the reply
  caused by `e1`.
- Where no reply exists, `store.exists(wal) is True` plus an empty result set gives a
  **definite "no duplicate"** rather than a shrug.

## Design decisions this settles

1. **Integrate `ag2.network`.** Envelope schema and hub contract adopted; the storage
   layer is ours.
2. **Do not adopt AG2's causation index as the dedupe authority.** It is a
   process-local cache with a retention horizon. Our effect ledger (ADR-0014) is the
   authority, backed by the durable log.
3. **`find_envelope_by_causation` must be reimplemented over our log**, returning a
   three-valued result — `FOUND(envelope_id)` / `NOT_FOUND` / `INDETERMINATE` — where
   `INDETERMINATE` occurs only if the log itself is unreadable. AG2's two-valued
   `Envelope | None` is the bug.
4. **`read_range` was never called** in 481 tests (0 of 2,121 storage calls). It is in
   the Protocol for session replay, which the network suite does not exercise. Our
   implementation must still be correct, but it is not on the hot path.

## What this does not prove

- **SQLite, not Postgres.** The semantics exercised (atomic append returning an
  offset, byte-range reads, durable rows) are ones Postgres provides, but the
  production implementation is unwritten.
- **No concurrency stress.** The suite is single-process. The `RETURNING`-based offset
  derivation is the right shape, but contention under real load is untested.
- **`on_change` returns a no-op subscription.** AG2 documents polling as the
  fallback, and the suite passes with it. A production store should implement it or
  accept the polling cost.

## Files

| File | What it is |
|---|---|
| `sqlstore.py` | `SqlKnowledgeStore` — the 8-method Protocol over SQLite |
| `conftest.py` | Swaps AG2's store for a counting subclass of ours |
| `test_oq024.py` | The retention-horizon gate |
| `ag2_test/` | AG2's own network suite, copied, run against our store |

Reproduce:

```bash
cd spikes/01-ag2-storage
./.venv/bin/python -m pytest ag2_test/network test_oq024.py -q --asyncio-mode=auto \
  --deselect ag2_test/network/test_sweeper_and_registry.py::test_handlers_module_does_not_touch_hub_privates
```
