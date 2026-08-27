"""SPIKE 06 GATE — no registered tool reaches a customer system unledgered.

INVARIANT, STATED FIRST (rule 1):
    A tool body executes only after the platform has written an `effect_ledger`
    row for that exact call. There is no path THROUGH THE HARNESS'S PUBLIC
    SURFACE -- construction, model-driven call, resume, approval, streaming, or
    error -- by which a registered tool body runs without one.

SCOPED 2026-08-28 (round 4), superseding the unqualified wording above (which
said "no path" without naming the surface). The boundary holds against a
COOPERATING in-process caller. `h._PhoenixHarness__build()` still returns the
`Agent`, and `override(native_tools=...)` / `override(toolsets=...)` on it
bypass the ledger entirely; `test_gate13_the_mangled_accessor_is_a_known_limitation`
asserts that limitation is real rather than absent. A boundary against a hostile
in-process caller requires the process split of OQ-056.

THE ORACLE IS INDEPENDENT (rule 5). Every tool in this file writes a line to a
real file in `tmp_path`. `harness.py` never reads or writes that file, so the
assertion is about OBSERVABLE SIDE EFFECTS, not about what the SDK reports
having done. That distinction is the whole point: a test that trusted the SDK's
own accounting would pass even if the SDK were lying.

TESTED THROUGH THE PUBLIC BOUNDARY (rule 3): `PhoenixHarness.run`, `.resume`,
`.stream_output`, `.resolve`, and -- for the facts being asserted ABOUT the SDK
rather than about Phoenix -- `Agent.run_sync`, `ExternalToolset.call_tool`,
`Agent.override`. No private attribute is poked to force a result, and the one
place that reaches for a name-mangled attribute is a NEGATIVE CONTROL whose
whole purpose is to show what an exposed `Agent` would allow.
"""
from __future__ import annotations

import collections.abc
import inspect
import json
import os
import subprocess
import sys
import types
import typing
from pathlib import Path

import pytest
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets.approval_required import ApprovalRequiredToolset
from pydantic_ai.toolsets.external import ExternalToolset
from pydantic_ai.toolsets.function import FunctionToolset

import verify_pin
from harness import (EffectLedger, LedgerRefused, LedgerRow, PhoenixHarness,
                     RunLease, UninterceptableTool)
from mutate import SPIKE_FILES, copy_spike

HERE = Path(__file__).resolve().parent
SCHEMA = {"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]}


# ---------------------------------------------------------------- the oracle
class SideChannel:
    """A real file. If a tool body ran, this file says so, whatever the SDK claims."""

    def __init__(self, tmp_path: Path):
        self.path = tmp_path / "customer_system_touched.log"

    def touch(self, what: str) -> str:
        with self.path.open("a") as fh:
            fh.write(what + "\n")
        return f"did:{what}"

    @property
    def lines(self) -> list[str]:
        return self.path.read_text().splitlines() if self.path.exists() else []


@pytest.fixture
def chan(tmp_path):
    return SideChannel(tmp_path)


@pytest.fixture
def led():
    return EffectLedger()


def harness(led, model=None, **kw) -> PhoenixHarness:
    return PhoenixHarness(ledger=led, model=model if model is not None else TestModel(), **kw)


# ============ CONTROL 0: the oracle can detect a real effect ================
# Rule 4, learned the hard way: assert a clean baseline AND assert the detector
# actually fires, before trusting any green result from it.
def test_control0_side_channel_detects_execution(chan):
    assert chan.lines == []
    chan.touch("send_email")
    assert chan.lines == ["send_email"]


# ============ GATE 0: THE VERSION PIN ======================================
# Every assertion below is about the behaviour of specific SDK BYTES. Review's
# control against the first version of this spike was: edit `toolsets/external.py`,
# run the suite, watch every gate still pass. Round 2 pinned five files -- and left
# `native_tools/__init__.py` unpinned while gate 6 admits tools by reading it, so
# the module that decides admission could be edited freely.
def test_gate0_pin_holds_against_the_installed_sdk():
    assert verify_pin.check() == [], "the installed SDK is not the pinned code"
    assert len(verify_pin.pinned()) >= len(verify_pin.REQUIRED_PINS)


def test_gate0_pin_covers_every_sdk_module_this_spike_imports():
    """The oracle is the IMPORT STATEMENTS, read from source, not a list we keep.

    Rule 5: if the pin's coverage were checked against a hand-kept list, the list
    and the pin would drift together. This parses `harness.py` and `test_gate.py`
    with `ast` and demands that every `pydantic_ai` module either one of them
    imports from is pinned by digest.
    """
    imported = verify_pin.sdk_modules_imported_by(
        [HERE / "harness.py", HERE / "test_gate.py"])
    assert imported, "the AST scan found no pydantic_ai imports -- the oracle is inert"
    unpinned = sorted(imported - set(verify_pin.pinned()))
    assert not unpinned, f"the gate depends on unpinned SDK files: {unpinned}"


def test_gate0_pin_covers_the_native_tool_admission_path():
    """The specific hole review found: admission is decided by `native_tools`."""
    for rel in ("native_tools/__init__.py", "native_tools/_tool_search.py",
                "models/function.py", "models/test.py", "toolsets/__init__.py",
                "toolsets/abstract.py",
                # ADDED 2026-08-28 (round 4). ADMISSION is decided HERE, not in
                # `native_tools/`: `models/__init__.py` defines
                # `ModelRequestParameters.native_tools` (`:179`) -- the object the
                # gate 13 recorder asserts is empty -- and `resolve_request_tools`
                # (`:1812-1930`), which filters native tools against
                # `supported_native_tools` at `:1849` and raises
                # `UserError('Native tool(s) ... not supported by this model')`.
                # `profiles/__init__.py` is where `supported_native_tools` comes
                # from. Round 3 pinned sixteen files and neither of these, so the
                # admission filter could be replaced wholesale with the pin still
                # reporting "pin holds" and all 47 gates green.
                "models/__init__.py", "profiles/__init__.py",
                # ADDED 2026-08-28 (round 5). `_tool_execution.py` does not run tool
                # bodies -- it imports `ToolManager` (`_tool_execution.py:15`) and
                # delegates (`:671`, `:958`). The body is invoked one level down, at
                # `tool_manager.py:1008` inside `_raw_execute` (`:994`), which is
                # where `ExternalToolset.call_tool`'s unconditional
                # `NotImplementedError` (`toolsets/external.py:46`) either propagates
                # or does not. It sat in `_coverage_frontier`, whose justification
                # ("none of which any assertion here touches") was false for it: in a
                # scratch SDK copy, `except NotImplementedError: tool_result = '...'`
                # at that line turned the refusal fail-OPEN and the pin still printed
                # "pin holds: 19 files" with 53 gates green.
                "tool_manager.py"):
        assert rel in verify_pin.pinned(), f"{rel} decides behaviour and is unpinned"


def test_gate0_the_import_oracle_reaches_the_admission_path_on_its_own():
    """Rule 5 for the oracle itself: it must be able to FIND the hole, not just
    agree with the hand-kept list.

    ADDED 2026-08-28 (round 4). `sdk_modules_imported_by` mapped each dotted name to
    a single relpath and never added the ancestor package `__init__.py` files an
    import executes, so it returned exactly ten modules -- a strict SUBSET of
    `REQUIRED_PINS` -- and `'models/__init__.py' in imported` was False. It asserted
    nothing the hand-kept list did not already assert. It now adds ancestors, so the
    module that decides admission is reached from the spike's own imports.
    """
    imported = verify_pin.sdk_modules_imported_by(
        [HERE / "harness.py", HERE / "test_gate.py"])
    assert "models/__init__.py" in imported, \
        "the oracle still cannot see the package __init__ an import executes"
    assert "__init__.py" in imported and "toolsets/__init__.py" in imported
    round3_list = set(verify_pin.REQUIRED_PINS) - {"models/__init__.py",
                                                   "profiles/__init__.py"}
    assert not imported <= round3_list, \
        "the oracle adds nothing round 3's hand-kept list did not already assert"


def test_gate0_negative_control_an_unrecorded_frontier_module_is_caught():
    """Rule 4 for what is DELIBERATELY out of the pin.

    The pin does not cover the transitive closure -- 284 modules, including every
    vendor model adapter. `pinned_digests.json:_coverage_frontier` records the
    one-level edge instead, and `check()` compares it, so a pinned file that grows
    an import into a module nobody has looked at fails rather than widening the
    unexamined surface silently. This plants a doctored frontier; nothing is
    written to the live pin file (rule 7).
    """
    files = sorted(verify_pin.pinned())
    real = verify_pin.frontier(files)
    assert len(real) > len(files), "the frontier is inert if it reaches nothing"
    assert verify_pin.frontier_problems(real, files) == []

    dropped = verify_pin.frontier_problems([r for r in real if r != "_utils.py"], files)
    assert len(dropped) == 1 and "_utils.py" in dropped[0]
    assert "outside the recorded frontier" in dropped[0]

    invented = verify_pin.frontier_problems([*real, "models/no_such.py"], files)
    assert len(invented) == 1 and "no pinned file imports" in invented[0]
    assert verify_pin.frontier_problems(None, files) == \
        ["the pin records no _coverage_frontier"]


def test_gate0_negative_control_a_fake_digest_is_caught():
    """Rule 4 for the pin itself: plant a wrong digest, the check must object."""
    real = verify_pin.pinned()["toolsets/external.py"]
    problems = verify_pin.check({"files": {"toolsets/external.py": "0" * 64}})
    assert len(problems) == 1 and "toolsets/external.py" in problems[0]
    assert verify_pin.check({"files": {"toolsets/external.py": real}}) == []


def test_gate0_negative_control_a_missing_file_and_an_empty_pin_are_caught():
    assert "MISSING" in verify_pin.check({"files": {"no_such_module.py": "0" * 64}})[0]
    assert verify_pin.check({"files": {}}) == ["the pin lists no files"]


def test_gate0_negative_control_a_mismatched_pin_aborts_COLLECTION(tmp_path):
    """The claim is "the session fails before any gate runs". Asserted, not stated.

    Rule 7: the mutation happens in a COPY of this spike inside `tmp_path`, which
    this test uniquely owns. The live tree is never written to, so a concurrent
    `make spike06` is unaffected.
    """
    work = copy_spike(tmp_path / "spike")
    pin = work / "pinned_digests.json"
    spec = json.loads(pin.read_text())
    spec["files"]["toolsets/external.py"] = "0" * 64
    pin.write_text(json.dumps(spec))

    r = subprocess.run([sys.executable, "-m", "pytest", "test_gate.py", "-q",
                        "--collect-only"], cwd=str(work), capture_output=True, text=True)
    assert r.returncode != 0, "a mismatched pin collected and ran anyway"
    assert "not the code spike 06 verified" in (r.stdout + r.stderr)
    assert "toolsets/external.py" in (r.stdout + r.stderr)


# ============ GATE 1: zero registered tools ================================
def test_gate1_no_tools_means_no_executable_path(chan, led):
    h = harness(led)
    turn = h.run("do something")
    assert not isinstance(turn.output, DeferredToolRequests)
    assert chan.lines == []
    assert led.rows == []


# ============ GATE 2: a registered tool never runs inside the SDK ==========
def test_gate2_run_halts_and_body_never_runs(chan, led):
    h = harness(led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))

    turn = h.run("email someone")

    assert isinstance(turn.output, DeferredToolRequests), \
        "the run must END on the deferred call, not execute it"
    assert [c.tool_name for c in turn.calls] == ["send_email"]
    # THE POINT: the SDK drove a tool call and the customer system was untouched.
    assert chan.lines == [], "SDK executed a registered tool body"
    assert led.rows == [], "nothing ledgered yet -- intent is the platform's move"


def test_gate2_negative_control_sdk_owned_tool_executes_unledgered(chan, led):
    """NEGATIVE CONTROL for `spec/08` row 30a.

    Hand the same function to the SDK the ordinary way (`FunctionToolset`) and
    the body runs with NO ledger row. This is the failure the design prevents,
    demonstrated rather than asserted.
    """
    fts = FunctionToolset()
    fts.add_function(lambda to: chan.touch(f"send_email:{to}"), name="send_email")
    agent = Agent(TestModel(), toolsets=[fts])

    agent.run_sync("email someone")

    assert chan.lines == ["send_email:a"], "control is broken if the body did not run"
    assert led.rows == [], "and the ledger never saw the effect -- the bypass, shown"


def test_gate2_a_duplicate_registration_is_refused(chan, led):
    """One name, one body -- because the ledger row names only the NAME.

    ADDED 2026-08-28 (round 5). `register()` accepted the same name twice with no key
    check, appending a second `ToolDefinition` and replacing the dispatcher.
    Measured at the round-4 commit: `defs: ['send_email', 'send_email']` and, on
    `run()` + `resolve()`, `fired: ['B']` -- the SECOND impl ran, the first was
    discarded silently, and the row read `('send_email', 'succeeded')`, so the ledger
    could not say which body executed. That is the key-uniqueness defect round 4
    closed inside `EffectLedger.append`, one layer up in the registry the row's
    `tool_name` refers to.
    """
    h = harness(led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"A:{to}"))
    with pytest.raises(UninterceptableTool, match="already registered"):
        h.register("send_email", SCHEMA, lambda to: chan.touch(f"B:{to}"))

    assert [d.name for d in h._defs] == ["send_email"], \
        "the refused registration still declared a second tool to the model"

    # VACUITY CONTROL: a DIFFERENT name still registers, so the refusal above is a
    # key comparison and not a blanket refusal to register a second tool.
    h.register("delete_row", SCHEMA, lambda to: chan.touch(f"C:{to}"))
    assert [d.name for d in h._defs] == ["send_email", "delete_row"]

    # ...and the body that runs is the one that was accepted.
    turn = h.run("email")
    h.resolve("run-1", turn.requests)
    assert sorted(chan.lines) == ["A:a", "C:a"]


# ============ GATE 3: exactly one ledger row per call, intent before act ===
def test_gate3_ledger_row_precedes_execution(chan, led):
    order: list[str] = []

    class Watched(EffectLedger):
        def append(self, row):
            order.append(f"ledger:{row.status}")
            super().append(row)

    led2 = Watched()
    h = harness(led2)
    h.register("send_email", SCHEMA,
               lambda to: (order.append("execute"), chan.touch(f"send_email:{to}"))[1])

    turn = h.run("email")
    h.resolve("run-1", turn.requests)

    assert order == ["ledger:intended", "execute"], f"wrong order: {order}"
    assert chan.lines == ["send_email:a"]
    rows = led2.rows_for(turn.calls[0].tool_call_id)
    assert len(rows) == 1 and rows[0].status == "succeeded"


class Call:
    """A pending call, the shape `DeferredToolRequests.calls` yields.

    Used where a gate must drive `intend()` and `dispatch()` with DIFFERENT calls,
    which the SDK's own object cannot express (it is one object, reused).
    """

    def __init__(self, tool_call_id, tool_name, args):
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name
        self.args = args


def test_gate3_dispatch_of_a_call_the_row_does_not_describe_is_refused(chan, led):
    """The invariant says "for that exact call". This asserts the word *exact*.

    ADDED 2026-08-28 (round 5). `dispatch()` never compared the call it was about to
    execute against the row the ledger holds for it: it looked the impl up by
    `call.tool_name` and claimed and settled by `call.tool_call_id`, from an object
    `intend()` had never seen. Reproduced at the round-4 commit through these same
    three public methods -- the ones gates 9 and 11 drive directly -- the CHARGE body
    executed and the single row settled `tc-1 read_doc {"to": "benign"} succeeded`.
    There was a row, and it was a row for a DIFFERENT effect.

    `spec/01-schema.md:403` is why that is not a technicality:
    `idempotency_key = sha256_hex(canon({tenant, run, logical_step_path,
    request_digest}))` puts the digest INSIDE the key, so a differing request is a
    different effect and cannot be settled under this one's key.
    """
    h = harness(led)
    h.register("read_doc", SCHEMA, lambda to: chan.touch(f"READ:{to}"))
    h.register("charge_card", SCHEMA, lambda to: chan.touch(f"CHARGE:{to}"))

    h.intend("run-1", Call("tc-1", "read_doc", {"to": "benign"}))

    # A different TOOL under the same call id.
    with pytest.raises(LedgerRefused, match="describes 'read_doc'"):
        h.dispatch("run-1", Call("tc-1", "charge_card", {"to": "victim"}))
    assert chan.lines == [], "a body ran against a row naming another effect"
    assert led.rows_for("tc-1")[0].status == "intended", \
        "the row must not be claimed or settled by a call it does not describe"

    # The same tool with different ARGUMENTS is equally a different effect.
    with pytest.raises(LedgerRefused, match="DIFFERENT effect"):
        h.dispatch("run-1", Call("tc-1", "read_doc", {"to": "somewhere-else"}))
    assert chan.lines == []
    assert led.rows_for("tc-1")[0].status == "intended"

    # VACUITY CONTROL: the MATCHING call still dispatches, so the two refusals
    # above are the identity comparison and not a blanket refusal to dispatch.
    assert h.dispatch("run-1", Call("tc-1", "read_doc", {"to": "benign"})) == \
        "did:READ:benign"
    assert chan.lines == ["READ:benign"]
    assert led.rows_for("tc-1")[0].status == "succeeded"


def test_gate3_settling_an_unledgered_call_is_refused(led):
    """Mutation control: the ledger cannot be made to settle what it never intended."""
    with pytest.raises(LedgerRefused, match="no ledger row"):
        led.settle("never-seen", "succeeded", None, owner="w", token="t")


# ============ GATE 4: THE RESUME PATH ======================================
# `_tool_execution.py:399`: when `tool_call_results` is supplied,
# `executable_function_kinds` becomes ('function','unknown','external','unapproved').
# External kinds DO flow through the regular pipeline on resume. If a body could
# run anywhere, it is here. This gate exists because the source said so.
def test_gate4_resume_consumes_platform_result_without_executing(chan, led):
    h = harness(led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))

    turn = h.run("email")
    call_id = turn.calls[0].tool_call_id

    # The platform dispatches, exactly once, through its own boundary.
    results = h.resolve("run-1", turn.requests)
    assert chan.lines == ["send_email:a"]

    after = h.resume(turn, results={call_id: results[call_id]})

    # THE ASSERTION: resume did not re-run the body. One dispatch, one effect.
    assert chan.lines == ["send_email:a"], "resume re-executed the tool body"
    assert len(led.rows_for(call_id)) == 1
    returned = [p.content for m in after.messages for p in m.parts
                if type(p).__name__ == "ToolReturnPart"]
    assert returned == ["did:send_email:a"], \
        "the model must observe the PLATFORM's result, not the SDK's"


def test_gate4_negative_control_resume_without_platform_dispatch(chan, led):
    """If the platform never dispatches, the customer system is never touched.

    Proves gate 4's green result comes from the platform's dispatch and not from
    something the SDK does incidentally.
    """
    h = harness(led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))

    turn = h.run("email")
    h.resume(turn, results={turn.calls[0].tool_call_id: "fabricated"})

    assert chan.lines == [], "a result supplied without dispatch still ran the body"
    assert led.rows == []


# ============ GATE 5: approval is fail-closed ==============================
def test_gate5_approval_required_halts_before_execution(chan, led):
    fts = FunctionToolset()
    fts.add_function(lambda to: chan.touch(f"send_email:{to}"), name="send_email")
    agent = Agent(TestModel(),
                  output_type=[str, DeferredToolRequests],
                  toolsets=[ApprovalRequiredToolset(fts)])

    result = agent.run_sync("email")

    assert isinstance(result.output, DeferredToolRequests)
    assert [c.tool_name for c in result.output.approvals] == ["send_email"]
    assert chan.lines == [], "approval gate let the body run"


def test_gate5_negative_control_approval_granted_then_it_runs(chan, led):
    """The control proving gate 5 tests the GATE and not a broken tool.

    Same setup, approval granted -> the body DOES run. So gate 5's empty
    side-channel was caused by the approval requirement, not by an inert tool.
    """
    fts = FunctionToolset()
    fts.add_function(lambda to: chan.touch(f"send_email:{to}"), name="send_email")
    agent = Agent(TestModel(),
                  output_type=[str, DeferredToolRequests],
                  toolsets=[ApprovalRequiredToolset(fts)])

    r1 = agent.run_sync("email")
    req = r1.output
    agent.run_sync(message_history=r1.all_messages(),
                   deferred_tool_results=req.build_results(approve_all=True))

    assert chan.lines == ["send_email:a"], "approval was granted but nothing ran"


# ==== GATE 6: row 30c, against EVERY native tool class the SDK defines =====
# Round 2's enumeration walked `dir(native_tools)` and wrapped construction in a
# bare `except Exception: pass`. Three real vendor-hosted tools -- `AdvisorTool`,
# `FileSearchTool`, `MCPServerTool` -- need constructor arguments, so all three
# were SILENTLY SKIPPED, and `ToolSearchTool` was never seen at all because it is
# not re-exported from the package namespace. A gate that skips what it cannot
# build is a gate that passes by not looking.
class CannotGenerate(Exception):
    """No minimal value could be generated for this annotation."""


def _value_for(tp: object):
    """Generate the smallest legal value for an annotation. No fallbacks."""
    origin = typing.get_origin(tp)
    if tp is str:
        return "spike06"
    if tp is int:
        return 1
    if tp is float:
        return 1.0
    if tp is bool:
        return False
    if origin is typing.Literal:
        return typing.get_args(tp)[0]
    if origin in (typing.Union, types.UnionType):
        for arm in typing.get_args(tp):
            if arm is type(None):
                continue
            try:
                return _value_for(arm)
            except CannotGenerate:
                continue
        raise CannotGenerate(tp)
    if origin in (list, set, frozenset, tuple, collections.abc.Sequence,
                  collections.abc.Iterable, collections.abc.Collection):
        args = typing.get_args(tp)
        return [_value_for(args[0])] if args else ["spike06"]
    if origin in (dict, collections.abc.Mapping):
        return {}
    raise CannotGenerate(tp)


def _minimal_args(cls) -> dict[str, object]:
    hints = typing.get_type_hints(cls)
    out = {}
    for name, p in inspect.signature(cls).parameters.items():
        if p.default is not inspect.Parameter.empty:
            continue
        out[name] = _value_for(hints.get(name, p.annotation))
    return out


def _every_native_tool_class() -> dict[str, type]:
    """Every `AbstractNativeTool` subclass the installed SDK defines.

    Source: `native_tools.NATIVE_TOOL_TYPES`, which is part of the module's
    `__all__` and is populated by `AbstractNativeTool.__init_subclass__` at class
    definition time -- so it holds subclasses that are NOT re-exported from the
    package namespace (`ToolSearchTool`), which is exactly what `dir()` missed.
    """
    import pydantic_ai.native_tools as nt
    registry = dict(nt.NATIVE_TOOL_TYPES)
    exported = {getattr(nt, n) for n in nt.__all__
                if isinstance(getattr(nt, n, None), type)
                and issubclass(getattr(nt, n), nt.AbstractNativeTool)
                and getattr(nt, n) is not nt.AbstractNativeTool}
    missing = exported - set(registry.values())
    assert not missing, f"__all__ exports native tools the registry lacks: {missing}"
    # `SUPPORTED_NATIVE_TOOLS` is a frozenset SNAPSHOT taken at module import, so it
    # can only be a subset of the live registry. Demanding equality would make the
    # negative control below fail on the snapshot rather than on the refusal.
    assert set(nt.SUPPORTED_NATIVE_TOOLS) <= set(registry.values()), \
        "SUPPORTED_NATIVE_TOOLS names a class the registry does not hold"
    return registry


def test_gate6_every_native_tool_class_is_instantiated_and_refused(led):
    """`spec/08` row 30c against every vendor-hosted tool class, INSTANTIATED.

    A class this test cannot construct is a HARD FAIL, never a skip: an
    unconstructible class is a native tool whose refusal was not exercised.
    """
    h = harness(led)
    checked = []
    for kind, cls in sorted(_every_native_tool_class().items()):
        try:
            args = _minimal_args(cls)
        except CannotGenerate as e:
            pytest.fail(f"{cls.__name__}: cannot generate minimal args for {e.args[0]!r} "
                        "-- the refusal for this native tool is UNTESTED")
        try:
            instance = cls(**args)
        except Exception as e:  # noqa: BLE001 -- deliberately fatal, never skipped
            pytest.fail(f"{cls.__name__}(**{args!r}) failed: {e!r} "
                        "-- the refusal for this native tool is UNTESTED")
        assert instance.kind == kind, f"{cls.__name__}.kind moved: {instance.kind!r}"
        with pytest.raises(UninterceptableTool, match="cannot be routed"):
            h.register(instance.kind, SCHEMA, lambda **k: "x")
        checked.append(instance.kind)

    assert len(checked) == len(set(checked)) >= 10, checked
    assert led.rows == []


def test_gate6_refusal_list_matches_the_sdk_registry_both_ways(led):
    """Fail-closed by construction, in BOTH directions.

    A native tool the SDK ships that the harness would admit is the dangerous
    direction; a name in the harness's list the SDK no longer ships means the
    refusal for it is dead code and the list is stale. Either is a failure.
    """
    from harness import NATIVE_TOOL_NAMES

    shipped = set(_every_native_tool_class())
    assert shipped - NATIVE_TOOL_NAMES == set(), \
        f"SDK ships native tools the harness would ADMIT: {sorted(shipped - NATIVE_TOOL_NAMES)}"
    assert NATIVE_TOOL_NAMES - shipped == set(), \
        f"harness refuses names the SDK no longer ships: {sorted(NATIVE_TOOL_NAMES - shipped)}"


def test_gate6_negative_control_a_new_native_tool_subclass_turns_the_gate_red(tmp_path):
    """Rule 4 for the enumeration: register a NEW native tool, watch the gate fail.

    The subclass is defined in a pytest plugin loaded only by a CHILD process, so
    it registers itself through the SDK's own `__init_subclass__` -- the same
    mechanism every shipped native tool uses -- without touching this process or
    the installed SDK (rule 7). Copying the SDK itself would trip the digest pin
    first, and the child would then go red for the wrong reason.

    CORRECTED 2026-08-28 (round 4). The child used to run at `cwd=HERE`, the LIVE
    spike directory, so it wrote `__pycache__/` and `.pytest_cache/` into a tree
    this test does not uniquely own while the parent session was running there too.
    Not destructive, and six concurrent runs were green -- but it is the asymmetry
    rule 7 names, and the two neighbouring controls
    (`..._a_mismatched_pin_aborts_COLLECTION`, `test_rule7_...`) already ran in an
    owned copy for exactly this reason. It now does the same.
    """
    plugin = tmp_path / "fake_native_tool.py"
    plugin.write_text(
        "from dataclasses import dataclass\n"
        "from pydantic_ai.native_tools import AbstractNativeTool\n"
        "@dataclass(kw_only=True)\n"
        "class FakeVendorTool(AbstractNativeTool):\n"
        "    kind: str = 'fake_vendor_search'\n")
    env = dict(os.environ, PYTHONPATH=str(tmp_path))
    work = copy_spike(tmp_path / "spike")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "test_gate.py", "-q", "-p", "fake_native_tool",
         "-k", "instantiated_and_refused or matches_the_sdk_registry"],
        cwd=str(work), capture_output=True, text=True, env=env)

    assert r.returncode != 0, "a new vendor-hosted tool was admitted with the gate green"
    assert "fake_vendor_search" in (r.stdout + r.stderr), r.stdout[-2000:]
    assert "2 failed" in r.stdout, r.stdout[-2000:]


def test_gate6_native_tools_never_enter_the_execution_pipeline():
    """WHY the refusal is structural, asserted against the SDK's own source.

    `_tool_execution.py` contains no reference to `NativeToolCallPart`. Native tools
    arrive as transcript parts from the provider; they are never dispatched locally.
    So there is no local body for `ExternalToolset` to withhold, which is why this is
    a structural impossibility rather than a policy choice.

    AMENDED 2026-08-28 (round 5), superseding — not erasing — the premise this
    docstring carried, which called `_tool_execution.py` "the only module that runs
    tool bodies". It is not: it ORCHESTRATES tool execution and the body is invoked
    one level down, at `tool_manager.py:1008` (`await self.toolset.call_tool(...)`
    inside `_raw_execute`, `:994`), which `_tool_execution.py:15` imports and
    `:671`/`:958` delegate to. Round 4 pinned neither that module nor this
    assertion's scope: in a scratch copy of the SDK (live site-packages untouched,
    rule 7), wrapping that call in
    `except NotImplementedError: tool_result = 'SILENTLY FABRICATED BY THE SDK'`
    turned `ExternalToolset`'s fail-closed refusal fail-OPEN inside the pipeline, and
    `verify_pin.py` still printed "pin holds: 19 files" while `pytest test_gate.py -q`
    printed "53 passed". Both modules are now pinned and both are grepped here.
    """
    bodies = {}
    for rel in ("_tool_execution.py", "tool_manager.py"):
        assert rel in verify_pin.pinned(), \
            f"{rel} is grepped by this gate and must be pinned by digest"
        bodies[rel] = (verify_pin.sdk_root() / rel).read_text()
    for rel, body in bodies.items():
        assert "NativeToolCallPart" not in body, \
            f"native tools now enter {rel} -- re-examine the refusal"
    assert "'external'" in bodies["_tool_execution.py"], \
        "sanity: external kinds ARE handled here"
    assert "self.toolset.call_tool(" in bodies["tool_manager.py"], \
        "sanity: tool_manager.py is still where the body is invoked"


def test_gate6_caller_declared_flag_is_also_refused(led):
    """The original assertion, kept but demoted to what it actually proves."""
    h = harness(led)
    with pytest.raises(UninterceptableTool, match="cannot be routed"):
        h.register("send_email", SCHEMA, lambda to: None, sdk_executable=True)
    assert h.run("anything").output is not None


def test_gate6_test_model_refuses_native_tools_is_a_fact_about_TestModel(led):
    """Corroboration, and NOT the structural claim. Kept, correctly labelled.

    `models/test.py:252` raises `UserError('TestModel does not support built-in
    tools')`. Review was right that this proves only that `TestModel` lacks
    built-in tool support; `FunctionModel` HAS it (`models/function.py:242`), so
    the structural claim is gate 13's, not this one's.
    """
    from pydantic_ai.exceptions import UserError
    from pydantic_ai.native_tools import WebSearchTool

    agent = Agent(TestModel(), output_type=[str, DeferredToolRequests])
    with pytest.raises(UserError, match="does not support built-in tools"):
        with agent.override(native_tools=[WebSearchTool()]):
            agent.run_sync("search the web")


def test_gate6_external_toolset_refuses_direct_invocation():
    """The SDK's own guarantee, asserted rather than assumed.

    `toolsets/external.py:46` raises unconditionally. If a future version made
    this executable, this test fails and the harness assumption is void.
    """
    import asyncio
    ts = ExternalToolset([ToolDefinition(name="send_email", parameters_json_schema=SCHEMA)])

    async def probe():
        tools = await ts.get_tools(None)  # type: ignore[arg-type]
        assert tools["send_email"].tool_def.kind == "external"
        with pytest.raises(NotImplementedError, match="cannot be called directly"):
            await ts.call_tool("send_email", {"to": "x"}, None, tools["send_email"])  # type: ignore[arg-type]

    asyncio.run(probe())


# ============ GATE 7: policy denial never reaches the system ===============
def test_gate7_denied_call_is_ledgered_and_never_executed(chan, led):
    h = harness(led, policy=lambda n, a: "deny")
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))

    turn = h.run("email")
    out = h.resolve("run-1", turn.requests)

    assert out[turn.calls[0].tool_call_id] == "DENIED by policy"
    assert chan.lines == [], "denied call still reached the customer system"
    rows = led.rows_for(turn.calls[0].tool_call_id)
    assert [r.status for r in rows] == ["denied"], \
        "a denial must be recorded, not silently dropped"
    assert rows[0].claim_owner is None and rows[0].claim_token is None, \
        "a denied row was never claimed (spec/01-schema.md:378)"


# ============ GATE 8: streaming is not a side door =========================
def test_gate8_streamed_run_does_not_execute_the_body(chan, led):
    """Streaming is a different code path through `_tool_execution.py`.

    A boundary that holds only on the buffered path is not a boundary.
    """
    import asyncio
    h = harness(led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))

    output = asyncio.run(h.stream_output("email"))
    assert isinstance(output, DeferredToolRequests)
    assert chan.lines == [], "the streaming path executed a registered tool body"


# ============ GATE 9: a hallucinated tool cannot invent a path =============
def test_gate9_unknown_tool_never_dispatches(chan, led):
    h = harness(led)
    h.register("send_email", SCHEMA, lambda to: chan.touch("send_email"))
    turn = h.run("email")
    call = turn.calls[0]

    class Fake:
        tool_call_id = call.tool_call_id
        tool_name = "rm_rf"
        args = {}

    h.intend("run-1", Fake())
    with pytest.raises(UninterceptableTool, match="no platform dispatcher"):
        h.dispatch("run-1", Fake())
    assert chan.lines == []
    row = led.rows_for(call.tool_call_id)[0]
    # `abandoned`, NOT `failed`: nothing was ever claimed or dispatched, and
    # `spec/01-schema.md:381` forbids a `failed` row with no claim.
    assert row.status == "abandoned" and row.error_code == "no_dispatcher"
    assert row.claim_owner is None and row.completed_at is None


# ============ GATE 10: many calls in one step stay distinct ================
def test_gate10_parallel_calls_get_one_row_each(chan, led):
    """A step with three tool calls must produce three ledger rows.

    If `tool_call_id`s collided, `settle()` would overwrite a sibling and one
    effect would vanish from the ledger while still having happened.
    """
    h = harness(led)
    for n in ("send_email", "delete_row", "charge_card"):
        h.register(n, SCHEMA, lambda to, _n=n: chan.touch(f"{_n}:{to}"))

    turn = h.run("do all three")
    assert len(turn.calls) == 3
    h.resolve("run-1", turn.requests)

    assert len(led.rows) == 3
    assert len({r.tool_call_id for r in led.rows}) == 3, "tool_call_id collision"
    assert sorted(chan.lines) == ["charge_card:a", "delete_row:a", "send_email:a"]
    assert all(r.status == "succeeded" for r in led.rows)


# ============ GATE 11: a failing body still leaves a settled verdict =======
def test_gate11_raising_tool_becomes_indeterminate_not_intended(chan, led):
    """`spec/02-consistency.md:326-348`: a dispatched effect must never be left
    with no verdict.

    The body ran (the side channel proves it) and then raised, so we CANNOT know
    whether the customer system was mutated. That is precisely `indeterminate`.

    This gate found a real defect rather than confirming a design: the first
    harness left the row at `intended`, which is indistinguishable from an effect
    that never started -- so a crashed charge would have looked like a charge
    that never happened. Fixed in `harness.py.dispatch`.
    """
    def boom(to):
        chan.touch(f"send_email:{to}")
        raise RuntimeError("smtp exploded")

    h = harness(led)
    h.register("send_email", SCHEMA, boom)
    turn = h.run("email")

    with pytest.raises(RuntimeError, match="smtp exploded"):
        h.resolve("run-1", turn.requests)

    assert chan.lines == ["send_email:a"], "the body must have actually run"
    row = led.rows_for(turn.calls[0].tool_call_id)[0]
    assert row.status == "indeterminate", \
        "a dispatched effect that crashed must surface, not look unstarted"
    assert row.error_code == "dispatch_lost_contact"
    assert row.completed_at is None, \
        "indeterminate is not completed (spec/01-schema.md:374)"


def test_gate11_a_raise_BEFORE_dispatch_is_failed_not_indeterminate(chan, led):
    """The other half of the same rule, and the one round 2 did not have.

    A claim taken, then a raise before the body is entered: nothing was
    dispatched, so the outcome IS known. `failed`, with an error code -- not
    `indeterminate`, which would send a human to investigate an effect that
    provably never happened.
    """
    h = harness(led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))

    class Undecodable:
        tool_call_id = "tc-bad-args"
        tool_name = "send_email"
        args = "{not json"

    h.intend("run-1", Undecodable())
    with pytest.raises(json.JSONDecodeError):
        h.dispatch("run-1", Undecodable())

    assert chan.lines == [], "the body must NOT have run"
    row = led.rows_for("tc-bad-args")[0]
    assert row.status == "failed" and row.error_code == "arguments_undecodable"
    assert row.completed_at is not None, "a failed effect is completed"
    assert row.claim_owner == "worker:run-1" and row.claim_token


def test_gate11_arguments_that_do_not_BIND_are_failed_not_indeterminate(chan, led):
    """The pre-dispatch branch a model actually reaches.

    ADDED 2026-08-28 (round 4). Argument BINDING used to happen at the
    `impl(**args)` call inside the dispatch try, and Python raises binding errors AT
    the call, before the body is entered -- so a call whose argument NAMES did not
    match the impl was recorded `indeterminate` / `dispatch_lost_contact` although
    nothing was dispatched. `spec/05-state-machine.md:110`: "Manufacturing
    uncertainty is not free -- every `indeterminate` run costs human attention, so
    the state must be reserved for cases where uncertainty is real."
    `spec/02-consistency.md:327-328`: "indeterminate now means only 'we took a
    lease, dispatched, and lost contact' -- real uncertainty, never bookkeeping."

    The sibling test above exercises the JSON-decode branch, which is UNREACHABLE on
    the real path: args arrive from the SDK as a dict. This is the branch a
    hallucinated or renamed parameter hits, so no gate could have gone red on it.
    """
    h = harness(led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))

    class WrongArgName:
        tool_call_id = "tc-unbindable"
        tool_name = "send_email"
        args = {"recipient": "a"}   # the impl takes `to`

    h.intend("run-1", WrongArgName())
    with pytest.raises(TypeError, match="missing a required argument"):
        h.dispatch("run-1", WrongArgName())

    assert chan.lines == [], "the body must NOT have run"
    row = led.rows_for("tc-unbindable")[0]
    assert row.status == "failed", \
        "nothing was dispatched, so the outcome is KNOWN -- not `indeterminate`"
    assert row.error_code == "arguments_unbindable"
    assert row.completed_at is not None, "a failed effect is completed"


def test_gate11_negative_control_intended_would_hide_the_effect(chan, led):
    """Mutation control for gate 11: prove the assertion discriminates.

    A ledger that keeps the row at `claimed` must FAIL the gate above. Without
    this control, gate 11 would pass against either behaviour.
    """
    class SloppyLedger(EffectLedger):
        def settle(self, tool_call_id, status, result_json, **kw):
            if status == "indeterminate":
                return  # the defect: a crash leaves the row untouched
            super().settle(tool_call_id, status, result_json, **kw)

    def boom(to):
        chan.touch(f"send_email:{to}")
        raise RuntimeError("smtp exploded")

    sloppy = SloppyLedger()
    h = harness(sloppy)
    h.register("send_email", SCHEMA, boom)
    turn = h.run("email")
    with pytest.raises(RuntimeError):
        h.resolve("run-1", turn.requests)

    statuses = [r.status for r in sloppy.rows_for(turn.calls[0].tool_call_id)]
    assert statuses == ["claimed"], \
        "control is broken if the row settled; it must be left at the claim"


# ==== GATE 12: the ledger IS spec/01 effect_status and spec/02's phases ====
# Round 2's ledger used a status `'settled'` that `spec/01-schema.md:332` does not
# define, accepted `intended -> settled` with no claim, no owner and no token, and
# had no run-lease predicate at all. Every assertion below is one predicate from
# `spec/02-consistency.md:196-322`.
def test_gate12_the_status_vocabulary_is_exactly_spec_01(led):
    """`settled` is not a status. Nor is anything else we might invent."""
    from harness import EFFECT_STATUS

    assert EFFECT_STATUS == {
        "intended", "awaiting_approval", "claimed", "succeeded", "failed",
        "denied", "abandoned", "indeterminate"}, "spec/01-schema.md:332"
    with pytest.raises(LedgerRefused, match="is not an effect_status"):
        led.append(LedgerRow("run-1", "tc-x", "send_email", "{}", "settled"))


def test_gate12_full_phase_order_is_observable(chan, led):
    """intended -> claimed -> succeeded, with the claim fields set at the claim."""
    seen: list[str] = []

    class Traced(EffectLedger):
        def append(self, row):
            seen.append(f"append:{row.status}")
            super().append(row)

        def claim(self, tool_call_id, owner, token, **kw):
            seen.append("claim")
            super().claim(tool_call_id, owner, token, **kw)

        def settle(self, tool_call_id, status, result_json, **kw):
            seen.append(f"settle:{status}")
            super().settle(tool_call_id, status, result_json, **kw)

    traced = Traced()
    h = harness(traced)
    h.register("send_email", SCHEMA,
               lambda to: (seen.append("EXECUTE"), chan.touch(f"send_email:{to}"))[1])
    turn = h.run("email")
    h.resolve("run-1", turn.requests)

    assert seen == ["append:intended", "claim", "EXECUTE", "settle:succeeded"], seen
    row = traced.rows_for(turn.calls[0].tool_call_id)[0]
    assert row.claim_owner == "worker:run-1" and row.claim_token
    assert row.lease_expires_at is not None and row.completed_at is not None


def _claimed_row(led, *, run_id="run-1", call_id="tc-1", owner="worker:run-1",
                 token="the-real-token", clock=lambda: 1000.0):
    led.clock = clock
    led.append(LedgerRow(run_id, call_id, "send_email", "{}", "intended"))
    lease = RunLease(run_id=run_id, holder=owner, fence_token="f", expires_at=clock() + 300)
    led.claim(call_id, owner, token, lease=lease, fence=lease.fence_token)
    return lease


def test_gate12_settle_of_an_INTENDED_row_is_refused(led):
    """The exact hole review found: `intended -> settled` with no claim at all."""
    led.append(LedgerRow("run-1", "tc-1", "send_email", "{}", "intended"))
    for status in ("succeeded", "failed", "indeterminate"):
        with pytest.raises(LedgerRefused, match="settle requires status 'claimed'"):
            led.settle("tc-1", status, None, owner="worker:run-1", token="t")
    assert led.rows_for("tc-1")[0].status == "intended"


def test_gate12_settle_with_a_wrong_token_or_no_token_is_refused(led):
    """`spec/02-consistency.md:301` — all three predicates, each one asserted."""
    _claimed_row(led)
    with pytest.raises(LedgerRefused, match="stale worker fenced out"):
        led.settle("tc-1", "succeeded", '"forged"', owner="worker:run-1", token="a-guess")
    with pytest.raises(LedgerRefused, match="stale worker fenced out"):
        led.settle("tc-1", "succeeded", '"forged"', owner="someone-else",
                   token="the-real-token")
    with pytest.raises(LedgerRefused, match="requires the claim owner AND its token"):
        led.settle("tc-1", "succeeded", '"forged"')
    with pytest.raises(LedgerRefused, match="requires the claim owner AND its token"):
        led.settle("tc-1", "succeeded", '"forged"', owner="worker:run-1")
    assert led.rows_for("tc-1")[0].status == "claimed", "the fence must hold the row"
    # ...and the holder still can.
    led.settle("tc-1", "succeeded", '"real"', owner="worker:run-1", token="the-real-token")
    assert led.rows_for("tc-1")[0].status == "succeeded"


def test_gate12_settle_cannot_be_used_for_denial_or_abandonment(led):
    """`denied` and `abandoned` move an UNCLAIMED row and have their own statements."""
    _claimed_row(led)
    for status in ("denied", "abandoned", "intended", "claimed", "settled"):
        with pytest.raises(LedgerRefused, match="settle takes one of"):
            led.settle("tc-1", status, None, owner="worker:run-1", token="the-real-token")


def test_gate12_claim_without_a_run_lease_is_refused(led):
    """`spec/02-consistency.md:246` predicate (b), which round 2 omitted entirely."""
    led.append(LedgerRow("run-1", "tc-1", "send_email", "{}", "intended"))
    with pytest.raises(LedgerRefused, match="requires an unexpired run lease"):
        led.claim("tc-1", "worker:run-1", "tok", lease=None)
    assert led.rows_for("tc-1")[0].status == "intended"


def test_gate12_claim_with_an_expired_or_foreign_run_lease_is_refused(led):
    led.clock = lambda: 1000.0
    led.append(LedgerRow("run-1", "tc-1", "send_email", "{}", "intended"))
    for bad, why in (
            (RunLease("run-1", "worker:run-1", "f", 999.0), "expired"),
            (RunLease("run-1", "another-worker", "f", 2000.0), "held by someone else"),
            (RunLease("run-OTHER", "worker:run-1", "f", 2000.0), "for another run")):
        with pytest.raises(LedgerRefused, match="does not authorise this claim"):
            led.claim("tc-1", "worker:run-1", "tok", lease=bad, fence="f")
        assert led.rows_for("tc-1")[0].status == "intended", why
    # ...and a good lease is accepted, so the refusals above are the predicate.
    led.claim("tc-1", "worker:run-1", "tok",
              lease=RunLease("run-1", "worker:run-1", "f", 2000.0), fence="f")
    assert led.rows_for("tc-1")[0].status == "claimed"


def test_gate12_claim_under_a_SUPERSEDED_fence_token_is_refused(led):
    """The fence half of predicate (b): `AND l.fence_token = $fence`
    (`spec/02-consistency.md:248`).

    ADDED 2026-08-28 (round 4). `fence_token` was stored on `RunLease` and read
    NOWHERE, so only the holder and expiry halves of predicate (b) existed and a
    worker holding a superseded token claimed successfully. `spec/02:440-443` is
    explicit about why that matters: a lease row carrying a *higher* token still
    matches an EXISTS that omits the token, so the stale worker's write lands.
    """
    led.clock = lambda: 1000.0
    led.append(LedgerRow("run-1", "tc-1", "send_email", "{}", "intended"))
    reclaimed = RunLease("run-1", "worker:run-1", "FENCE-2", 2000.0)

    with pytest.raises(LedgerRefused, match="does not authorise this claim"):
        led.claim("tc-1", "worker:run-1", "tok", lease=reclaimed, fence="FENCE-1")
    assert led.rows_for("tc-1")[0].status == "intended", \
        "a superseded fence token took the claim"
    # ...and no fence at all is not a way around it.
    with pytest.raises(LedgerRefused, match="does not authorise this claim"):
        led.claim("tc-1", "worker:run-1", "tok", lease=reclaimed, fence=None)
    assert led.rows_for("tc-1")[0].status == "intended"
    # ...while the token the lease actually carries is accepted, so the two
    # refusals above are the fence and not something incidental.
    led.claim("tc-1", "worker:run-1", "tok", lease=reclaimed, fence="FENCE-2")
    assert led.rows_for("tc-1")[0].status == "claimed"


def test_gate12_a_second_intent_for_the_same_call_is_a_no_op(chan, led):
    """`spec/01-schema.md:366-367` — THE PRIMITIVE: `PRIMARY KEY (tenant_id,
    idempotency_key)`, and `spec/02-consistency.md:202-204` makes a duplicate intent
    `ON CONFLICT ... DO NOTHING`.

    ADDED 2026-08-28 (round 4). `append()` appended unconditionally, so the ledger
    had no key uniqueness at all. Reproduced single-threaded through the PUBLIC
    surface: `resolve()` twice for one call left two rows for one `tool_call_id` --
    `[('c2','succeeded'), ('c2','intended')]` -- and since `_index()` returns the
    first match the duplicate was permanently unreachable, stuck at `intended`
    forever. Gate 3's "exactly one row per call" held only because no gate had ever
    intended twice.
    """
    h = harness(led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    turn = h.run("email")

    h.resolve("run-1", turn.requests)
    call_id = turn.calls[0].tool_call_id
    assert [r.status for r in led.rows_for(call_id)] == ["succeeded"]
    assert chan.lines == ["send_email:a"]

    # The same call, intended a second time. The duplicate intent is dropped, so
    # the claim meets the SETTLED row rather than a fresh `intended` one and the
    # effect is refused instead of executed twice.
    with pytest.raises(LedgerRefused, match="claim requires status 'intended'"):
        h.resolve("run-1", turn.requests)

    rows = led.rows_for(call_id)
    assert len(rows) == 1, f"a duplicate intent created a second row: {rows}"
    assert rows[0].status == "succeeded", \
        "the duplicate intent reset a settled effect to `intended`"
    assert chan.lines == ["send_email:a"], "the effect was executed twice"

    # Control for vacuity: a DIFFERENT key still appends, so the guard above is a
    # key comparison and not a blanket refusal to record intent.
    led.append(LedgerRow("run-1", "tc-other", "send_email", "{}", "intended"))
    assert len(led.rows_for("tc-other")) == 1


def test_gate12_one_key_spans_two_runs_and_the_second_run_cannot_dispatch(chan, led):
    """The PRIMARY KEY has no `run_id` in it, and the dispatch says so out loud.

    ADDED 2026-08-28 (round 5). The round-4 conflict guard was
    `r.tool_call_id == row.tool_call_id AND r.run_id == row.run_id`, i.e.
    `UNIQUE (tenant_id, idempotency_key, run_id)` (`spec/01-schema.md:372`) -- not the
    `PRIMARY KEY (tenant_id, idempotency_key)` (`spec/01:367`) its own docstring
    quoted, and not the `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING`
    conflict target of `spec/02-consistency.md:202`, which contains no `run_id`.
    Measured at that commit: intending one call under two runs left TWO rows for one
    key, the second permanently unreachable at `intended`; and with a caller-supplied
    lease, `dispatch('run-2', call)` EXECUTED the effect and recorded it against
    run-1's row, leaving run-2 executed-but-`intended` (`spec/01:509`: "nothing
    returns to `intended`").
    """
    h = harness(led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    call = Call("tc-1", "send_email", {"to": "a"})

    h.intend("run-1", call)
    h.intend("run-2", call)
    rows = led.rows_for("tc-1")
    assert len(rows) == 1, f"one idempotency_key, two rows (spec/01:367): {rows}"
    assert rows[0].run_id == "run-1", "DO NOTHING kept the first row, as specified"

    # The surviving row belongs to another run, so run-2 may not execute against it.
    with pytest.raises(LedgerRefused, match="is an effect of run 'run-1'"):
        h.dispatch("run-2", call)
    assert chan.lines == [], "run-2 executed an effect recorded against run-1"
    assert [(r.run_id, r.status) for r in led.rows] == [("run-1", "intended")], \
        "the wrong run's row was claimed or settled"

    # VACUITY CONTROL: the run that owns the row still dispatches.
    assert h.dispatch("run-1", call) == "did:send_email:a"
    assert [(r.run_id, r.status) for r in led.rows] == [("run-1", "succeeded")]
    assert chan.lines == ["send_email:a"]


def test_gate12_an_expired_run_lease_stops_the_whole_dispatch(chan, led):
    """End to end, through the harness: no lease, no effect, no verdict invented."""
    clock = lambda: 1000.0  # noqa: E731
    led.clock = clock
    h = harness(led, clock=clock,
                lease=RunLease("run-1", "worker:run-1", "f", 999.0))
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    turn = h.run("email")

    with pytest.raises(LedgerRefused, match="does not authorise this claim"):
        h.resolve("run-1", turn.requests)

    assert chan.lines == [], "a fenced-out worker reached the customer system"
    assert [r.status for r in led.rows] == ["intended"]

    # ADDED 2026-08-28 (round 5). The two clocks above are pinned to the SAME lambda
    # by hand, which was the symptom: `_lease_for()` minted `expires_at` from
    # `PhoenixHarness.clock` while `claim()` judged it against `EffectLedger.clock`,
    # two independent attributes where `spec/02-consistency.md:249` has one `now()`
    # inside one statement. Measured before the fix: a harness whose only unusual
    # argument was `clock=lambda: 1000.0`, against a ledger reading
    # `time.monotonic()`, minted `expires_at=1060.0` and every dispatch raised
    # "the run lease does not authorise this claim". So: pin ONLY the harness clock,
    # leave the ledger on real time, and the mint must still authorise the claim.
    unpinned = EffectLedger()          # real `time.monotonic()`
    h2 = harness(unpinned, clock=lambda: 1000.0)
    h2.register("send_email", SCHEMA, lambda to: chan.touch(f"second:{to}"))
    turn2 = h2.run("email")
    h2.resolve("run-1", turn2.requests)
    assert [r.status for r in unpinned.rows] == ["succeeded"], \
        "the lease was minted on one clock and judged on another"
    assert chan.lines == ["second:a"]


def test_gate12_the_approval_phase_is_the_spec_one(led):
    """intended -> awaiting_approval -> (denied | claimed-with-approval).

    `awaiting_approval` is a distinct status precisely so an effect waiting on a
    human is not holding an execution lease (`spec/01-schema.md:326`).
    """
    led.clock = lambda: 1000.0
    led.append(LedgerRow("run-1", "tc-1", "send_email", "{}", "intended"))
    led.await_approval("tc-1")
    row = led.rows_for("tc-1")[0]
    assert row.status == "awaiting_approval"
    assert row.claim_owner is None and row.lease_expires_at is None, \
        "an effect awaiting a human holds no lease"

    good = RunLease("run-1", "worker:run-1", "f", 2000.0)
    with pytest.raises(LedgerRefused, match="requires an approval"):
        led.claim("tc-1", "worker:run-1", "tok", lease=good, fence="f")
    assert led.rows_for("tc-1")[0].status == "awaiting_approval"

    led.claim("tc-1", "worker:run-1", "tok", lease=good, fence="f", approved=True)
    assert led.rows_for("tc-1")[0].status == "claimed"


def test_gate12_denial_and_abandonment_move_only_unclaimed_rows(led):
    """`spec/02-consistency.md:307-322`: neither can ever produce `indeterminate`."""
    led.append(LedgerRow("run-1", "tc-a", "send_email", "{}", "intended"))
    led.deny("tc-a", error_code="approver_refused")
    assert led.rows_for("tc-a")[0].status == "denied"

    led.append(LedgerRow("run-1", "tc-b", "send_email", "{}", "intended"))
    led.abandon("tc-b", error_code="run_ended")
    assert led.rows_for("tc-b")[0].status == "abandoned"

    _claimed_row(led, call_id="tc-c")
    with pytest.raises(LedgerRefused, match="requires an unclaimed row"):
        led.deny("tc-c")
    with pytest.raises(LedgerRefused, match="requires an unclaimed row"):
        led.abandon("tc-c")


def test_gate12_claim_requires_intent_first(led):
    """Claiming a row that was never intended is refused, so phases cannot be skipped."""
    good = RunLease("run-nope", "worker:x", "f", 1e18)
    with pytest.raises(LedgerRefused, match="no ledger row"):
        led.claim("tc-nope", "worker:x", "tok", lease=good)
    _claimed_row(led, call_id="tc-2")
    with pytest.raises(LedgerRefused, match="claim requires status 'intended'"):
        led.claim("tc-2", "worker:run-1", "tok",
                  lease=RunLease("run-1", "worker:run-1", "f", 1e18))


def test_gate12_the_claim_field_check_constraint_is_enforced(led):
    """`spec/01-schema.md:378` — an unclaimed row carries no owner; a claimed one does."""
    with pytest.raises(LedgerRefused, match="must carry no owner"):
        led.append(LedgerRow("run-1", "tc-1", "e", "{}", "intended", claim_owner="w"))
    with pytest.raises(LedgerRefused, match="requires owner, token"):
        led.append(LedgerRow("run-1", "tc-2", "e", "{}", "claimed"))
    with pytest.raises(LedgerRefused, match="completed_at IS NOT NULL"):
        led.append(LedgerRow("run-1", "tc-3", "e", "{}", "succeeded", claim_owner="w",
                             claim_token="t", lease_expires_at=1.0))


# ==== GATE 13: THE STRUCTURAL REFUSAL — there is no Agent to override ======
# Review's finding, and it was correct: `build_agent()` handed back a raw `Agent`.
# With it in hand, `agent.override(native_tools=[WebSearchTool()])` delivers a
# vendor-hosted tool to the model with zero Phoenix involvement. The old gate
# asserted only that `TestModel` REFUSES built-in tools -- a fact about
# `TestModel`. `FunctionModel` supports them (`models/function.py:242`), and the
# negative control below shows the delivery happening.
def _recorder_model(seen: list, tool_name: str = "send_email"):
    """A FunctionModel that records what native tools the model was handed.

    Both halves are supplied, so the BUFFERED and the STREAMING request paths are
    each observed: a boundary that leaks only when streaming is still a leak.
    """
    state = {"n": 0}

    def f(messages, info: AgentInfo):
        seen.append(tuple(info.model_request_parameters.native_tools))
        state["n"] += 1
        if state["n"] == 1 and tool_name:
            return ModelResponse(parts=[ToolCallPart(
                tool_name, {"to": "a"}, tool_call_id="fm-1")])
        return ModelResponse(parts=[TextPart("done")])

    async def stream(messages, info: AgentInfo):
        seen.append(tuple(info.model_request_parameters.native_tools))
        if tool_name:
            yield {0: DeltaToolCall(name=tool_name, json_args='{"to": "a"}',
                                    tool_call_id="fm-stream-1")}
        else:
            yield "done"

    return FunctionModel(f, stream_function=stream)


def agents_reachable_from(obj) -> list[str]:
    """Every public name on `obj` that IS, or zero-argument-returns, an `Agent`.

    Calling public zero-argument callables is deliberate: `build_agent()` was a
    method, not an attribute, so a scan that only read values would have declared
    the old harness clean.
    """
    found = []
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            value = getattr(obj, name)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(value, Agent):
            found.append(name)
            continue
        if callable(value):
            try:
                returned = value()
            except Exception:  # noqa: BLE001 -- needs arguments; not an accessor
                continue
            if isinstance(returned, Agent):
                found.append(f"{name}()")
    return found


def test_gate13_no_public_name_on_the_harness_yields_an_agent(chan, led):
    h = harness(led, model=_recorder_model([]))
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    turn = h.run("email")

    assert agents_reachable_from(h) == [], "the harness exposes an Agent"
    assert agents_reachable_from(turn) == [], "the Turn exposes an Agent"
    assert not any(isinstance(v, Agent) for v in vars(turn).values())
    assert not [k for k, v in vars(h).items()
                if isinstance(v, Agent) and not k.startswith("_")]
    assert not hasattr(h, "build_agent"), \
        "build_agent() is the hole review found; it must not come back"


def test_gate13_native_tools_and_toolsets_are_refused_at_the_door(led):
    """A caller cannot hand the harness SDK surface Phoenix would not ledger.

    EXTENDED 2026-08-28 (round 4) with `capabilities=`, the THIRD such surface and
    the one this gate did not name. `Agent(capabilities=[...])`
    (`agent/__init__.py:618-631`) delivers native tools -- verified: a
    `FunctionModel` recorder handed `NativeTool(WebSearchTool())` through it sees
    `WebSearchTool(kind='web_search', ...)` -- and `pydantic_ai.capabilities` also
    exports `Toolset`, `MCP(local=True)` and `WebSearch(local='duckduckgo')`, which
    carry a LOCAL EXECUTABLE BODY, i.e. exactly what `ExternalToolset` exists to
    withhold. The harness already failed closed on it, but only through the
    catch-all "unknown arguments" branch, with no gate asserting it and the refusal
    naming no surface.
    """
    from pydantic_ai.capabilities import NativeTool
    from pydantic_ai.native_tools import WebSearchTool

    with pytest.raises(UninterceptableTool, match="native_tools="):
        PhoenixHarness(ledger=led, model=TestModel(), native_tools=[WebSearchTool()])
    with pytest.raises(UninterceptableTool, match="toolsets="):
        PhoenixHarness(ledger=led, model=TestModel(), toolsets=[FunctionToolset()])
    with pytest.raises(UninterceptableTool, match="capabilities="):
        PhoenixHarness(ledger=led, model=TestModel(),
                       capabilities=[NativeTool(WebSearchTool())])

    h = harness(led)
    with pytest.raises(UninterceptableTool, match="capabilities="):
        h.register("send_email", SCHEMA, lambda to: None,
                   capabilities=[NativeTool(WebSearchTool())])
    with pytest.raises(UninterceptableTool, match="native_tools="):
        h.register("send_email", SCHEMA, lambda to: None, native_tools=[WebSearchTool()])
    with pytest.raises(UninterceptableTool, match="native_tools="):
        h.register("send_email", SCHEMA, lambda to: None, native_tools=None)
    with pytest.raises(UninterceptableTool, match="toolsets="):
        h.register("send_email", SCHEMA, lambda to: None, toolsets=[FunctionToolset()])
    with pytest.raises(UninterceptableTool, match="tools="):
        h.register("send_email", SCHEMA, lambda to: None, tools=[lambda: None])
    assert led.rows == []


def test_gate13_the_mangled_accessor_is_a_known_limitation(chan, led):
    """The STATED LIMIT of an in-process boundary, asserted rather than left absent.

    ADDED 2026-08-28 (round 4). `harness.py` claimed "THE AGENT IS NOT REACHABLE."
    It is reachable, through the ordinary Python name-mangling idiom, and this
    spike's own files already use it: `LeakyHarness` below and `mutate.py`'s "expose
    the Agent" mutation both call `self._PhoenixHarness__build()`. The scanner
    `agents_reachable_from` skips every name starting with `_`, so it is blind to
    the only route that exists -- which makes gate 13's green result a statement
    about PUBLIC names and nothing more.

    So this test asserts the limitation is REAL. Name mangling is not access
    control. In-process, the tool author and the platform share an interpreter; the
    ledger boundary is enforced against ACCIDENT and against the SDK's own public
    surface, not against a hostile in-process caller. A boundary against a hostile
    in-process caller needs the process split of OQ-056. If a future change made
    this test fail, that would be good news and this test should be rewritten, not
    deleted.
    """
    h = harness(led)   # TestModel, which calls every tool it is shown
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))

    agent = h._PhoenixHarness__build()      # the route the scanner cannot see
    assert isinstance(agent, Agent), \
        "name mangling started to actually hide the Agent -- re-examine the claim"

    side: list[str] = []
    fts = FunctionToolset()
    fts.add_function(lambda to: side.append(f"send_email:{to}") or "ok",
                     name="send_email")
    with agent.override(toolsets=[fts]):
        agent.run_sync("go")

    assert side == ["send_email:a"], \
        "the limitation is stated as real; if the body no longer runs, say so"
    assert led.rows == [], \
        "and it runs with ZERO ledger rows -- that is the limit being recorded"
    assert chan.lines == [], "the harness's own registered body was not the one run"


def test_gate13_a_function_model_is_never_handed_a_native_tool(chan, led):
    """The delivery assertion, on a model that DOES support native tools.

    `FunctionModel.supported_native_tools()` returns `SUPPORTED_NATIVE_TOOLS`
    (`models/function.py:242-244`), so if any native tool could reach the model
    through this harness, this recorder would see it -- on the first request, on
    the resume request, and on the streaming path.
    """
    import asyncio
    seen: list[tuple] = []
    h = harness(led, model=_recorder_model(seen))
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))

    turn = h.run("email")
    assert isinstance(turn.output, DeferredToolRequests)
    results = h.resolve("run-1", turn.requests)
    h.resume(turn, results=results)

    streamed = harness(EffectLedger(), model=_recorder_model(seen))
    streamed.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    assert isinstance(asyncio.run(streamed.stream_output("email")), DeferredToolRequests)

    assert seen, "the recorder never ran -- the assertion below would be vacuous"
    assert all(nt == () for nt in seen), f"a native tool reached the model: {seen}"


def test_gate13_negative_control_exposing_the_agent_lets_the_override_through(led):
    """RULE 4 for the structural claim: put the `Agent` back, watch it break.

    This is review's own reproduction, executable. `LeakyHarness` re-exposes the
    agent exactly as `build_agent()` used to, and the override then delivers
    `WebSearchTool` to the model. So gate 13's green result comes from the
    harness's shape, not from something the SDK does incidentally.
    """
    from pydantic_ai.native_tools import WebSearchTool

    class LeakyHarness(PhoenixHarness):
        """The defect, restored, so its consequence can be measured."""

        def build_agent(self):
            return self._PhoenixHarness__build()

    seen: list[tuple] = []
    leaky = LeakyHarness(ledger=led, model=_recorder_model(seen, tool_name=""))
    leaky.register("send_email", SCHEMA, lambda to: None)

    assert agents_reachable_from(leaky) == ["build_agent()"], \
        "the scanner is inert if it cannot see a deliberately exposed Agent"

    agent = leaky.build_agent()
    with agent.override(native_tools=[WebSearchTool()]):
        agent.run_sync("search the web")

    assert seen and seen[-1] and isinstance(seen[-1][0], WebSearchTool), \
        "control is broken: the override delivered nothing, so the sealed " \
        "harness's empty recorder would prove nothing"
    assert led.rows == [], "and not one ledger row for a vendor-hosted tool"


def test_gate13_the_agent_runs_only_the_delegating_wrapper(chan, led, monkeypatch):
    """The toolset the SDK RUNS is not the one the harness built.

    ADDED 2026-08-28 (round 5). `__build`'s docstring said "an agent whose tools are
    all external, so the SDK cannot execute any" and `RESULT.md` said "the SDK is
    given no way to run it" -- both true of the `ExternalToolset` the harness
    constructs, and neither a statement about what the SDK puts around it.
    `Agent.__init__` AUTO-INJECTS `ToolSearch` and `PendingMessageDrainCapability`
    (`agent/__init__.py:630`, `_AUTO_INJECT_CAPABILITY_TYPES` at `:3955-3958`), and
    `ToolSearch` ALWAYS wraps the toolset in `ToolSearchToolset`
    (`capabilities/_tool_search.py:191-196`) whose `call_tool`
    (`toolsets/_tool_search.py:435-437`) runs `search_tools` LOCALLY instead of
    delegating -- while `_reject_sdk_surface` refuses a caller's `capabilities=` by
    name, on the stated ground that it delivers executable LOCAL bodies.

    It fails closed here, and the reason is a fact about the SDK's bytes rather than
    about this harness: no `ToolDefinition` the harness builds sets `defer_loading`,
    so the wrapper emits no `search_tools` tool. That is why both deciding modules
    are now pinned -- asserted first, so this gate cannot be green against bytes
    nobody checked.

    Rule 7: `ToolManager.for_run_step` is patched through `monkeypatch`, which
    restores it, and nothing outside this test's own objects is written.
    """
    from pydantic_ai.tool_manager import ToolManager

    for rel in ("capabilities/_tool_search.py", "toolsets/_tool_search.py"):
        assert rel in verify_pin.pinned(), \
            f"{rel} decides what wraps the boundary toolset and is unpinned"

    seen_toolsets: list[object] = []
    original = ToolManager.for_run_step

    async def recording(self, ctx):
        manager = await original(self, ctx)
        seen_toolsets.append(manager.toolset)
        return manager

    monkeypatch.setattr(ToolManager, "for_run_step", recording)

    seen_native: list[tuple] = []
    seen_fn: list[list[str]] = []

    def recorder(messages, info: AgentInfo):
        seen_native.append(tuple(info.model_request_parameters.native_tools))
        seen_fn.append([t.name for t in info.function_tools])
        return ModelResponse(parts=[TextPart("done")])

    h = harness(led, model=FunctionModel(recorder))
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    h.run("email")

    assert seen_toolsets, "the recorder never ran -- everything below would be vacuous"
    outer = seen_toolsets[0]
    assert type(outer).__name__ == "ToolSearchToolset", \
        f"the SDK's wrapping changed: it now runs {type(outer).__name__}"

    # ...and the wrapper chain bottoms out in the toolset THIS harness built, which
    # is identified by the very `_defs` list object it was constructed from.
    def flatten(ts, out):
        out.append(ts)
        wrapped = getattr(ts, "wrapped", None)
        if wrapped is not None:
            flatten(wrapped, out)
        for sub in getattr(ts, "toolsets", []) or []:
            flatten(sub, out)
        return out

    externals = [t for t in flatten(outer, []) if isinstance(t, ExternalToolset)]
    assert len(externals) == 1, f"expected one ExternalToolset, got {externals}"
    assert externals[0].tool_defs is h._defs, \
        "the ExternalToolset at the bottom is not the one the harness built"

    # The wrapper emits no tool of its own, so the model is shown only ours.
    assert seen_fn and all(names == ["send_email"] for names in seen_fn), \
        f"the SDK's wrapper added a tool the harness never declared: {seen_fn}"
    assert all(nt == () for nt in seen_native)

    # FAIL-CLOSED CONTROL: a model that CALLS the wrapper's local tool gets nowhere.
    # `ToolSearchToolset.call_tool` would run `_search_tools` in-SDK if the tool were
    # emitted; it is not, so the call cannot be routed at all.
    led2 = EffectLedger()

    def calls_search_tools(messages, info: AgentInfo):
        if not any(isinstance(pt, ToolCallPart) for m in messages
                   for pt in getattr(m, "parts", [])):
            return ModelResponse(parts=[ToolCallPart(
                "search_tools", {"query": "email"}, tool_call_id="ts-1")])
        return ModelResponse(parts=[TextPart("done")])

    h2 = harness(led2, model=FunctionModel(calls_search_tools))
    h2.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    turn2 = h2.run("find a tool")

    # Vacuity control for the control: the model really did call it and was refused,
    # so the empty side channel is a refusal rather than a call that never happened.
    transcript = [str(pt) for m in turn2.messages for pt in getattr(m, "parts", [])]
    assert any("Unknown tool name: 'search_tools'" in t for t in transcript), \
        f"the wrapper's local tool was never actually called: {transcript}"
    assert chan.lines == [], "the SDK-chosen wrapper reached a customer system"
    assert led2.rows == [], "an in-SDK tool ran with no ledger row"


# ============ RULE 7: the mutation runner owns what it mutates =============
def test_rule7_the_mutation_runner_never_writes_to_the_live_tree(tmp_path):
    """`mutate.py` used to rewrite `harness.py` IN PLACE.

    That is a rule-7 violation: the live tree is not uniquely owned by the
    mutation run, so a concurrent `make spike06` could import a deliberately
    broken harness. It now copies the spike into a directory it creates. This
    asserts the copy is complete and self-contained.
    """
    work = copy_spike(tmp_path / "spike")
    for name in SPIKE_FILES:
        assert (work / name).exists(), f"{name} missing from the copy"
    assert (work / "harness.py").read_text() == (HERE / "harness.py").read_text()
    assert work.resolve() != HERE
