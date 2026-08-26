"""SPIKE 02 REVISED GATE — the eight properties the review demanded."""
import os, tempfile
import pytest
from pin import (AgentDefinition, ToolBinding, AdapterContract, Pin,
                 IncompatibleCheckpoint, ArtifactMissing, NonCanonical,
                 canonical_digest)
from runtime import Store, Runtime, TripwireAdapter, AdapterInvoked


def _tool(name="bash", schema="sch1", ver="1.0",
          binding="local:python", approval="never", cred=None, artifact="art-abc"):
    return ToolBinding(name, schema, ver, artifact, binding, approval, cred)

def _defn(instructions="review the diff", tools=None, exts=()):
    return AgentDefinition("reviewer", instructions,
                           tuple(tools if tools is not None else (_tool(),)), exts)

def _adapter(identity="acp:claude-code", proto="1.0", mode="ACP_SUBPROCESS",
             caps=None, fail=False):
    return TripwireAdapter(AdapterContract(identity, proto, mode, caps or {}), fail)

@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    yield Store(path)
    os.unlink(path)


# 1. equivalent definitions -> identical digests
def test_equivalent_definitions_same_digest():
    assert _defn().digest == _defn().digest
    # tool ORDER is not semantic; tool SET is
    a = _defn(tools=(_tool("a"), _tool("b")))
    b = _defn(tools=(_tool("b"), _tool("a")))
    assert a.digest == b.digest


# 2. EVERY execution-relevant change produces a mismatch
@pytest.mark.parametrize("mutate,label", [
    (lambda: _defn(instructions="different"),                      "instructions"),
    (lambda: _defn(tools=(_tool(name="sh"),)),                     "tool name"),
    (lambda: _defn(tools=(_tool(schema="sch2"),)),                 "tool schema"),
    (lambda: _defn(tools=(_tool(ver="2.0"),)),                     "tool version"),
    (lambda: _defn(tools=(_tool(binding="mcp:remote"),)),          "execution binding"),
    (lambda: _defn(tools=(_tool(approval="always"),)),             "approval mode"),
    (lambda: _defn(tools=(_tool(cred="prod-key"),)),               "credential ref"),
    (lambda: _defn(tools=(_tool(), _tool("extra"))),               "added tool"),
    (lambda: _defn(exts=("Instrumentation",)),                     "extension added"),
])
def test_every_execution_relevant_change_mismatches(store, mutate, label):
    rt, a = Runtime(store), _adapter()
    rt.start("r", _defn(), a, {"x": 1})
    with pytest.raises(IncompatibleCheckpoint) as e:
        rt.resume("r", mutate(), a)
    assert "definition_digest changed" in str(e.value), label


# 3. version-only change does NOT mismatch
def test_version_only_change_resumes(store):
    rt, a = Runtime(store), _adapter()
    rt.start("r", _defn(), a, {"x": 1})
    bumped = AgentDefinition("reviewer", "review the diff", (_tool(),), (), version=99)
    assert rt.resume("r", bumped, a) == {"resumed_from": {"x": 1}}

def test_forgetting_to_bump_still_detected(store):
    """The failure Omnigent cannot catch: content moved, version did not."""
    rt, a = Runtime(store), _adapter()
    rt.start("r", _defn(), a, {"x": 1})
    sneaky = AgentDefinition("reviewer", "do something else", (_tool(),), (), version=1)
    with pytest.raises(IncompatibleCheckpoint):
        rt.resume("r", sneaky, a)


# 4. non-canonical values are REJECTED
@pytest.mark.parametrize("bad,label", [
    ({"t": object()},          "arbitrary object"),
    ({"x": float("nan")},      "NaN"),
    ({"x": float("inf")},      "Infinity"),
    ({1: "a"},                 "non-string key"),
])
def test_noncanonical_rejected(bad, label):
    with pytest.raises(NonCanonical):
        canonical_digest(bad)

def test_unicode_normalised():
    assert canonical_digest({"s": "café"}) == canonical_digest({"s": "cafe\u0301"})

def test_duplicate_tool_names_rejected():
    with pytest.raises(NonCanonical):
        _defn(tools=(_tool("bash"), _tool("bash", schema="other")))


# 5. checkpoints survive runtime/process reconstruction
def test_survives_process_restart(tmp_path):
    """Two independent Store+Runtime objects over the same file — the real test."""
    path = str(tmp_path / "r.db")
    Runtime(Store(path)).start("r", _defn(), _adapter(), {"progress": "23 files"})

    rt2 = Runtime(Store(path))                     # fresh objects, same bytes
    assert rt2.resume("r", _defn(), _adapter()) == {"resumed_from": {"progress": "23 files"}}

    with pytest.raises(IncompatibleCheckpoint):    # and still detects an edit
        rt2.resume("r", _defn(instructions="edited"), _adapter())


# 6. definition / adapter / schema mismatches fail DISTINCTLY
def test_each_pin_field_named_distinctly(store):
    rt = Runtime(store)
    rt.start("r1", _defn(), _adapter(), {})
    with pytest.raises(IncompatibleCheckpoint, match="definition_digest changed"):
        rt.resume("r1", _defn(instructions="x"), _adapter())

    rt.start("r2", _defn(), _adapter(), {})
    with pytest.raises(IncompatibleCheckpoint, match="adapter_identity changed"):
        rt.resume("r2", _defn(), _adapter(identity="acp:codex"))

    rt.start("r3", _defn(), _adapter(), {})
    with pytest.raises(IncompatibleCheckpoint, match="adapter_digest changed"):
        rt.resume("r3", _defn(), _adapter(proto="2.0"))     # same identity, new contract


# 7. NO adapter method runs before validation
def test_adapter_not_invoked_before_validation(store):
    rt = Runtime(store)
    rt.start("r", _defn(), _adapter(), {"x": 1})
    tripwire = _adapter(fail=True)          # raises if called at all
    with pytest.raises(IncompatibleCheckpoint):
        rt.resume("r", _defn(instructions="edited"), tripwire)
    assert tripwire.calls == [], "adapter was touched before the pin was checked"

def test_adapter_invoked_exactly_once_on_success(store):
    rt, a = Runtime(store), _adapter()
    rt.start("r", _defn(), a, {"x": 1})
    assert a.calls == []                     # start must not invoke it either
    rt.resume("r", _defn(), a)
    assert a.calls == ["start"]


# 8. the EXECUTED artifact is the one whose digest was checked
def test_definition_resolved_from_registry_not_caller(store):
    """If the pinned artifact is gone, resume must refuse rather than trust the
    caller's in-memory object."""
    rt, a = Runtime(store), _adapter()
    rt.start("r", _defn(), a, {"x": 1})
    store.db.execute("DELETE FROM definitions")      # artifact lost
    store.db.commit()
    # a MISSING artifact is now distinct from an INCOMPATIBLE one: different remedy
    with pytest.raises(ArtifactMissing, match="not in the registry"):
        rt.resume("r", _defn(), a)

def test_registry_is_content_addressed(store):
    """Same definition stored twice is one row; the digest IS the key."""
    d = _defn()
    store.put_definition(d); store.put_definition(d)
    n = store.db.execute("SELECT COUNT(*) FROM definitions").fetchone()[0]
    assert n == 1
    assert store.get_definition_body(d.digest) is not None
