"""Run every harness mutation and report which gates each one breaks.

WHY THIS FILE EXISTS. `RESULT.md` listed five mutations and their failure counts
as PROSE. Review reproduced the first one and got 6 failures where the table
claimed 3. The table was written before gates 10 and 11 existed and never
re-measured, so it was stale rather than wrong-in-principle -- but an unreproducible
claim is not evidence (`VERIFICATION-RULES.md` rule 6). The table is now GENERATED.

A STALE-BYTECODE TRAP, worth naming because it cost real time. Two of these
mutations only REORDER lines, so the file's byte length is unchanged. Restoring it
with `cp` can reproduce an mtime that collides with the cached entry, and CPython
invalidates `.pyc` files on `(mtime, size)` -- so the interpreter silently keeps
running the MUTATED bytecode. That is how a clean tree reported 6 failures. Every
run here deletes `__pycache__` first.

    ../../.venv/bin/python mutate.py            # table
    ../../.venv/bin/python mutate.py --check    # non-zero if any mutation is survivable
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "harness.py"
PY = HERE.parent.parent / ".venv" / "bin" / "python"

# (label, what it removes, old, new)
MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "dispatch before ledgering",
        "intent no longer precedes the effect",
        "            self.intend(run_id, call)\n"
        "            out[call.tool_call_id] = self.dispatch(run_id, call)",
        "            out[call.tool_call_id] = self.dispatch(run_id, call)\n"
        "            self.intend(run_id, call)",
    ),
    (
        "ignore the policy verdict",
        "a denied call executes anyway",
        '        if verdict == "deny":',
        "        if False:",
    ),
    (
        "allow uninterceptable registration",
        "spec/08 row 30c is unenforced",
        "        if not self._can_route(name, sdk_executable=sdk_executable):",
        "        if False:",
    ),
    (
        "route tools through FunctionToolset",
        "THE REAL BYPASS: the SDK gets an executable body",
        "        toolset = ExternalToolset(self._defs) if self._defs else None\n"
        "        return Agent(model,\n"
        "                     output_type=[str, DeferredToolRequests],\n"
        "                     toolsets=[toolset] if toolset else [])",
        "        from pydantic_ai.toolsets.function import FunctionToolset\n"
        "        fts = FunctionToolset()\n"
        "        for _n, _impl in self._dispatch.items():\n"
        "            fts.add_function(_impl, name=_n)\n"
        "        return Agent(model,\n"
        "                     output_type=[str, DeferredToolRequests],\n"
        "                     toolsets=[fts])",
    ),
    (
        "drop the claim before dispatch",
        "an effect is dispatched without being claimed",
        "        self.ledger.claim(call.tool_call_id, owner, token)",
        "        pass  # claim removed",
    ),
    (
        "settle indeterminate as intended",
        "a crashed effect looks like one that never started",
        '            self.ledger.settle(call.tool_call_id, "indeterminate", None, token=token)',
        "            pass  # verdict dropped",
    ),
]


def _clean_pycache() -> None:
    shutil.rmtree(HERE / "__pycache__", ignore_errors=True)


def _run() -> tuple[int, int, list[str]]:
    _clean_pycache()
    r = subprocess.run([str(PY), "-m", "pytest", "test_gate.py", "-q", "--no-header"],
                       cwd=str(HERE), capture_output=True, text=True)
    out = r.stdout
    m = re.search(r"(\d+) failed, (\d+) passed", out)
    if m:
        failed, passed = int(m.group(1)), int(m.group(2))
    else:
        m2 = re.search(r"(\d+) passed", out)
        failed, passed = 0, int(m2.group(1)) if m2 else -1
    names = sorted({re.sub(r"^FAILED test_gate\.py::", "", ln).split(" ")[0]
                    for ln in out.splitlines() if ln.startswith("FAILED")})
    return failed, passed, names


def main() -> int:
    check = "--check" in sys.argv
    original = HARNESS.read_text()

    baseline_failed, baseline_passed, _ = _run()
    print(f"baseline: {baseline_passed} passed, {baseline_failed} failed")
    if baseline_failed:
        print("BASELINE IS NOT CLEAN -- fix that before trusting any mutation")
        return 1

    rows, survivable = [], []
    try:
        for label, removes, old, new in MUTATIONS:
            if old not in original:
                rows.append((label, removes, "PATTERN MISS", []))
                survivable.append(label)
                continue
            HARNESS.write_text(original.replace(old, new, 1))
            failed, _passed, names = _run()
            rows.append((label, removes, f"{failed} failed", names))
            if failed == 0:
                survivable.append(label)
            HARNESS.write_text(original)
    finally:
        HARNESS.write_text(original)
        _clean_pycache()

    width = max(len(r[0]) for r in rows)
    print()
    print(f"| {'Mutation'.ljust(width)} | Removes | Gates broken |")
    print(f"|{'-' * (width + 2)}|---|---|")
    for label, removes, result, names in rows:
        short = ", ".join(n.replace("test_", "") for n in names) or "-"
        print(f"| {label.ljust(width)} | {removes} | **{result}** — {short} |")

    final_failed, final_passed, _ = _run()
    print(f"\nrestored: {final_passed} passed, {final_failed} failed")
    if survivable:
        print("\nSURVIVABLE MUTATIONS (no gate caught them):")
        for s in survivable:
            print("  ", s)
        return 1 if check else 0
    print("\nevery mutation is caught by at least one gate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
