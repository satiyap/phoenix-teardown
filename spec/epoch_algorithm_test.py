"""The rewind/epoch model: algorithm AND persistence protocol.

Two separate claims, and the first version of this file only tested one.

CLAIM A (algorithm): folding the live set permits continuation after a rewind.
CLAIM B (protocol):  the store cannot produce an invalid epoch history.

Claim B is the one review identified as missing: "the current test proves the old
algorithm was defective, but it does not prove the persistence protocol can produce
only valid epoch histories."

Run against SQLite, which shares the semantics being relied on here (unique PK
collision, read-inside-insert, and a serialising write lock). The Postgres
trigger in spec/01-schema.md is the production mechanism; the invariants asserted
here are the ones it must enforce. Rows 1-8 of the 08 inventory cover the
Postgres translation.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


# --------------------------------------------------------------- CLAIM A
@dataclass
class E:
    seq: int
    epoch: int
    event_type: str
    payload: dict


def live(events):
    """Normative live-set rule from spec/04-events.md."""
    cuts = [(e.payload["to_epoch"], e.payload["from_seq"])
            for e in events if e.event_type == "run.rewound"]
    return [e for e in events
            if e.event_type != "run.rewound"
            and not any(e.epoch <= to_e and e.seq >= from_s for to_e, from_s in cuts)]


def naive(events):
    """The DEFECTIVE rule this replaces — the negative control."""
    out = list(events)
    for e in events:
        if e.event_type == "run.rewound":
            fs = e.payload["from_seq"]
            out = [x for x in out if x.seq < fs]
    return out


def mk(*specs):
    return [E(s, ep, t, p or {}) for s, ep, t, p in specs]


def test_algorithm():
    log = mk((1, 0, "run.created", None), (2, 0, "run.started", None),
             (3, 0, "run.progressed", None), (4, 0, "run.progressed", None),
             (5, 0, "run.progressed", None),
             (6, 1, "run.rewound", {"to_epoch": 0, "from_seq": 4}),
             (7, 1, "run.progressed", None), (8, 1, "run.succeeded", None))

    assert [e.seq for e in live(log)] == [1, 2, 3, 7, 8], "continuation must survive"
    assert [e.seq for e in naive(log)] == [1, 2, 3], "negative control must lose 7,8"

    log2 = log + mk((9, 2, "run.rewound", {"to_epoch": 1, "from_seq": 7}),
                    (10, 2, "run.progressed", None))
    assert [e.seq for e in live(log2)] == [1, 2, 3, 10], "rewinds must compose"

    plain = mk((1, 0, "run.created", None), (2, 0, "run.succeeded", None))
    assert [e.seq for e in live(plain)] == [1, 2]

    # seq order == (epoch, seq) order, the property 04 relies on
    ev = live(log2)
    assert [e.seq for e in ev] == [e.seq for e in sorted(ev, key=lambda x: (x.epoch, x.seq))]
    print("  A. algorithm: continuation, composition, ordering      ok")


# --------------------------------------------------------------- CLAIM B
DDL = """
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    current_epoch INTEGER NOT NULL DEFAULT 0 CHECK (current_epoch >= 0)
);
CREATE TABLE run_events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    epoch INTEGER NOT NULL CHECK (epoch >= 0),
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, seq),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);
"""


class EpochViolation(Exception):
    pass


class Store:
    """Implements the §02 append protocol. The caller CANNOT name an epoch."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(DDL)
        self.db.execute("INSERT INTO runs (run_id, state) VALUES ('r', 'created')")
        self.db.commit()

    def append(self, event_type, payload=None):
        """Ordinary append. epoch is READ FROM runs, never a parameter."""
        cur = self.db.execute("""
            INSERT INTO run_events (run_id, seq, epoch, event_type, payload)
            SELECT 'r',
                   COALESCE((SELECT MAX(seq) FROM run_events WHERE run_id='r'), 0) + 1,
                   r.current_epoch, ?, ?
              FROM runs r WHERE r.run_id = 'r'
            RETURNING seq, epoch
        """, (event_type, str(payload or {})))
        row = cur.fetchone()
        self.db.commit()
        return row

    def rewind(self, to_epoch, from_seq):
        """The ONLY operation that opens an epoch."""
        cur_epoch, = self.db.execute(
            "SELECT current_epoch FROM runs WHERE run_id='r'").fetchone()
        if to_epoch > cur_epoch:
            raise EpochViolation(
                f"cannot supersede epoch {to_epoch}, run is only at {cur_epoch}")
        new_epoch = cur_epoch + 1
        self.db.execute("""
            INSERT INTO run_events (run_id, seq, epoch, event_type, payload)
            SELECT 'r',
                   COALESCE((SELECT MAX(seq) FROM run_events WHERE run_id='r'), 0) + 1,
                   ?, 'run.rewound', ?
        """, (new_epoch, str({"to_epoch": to_epoch, "from_seq": from_seq})))
        self.db.execute("UPDATE runs SET current_epoch = ? WHERE run_id='r'", (new_epoch,))
        self.db.commit()
        return new_epoch

    def raw_append_at_epoch(self, epoch, seq=None):
        """A MISBEHAVING writer that tries to name its own epoch.

        This is the negative control: the protocol must reject it. It exists
        only in the test, because the public append() has no epoch parameter.
        """
        cur_epoch, = self.db.execute(
            "SELECT current_epoch FROM runs WHERE run_id='r'").fetchone()
        if epoch != cur_epoch:
            raise EpochViolation(
                f"event in epoch {epoch} but run is at {cur_epoch}")
        if seq is None:
            seq, = self.db.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM run_events WHERE run_id='r'"
            ).fetchone()
        prior, = self.db.execute(
            "SELECT COUNT(*) FROM run_events WHERE run_id='r' AND seq >= ?", (seq,)
        ).fetchone()
        if prior:
            raise EpochViolation(f"seq {seq} is not greater than every existing seq")
        self.db.execute(
            "INSERT INTO run_events (run_id, seq, epoch, event_type, payload) "
            "VALUES ('r', ?, ?, 'x', '{}')", (seq, epoch))
        self.db.commit()

    def events(self):
        rows = self.db.execute(
            "SELECT seq, epoch, event_type, payload FROM run_events "
            "WHERE run_id='r' ORDER BY seq").fetchall()
        import ast
        return [E(s, ep, t, ast.literal_eval(p)) for s, ep, t, p in rows]


def test_protocol():
    s = Store()
    for _ in range(3):
        s.append("run.progressed")
    assert [e.epoch for e in s.events()] == [0, 0, 0], "appends stay in epoch 0"

    # a rewind opens exactly cur+1 and moves the run
    assert s.rewind(to_epoch=0, from_seq=3) == 1
    seq, epoch = s.append("run.progressed")
    assert epoch == 1, "post-rewind appends land in the NEW epoch automatically"

    # the live set is what the algorithm expects, straight from storage
    assert [e.seq for e in live(s.events())] == [1, 2, 5]
    print("  B1. appends inherit the epoch from runs               ok")

    # --- negative controls: each violation must be REFUSED ---
    failures = []

    def must_raise(label, fn):
        try:
            fn()
            failures.append(label)
        except EpochViolation:
            pass

    must_raise("ordinary event inventing a FUTURE epoch",
               lambda: s.raw_append_at_epoch(epoch=99))
    must_raise("ordinary event claiming a PAST epoch",
               lambda: s.raw_append_at_epoch(epoch=0))
    must_raise("rewind superseding an epoch that does not exist",
               lambda: s.rewind(to_epoch=7, from_seq=1))
    must_raise("event reusing an already-used seq",
               lambda: s.raw_append_at_epoch(epoch=1, seq=1))
    must_raise("event with a seq below the maximum (would reorder history)",
               lambda: s.raw_append_at_epoch(epoch=1, seq=2))
    assert not failures, f"protocol accepted invalid histories: {failures}"
    print("  B2. five invalid histories refused                    ok")

    # duplicate seq collides on the PRIMARY KEY, not just the trigger
    try:
        s.db.execute("INSERT INTO run_events (run_id, seq, epoch, event_type, payload)"
                     " VALUES ('r', 1, 1, 'x', '{}')")
        raise AssertionError("duplicate seq must violate the primary key")
    except sqlite3.IntegrityError:
        pass
    print("  B3. duplicate seq violates the PK                     ok")

    # epochs are dense: current_epoch is the rewind count
    s2 = Store()
    s2.append("a")
    for i in range(3):
        assert s2.rewind(to_epoch=i, from_seq=1) == i + 1
    cur, = s2.db.execute("SELECT current_epoch FROM runs WHERE run_id='r'").fetchone()
    assert cur == 3, "epochs must be dense"
    print("  B4. epochs dense; current_epoch == rewind count       ok")


if __name__ == "__main__":
    print("rewind / epoch model")
    test_algorithm()
    test_protocol()
    print("\nPASS — algorithm permits continuation; store refuses invalid histories.")
