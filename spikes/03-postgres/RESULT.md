# Spike 03 — the Postgres gate

**Verdict: PASS.** **41 assertions**, 0 failures, 6 negative controls, against
**PostgreSQL 16.14** in a throwaway container. (35 at first writing; scenario 9 added
2026-08-27 with the unmediated-tools decision.)

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
| 9 | **Unmediated effects** (added 2026-08-27) | `observed` is recorded but structurally cannot carry claim fields, cannot be claimed, and cannot reach `succeeded`; `status <> 'observed'` is a reliable at-most-once filter because `observed` ⇔ `kind='unmediated'` |

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

## Still not verified

- **Multi-node.** One Postgres instance; no failover, no replica lag, no partition.
- **Load.** 8 concurrent processes, not 800. Lock-contention behaviour under real
  throughput is unmeasured, and finding 1 makes that a latency question worth measuring.
- **Lease TTL calibration.** The 60s run lease and 5-minute effect lease are asserted to
  *work*, not shown to be the right durations.
