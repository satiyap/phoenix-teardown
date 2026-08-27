#!/usr/bin/env python3
"""Generate the normative canonicalisation fixture.

Kept as a script, not a heredoc, so regeneration is reviewable and the reject
error strings are written deliberately rather than patched later — the previous
fixture ended up with TWO Infinity cases and no NaN because a bulk replace
rewrote both the value and its description.
"""
import json
from pathlib import Path

import pin

SURR_HI = chr(0xD800)
SURR_LO = chr(0xDCFF)

accept = [
    (1,  "effect_key", {}, "empty object"),
    (2,  "effect_key", {"a": 1}, "baseline"),
    (3,  "agent_definition", {"a": 1}, "domain separation: MUST DIFFER from #2"),
    (4,  "effect_key", {"s": "caf\u00e9"}, "NFC"),
    (5,  "effect_key", {"s": "cafe\u0301"}, "NFD: MUST EQUAL #4"),
    (6,  "effect_key", {"b": 2, "a": 1}, "key order normalised"),
    (7,  "effect_key", {"k": [1, 2, 3]}, "array order is significant"),
    (8,  "effect_key", {"n": 1.0}, "integral float: MUST EQUAL #9"),
    (9,  "effect_key", {"n": 1}, "integer"),
    (10, "effect_key", {"n": -0.0}, "negative zero: MUST EQUAL #11"),
    (11, "effect_key", {"n": 0}, "zero"),
    (12, "effect_key", {"n": 9007199254740991}, "largest accepted integer (2^53-1)"),
    (13, "effect_key", {"s": "4.5"}, "fractions travel as strings"),
    (14, "effect_key", {"\ue000": 1, "\U0001f600": 2},
     "NON-BMP SORT: UTF-8 byte order puts U+E000 before U+1F600; UTF-16 code-unit "
     "order (RFC 8785) would put U+1F600 first, because its surrogate pair starts "
     "0xD800. This profile mandates UTF-8 byte order."),
    (15, "effect_key", {"\U0001f600": 2, "\ue000": 1},
     "same pair, insertion order reversed: MUST EQUAL #14"),
    (16, "effect_key", {"a": {"z": 1, "\U0001f600": 2, "b": 3}},
     "nested object sorted by the same rule"),
    (17, "effect_key", {"s": "\u0000\u001f\"\\"},
     "control chars, quote and backslash escaped per RFC 8785 6.1"),
    (18, "effect_key", {"s": "\U0001f600"},
     "a VALID surrogate pair (non-BMP char) is accepted and emitted raw as UTF-8"),
    (19, "effect_key", {"a": [{"b": 1}, {"b": 2}]}, "array of objects keeps order"),
    (20, "effect_key", {"t": True, "f": False, "n": None},
     "literals: true/false/null lowercase, unquoted"),
    (21, "effect_key", {"\U0001f600": 1},
     "a valid surrogate pair as a KEY is accepted"),
]

reject = [
    ({"n": 1.5}, "non_integral_float",
     "non-integral float: Python emits 1.5, and formatting rules diverge across "
     "languages for other fractions. Encode fractions as strings."),
    ({"n": 9007199254740992}, "integer_out_of_range",
     "integer exceeds 2^53-1 and cannot round-trip through a JSON number in every "
     "language"),
    ({"n": 1e-7}, "non_integral_float",
     "non-integral float: Python emits 1e-07 where ECMAScript emits 1e-7"),
    ({"n": {"__nonfinite__": "nan"}}, "non_finite",
     "NaN has no canonical JSON form"),
    ({"n": {"__nonfinite__": "inf"}}, "non_finite",
     "Infinity has no canonical JSON form"),
    ({"caf\u00e9": 1, "cafe\u0301": 2}, "nfc_key_collision",
     "two distinct keys normalise to the same key under NFC; one would silently "
     "overwrite the other"),
    ({"s": {"__surrogate__": "high"}}, "lone_surrogate",
     "unpaired HIGH surrogate in a string value: Python raises UnicodeEncodeError "
     "while JSON.stringify emits an escape and digests it"),
    ({"s": {"__surrogate__": "low"}}, "lone_surrogate",
     "unpaired LOW surrogate in a string value"),
    ({"__surrogate_key__": "high"}, "lone_surrogate",
     "unpaired surrogate in a KEY"),
]


def subst(v):
    """Expand the symbolic placeholders strict JSON cannot express."""
    if isinstance(v, dict):
        if set(v) == {"__nonfinite__"}:
            return float("nan") if v["__nonfinite__"] == "nan" else float("inf")
        if set(v) == {"__surrogate__"}:
            return SURR_HI if v["__surrogate__"] == "high" else SURR_LO
        if set(v) == {"__surrogate_key__"}:
            return {SURR_HI if v["__surrogate_key__"] == "high" else SURR_LO: 1}
        return {k: subst(x) for k, x in v.items()}
    return v


def main():
    rows = []
    for n, kind, payload, note in accept:
        rows.append({"n": n, "kind": kind, "payload": payload,
                     "digest": pin.canonical_digest(payload, kind=kind), "note": note})

    rej = []
    for case, code, why in reject:
        expanded = subst(case)
        try:
            pin.canonical_digest(expanded, kind="effect_key")
            raise SystemExit(f"FIXTURE BUG: {code} case was ACCEPTED: {case}")
        except pin.NonCanonical:
            pass
        rej.append({"case": case, "kind": "effect_key", "code": code, "error": why})

    fx = {
        "profile": f"{pin.CANON_PROFILE}/v{pin.CANON_VERSION}",
        "sort_rule": ("object keys sorted by UTF-8 byte order — NOT UTF-16 code units, "
                      "NOT locale. This is deliberately not RFC 8785 ordering."),
        "symbolic_encoding": {
            "__nonfinite__": "nan | inf — a value strict JSON cannot express",
            "__surrogate__": "high | low — an unpaired UTF-16 surrogate in a string",
            "__surrogate_key__": "high | low — an unpaired surrogate used as a key",
        },
        "accept": rows,
        "reject": rej,
    }
    out = json.dumps(fx, indent=2, ensure_ascii=False) + "\n"
    json.loads(out)                      # must be strict JSON
    Path("canon_vectors.json").write_text(out)
    Path("../../spec/canon_vectors.json").write_text(out)

    def d(n): return next(r["digest"] for r in rows if r["n"] == n)
    checks = [("#4 == #5 NFC/NFD", d(4) == d(5)),
              ("#8 == #9 1.0 == 1", d(8) == d(9)),
              ("#10 == #11 -0.0 == 0", d(10) == d(11)),
              ("#14 == #15 insertion order", d(14) == d(15)),
              ("#2 != #3 domain separation", d(2) != d(3))]
    for label, ok in checks:
        print(f"  {'ok' if ok else 'FAIL'}  {label}")
        assert ok, label
    codes = sorted({r["code"] for r in rej})
    print(f"\n{len(rows)} accept, {len(rej)} reject; reject codes: {codes}")


if __name__ == "__main__":
    main()
