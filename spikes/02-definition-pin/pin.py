"""Content-derived definition pin — the ADR-0011 mechanism.

Derived from MAF's graph_signature_hash (bytecode digest, enforced on restore)
and applied where MAF does not apply it: the AGENT definition.

The rule from ADR-0011 amendment 3: pins are content digests wherever the pinned
thing has content; declared versions are for humans and never compared.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field
from typing import Any


def canonical_digest(obj: Any) -> str:
    """Stable digest of a definition.

    Canonicalisation is load-bearing (MAF: sort_keys + tight separators). A pin
    that varies by dict ordering or whitespace is worse than no pin, because it
    fails randomly instead of never.
    """
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class AgentDefinition:
    """What an agent IS. Content-addressed; the version is informational."""
    name: str
    instructions: str
    tools: list[str] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
    version: int = 1            # human-facing only, NEVER compared

    @property
    def digest(self) -> str:
        # `version` is deliberately excluded: bumping it must not change the
        # digest, and forgetting to bump it must not hide a real change.
        return canonical_digest({
            "name": self.name,
            "instructions": self.instructions,
            "tools": sorted(self.tools),
            "capabilities": self.capabilities,
        })


@dataclass(frozen=True)
class Pin:
    """Recorded on the Run at start; compared on every resume."""
    definition_digest: str
    adapter_identity: str
    adapter_digest: str
    checkpoint_schema_version: int

    def mismatch(self, other: "Pin") -> str | None:
        """Return the FIELD that differs, or None. Naming the field is the point:
        an error that says 'incompatible' sends the operator hunting."""
        for f in ("definition_digest", "adapter_identity",
                  "adapter_digest", "checkpoint_schema_version"):
            if getattr(self, f) != getattr(other, f):
                return f
        return None


class IncompatibleCheckpoint(Exception):
    """Raised on resume across a definition change. Three parts: what was refused,
    the mechanism, the alternative (DESIGN.md 5)."""


@dataclass
class Checkpoint:
    run_id: str
    pin: Pin
    state: dict


class Runtime:
    """Minimal control plane: start a run, checkpoint it, resume it."""

    CHECKPOINT_SCHEMA_VERSION = 1

    def __init__(self, adapter_identity="acp:claude-code", adapter_digest="ad-1"):
        self._adapter_identity = adapter_identity
        self._adapter_digest = adapter_digest
        self._store: dict[str, Checkpoint] = {}

    def _pin_for(self, defn: AgentDefinition) -> Pin:
        return Pin(defn.digest, self._adapter_identity, self._adapter_digest,
                   self.CHECKPOINT_SCHEMA_VERSION)

    def start(self, run_id: str, defn: AgentDefinition, state: dict) -> Checkpoint:
        cp = Checkpoint(run_id, self._pin_for(defn), dict(state))
        self._store[run_id] = cp
        return cp

    def resume(self, run_id: str, defn: AgentDefinition) -> dict:
        cp = self._store[run_id]
        current = self._pin_for(defn)
        bad = cp.pin.mismatch(current)
        if bad:
            raise IncompatibleCheckpoint(
                f"Cannot resume run {run_id}: {bad} changed "
                f"({getattr(cp.pin, bad)!r} -> {getattr(current, bad)!r}). "
                f"The agent definition or adapter was modified after this run "
                f"checkpointed. Start a new run, or restore the prior definition."
            )
        return cp.state
