"""SPIKE 02 GATE-2 — the platform invariant, not just the mechanism.

Every test states the externally observable invariant, and each guard has a
NEGATIVE CONTROL proving the test fails when the guarantee is removed.
"""
import json, sqlite3
import pytest
from pin import (
    ExtensionBinding,AgentDefinition, ToolBinding, AdapterContract, Pin, NonCanonical,
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
    assert CANON_PROFILE == "nfc+intjson" and CANON_VERSION == 1

def test_NEGATIVE_control_profile_change_changes_digests(monkeypatch):
    """Bumping the profile must visibly change digests — that is the point of
    embedding it, so an old pin cannot be silently 'recomputed differently'."""
    import pin as P
    before = P.canonical_digest({"a": 1}, kind="definition")
    monkeypatch.setattr(P, "CANON_VERSION", 2)
    after = P.canonical_digest({"a": 1}, kind="definition")
    assert before != after


# ---- INVARIANT 7: number canonicalisation (JCS-derived, honestly scoped)
def test_integral_float_equals_integer():
    """RFC 8785 3.2.2.3 via ECMAScript: 1.0 serialises as 1. Python's json does
    NOT do this, which is why the profile converts integral floats to int."""
    assert canonical_digest({"n": 1.0}, kind="effect_key") == \
           canonical_digest({"n": 1},   kind="effect_key")

def test_negative_zero_equals_zero():
    assert canonical_digest({"n": -0.0}, kind="effect_key") == \
           canonical_digest({"n": 0},    kind="effect_key")

@pytest.mark.parametrize("bad,label", [
    ({"n": 4.5},      "non-integral float"),
    ({"n": 2**53},    "integer beyond 2^53-1"),
])
def test_numbers_outside_the_profile_are_rejected(bad, label):
    """Python's json and ECMAScript disagree on fraction and exponent formatting,
    so rather than mis-serialise silently the profile REJECTS. Loud beats wrong."""
    with pytest.raises(NonCanonical):
        canonical_digest(bad, kind="effect_key")

# Import the ONE substitution implementation rather than keeping a copy. A local
# copy is how this test silently stopped rejecting: the fixture grew surrogate
# placeholders, the copy did not learn them, and the literal dict was digested
# happily instead of being expanded into a lone surrogate.
from verify_vectors import subst as _subst


def _fixture():
    import json, pathlib
    return json.loads(pathlib.Path("canon_vectors.json").read_text())


def test_reference_accept_vectors_reproduce():
    fx = _fixture()
    assert fx["profile"] == f"{CANON_PROFILE}/v{CANON_VERSION}"
    for row in fx["accept"]:
        assert canonical_digest(row["payload"], kind=row["kind"]) == row["digest"], row["n"]


def test_reference_reject_vectors_actually_reject():
    """Review found this loop was literally `pass`.

    A fixture that lists rejections without attempting them is decoration. Each
    case must raise, and the test must fail if any is silently accepted.
    """
    fx = _fixture()
    assert fx["reject"], "fixture has no rejection cases"
    accepted = []
    for row in fx["reject"]:
        case = _subst(row["case"])
        try:
            canonical_digest(case, kind=row["kind"])
            accepted.append(row["error"])
        except NonCanonical:
            pass
    assert not accepted, f"these MUST be rejected but were accepted: {accepted}"


def test_fixture_is_strict_json():
    """Python writes bare NaN/Infinity, which no other language can parse — the
    JS oracle failed to even LOAD the fixture until this was fixed."""
    import json, pathlib
    raw = pathlib.Path("canon_vectors.json").read_text()
    for literal in ("NaN", "Infinity", "-Infinity"):
        assert f": {literal}" not in raw, f"fixture contains non-JSON literal {literal}"
    json.loads(raw)


# ---------------------------------------------------------------- INVARIANT 8
# Key ordering and NFC collisions. Both were violated by the implementation
# while the spec claimed otherwise (review finding 1).

def test_nfc_colliding_keys_are_rejected_not_merged():
    """Two distinct keys normalising to one must NOT silently overwrite.

    Before the fix, {"café": 1, "cafe\u0301": 2} produced {"café": 2} — a digest
    for an object the caller never supplied, with a field silently dropped.
    """
    with pytest.raises(NonCanonical) as e:
        canonical_digest({"caf\u00e9": 1, "cafe\u0301": 2}, kind="effect_key")
    assert "normalise" in str(e.value).lower()


def test_key_order_is_utf8_byte_order_including_non_bmp():
    """The sort rule must be independently specified, and it is UTF-8 byte order.

    `json.dumps(sort_keys=True)` sorts by code point, NOT the UTF-16 code units
    RFC 8785 requires; they disagree exactly for non-BMP characters, because a
    surrogate pair starts 0xD800 which sorts below U+E000. This asserts our
    documented rule rather than assuming Python's default matches it.
    """
    pair = {"\ue000": 1, "\U0001f600": 2}
    reversed_insertion = {"\U0001f600": 2, "\ue000": 1}
    a = canonical_digest(pair, kind="effect_key")
    b = canonical_digest(reversed_insertion, kind="effect_key")
    assert a == b, "insertion order must not affect the digest"

    # and the order is the DOCUMENTED one: U+E000 before U+1F600
    import pin
    blob = pin._emit(pin._canon(pair)).decode()
    assert blob.index("\ue000") < blob.index("\U0001f600"), (
        "UTF-8 byte order puts U+E000 first; got UTF-16 order instead")


def test_extension_order_changes_the_digest():
    """Extensions compose, so order is semantic. They were being SORTED."""
    a = ExtensionBinding(name="a", artifact_digest="d1")
    b = ExtensionBinding(name="b", artifact_digest="d2")
    x = AgentDefinition(name="r", instructions="i", extensions=(a, b))
    y = AgentDefinition(name="r", instructions="i", extensions=(b, a))
    assert x.digest != y.digest, "swapping two extensions must change the digest"


def test_extension_requires_an_artifact_digest():
    with pytest.raises(NonCanonical):
        ExtensionBinding(name="a", artifact_digest="")


def test_model_digests_are_domain_separated():
    """AgentDefinition.digest and AdapterContract.digest omitted their kind, so
    domain separation existed in the envelope but not in the models using it."""
    payload = {"name": "x", "instructions": "y"}
    generic = canonical_digest(payload, kind="generic")
    d = AgentDefinition(name="x", instructions="y").digest
    assert d != generic, "AgentDefinition.digest must not sit in the generic domain"
    assert d == canonical_digest(
        {"name": "x", "instructions": "y", "tools": [], "extensions": []},
        kind="agent_definition")
