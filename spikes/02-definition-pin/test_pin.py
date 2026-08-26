"""SPIKE 02 GATE — the pin, end to end.

Gate (DESIGN.md 9 / scope-reconciliation 6):
  digest a definition, checkpoint, edit the definition, resume, confirm INCOMPATIBLE.

Plus: prove the verified LangGraph failure mode is actually prevented, since that
bug is the entire justification for ADR-0011.
"""
import pytest
from pin import (AgentDefinition, Runtime, IncompatibleCheckpoint, canonical_digest)


def _defn(instructions="review the diff", tools=("bash", "read")):
    return AgentDefinition(name="reviewer", instructions=instructions,
                           tools=list(tools), capabilities={"streaming": True})


# --- the gate ---------------------------------------------------------------

def test_gate_resume_after_edit_is_incompatible():
    rt = Runtime()
    rt.start("r1", _defn(), {"step": 7, "notes": "half done"})

    edited = _defn(instructions="review the diff AND run tests")   # the edit
    with pytest.raises(IncompatibleCheckpoint) as e:
        rt.resume("r1", edited)

    msg = str(e.value)
    assert "definition_digest changed" in msg          # names the FIELD
    assert "Start a new run" in msg                    # names the ALTERNATIVE
    print(f"\n  {msg}\n")


def test_gate_resume_unchanged_succeeds():
    """The pin must not be so brittle that nothing resumes."""
    rt = Runtime()
    rt.start("r2", _defn(), {"step": 7})
    assert rt.resume("r2", _defn()) == {"step": 7}


# --- the LangGraph failure mode, prevented ----------------------------------

def test_langgraph_failure_mode_is_prevented():
    """VERIFIED in the teardown: LangGraph resumes a renamed node by returning []
    with no error and silent work loss. Same shape here must RAISE."""
    rt = Runtime()
    rt.start("r3", _defn(tools=("bash", "read")), {"progress": "23 files scanned"})

    renamed = _defn(tools=("bash", "read_file"))       # a tool renamed
    with pytest.raises(IncompatibleCheckpoint):
        rt.resume("r3", renamed)                       # NOT a silent []


# --- properties the mechanism must have -------------------------------------

def test_version_bump_alone_does_not_invalidate():
    """A declared version is informational. Bumping it must not break resume,
    and forgetting to bump it must not hide a change."""
    rt = Runtime()
    d = _defn()
    rt.start("r4", d, {"x": 1})
    bumped = AgentDefinition(d.name, d.instructions, d.tools, d.capabilities, version=99)
    assert rt.resume("r4", bumped) == {"x": 1}


def test_forgetting_to_bump_still_detected():
    """The failure Omnigent cannot catch: content changed, version did not."""
    rt = Runtime()
    rt.start("r5", _defn(), {"x": 1})
    sneaky = AgentDefinition("reviewer", "do something else",
                             ["bash", "read"], {"streaming": True}, version=1)
    with pytest.raises(IncompatibleCheckpoint):
        rt.resume("r5", sneaky)


def test_adapter_change_detected_separately():
    """AX pins adapter identity; we pin both and must name which one moved."""
    rt = Runtime()
    rt.start("r6", _defn(), {"x": 1})
    rt._adapter_identity = "acp:codex"
    with pytest.raises(IncompatibleCheckpoint) as e:
        rt.resume("r6", _defn())
    assert "adapter_identity changed" in str(e.value)


def test_digest_is_canonical_not_ordering_sensitive():
    """A pin that varies by key order fails randomly, which is worse than never."""
    a = canonical_digest({"b": 2, "a": 1, "c": [3, 4]})
    b = canonical_digest({"c": [3, 4], "a": 1, "b": 2})
    assert a == b

def test_tool_reordering_does_not_invalidate():
    """Reordering a tool list is not a semantic change."""
    rt = Runtime()
    rt.start("r7", _defn(tools=("bash", "read")), {"x": 1})
    assert rt.resume("r7", _defn(tools=("read", "bash"))) == {"x": 1}
