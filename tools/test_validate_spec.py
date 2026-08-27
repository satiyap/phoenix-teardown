#!/usr/bin/env python3
"""Negative controls for validate_spec.py itself.

The superseded-claims gate passed on commit 59da08b while five documents
contradicted the change it was supposed to police. A gate with no test of its own
is a gate nobody has checked, so each control below injects a defect into a TEMP
COPY of the repo and asserts the tool fails and names the file.

Run: ../.venv/bin/python tools/test_validate_spec.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(label: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(label)
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{detail}]" if detail else ""))


def run_in(tmp: Path) -> tuple[bool, list[str]]:
    """Run the validator against a copied tree and isolate the superseded check.

    A partial copy legitimately fails unrelated checks (no node, no Postgres, no
    spike venv), so the controls must read the SUPERSEDED result specifically
    rather than the process exit code. The first version of this test asserted on
    the whole run and therefore measured nothing -- caught by its own control 0.
    """
    res = subprocess.run([sys.executable, str(tmp / "tools" / "validate_spec.py")],
                         capture_output=True, text=True, cwd=str(tmp),
                         env={"PATH": "/usr/bin:/bin", "SPEC_ALLOW_UNVERIFIED": "1"})
    out = res.stdout + res.stderr
    hits = [ln.strip()[2:].strip() for ln in out.splitlines()
            if ln.strip().startswith("x ") and "superseded on" in ln]
    ok = any("superseded claims" in ln and " ok" in ln for ln in out.splitlines())
    return ok, hits


def copy_repo(tmp: Path) -> Path:
    dst = tmp / "repo"
    dst.mkdir()
    for d in ("spec", "synthesis", "decisions", "tools", "spikes"):
        shutil.copytree(ROOT / d, dst / d,
                        ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"))
    for f in ("DESIGN.md", "README.md"):
        shutil.copy2(ROOT / f, dst / f)
    return dst


def main() -> int:
    print("negative controls for the superseded-claims gate")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = copy_repo(tmp)

        # control 0: the unmodified copy must PASS, or every result below is noise
        ok, hits = run_in(base)
        check("baseline copy passes the superseded gate", ok and not hits,
              f"{len(hits)} unexpected: {hits[:2]}")

        # control 1: the one the verifier asked for -- ACP adapter in DESIGN.md
        p = base / "DESIGN.md"
        original = p.read_text()
        p.write_text(original + "\n\nWe ship an ACP adapter for third-party agents.\n")
        ok, hits = run_in(base)
        check("injecting 'ACP adapter' into DESIGN.md FAILS the gate",
              not ok and bool(hits))
        check("...and the failure names DESIGN.md",
              any(h.startswith("DESIGN.md:") for h in hits), str(hits[:2]))
        p.write_text(original)

        # control 2: a file the OLD gate never scanned
        p = base / "synthesis" / "v01-boundary.md"
        original = p.read_text()
        p.write_text(original + "\n\nWe adapt agents written by someone else.\n")
        ok, hits = run_in(base)
        check("a claim in synthesis/ is caught (the old gate scanned spec/ only)",
              any(h.startswith("v01-boundary.md:") for h in hits), str(hits[:2]))
        p.write_text(original)

        # control 3: an amendment marker nearby must still be FORGIVEN
        p.write_text(original + "\n\nAmended 2026-08-27: this once said we adapt\n"
                                "someone else's agents; it no longer does.\n")
        ok, hits = run_in(base)
        check("a dated amendment quoting the old wording is NOT flagged",
              ok and not hits, str(hits[:2]))
        p.write_text(original)

        # control 4: an empty pattern file must FAIL, not silently pass
        pf = base / "tools" / "superseded-patterns.txt"
        saved = pf.read_text()
        pf.write_text("# all patterns removed\n")
        ok, hits = run_in(base)
        check("an empty pattern file does NOT silently pass", not ok)
        pf.write_text(saved)

        # control 5: a Task-deferral claim, the item 3 regression
        p2 = base / "spec" / "00-overview.md"
        orig2 = p2.read_text()
        p2.write_text(orig2 + "\n\nThe Task resource is deferred past v0.1.\n")
        ok, hits = run_in(base)
        check("a revived 'Task is deferred' claim is caught",
              any(h.startswith("00-overview.md:") for h in hits), str(hits[:2]))
        p2.write_text(orig2)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    print("PASS — the gate fails on every injected defect and forgives amendments.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
