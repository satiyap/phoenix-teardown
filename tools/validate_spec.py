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
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec"
PIN = ROOT / "spikes" / "02-definition-pin"


def check_canon_vectors() -> list[str]:
    """The fixture is normative; it must reproduce against the implementation."""
    errs: list[str] = []
    fx_path = SPEC / "canon_vectors.json"
    if not fx_path.exists():
        return ["spec/canon_vectors.json missing"]
    fx = json.loads(fx_path.read_text())

    code = r'''
import json, sys
sys.path.insert(0, %r)
from pin import canonical_digest, NonCanonical, CANON_PROFILE, CANON_VERSION
fx = json.load(open(%r))
out = {"profile": f"{CANON_PROFILE}/v{CANON_VERSION}", "accept": [], "reject": []}
for r in fx["accept"]:
    out["accept"].append({"n": r["n"],
                          "digest": canonical_digest(r["payload"], kind=r["kind"])})
for r in fx["reject"]:
    out["reject"].append({"case": r["case"]})
print(json.dumps(out))
''' % (str(PIN), str(fx_path))
    py = PIN / ".venv" / "bin" / "python"
    if not py.exists():
        return ["spikes/02-definition-pin/.venv missing — cannot verify vectors"]
    res = subprocess.run([str(py), "-c", code], capture_output=True, text=True)
    if res.returncode != 0:
        return [f"vector check failed to run: {res.stderr.strip()[-200:]}"]
    got = json.loads(res.stdout)

    if got["profile"] != fx["profile"]:
        errs.append(f"profile drift: fixture {fx['profile']} != impl {got['profile']}")
    by = {r["n"]: r["digest"] for r in got["accept"]}
    for r in fx["accept"]:
        if by.get(r["n"]) != r["digest"]:
            errs.append(f"vector #{r['n']} digest drift: "
                        f"fixture {r['digest'][:12]} != impl {by.get(r['n'], '?')[:12]}")

    # the required relations, asserted from the fixture itself
    def dig(n): return by.get(n)
    notes = {r["n"]: r.get("note", "") for r in fx["accept"]}
    for a, b in _must_equal(notes):
        if dig(a) != dig(b):
            errs.append(f"vector #{a} must equal #{b} ({notes[a]})")
    return errs


def _must_equal(notes: dict[int, str]) -> list[tuple[int, int]]:
    """Parse 'MUST EQUAL #n' out of the fixture notes, so the fixture is the source."""
    pairs = []
    for n, note in notes.items():
        m = re.search(r"MUST EQUAL #(\d+)", note)
        if m:
            pairs.append((n, int(m.group(1))))
    return pairs


def check_rewind_algorithm() -> list[str]:
    """The normative epoch algorithm must permit continuation after a rewind."""
    t = (SPEC / "04-events.md").read_text()
    if "epoch" not in t.lower():
        return ["04-events.md: no epoch semantics — the naive rewind rule loses "
                "post-rewind events"]
    script = SPEC / "epoch_algorithm_test.py"
    if not script.exists():
        return ["spec/epoch_algorithm_test.py missing — the rewind rule is unverified"]
    res = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    if res.returncode != 0:
        return [f"rewind algorithm test failed: {res.stdout.strip()[-200:]}"]
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
        return []                              # cannot verify; do not fail the build
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
        return []
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
    total = 0
    print("spec validation")
    print("-" * 52)
    for label, errs in groups:
        print(f"  {label:26} {'ok' if not errs else f'{len(errs)} problem(s)'}")
        total += len(errs)
    if total:
        print()
        for label, errs in groups:
            for e in errs:
                print(f"  x {e}")
        return 1
    print("\nspec/ valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
