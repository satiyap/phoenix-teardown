#!/usr/bin/env python3
"""Self-test for the superseded-claims gate.

The gate passed on commit 793828b with "We adapt agents supplied by customers."
and "Our adapter exposes four methods." sitting in scratch copies. Three faults:
case-sensitive matching, per-LINE application with a 3-line forgiveness window,
and quoting treated as an exemption.

Each mutation below is injected into a temp copy and must FAIL the gate, naming
both the file and the offending sentence. Baseline must pass.

Run: make gate-tests
"""
from __future__ import annotations

import glob
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(label: str, cond: bool, detail: str = "") -> None:
    """Print the detail ONLY on failure.

    An earlier version printed it always, so a passing line read
    "ok  <label>  [caught but sentence not quoted]" -- the diagnostic for the
    failure case, displayed next to a pass. Misleading output in a green run is
    the same defect class as a green run that means nothing.
    """
    (PASS if cond else FAIL).append(label)
    suffix = f"  [{detail}]" if (detail and not cond) else ""
    print(f"  {'ok  ' if cond else 'FAIL'} {label}{suffix}")


def copy_repo(tmp: Path) -> Path:
    dst = tmp / "repo"
    dst.mkdir()
    for d in ("spec", "synthesis", "decisions", "tools", "spikes"):
        src = ROOT / d
        if src.is_dir():
            shutil.copytree(src, dst / d,
                            ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"))
    for f in ("DESIGN.md", "README.md", "open-questions.md"):
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, dst / f)
    return dst


def run_gate(tree: Path) -> tuple[bool, list[str]]:
    """Isolate the superseded result: a partial copy legitimately fails other checks."""
    res = subprocess.run([sys.executable, str(tree / "tools" / "validate_spec.py")],
                         capture_output=True, text=True, cwd=str(tree),
                         env={"PATH": "/usr/bin:/bin", "SPEC_ALLOW_UNVERIFIED": "1"})
    out = res.stdout + res.stderr
    hits, keep = [], False
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith("x ") and "superseded" in s:
            hits.append(s[2:].strip())
            keep = True
        elif keep and s.startswith("-> "):
            hits[-1] += " " + s
        else:
            keep = False
    ok = any("superseded claims" in ln and " ok" in ln for ln in out.splitlines())
    return ok, hits


# (label, relative path or glob, sentence to inject)
MUTATIONS = [
    ("'We adapt agents supplied by customers.' in DESIGN.md",
     "DESIGN.md", "We adapt agents supplied by customers."),
    ("'Our adapter exposes four methods.' in reference-architecture.md",
     "synthesis/reference-architecture.md", "Our adapter exposes four methods."),
    # Injected into the DECISION section, not the evidence log: everything after
    # "## Evidence log" is a finding about another project and is exempt by design.
    # Appending at end-of-file would land inside that exemption and test nothing.
    ("'The ACP path ships first.' in ADR-0014 (decision section)",
     "decisions/ADR-0014-*.md", "The ACP path ships first."),
    ("'a pending row past its lease' in exit-criteria.md",
     "synthesis/exit-criteria.md", "Consider a pending row past its lease."),
    # The verifier's actual misses on 3026e38. Each passed the gate before redo 3.
    ("identity comment 'acp:claude-code'",
     "spec/01-schema.md", "-- identity looks like 'acp:claude-code'."),
    ("'ACP covers the agents we care about'",
     "synthesis/v01-boundary.md", "ACP covers the agents we care about."),
    ("'no Task resource yet'",
     "spec/01-schema.md", "Intent lives on the run (no Task resource yet)."),
    ("'can tell you whether the effect happened'",
     "README.md", "After a crash it can tell you whether the effect happened."),
    ("'the restriction costs nothing'",
     "spec/07-adapter-protocol.md", "And the restriction costs nothing."),
    ("'Spike the storage swap before committing'",
     "synthesis/v01-boundary.md", "Mitigation: spike the storage swap before committing."),
]


def main() -> int:
    print("self-test: superseded-claims gate")
    with tempfile.TemporaryDirectory() as td:
        base = copy_repo(Path(td))

        ok, hits = run_gate(base)
        check("baseline copy passes", ok and not hits,
              f"{len(hits)} unexpected: {hits[:1]}")
        if hits:
            print("      (baseline must be clean before any mutation means anything)")

        for label, rel, sentence in MUTATIONS:
            matches = glob.glob(str(base / rel))
            if not matches:
                check(label, False, f"target {rel} not found")
                continue
            target = Path(matches[0])
            original = target.read_text()
            if "## Evidence log" in original:
                head, sep, tail = original.partition("## Evidence log")
                target.write_text(head + "\n" + sentence + "\n\n" + sep + tail)
            else:
                target.write_text(original + "\n\n" + sentence + "\n")
            ok, hits = run_gate(base)
            named = [h for h in hits if h.startswith(target.name + ":")]
            quoted = [h for h in named if sentence.rstrip(".") in h]
            check(label, bool(named) and bool(quoted),
                  "not caught" if not named else "caught but sentence not quoted")
            target.write_text(original)

        # a dated retraction IS exempt; a bare quote is NOT
        p = base / "DESIGN.md"
        original = p.read_text()
        p.write_text(original + "\n\nRetracted 2026-08-27: we no longer adapt agents "
                                "supplied by customers.\n")
        ok, hits = run_gate(base)
        check("a dated retraction in the same sentence is exempt", ok and not hits,
              str(hits[:1]))
        p.write_text(original + "\n\nThis document once said we adapt agents "
                                "supplied by customers.\n")
        ok, hits = run_gate(base)
        check("quoting WITHOUT a date is NOT exempt", bool(hits))
        p.write_text(original)

        # the inventory-count check needs a control too (step 4)
        p = base / "README.md"
        original = p.read_text()
        p.write_text(re.sub(r"\d+ required invariant tests",
                            "999 required invariant tests", original))
        res = subprocess.run([sys.executable, str(base / "tools" / "validate_spec.py")],
                             capture_output=True, text=True, cwd=str(base),
                             env={"PATH": "/usr/bin:/bin", "SPEC_ALLOW_UNVERIFIED": "1"})
        out = res.stdout + res.stderr
        check("a wrong invariant count in README fails the count check",
              "invariant" in out and "999" in out, "count check did not fire")
        p.write_text(original)

        # empty pattern file must not silently pass
        pf = base / "tools" / "superseded-patterns.txt"
        saved = pf.read_text()
        pf.write_text("# emptied\n")
        ok, _ = run_gate(base)
        check("an empty pattern file does not silently pass", not ok)
        pf.write_text(saved)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    print("PASS — every mutation is caught and named; amendments are forgiven only when dated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
