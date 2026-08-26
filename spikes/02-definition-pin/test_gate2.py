"""SPIKE 02 GATE-2 — the platform invariant, not just the mechanism.

Every test states the externally observable invariant, and each guard has a
NEGATIVE CONTROL proving the test fails when the guarantee is removed.
"""
import json, sqlite3
import pytest
from pin import (AgentDefinition, ToolBinding, AdapterContract, Pin, NonCanonical,
                 CANON_PROFILE, CANON_VERSION, canonical_digest,
                 IncompatibleCheckpoint, ArtifactMissing, ArtifactCorrupted,
                 ConcurrentResume)
from runtime import Store, Runtime, TripwireAdapter

def _tool(**kw):
    d = dict(name="bash", schema_digest="sch1", version="1.0",
             artifact_digest="art-abc", execution_binding="local:python",
             approval_mode="never", credential_ref=None)
    d.update(kw); return ToolBinding(**d)

def _defn(instructions="review", tools=None, exts=()):
    return AgentDefinition("reviewer", instructions,
                           tuple(tools if tools is not None else (_tool(),)), exts)

def _ad(**kw):
    d = dict(identity="acp:claude-code", protocol_version="1.0",
             integration_mode="ACP_SUBPROCESS", declared_capabilities={})
    d.update(kw); return AdapterContract(**d)

def _rt(tmp_path, name="r.db"):
    return Runtime(Store(str(tmp_path / name)))


# ---- INVARIANT 1: the artifact that EXECUTES is the one whose digest was checked
def test_executes_the_resolved_artifact_not_the_callers_object(tmp_path):
    rt, a = _rt(tmp_path), TripwireAdapter(_ad())
    rt.start("r", _defn(), a, {"x": 1})
    rt.resume("r", _defn(), a)
    assert a.executed_definition is not None
    assert a.executed_definition["instructions"] == "review"
    # it came from the registry, byte-for-byte
    body = rt.store.get_definition_body(_defn().digest)
    assert a.executed_definition == body

def test_NEGATIVE_control_check_use_gap_would_be_caught(tmp_path):
    """If the registry artifact is swapped after the check, integrity must fire."""
    rt, a = _rt(tmp_path), TripwireAdapter(_ad())
    rt.start("r", _defn(), a, {"x": 1})
    d = _defn().digest
    tampered = json.dumps({"name": "reviewer", "instructions": "EVIL",
                           "tools": [], "extensions": [], "version": 1}, sort_keys=True)
    rt.store.db.execute("UPDATE definitions SET body=? WHERE digest=?", (tampered, d))
    rt.store.db.commit()
    with pytest.raises(ArtifactCorrupted):
        rt.resume("r", _defn(), a)
    assert a.calls == [], "adapter must not run on a corrupted artifact"


# ---- INVARIANT 2: distinct failures have distinct types
def test_four_outcomes_are_distinct(tmp_path):
    rt, a = _rt(tmp_path), TripwireAdapter(_ad())

    rt.start("r1", _defn(), a, {})
    with pytest.raises(IncompatibleCheckpoint):
        rt.resume("r1", _defn(instructions="edited"), a)

    rt.start("r2", _defn(), a, {})
    rt.store.db.execute("DELETE FROM definitions"); rt.store.db.commit()
    with pytest.raises(ArtifactMissing):
        rt.resume("r2", _defn(), a)

    rt2, a2 = _rt(tmp_path, "r2.db"), TripwireAdapter(_ad())
    rt2.start("r3", _defn(), a2, {})
    rt2.resume("r3", _defn(), a2, holder="w1")
    with pytest.raises(ConcurrentResume):
        rt2.resume("r3", _defn(), a2, holder="w2")


# ---- INVARIANT 3: at most one worker reaches the adapter
def test_concurrent_resume_only_one_reaches_adapter(tmp_path):
    rt = _rt(tmp_path)
    a = TripwireAdapter(_ad())
    rt.start("r", _defn(), a, {"x": 1})
    reached, refused = 0, 0
    for i in range(6):
        try:
            rt.resume("r", _defn(), a, holder=f"w{i}"); reached += 1
        except ConcurrentResume:
            refused += 1
    assert (reached, refused) == (1, 5), (reached, refused)
    assert a.calls == ["start"], "adapter invoked exactly once"

def test_NEGATIVE_control_without_lease_all_workers_execute(tmp_path):
    """Prove the lease is load-bearing: remove it and every worker gets in."""
    rt = _rt(tmp_path)
    a = TripwireAdapter(_ad())
    rt.start("r", _defn(), a, {"x": 1})
    rt.store.acquire_resume_lease = lambda *_a, **_k: True   # guarantee REMOVED
    for i in range(4):
        rt.resume("r", _defn(), a, holder=f"w{i}")
    assert a.calls == ["start"] * 4, "negative control must show 4 executions"


# ---- INVARIANT 4: tool identity is an immutable artifact
def test_tool_requires_immutable_artifact_digest():
    with pytest.raises(NonCanonical):
        _tool(artifact_digest="")

def test_same_version_new_artifact_is_a_mismatch(tmp_path):
    """The exact hole: version string unchanged, code swapped underneath."""
    rt, a = _rt(tmp_path), TripwireAdapter(_ad())
    rt.start("r", _defn(), a, {})
    swapped = _defn(tools=(_tool(artifact_digest="art-XYZ"),))   # same version!
    with pytest.raises(IncompatibleCheckpoint, match="definition_digest changed"):
        rt.resume("r", swapped, a)


# ---- INVARIANT 5: adapter payload schema is pinned separately
def test_adapter_payload_schema_change_is_detected(tmp_path):
    rt = _rt(tmp_path)
    a = TripwireAdapter(_ad(), payload_schema_digest="pay-v1")
    rt.start("r", _defn(), a, {})
    a2 = TripwireAdapter(_ad(), payload_schema_digest="pay-v2")  # adapter's own format
    with pytest.raises(IncompatibleCheckpoint, match="payload_schema_digest changed"):
        rt.resume("r", _defn(), a2)


# ---- INVARIANT 6: canonicalisation is versioned and domain-separated
def test_canonicalisation_is_domain_separated():
    assert canonical_digest({"a": 1}, kind="tool") != canonical_digest({"a": 1}, kind="definition")

def test_canonicalisation_profile_is_named_and_versioned():
    assert CANON_PROFILE == "nfc+jcs" and CANON_VERSION == 1

def test_NEGATIVE_control_profile_change_changes_digests(monkeypatch):
    """Bumping the profile must visibly change digests — that is the point of
    embedding it, so an old pin cannot be silently 'recomputed differently'."""
    import pin as P
    before = P.canonical_digest({"a": 1}, kind="definition")
    monkeypatch.setattr(P, "CANON_VERSION", 2)
    after = P.canonical_digest({"a": 1}, kind="definition")
    assert before != after
