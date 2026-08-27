"""Verify the installed SDK is byte-for-byte the code these gates were written against.

WHY THIS FILE EXISTS. `RESULT.md` claimed the pin was "by digest, not by
declaration" while nothing stored or checked a digest. Review disproved the claim
in one move: edit `toolsets/external.py`, run the suite, watch 18/18 still pass.
A pin that is not asserted is a comment.

`requirements.txt` pins `pydantic-ai-slim==2.35.0`, but that string is only a
label -- the source tree uses `uv-dynamic-versioning` (`pyproject.toml:5-6`) and
the read clone has no git tags, so it cannot state its own version. These five
digests are the real assertion.

Run standalone, or let `conftest.py` fail the whole session.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIN = HERE / "pinned_digests.json"


class PinMismatch(Exception):
    """The installed SDK is not the code the gates were written against."""


def sdk_root() -> Path:
    import pydantic_ai
    return Path(os.path.dirname(pydantic_ai.__file__))


def check() -> list[str]:
    """Return a list of problems; empty means the pin holds."""
    spec = json.loads(PIN.read_text())
    root = sdk_root()
    problems: list[str] = []
    for rel, want in spec["files"].items():
        path = root / rel
        if not path.exists():
            problems.append(f"{rel}: MISSING from the installed SDK")
            continue
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != want:
            problems.append(f"{rel}: expected {want[:16]}… got {got[:16]}…")
    if not spec["files"]:
        problems.append("pinned_digests.json lists no files")
    return problems


def require() -> None:
    problems = check()
    if problems:
        raise PinMismatch(
            "the installed Pydantic AI is not the code spike 06 verified:\n  "
            + "\n  ".join(problems)
            + "\n\nEvery gate in this spike asserts behaviour of THOSE bytes. Re-run the "
              "spike against the pinned version, or re-verify and update "
              "pinned_digests.json deliberately."
        )


if __name__ == "__main__":
    probs = check()
    if probs:
        print("PIN MISMATCH")
        for p in probs:
            print(" ", p)
        sys.exit(1)
    n = len(json.loads(PIN.read_text())["files"])
    print(f"pin holds: {n} files byte-identical to the verified SDK")
