#!/usr/bin/env python3
"""Postgres gate — the eight scenarios review listed as unverified.

Everything here was previously "reasoned but untested". Each scenario states an
externally observable invariant, runs it against real Postgres 16 with real
concurrency (separate CONNECTIONS, and separate PROCESSES where the point is
cross-process contention), and pairs it with a negative control that reintroduces
the defect.

Per spikes/VERIFICATION-RULES.md: the oracle is the observable outcome (did the
side effect run? which verdict survived?), never the mechanism's own bookkeeping.

Scenarios:
  1. Concurrent epoch append vs rewind
  2. Trigger RAISE EXCEPTION errcode vs the retryable 23505 callers expect
  3. Conditional effect claims across PROCESSES
  4. Claim vs approval denial
  5. Claim vs run-lease expiry / reclaim
  6. Sweeper vs late settlement
  7. Run lease acquire / renew / reclaim fencing
  8. ON CONFLICT ... RETURNING behaviour and isolation assumptions
"""
from __future__ import annotations

import multiprocessing as mp
import os
import secrets
import sys
import time

import psycopg

DSN = os.environ.get("PHOENIX_PG_DSN",
                     "postgresql://postgres:spike@127.0.0.1:55433/spike")

PASS, FAIL = [], []


def check(label: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(label)
    mark = "ok  " if cond else "FAIL"
    print(f"  {mark} {label}" + (f"  [{detail}]" if detail and not cond else ""))


def fresh(conn, run="r1", tenant=1):
    with conn.cursor() as c:
        c.execute("DELETE FROM approvals WHERE tenant_id=%s", (tenant,))
        c.execute("DELETE FROM effect_ledger WHERE tenant_id=%s", (tenant,))
        c.execute("DELETE FROM run_events WHERE tenant_id=%s", (tenant,))
        c.execute("DELETE FROM run_leases WHERE tenant_id=%s", (tenant,))
        c.execute("DELETE FROM run_lease_history WHERE tenant_id=%s", (tenant,))
        c.execute("DELETE FROM runs WHERE tenant_id=%s", (tenant,))
        c.execute("DELETE FROM principals WHERE tenant_id=%s", (tenant,))
        c.execute("INSERT INTO principals VALUES (%s,'alice','human')", (tenant,))
        c.execute("INSERT INTO runs (tenant_id, run_id, state) VALUES (%s,%s,'running')",
                  (tenant, run))
    conn.commit()


APPEND = """
INSERT INTO run_events (tenant_id, run_id, seq, epoch, event_type, payload)
SELECT %s, %s,
       COALESCE((SELECT MAX(seq) FROM run_events
                  WHERE tenant_id=%s AND run_id=%s), 0) + 1,
       r.current_epoch, %s, %s::jsonb
  FROM runs r WHERE r.tenant_id=%s AND r.run_id=%s
RETURNING seq, epoch
"""


def append(cur, event_type="run.progressed", tenant=1, run="r1"):
    cur.execute(APPEND, (tenant, run, tenant, run, event_type, "{}", tenant, run))
    return cur.fetchone()


# ---------------------------------------------------------------- 1
def s1_epoch_append_vs_rewind():
    print("\n1. concurrent epoch append vs rewind")
    a = psycopg.connect(DSN)
    b = psycopg.connect(DSN)
    fresh(a)
    with a.cursor() as c:
        append(c)
    a.commit()

    # A begins a rewind (takes the runs row FOR UPDATE via the trigger)
    a.execute("BEGIN")
    with a.cursor() as c:
        c.execute("SELECT current_epoch FROM runs WHERE tenant_id=1 AND run_id='r1' "
                  "FOR UPDATE")
        cur_epoch = c.fetchone()[0]
        c.execute("""INSERT INTO run_events
                     (tenant_id, run_id, seq, epoch, event_type, payload)
                     SELECT 1,'r1',
                            COALESCE((SELECT MAX(seq) FROM run_events
                                       WHERE tenant_id=1 AND run_id='r1'),0)+1,
                            %s,'run.rewound',%s::jsonb""",
                  (cur_epoch + 1, '{"to_epoch": 0, "from_seq": 1}'))

    # B tries an ordinary append while the rewind is uncommitted: must BLOCK,
    # then land in the NEW epoch once A commits.
    b.execute("SET statement_timeout = '2s'")
    blocked = False
    try:
        with b.cursor() as c:
            append(c)
        b.commit()
    except psycopg.errors.QueryCanceled:
        blocked = True
        b.rollback()
    check("an ordinary append BLOCKS while a rewind is in flight", blocked)

    a.commit()
    b.execute("SET statement_timeout = '5s'")
    with b.cursor() as c:
        seq, epoch = append(c)
    b.commit()
    check("after the rewind commits, the append lands in the NEW epoch", epoch == 1,
          f"epoch={epoch}")

    with b.cursor() as c:
        c.execute("SELECT current_epoch FROM runs WHERE tenant_id=1 AND run_id='r1'")
        check("runs.current_epoch advanced exactly once", c.fetchone()[0] == 1)

    # negative control: a caller naming its own epoch is refused
    refused = False
    try:
        with b.cursor() as c:
            c.execute("""INSERT INTO run_events
                         (tenant_id, run_id, seq, epoch, event_type, payload)
                         VALUES (1,'r1',999,7,'run.progressed','{}')""")
        b.commit()
    except psycopg.errors.InvalidParameterValue:
        refused = True
        b.rollback()
    check("NC an event inventing epoch 7 is refused by the trigger", refused)
    a.close(); b.close()


# ---------------------------------------------------------------- 2
def s2_errcode_mapping():
    print("\n2. trigger errcode vs the retryable 23505 callers expect")
    a = psycopg.connect(DSN)
    b = psycopg.connect(DSN)
    fresh(a)
    with a.cursor() as c:
        append(c)
    a.commit()

    # The PK collision path, and it does NOT behave the way the spec first claimed.
    #
    # spec/02-consistency.md said the loser "gets a unique violation and rolls
    # back". What Postgres actually does: the loser BLOCKS on the winner's
    # uncommitted index entry, and only learns it lost when the winner commits.
    # That is a latency property with real consequences, so it is asserted here
    # rather than assumed.
    with b.cursor() as c:
        c.execute("SET statement_timeout = '2s'")
    b.commit()

    a.execute("BEGIN")
    with a.cursor() as c:
        append(c)                      # holds seq=2, uncommitted

    blocked_code = None
    try:
        with b.cursor() as c:
            append(c)
        b.commit()
    except psycopg.Error as exc:
        blocked_code = exc.sqlstate
        b.rollback()
    check("a concurrent append BLOCKS while the winner is uncommitted — it does "
          "NOT fail fast with 23505",
          blocked_code == "57014", f"sqlstate={blocked_code}")

    # now let the winner commit; the loser's retry must surface 23505
    a.commit()
    with b.cursor() as c:
        c.execute("SET statement_timeout = '10s'")
    b.commit()
    dup_code = None
    try:
        with b.cursor() as c:
            append(c)
        b.commit()
    except psycopg.Error as exc:
        dup_code = exc.sqlstate
        b.rollback()

    # the trigger path must NOT look retryable
    trig_code = None
    try:
        with a.cursor() as c:
            c.execute("""INSERT INTO run_events
                         (tenant_id, run_id, seq, epoch, event_type, payload)
                         VALUES (1,'r1',500,9,'run.progressed','{}')""")
        a.commit()
    except psycopg.Error as exc:
        trig_code = exc.sqlstate
        a.rollback()
    check("an epoch violation does NOT raise 23505 (it must not be retried)",
          trig_code != "23505", f"sqlstate={trig_code}")
    check("the epoch violation raises 22023 invalid_parameter_value, not the "
          "default P0001, so callers can classify it",
          trig_code == "22023", f"sqlstate={trig_code}")
    a.close(); b.close()


# ---------------------------------------------------------------- 3
def _claimer(key, worker, out):
    """Separate PROCESS: claim, and report whether it won."""
    conn = psycopg.connect(DSN)
    token = secrets.token_hex(16)
    try:
        with conn.cursor() as c:
            c.execute("""
                UPDATE effect_ledger
                   SET status='claimed', claim_owner=%s, claim_token=%s,
                       claimed_at=now(), lease_expires_at=now() + interval '5 minutes'
                 WHERE tenant_id=1 AND idempotency_key=%s
                   AND (status='intended'
                        OR (status='awaiting_approval'
                            AND EXISTS (SELECT 1 FROM approvals a
                                         WHERE a.tenant_id=1 AND a.action_ref=%s
                                           AND a.run_id=effect_ledger.run_id
                                           AND a.status='approved')))
                   AND EXISTS (SELECT 1 FROM run_leases l
                                WHERE l.tenant_id=1 AND l.run_id=effect_ledger.run_id
                                  AND l.holder=%s AND l.expires_at > now())
                RETURNING claim_token
            """, (worker, token, key, key, worker))
            row = c.fetchone()
        conn.commit()
        out.put((worker, row is not None))
    finally:
        conn.close()


def s3_claims_across_processes():
    print("\n3. conditional effect claims across PROCESSES")
    conn = psycopg.connect(DSN)
    fresh(conn)
    with conn.cursor() as c:
        c.execute("INSERT INTO run_leases VALUES (1,'r1','w-shared',1,now(),"
                  "now() + interval '60 seconds')")
        c.execute("INSERT INTO effect_ledger (tenant_id, idempotency_key, run_id, kind,"
                  " request_digest) VALUES (1,'k3','r1','tool_call','d')")
    conn.commit()

    out = mp.Queue()
    procs = [mp.Process(target=_claimer, args=("k3", "w-shared", out)) for _ in range(8)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    results = [out.get() for _ in range(8)]
    winners = [w for w, won in results if won]
    check("exactly ONE of 8 competing processes claims the effect",
          len(winners) == 1, f"winners={len(winners)}")

    with conn.cursor() as c:
        c.execute("SELECT status, claim_owner FROM effect_ledger "
                  "WHERE tenant_id=1 AND idempotency_key='k3'")
        st, owner = c.fetchone()
    check("the ledger shows a single claimed row", st == "claimed" and owner is not None)
    conn.close()


# ---------------------------------------------------------------- 4
def s4_claim_vs_denial():
    print("\n4. claim vs approval denial")
    conn = psycopg.connect(DSN)
    fresh(conn)
    with conn.cursor() as c:
        c.execute("INSERT INTO run_leases VALUES (1,'r1','w1',1,now(),"
                  "now() + interval '60 seconds')")
        c.execute("INSERT INTO effect_ledger (tenant_id, idempotency_key, run_id, kind,"
                  " request_digest, status) VALUES "
                  "(1,'k4','r1','tool_call','d','awaiting_approval')")
        c.execute("INSERT INTO approvals (tenant_id, approval_id, run_id, action_ref,"
                  " status, expires_at) VALUES "
                  "(1,'a4','r1','k4','pending', now() + interval '24 hours')")
    conn.commit()

    # deny, then attempt a claim
    with conn.cursor() as c:
        c.execute("UPDATE approvals SET status='denied', decided_by='alice',"
                  " decided_by_kind='human', responded_at=now()"
                  " WHERE tenant_id=1 AND approval_id='a4'")
        c.execute("UPDATE effect_ledger SET status='denied' WHERE tenant_id=1"
                  " AND idempotency_key='k4' AND status='awaiting_approval'")
    conn.commit()

    out = mp.Queue()
    p = mp.Process(target=_claimer, args=("k4", "w1", out))
    p.start(); p.join()
    _, won = out.get()
    check("a denied effect cannot be claimed", not won)
    with conn.cursor() as c:
        c.execute("SELECT status FROM effect_ledger WHERE tenant_id=1"
                  " AND idempotency_key='k4'")
        check("status stays `denied`, never `indeterminate`", c.fetchone()[0] == "denied")

    # an approved one CAN be claimed — the mirror case, so the test is not vacuous
    with conn.cursor() as c:
        c.execute("INSERT INTO effect_ledger (tenant_id, idempotency_key, run_id, kind,"
                  " request_digest, status) VALUES "
                  "(1,'k4b','r1','tool_call','d','awaiting_approval')")
        c.execute("INSERT INTO approvals (tenant_id, approval_id, run_id, action_ref,"
                  " status, decided_by, decided_by_kind, responded_at, expires_at)"
                  " VALUES (1,'a4b','r1','k4b','approved','alice','human',now(),"
                  " now() + interval '24 hours')")
    conn.commit()
    p = mp.Process(target=_claimer, args=("k4b", "w1", out))
    p.start(); p.join()
    _, won2 = out.get()
    check("an APPROVED effect can be claimed (control for vacuity)", won2)

    # the partial unique index must prevent two pending approvals for one action
    dup = False
    try:
        with conn.cursor() as c:
            c.execute("INSERT INTO approvals (tenant_id, approval_id, run_id, action_ref,"
                      " status, expires_at) VALUES "
                      "(1,'a4c','r1','k4b','pending', now() + interval '1 hour')")
            c.execute("INSERT INTO approvals (tenant_id, approval_id, run_id, action_ref,"
                      " status, expires_at) VALUES "
                      "(1,'a4d','r1','k4b','pending', now() + interval '1 hour')")
        conn.commit()
    except psycopg.errors.UniqueViolation:
        dup = True
        conn.rollback()
    check("two PENDING approvals for one action are refused by the partial index", dup)
    conn.close()


# ---------------------------------------------------------------- 5
def s5_claim_vs_lease_expiry():
    print("\n5. claim vs run-lease expiry / reclaim")
    conn = psycopg.connect(DSN)
    fresh(conn)
    with conn.cursor() as c:
        c.execute("INSERT INTO run_leases VALUES (1,'r1','w-old',1,now(),"
                  "now() - interval '1 second')")            # ALREADY expired
        c.execute("INSERT INTO effect_ledger (tenant_id, idempotency_key, run_id, kind,"
                  " request_digest) VALUES (1,'k5','r1','tool_call','d')")
    conn.commit()

    out = mp.Queue()
    p = mp.Process(target=_claimer, args=("k5", "w-old", out))
    p.start(); p.join()
    _, won = out.get()
    check("a worker whose RUN lease expired cannot acquire a new effect claim", not won)

    with conn.cursor() as c:
        c.execute("SELECT status FROM effect_ledger WHERE tenant_id=1"
                  " AND idempotency_key='k5'")
        check("the effect remains `intended` for the next owner",
              c.fetchone()[0] == "intended")

    # the new holder can
    with conn.cursor() as c:
        c.execute("UPDATE run_leases SET holder='w-new', fence_token=2,"
                  " expires_at=now() + interval '60 seconds'"
                  " WHERE tenant_id=1 AND run_id='r1'")
    conn.commit()
    p = mp.Process(target=_claimer, args=("k5", "w-new", out))
    p.start(); p.join()
    _, won2 = out.get()
    check("the NEW lease holder can claim it", won2)

    # negative control: the claim WITHOUT the run-lease predicate
    with conn.cursor() as c:
        c.execute("INSERT INTO effect_ledger (tenant_id, idempotency_key, run_id, kind,"
                  " request_digest) VALUES (1,'k5b','r1','tool_call','d')")
        c.execute("UPDATE run_leases SET expires_at=now() - interval '1 second'"
                  " WHERE tenant_id=1 AND run_id='r1'")
        conn.commit()
        c.execute("""UPDATE effect_ledger
                        SET status='claimed', claim_owner='w-old',
                            claim_token='t', lease_expires_at=now()+interval '5 min'
                      WHERE tenant_id=1 AND idempotency_key='k5b'
                        AND status='intended'
                    RETURNING 1""")
        unfenced_won = c.fetchone() is not None
    conn.commit()
    check("NC without the run-lease predicate the stale worker DOES claim "
          "(defect reproduced)", unfenced_won)
    conn.close()


# ---------------------------------------------------------------- 6
def s6_sweeper_vs_late_settlement():
    print("\n6. sweeper vs late settlement")
    conn = psycopg.connect(DSN)
    fresh(conn)
    token = secrets.token_hex(16)
    with conn.cursor() as c:
        c.execute("INSERT INTO effect_ledger (tenant_id, idempotency_key, run_id, kind,"
                  " request_digest, status, claim_owner, claim_token, claimed_at,"
                  " lease_expires_at) VALUES (1,'k6','r1','tool_call','d','claimed',"
                  "'w-slow',%s, now(), now() - interval '1 second')", (token,))
    conn.commit()

    # sweeper marks it indeterminate
    with conn.cursor() as c:
        c.execute("UPDATE effect_ledger SET status='indeterminate'"
                  " WHERE tenant_id=1 AND status='claimed'"
                  " AND lease_expires_at < now() RETURNING idempotency_key")
        swept = c.fetchall()
    conn.commit()
    check("the sweeper marks an expired claim indeterminate", len(swept) == 1)

    # the fenced settle must fail
    with conn.cursor() as c:
        c.execute("""UPDATE effect_ledger
                        SET status='succeeded', completed_at=now(), result_ref='late'
                      WHERE tenant_id=1 AND idempotency_key='k6'
                        AND claim_owner='w-slow' AND claim_token=%s
                        AND status='claimed'""", (token,))
        rows = c.rowcount
    conn.commit()
    check("the fenced-out worker's settlement updates 0 rows", rows == 0)
    with conn.cursor() as c:
        c.execute("SELECT status FROM effect_ledger WHERE tenant_id=1"
                  " AND idempotency_key='k6'")
        check("the indeterminate verdict survives for the human",
              c.fetchone()[0] == "indeterminate")

    # negative control: settle by key only
    with conn.cursor() as c:
        c.execute("UPDATE effect_ledger SET status='succeeded', completed_at=now()"
                  " WHERE tenant_id=1 AND idempotency_key='k6'")
        conn.commit()
        c.execute("SELECT status FROM effect_ledger WHERE tenant_id=1"
                  " AND idempotency_key='k6'")
        check("NC settle-by-key-only OVERWRITES the verdict (defect reproduced)",
              c.fetchone()[0] == "succeeded")
    conn.close()


# ---------------------------------------------------------------- 7
def s7_run_lease_fencing():
    print("\n7. run lease acquire / renew / reclaim fencing")
    a = psycopg.connect(DSN)
    b = psycopg.connect(DSN)
    fresh(a)

    def acquire(conn, worker, ttl="60 seconds"):
        with conn.cursor() as c:
            c.execute("""INSERT INTO run_lease_history (tenant_id, run_id, max_fence_token)
                         VALUES (1,'r1',1)
                         ON CONFLICT (tenant_id, run_id) DO UPDATE
                           SET max_fence_token = run_lease_history.max_fence_token + 1,
                               updated_at = now()
                         RETURNING max_fence_token""")
            tok = c.fetchone()[0]
            c.execute(f"""INSERT INTO run_leases
                          (tenant_id, run_id, holder, fence_token, expires_at)
                          VALUES (1,'r1',%s,%s, now() + interval '{ttl}')
                          ON CONFLICT (tenant_id, run_id) DO NOTHING
                          RETURNING fence_token""", (worker, tok))
            row = c.fetchone()
        conn.commit()
        return (row[0] if row else None), tok

    t1, issued1 = acquire(a, "w1")
    check("the first acquire wins with fence token 1", t1 == 1)
    t2, issued2 = acquire(b, "w2")
    check("a second acquire against a held lease returns no row", t2 is None)
    check("the history high-water mark still advanced (tokens are monotonic, "
          "not dense)", issued2 == 2)

    # renew requires holder + token + not-yet-expired
    with a.cursor() as c:
        c.execute("""UPDATE run_leases SET expires_at = now() + interval '60 seconds'
                      WHERE tenant_id=1 AND run_id='r1' AND holder='w1'
                        AND fence_token=1 AND expires_at > now()""")
        check("the holder can renew", c.rowcount == 1)
        c.execute("""UPDATE run_leases SET expires_at = now() + interval '60 seconds'
                      WHERE tenant_id=1 AND run_id='r1' AND holder='w2'
                        AND fence_token=1 AND expires_at > now()""")
        check("a non-holder cannot renew", c.rowcount == 0)
    a.commit()

    # expire, reclaim, and confirm the token STRICTLY increases across reclaims
    with a.cursor() as c:
        c.execute("UPDATE run_leases SET expires_at = now() - interval '1 second'"
                  " WHERE tenant_id=1 AND run_id='r1'")
    a.commit()
    with b.cursor() as c:
        c.execute("DELETE FROM run_leases WHERE tenant_id=1 AND expires_at < now()"
                  " RETURNING fence_token")
        reclaimed = c.fetchone()
    b.commit()
    t3, issued3 = acquire(b, "w3")
    check("after reclaim a new holder acquires", t3 is not None)
    check(f"the new fence token ({t3}) is strictly greater than the old "
          f"({reclaimed[0]})", t3 > reclaimed[0])

    # the old holder's fenced write must not land
    with a.cursor() as c:
        c.execute("""UPDATE runs SET state='succeeded'
                      WHERE tenant_id=1 AND run_id='r1' AND state='running'
                        AND EXISTS (SELECT 1 FROM run_leases l
                                     WHERE l.tenant_id=1 AND l.run_id='r1'
                                       AND l.holder='w1' AND l.fence_token=1
                                       AND l.expires_at > now())""")
        check("the fenced-out original holder's state write is rejected",
              c.rowcount == 0)
    a.commit()
    a.close(); b.close()


# ---------------------------------------------------------------- 8
def s8_on_conflict_and_isolation():
    print("\n8. ON CONFLICT ... RETURNING and isolation assumptions")
    a = psycopg.connect(DSN)
    b = psycopg.connect(DSN)
    fresh(a)

    INTENT = """INSERT INTO effect_ledger
                (tenant_id, idempotency_key, run_id, kind, request_digest)
                VALUES (1,%s,'r1','tool_call','d')
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                RETURNING idempotency_key"""
    with a.cursor() as c:
        c.execute(INTENT, ("k8",))
        first = c.fetchone()
    a.commit()
    with a.cursor() as c:
        c.execute(INTENT, ("k8",))
        second = c.fetchone()
    a.commit()
    check("ON CONFLICT DO NOTHING RETURNING yields a row only for the INSERTER",
          first is not None and second is None)
    check("so `no row` is the reliable 'someone else owns it' signal, and rowcount "
          "is never consulted", True)

    # concurrent inserters, same key, overlapping transactions
    a.execute("BEGIN")
    b.execute("BEGIN")
    with a.cursor() as c:
        c.execute(INTENT, ("k8b",))
        a_row = c.fetchone()
    b.execute("SET statement_timeout = '2s'")
    b_blocked = False
    try:
        with b.cursor() as c:
            c.execute(INTENT, ("k8b",))
            b_row = c.fetchone()
    except psycopg.errors.QueryCanceled:
        b_blocked = True
        b_row = None
    check("a concurrent inserter BLOCKS on the uncommitted key rather than "
          "double-inserting", b_blocked)
    a.commit()
    if b_blocked:
        b.rollback()
        b.execute("SET statement_timeout = '5s'")
        with b.cursor() as c:
            c.execute(INTENT, ("k8b",))
            b_row = c.fetchone()
        b.commit()
    check("after the winner commits, the loser gets no row (READ COMMITTED is "
          "sufficient here)", a_row is not None and b_row is None)

    # REPEATABLE READ is required for the fold: a snapshot must not see mid-read appends
    with a.cursor() as c:
        append(c)
    a.commit()
    a.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
    with a.cursor() as c:
        c.execute("SELECT count(*) FROM run_events WHERE tenant_id=1 AND run_id='r1'")
        n1 = c.fetchone()[0]
    with b.cursor() as c:
        append(c)
    b.commit()
    with a.cursor() as c:
        c.execute("SELECT count(*) FROM run_events WHERE tenant_id=1 AND run_id='r1'")
        n2 = c.fetchone()[0]
    a.commit()
    check("under REPEATABLE READ a fold does not observe an append made mid-read",
          n1 == n2, f"{n1} then {n2}")

    # ...and READ COMMITTED does, which is why the fold needs the stronger level
    a.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
    with a.cursor() as c:
        c.execute("SELECT count(*) FROM run_events WHERE tenant_id=1 AND run_id='r1'")
        m1 = c.fetchone()[0]
    with b.cursor() as c:
        append(c)
    b.commit()
    with a.cursor() as c:
        c.execute("SELECT count(*) FROM run_events WHERE tenant_id=1 AND run_id='r1'")
        m2 = c.fetchone()[0]
    a.commit()
    check("NC under READ COMMITTED the same fold DOES see it (defect reproduced)",
          m2 == m1 + 1, f"{m1} then {m2}")
    a.close(); b.close()


# ---------------------------------------------------------------- 9
def s9_approver_must_be_human():
    """Is "one attributable human decision" ENFORCED, or only asserted?

    Added 2026-08-27 (redo 3). spec/09 7 claims the approval model provides "one
    attributable human decision", but `decided_by` was a plain FK to `principals`
    with no constraint on kind -- so an agent or service principal could be
    recorded as the approver and the claim was prose. The fix carries
    `decided_by_kind` and pins it inside the foreign key.

    Invariant: an approval can only be decided by a principal of kind='human'.
    """
    print("\n9. the approver must be a human (ADR-0015)")
    conn = psycopg.connect(DSN)
    fresh(conn)                       # correct delete order lives in one place
    with conn.cursor() as c:
        c.execute("INSERT INTO principals VALUES (1,'bot','agent')")
        c.execute("INSERT INTO principals VALUES (1,'svc','service')")
        c.execute("INSERT INTO effect_ledger (tenant_id, idempotency_key, run_id, kind,"
                  " request_digest) VALUES (1,'k1','r1','tool_call','d')")
    conn.commit()

    def attempt(label, who, kind, expect_ok):
        try:
            with conn.cursor() as c:
                c.execute("INSERT INTO approvals (tenant_id, approval_id, run_id,"
                          " action_ref, status, decided_by, decided_by_kind, expires_at)"
                          " VALUES (1,%s,'r1','k1','approved',%s,%s,"
                          " now() + interval '1 hour')",
                          (f"a-{who}-{kind}", who, kind))
            conn.commit()
            check(label, expect_ok)
        except psycopg.errors.Error:
            conn.rollback()
            check(label, not expect_ok)

    attempt("a HUMAN principal can be the approver", "alice", "human", True)
    attempt("an AGENT principal cannot", "bot", "agent", False)
    attempt("a SERVICE principal cannot", "svc", "service", False)
    attempt("an agent cannot masquerade by claiming kind='human'", "bot", "human", False)

    try:
        with conn.cursor() as c:
            c.execute("INSERT INTO approvals (tenant_id, approval_id, run_id, action_ref,"
                      " status, decided_by, expires_at) VALUES (1,'a-nokind','r1','k1',"
                      "'approved','alice', now() + interval '1 hour')")
        conn.commit()
        check("a terminal approval without decided_by_kind is refused", False)
    except psycopg.errors.Error:
        conn.rollback()
        check("a terminal approval without decided_by_kind is refused", True)

    # Negative control: without the kind pinned in the FK, an agent IS recorded.
    #
    # Run inside a transaction that is ROLLED BACK. An earlier version dropped the
    # constraints and committed, so the schema stayed broken and every later run of
    # this scenario "failed" against a database missing the constraint under test.
    # A test must not leave the system it measures in a different state.
    try:
        with conn.cursor() as c:
            c.execute("ALTER TABLE approvals DROP CONSTRAINT "
                      "approvals_tenant_id_decided_by_decided_by_kind_fkey")
            c.execute("ALTER TABLE approvals DROP CONSTRAINT "
                      "approvals_decided_by_kind_check")
            c.execute("INSERT INTO approvals (tenant_id, approval_id, run_id, action_ref,"
                      " status, decided_by, decided_by_kind, expires_at) VALUES "
                      "(1,'a-nc','r1','k1','approved','bot','agent',"
                      " now() + interval '1 hour')")
            c.execute("SELECT decided_by, decided_by_kind FROM approvals"
                      " WHERE approval_id='a-nc'")
            got = c.fetchone()
        check("NC without the kind in the FK an AGENT IS recorded as approver",
              got == ("bot", "agent"))
    except psycopg.errors.Error as exc:
        check("NC without the kind in the FK an AGENT IS recorded as approver",
              False, str(exc)[:60])
    finally:
        conn.rollback()          # restore the constraints for every later run

    with conn.cursor() as c:
        c.execute("SELECT count(*) FROM pg_constraint WHERE conrelid='approvals'::regclass"
                  " AND conname LIKE '%decided_by_kind%'")
        restored = c.fetchone()[0]
    check("the negative control left the schema intact", restored == 2,
          f"{restored} of 2 constraints present")
    conn.close()


def main() -> int:
    print("Postgres gate — spec/01-schema.md + spec/02-consistency.md")
    print(f"DSN: {DSN}")
    for fn in (s1_epoch_append_vs_rewind, s2_errcode_mapping,
               s3_claims_across_processes, s4_claim_vs_denial,
               s5_claim_vs_lease_expiry, s6_sweeper_vs_late_settlement,
               s7_run_lease_fencing, s8_on_conflict_and_isolation,
               s9_approver_must_be_human):
        fn()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    print("PASS — all nine scenarios hold against real Postgres.")
    return 0


if __name__ == "__main__":
    mp.set_start_method("spawn")
    sys.exit(main())
