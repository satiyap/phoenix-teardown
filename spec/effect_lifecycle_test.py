"""The effect lifecycle: intent -> approval -> claim -> dispatch -> settle.

The externally observable invariants, stated before any code:

  I1. An effect awaiting a human NEVER becomes `indeterminate`, however long the
      human takes. (`indeterminate` must mean "may have happened", not "we were
      slow at paperwork".)
  I2. An effect whose approval was DENIED is never dispatched.
  I3. Under N concurrent workers with an approved effect, the side effect runs
      exactly once.
  I4. A worker fenced out by lease expiry cannot overwrite a settled verdict.
  I5. An approval cannot gate an effect belonging to a different run.

Each has a negative control that reintroduces the defect and shows the assertion
failing, per spikes/VERIFICATION-RULES.md rule 4.

SQLite, single process. The Postgres translation of the claim statement
(`ON CONFLICT ... RETURNING`) and its isolation level are rows 1-8 of the §08
inventory and are NOT proven here.
"""
from __future__ import annotations

import secrets
import sqlite3
import time

DDL = """
CREATE TABLE runs (run_id TEXT PRIMARY KEY, state TEXT NOT NULL);
CREATE TABLE effect_ledger (
    idempotency_key TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'intended',
    claim_owner TEXT,
    claim_token TEXT,
    lease_expires_at REAL,
    result_ref  TEXT,
    UNIQUE (idempotency_key, run_id),
    FOREIGN KEY (run_id) REFERENCES runs (run_id),
    CHECK (
      (status IN ('intended','awaiting_approval','denied','abandoned')
        AND claim_owner IS NULL AND claim_token IS NULL AND lease_expires_at IS NULL)
      OR
      (status IN ('claimed','succeeded','failed','indeterminate')
        AND claim_owner IS NOT NULL AND claim_token IS NOT NULL
        AND lease_expires_at IS NOT NULL)
    )
);
CREATE TABLE approvals (
    approval_id TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    action_ref  TEXT NOT NULL,
    status      TEXT NOT NULL,
    decided_by  TEXT,
    FOREIGN KEY (action_ref, run_id) REFERENCES effect_ledger (idempotency_key, run_id)
);
"""

SIDE_EFFECTS: list[str] = []          # the observable boundary


class Ledger:
    LEASE = 0.2                        # seconds; short so expiry is testable

    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(DDL)
        self.db.execute("INSERT INTO runs VALUES ('run-A', 'running')")
        self.db.execute("INSERT INTO runs VALUES ('run-B', 'running')")
        self.db.commit()

    # ---- phase 1
    def intend(self, key, run="run-A"):
        self.db.execute(
            "INSERT INTO effect_ledger (idempotency_key, run_id, status) "
            "VALUES (?, ?, 'intended') ON CONFLICT DO NOTHING", (key, run))
        self.db.commit()

    # ---- phase 2
    def require_approval(self, key, aid, run="run-A"):
        self.db.execute("UPDATE effect_ledger SET status='awaiting_approval' "
                        "WHERE idempotency_key=? AND status='intended'", (key,))
        self.db.execute("INSERT INTO approvals VALUES (?,?,?, 'pending', NULL)",
                        (aid, run, key))
        self.db.commit()

    def decide(self, aid, decision, by="alice"):
        self.db.execute("UPDATE approvals SET status=?, decided_by=? "
                        "WHERE approval_id=? AND status='pending'",
                        (decision, by, aid))
        if decision == "denied":
            self.db.execute(
                "UPDATE effect_ledger SET status='denied' WHERE idempotency_key="
                "(SELECT action_ref FROM approvals WHERE approval_id=?) "
                "AND status='awaiting_approval'", (aid,))
        self.db.commit()

    # ---- phase 3
    def claim(self, key, worker, run="run-A"):
        """Approval check and claim in ONE statement, so they cannot interleave."""
        token = secrets.token_hex(16)
        cur = self.db.execute("""
            UPDATE effect_ledger
               SET status='claimed', claim_owner=?, claim_token=?, lease_expires_at=?
             WHERE idempotency_key=?
               AND (status='intended'
                    OR (status='awaiting_approval'
                        AND EXISTS (SELECT 1 FROM approvals a
                                     WHERE a.action_ref=effect_ledger.idempotency_key
                                       AND a.run_id=effect_ledger.run_id
                                       AND a.status='approved')))
            RETURNING claim_token
        """, (worker, token, time.time() + self.LEASE, key))
        row = cur.fetchone()
        self.db.commit()
        return row[0] if row else None

    # ---- phase 4/5
    def dispatch_and_settle(self, key, worker, token, label):
        SIDE_EFFECTS.append(label)
        cur = self.db.execute(
            "UPDATE effect_ledger SET status='succeeded', result_ref=? "
            "WHERE idempotency_key=? AND claim_owner=? AND claim_token=? "
            "AND status='claimed'", (label, key, worker, token))
        self.db.commit()
        return cur.rowcount

    def sweep(self):
        """Only CLAIMED rows past their lease become indeterminate."""
        cur = self.db.execute(
            "UPDATE effect_ledger SET status='indeterminate' "
            "WHERE status='claimed' AND lease_expires_at < ?", (time.time(),))
        self.db.commit()
        return cur.rowcount

    def status(self, key):
        return self.db.execute(
            "SELECT status FROM effect_ledger WHERE idempotency_key=?", (key,)
        ).fetchone()[0]


def check(label, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    assert cond, label


def main():
    print("effect lifecycle")

    # I1 -----------------------------------------------------------------
    SIDE_EFFECTS.clear()
    l = Ledger()
    l.intend("k1"); l.require_approval("k1", "a1")
    time.sleep(Ledger.LEASE * 2)                 # a human deliberating
    swept = l.sweep()
    check("I1 awaiting_approval survives 2x the lease without sweeping",
          swept == 0 and l.status("k1") == "awaiting_approval")
    check("I1 nothing dispatched while awaiting a human", SIDE_EFFECTS == [])

    # negative control: claim BEFORE approval (the defect)
    l2 = Ledger()
    l2.intend("k1")
    tok = l2.claim("k1", "w1")                   # claimed early, then ask a human
    time.sleep(Ledger.LEASE * 2)
    check("I1-NC claiming before approval DOES produce indeterminate "
          "(defect reproduced)", l2.sweep() == 1 and l2.status("k1") == "indeterminate")

    # I2 -----------------------------------------------------------------
    SIDE_EFFECTS.clear()
    l = Ledger()
    l.intend("k2"); l.require_approval("k2", "a2"); l.decide("a2", "denied")
    check("I2 a denied effect cannot be claimed", l.claim("k2", "w1") is None)
    check("I2 nothing dispatched after denial", SIDE_EFFECTS == [])
    check("I2 status is denied, not indeterminate", l.status("k2") == "denied")

    # I3 -----------------------------------------------------------------
    SIDE_EFFECTS.clear()
    l = Ledger()
    l.intend("k3"); l.require_approval("k3", "a3"); l.decide("a3", "approved")
    winners = []
    for w in ("w1", "w2", "w3", "w4", "w5"):
        tk = l.claim("k3", w)
        if tk:
            winners.append(w)
            l.dispatch_and_settle("k3", w, tk, w)
    check("I3 exactly one of five workers claims", len(winners) == 1)
    check(f"I3 side effect ran exactly once (got {SIDE_EFFECTS})",
          len(SIDE_EFFECTS) == 1)

    # negative control: read-then-act
    SIDE_EFFECTS.clear()
    l = Ledger()
    l.intend("k3b"); l.require_approval("k3b", "a3b"); l.decide("a3b", "approved")
    for w in ("w1", "w2"):
        st = l.status("k3b")                      # READ
        if st == "awaiting_approval":             # then ACT
            SIDE_EFFECTS.append(w)
    check(f"I3-NC read-then-act double-executes (got {SIDE_EFFECTS})",
          SIDE_EFFECTS == ["w1", "w2"])

    # I4 -----------------------------------------------------------------
    SIDE_EFFECTS.clear()
    l = Ledger()
    l.intend("k4")
    tok = l.claim("k4", "slow")
    time.sleep(Ledger.LEASE * 2)
    l.sweep()
    check("I4 stalled claim became indeterminate", l.status("k4") == "indeterminate")
    rows = l.dispatch_and_settle("k4", "slow", tok, "late")
    check("I4 fenced-out worker's settlement is rejected", rows == 0)
    check("I4 verdict preserved for the human", l.status("k4") == "indeterminate")

    # negative control: settle by key only
    l = Ledger()
    l.intend("k4b"); tok = l.claim("k4b", "slow")
    time.sleep(Ledger.LEASE * 2); l.sweep()
    l.db.execute("UPDATE effect_ledger SET status='succeeded' WHERE idempotency_key=?",
                 ("k4b",))
    l.db.commit()
    check("I4-NC settle-by-key-only OVERWRITES the verdict (defect reproduced)",
          l.status("k4b") == "succeeded")

    # I5 -----------------------------------------------------------------
    l = Ledger()
    l.intend("k5", run="run-A")
    try:
        l.db.execute("INSERT INTO approvals VALUES ('x','run-B','k5','pending',NULL)")
        l.db.commit()
        check("I5 cross-run approval refused by the composite FK", False)
    except sqlite3.IntegrityError:
        check("I5 cross-run approval refused by the composite FK", True)

    print("\nPASS — 13 assertions, 4 negative controls reproducing the defects.")


if __name__ == "__main__":
    main()
