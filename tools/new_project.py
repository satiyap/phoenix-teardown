"""Scaffold projects/<slug>/ with facts.yaml, teardown.md, sources.md, dx-log.md.

    ./.venv/bin/python tools/new_project.py <slug> "<Display Name>" [depth]

depth defaults to 'deep'. Existing files are never overwritten.
The generated facts.yaml is pre-populated with every probe id set to 'unknown',
so filling it in is editing rather than remembering.
"""

from __future__ import annotations

import sys
from datetime import date

from probes import (PROJECTS_DIR, REPO_ROOT, load_probes, load_schema,
                    probe_order)

TEMPLATE = REPO_ROOT / "schema" / "teardown-template.md"


def facts_stub(slug: str, name: str, depth: str) -> str:
    probes, scenarios, sections = load_probes()
    schema = load_schema()

    lines = [
        "# Machine-readable extraction. Schema: schema/facts.schema.yaml",
        "# Validate:  ./.venv/bin/python tools/validate_facts.py",
        "#",
        "# verdict:   first_class | implicit | absent | unknown",
        "# scenarios: first_class_answer | inferable | undefined | unknown",
        "# evidence:  'path/file.py:120 @ sha'  or  'URL (read YYYY-MM-DD)'",
        "",
        f"schema_version: {schema['schema_version']}",
        "",
        "project:",
        f"  slug: {slug}",
        f"  name: {name}",
        f"  depth: {depth}",
        "  evidence_class: C        # A source+docs | B docs only | C thin",
        f"  read_on: {date.today().isoformat()}",
        "  repo:",
        "  commit:                  # SHA the claims were read against",
        "  docs:",
        "  version:",
        "  license:",
        "  license_verdict: unknown",
        "  runtime_class: unknown",
        "  one_line:                # what it is, in their vocabulary",
        "  thesis:                  # the core architectural bet",
        "",
        "probes:",
    ]

    current_section = None
    for pid in sorted(probes, key=probe_order):
        letter = pid[0]
        if letter != current_section:
            current_section = letter
            lines.append("")
            lines.append(f"  # --- {letter}. {sections.get(letter, '')} ---")
        question = probes[pid]
        if len(question) > 96:
            question = question[:93] + "..."
        lines.append(f"  # {pid}: {question}")
        lines.append(f"  {pid}:")
        lines.append("    verdict: unknown")
        lines.append("    note:")
        lines.append("    evidence:")

    lines.append("")
    lines.append(f"  # --- S. {sections.get('S', 'Hard scenarios')} ---")
    for pid in sorted(scenarios, key=probe_order):
        title = scenarios[pid].split(".")[0]
        lines.append(f"  # {pid}: {title}")
        lines.append(f"  {pid}:")
        lines.append("    verdict: unknown")
        lines.append("    note:")
        lines.append("    evidence:")

    lines += [
        "",
        "object_model: |",
        "  # ASCII tree of resources that actually exist",
        "",
        "strongest_ideas: []",
        "",
        "weakest_choices: []",
        "",
        "reusable_components: []",
        "  # - component: ",
        "  #   decision: INTEGRATE   # BUILD|INTEGRATE|ADOPT_AS_STANDARD|REUSE|DEFER",
        "  #   note: ",
        "",
        "lessons: []",
        "",
        "adr_impact: []",
        "  # - adr: ADR-0001",
        "  #   effect: confirms      # confirms|amends|challenges|neutral",
        "  #   note: ",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    slug, name = sys.argv[1], sys.argv[2]
    depth = sys.argv[3] if len(sys.argv) > 3 else "deep"

    valid_depths = load_schema()["vocabularies"]["depth"]
    if depth not in valid_depths:
        print(f"depth must be one of {valid_depths}")
        return 2
    if slug != slug.lower() or " " in slug:
        print("slug must be lowercase with dashes, no spaces")
        return 2

    directory = PROJECTS_DIR / slug
    directory.mkdir(parents=True, exist_ok=True)

    created, skipped = [], []
    files = {
        "facts.yaml": facts_stub(slug, name, depth),
        "teardown.md": TEMPLATE.read_text().replace("<PROJECT NAME>", name),
        "sources.md": (
            f"# Sources — {name}\n\n"
            "Every URL and file path the teardown cites, with the date read and\n"
            "the commit SHA. This is what makes claims auditable six months on.\n\n"
            "## Repository\n\n- repo: \n- commit: \n- cloned on: \n\n"
            "## Documentation\n\n| URL | Read on | Notes |\n|---|---|---|\n| | | |\n\n"
            "## Key source files\n\n| Path | Why it matters |\n|---|---|\n| | |\n\n"
            "## Other\n\nBlog posts, talks, RFCs, issues, PRs.\n"
        ),
        "dx-log.md": (
            f"# DX log — {name}\n\n"
            "Timeboxed 60–90 min hands-on. Log friction **as it happens**;\n"
            "reconstructing this afterwards loses the detail that matters.\n\n"
            "- Started: \n- Stopped: \n- Got to a running agent: yes / no\n\n"
            "## Timeline\n\n| Elapsed | What I did | What happened |\n|---|---|---|\n"
            "| 0:00 | | |\n\n"
            "## Friction points\n\n1. \n\n"
            "## What was genuinely good\n\n1. \n\n"
            "## Answers to R1–R7\n\n"
            "- R1 clone to running agent: \n- R2 concepts before hello world: \n"
            "- R3 local dev loop / hot reload: \n- R4 debugging a stuck run: \n"
            "- R5 unit testing an agent: \n- R6 deployment: \n- R7 CLI ergonomics: \n"
        ),
    }
    for filename, content in files.items():
        path = directory / filename
        if path.exists():
            skipped.append(filename)
            continue
        path.write_text(content)
        created.append(filename)

    location = directory.relative_to(REPO_ROOT)
    print(f"{location}: created {', '.join(created) or 'nothing'}"
          + (f" (kept existing {', '.join(skipped)})" if skipped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
