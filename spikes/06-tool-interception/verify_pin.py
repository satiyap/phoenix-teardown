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

WHY IT WAS REVISED AGAIN (2026-08-28, round 4). Round 3's sixteen files omitted
`models/__init__.py`, which is where native-tool ADMISSION is decided
(`ModelRequestParameters.native_tools` at `:179`; `resolve_request_tools` at
`:1812-1930`, whose `:1849` filter is what rejects an unsupported native tool), and
`profiles/__init__.py`, the source of `supported_native_tools`. Review reproduced
the round-2 defect verbatim in a scratch copy of the SDK: replace the admission
filter so no model can reject a native tool, and this file still printed "pin holds:
16 files" with all 47 gates green. Both are now pinned. The coverage oracle was also
blind by construction -- it never added the ancestor package `__init__.py` files an
import executes, so it returned a strict SUBSET of the hand-written list. It now
adds them, and `frontier()` records the one-level transitive edge of the pin so a
new import out of a pinned file is a decision rather than a silent widening.

WHY IT WAS REVISED A THIRD TIME (2026-08-28, round 5). Round 4's nineteen files
omitted `tool_manager.py`, and the reason is the same shape one level further out:
`_tool_execution.py` does not run tool bodies. It imports `ToolManager`
(`_tool_execution.py:15`) and delegates (`:671`, `:958`); the body is invoked at
`tool_manager.py:1008` -- `await self.toolset.call_tool(...)` inside `_raw_execute`
(`:994`) -- which is where `ExternalToolset.call_tool`'s unconditional
`NotImplementedError` (`toolsets/external.py:46`) either propagates or does not.
It sat in `_coverage_frontier`, whose justification called the frontier modules ones
"none of which any assertion here touches"; in a scratch SDK copy, wrapping that call
in `except NotImplementedError: tool_result = 'SILENTLY FABRICATED BY THE SDK'` turned
the fail-closed refusal fail-OPEN inside the pipeline and this file still printed
"pin holds: 19 files" with all 53 gates green. `capabilities/_tool_search.py` and
`toolsets/_tool_search.py` joined the pin at the same time: `Agent.__init__`
auto-injects `ToolSearch`, which ALWAYS wraps the boundary toolset in
`ToolSearchToolset`, so gate 13c's claim about what the agent runs is a claim about
those bytes.

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
    # ADDED 2026-08-28 (round 4). Native-tool ADMISSION is decided here, not in
    # `native_tools/`: `models/__init__.py:179` defines
    # `ModelRequestParameters.native_tools` -- the exact object gate 13's recorder
    # asserts is empty -- and `resolve_request_tools` (`models/__init__.py:1812-1930`)
    # is the function that filters native tools against `supported_native_tools` at
    # `:1849`, and raises `UserError('Native tool(s) ... not supported by this
    # model')` at `:1861-1862` (citation corrected 2026-08-28: `:1849` was cited for
    # the raise; `:1849` is the `supported_natives` filter line).
    # Round 3's pin covered sixteen files and omitted both of these, so the admission
    # filter could be replaced with `supported_natives = list(params.native_tools)`
    # and `verify_pin.py` still printed "pin holds" with all 47 gates green.
    "models/__init__.py",
    "profiles/__init__.py",   # the source of `supported_native_tools`
    # `capabilities=` is the THIRD SDK surface that delivers tools (round 4): it
    # carries both native tools and executable LOCAL bodies. Gate 13 asserts the
    # harness refuses it, so these bytes are load-bearing too.
    "capabilities/__init__.py",
    # ADDED 2026-08-28 (round 5). `_tool_execution.py` ORCHESTRATES tool execution;
    # it does not invoke the body. It imports `ToolManager` (`_tool_execution.py:15`)
    # and delegates at `:671`/`:958`, and the actual invocation is
    # `tool_manager.py:1008` -- `tool_result = await self.toolset.call_tool(...)`
    # inside `_raw_execute` (`tool_manager.py:994`). That is where
    # `ExternalToolset.call_tool`'s unconditional `NotImplementedError`
    # (`toolsets/external.py:46`, this spike's first cited claim) either propagates or
    # does not. It was in `_coverage_frontier`, justified as a module "no assertion
    # here touches" -- false for this one: in a scratch SDK copy, wrapping that call
    # in `except NotImplementedError: tool_result = 'SILENTLY FABRICATED BY THE SDK'`
    # turned the fail-closed refusal fail-OPEN inside the pipeline, and this file
    # still printed "pin holds: 19 files" with all 53 gates green.
    "tool_manager.py",
    # ADDED 2026-08-28 (round 5). `Agent.__init__` AUTO-INJECTS `ToolSearch`
    # (`agent/__init__.py:630`, `:3955-3958`), which ALWAYS wraps the harness's
    # `ExternalToolset` in `ToolSearchToolset` (`capabilities/_tool_search.py:191-196`)
    # whose `call_tool` has a LOCAL branch (`toolsets/_tool_search.py:435-437`). Gate
    # 13's `..._the_agent_runs_only_the_delegating_wrapper` asserts the wrapping and
    # the fail-closed behaviour, so these bytes are load-bearing.
    "capabilities/_tool_search.py",
    "toolsets/_tool_search.py",
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


def ancestor_inits(rel: str) -> set[str]:
    """`models/function.py` -> {`models/__init__.py`, `__init__.py`}.

    ADDED 2026-08-28 (round 4). Importing `pydantic_ai.models.function` EXECUTES
    `pydantic_ai/__init__.py` and `pydantic_ai/models/__init__.py` first; those bytes
    are as load-bearing as the leaf module's. Omitting them is why the round-3 oracle
    could not see the `models/__init__.py` hole.
    """
    out: set[str] = set()
    parts = rel.split("/")[:-1]
    while True:
        candidate = "/".join([*parts, "__init__.py"])
        if candidate != rel and (sdk_root() / candidate).is_file():
            out.add(candidate)
        if not parts:
            return out
        parts.pop()


def sdk_modules_imported_by(paths) -> set[str]:
    """Every SDK file imported from by the given source files, read with `ast`.

    This is the independent oracle for the pin's COVERAGE (rule 5): it is derived
    from the spike's own import statements, so adding a dependency on a new SDK
    module without pinning it is a gate failure rather than a silent gap.

    AMENDED 2026-08-28 (round 4). As written in round 3 this mapped each dotted name
    to a SINGLE relpath and never added the ancestor package `__init__.py` files
    Python must execute to perform the import, so
    `from pydantic_ai.models.function import FunctionModel` yielded only
    `models/function.py`. Measured at that commit it returned exactly ten modules --
    a strict SUBSET of the sixteen hand-written `REQUIRED_PINS` -- so it asserted
    nothing the hand-kept list did not already assert, and `'models/__init__.py' in
    imported` was False. It could not have caught the admission-path hole. It now
    adds every ancestor package `__init__.py`, which makes it catch that hole on its
    own.
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
                    found |= ancestor_inits(rel)
    return found


def sdk_imports_of(rel: str) -> set[str]:
    """Every SDK module the PINNED file `rel` imports from, relative imports included.

    `sdk_modules_imported_by` reads the spike's own sources, which use absolute
    imports only. Inside the SDK almost every import is relative, so resolving
    `node.level` is required or the walk below sees nothing.
    """
    pkg = rel.split("/")[:-1]
    found: set[str] = set()
    tree = ast.parse((sdk_root() / rel).read_text())
    for node in ast.walk(tree):
        dotted_names: list[str] = []
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = ["pydantic_ai", *pkg][: len(pkg) + 1 - (node.level - 1)]
                if node.module:
                    dotted_names.append(".".join([*base, node.module]))
                else:
                    dotted_names += [".".join([*base, a.name]) for a in node.names]
            elif node.module:
                dotted_names.append(node.module)
        elif isinstance(node, ast.Import):
            dotted_names += [a.name for a in node.names]
        for dotted in dotted_names:
            got = module_to_relpath(dotted)
            if got:
                found.add(got)
                found |= ancestor_inits(got)
    return found


def frontier(files) -> list[str]:
    """The one-level transitive frontier: SDK modules the pinned files import and
    that are NOT themselves pinned.

    ADDED 2026-08-28 (round 4). The pin covers the files whose bytes an assertion in
    this spike depends on DIRECTLY. It deliberately does not cover the transitive
    closure, which at this SDK is effectively the whole distribution (284 modules,
    including every vendor model adapter). Leaving that unstated is what let the
    `models/__init__.py` hole sit unnoticed, so the frontier is now RECORDED in
    `pinned_digests.json` and compared on every check: a pinned file growing a new
    import into a module nobody has looked at is a deliberate decision, not a silent
    widening.
    """
    reached: set[str] = set()
    for rel in files:
        reached |= sdk_imports_of(rel)
    return sorted(reached - set(files))


def frontier_problems(recorded, files) -> list[str]:
    """Compare the recorded frontier with the one computed from the installed SDK.

    Injectable so a gate can plant a wrong frontier and prove this objects (rule 4)
    without writing to the live pin file (rule 7).
    """
    got = frontier(files)
    if recorded is None:
        return ["the pin records no _coverage_frontier"]
    added = sorted(set(got) - set(recorded))
    gone = sorted(set(recorded) - set(got))
    problems = []
    if added:
        problems.append(
            "pinned files now import SDK modules outside the recorded frontier "
            f"(neither pinned nor reviewed): {added}")
    if gone:
        problems.append(
            f"the recorded frontier lists modules no pinned file imports: {gone}")
    return problems


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
        problems += frontier_problems(spec.get("_coverage_frontier"), sorted(files))
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
    spec["files"] = {rel: digest(rel) for rel in sorted(REQUIRED_PINS)}
    spec["_coverage_frontier"] = frontier(sorted(REQUIRED_PINS))
    PIN.write_text(json.dumps(spec, indent=2) + "\n")
    print(f"recorded {len(spec['files'])} digests and a "
          f"{len(spec['_coverage_frontier'])}-module frontier from {sdk_root()}")


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
