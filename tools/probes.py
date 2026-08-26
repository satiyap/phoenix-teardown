"""Parse the probe set and facts schema. Single source of truth for tooling.

Probe ids and section names are read from probes/probe-set.md rather than
duplicated here, so the document stays authoritative.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_SET = REPO_ROOT / "probes" / "probe-set.md"
SCHEMA = REPO_ROOT / "schema" / "facts.schema.yaml"
PROJECTS_DIR = REPO_ROOT / "projects"

# "- **A1** What does..." / "- **S1 — Delegated authority.** Agent A..."
_PROBE_RE = re.compile(r"^-\s+\*\*([A-R]\d{1,2})\*\*\s+(.+)$")
_SCENARIO_RE = re.compile(r"^-\s+\*\*(S\d{1,2})\s*[—-]\s*(.+?)\.?\*\*\s*(.*)$")
# "## A. Core abstraction and object model (A1-A9)"
_SECTION_RE = re.compile(r"^##\s+([A-S])\.\s+(.+?)\s*(?:\(.*\))?$")


def load_schema() -> dict:
    return yaml.safe_load(SCHEMA.read_text())


def vocab(name: str) -> list[str]:
    return load_schema()["vocabularies"][name]


def load_probes() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return (probes, scenarios, sections) keyed by id / section letter."""
    probes: dict[str, str] = {}
    scenarios: dict[str, str] = {}
    sections: dict[str, str] = {}

    for raw in PROBE_SET.read_text().splitlines():
        line = raw.strip()
        if match := _SECTION_RE.match(line):
            sections[match.group(1)] = match.group(2).strip()
            continue
        if match := _PROBE_RE.match(line):
            probes[match.group(1)] = match.group(2).strip()
            continue
        if match := _SCENARIO_RE.match(line):
            title, rest = match.group(2).strip(), match.group(3).strip()
            scenarios[match.group(1)] = f"{title}. {rest}".strip()

    if not probes:
        raise SystemExit(f"no probes parsed from {PROBE_SET} — format drift?")
    return probes, scenarios, sections


def probe_order(pid: str) -> tuple[str, int]:
    """Sort key: section letter, then numeric part (A2 before A10)."""
    return pid[0], int(pid[1:])


def project_slugs() -> list[str]:
    if not PROJECTS_DIR.exists():
        return []
    return sorted(
        p.name for p in PROJECTS_DIR.iterdir()
        if p.is_dir() and (p / "facts.yaml").exists()
    )


def load_facts(slug: str) -> dict:
    return yaml.safe_load((PROJECTS_DIR / slug / "facts.yaml").read_text()) or {}


if __name__ == "__main__":
    probes, scenarios, sections = load_probes()
    print(f"{len(probes)} probes, {len(scenarios)} scenarios, {len(sections)} sections")
    counts: dict[str, int] = {}
    for pid in probes:
        counts[pid[0]] = counts.get(pid[0], 0) + 1
    for letter, title in sections.items():
        n = counts.get(letter, len(scenarios) if letter == "S" else 0)
        print(f"  {letter}. {title:<45} {n}")
