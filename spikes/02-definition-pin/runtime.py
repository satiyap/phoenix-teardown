"""Durable runtime: SQLite-backed runs, a real adapter, pin checked BEFORE start.

The review's point: hashing an object in memory and comparing it later is
tautological. The dangerous boundary is (a) surviving process death, (b) resolving
the definition artifact by digest rather than trusting the caller, and (c) proving
no adapter code runs before validation.
"""
from __future__ import annotations
import json, sqlite3
from pin import (AgentDefinition, AdapterContract, Pin, IncompatibleCheckpoint,
                 canonical_digest)

CHECKPOINT_SCHEMA_VERSION = 1


class AdapterInvoked(Exception):
    """Raised by the tripwire adapter to prove ordering."""


class TripwireAdapter:
    """Records every call so a test can assert the pin was checked FIRST."""
    def __init__(self, contract: AdapterContract, fail_if_called=False):
        self.contract = contract
        self.calls: list[str] = []
        self._fail = fail_if_called

    def start(self, run_id, state):
        self.calls.append("start")
        if self._fail:
            raise AdapterInvoked("adapter ran before the pin was validated")
        return {"resumed_from": state}


class Store:
    """Durable definition registry + run/checkpoint tables."""

    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS definitions (
            digest TEXT PRIMARY KEY,
            body   TEXT NOT NULL          -- immutable, content-addressed
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            definition_digest TEXT NOT NULL,
            adapter_identity  TEXT NOT NULL,
            adapter_digest    TEXT NOT NULL,
            checkpoint_schema_version INTEGER NOT NULL,
            state TEXT NOT NULL,
            FOREIGN KEY (definition_digest) REFERENCES definitions(digest)
        );
        """)
        self.db.commit()

    # definitions are content-addressed: putting the same one twice is a no-op
    def put_definition(self, defn: AgentDefinition) -> str:
        body = json.dumps({"name": defn.name, "instructions": defn.instructions,
                           "tools": [t.as_canon() for t in defn.tools],
                           "extensions": list(defn.extensions),
                           "version": defn.version}, sort_keys=True)
        self.db.execute("INSERT OR IGNORE INTO definitions(digest, body) VALUES(?,?)",
                        (defn.digest, body))
        self.db.commit()
        return defn.digest

    def get_definition_body(self, digest: str) -> dict | None:
        r = self.db.execute("SELECT body FROM definitions WHERE digest=?", (digest,)).fetchone()
        return json.loads(r[0]) if r else None

    def save_run(self, run_id: str, pin: Pin, state: dict) -> None:
        row = pin.as_row()
        self.db.execute(
            "INSERT INTO runs(run_id, definition_digest, adapter_identity,"
            " adapter_digest, checkpoint_schema_version, state)"
            " VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(run_id) DO UPDATE SET state=excluded.state",
            (run_id, row["definition_digest"], row["adapter_identity"],
             row["adapter_digest"], row["checkpoint_schema_version"], json.dumps(state)))
        self.db.commit()

    def load_run(self, run_id: str) -> tuple[Pin, dict] | None:
        r = self.db.execute(
            "SELECT definition_digest, adapter_identity, adapter_digest,"
            " checkpoint_schema_version, state FROM runs WHERE run_id=?",
            (run_id,)).fetchone()
        if not r:
            return None
        return Pin(r[0], r[1], r[2], int(r[3])), json.loads(r[4])


class Runtime:
    """A control plane that can be destroyed and rebuilt over the same store."""

    def __init__(self, store: Store):
        self.store = store

    def start(self, run_id: str, defn: AgentDefinition, adapter: TripwireAdapter,
              state: dict) -> Pin:
        self.store.put_definition(defn)
        pin = Pin(defn.digest, adapter.contract.identity,
                  adapter.contract.digest, CHECKPOINT_SCHEMA_VERSION)
        self.store.save_run(run_id, pin, state)
        return pin

    def resume(self, run_id: str, defn: AgentDefinition,
               adapter: TripwireAdapter) -> dict:
        """Validate BEFORE touching the adapter.

        Note the definition is resolved from the durable registry by digest, so a
        caller cannot hand us a definition we never recorded.
        """
        loaded = self.store.load_run(run_id)
        if loaded is None:
            raise KeyError(run_id)
        pinned, state = loaded

        if self.store.get_definition_body(pinned.definition_digest) is None:
            raise IncompatibleCheckpoint(
                f"Cannot resume run {run_id}: the pinned definition "
                f"{pinned.definition_digest[:12]}… is no longer in the registry. "
                f"Restore that definition artifact, or start a new run.")

        current = Pin(defn.digest, adapter.contract.identity,
                      adapter.contract.digest, CHECKPOINT_SCHEMA_VERSION)
        bad = pinned.mismatch(current)
        if bad:
            raise IncompatibleCheckpoint(
                f"Cannot resume run {run_id}: {bad} changed "
                f"({getattr(pinned, bad)!r} -> {getattr(current, bad)!r}). "
                f"The agent definition or adapter was modified after this run "
                f"checkpointed. Start a new run, or restore the prior definition.")

        return adapter.start(run_id, state)      # only now
