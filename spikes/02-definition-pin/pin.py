"""Content-derived definition pin — ADR-0011, hardened.

Revised after review found the first version unsafe: `default=str` admitted
arbitrary objects (embedding memory addresses, so identical definitions in two
processes produced different digests and NOTHING would resume), NaN/Infinity were
accepted, and tools were hashed by name only.

Rule from ADR-0011 amendment 3: pins are content digests wherever the pinned thing
has content; declared versions are for humans and are never compared.
"""
from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import dataclass, field
from typing import Any


class NonCanonical(Exception):
    """A value cannot be canonically digested. Fail loudly: a digest that varies
    between processes is worse than no digest, because it fails randomly."""


_ALLOWED = (str, int, bool, type(None), float, list, tuple, dict)


def _canon(v: Any, path: str = "$") -> Any:
    """Reject anything whose serialisation is not stable across processes."""
    if isinstance(v, bool) or v is None or isinstance(v, int):
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            raise NonCanonical(f"{path}: non-finite float {v!r} has no canonical form")
        return v
    if isinstance(v, str):
        # NFC so 'café' (composed) and 'cafe\u0301' (decomposed) agree.
        return unicodedata.normalize("NFC", v)
    if isinstance(v, (list, tuple)):
        return [_canon(x, f"{path}[{i}]") for i, x in enumerate(v)]
    if isinstance(v, dict):
        out = {}
        for k in v:
            if not isinstance(k, str):
                raise NonCanonical(f"{path}: non-string key {k!r}")
            out[unicodedata.normalize("NFC", k)] = _canon(v[k], f"{path}.{k}")
        return out
    raise NonCanonical(
        f"{path}: {type(v).__name__} is not canonically serialisable. "
        f"Convert it to a str/int/float/bool/None/list/dict before digesting."
    )


def canonical_digest(obj: Any) -> str:
    """Stable SHA-256 over a canonicalised structure.

    Canonicalisation is load-bearing (MAF: sort_keys + tight separators). No
    `default=` fallback: unsupported types raise.
    """
    blob = json.dumps(_canon(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ToolBinding:
    """A tool is not a name. Everything here changes what the agent can DO,
    so everything here is in the digest."""
    name: str
    schema_digest: str          # digest of the JSON schema
    version: str
    execution_binding: str      # e.g. "mcp:learn@https://..." or "local:python"
    approval_mode: str          # never | always | risk_based
    credential_ref: str | None = None

    def as_canon(self) -> dict:
        return {"name": self.name, "schema_digest": self.schema_digest,
                "version": self.version, "execution_binding": self.execution_binding,
                "approval_mode": self.approval_mode,
                "credential_ref": self.credential_ref}


@dataclass(frozen=True)
class AdapterContract:
    """The adapter digest must be DERIVED, not caller-supplied."""
    identity: str               # "acp:claude-code"
    protocol_version: str
    integration_mode: str       # Omnigent's taxonomy
    declared_capabilities: dict[str, Any] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        return canonical_digest({
            "identity": self.identity,
            "protocol_version": self.protocol_version,
            "integration_mode": self.integration_mode,
            "declared_capabilities": self.declared_capabilities,
        })


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    instructions: str
    tools: tuple[ToolBinding, ...] = ()
    extensions: tuple[str, ...] = ()     # installed behaviour (ADR-0012)
    version: int = 1                     # human-facing only, NEVER digested

    def __post_init__(self):
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise NonCanonical(f"duplicate tool names: {dupes}")

    @property
    def digest(self) -> str:
        return canonical_digest({
            "name": self.name,
            "instructions": self.instructions,
            # sorted by name: tool ORDER is not semantic, tool SET is
            "tools": [t.as_canon() for t in sorted(self.tools, key=lambda t: t.name)],
            "extensions": sorted(self.extensions),
        })


@dataclass(frozen=True)
class Pin:
    definition_digest: str
    adapter_identity: str
    adapter_digest: str
    checkpoint_schema_version: int

    def mismatch(self, other: "Pin") -> str | None:
        for f in ("definition_digest", "adapter_identity",
                  "adapter_digest", "checkpoint_schema_version"):
            if getattr(self, f) != getattr(other, f):
                return f
        return None

    def as_row(self) -> dict:
        return {"definition_digest": self.definition_digest,
                "adapter_identity": self.adapter_identity,
                "adapter_digest": self.adapter_digest,
                "checkpoint_schema_version": self.checkpoint_schema_version}

    @staticmethod
    def from_row(r: dict) -> "Pin":
        return Pin(r["definition_digest"], r["adapter_identity"],
                   r["adapter_digest"], int(r["checkpoint_schema_version"]))


class IncompatibleCheckpoint(Exception):
    pass
