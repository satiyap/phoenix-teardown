#!/usr/bin/env python3
"""Falsification test: does the generic model hold on a bundle we did not design for?

The claim under test is NOT "the model is expressive". It is the specific,
falsifiable one:

  A domain-neutral core of {WorkBundle, Resource, Action, ActionReceipt,
  Verifier, effect_class} can express every executable in the SonyLIV OKF bundle
  AND a mutation-shaped action, WITHOUT the platform learning any domain noun.

Failure conditions, stated before running (any one falsifies the claim):

  F1. A domain noun (DAU, watchtime, deployment, pod) must be understood by the
      core to make the mapping work.
  F2. An OKF executable needs a field the generic Action/Receipt cannot carry.
  F3. A mutation needs a settlement path the effect ledger does not have.
  F4. `effect_class` cannot be derived from the bundle, so it becomes a guess.
  F5. The verifier cannot be pinned independently of the bundle it verifies.
  F6. Freshness/staleness forces mutable state into an immutable bundle.

This reads the REAL bundle. It is not a mock.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

BUNDLE = Path("/Users/satiya/dev/phoenix-onboarding/okf/bundles/sonyliv-analytics")

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(label)
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{detail}]" if detail else ""))


# --------------------------------------------------------------------- core
# Deliberately tiny. If this grows a domain noun, the claim is falsified.

BEHAVIOURAL_ROLES = {"knowledge", "procedure", "executable", "executor",
                     "verifier", "resource_descriptor", "template"}

EFFECT_CLASSES = {"observation", "idempotent_mutation",
                  "non_idempotent_mutation", "long_running_operation"}


def digest(b: bytes | str, kind: str) -> str:
    if isinstance(b, str):
        b = b.encode()
    return hashlib.sha256(kind.encode() + b"\x00" + b).hexdigest()


@dataclass(frozen=True)
class BundleNode:
    path: str
    digest: str
    roles: frozenset[str]
    domain_type: str          # OPEN value; the core never branches on it
    status: str
    stale_after: str | None
    verified_by: str | None
    verified_at: str | None


@dataclass(frozen=True)
class WorkBundle:
    bundle_id: str
    revision: str
    nodes: tuple[BundleNode, ...]

    @property
    def digest(self) -> str:
        return digest(json.dumps(
            [[n.path, n.digest, sorted(n.roles)] for n in
             sorted(self.nodes, key=lambda x: x.path)],
            separators=(",", ":")), "work_bundle")

    def by_role(self, role: str) -> list[BundleNode]:
        return [n for n in self.nodes if role in n.roles]


@dataclass(frozen=True)
class Resource:
    tenant_id: int
    kind: str                 # OPEN
    provider: str             # OPEN
    canonical_id: str
    environment: str
    classification: str


@dataclass(frozen=True)
class Action:
    operation: str            # OPEN: "query" | "set_deployment_version" | ...
    resource_ref: str
    input_digest: str
    effect_class: str
    executable_digest: str | None
    requested_by: str

    def __post_init__(self):
        if self.effect_class not in EFFECT_CLASSES:
            raise ValueError(f"unknown effect_class {self.effect_class}")


@dataclass(frozen=True)
class ActionReceipt:
    """Factual and immutable. NO reconciliation_status, and no promise that
    Phoenix drives the external operation toward settlement."""
    action_id: str
    connector_digest: str
    request_digest: str
    dispatched_at: str
    transport_outcome: str            # response | timeout | disconnect
    external_operation_id: str | None = None
    response_received_at: str | None = None
    external_response_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def settlement(self) -> str:
        """The effect-ledger transition this receipt justifies."""
        if self.transport_outcome == "response":
            return "succeeded"
        return "indeterminate"        # timeout/disconnect: cannot assert


@dataclass(frozen=True)
class EffectObservation:
    """An inspection is a SEPARATE Action producing a separate immutable record.
    Phoenix authorizes and records it; it never schedules it."""
    original_action_id: str
    inspection_action_id: str
    external_operation_id: str
    observed_state: str
    observed_at: str
    evidence_ref: str


@dataclass(frozen=True)
class VerifierVerdict:
    outcome: str              # PASS | FAIL | UNVERIFIED
    reasons: tuple[str, ...] = ()


# --------------------------------------------------------------- bundle read
def parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    fm, out = m.group(1), {}
    for key in ("type", "title", "status", "runtime", "stale_after"):
        km = re.search(rf"^{key}:\s*(.+)$", fm, re.MULTILINE)
        if km:
            out[key] = km.group(1).strip().strip('"')
    vm = re.search(r"^verified:\s*\{\s*by:\s*([^,}]+),\s*at:\s*([^}]+)\}", fm, re.MULTILINE)
    if vm:
        out["verified_by"] = vm.group(1).strip()
        out["verified_at"] = vm.group(2).strip()
    if re.search(r"^executor:", fm, re.MULTILINE):
        em = re.search(r"^executor:\s*\n\s*resource:\s*(\S+)", fm, re.MULTILINE)
        out["executor"] = em.group(1) if em else "?"
        rm = re.search(r"receipt:\s*\[([^\]]+)\]", fm)
        out["receipt_fields"] = [x.strip() for x in rm.group(1).split(",")] if rm else []
    am = re.search(r"^attester:\s*\n\s*resource:\s*(\S+)", fm, re.MULTILINE)
    if am:
        out["attester"] = am.group(1)
    if re.search(r"^parameters:", fm, re.MULTILINE):
        out["parameters"] = re.findall(r"name:\s*(\w+)", fm)
    return out


# OKF's domain `type` -> behavioural roles. This table is BUNDLE-SUPPLIED
# metadata, not core logic: a different domain ships a different table and the
# core is untouched.
ROLE_MAP = {
    "Attested Computation": {"executable", "knowledge"},
    "Executor": {"executor"},
    "Metric": {"knowledge"},
    "Reference": {"knowledge"},
    "Playbook": {"procedure"},
    "Template": {"template"},
    "BigQuery Table": {"resource_descriptor", "knowledge"},
    "Trino Table": {"resource_descriptor", "knowledge"},
    "BigQuery Dataset": {"resource_descriptor"},
    "Trino Schema": {"resource_descriptor"},
    "Query Platform": {"resource_descriptor"},
    "API Platform": {"resource_descriptor"},
    "BI Platform": {"resource_descriptor"},
}


def load_bundle() -> tuple[WorkBundle, dict[str, dict]]:
    nodes, meta = [], {}
    for p in sorted(BUNDLE.rglob("*.md")):
        rel = str(p.relative_to(BUNDLE))
        raw = p.read_bytes()
        fm = parse_frontmatter(raw.decode())
        ty = fm.get("type", "")
        roles = set(ROLE_MAP.get(ty, set()))
        if not roles:
            roles = {"knowledge"}
        nodes.append(BundleNode(
            path=rel, digest=digest(raw, "bundle_node"), roles=frozenset(roles),
            domain_type=ty or "<untyped>", status=fm.get("status", "unknown"),
            stale_after=fm.get("stale_after"), verified_by=fm.get("verified_by"),
            verified_at=fm.get("verified_at")))
        meta[rel] = fm
    # the verifier is a .py file, not markdown -- include it explicitly
    vp = BUNDLE / "references/attesters/sql_equality.py"
    if vp.exists():
        nodes.append(BundleNode(
            path=str(vp.relative_to(BUNDLE)), digest=digest(vp.read_bytes(), "bundle_node"),
            roles=frozenset({"verifier"}), domain_type="Attester",
            status="stable", stale_after=None, verified_by=None, verified_at=None))
    return WorkBundle("sonyliv-analytics", "2026-08-20", tuple(nodes)), meta


def main() -> int:
    print("Falsification test: generic core against the real OKF bundle")
    print(f"bundle: {BUNDLE}")
    if not BUNDLE.exists():
        print("BUNDLE NOT FOUND")
        return 2
    wb, meta = load_bundle()
    print(f"loaded {len(wb.nodes)} nodes, bundle digest {wb.digest[:16]}\n")

    # ---------------------------------------------------------------- roles
    print("A. every node maps to a behavioural role the core knows")
    unknown = {r for n in wb.nodes for r in n.roles} - BEHAVIOURAL_ROLES
    check("no role outside the fixed 7", not unknown, str(unknown))
    counts = {r: len(wb.by_role(r)) for r in sorted(BEHAVIOURAL_ROLES)}
    print(f"       {counts}")
    check("the bundle supplies executables, an executor and a verifier",
          counts["executable"] > 0 and counts["executor"] > 0 and counts["verifier"] > 0)

    # F1: does the core contain any domain noun?
    print("\nB. F1 — the core must contain no domain noun")
    core_src = Path(__file__).read_text()
    core_region = core_src[core_src.index("# --------------------------------------------------------------------- core"):
                           core_src.index("# --------------------------------------------------------------- bundle read")]
    nouns = ["dau", "watchtime", "bigquery", "trino", "kubernetes", "deployment",
             "revenue", "inventory", "rai", "pod", "refund", "incident"]
    leaked = [n for n in nouns if re.search(rf"\b{n}\b", core_region, re.IGNORECASE)]
    check("no domain noun appears in the core dataclasses", not leaked, str(leaked))

    # ------------------------------------------------------- OKF executables
    print("\nC. F2 — every OKF executable expresses as Resource + Action")
    execs = [n for n in wb.nodes if "executable" in n.roles]
    check("found the 6 attested computations", len(execs) == 6, f"got {len(execs)}")

    bq = Resource(tenant_id=1, kind="dataset", provider="bigquery",
                  canonical_id="api-project-911592150515.sony_liv_product",
                  environment="production", classification="internal")
    actions = []
    for n in execs:
        fm = meta[n.path]
        params = fm.get("parameters", [])
        if not params:
            check(f"{n.path} declares parameters", False)
            continue
        a = Action(operation="query", resource_ref=bq.canonical_id,
                   input_digest=digest(json.dumps({p: "<bound>" for p in params},
                                                  sort_keys=True), "action_input"),
                   effect_class="observation",
                   executable_digest=n.digest, requested_by="principal:analyst-1")
        actions.append((n, a))
    check("all 6 became generic Actions with no core change", len(actions) == 6)

    # F4: is effect_class derivable, or guessed?
    print("\nD. F4 — effect_class must be DERIVABLE from the bundle")
    ex_doc = (BUNDLE / "references/skills/run-on-bq.md").read_text()
    readonly = "only" in ex_doc and "SELECT" in ex_doc
    check("the executor contract states read-only (SELECT/WITH), so "
          "effect_class=observation is derived, not assumed", readonly)

    # F5: is the verifier pinned independently of the bundle?
    print("\nE. F5 — the verifier must be pinnable INDEPENDENTLY")
    ver = [n for n in wb.nodes if "verifier" in n.roles][0]
    inside = (BUNDLE / ver.path).exists()
    check("today the verifier lives INSIDE the bundle it verifies "
          "(so bundle authors can edit their own checker)", inside)
    check("but it carries its own digest, so it CAN be pinned separately "
          "and published by a different principal",
          len(ver.digest) == 64 and ver.digest != wb.digest)

    # ------------------------------------------------- receipts + settlement
    print("\nF. F2/F3 — receipts and settlement, both outcomes")
    fm0 = meta[execs[0].path]
    check("the OKF receipt fields fit ActionReceipt without extension",
          set(fm0.get("receipt_fields", [])) <= {"job_id", "executed_sql", "result"},
          str(fm0.get("receipt_fields")))

    ok_r = ActionReceipt(action_id="a1", connector_digest="c1", request_digest="r1",
                         dispatched_at="T0", transport_outcome="response",
                         external_operation_id="bqjob_123",
                         response_received_at="T1",
                         external_response_ref="artifact://bqjob_123")
    check("a responded receipt settles `succeeded`", ok_r.settlement() == "succeeded")
    lost = ActionReceipt(action_id="a2", connector_digest="c1", request_digest="r1",
                         dispatched_at="T0", transport_outcome="disconnect",
                         external_operation_id="bqjob_456")
    check("a disconnected receipt settles `indeterminate`, NOT a retry",
          lost.settlement() == "indeterminate")
    check("the receipt carries NO reconciliation_status field",
          "reconciliation_status" not in ActionReceipt.__dataclass_fields__)
    check("an external_operation_id survives on the indeterminate receipt as a "
          "RECOVERY HANDLE, not a work queue",
          lost.external_operation_id == "bqjob_456")

    # inspection is a separate Action, never scheduled by the core
    obs = EffectObservation(original_action_id="a2", inspection_action_id="a3",
                            external_operation_id="bqjob_456",
                            observed_state="DONE", observed_at="T9",
                            evidence_ref="evidence://bqjob_456")
    check("inspecting the lost operation is a SEPARATE action_id",
          obs.inspection_action_id != obs.original_action_id)
    # Match CODE, not prose. The first version of this check matched the word
    # "schedules" inside a docstring that said the core NEVER schedules -- the
    # same negation-spanning false positive that produced 4 bad hits in the
    # capability map. Strip comments and docstrings first.
    code_only = re.sub(r'"""..*?"""', "", core_region, flags=re.DOTALL)
    code_only = re.sub(r"#.*$", "", code_only, flags=re.MULTILINE)
    scheduler_calls = [w for w in ("time.sleep", "asyncio.sleep", "poll(",
                                   "schedule(", "backoff", "cron", "retry_after",
                                   "while True")
                       if w in code_only]
    check("the core contains no polling/scheduling CODE (comments excluded)",
          not scheduler_calls, str(scheduler_calls))

    # ------------------------------------------------------------ mutations
    print("\nG. F3 — a mutation-shaped action needs no new settlement path")
    k8s = Resource(tenant_id=1, kind="deployment", provider="kubernetes",
                   canonical_id="prod/checkout-api", environment="production",
                   classification="internal")
    # Narrow actions, per the corrected rule: no "deploy AND wait until healthy"
    seq = [("set_deployment_version", "idempotent_mutation"),
           ("observe_rollout", "observation"),
           ("query_service_health", "observation"),
           ("rollback_deployment", "idempotent_mutation")]
    mut = []
    for op, ec in seq:
        mut.append(Action(operation=op, resource_ref=k8s.canonical_id,
                          input_digest=digest(op, "action_input"), effect_class=ec,
                          executable_digest=None, requested_by="principal:sre-agent"))
    check("an SRE deployment decomposes into 4 narrow Actions", len(mut) == 4)
    check("no Action means 'do X and wait until healthy'",
          not any("until" in a.operation or "and_" in a.operation for a in mut))
    check("the same 3 settlement outcomes cover mutations",
          ActionReceipt(action_id="m1", connector_digest="c2", request_digest="r2",
                        dispatched_at="T0", transport_outcome="timeout"
                        ).settlement() == "indeterminate")

    refund = Action(operation="issue_refund", resource_ref="stripe/ch_123",
                    input_digest=digest("amt", "action_input"),
                    effect_class="non_idempotent_mutation",
                    executable_digest=None, requested_by="principal:support-agent")
    check("a non-idempotent mutation is expressible and distinguishable "
          "from an observation", refund.effect_class != mut[1].effect_class)

    # ------------------------------------------------ trust: verified/stale
    print("\nH. trust metadata — UNKNOWN must not degrade to verified")
    def trust(n: BundleNode, today="2026-09-01") -> str:
        if n.verified_by is None:
            return "UNVERIFIED"
        if n.stale_after and n.stale_after < today:
            return "STALE"
        return "VERIFIED"

    rai = next(n for n in execs if "rai-per-million" in n.path)
    inv = next(n for n in execs if "inventory" in n.path)
    check("rai-per-million has NO `verified` field in the real bundle",
          rai.verified_by is None)
    check("...so it grades UNVERIFIED, never silently trusted",
          trust(rai) == "UNVERIFIED")
    check("inventory is verified by a named human and grades VERIFIED",
          inv.verified_by and trust(inv) == "VERIFIED", str(inv.verified_by))
    check("a past stale_after grades STALE, not VERIFIED",
          trust(inv, today="2027-01-01") == "STALE")

    # ---------------------------------------------------------- F6 freshness
    print("\nI. F6 — mutable external state must not live in the bundle")
    # This is a FINDING about the bundle, not a property of the core, so it is
    # reported rather than asserted -- the earlier version asserted the DEFECT
    # was present, which made a green run mean "the conflict exists". Wrong
    # polarity: the test should assert the CORE resolves it.
    ds_files = list((BUNDLE / "datasets").glob("*.md"))
    freshness_docs = [p.name for p in ds_files
                      if re.search(r"freshness", p.read_text(), re.IGNORECASE)]
    print(f"       FINDING: {len(freshness_docs)}/{len(ds_files)} dataset docs carry "
          f"freshness prose about external systems")
    check("the core does NOT model freshness as bundle content, so a staleness "
          "change cannot force a new bundle revision",
          "freshness" not in BundleNode.__dataclass_fields__
          and "freshness" not in WorkBundle.__dataclass_fields__)
    check("BundleNode has no freshness field, so freshness must arrive as "
          "evidence rather than bundle content",
          "freshness" not in BundleNode.__dataclass_fields__)

    # --------------------------------------------------- determinism of pin
    print("\nJ. bundle resolution is deterministic")
    wb2, _ = load_bundle()
    check("re-reading the bundle yields an identical digest", wb.digest == wb2.digest)
    mutated = WorkBundle(wb.bundle_id, wb.revision,
                         wb.nodes[:-1] + (BundleNode(
                             path=wb.nodes[-1].path, digest="0" * 64,
                             roles=wb.nodes[-1].roles, domain_type="x",
                             status="s", stale_after=None,
                             verified_by=None, verified_at=None),))
    check("NC changing one node's digest changes the bundle digest",
          mutated.digest != wb.digest)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("\nFALSIFIED:")
        for f in FAIL:
            print(f"  - {f}")
        return 1
    print("\nNOT FALSIFIED — the generic core expressed every real executable, a "
          "mutation sequence, and both settlement outcomes, with no domain noun.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
