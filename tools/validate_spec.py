#!/usr/bin/env python3
"""Validate spec/ — so `make check` says something about the specification.

Review finding 11: `make check` validated teardown facts and printed status, but
never parsed spec/. "make check green" was true and irrelevant to spec correctness.

Checks, all of which have caught a real defect in this repo:
  1. the canonicalisation fixture reproduces against the reference implementation
  2. every required equality/rejection in the fixture actually holds
  3. the normative rewind algorithm permits continuation after a rewind
  4. cross-document references resolve
  5. no placeholder text survives
  6. every SQL table referenced by a FOREIGN KEY is defined somewhere in the spec
  7. the extracted .proto actually compiles (this found an undefined message)
  8. openapi.yaml parses and covers exactly the paths 06-api.md documents
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec"
PIN = ROOT / "spikes" / "02-definition-pin"


def check_canon_vectors() -> list[str]:
    """Verify the fixture against an INDEPENDENT implementation, not its author.

    Review finding: comparing the vectors with the same Python that generated
    them proves only that Python is deterministic. The CLAIM is cross-language
    reproducibility, so the oracle must be a different language. `canon_ref.mjs`
    is written from the normative text, not ported from pin.py.

    It has already earned its keep: it could not even PARSE the fixture, because
    Python had written bare `NaN`/`Infinity` — literals no other language reads.
    """
    errs: list[str] = []
    fx_path = SPEC / "canon_vectors.json"
    if not fx_path.exists():
        return ["spec/canon_vectors.json missing"]

    raw = fx_path.read_text()
    for literal in ("NaN", "Infinity"):
        if f": {literal}" in raw:
            errs.append(f"canon_vectors.json contains the non-JSON literal {literal}; "
                        f"other languages cannot parse it")
    try:
        fx = json.loads(raw)
    except Exception as exc:                                     # noqa: BLE001
        return errs + [f"canon_vectors.json is not valid JSON: {exc}"]

    if not fx.get("reject"):
        errs.append("fixture lists no rejection cases")
    if "sort_rule" not in fx:
        errs.append("fixture does not state its key sort_rule")

    # 1. the spike fixture and the spec fixture must be the same file
    spike_fx = PIN / "canon_vectors.json"
    if spike_fx.exists() and spike_fx.read_text() != raw:
        errs.append("spec/canon_vectors.json and the spike fixture have diverged")

    # 2. the independent JS oracle must reproduce every accept and reject
    oracle = PIN / "canon_ref.mjs"
    node = shutil.which("node")
    if not oracle.exists():
        errs.append("canon_ref.mjs missing — no independent oracle for the vectors")
    elif node is None:
        # FAIL CLOSED. A missing verifier is an unverified claim, not a pass.
        errs.append("node is not installed, so the canonicalisation vectors cannot be "
                    "verified against an independent implementation. Install node or "
                    "run with SPEC_ALLOW_UNVERIFIED=1 to downgrade this to a warning.")
    else:
        res = subprocess.run([node, str(oracle), str(fx_path)],
                             capture_output=True, text=True, cwd=str(PIN))
        if res.returncode != 0:
            detail = (res.stdout + res.stderr).strip().splitlines()
            errs.extend(f"independent oracle disagrees: {ln.strip()}"
                        for ln in detail if ln.strip())

    # 3. the fixture's own MUST EQUAL relations, checked structurally
    by_n = {r["n"]: r for r in fx.get("accept", [])}
    for n, row in by_n.items():
        m = re.search(r"MUST EQUAL #(\d+)", row.get("note", ""))
        if m:
            other = int(m.group(1))
            if other not in by_n:
                errs.append(f"vector #{n} references missing #{other}")
            elif by_n[other]["digest"] != row["digest"]:
                errs.append(f"vector #{n} must equal #{other} but digests differ")
        m2 = re.search(r"MUST DIFFER from #(\d+)", row.get("note", ""))
        if m2:
            other = int(m2.group(1))
            if other in by_n and by_n[other]["digest"] == row["digest"]:
                errs.append(f"vector #{n} must differ from #{other} but digests match")
    return errs


def check_rewind_algorithm() -> list[str]:
    """The epoch model: algorithm AND the DDL that makes it enforceable.

    Review finding: epochs existed in prose but not in storage. Checking the
    algorithm alone would pass a spec whose event table has no epoch column.
    """
    errs: list[str] = []
    ev = (SPEC / "04-events.md").read_text()
    sc = (SPEC / "01-schema.md").read_text()
    if "epoch" not in ev.lower():
        errs.append("04-events.md: no epoch semantics — the naive rewind rule "
                    "loses post-rewind events")
    # the DDL must actually carry it
    # Must match a COLUMN DEFINITION, not merely the substring "epoch" — the
    # constraint name run_events_epoch_nonneg contains it, which made an earlier
    # version of this check pass with the column deleted. Found by its own
    # negative control.
    _blk = re.search(r"CREATE TABLE run_events\b(.*?)\n\);", sc, re.DOTALL)
    _has_col = _blk and re.search(r"^\s+epoch\s+(INTEGER|BIGINT|INT)\b",
                                 _blk.group(1), re.MULTILINE)
    if not _has_col:
        errs.append("01-schema.md: run_events has no `epoch` column, so the epoch "
                    "model in 04 is unimplementable")
    if "current_epoch" not in sc:
        errs.append("01-schema.md: no `current_epoch` on runs, so nothing defines "
                    "which epoch an ordinary append belongs to")
    if "run_events_epoch_check" not in sc:
        errs.append("01-schema.md: no trigger enforcing epoch assignment; an event "
                    "could invent a future or past epoch")
    ap = (SPEC / "02-consistency.md").read_text()
    if not re.search(r"INSERT INTO run_events[^;]{0,400}?epoch", ap, re.DOTALL):
        errs.append("02-consistency.md: the append protocol does not carry an epoch")
    if errs:
        return errs
    script = SPEC / "epoch_algorithm_test.py"
    if not script.exists():
        return ["spec/epoch_algorithm_test.py missing — the rewind rule is unverified"]
    res = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    if res.returncode != 0:
        tail = (res.stdout + res.stderr).strip().splitlines()[-3:]
        return [f"rewind/epoch test failed: {' | '.join(t.strip() for t in tail)}"]
    return []


def check_proto_compiles() -> list[str]:
    """Extract the proto from 07 and COMPILE it.

    This caught a real defect: `DescribeRequest` was referenced by the Describe RPC
    and never defined. A protobuf contract that lives only in Markdown is never
    compiled, so it is never correct for long.
    """
    spec07 = SPEC / "07-adapter-protocol.md"
    if not spec07.exists():
        return ["07-adapter-protocol.md missing"]
    blocks = re.findall(r"```protobuf\n(.*?)```", spec07.read_text(), re.DOTALL)
    if not blocks:
        return ["07-adapter-protocol.md: no protobuf blocks found"]
    out = SPEC / "contracts" / "adapter.proto"
    out.parent.mkdir(exist_ok=True)
    extracted = "\n".join(b.rstrip() for b in blocks) + "\n"
    if not out.exists() or out.read_text() != extracted:
        out.write_text(extracted)      # regenerate: the .md is the source
    try:
        from grpc_tools import protoc          # type: ignore
    except ImportError:
        # FAIL CLOSED. Silently passing when the compiler is absent is how a
        # non-compiling contract stayed green (review finding 7).
        return ["grpcio-tools is not installed, so the .proto is UNVERIFIED. "
                "Run `make setup`, or set SPEC_ALLOW_UNVERIFIED=1."]
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rc = protoc.main(["protoc", f"--proto_path={out.parent}",
                          f"--python_out={td}", str(out)])
    return [] if rc == 0 else ["contracts/adapter.proto does not compile "
                               "(run: make spec, read protoc output above)"]


def check_openapi() -> list[str]:
    """The OpenAPI file must parse AND cover exactly the paths 06 documents.

    Prevents the drift where prose gains an endpoint the contract never learns about.
    """
    oa = SPEC / "contracts" / "openapi.yaml"
    if not oa.exists():
        return ["contracts/openapi.yaml missing"]
    try:
        import yaml  # type: ignore
    except ImportError:
        return ["pyyaml is not installed, so openapi.yaml is UNVERIFIED. "
                "Run `make setup`, or set SPEC_ALLOW_UNVERIFIED=1."]
    try:
        doc = yaml.safe_load(oa.read_text())
    except Exception as exc:                                    # noqa: BLE001
        return [f"openapi.yaml does not parse: {exc}"]

    declared = set(doc.get("paths", {}))
    md = (SPEC / "06-api.md").read_text()
    documented = set()
    for verb, path in re.findall(r"^(POST|GET|PATCH|PUT|DELETE)\s+(/v1/\S+)", md,
                                re.MULTILINE):
        path = path.split("?")[0].rstrip(",.")
        documented.add(path)

    errs = []
    for missing in sorted(documented - declared):
        errs.append(f"06-api.md documents {missing} but openapi.yaml omits it")
    for extra in sorted(declared - documented):
        errs.append(f"openapi.yaml declares {extra} but 06-api.md does not document it")
    return errs


def check_references() -> list[str]:
    errs = []
    for f in sorted(SPEC.glob("*.md")):
        for ref in re.findall(r"\]\((\d\d-[a-z0-9-]+\.md)", f.read_text()):
            if not (SPEC / ref).exists():
                errs.append(f"{f.name}: dangling reference to {ref}")
    return errs


def check_placeholders() -> list[str]:
    errs = []
    for f in sorted(SPEC.glob("*.md")):
        body = f.read_text()
        for pat in ("TODO", "TBD", "generate and pin", "FIXME"):
            if pat in body:
                errs.append(f"{f.name}: placeholder {pat!r}")
    return errs


def check_fk_targets() -> list[str]:
    """Every table named in a FOREIGN KEY must be CREATEd in the spec."""
    body = "\n".join(f.read_text() for f in SPEC.glob("*.md"))
    defined = set(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", body))
    referenced = set(re.findall(r"REFERENCES\s+(\w+)\s*\(", body))
    missing = sorted(referenced - defined)
    return [f"FOREIGN KEY references undefined table: {m}" for m in missing]


UNVERIFIED = "UNVERIFIED"


def _downgrade(errs: list[str]) -> tuple[list[str], list[str]]:
    """Split hard failures from 'cannot verify' when explicitly allowed."""
    if os.environ.get("SPEC_ALLOW_UNVERIFIED") != "1":
        return errs, []
    hard, soft = [], []
    for e in errs:
        (soft if UNVERIFIED in e or "is not installed" in e else hard).append(e)
    return hard, soft


def main() -> int:
    groups = [
        ("canonicalisation vectors", check_canon_vectors()),
        ("rewind algorithm", check_rewind_algorithm()),
        ("protobuf compiles", check_proto_compiles()),
        ("openapi coverage", check_openapi()),
        ("cross-references", check_references()),
        ("placeholders", check_placeholders()),
        ("foreign-key targets", check_fk_targets()),
    ]
    print("spec validation")
    print("-" * 52)
    hard_total, soft_total = 0, 0
    resolved = []
    for label, errs in groups:
        hard, soft = _downgrade(errs)
        resolved.append((label, hard, soft))
        if hard:
            status = f"{len(hard)} problem(s)"
        elif soft:
            status = f"UNVERIFIED ({len(soft)})"
        else:
            status = "ok"
        print(f"  {label:26} {status}")
        hard_total += len(hard)
        soft_total += len(soft)

    if hard_total or soft_total:
        print()
        for label, hard, soft in resolved:
            for e in hard:
                print(f"  x {e}")
            for e in soft:
                print(f"  ! {e}")
    if hard_total:
        return 1
    if soft_total:
        print(f"\nspec/ has no known defects, but {soft_total} check(s) could not RUN.")
        print("That is weaker than valid. Install the missing tools.")
        return 0
    print("\nspec/ valid (all checks executed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
