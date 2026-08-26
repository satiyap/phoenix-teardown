# Spike 01 — AG2 storage swap

## Verdicts — two, recorded separately

| Route | Verdict |
|---|---|
| **Clean `ag2.network` integration** (contract intact) | **FAIL** |
| **AG2 behind an owned compatibility layer** | **PASS** — public composition, atomic claim proven |

"Conditional PASS" obscured that the original gate *failed*. It did. The clean-integration
route is dead: satisfying OQ-024 requires changing the public semantics of
`find_envelope_by_causation`, which the gate forbade.

The compatibility-layer route is now evidenced rather than asserted — see §Gate 01b
(atomicity) and §Gate 01c (ownership boundary) below.
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

## Gate 01b — atomicity: a three-valued lookup is NOT a dedupe primitive

The review's sharpest point, and it is correct. `FOUND | NOT_FOUND | INDETERMINATE`
is still a **read**. Two hubs can both read `NOT_FOUND`, both act, both append.

Tested with a **negative control first** (`test_race.py`):

```
read-then-act effects : ['w1', 'w2']     <- KNOWN-BAD, double execution
atomic-claim effects  : ['w0']           <- exactly one winner (8 racers)
claim survives channel close AND WAL deletion
two-hub winners       : ['h1']
```

The primitive is an **atomic claim**, not a lookup:

```sql
CREATE TABLE effect_ledger (
  channel_id TEXT, sender_id TEXT, causation_id TEXT, status TEXT,
  PRIMARY KEY (channel_id, sender_id, causation_id));

INSERT OR IGNORE INTO effect_ledger(...) VALUES(...);   -- rowcount == 1 means WE won
```

`test_C_claim_is_independent_of_channel_lifetime` closes the channel **and deletes the
WAL entirely**, then asserts the claim still holds. So the second review point is
settled too: **the effect ledger does not depend on message-log retention.**
`causation_id` *derives* the key; the ledger *is* the authority. Channel deletion,
compaction or federation cannot change the safety guarantee for an unrelated external
effect.

## Gate 01c — ownership: adapter, not fork

The question: can we own dedupe through public composition, or must we replace a hub
method?

`test_ownership.py` answers it from the source. There is exactly **one** internal
self-call of `find_envelope_by_causation`, and it is in the **RPC dispatch table**
(`op == "find_envelope_by_causation"`) — routing a *remote* request. Asserted
directly:

```python
post_src = inspect.getsource(CoreHub.post_envelope)
assert "find_envelope_by_causation" not in post_src
```

**`post_envelope` never consults it.** The hub does not make a dedupe decision while
accepting an envelope, so dedupe is ours to own by wrapping. A `DedupingHub` that
claims-then-delegates touches no privates.

**Therefore: a compatibility layer over public API, not a maintained fork.** The
upstream-drift risk is correspondingly smaller — it is `post_envelope`'s signature and
the `Envelope` schema we depend on, not internal index behaviour.

## The decision

**Integrate `ag2.network`** for the `Envelope` schema, channel protocols, delivery,
cursors, replay and expectations — 480 upstream tests' worth of machinery we would
otherwise write.

**Own dedupe entirely.** Do not use `find_envelope_by_causation` for correctness at
all. Our effect ledger claims atomically before any effect, keyed on
`(tenant, run, logical_step, request_digest)` with `causation_id` as one derivation
path. AG2's lookup remains useful only as an optimisation hint.

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

## Reproduce — every gate test, no exclusions

```bash
cd spikes/01-ag2-storage
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m pytest test_gate_real.py test_race.py test_ownership.py \
    -q --asyncio-mode=auto -s
# 12 passed
```

`requirements.txt` pins `ag2==1.0.2` and records the AG2 source commit
`90f490a1b72b27ab4c219dd3586e94d42383a016`.

The 480-test upstream run is **supporting evidence only** and is not reproducible from
this checkout — it needs AG2's `test/` tree copied in. The 12 public-API tests above
carry the verdict.

## Files

| File | What it is |
|---|---|
| `sqlstore.py` | `SqlKnowledgeStore` — the 8-method Protocol over SQLite |
| `test_gate_real.py` | **The gate.** Public API only, 5 scenarios |
| `conftest.py` | Swaps AG2's store for a counting subclass (upstream-suite run) |
| `requirements.txt` | Pinned deps + AG2 source commit |
