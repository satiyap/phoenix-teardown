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


# JCS numbers, honestly scoped.
#
# RFC 8785 3.2.2.3 mandates ECMAScript Number::toString. Python's json does NOT
# implement it: it emits "1.0" where JCS requires "1", and "1e-07" where
# ECMAScript requires "1e-7". Rather than reimplement ECMAScript formatting and
# risk a subtle cross-language mismatch, the profile RESTRICTS the number domain
# to the range where Python and JCS provably agree, and REJECTS the rest.
#
# A rejected number is a loud error the caller must resolve (usually by encoding
# the value as a string). A silently mis-serialised number is a digest that
# differs across languages, which is the failure this whole profile exists to
# prevent.
_INT_SAFE = 2**53 - 1


def _jcs_number(v: float, path: str) -> int:
    """Accept only integral values in the JS-safe range; reject everything else."""
    if not v.is_integer():
        raise NonCanonical(
            f"{path}: non-integral number {v!r} is outside profile nfc+jcs/v1. "
            f"Python's json and ECMAScript Number::toString disagree on exponent "
            f"and fraction formatting, so a fractional value would digest "
            f"differently across languages. Encode it as a string.")
    if abs(v) > _INT_SAFE:
        raise NonCanonical(
            f"{path}: {v!r} exceeds 2^53-1 and cannot round-trip through a JSON "
            f"number in every language. Encode it as a string.")
    return int(v)


def _reject_lone_surrogates(s: str, path: str) -> None:
    r"""Reject unpaired UTF-16 surrogates (U+D800..U+DFFF).

    These are not characters; they only exist as PAIRS inside UTF-16. Languages
    disagree on what to do with a lone one, which was verified rather than assumed:

        Python  json/encode : UnicodeEncodeError
        JS      JSON.stringify: accepts, emits "\ud800", produces a digest

    So a lone surrogate is an "incompatible by accident" value: one implementation
    refuses, another silently digests. Rejecting it explicitly in the PROFILE is what
    keeps a future language from legitimately disagreeing.
    """
    for i, ch in enumerate(s):
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise NonCanonical(
                f"{path}: unpaired UTF-16 surrogate U+{ord(ch):04X} at index {i}. "
                f"Surrogates are not characters; they exist only as pairs in UTF-16, "
                f"and implementations disagree on lone ones (Python raises, "
                f"JavaScript digests). Remove it or encode the text as bytes.")


def _canon(v: Any, path: str = "$") -> Any:
    """Reject anything whose serialisation is not stable across processes."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int):
        if abs(v) > _INT_SAFE:
            raise NonCanonical(
                f"{path}: integer {v!r} exceeds 2^53-1 and cannot round-trip "
                f"through a JSON number in every language. Encode it as a string.")
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            raise NonCanonical(f"{path}: non-finite float {v!r} has no canonical form")
        return _jcs_number(v, path)
    if isinstance(v, str):
        _reject_lone_surrogates(v, path)
        # NFC so 'café' (composed) and 'cafe\u0301' (decomposed) agree.
        return unicodedata.normalize("NFC", v)
    if isinstance(v, (list, tuple)):
        return [_canon(x, f"{path}[{i}]") for i, x in enumerate(v)]
    if isinstance(v, dict):
        out: dict[str, Any] = {}
        origin: dict[str, str] = {}
        for k in v:
            if not isinstance(k, str):
                raise NonCanonical(f"{path}: non-string key {k!r}")
            _reject_lone_surrogates(k, f"{path} (key)")
            nk = unicodedata.normalize("NFC", k)
            if nk in origin:
                # Two DISTINCT keys that normalise to the same key. Overwriting
                # one silently loses a field and produces a digest for an object
                # the caller never supplied. Reject.
                raise NonCanonical(
                    f"{path}: keys {origin[nk]!r} and {k!r} both normalise to "
                    f"{nk!r} under NFC. One would silently overwrite the other. "
                    f"Rename one of them.")
            origin[nk] = k
            out[nk] = _canon(v[k], f"{path}.{nk}")
        return out
    raise NonCanonical(
        f"{path}: {type(v).__name__} is not canonically serialisable. "
        f"Convert it to a str/int/float/bool/None/list/dict before digesting."
    )


# The canonicalisation PROFILE, named and versioned.
#
# RFC 8785 (JCS) alone does NOT normalise Unicode, so "JCS" is an insufficient
# spec. Ours is: NFC normalisation of every string and key, THEN JCS-style
# serialisation (sorted keys, tight separators, no NaN/Inf, UTF-8).
CANON_PROFILE = "nfc+intjson"
CANON_VERSION = 1


def canonical_digest(obj: Any, *, kind: str = "generic") -> str:
    """Stable SHA-256 over a DOMAIN-SEPARATED, VERSIONED envelope.

    Without `kind` a tool digest could collide with a definition digest that
    happens to canonicalise identically. Without `canonicalization_version`,
    changing the canonicaliser silently invalidates every old pin with no way to
    tell "changed" from "recomputed differently".
    """
    envelope = {
        "kind": kind,
        "canonicalization": f"{CANON_PROFILE}/v{CANON_VERSION}",
        "payload": _canon(obj),
    }
    blob = _emit(envelope)
    return hashlib.sha256(blob).hexdigest()


def _emit(v: Any) -> bytes:
    """Serialise with an EXPLICIT sort rule: UTF-8 byte order.

    `json.dumps(sort_keys=True)` sorts by Unicode CODE POINT. RFC 8785 requires
    UTF-16 CODE UNIT order, and the two disagree for non-BMP characters:

        code point order : U+E000, U+1F600      (Python)
        UTF-16 unit order: U+1F600, U+E000      (JCS)

    because a non-BMP character becomes a surrogate pair starting 0xD800, which
    sorts BELOW U+E000. So `sort_keys=True` is NOT JCS, and this profile does not
    pretend to be. We specify **UTF-8 byte order**: simpler to state, identical
    to code point order (a property of UTF-8, so no surprises), and trivially
    reimplementable in any language with a byte comparator.
    """
    if isinstance(v, dict):
        items = sorted(v.items(), key=lambda kv: kv[0].encode("utf-8"))
        inner = b",".join(_emit_str(k) + b":" + _emit(x) for k, x in items)
        return b"{" + inner + b"}"
    if isinstance(v, (list, tuple)):
        return b"[" + b",".join(_emit(x) for x in v) + b"]"
    if isinstance(v, str):
        return _emit_str(v)
    if isinstance(v, bool):
        return b"true" if v else b"false"
    if v is None:
        return b"null"
    if isinstance(v, int):
        return str(v).encode("utf-8")
    raise NonCanonical(f"_emit: unexpected {type(v).__name__} after canonicalisation")


def _emit_str(s: str) -> bytes:
    """JSON string escaping per RFC 8785 6.1 (the part we DO follow)."""
    return json.dumps(s, ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class ToolBinding:
    """A tool is not a name, and a version string is not an artifact.

    `artifact_digest` is REQUIRED: a version pointing at mutable code preserves
    the pin while changing behaviour, which is the whole failure mode we are
    trying to prevent one level up.
    """
    name: str
    schema_digest: str          # digest of the JSON schema
    version: str                # human-facing label
    artifact_digest: str        # IMMUTABLE code/image identity — load-bearing
    execution_binding: str      # e.g. "mcp:learn@https://..." | "local:python"
    approval_mode: str          # never | always | risk_based
    credential_ref: str | None = None

    def __post_init__(self):
        if not self.artifact_digest:
            raise NonCanonical(
                f"tool {self.name!r}: artifact_digest is required. A version "
                f"string that points at mutable code preserves the pin while "
                f"changing behaviour.")

    def as_canon(self) -> dict:
        return {"name": self.name, "schema_digest": self.schema_digest,
                "version": self.version, "artifact_digest": self.artifact_digest,
                "execution_binding": self.execution_binding,
                "approval_mode": self.approval_mode,
                "credential_ref": self.credential_ref}


@dataclass(frozen=True)
class ExtensionBinding:
    """An extension is not a name, and its ORDER is semantic.

    Two defects this replaces (both found in review):
      1. extensions were digested as SORTED strings, so swapping two extensions
         left the digest unchanged even though composition order changes
         behaviour (Pydantic AI's outermost/innermost exists for this reason);
      2. a bare name does not pin an implementation, so changing extension code
         preserved the pin -- the same hole artifact_digest closes for tools.
    """
    name: str
    artifact_digest: str                 # IMMUTABLE code identity -- required
    config_digest: str = ""
    position: str = "outermost"          # outermost | innermost

    def __post_init__(self):
        if not self.artifact_digest:
            raise NonCanonical(
                f"extension {self.name!r}: artifact_digest is required. A name "
                f"alone does not pin an implementation.")
        if self.position not in ("outermost", "innermost"):
            raise NonCanonical(
                f"extension {self.name!r}: position must be 'outermost' or "
                f"'innermost', got {self.position!r}")

    def as_canon(self) -> dict:
        return {"name": self.name, "artifact_digest": self.artifact_digest,
                "config_digest": self.config_digest, "position": self.position}


@dataclass(frozen=True)
class AdapterContract:
    """The adapter digest must be DERIVED, not caller-supplied."""
    identity: str               # "acp:claude-code"
    protocol_version: str
    integration_mode: str       # Omnigent's taxonomy
    declared_capabilities: dict[str, Any] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        # kind= is load-bearing: without it this digest lives in the SAME domain
        # as a definition digest, so domain separation is claimed in the envelope
        # and not actually applied to the models that matter.
        return canonical_digest({
            "identity": self.identity,
            "protocol_version": self.protocol_version,
            "integration_mode": self.integration_mode,
            "declared_capabilities": self.declared_capabilities,
        }, kind="adapter_contract")


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    instructions: str
    tools: tuple[ToolBinding, ...] = ()
    extensions: tuple[ExtensionBinding, ...] = ()   # ORDERED (ADR-0012)
    version: int = 1                     # human-facing only, NEVER digested

    def __post_init__(self):
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise NonCanonical(f"duplicate tool names: {dupes}")
        enames = [e.name for e in self.extensions]
        if len(enames) != len(set(enames)):
            dupes = sorted({n for n in enames if enames.count(n) > 1})
            raise NonCanonical(f"duplicate extension names: {dupes}")

    @property
    def digest(self) -> str:
        return canonical_digest({
            "name": self.name,
            "instructions": self.instructions,
            # sorted by name: tool ORDER is not semantic, tool SET is
            "tools": [t.as_canon() for t in sorted(self.tools, key=lambda t: t.name)],
            # NOT sorted: extension order IS semantic, because extensions compose
            "extensions": [e.as_canon() for e in self.extensions],
        }, kind="agent_definition")


@dataclass(frozen=True)
class Pin:
    definition_digest: str
    adapter_identity: str
    adapter_digest: str
    checkpoint_schema_version: int       # OUR envelope format
    payload_schema_digest: str = ""      # the ADAPTER's own payload format

    def mismatch(self, other: "Pin") -> str | None:
        for f in ("definition_digest", "adapter_identity",
                  "adapter_digest", "checkpoint_schema_version",
                  "payload_schema_digest"):
            if getattr(self, f) != getattr(other, f):
                return f
        return None

    def as_row(self) -> dict:
        return {"definition_digest": self.definition_digest,
                "adapter_identity": self.adapter_identity,
                "adapter_digest": self.adapter_digest,
                "checkpoint_schema_version": self.checkpoint_schema_version,
                "payload_schema_digest": self.payload_schema_digest}

    @staticmethod
    def from_row(r: dict) -> "Pin":
        return Pin(r["definition_digest"], r["adapter_identity"],
                   r["adapter_digest"], int(r["checkpoint_schema_version"]),
                   r.get("payload_schema_digest", ""))


class ResumeRefused(Exception):
    """Base: resume cannot proceed. Subclasses carry DIFFERENT operator remedies."""


class IncompatibleCheckpoint(ResumeRefused):
    """The definition/adapter changed. Remedy: new run, or restore the prior version."""


class ArtifactMissing(ResumeRefused):
    """The pinned artifact is absent from the registry. Remedy: restore the artifact."""


class ArtifactCorrupted(ResumeRefused):
    """The artifact is present but does not hash to its own key. Remedy: re-fetch;
    this is a storage-integrity incident, not a version mismatch."""


class ConcurrentResume(ResumeRefused):
    """Another worker holds the resume lease. Remedy: none — this is correct."""
