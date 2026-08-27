"""SPIKE 06 GATE — no registered tool reaches a customer system unledgered.

INVARIANT, STATED FIRST (rule 1):
    A tool body executes only after the platform has written an `effect_ledger`
    row for that exact call. There is no path -- construction, model-driven
    call, resume, approval, streaming, or error -- by which a registered tool
    body runs without one.

THE ORACLE IS INDEPENDENT (rule 5). Every tool in this file writes a line to a
real file in `tmp_path`. `harness.py` never reads or writes that file, so the
assertion is about OBSERVABLE SIDE EFFECTS, not about what the SDK reports
having done. That distinction is the whole point: a test that trusted the SDK's
own accounting would pass even if the SDK were lying.

TESTED THROUGH THE PUBLIC BOUNDARY (rule 3): `Agent.run_sync`,
`Agent.run_stream`, `DeferredToolRequests`, `build_results`,
`deferred_tool_results`. No private attribute is poked to force a result.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets.approval_required import ApprovalRequiredToolset
from pydantic_ai.toolsets.external import ExternalToolset
from pydantic_ai.toolsets.function import FunctionToolset

from harness import EffectLedger, LedgerRow, PhoenixHarness, UninterceptableTool

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


# ============ CONTROL 0: the oracle can detect a real effect ================
# Rule 4, learned the hard way: assert a clean baseline AND assert the detector
# actually fires, before trusting any green result from it.
def test_control0_side_channel_detects_execution(chan):
    assert chan.lines == []
    chan.touch("send_email")
    assert chan.lines == ["send_email"]


# ============ GATE 1: zero registered tools ================================
def test_gate1_no_tools_means_no_executable_path(chan, led):
    h = PhoenixHarness(ledger=led)
    agent = h.build_agent(TestModel())
    result = agent.run_sync("do something")
    assert not isinstance(result.output, DeferredToolRequests)
    assert chan.lines == []
    assert led.rows == []


# ============ GATE 2: a registered tool never runs inside the SDK ==========
def test_gate2_run_halts_and_body_never_runs(chan, led):
    h = PhoenixHarness(ledger=led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    agent = h.build_agent(TestModel())

    result = agent.run_sync("email someone")

    assert isinstance(result.output, DeferredToolRequests), \
        "the run must END on the deferred call, not execute it"
    assert [c.tool_name for c in result.output.calls] == ["send_email"]
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


# ============ GATE 3: exactly one ledger row per call, intent before act ===
def test_gate3_ledger_row_precedes_execution(chan, led):
    order: list[str] = []

    class Watched(EffectLedger):
        def append(self, row):
            order.append(f"ledger:{row.status}")
            super().append(row)

    led2 = Watched()
    h = PhoenixHarness(ledger=led2)
    h.register("send_email", SCHEMA,
               lambda to: (order.append("execute"), chan.touch(f"send_email:{to}"))[1])
    agent = h.build_agent(TestModel())

    req = agent.run_sync("email").output
    h.resolve("run-1", req)

    assert order == ["ledger:intended", "execute"], f"wrong order: {order}"
    assert chan.lines == ["send_email:a"]
    rows = led2.rows_for(req.calls[0].tool_call_id)
    assert len(rows) == 1 and rows[0].status == "settled"


def test_gate3_settling_an_unledgered_call_is_refused(led):
    """Mutation control: the ledger cannot be made to settle what it never intended."""
    with pytest.raises(AssertionError, match="unledgered"):
        led.settle("never-seen", "settled", None)


# ============ GATE 4: THE RESUME PATH ======================================
# `_tool_execution.py:399`: when `tool_call_results` is supplied,
# `executable_function_kinds` becomes ('function','unknown','external','unapproved').
# External kinds DO flow through the regular pipeline on resume. If a body could
# run anywhere, it is here. This gate exists because the source said so.
def test_gate4_resume_consumes_platform_result_without_executing(chan, led):
    h = PhoenixHarness(ledger=led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    agent = h.build_agent(TestModel())

    r1 = agent.run_sync("email")
    req = r1.output
    call_id = req.calls[0].tool_call_id

    # The platform dispatches, exactly once, through its own boundary.
    results = h.resolve("run-1", req)
    assert chan.lines == ["send_email:a"]

    r2 = agent.run_sync(message_history=r1.all_messages(),
                        deferred_tool_results=req.build_results(
                            calls={call_id: results[call_id]}))

    # THE ASSERTION: resume did not re-run the body. One dispatch, one effect.
    assert chan.lines == ["send_email:a"], "resume re-executed the tool body"
    assert len(led.rows_for(call_id)) == 1
    returned = [p.content for m in r2.all_messages() for p in m.parts
                if type(p).__name__ == "ToolReturnPart"]
    assert returned == ["did:send_email:a"], \
        "the model must observe the PLATFORM's result, not the SDK's"


def test_gate4_negative_control_resume_without_platform_dispatch(chan, led):
    """If the platform never dispatches, the customer system is never touched.

    Proves gate 4's green result comes from the platform's dispatch and not from
    something the SDK does incidentally.
    """
    h = PhoenixHarness(ledger=led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    agent = h.build_agent(TestModel())

    r1 = agent.run_sync("email")
    req = r1.output
    agent.run_sync(message_history=r1.all_messages(),
                   deferred_tool_results=req.build_results(
                       calls={req.calls[0].tool_call_id: "fabricated"}))

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


# ============ GATE 6: row 30c is executable, against the REAL admission path
def test_gate6_every_native_tool_the_sdk_ships_is_refused(led):
    """`spec/08` row 30c against Pydantic AI's ACTUAL vendor-hosted tools.

    An earlier version asserted only on `sdk_executable=True` -- a boolean Phoenix
    invented. Review was right to call that mechanism-shaped evidence: it tested
    our own flag, not the SDK's real native-tool path. This enumerates the tools
    the installed SDK actually ships and asserts each is refused BY NAME.
    """
    import pydantic_ai.native_tools as nt

    shipped = {}
    for attr in dir(nt):
        if attr.endswith("Tool") and not attr.startswith("Abstract"):
            try:
                shipped[getattr(nt, attr)().kind] = attr
            except Exception:
                pass
    assert shipped, "could not enumerate the SDK's native tools"

    h = PhoenixHarness(ledger=led)
    for kind, cls in shipped.items():
        with pytest.raises(UninterceptableTool, match="cannot be routed"):
            h.register(kind, SCHEMA, lambda **k: "x")
    assert led.rows == []


def test_gate6_native_tool_list_is_complete(led):
    """If a FUTURE SDK version adds a native tool, this fails rather than admitting it.

    Fail-closed by construction: the harness's refusal list is compared against the
    installed SDK, so a new vendor-hosted tool cannot slip through unnoticed.
    """
    import pydantic_ai.native_tools as nt
    from harness import NATIVE_TOOL_NAMES

    shipped = set()
    for attr in dir(nt):
        if attr.endswith("Tool") and not attr.startswith("Abstract"):
            try:
                shipped.add(getattr(nt, attr)().kind)
            except Exception:
                pass
    missing = shipped - NATIVE_TOOL_NAMES
    assert not missing, f"SDK ships native tools the harness would admit: {sorted(missing)}"


def test_gate6_native_tools_never_enter_the_execution_pipeline():
    """WHY the refusal is structural, asserted against the SDK's own source.

    `_tool_execution.py` -- the only module that runs tool bodies -- contains no
    reference to `NativeToolCallPart`. Native tools arrive as transcript parts from
    the provider; they are never dispatched locally. So there is no local body for
    `ExternalToolset` to withhold, which is why this is a structural impossibility
    rather than a policy choice.
    """
    import os
    import pydantic_ai
    src = Path(os.path.dirname(pydantic_ai.__file__)) / "_tool_execution.py"
    body = src.read_text()
    assert "NativeToolCallPart" not in body, \
        "native tools now enter the execution pipeline -- re-examine the refusal"
    assert "'external'" in body, "sanity: external kinds ARE handled here"


def test_gate6_caller_declared_flag_is_also_refused(led):
    """The original assertion, kept but demoted to what it actually proves."""
    h = PhoenixHarness(ledger=led)
    with pytest.raises(UninterceptableTool, match="cannot be routed"):
        h.register("send_email", SCHEMA, lambda to: None, sdk_executable=True)
    assert h.build_agent(TestModel()) is not None


def test_gate6_test_model_refuses_native_tools_entirely(led):
    """Independent corroboration from the SDK: native tools are MODEL-side.

    `models/test.py:252` raises `UserError('TestModel does not support built-in
    tools')`. A tool the model must support is a tool the platform cannot
    intercept -- the clearest possible statement that this is not our layer.
    """
    from pydantic_ai import Agent
    from pydantic_ai.exceptions import UserError
    from pydantic_ai.native_tools import WebSearchTool

    agent = Agent(TestModel(), output_type=[str, DeferredToolRequests])
    with pytest.raises(UserError, match="does not support built-in tools"):
        with agent.override(native_tools=[WebSearchTool()]):
            agent.run_sync("search the web")


def test_gate6_external_toolset_refuses_direct_invocation():
    """The SDK's own guarantee, asserted rather than assumed.

    `toolsets/external.py:44` raises unconditionally. If a future version made
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
    h = PhoenixHarness(ledger=led, policy=lambda n, a: "deny")
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    agent = h.build_agent(TestModel())

    req = agent.run_sync("email").output
    out = h.resolve("run-1", req)

    assert out[req.calls[0].tool_call_id] == "DENIED by policy"
    assert chan.lines == [], "denied call still reached the customer system"
    rows = led.rows_for(req.calls[0].tool_call_id)
    assert [r.status for r in rows] == ["denied"], \
        "a denial must be recorded, not silently dropped"


# ============ GATE 8: streaming is not a side door =========================
def test_gate8_streamed_run_does_not_execute_the_body(chan, led):
    """Streaming is a different code path through `_tool_execution.py`.

    A boundary that holds only on the buffered path is not a boundary.
    """
    import asyncio
    h = PhoenixHarness(ledger=led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    agent = h.build_agent(TestModel())

    async def run():
        async with agent.run_stream("email") as stream:
            async for _ in stream.stream_output(debounce_by=None):
                pass
            return await stream.get_output()

    output = asyncio.run(run())
    assert isinstance(output, DeferredToolRequests)
    assert chan.lines == [], "the streaming path executed a registered tool body"


# ============ GATE 9: a hallucinated tool cannot invent a path =============
def test_gate9_unknown_tool_never_dispatches(chan, led):
    h = PhoenixHarness(ledger=led)
    h.register("send_email", SCHEMA, lambda to: chan.touch("send_email"))
    agent = h.build_agent(TestModel())
    req = agent.run_sync("email").output
    call = req.calls[0]

    class Fake:
        tool_call_id = call.tool_call_id
        tool_name = "rm_rf"
        args = {}

    h.intend("run-1", Fake())
    with pytest.raises(UninterceptableTool, match="no platform dispatcher"):
        h.dispatch("run-1", Fake())
    assert chan.lines == []
    assert [r.status for r in led.rows_for(call.tool_call_id)] == ["failed"]


# ============ GATE 10: many calls in one step stay distinct ================
def test_gate10_parallel_calls_get_one_row_each(chan, led):
    """A step with three tool calls must produce three ledger rows.

    If `tool_call_id`s collided, `settle()` would overwrite a sibling and one
    effect would vanish from the ledger while still having happened.
    """
    h = PhoenixHarness(ledger=led)
    for n in ("send_email", "delete_row", "charge_card"):
        h.register(n, SCHEMA, lambda to, _n=n: chan.touch(f"{_n}:{to}"))
    agent = h.build_agent(TestModel())

    req = agent.run_sync("do all three").output
    assert len(req.calls) == 3
    h.resolve("run-1", req)

    assert len(led.rows) == 3
    assert len({r.tool_call_id for r in led.rows}) == 3, "tool_call_id collision"
    assert sorted(chan.lines) == ["charge_card:a", "delete_row:a", "send_email:a"]
    assert all(r.status == "settled" for r in led.rows)


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

    h = PhoenixHarness(ledger=led)
    h.register("send_email", SCHEMA, boom)
    agent = h.build_agent(TestModel())
    req = agent.run_sync("email").output

    with pytest.raises(RuntimeError, match="smtp exploded"):
        h.resolve("run-1", req)

    assert chan.lines == ["send_email:a"], "the body must have actually run"
    rows = led.rows_for(req.calls[0].tool_call_id)
    assert [r.status for r in rows] == ["indeterminate"], \
        "a dispatched effect that crashed must surface, not look unstarted"


def test_gate11_negative_control_intended_would_hide_the_effect(chan, led):
    """Mutation control for gate 11: prove the assertion discriminates.

    A ledger that keeps the row at `intended` must FAIL the gate above. Without
    this control, gate 11 would pass against either behaviour.
    """
    class SloppyLedger(EffectLedger):
        def settle(self, tool_call_id, status, result_json, *, token=None):
            if status == "indeterminate":
                return  # the defect: a crash leaves the row untouched
            super().settle(tool_call_id, status, result_json, token=token)

    def boom(to):
        chan.touch(f"send_email:{to}")
        raise RuntimeError("smtp exploded")

    sloppy = SloppyLedger()
    h = PhoenixHarness(ledger=sloppy)
    h.register("send_email", SCHEMA, boom)
    req = h.build_agent(TestModel()).run_sync("email").output
    with pytest.raises(RuntimeError):
        h.resolve("run-1", req)

    statuses = [r.status for r in sloppy.rows_for(req.calls[0].tool_call_id)]
    assert statuses == ["claimed"], \
        "control is broken if the row settled; it must be left at the claim"


# ============ GATE 12: the claim/fence lifecycle, per spec/02 ==============
def test_gate12_indeterminate_requires_a_claimed_row(led):
    """`spec/02-consistency.md:326`: "a never-claimed row ... cannot produce
    `indeterminate`".

    Review found the first harness moving `intended` straight to `indeterminate`,
    which made row 30e's VERIFIED label false: the mechanism the spec describes
    (claim, then lose contact) was not present at all. The ledger now refuses.
    """
    led.append(LedgerRow("run-1", "tc-1", "send_email", "{}", "intended"))
    with pytest.raises(AssertionError, match="indeterminate requires a claimed row"):
        led.settle("tc-1", "indeterminate", None)


def test_gate12_effect_is_claimed_before_dispatch(chan, led):
    """The full phase order is observable: intended -> claimed -> settled."""
    seen: list[str] = []

    class Traced(EffectLedger):
        def append(self, row):
            seen.append(f"append:{row.status}")
            super().append(row)

        def claim(self, tool_call_id, owner, token):
            seen.append("claim")
            super().claim(tool_call_id, owner, token)

        def settle(self, tool_call_id, status, result_json, *, token=None):
            seen.append(f"settle:{status}")
            super().settle(tool_call_id, status, result_json, token=token)

    traced = Traced()
    h = PhoenixHarness(ledger=traced)
    h.register("send_email", SCHEMA,
               lambda to: (seen.append("EXECUTE"), chan.touch(f"send_email:{to}"))[1])
    req = h.build_agent(TestModel()).run_sync("email").output
    h.resolve("run-1", req)

    assert seen == ["append:intended", "claim", "EXECUTE", "settle:settled"], seen
    row = traced.rows_for(req.calls[0].tool_call_id)[0]
    assert row.claim_owner == "worker:run-1" and row.claim_token


def test_gate12_a_stale_worker_is_fenced_out(chan, led):
    """A claim token that is not the holder's cannot overwrite the verdict.

    Without the fence, a stale worker could settle an effect it does not own --
    including overwriting an `indeterminate` verdict that a human is investigating.
    """
    h = PhoenixHarness(ledger=led)
    h.register("send_email", SCHEMA, lambda to: chan.touch(f"send_email:{to}"))
    req = h.build_agent(TestModel()).run_sync("email").output
    call_id = req.calls[0].tool_call_id

    led.append(LedgerRow("run-1", call_id, "send_email", "{}", "intended"))
    led.claim(call_id, "worker:run-1", "the-real-token")

    with pytest.raises(AssertionError, match="stale worker fenced out"):
        led.settle(call_id, "settled", '"forged"', token="a-guess")
    with pytest.raises(AssertionError, match="needs its claim token"):
        led.settle(call_id, "settled", '"forged"')
    assert led.rows_for(call_id)[0].status == "claimed", "the fence must hold the row"


def test_gate12_claim_requires_intent_first(led):
    """Claiming a row that was never intended is refused, so the phases cannot be skipped."""
    with pytest.raises(AssertionError, match="claim for an unledgered call"):
        led.claim("tc-nope", "worker:x", "tok")
    led.append(LedgerRow("run-1", "tc-2", "send_email", "{}", "settled"))
    with pytest.raises(AssertionError, match="claim requires status 'intended'"):
        led.claim("tc-2", "worker:x", "tok")
