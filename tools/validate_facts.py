"""Validate every projects/*/facts.yaml against schema/facts.schema.yaml.

Exit 1 on error. Warnings do not fail the build: mid-teardown files are
legitimately incomplete, and a validator that blocks progress gets bypassed.

    ./.venv/bin/python tools/validate_facts.py [--strict]

--strict promotes warnings to errors. Use before declaring a phase complete.
"""

from __future__ import annotations

import sys

from probes import (PROJECTS_DIR, REPO_ROOT, load_facts, load_probes,
                    load_schema, probe_order, project_slugs)

DATE_RE = r"^\d{4}-\d{2}-\d{2}$"


def validate(slug: str, schema: dict, probes: dict, scenarios: dict,
             ) -> tuple[list[str], list[str], float]:
    import re

    errors: list[str] = []
    warnings: list[str] = []
    unknowns: list[str] = []
    vocabs = schema["vocabularies"]

    try:
        facts = load_facts(slug)
    except Exception as exc:
        return [f"{slug}: unparseable YAML: {exc}"], [], 0.0

    for field in schema["required_top_level"]:
        if field not in facts:
            errors.append(f"{slug}: missing top-level '{field}'")

    if facts.get("schema_version") != schema["schema_version"]:
        errors.append(
            f"{slug}: schema_version {facts.get('schema_version')!r} "
            f"!= {schema['schema_version']}"
        )

    project = facts.get("project") or {}
    spec = schema["project_fields"]
    for field in spec["required"]:
        if not project.get(field):
            errors.append(f"{slug}: project.{field} is required")

    if project.get("slug") and project["slug"] != slug:
        errors.append(
            f"{slug}: project.slug is {project['slug']!r}, must match directory"
        )

    known = set(spec["required"]) | set(spec["optional"])
    for field in project:
        if field not in known:
            warnings.append(f"{slug}: unknown project field '{field}'")

    if (read_on := project.get("read_on")) and not re.match(DATE_RE, str(read_on)):
        errors.append(f"{slug}: project.read_on {read_on!r} is not YYYY-MM-DD")

    # Enum-valued project fields.
    for field, vocab_name in (
        ("depth", "depth"),
        ("evidence_class", "evidence_class"),
        ("runtime_class", "runtime_class"),
        ("license_verdict", "license_verdict"),
    ):
        value = project.get(field)
        if value is not None and value not in vocabs[vocab_name]:
            errors.append(
                f"{slug}: project.{field}={value!r} not in {vocabs[vocab_name]}"
            )

    depth = project.get("depth")
    entries = facts.get("probes") or {}
    if not isinstance(entries, dict):
        errors.append(f"{slug}: 'probes' must be a mapping of probe id -> entry")
        entries = {}

    answered = 0
    # A stub is all-unknown by design. Only nag about unknowns once the
    # teardown is genuinely in progress, or the warnings train people to
    # ignore warnings.
    started = any(
        isinstance(e, dict) and e.get("verdict") not in (None, "unknown")
        for e in entries.values()
    ) if isinstance(entries, dict) else False

    for pid, entry in sorted(entries.items(), key=lambda kv: _safe_order(kv[0])):
        if pid not in probes and pid not in scenarios:
            errors.append(f"{slug}: unknown probe id '{pid}'")
            continue
        if not isinstance(entry, dict):
            errors.append(f"{slug}: probe {pid} must be a mapping, got {type(entry).__name__}")
            continue

        is_scenario = pid in scenarios
        allowed = vocabs["scenario_verdict" if is_scenario else "verdict"]
        verdict = entry.get("verdict")
        if verdict is None:
            errors.append(f"{slug}: probe {pid} missing 'verdict'")
            continue
        if verdict not in allowed:
            errors.append(f"{slug}: probe {pid} verdict={verdict!r} not in {allowed}")
            continue

        if verdict not in ("unknown",):
            answered += 1
        if verdict in ("first_class", "implicit", "first_class_answer", "inferable"):
            if not entry.get("evidence"):
                warnings.append(f"{slug}: probe {pid} verdict={verdict} has no evidence")
        if verdict == "unknown" and depth == "deep" and started:
            unknowns.append(pid)

    total = len(probes) + len(scenarios)
    coverage = 100.0 * answered / total if total else 0.0

    # One aggregated warning beats 140 individual ones.
    if unknowns:
        preview = ", ".join(unknowns[:12])
        more = f" +{len(unknowns) - 12} more" if len(unknowns) > 12 else ""
        warnings.append(
            f"{slug}: {len(unknowns)} probe(s) still unknown "
            f"({preview}{more}) — each needs an open-questions.md entry"
        )

    # Cross-file consistency: teardown.md should exist for anything deep.
    if depth == "deep" and not (PROJECTS_DIR / slug / "teardown.md").exists():
        warnings.append(f"{slug}: depth=deep but no teardown.md")

    for item in facts.get("adr_impact") or []:
        if not isinstance(item, dict) or "adr" not in item or "effect" not in item:
            errors.append(f"{slug}: adr_impact entries need 'adr' and 'effect'")
            continue
        if item["effect"] not in ("confirms", "amends", "challenges", "neutral"):
            errors.append(f"{slug}: adr_impact effect {item['effect']!r} invalid")

    for item in facts.get("reusable_components") or []:
        if isinstance(item, dict) and (d := item.get("decision")):
            if d not in vocabs["build_decision"]:
                errors.append(f"{slug}: reusable_components decision {d!r} invalid")

    return errors, warnings, coverage


def _safe_order(pid: str) -> tuple[str, int]:
    try:
        return probe_order(pid)
    except (ValueError, IndexError):
        return ("~", 0)


def main() -> int:
    strict = "--strict" in sys.argv
    schema = load_schema()
    probes, scenarios, _ = load_probes()

    slugs = project_slugs()
    if not slugs:
        print("No projects with facts.yaml yet. Nothing to validate.")
        return 0

    all_errors: list[str] = []
    all_warnings: list[str] = []
    print(f"{'project':<26} {'depth':<9} {'cov':>6}  status")
    print("-" * 60)
    for slug in slugs:
        errors, warnings, coverage = validate(slug, schema, probes, scenarios)
        facts = {}
        try:
            facts = load_facts(slug)
        except Exception:
            pass
        depth = (facts.get("project") or {}).get("depth", "?")
        status = "FAIL" if errors else ("warn" if warnings else "ok")
        print(f"{slug:<26} {depth:<9} {coverage:5.1f}%  {status}"
              f"{f' ({len(errors)}e/{len(warnings)}w)' if errors or warnings else ''}")
        all_errors += errors
        all_warnings += warnings

    if all_warnings:
        print(f"\n{len(all_warnings)} warning(s):")
        for warning in all_warnings[:40]:
            print(f"  ! {warning}")
        if len(all_warnings) > 40:
            print(f"  ... and {len(all_warnings) - 40} more")

    if all_errors:
        print(f"\n{len(all_errors)} error(s):")
        for error in all_errors:
            print(f"  x {error}")
        return 1

    if strict and all_warnings:
        print("\n--strict: warnings treated as errors")
        return 1

    print("\nAll facts.yaml valid.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    raise SystemExit(main())
