# Verification rules
<!-- status: final -->

Seven rules, adopted after two rounds of external review found that **I verified the
thing I built rather than the thing I claimed** — twice, in the same shape.

These are binding on every spike and on the implementation specification.

---

## The rules

### 1. State the externally observable invariant first

Before writing any test, write the property in terms an outsider could check without
reading the implementation.

> For a given `(tenant, run, logical_step, request_digest)`, **at most one actor may
> execute the effect**, regardless of how many observers see "not found".

Not: "the ledger returns the right thing".

### 2. Run the assertion against the known-bad system and confirm it fails

If the test cannot detect the bug, it is not evidence. Spike 01's original gate
"passed" against a system that had the defect, which is how it passed while proving
nothing.

```
read-then-act effects : ['w1', 'w2']     <- KNOWN-BAD reproduced
atomic-claim effects  : ['w0']           <- guard works
```

### 3. Test only through the public boundary

The failure mode: Spike 01's first gate never called
`Hub.find_envelope_by_causation()`. It fabricated JSONL, cleared a dict it had created
itself, and scanned by hand — measuring my reimplementation, not the dependency.

If the claim is about someone else's component, the assertion must go through their
public API.

### 4. Add a mutation / negative control proving the test fails when the guarantee is removed

Every guard gets a paired test that **removes** it and shows the suite goes red.

```python
rt.store.acquire_resume_lease = lambda *_a, **_k: True   # guarantee REMOVED
...
assert a.calls == ["start"] * 4, "negative control must show 4 executions"
```

Without this, a passing test may be passing for an unrelated reason — which is exactly
what Spike 01's `test_4_two_hubs_one_store` did (it passed because both hubs hydrated
*before* the close, not because the mechanism worked).

### 5. Keep the implementation helper and the test oracle independent

If the same function computes the expected value and the actual value, the test is a
tautology. The oracle must be derivable without the code under test — a second
implementation, a stored fixture, an external observation, or a property that holds by
construction.

### 6. Do not write PASS until the exact reproduction command includes every gate test

Spike 01's first `RESULT.md` reported a pass while its reproduce command silently
omitted the one failing file. The command in the result document must run **all** gate
tests, with no `--deselect` and no omissions, and the stated count must match.

Supporting evidence that is *not* reproducible from the checkout (e.g. a vendored
upstream suite) must be labelled as such and must not carry the verdict.

### 7. A verifier must never destructively mutate state it does not uniquely own

Added 2026-08-27, after **three** ownership violations among five unsound verification steps in six review passes — and one case
where the *fix for* an unsound step was itself unsound.

> **Prefer rollback. Where explicit cleanup is necessary, target only uniquely named, run-owned
> resources, and prove unrelated state survives.**

The instances, all real:

| What it did | Rule violated | State it did not own |
|---|---|---|
| inserted the `observed` ledger row by hand | **2 and 4**, not 7 | nothing — the row was its own; the defect is that it asserted the guard's *output*, so the guard was never exercised and no negative control could have gone red (`synthesis/scope-reconciliation.md:456-458`) |
| `schema.sql` was not idempotent | **6**, not 7 | nothing — the schema was its own; the defect is that the PASS was written from a standalone 6/6 run rather than the full gate command, against a second apply that left a **half-built** schema missing the constraint under test (`synthesis/scope-reconciliation.md:584-588`) |
| a negative control dropped two constraints and **committed** | **7** | every later run failed against a schema the test had broken |
| DDL check used a fixed `specddl` schema + `SET search_path`, then `DROP SCHEMA CASCADE` | **7** | **the spike's own tables**, created under that `search_path` |
| DDL check used a fixed `specddl_check` database + `DROP DATABASE ... WITH (FORCE)` | **7** | **a pre-existing database of that name**, belonging to whoever created it |

The first two rows were listed here as rule-7 instances and are not: each mutated only state it
owned. Classified under the earlier rules they actually violate, **added 2026-08-27**; they stay
in the table because both were found in the same review sweep.

An earlier version of this rule said *"a verification step should have no destructive statement in it at all"* — **superseded 2026-08-27** as overbroad, because the spike's own `fresh()` deletes rows from fixture tables it created, which is legitimate.
The verb was never the problem — **ownership** was.

Two clauses do the work. *Prefer rollback* removes the destructive statement where possible: the
DDL check now creates a `specddl_<12 hex>` schema inside one transaction and rolls it back
unconditionally, so there is nothing to drop. *Prove unrelated state survives* is what actually
catches a violation — assert the planted sentinel, the pre-existing role, and the neighbouring
tables are all still there after a run.

---

## Verdict vocabulary

A single "PASS" hid a failure once. Verdicts are now recorded **per route**, not per
spike.

| Verdict | Meaning |
|---|---|
| **PASS** | The stated invariant holds, tested through the public boundary, with a negative control |
| **FAIL** | The invariant does not hold on this route |
| **PASS (route B), FAIL (route A)** | Two designs were on the table; say which one died |
| **INCONCLUSIVE** | Not tested, or tested without a negative control. **Not** a synonym for "probably fine" |

Spike 01's honest record is *FAIL* for clean integration and *PASS* for the
compatibility-layer route. "Conditional PASS" obscured that the original gate failed.

---

## Applied to the two spikes

| | Spike 01 | Spike 02 |
|---|---|---|
| 1 · invariant stated first | at most one executor per causation key | executed artifact == checked artifact |
| 2 · known-bad reproduced | read-then-act double-executes | tampered artifact ⇒ `ArtifactCorrupted` |
| 3 · public boundary only | `Hub.open`, `post_envelope`, `read_wal`, `find_envelope_by_causation` | adapter invoked only via `Runtime.resume` |
| 4 · negative controls | claim removed ⇒ both workers act | lease stubbed ⇒ 4 executions; canon version bumped ⇒ digest changes |
| 5 · independent oracle | `sqlite3` inspected directly, not via the store | registry body compared byte-for-byte |
| 6 · full reproduce command | 12 tests, no deselect | 35 tests, no deselect |

## The failure this prevents

Both review rounds found the same class of defect, and it was not carelessness — it
was **confirmation-shaped effort**. I built a mechanism, then wrote tests that
exercised the mechanism, and read green as evidence about the *claim*. The claim was
always about something outside the mechanism: someone else's dependency, or a
guarantee under concurrency.

Rule 3 and rule 4 exist specifically to break that: test the boundary you are making
a claim about, and prove your test can fail.

**Rule 7 is the same failure in a different direction.** There, a green result was evidence
about the wrong thing; here, a verification step *changed the system it was measuring* and the
damage showed up as an unrelated failure one run later. Both come from treating the harness as
trustworthy because I wrote it.
