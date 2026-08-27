# Spike 03 — the Postgres gate

**Gate assertions: 42** — the number `README.md` sums. Counts only tests that assert THIS spike's claims through its public boundary; vendored upstream suites are evidence, not our verdict (`VERIFICATION-RULES.md` rule 6).


**Verdict: PASS.** **42 assertions**, 0 failures, 7 negative controls, against
**PostgreSQL 16.14** in a throwaway container. (35 at first writing; scenario 9 added
2026-08-27 in redo 3 — see finding 3.)

> A ninth scenario for unmediated effects was added and **retracted** on 2026-08-27: it
> inserted the `observed` row by hand, which asserts the guard's output rather than the
> guard. Vendor-hosted tools are unsupported in v0.1 (spec/07, OQ-043).

Everything here was classified "reasoned but untested" in the previous review round.
The two earlier spikes ran SQLite in a single process, so isolation levels, real
cross-process contention and Postgres error codes were assumptions.

## What was verified

| # | Scenario | Result |
|---|---|---|
| 1 | Concurrent epoch append vs rewind | append **blocks** while a rewind is in flight, then lands in the new epoch; `current_epoch` advances exactly once |
| 2 | Trigger errcode vs the retryable `23505` | see finding below |
| 3 | Conditional effect claims across **processes** | 1 of 8 competing OS processes claims |
| 4 | Claim vs approval denial | denied ⇒ unclaimable and stays `denied`; approved ⇒ claimable (non-vacuity control) |
| 5 | Claim vs run-lease expiry | a fenced-out worker cannot acquire a new claim; the new holder can |
| 6 | Sweeper vs late settlement | the `indeterminate` verdict survives a late fenced settle |
| 7 | Run lease acquire / renew / reclaim | monotonic-but-not-dense tokens; non-holder cannot renew; fenced write rejected |
| 8 | `ON CONFLICT ... RETURNING` and isolation | `no row` is the reliable ownership signal; `REPEATABLE READ` protects the fold and `READ COMMITTED` does not |
| 9 | **The approver must be a human** (added redo 3) | `decided_by` alone did not enforce it; pinning `kind` inside the FK does. An agent, a service account, and an agent claiming `kind='human'` are all refused |

The DDL in `spec/01-schema.md` applied to a real server **unchanged** — table names,
composite keys, both `CHECK` constraints, the partial indexes and the trigger.

## Two findings that changed the spec

**1. A losing append BLOCKS; it does not fail fast.**

`spec/02-consistency.md` said the loser of a `seq` race "gets a unique violation and rolls
back". Measured behaviour: the loser waits on the winner's *uncommitted* index entry and
only receives `23505` once the winner commits. With a `statement_timeout` it instead sees
`57014`.

Consequences now in the spec: keep the append transaction short and never hold it across a
network call; `statement_timeout` is mandatory on the append path; both `23505` and `57014`
are retryable there. The single-writer guarantee holds, but it is a *blocking* guarantee.

**2. A bare `RAISE EXCEPTION` is unclassifiable.**

The epoch trigger as originally written raised `P0001` (`raise_exception`) — the same code
as every other PL/pgSQL error. A caller could not distinguish "you named an epoch you may
not name" (a bug, never retry) from a contention error (retry). The trigger now raises
`USING ERRCODE = 'invalid_parameter_value'` (`22023`), and the spike asserts both that the
code *is* `22023` and that it is **not** `23505`.

## Negative controls

Each proves the assertion can fail:

| Control | Reproduced defect |
|---|---|
| event naming its own epoch | refused by the trigger (`22023`) |
| claim without the run-lease predicate | a stale worker **does** claim and would dispatch |
| settle by key only | **overwrites** an `indeterminate` verdict |
| fold under `READ COMMITTED` | **observes** an append made mid-read |
| second `pending` approval for one action | refused by the partial unique index |
| non-holder renewing a lease | 0 rows |

## Reproduce

```bash
docker run -d --rm --name phoenix-pg-spike \
  -e POSTGRES_PASSWORD=spike -e POSTGRES_DB=spike -p 55433:5432 postgres:16-alpine
docker exec -i phoenix-pg-spike psql -U postgres -d spike -q -v ON_ERROR_STOP=1 < schema.sql
../../.venv/bin/python test_postgres.py
docker stop phoenix-pg-spike
```

Runs in about 40s. `PHOENIX_PG_DSN` overrides the connection string.

## Known limitation — one runner at a time

`fresh()` deletes rows by `tenant_id` from shared tables, so **two concurrent runs of this
suite interfere** and one will fail. That is a property of the fixtures, not of the invariants:
the assertions are about single-writer behaviour under concurrent *connections*, which the suite
creates itself.

Noted 2026-08-27 after a concurrency probe. The **spec DDL check** in `validate_spec.py` is
separately concurrency-safe — it uses a unique schema per run inside a rolled-back transaction,
verified with four parallel invocations.

## Still not verified

- **Multi-node.** One Postgres instance; no failover, no replica lag, no partition.
- **Load.** 8 concurrent processes, not 800. Lock-contention behaviour under real
  throughput is unmeasured, and finding 1 makes that a latency question worth measuring.
- **Lease TTL calibration.** The 60s run lease and 5-minute effect lease are asserted to
  *work*, not shown to be the right durations.

## Findings 3 and 4 — added in redo 3 (2026-08-27)

**3. "One attributable human decision" was prose, not a constraint.**
`spec/09` §7 claims the approval model gives "one attributable human decision", and
`ADR-0015` exists because no project in the study names its approver. But `decided_by` was a
plain foreign key to `principals` with **no constraint on kind** — so an agent or a service
account could be recorded as the approver and the database would accept it. Found while
applying decision D-A, which forced the question "what actually stops an agent deciding?"

The fix carries `decided_by_kind` on the row and pins it *inside* the foreign key
(`(tenant_id, decided_by, decided_by_kind) → principals (tenant_id, principal_id, kind)`),
which needs a `UNIQUE (tenant_id, principal_id, kind)` on `principals` to be legal. Scenario 9
proves an agent, a service account, and an agent claiming `kind='human'` are all refused, and
its negative control shows an agent **is** recorded as approver once the kind leaves the FK.

**4. `schema.sql` was not idempotent, and that produced a false PASS.**
`CREATE FUNCTION check_event_epoch()` aborted on a second apply, so re-running the file left a
**half-built schema**. A standalone run of the new approver test reported 6/6 against a
database that did not contain the constraint under test — it passed because the `INSERT`s
failed for unrelated reasons. Now `CREATE OR REPLACE`, with the trigger dropped first, and
both applies verified.

This is the same defect class as the retracted `observed` scenario: a test that passes without
exercising the mechanism it names. The difference is that this one was caught by asking the
database what constraints it actually held, rather than trusting the file.

**5. The new scenario's negative control corrupted the schema it measured.**
It dropped the two constraints, **committed**, and never restored them — so the first run
passed and every later run failed against a database missing the constraint under test. Now the
drop-insert-observe sequence runs inside a transaction that is **rolled back**, with a final
assertion that both constraints are present afterwards. Verified by running the suite twice in
a row: 42/42 both times.

A test must not leave the system it measures in a different state, and "run it twice" is the
cheapest check for that.
