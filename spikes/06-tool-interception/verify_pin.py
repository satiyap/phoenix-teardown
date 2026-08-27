"""Verify the installed SDK is byte-for-byte the code these gates were written against.

WHY THIS FILE EXISTS. `RESULT.md` claimed the pin was "by digest, not by
declaration" while nothing stored or checked a digest. Review disproved the claim
in one move: edit `toolsets/external.py`, run the suite, watch 18/18 still pass.
A pin that is not asserted is a comment.

WHY IT WAS REVISED (2026-08-27, round 3). The pin then covered FIVE files, and
review disproved *that* the same way: gate 6 decides which tools may be admitted
by reading `pydantic_ai.native_tools`, and `native_tools/__init__.py` was not
pinned — so the module that governs admission could be edited with every gate
still green. The pin now covers every SDK file whose bytes any assertion in this
spike depends on, and `test_gate.py` derives the *required* set from the import
statements of `harness.py` and `test_gate.py` (`sdk_modules_imported_by`) rather
than from a second hand-kept list, so the pin and its coverage check cannot drift
together.

`requirements.txt` pins `pydantic-ai-slim==2.35.0`, but that string is only a
label -- the source tree uses `uv-dynamic-versioning` (`pyproject.toml:5-6`) and
the read clone has no git tags, so it cannot state its own version. These digests
are the real assertion.

Run standalone, or let `conftest.py` fail the whole session:

    python verify_pin.py            # check
    python verify_pin.py --record   # recompute and rewrite pinned_digests.json
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIN = HERE / "pinned_digests.json"

# The behaviour-bearing set, stated so `--record` has something to walk and so a
# deletion from `pinned_digests.json` is a failure rather than a silent narrowing.
# `test_gate.py` checks the pin covers this AND everything the spike imports.
REQUIRED_PINS: tuple[str, ...] = (
    # the run surface and the tool-execution pipeline
    "__init__.py",
    "agent/__init__.py",
    "_tool_execution.py",
    "_deferred.py",
    "tools.py",
    "messages.py",
    "exceptions.py",
    # the toolset machinery the boundary is built from
    "toolsets/__init__.py",
    "toolsets/abstract.py",
    "toolsets/external.py",
    "toolsets/approval_required.py",
    "toolsets/function.py",
    # NATIVE-TOOL ADMISSION. Unpinned in round 2; the reason this file changed.
    "native_tools/__init__.py",
    "native_tools/_tool_search.py",
    # the two models the gates drive, one of which SUPPORTS native tools
    "models/function.py",
    "models/test.py",
)


class PinMismatch(Exception):
    """The installed SDK is not the code the gates were written against."""


def sdk_root() -> Path:
    import pydantic_ai
    return Path(os.path.dirname(pydantic_ai.__file__))


def pinned() -> dict[str, str]:
    return dict(json.loads(PIN.read_text())["files"])


def digest(rel: str) -> str:
    return hashlib.sha256((sdk_root() / rel).read_bytes()).hexdigest()


def module_to_relpath(dotted: str) -> str | None:
    """`pydantic_ai.toolsets.external` -> `toolsets/external.py`.

    Returns None for a name that is not a module of the installed SDK (e.g. a
    symbol imported from a package `__init__`).
    """
    if dotted != "pydantic_ai" and not dotted.startswith("pydantic_ai."):
        return None
    tail = dotted[len("pydantic_ai"):].lstrip(".")
    root = sdk_root()
    for candidate in ([f"{tail.replace('.', '/')}.py",
                       f"{tail.replace('.', '/')}/__init__.py"] if tail
                      else ["__init__.py"]):
        if (root / candidate).is_file():
            return candidate
    return None


def sdk_modules_imported_by(paths) -> set[str]:
    """Every SDK file imported from by the given source files, read with `ast`.

    This is the independent oracle for the pin's COVERAGE (rule 5): it is derived
    from the spike's own import statements, so adding a dependency on a new SDK
    module without pinning it is a gate failure rather than a silent gap.
    """
    found: set[str] = set()
    for path in paths:
        tree = ast.parse(Path(path).read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.append(node.module)
            elif isinstance(node, ast.Import):
                names.extend(a.name for a in node.names)
            for dotted in names:
                rel = module_to_relpath(dotted)
                if rel:
                    found.add(rel)
    return found


def check(spec: dict | None = None) -> list[str]:
    """Return a list of problems; empty means the pin holds.

    `spec` is injectable so the gate can plant a wrong digest and prove this
    function objects (rule 4) without ever writing to the live pin file (rule 7).
    """
    injected = spec is not None
    if spec is None:
        spec = json.loads(PIN.read_text())
    files = spec["files"]
    root = sdk_root()
    problems: list[str] = []
    if not files:
        return ["the pin lists no files"]
    for rel, want in files.items():
        path = root / rel
        if not path.exists():
            problems.append(f"{rel}: MISSING from the installed SDK")
            continue
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != want:
            problems.append(f"{rel}: expected {want[:16]}… got {got[:16]}…")
    if not injected:
        # Coverage is a property of the REAL pin file. An injected spec is a
        # negative control probing one digest, so holding it to the full required
        # set would drown the one problem it exists to produce.
        missing = [rel for rel in REQUIRED_PINS if rel not in files]
        if missing:
            problems.append(f"the pin no longer covers required files: {missing}")
    return problems


def require() -> None:
    problems = check()
    if problems:
        raise PinMismatch(
            "the installed Pydantic AI is not the code spike 06 verified:\n  "
            + "\n  ".join(problems)
            + "\n\nEvery gate in this spike asserts behaviour of THOSE bytes. Re-run the "
              "spike against the pinned version, or re-verify and update "
              "pinned_digests.json deliberately (verify_pin.py --record)."
        )


def record() -> None:
    """Rewrite the pin from the installed SDK. A DELIBERATE act, never automatic."""
    spec = json.loads(PIN.read_text())
    spec["files"] = {rel: digest(rel) for rel in REQUIRED_PINS}
    PIN.write_text(json.dumps(spec, indent=2) + "\n")
    print(f"recorded {len(spec['files'])} digests from {sdk_root()}")


if __name__ == "__main__":
    if "--record" in sys.argv:
        record()
        sys.exit(0)
    probs = check()
    if probs:
        print("PIN MISMATCH")
        for p in probs:
            print(" ", p)
        sys.exit(1)
    print(f"pin holds: {len(pinned())} files byte-identical to the verified SDK")
