"""Run every harness mutation and report which gates each one breaks.

WHY THIS FILE EXISTS. `RESULT.md` listed five mutations and their failure counts
as PROSE. Review reproduced the first one and got 6 failures where the table
claimed 3. The table was written before gates 10 and 11 existed and never
re-measured, so it was stale rather than wrong-in-principle -- but an unreproducible
claim is not evidence (`VERIFICATION-RULES.md` rule 6). The table is now GENERATED.

RULE 7, AND WHY THIS FILE CHANGED AGAIN (2026-08-27, round 3). The previous
version mutated `harness.py` **in the live tree** and restored it in a `finally`.
That is exactly the ownership violation rule 7 names: for the duration of a
mutation run, a shared working tree contains a deliberately broken harness, so a
concurrent `make spike06` -- or an editor, or CI -- sees code nobody wrote. It now
copies the spike into a directory it creates under `tempfile.mkdtemp()`, mutates
the copy, and removes the whole directory afterwards. The live tree is never
opened for writing.

That also retires the stale-bytecode trap the old version had to work around: two
mutations only REORDER lines, leaving the file length unchanged, and CPython
invalidates `.pyc` files on `(mtime, size)` -- so a restore with a colliding mtime
could leave the interpreter running MUTATED bytecode. Every mutation now gets a
fresh directory with no `__pycache__` at all, so there is nothing to invalidate.

    ../../.venv/bin/python mutate.py            # table
    ../../.venv/bin/python mutate.py --check    # non-zero if any mutation is survivable
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = HERE.parent.parent / ".venv" / "bin" / "python"

# Everything a run of this spike needs. `copy_spike` is also used by `test_gate.py`
# for its own owned-copy work, so the list lives in one place.
SPIKE_FILES: tuple[str, ...] = (
    "harness.py", "test_gate.py", "conftest.py", "verify_pin.py", "mutate.py",
    "pinned_digests.json", "requirements.txt",
)


def copy_spike(dest: Path) -> Path:
    """Copy the spike into `dest`, which the CALLER owns. Never writes to HERE."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name in SPIKE_FILES:
        shutil.copy2(HERE / name, dest / name)
    return dest


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
        "accept any policy verdict",
        "OQ-065: an unknown verdict runs the body (fail open)",
        "            if verdict not in POLICY_VERDICTS:",
        "            if False:",
    ),
    (
        "strand an unserialisable result at claimed",
        "OQ-066: the effect ran and the row never gets a verdict",
        "            self.ledger.settle(call.tool_call_id, \"indeterminate\", None,\n"
        "                               owner=owner, token=token,\n"
        "                               error_code=\"result_unserialisable\")",
        "            pass  # result settle removed",
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
        "            toolset = ExternalToolset(self._defs) if self._defs else None\n"
        "            self.__agent = Agent(self.__model,\n"
        "                                 output_type=[str, DeferredToolRequests],\n"
        "                                 toolsets=[toolset] if toolset else [])",
        "            from pydantic_ai.toolsets.function import FunctionToolset\n"
        "            fts = FunctionToolset()\n"
        "            for _n, _impl in self._dispatch.items():\n"
        "                fts.add_function(_impl, name=_n)\n"
        "            self.__agent = Agent(self.__model,\n"
        "                                 output_type=[str, DeferredToolRequests],\n"
        "                                 toolsets=[fts])",
    ),
    (
        "expose the Agent",
        "THE STRUCTURAL REFUSAL: a caller can override(native_tools=...)",
        "    @staticmethod\n"
        "    def __turn(result: Any) -> Turn:",
        "    def build_agent(self) -> Agent:\n"
        "        return self.__build()\n"
        "\n"
        "    @staticmethod\n"
        "    def __turn(result: Any) -> Turn:",
    ),
    (
        "accept caller-supplied native_tools",
        "vendor-hosted tools reach the model unledgered",
        '        _reject_sdk_surface("register()", sdk_surface)',
        "        pass  # surface check removed",
    ),
    (
        "drop the claim before dispatch",
        "an effect is dispatched without being claimed",
        "        self.ledger.claim(call.tool_call_id, owner, token, lease=lease,\n"
        "                          fence=lease.fence_token if lease else None,\n"
        "                          approved=approved)",
        "        pass  # claim removed",
    ),
    (
        "drop the run-lease predicate",
        "a worker whose run was reclaimed can still claim and dispatch",
        "        if lease is None:\n"
        "            raise LedgerRefused(\n"
        '                "claim requires an unexpired run lease "\n'
        '                "(spec/02-consistency.md:246, predicate (b))")\n'
        "        now = self.clock()\n"
        "        if not lease.authorises(row.run_id, owner, fence, now):",
        "        now = self.clock()\n"
        "        if False:",
    ),
    (
        "drop the settle fence",
        "a stale worker can overwrite the claim holder's verdict",
        '        if row.status != "claimed":',
        "        if False:",
    ),
    (
        "settle indeterminate as intended",
        "a crashed effect looks like one that never started",
        '            self.ledger.settle(call.tool_call_id, "indeterminate", None,\n'
        "                               owner=owner, token=token,\n"
        '                               error_code="dispatch_lost_contact")',
        "            pass  # verdict dropped",
    ),
    (
        "bind arguments inside the dispatch try",
        "a call that never dispatched is reported as uncertain",
        "        try:\n"
        "            bound = inspect.signature(impl).bind(**args)\n"
        "        except Exception:\n"
        '            self.ledger.settle(call.tool_call_id, "failed", None,\n'
        "                               owner=owner, token=token,\n"
        '                               error_code="arguments_unbindable")\n'
        "            raise\n"
        "\n"
        "        # --- the dispatch itself. After this line the outcome is unknowable. ---\n"
        "        try:\n"
        "            result = impl(*bound.args, **bound.kwargs)\n",
        # the defect, restored exactly: binding happens AT the call, inside the try
        # that settles `indeterminate`
        "        # --- the dispatch itself. After this line the outcome is unknowable. ---\n"
        "        try:\n"
        "            result = impl(**args)\n",
    ),
    (
        "drop the intent conflict guard",
        "the ledger has no primary key: one call, two rows",
        "        if any(r.tool_call_id == row.tool_call_id for r in self._rows):\n"
        "            return  # ON CONFLICT (tenant_id, idempotency_key) DO NOTHING (spec/02:202)\n",
        "",
    ),
    (
        "drop the fence-token comparison",
        "a worker holding a superseded fence token can still claim",
        "                and fence is not None and self.fence_token == fence\n",
        "",
    ),
    (
        "drop the intent/dispatch identity check",
        "a body runs against a ledger row naming a DIFFERENT tool and arguments",
        "        if row.tool_name != call.tool_name or row.args_json != args_json_of(call.args):\n"
        "            raise LedgerRefused(\n"
        '                f"the ledger row for {call.tool_call_id!r} describes "\n'
        '                f"{row.tool_name!r}{row.args_json}, not {call.tool_name!r}"\n'
        '                f"{args_json_of(call.args)}; a differing request_digest is a "\n'
        '                "DIFFERENT effect, not this one (spec/01-schema.md:403)")\n',
        "",
    ),
    (
        "drop the dispatch run check",
        "one run dispatches and settles an effect recorded against another run",
        "        if row.run_id != run_id:\n"
        "            raise LedgerRefused(\n"
        '                f"{call.tool_call_id!r} is an effect of run {row.run_id!r}, not "\n'
        '                f"{run_id!r}; the run is part of the key "\n'
        '                "(spec/01-schema.md:372, spec/01-schema.md:403)")\n',
        "",
    ),
    (
        "make the intent guard the SECONDARY unique constraint",
        "one idempotency_key spans two runs: two rows, the second unreachable",
        "        if any(r.tool_call_id == row.tool_call_id for r in self._rows):\n"
        "            return  # ON CONFLICT (tenant_id, idempotency_key) DO NOTHING (spec/02:202)\n",
        "        if any(r.tool_call_id == row.tool_call_id and r.run_id == row.run_id\n"
        "               for r in self._rows):\n"
        "            return  # the round-4 defect, restored\n",
    ),
    (
        "allow a duplicate registration",
        "a second register() silently replaces the body a ledger row names",
        "        if name in self._dispatch:\n"
        "            raise UninterceptableTool(\n"
        '                f"{name!r} is already registered; a second registration would "\n'
        '                "silently replace the body a ledger row names")\n',
        "",
    ),
    (
        "mint the run lease on the harness clock",
        "the lease is minted on one clock and judged on another (spec/02:249)",
        "                             expires_at=self.ledger.clock() + RUN_LEASE_SECONDS)",
        "                             expires_at=self.clock() + RUN_LEASE_SECONDS)",
    ),
    (
        "call a raise after dispatch 'failed'",
        "an effect of unknown outcome is reported as one that provably did not happen",
        '            self.ledger.settle(call.tool_call_id, "indeterminate", None,\n'
        "                               owner=owner, token=token,\n"
        '                               error_code="dispatch_lost_contact")',
        '            self.ledger.settle(call.tool_call_id, "failed", None,\n'
        "                               owner=owner, token=token,\n"
        '                               error_code="dispatch_lost_contact")',
    ),
]


def _run(work: Path) -> tuple[int, int, list[str]]:
    r = subprocess.run([str(PY), "-m", "pytest", "test_gate.py", "-q", "--no-header"],
                       cwd=str(work), capture_output=True, text=True)
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
    original = (HERE / "harness.py").read_text()

    root = Path(tempfile.mkdtemp(prefix="spike06-mutations-"))
    try:
        baseline_failed, baseline_passed, _ = _run(copy_spike(root / "baseline"))
        print(f"baseline: {baseline_passed} passed, {baseline_failed} failed "
              f"(in {root}, NOT the live tree)")
        if baseline_failed:
            print("BASELINE IS NOT CLEAN -- fix that before trusting any mutation")
            return 1

        rows, survivable = [], []
        for i, (label, removes, old, new) in enumerate(MUTATIONS):
            if old not in original:
                rows.append((label, removes, "PATTERN MISS", []))
                survivable.append(label)
                continue
            work = copy_spike(root / f"m{i:02d}")
            (work / "harness.py").write_text(original.replace(old, new, 1))
            failed, _passed, names = _run(work)
            rows.append((label, removes, f"{failed} failed", names))
            if failed == 0:
                survivable.append(label)

        width = max(len(r[0]) for r in rows)
        print()
        print(f"| {'Mutation'.ljust(width)} | Removes | Gates broken |")
        print(f"|{'-' * (width + 2)}|---|---|")
        for label, removes, result, names in rows:
            short = ", ".join(n.replace("test_", "") for n in names) or "-"
            print(f"| {label.ljust(width)} | {removes} | **{result}** — {short} |")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    assert (HERE / "harness.py").read_text() == original, \
        "the live harness changed during a mutation run -- rule 7 violated"
    print("\nthe live tree is byte-identical to where it started")
    if survivable:
        print("\nSURVIVABLE MUTATIONS (no gate caught them):")
        for s in survivable:
            print("  ", s)
        return 1 if check else 0
    print("\nevery mutation is caught by at least one gate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
