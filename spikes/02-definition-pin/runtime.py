"""Durable runtime: SQLite-backed runs, a real adapter, pin checked BEFORE start.

The review's point: hashing an object in memory and comparing it later is
tautological. The dangerous boundary is (a) surviving process death, (b) resolving
the definition artifact by digest rather than trusting the caller, and (c) proving
no adapter code runs before validation.
"""
from __future__ import annotations
import json, sqlite3
from pin import (AgentDefinition, AdapterContract, Pin, canonical_digest,
                 IncompatibleCheckpoint, ArtifactMissing, ArtifactCorrupted,
                 ConcurrentResume)

CHECKPOINT_SCHEMA_VERSION = 1


class AdapterInvoked(Exception):
    """Raised by the tripwire adapter to prove ordering."""


class TripwireAdapter:
    """Records every call so a test can assert the pin was checked FIRST.

    `payload_schema_digest` is the ADAPTER's own checkpoint format, distinct from
    the platform envelope version.
    """
    def __init__(self, contract: AdapterContract, fail_if_called=False,
                 payload_schema_digest="pay-v1"):
        self.contract = contract
        self.payload_schema_digest = payload_schema_digest
        self.calls: list[str] = []
        self.executed_definition: dict | None = None
        self._fail = fail_if_called

    def start(self, run_id, state, *, resolved_definition=None):
        self.calls.append("start")
        if self._fail:
            raise AdapterInvoked("adapter ran before the pin was validated")
        # what actually EXECUTES is recorded, so a test can prove closure
        self.executed_definition = resolved_definition
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
            payload_schema_digest TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL,
            FOREIGN KEY (definition_digest) REFERENCES definitions(digest)
        );
        -- An atomic resume lease. Pin correctness does not prevent DUPLICATE
        -- execution: two workers can both hold a valid pin. The lease is the
        -- primitive, exactly as the effect ledger is for side effects.
        CREATE TABLE IF NOT EXISTS resume_leases (
            run_id TEXT PRIMARY KEY,
            holder TEXT NOT NULL
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

    @staticmethod
    def digest_of_body(body: dict) -> str:
        """Recompute a stored artifact's digest from its own bytes."""
        from pin import AgentDefinition, ToolBinding
        tools = tuple(ToolBinding(**t) for t in body["tools"])
        return AgentDefinition(body["name"], body["instructions"], tools,
                               tuple(body["extensions"])).digest

    def get_definition_body(self, digest: str) -> dict | None:
        r = self.db.execute("SELECT body FROM definitions WHERE digest=?", (digest,)).fetchone()
        return json.loads(r[0]) if r else None

    def save_run(self, run_id: str, pin: Pin, state: dict) -> None:
        row = pin.as_row()
        self.db.execute(
            "INSERT INTO runs(run_id, definition_digest, adapter_identity,"
            " adapter_digest, checkpoint_schema_version, payload_schema_digest, state)"
            " VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(run_id) DO UPDATE SET state=excluded.state",
            (run_id, row["definition_digest"], row["adapter_identity"],
             row["adapter_digest"], row["checkpoint_schema_version"],
             row["payload_schema_digest"], json.dumps(state)))
        self.db.commit()

    def load_run(self, run_id: str) -> tuple[Pin, dict] | None:
        r = self.db.execute(
            "SELECT definition_digest, adapter_identity, adapter_digest,"
            " checkpoint_schema_version, payload_schema_digest, state"
            " FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            return None
        return Pin(r[0], r[1], r[2], int(r[3]), r[4]), json.loads(r[5])

    def acquire_resume_lease(self, run_id: str, holder: str) -> bool:
        """True iff THIS caller won the right to resume. Atomic."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO resume_leases(run_id, holder) VALUES(?,?)",
            (run_id, holder))
        self.db.commit()
        return cur.rowcount == 1


class Runtime:
    """A control plane that can be destroyed and rebuilt over the same store."""

    def __init__(self, store: Store):
        self.store = store

    def start(self, run_id: str, defn: AgentDefinition, adapter: TripwireAdapter,
              state: dict) -> Pin:
        self.store.put_definition(defn)
        pin = Pin(defn.digest, adapter.contract.identity,
                  adapter.contract.digest, CHECKPOINT_SCHEMA_VERSION,
                  adapter.payload_schema_digest)
        self.store.save_run(run_id, pin, state)
        return pin

    def resume(self, run_id: str, defn: AgentDefinition,
               adapter: TripwireAdapter, *, holder: str = "worker-1") -> dict:
        """Validate, verify, lease — THEN execute the resolved artifact.

        Order is the contract:
          1. load the pin
          2. resolve the pinned artifact from the registry (not the caller's object)
          3. verify the artifact hashes to its own key   -> ArtifactCorrupted
          4. compare the pin                            -> IncompatibleCheckpoint
          5. acquire an ATOMIC lease                     -> ConcurrentResume
          6. only now touch the adapter, passing the RESOLVED artifact
        """
        loaded = self.store.load_run(run_id)
        if loaded is None:
            raise KeyError(run_id)
        pinned, state = loaded

        # (2) resolve by digest — the caller cannot substitute a definition
        body = self.store.get_definition_body(pinned.definition_digest)
        if body is None:
            raise ArtifactMissing(
                f"Cannot resume run {run_id}: pinned definition "
                f"{pinned.definition_digest[:12]}… is not in the registry. "
                f"Restore that artifact, then retry. (Distinct from a version "
                f"mismatch: nothing changed, something is missing.)")

        # (3) integrity: the digest IS the key, so recomputing must agree
        recomputed = self.store.digest_of_body(body)
        if recomputed != pinned.definition_digest:
            raise ArtifactCorrupted(
                f"Cannot resume run {run_id}: stored artifact does not hash to "
                f"its own key ({recomputed[:12]}… != "
                f"{pinned.definition_digest[:12]}…). This is a storage-integrity "
                f"incident, not a version mismatch. Re-fetch the artifact.")

        # (4) pin comparison
        current = Pin(defn.digest, adapter.contract.identity,
                      adapter.contract.digest, CHECKPOINT_SCHEMA_VERSION,
                      adapter.payload_schema_digest)
        bad = pinned.mismatch(current)
        if bad:
            raise IncompatibleCheckpoint(
                f"Cannot resume run {run_id}: {bad} changed "
                f"({getattr(pinned, bad)!r} -> {getattr(current, bad)!r}). "
                f"The agent definition or adapter was modified after this run "
                f"checkpointed. Start a new run, or restore the prior definition.")

        # (5) atomic lease: pin correctness does NOT prevent duplicate execution
        if not self.store.acquire_resume_lease(run_id, holder):
            raise ConcurrentResume(
                f"Cannot resume run {run_id}: another worker holds the resume "
                f"lease. No action needed — this is the guard working.")

        # (6) execute the RESOLVED artifact, closing the check/use gap
        return adapter.start(run_id, state, resolved_definition=body)
