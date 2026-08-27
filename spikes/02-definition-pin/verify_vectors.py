#!/usr/bin/env python3
"""Verify the fixture with the PYTHON canonicaliser and emit its digests.

`make spec` needs Python's answers as data so it can compare them with the JS
oracle's directly, not merely check each against the file.

Exit 0 and print {"digests": {...}} on success; exit 1 with reasons otherwise.
"""
import json
import sys
from pathlib import Path

import pin


def subst(v):
    if isinstance(v, dict):
        if set(v) == {"__nonfinite__"}:
            return float("nan") if v["__nonfinite__"] == "nan" else float("inf")
        if set(v) == {"__surrogate__"}:
            return chr(0xD800) if v["__surrogate__"] == "high" else chr(0xDCFF)
        if set(v) == {"__surrogate_key__"}:
            return {chr(0xD800) if v["__surrogate_key__"] == "high" else chr(0xDCFF): 1}
        return {k: subst(x) for k, x in v.items()}
    return v


def main() -> int:
    fx = json.loads(Path(sys.argv[1]).read_text())
    problems, digests = [], {}

    if fx["profile"] != f"{pin.CANON_PROFILE}/v{pin.CANON_VERSION}":
        problems.append(f"profile drift: fixture {fx['profile']} != "
                        f"{pin.CANON_PROFILE}/v{pin.CANON_VERSION}")

    for row in fx["accept"]:
        try:
            got = pin.canonical_digest(row["payload"], kind=row["kind"])
        except pin.NonCanonical as exc:
            problems.append(f"#{row['n']} unexpectedly REJECTED: {exc}")
            continue
        digests[str(row["n"])] = got
        if got != row["digest"]:
            problems.append(f"#{row['n']} digest drift: fixture {row['digest'][:12]} "
                            f"!= python {got[:12]}")

    for row in fx["reject"]:
        try:
            pin.canonical_digest(subst(row["case"]), kind=row["kind"])
            problems.append(f"reject case `{row.get('code')}` was ACCEPTED: "
                            f"{json.dumps(row['case'])}")
        except pin.NonCanonical:
            pass                      # the ONLY acceptable outcome
        except Exception as exc:      # noqa: BLE001
            # A raw UnicodeEncodeError (or similar) means the value was refused by
            # the LANGUAGE rather than by the profile. That is not good enough: the
            # message is unactionable and another language may not refuse at all,
            # which is exactly how lone surrogates diverged.
            problems.append(
                f"reject case `{row.get('code')}` raised {type(exc).__name__} instead "
                f"of NonCanonical: the profile must reject it explicitly, not rely on "
                f"the language failing to encode it")

    if problems:
        for p in problems:
            print(p)
        return 1
    print(json.dumps({"digests": digests}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
