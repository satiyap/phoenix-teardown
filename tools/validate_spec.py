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
    """Run BOTH canonicalisers and compare all three pairings.

    Review finding: the gate ran the JS oracle against the fixture but never
    invoked the Python implementation, so `make spec` alone did not establish
    "two implementations agree". The three comparisons are now explicit:

        fixture <-> Python        (the fixture is not stale)
        fixture <-> JavaScript    (a second language reproduces it)
        Python  <-> JavaScript    (they agree with each other, not just the file)

    The third is not implied by the first two only when a digest is missing from
    one side, but stating it keeps the claim honest and catches partial runs.
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

    # every distinct failure MODE must be represented, not just a count
    codes = {r.get("code") for r in fx.get("reject", [])}
    for required in ("non_integral_float", "integer_out_of_range", "non_finite",
                     "nfc_key_collision", "lone_surrogate"):
        if required not in codes:
            errs.append(f"fixture has no `{required}` rejection case")
    # both non-finite values, not the same one twice
    nonfinite = {json.dumps(r["case"]) for r in fx.get("reject", [])
                 if r.get("code") == "non_finite"}
    kinds = set()
    for c in nonfinite:
        if '"nan"' in c:
            kinds.add("nan")
        if '"inf"' in c:
            kinds.add("inf")
    if kinds != {"nan", "inf"}:
        errs.append(f"non_finite cases cover {sorted(kinds) or 'nothing'}; both NaN and "
                    f"Infinity must be present (an earlier fixture had Infinity twice "
                    f"and no NaN)")

    spike_fx = PIN / "canon_vectors.json"
    if spike_fx.exists() and spike_fx.read_text() != raw:
        errs.append("spec/canon_vectors.json and the spike fixture have diverged")

    # ---- comparison 1: fixture <-> Python
    py = PIN / ".venv" / "bin" / "python"
    py_exe = str(py) if py.exists() else sys.executable
    py_digests: dict[str, str] = {}
    runner = PIN / "verify_vectors.py"
    if not runner.exists():
        errs.append("spikes/02-definition-pin/verify_vectors.py missing")
    else:
        res = subprocess.run([py_exe, str(runner), str(fx_path)],
                             capture_output=True, text=True, cwd=str(PIN))
        if res.returncode != 0:
            for ln in (res.stdout + res.stderr).strip().splitlines():
                if ln.strip():
                    errs.append(f"python canonicaliser: {ln.strip()}")
        else:
            try:
                py_digests = json.loads(res.stdout)["digests"]
            except Exception:                                    # noqa: BLE001
                errs.append("python canonicaliser produced unreadable output")

    # ---- comparison 2: fixture <-> JavaScript
    oracle = PIN / "canon_ref.mjs"
    node = shutil.which("node")
    js_digests: dict[str, str] = {}
    if not oracle.exists():
        errs.append("canon_ref.mjs missing — no independent oracle for the vectors")
    elif node is None:
        errs.append("node is not installed, so the canonicalisation vectors cannot be "
                    "verified against an independent implementation. Install node or "
                    "run with SPEC_ALLOW_UNVERIFIED=1 to downgrade this to a warning.")
    else:
        res = subprocess.run([node, str(oracle), str(fx_path), "--json"],
                             capture_output=True, text=True, cwd=str(PIN))
        if res.returncode != 0:
            for ln in (res.stdout + res.stderr).strip().splitlines():
                if ln.strip() and not ln.startswith("{"):
                    errs.append(f"independent oracle disagrees: {ln.strip()}")
        else:
            for ln in res.stdout.splitlines():
                if ln.startswith("{"):
                    try:
                        js_digests = json.loads(ln)["digests"]
                    except Exception:                            # noqa: BLE001
                        pass

    # ---- comparison 3: Python <-> JavaScript, directly
    if py_digests and js_digests:
        for n in sorted(set(py_digests) | set(js_digests), key=lambda x: int(x)):
            a, b = py_digests.get(n), js_digests.get(n)
            if a != b:
                errs.append(f"vector #{n}: python {str(a)[:12]} != javascript "
                            f"{str(b)[:12]}")
    elif not errs:
        errs.append("could not compare the two implementations directly")

    # ---- the fixture's own declared relations
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
    """Compare OPERATIONS, security, states and schemas — not just path strings.

    Review finding: "the validator compares only path strings, not HTTP verbs,
    parameters, security, schemas or response codes. A GET changed to POST would
    still pass." Each check below closes one of those.
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

    errs: list[str] = []
    md = (SPEC / "06-api.md").read_text()
    VERBS = ("get", "post", "patch", "put", "delete")

    # --- 1. operations must match, VERB INCLUDED
    documented = set()
    for verb, path in re.findall(r"^(POST|GET|PATCH|PUT|DELETE)\s+(/v1/\S+)", md,
                                re.MULTILINE):
        documented.add((verb.lower(), path.split("?")[0].rstrip(",.")))
    declared = {(m, path) for path, item in doc.get("paths", {}).items()
                for m in item if m in VERBS}
    for verb, path in sorted(documented - declared):
        errs.append(f"06-api.md documents {verb.upper()} {path}; openapi.yaml lacks it")
    for verb, path in sorted(declared - documented):
        errs.append(f"openapi.yaml declares {verb.upper()} {path}; 06-api.md lacks it")

    # --- 2. the run-state enum must match 05 exactly
    sm = (SPEC / "05-state-machine.md").read_text()
    md_states = set(re.findall(r"^\| `([a-z_]+)`", sm, re.MULTILINE))
    md_states |= {s for grp in re.findall(r"^\| ((?:`[a-z_]+` / )+`[a-z_]+`)", sm,
                                          re.MULTILINE)
                  for s in re.findall(r"`([a-z_]+)`", grp)}
    schema_states = set(
        doc.get("components", {}).get("schemas", {}).get("RunState", {}).get("enum", []))
    if schema_states:
        for missing in sorted(md_states - schema_states):
            errs.append(f"RunState enum omits `{missing}` which 05 defines")
        for extra in sorted(schema_states - md_states):
            errs.append(f"RunState enum has `{extra}` which 05 does not define")
    else:
        errs.append("openapi.yaml has no RunState enum to compare")

    # --- 3. credential CLASSES must be the ones 06 defines
    md_classes = set()
    for name in re.findall(r"^\| \*\*(\w+)\*\* \|", md, re.MULTILINE):
        md_classes.add(name.lower())
    declared_schemes = {k.lower().replace("token", "")
                        for k in doc.get("components", {})
                                    .get("securitySchemes", {})}
    for cls in sorted(md_classes - declared_schemes):
        errs.append(f"06-api.md defines credential class `{cls}` with no matching "
                    f"securityScheme")

    # --- 4. admin-only sections must be secured as admin
    admin_paths = set()
    for m in re.finditer(r"### (\w[\w ]*) — admin only(.*?)(?=\n### |\n## |\Z)",
                         md, re.DOTALL):
        for verb, path in re.findall(r"^(POST|GET|PATCH|PUT|DELETE)\s+(/v1/\S+)",
                                    m.group(2), re.MULTILINE):
            admin_paths.add((verb.lower(), path.split("?")[0].rstrip(",.")))
    for verb, path in sorted(admin_paths):
        op = doc.get("paths", {}).get(path, {}).get(verb)
        if not isinstance(op, dict):
            continue
        schemes = {k for entry in op.get("security", []) for k in entry}
        if "adminToken" not in schemes:
            errs.append(f"{verb.upper()} {path} is admin-only in 06-api.md but "
                        f"openapi.yaml does not require adminToken")

    # --- 5. required Idempotency-Key must be required
    idem_required = set()
    m = re.search(r"`Idempotency-Key` is \*\*required\*\* on (.*?)[,.]", md, re.DOTALL)
    if m:
        for verb, path in re.findall(r"(POST|GET|PATCH)\s+(/v1/\S+)", m.group(1)):
            idem_required.add((verb.lower(), path.rstrip(",.")))
    for verb, path in sorted(idem_required):
        op = doc.get("paths", {}).get(path, {}).get(verb)
        if not isinstance(op, dict):
            errs.append(f"{verb.upper()} {path} requires Idempotency-Key but is not "
                        f"in openapi.yaml")
            continue
        params = op.get("parameters", [])
        names = []
        for prm in params:
            ref = prm.get("$ref", "")
            if ref:
                names.append(ref.rsplit("/", 1)[-1])
            elif prm.get("name") == "Idempotency-Key":
                names.append("required" if prm.get("required") else "optional")
        if not any("Required" in n or n == "required" for n in names):
            errs.append(f"{verb.upper()} {path} must REQUIRE Idempotency-Key "
                        f"(06-api.md), but openapi.yaml does not")

    # --- 5b. an operation 06 marks admin-only must not be reachable by an agent token
    for verb, path in sorted(admin_paths):
        op = doc.get("paths", {}).get(path, {}).get(verb)
        if not isinstance(op, dict):
            continue
        schemes = {k for entry in op.get("security", []) for k in entry}
        if "agentToken" in schemes or (not schemes and "agentToken" in
                                      {k for e in doc.get("security", []) for k in e}):
            errs.append(f"{verb.upper()} {path} is admin-only in 06-api.md but inherits "
                        f"or declares agentToken, so an agent credential could reach it")

    # Deciding an approval is not an "admin-only section" in 06, but D-A forbids an
    # agent token, so it needs the same treatment stated explicitly.
    decide = doc.get("paths", {}).get("/v1/approvals/{id}/decide", {}).get("post")
    if isinstance(decide, dict):
        schemes = {k for entry in decide.get("security", []) for k in entry}
        if not schemes:
            errs.append("POST /v1/approvals/{id}/decide inherits the global security "
                        "(agentToken); D-A requires an explicit non-agent requirement")
        elif "agentToken" in schemes:
            errs.append("POST /v1/approvals/{id}/decide accepts agentToken; agents do "
                        "not decide approvals in v0.1 (D-A)")

    # --- 6. no operation may be schema-less
    for path, item in doc.get("paths", {}).items():
        for verb, op in item.items():
            if verb not in VERBS or not isinstance(op, dict):
                continue
            if not op.get("operationId"):
                errs.append(f"{verb.upper()} {path} has no operationId")
            success = [c for c in op.get("responses", {}) if c.startswith("2")]
            if not success:
                errs.append(f"{verb.upper()} {path} declares no 2xx response")
            for code in success:
                body = op["responses"][code]
                if isinstance(body, dict) and "$ref" not in body \
                        and "content" not in body and code != "204":
                    errs.append(f"{verb.upper()} {path} {code} has no response schema")

    # --- 7. tool/extension bindings must carry the canonicalisation requirements
    schemas = doc.get("components", {}).get("schemas", {})
    tb = schemas.get("ToolBinding", {})
    if "artifact_digest" not in tb.get("required", []):
        errs.append("ToolBinding does not require artifact_digest, so a version string "
                    "could pin mutable code")
    eb = schemas.get("ExtensionBinding", {})
    if "artifact_digest" not in eb.get("required", []):
        errs.append("ExtensionBinding does not require artifact_digest")
    defn = schemas.get("Definition", {}).get("properties", {})
    if defn.get("extensions", {}).get("type") != "array":
        errs.append("Definition.extensions must be an ORDERED array of bindings")
    return errs


def check_effect_lifecycle() -> list[str]:
    """The intent->approval->claim->dispatch->settle protocol, plus its DDL.

    Review: "when is the effect claimed relative to human approval?" was
    undefined, and claiming first makes a slow human produce `indeterminate`.
    """
    errs: list[str] = []
    sc = (SPEC / "01-schema.md").read_text()
    for needed, why in [
        ("'intended'", "no `intended` status, so an effect must be claimed before "
                       "approval and a slow human produces `indeterminate`"),
        ("'awaiting_approval'", "no `awaiting_approval` status"),
        ("effect_claim_fields_together", "no CHECK keeping lease fields NULL on an "
                                         "unclaimed row"),
    ]:
        if needed not in sc:
            errs.append(f"01-schema.md: {why}")
    if "effect_claim_history" in sc and "earlier draft" not in sc:
        errs.append("01-schema.md: effect_claim_history is defined but effect rows are "
                    "never reclaimed, so monotonic claim tokens describe an impossible "
                    "transition")
    if not re.search(r"FOREIGN KEY \(tenant_id, action_ref, run_id\)", sc):
        errs.append("01-schema.md: approvals.action_ref FK omits run_id, so an approval "
                    "can gate an effect belonging to a different run")

    script = SPEC / "effect_lifecycle_test.py"
    if not script.exists():
        return errs + ["spec/effect_lifecycle_test.py missing"]
    res = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    if res.returncode != 0:
        tail = (res.stdout + res.stderr).strip().splitlines()[-3:]
        errs.append(f"effect lifecycle test failed: {' | '.join(x.strip() for x in tail)}")
    return errs


def _spec_sql_blocks() -> str:
    """Every ```sql fence in spec/01, concatenated in document order.

    Skips fences that are illustrative rather than schema: a fence containing
    INSERT/UPDATE/SELECT-only statements belongs to a worked example, not the DDL.
    """
    body = (SPEC / "01-schema.md").read_text()
    out = []
    for block in re.findall(r"```sql\n(.*?)```", body, re.DOTALL):
        stripped = block.strip()
        if not stripped:
            continue
        if re.match(r"^(INSERT|UPDATE|SELECT|BEGIN|--)\b", stripped, re.IGNORECASE):
            continue
        out.append(block)
    return "\n".join(out)


def _apply_spec_ddl(dsn: str) -> list[str]:
    """Apply spec/01's DDL to a scratch schema and report any SQL error."""
    py = ROOT / ".venv" / "bin" / "python"
    py = py if py.exists() else Path(sys.executable)
    sql = _spec_sql_blocks()
    if not sql.strip():
        return ["no ```sql blocks found in spec/01-schema.md"]
    # Apply inside a UNIQUE schema, in ONE transaction, and ALWAYS roll back.
    #
    # Two earlier designs were destructive, and both were caught by review rather
    # than by me:
    #   1. a fixed `specddl` SCHEMA with `SET search_path` -- dropping it destroyed
    #      the spike's tables, because they had been created under that search_path;
    #   2. a fixed `specddl_check` DATABASE with `DROP DATABASE ... WITH (FORCE)` --
    #      which silently deleted a pre-existing database of that name belonging to
    #      someone else. A verification step must never force-drop a target it did
    #      not create.
    #
    # This design cannot destroy anything: the schema name is unique per run, every
    # object is created inside one transaction, and the transaction is rolled back
    # unconditionally. Nothing is dropped, so there is nothing to drop by mistake.
    # `app_role` is created inside the same transaction, so a role that did not
    # already exist disappears with the rollback.
    script = (
        "import secrets, sys, psycopg\n"
        "dsn, sql = sys.argv[1], sys.stdin.read()\n"
        "schema = 'specddl_' + secrets.token_hex(6)\n"
        "conn = psycopg.connect(dsn)          # NOT autocommit: we need the rollback\n"
        "rc, msg = 0, None\n"
        "try:\n"
        "    cur = conn.cursor()\n"
        "    cur.execute(f'CREATE SCHEMA {schema}')\n"
        "    cur.execute(f'SET LOCAL search_path TO {schema}')\n"
        "    cur.execute(\"SELECT 1 FROM pg_roles WHERE rolname='app_role'\")\n"
        "    if cur.fetchone() is None:\n"
        "        cur.execute('CREATE ROLE app_role NOLOGIN')   # transactional\n"
        "    try:\n"
        "        cur.execute(sql)\n"
        "    except Exception as e:\n"
        "        msg = f'{type(e).__name__}: {e}'.replace(chr(10), ' ')[:300]\n"
        "        rc = 1\n"
        "finally:\n"
        "    conn.rollback()                  # unconditional; drops schema and role\n"
        "    conn.close()\n"
        "if msg:\n"
        "    print(msg)\n"
        "sys.exit(rc)\n"
    )
    res = subprocess.run([str(py), "-c", script, dsn], input=sql,
                         capture_output=True, text=True)
    if res.returncode != 0:
        detail = (res.stdout + res.stderr).strip().splitlines()
        return [f"spec/01-schema.md DDL does not apply to Postgres: "
                f"{detail[0] if detail else 'unknown error'}"]
    return []


def check_postgres_gate() -> list[str]:
    """Run the Postgres scenarios when a server is reachable.

    Skipped-but-reported when it is not: the point of spike 03 is that these
    were previously assumptions, so silence would be the wrong default.
    """
    spike = ROOT / "spikes" / "03-postgres"
    script = spike / "test_postgres.py"
    if not script.exists():
        return ["spikes/03-postgres/test_postgres.py missing"]
    dsn = os.environ.get("PHOENIX_PG_DSN",
                         "postgresql://postgres:spike@127.0.0.1:55433/spike")
    # Fall back to the running interpreter when the repo venv is absent, e.g. when
    # the tool is executed against a copied tree. Hard-coding the venv path made
    # the whole validator crash with FileNotFoundError instead of reporting a
    # single UNVERIFIED check -- found by tools/test_validate_spec.py control 0.
    _venv = ROOT / ".venv" / "bin" / "python"
    py = _venv if _venv.exists() else Path(sys.executable)
    probe = subprocess.run(
        [str(py), "-c",
         "import sys,psycopg\n"
         "try:\n"
         "    psycopg.connect(sys.argv[1], connect_timeout=2).close()\n"
         "except Exception as e:\n"
         "    print(e); sys.exit(1)\n", dsn],
        capture_output=True, text=True)
    if probe.returncode != 0:
        return ["no Postgres reachable, so the eight concurrency scenarios are "
                "UNVERIFIED. See spikes/03-postgres/RESULT.md for the one-line "
                "docker command."]
    # FIRST: apply spec/01's own SQL to the disposable server. The normative DDL
    # carried a missing comma for a full pass (redo 3 -> redo 4) because nothing ever
    # executed it -- only the spike's hand-maintained copy was run. A spec whose
    # schema has never been applied is a schema nobody has checked.
    ddl_errs = _apply_spec_ddl(dsn)
    if ddl_errs:
        return ddl_errs

    res = subprocess.run([str(py), str(script)], capture_output=True, text=True,
                         cwd=str(spike), env={**os.environ, "PHOENIX_PG_DSN": dsn})
    if res.returncode != 0:
        bad = [ln.strip() for ln in res.stdout.splitlines()
               if ln.strip().startswith("FAIL")]
        return [f"postgres gate: {b}" for b in bad] or ["postgres gate failed"]
    return []


def check_references() -> list[str]:
    errs = []
    for f in sorted(SPEC.glob("*.md")):
        for ref in re.findall(r"\]\((\d\d-[a-z0-9-]+\.md)", f.read_text()):
            if not (SPEC / ref).exists():
                errs.append(f"{f.name}: dangling reference to {ref}")
    return errs


def _load_superseded_patterns() -> list[tuple[str, str, str]]:
    """Patterns live in a FILE, not in this source."""
    path = ROOT / "tools" / "superseded-patterns.txt"
    if not path.exists():
        return []
    out = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        out.append((parts[0], parts[1].strip(), parts[2].strip()))
    return out


# A sentence is exempt ONLY with a dated marker AND a retraction verb. Quoting is
# not an exemption: "this once said X" must also say when it stopped being true.
_DATE = re.compile(r"20\d\d-\d\d-\d\d")
_VERB = re.compile(r"superseded|amended|reversed|retracted", re.IGNORECASE)

# Files whose job is to record history or describe OTHER systems. A foreign agent
# named here is a FINDING, not a claim about what we ship, and rewriting a finding
# to match our business model would falsify the study. `projects/` is excluded by
# omission from _scanned_files().
_EXEMPT_FILES = {
    "scope-reconciliation.md",   # the change log: quotes old wording by design
    "recon.md",                  # what each candidate project claimed to be
    "capability-matrix.md",      # generated; probe text names foreign agents
    "capability-map.md",
    "phase2-findings.md",        # dated findings from a point in the study
    "phase3-findings.md",
    "phase3-findings-final.md",
    "licensing.md",
    "build-reuse-map.md",        # records what each project SUPPLIED to us
}


# Frozen 2026-08-27 (Phase 5 artefacts). Excluded from the scan the way `projects/`
# is: both documents were written at a point in the study and are no longer edited,
# so rewriting them to match a later scope would falsify the record. Where they
# disagree with the boundary, v01-boundary.md / scope.yaml wins, which each file now
# says at the top.
_FROZEN_FILES = {
    "reference-architecture.md",
    "exit-criteria.md",
}


def _scanned_files() -> list[Path]:
    """Everything that states what WE build. `projects/` is excluded by omission:
    a teardown describes another system, and its findings must not be rewritten to
    match our business model."""
    files: list[Path] = []
    files += sorted(SPEC.glob("*.md"))
    # The contract files are NOT markdown, and skipping them is how "answer its own
    # approvals" survived in openapi.yaml through three passes of this gate.
    if (SPEC / "contracts").is_dir():
        files += [f for f in sorted((SPEC / "contracts").glob("*"))
                  if f.suffix in {".yaml", ".yml", ".proto", ".json"}]
    files += [f for f in sorted((ROOT / "synthesis").glob("*.md"))
              if f.name not in _FROZEN_FILES]
    files += sorted((ROOT / "decisions").glob("*.md"))
    # The verification rules bind the spec, so a superseded claim in them is a
    # superseded claim in the standard. It was outside the scan until 2026-08-27.
    vr = ROOT / "spikes" / "VERIFICATION-RULES.md"
    if vr.exists():
        files.append(vr)
    for name in ("DESIGN.md", "README.md", "open-questions.md"):
        p = ROOT / name
        if p.exists():
            files.append(p)
    return [f for f in files if f.is_file()]


# Fenced blocks are skipped by the sentence splitter for good reason -- SQL and
# protobuf are not prose -- but `text` diagrams ARE claims: an `Adapter (ACP)` box
# says we ship ACP. Scan those, and leave sql/protobuf/python/bash alone.
_SCANNED_FENCE_LANGS = {"text", "", "http", "yaml"}


def _fence_spans(body: str) -> list[tuple[int, int, bool]]:
    """(start_line, end_line, scan?) for each fenced block, 1-based inclusive."""
    spans, open_at, lang = [], None, ""
    for n, line in enumerate(body.splitlines(), start=1):
        m = re.match(r"^\s*```(\w*)", line)
        if not m:
            continue
        if open_at is None:
            open_at, lang = n, m.group(1).lower()
        else:
            spans.append((open_at, n, lang in _SCANNED_FENCE_LANGS))
            open_at, lang = None, ""
    return spans


def _sentences(body: str) -> list[tuple[int, str]]:
    """Split into sentences, carrying each one's 1-based line number.

    Per-sentence rather than per-line, because a dated amendment three lines below
    a stale claim previously exempted it -- and a table row can hold both a stale
    cell and an amended one.
    """
    out: list[tuple[int, str]] = []
    skip = set()
    for start, end, scan in _fence_spans(body):
        if not scan:
            skip.update(range(start, end + 1))
    for line_no, line in enumerate(body.splitlines(), start=1):
        if line_no in skip:
            continue
        for piece in re.split(r"(?<=\.)\s+|\|", line):
            piece = piece.strip()
            if piece:
                out.append((line_no, piece))
    return out


def check_superseded_claims() -> list[str]:
    """Fail when any document still states a decision that was reversed.

    Rewritten 2026-08-27 after the gate passed on two injected sentences -- "We
    adapt agents supplied by customers." and "Our adapter exposes four methods."
    Three faults: matching was case-sensitive, patterns were applied per LINE with
    a 3-line forgiveness window, and quoting counted as an exemption.
    """
    patterns = _load_superseded_patterns()
    if not patterns:
        return ["tools/superseded-patterns.txt is missing or empty, so the "
                "superseded-claims gate is UNVERIFIED"]

    compiled = []
    errs: list[str] = []
    for pat, date, why in patterns:
        try:
            compiled.append((re.compile(pat, re.IGNORECASE), date, why))
        except re.error as exc:                                  # noqa: BLE001
            errs.append(f"bad pattern {pat!r} in superseded-patterns.txt: {exc}")
    if errs:
        return errs

    for f in _scanned_files():
        if f.name in _EXEMPT_FILES:
            continue
        try:
            body = f.read_text()
        except UnicodeDecodeError:
            continue
        is_sql_ish = f.suffix in {".proto", ".yaml", ".yml"}
        # An ADR evidence log records what ANOTHER project does. "Letta wraps Claude
        # Code" is a finding about Letta and stays true whatever we ship; rewriting
        # it to match our business model would falsify the teardown. Everything from
        # the "## Evidence log" heading onward is evidence, not a claim about us.
        ev_from = None
        if f.parent.name == "decisions":
            m_ev = re.search(r"^## Evidence log", body, re.MULTILINE)
            if m_ev:
                ev_from = body[:m_ev.start()].count("\n") + 1

        for ln_no, sentence in _sentences(body):
            if ev_from is not None and ln_no >= ev_from:
                continue
            if _DATE.search(sentence) and _VERB.search(sentence):
                continue
            # A retained value inside a SQL/enum literal is not a claim: the modes
            # stay in the CHECK so the column never needs a migration, and a
            # separate constraint restricts which one may be used. Recognised by
            # the value being quoted as a literal, not by the file it sits in.
            if re.search(r"'[a-z_]*(acp_subprocess|native_tui|cli_subprocess"
                         r"|native_server)[a-z_]*'", sentence):
                continue
            # NOTE: comments in a contract file are NOT exempt. An earlier version
            # skipped any `#`/`//` line in .yaml/.proto, which is how a mutation
            # reading "# agents answer its own approvals here" passed the gate --
            # and YAML descriptions are mostly comments, so the exemption hid the
            # very class the gate was extended to catch. Only a LICENCE/codegen
            # banner is skipped, matched narrowly.
            if is_sql_ish and re.match(r"^\s*(//|#)\s*(Code generated|Copyright|"
                                       r"SPDX-|DO NOT EDIT)", sentence):
                continue
            for rx, date, why in compiled:
                if rx.search(sentence):
                    snippet = sentence if len(sentence) <= 90 else sentence[:87] + "..."
                    errs.append(f"{f.name}:{ln_no} superseded {date} ({why})\n"
                                f"      -> {snippet}")
                    break
    return errs


def check_counts() -> list[str]:
    """Counts must be READ from the source of truth, never restated.

    Three numbers drifted across three review rounds: the invariant-row count, the
    spike assertion total, and the ADR status split. Each is now asserted against
    the artifact that defines it.
    """
    errs: list[str] = []

    # 1. spec/08 inventory rows vs README's claim
    inv = SPEC / "08-conformance.md"
    readme = ROOT / "README.md"
    if inv.exists() and readme.exists():
        rows = len(re.findall(r"^\| \d+[a-z]? \|", inv.read_text(), re.MULTILINE))
        m = re.search(r"(\d+) required invariant tests", readme.read_text())
        if not m:
            errs.append("README does not state a 'required invariant tests' count")
        elif int(m.group(1)) != rows:
            errs.append(f"README says {m.group(1)} required invariant tests; "
                        f"spec/08-conformance.md has {rows} inventory rows")

    # 2. spike assertion total vs the four RESULT.md headline counts
    totals = {}
    for res in sorted((ROOT / "spikes").glob("*/RESULT.md")):
        body = res.read_text()
        # Each RESULT.md declares its own headline in ONE machine-readable form, so
        # the total is derived rather than restated. Prose counts are not parsed:
        # a spike that mentions "480 passed" from a vendored suite must not have
        # that number swept into our verdict.
        m = re.search(r"\*\*Gate assertions: (\d+)\*\*", body)
        if m:
            totals[res.parent.name] = int(m.group(1))
    if totals and readme.exists():
        want = sum(totals.values())
        m = re.search(r"\*\*(\d+) gate assertions\*\*", readme.read_text())
        if not m:
            errs.append("README does not state a '<n> gate assertions' total")
        elif int(m.group(1)) != want:
            errs.append(f"README says {m.group(1)} gate assertions; the four "
                        f"RESULT.md files sum to {want} ({totals})")

    # 3. ADR status split
    adrs = sorted((ROOT / "decisions").glob("ADR-*.md"))
    if adrs and readme.exists():
        acc = pro = 0
        for a in adrs:
            m = re.search(r"\*\*Status:\*\*\s*\**(\w+)", a.read_text())
            s = (m.group(1).lower() if m else "")
            acc += s == "accepted"
            pro += s == "proposed"
        body = readme.read_text()
        m = re.search(r"(\d+) ADRs \((\d+) Accepted, (\d+) Proposed\)", body)
        if not m:
            errs.append("README does not state the ADR split as "
                        "'<n> ADRs (<a> Accepted, <p> Proposed)'")
        elif (int(m.group(1)), int(m.group(2)), int(m.group(3))) != (len(adrs), acc, pro):
            errs.append(f"README claims {m.group(0)}; decisions/ holds "
                        f"{len(adrs)} ADRs with {acc} Accepted and {pro} Proposed")
    return errs


def _md_rows(body: str, start: str, end: str) -> list[list[str]]:
    """Table rows between two markers, as cell lists. `\\|` is an escaped pipe."""
    i = body.find(start)
    if i < 0:
        return []
    j = body.find(end, i + len(start))
    rows = []
    for line in body[i:(j if j > 0 else len(body))].splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        if not cells or set("".join(cells)) <= set("-: "):
            continue
        rows.append(cells)
    return rows


def _bold(cell: str) -> str:
    m = re.match(r"\*\*(.+?)\*\*", cell)
    return m.group(1) if m else cell


def check_scope_source_of_truth() -> list[str]:
    """The three scope-restating documents must match synthesis/scope.yaml.

    A scope change in August 2026 propagated through eight commits, and the same
    tier list was corrected by hand in four documents. The lists now live in one
    machine-readable file; the markdown is NOT generated from it, it is ASSERTED
    against it, so an edit to either side that is not made to the other fails here.
    """
    src = ROOT / "synthesis" / "scope.yaml"
    if not src.exists():
        return ["synthesis/scope.yaml is missing, so scope is UNVERIFIED"]
    try:
        import yaml
    except ImportError:
        return ["pyyaml is not installed, so scope vs scope.yaml is UNVERIFIED"]
    scope = yaml.safe_load(src.read_text())
    errs: list[str] = []

    def compare(what: str, want: list[str], got: list[str]) -> None:
        if want == got:
            return
        missing = [x for x in want if x not in got]
        extra = [x for x in got if x not in want]
        detail = []
        if missing:
            detail.append(f"in scope.yaml but not in the document: {missing}")
        if extra:
            detail.append(f"in the document but not in scope.yaml: {extra}")
        if not detail:
            detail.append(f"same items, different order: {got}")
        errs.append(f"{what}: " + "; ".join(detail))

    # 1. v01-boundary.md tier / deferred / never tables
    bnd_path = ROOT / "synthesis" / "v01-boundary.md"
    if not bnd_path.exists():
        errs.append("synthesis/v01-boundary.md is missing")
    else:
        bnd = bnd_path.read_text()
        for key, start, end in (("tier1", "### Tier 1", "### Tier 2"),
                                ("tier2", "### Tier 2", "### Tier 3"),
                                ("tier3", "### Tier 3", "## Deferred with intent")):
            want = [f"{e['number']} {e['item']}" for e in scope["tiers"][key]]
            got = [f"{r[0]} {_bold(r[1])}" for r in _md_rows(bnd, start, end)
                   if r[0].isdigit()]
            compare(f"v01-boundary.md {key}", want, got)

        want = [f"{e['item']} -> {e['trigger']}" for e in scope["deferred"]]
        got = [f"{_bold(r[0])} -> {r[2]}"
               for r in _md_rows(bnd, "## Deferred with intent", "## Never")
               if len(r) >= 3 and r[0].startswith("**")]
        compare("v01-boundary.md deferred", want, got)

        want = [f"{e['number']} {e['item']}" for e in scope["never"]]
        got = [f"{r[0]} {_bold(r[1])}"
               for r in _md_rows(bnd, "## Never",
                                 "## What v0.1 explicitly does not guarantee")
               if r[0].isdigit()]
        compare("v01-boundary.md never", want, got)

    # 2. README status counts
    readme = ROOT / "README.md"
    if not readme.exists():
        errs.append("README.md is missing")
    else:
        body = readme.read_text()
        c = scope["counts"]
        adr = c["adr_status"]
        m = re.search(r"(\d+) ADRs \((\d+) Accepted, (\d+) Proposed\)", body)
        if not m:
            errs.append("README states no ADR split to compare with scope.yaml")
        elif [int(x) for x in m.groups()] != [adr["total"], adr["accepted"],
                                              adr["proposed"]]:
            errs.append(f"README says {m.group(0)}; scope.yaml says {adr}")
        for label, pat, want in (
                ("spec_docs", r"\*\*(\d+) documents\*\*", c["spec_docs"]),
                ("invariant_rows", r"(\d+) required invariant tests",
                 c["invariant_rows"]),
                ("spike_assertions", r"\*\*(\d+) gate assertions\*\*",
                 c["spike_assertions"])):
            m = re.search(pat, body)
            if not m:
                errs.append(f"README states no {label} count to compare with scope.yaml")
            elif int(m.group(1)) != want:
                errs.append(f"README says {label}={m.group(1)}; scope.yaml says {want}")

    # 3. spec/00-overview.md "Not yet specified" rows
    ov = SPEC / "00-overview.md"
    if not ov.exists():
        errs.append("spec/00-overview.md is missing")
    else:
        rows = _md_rows(ov.read_text(), "## Not yet specified", "**Sequencing note.**")
        got = [r[0].replace("**", "") for r in rows if r[0] != "Area"]
        compare("spec/00-overview.md owed_specs", list(scope["owed_specs"]), got)

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
        ("effect lifecycle", check_effect_lifecycle()),
        ("postgres gate", check_postgres_gate()),
        ("superseded claims", check_superseded_claims()),
        ("counts vs source of truth", check_counts()),
        ("scope vs source of truth", check_scope_source_of_truth()),
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
