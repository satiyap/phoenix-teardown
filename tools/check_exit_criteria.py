"""Report progress against synthesis/exit-criteria.md and the phase plan.

    ./.venv/bin/python tools/check_exit_criteria.py

Aggregates three signals so status is one command, not a reading exercise:
  1. exit criteria answered   (Section 28 questions)
  2. per-project probe coverage
  3. ADR status and evidence
"""

from __future__ import annotations

import re
from pathlib import Path

from probes import (PROJECTS_DIR, REPO_ROOT, load_facts, load_probes,
                    project_slugs)

EXIT_FILE = REPO_ROOT / "synthesis" / "exit-criteria.md"
DECISIONS_DIR = REPO_ROOT / "decisions"

_Q_RE = re.compile(r"^###\s+(Q\d+)\.\s+(.+?)\s*$")
_A_RE = re.compile(r"^Answer:\s*(.*)$")


def exit_criteria() -> list[tuple[str, str, bool]]:
    if not EXIT_FILE.exists():
        return []
    rows: list[tuple[str, str, bool]] = []
    qid = title = None
    in_fence = False
    for raw in EXIT_FILE.read_text().splitlines():
        # The file documents its own format in a fenced block; don't parse that
        # example as a real question.
        if raw.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if match := _Q_RE.match(raw.strip()):
            qid, title = match.group(1), match.group(2)
            continue
        if qid and (match := _A_RE.match(raw.strip())):
            answer = match.group(1).strip()
            answered = bool(answer) and "TODO" not in answer.upper()
            rows.append((qid, title, answered))
            qid = title = None
    return rows


def adr_status() -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    if not DECISIONS_DIR.exists():
        return rows
    for path in sorted(DECISIONS_DIR.glob("ADR-*.md")):
        text = path.read_text()
        status = "unknown"
        if match := re.search(r"\*\*Status:\*\*\s*(.+)", text):
            status = match.group(1).strip().split("(")[0].strip()
        rows.append((path.stem.split("-")[0] + "-" + path.stem.split("-")[1],
                     status, text.count("| ")))
    return rows


def main() -> int:
    probes, scenarios, _ = load_probes()
    total_probes = len(probes) + len(scenarios)

    print("=" * 66)
    print("PHOENIX TEARDOWN — STATUS")
    print("=" * 66)

    slugs = project_slugs()
    deep = targeted = 0
    print(f"\nProjects ({len(slugs)} scaffolded)\n")
    print(f"  {'project':<28} {'depth':<9} {'ev':<3} {'cov':>5}  {'ADR impact':>10}")
    print("  " + "-" * 62)
    for slug in slugs:
        facts = load_facts(slug)
        project = facts.get("project") or {}
        entries = facts.get("probes") or {}
        answered = sum(
            1 for e in entries.values()
            if isinstance(e, dict) and e.get("verdict") not in (None, "unknown")
        )
        pct = 100.0 * answered / total_probes if total_probes else 0.0
        depth = project.get("depth", "?")
        deep += depth == "deep"
        targeted += depth == "targeted"
        impacts = len(facts.get("adr_impact") or [])
        flag = "" if impacts or pct == 0 else "  <- no ADR impact recorded"
        print(f"  {slug:<28} {depth:<9} {str(project.get('evidence_class','?')):<3} "
              f"{pct:4.0f}%  {impacts:>10}{flag}")

    rows = exit_criteria()
    done = sum(1 for *_, ok in rows if ok)
    print(f"\nExit criteria: {done}/{len(rows)} answered")
    if rows and done < len(rows):
        pending = [qid for qid, _, ok in rows if not ok]
        print(f"  outstanding: {', '.join(pending[:14])}"
              + (f" +{len(pending)-14} more" if len(pending) > 14 else ""))

    adrs = adr_status()
    print(f"\nADRs: {len(adrs)}")
    by_status: dict[str, int] = {}
    for _, status, _ in adrs:
        by_status[status] = by_status.get(status, 0) + 1
    for status, count in sorted(by_status.items()):
        print(f"  {status:<14} {count}")

    # Deliverables from section 22-27.
    print("\nSynthesis deliverables\n")
    deliverables = [
        ("D1 capability matrix", "synthesis/capability-matrix.md"),
        ("D2 ADR log", "decisions/"),
        ("D3 domain model", "synthesis/domain-model.md"),
        ("D4 reference architecture", "synthesis/reference-architecture.md"),
        ("D5 build/reuse map", "synthesis/build-reuse-map.md"),
        ("D6 v0.1 boundary", "synthesis/v01-boundary.md"),
        ("   licensing review", "synthesis/licensing.md"),
        ("   open questions", "open-questions.md"),
    ]
    for label, rel in deliverables:
        path = REPO_ROOT / rel
        if path.is_dir():
            state = f"{len(list(path.glob('*.md')))} files"
        elif path.exists():
            body = path.read_text()
            lowered = body.lower()
            if "strawman" in lowered or "status: **stub" in lowered:
                state = "strawman"
            elif "GENERATED" in body and body.count("·") > 0 and "not yet examined" in body:
                state = "generated"
            elif "TODO" in body or len(body) < 1200:
                state = "stub"
            else:
                state = "drafted"
        else:
            state = "missing"
        print(f"  {label:<28} {state:<10} {rel}")

    print(f"\n{deep} deep + {targeted} targeted. Probe set: {total_probes} probes.")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
