"""SPIKE 06 — the Phoenix side of the tool boundary, on Pydantic AI 2.35.0.

This is the implementation under test. It is deliberately NOT the test oracle
(`VERIFICATION-RULES.md` rule 5): the gate asserts through a filesystem
side-channel that this module never touches.

The claim being tested is NOT "we can wrap the decorator". Reading the source
showed Pydantic AI already has the shape Phoenix needs:

  * `toolsets/external.py:44` — `ExternalToolset.call_tool` raises
    `NotImplementedError('External tools cannot be called directly')`
    UNCONDITIONALLY. An external tool has no executable body inside the SDK.
  * `_deferred.py:27` — `DeferredToolRequests` used as an `output_type` ENDS the
    run and hands back the pending `ToolCallPart`s.
  * `toolsets/approval_required.py:29` — raises `ApprovalRequired` BEFORE
    delegating to `super().call_tool`, i.e. fail-closed.

So the boundary is a TOOLSET, not a decorator. The claim under test is the
stronger one: **no registered tool reaches a customer system without an
`effect_ledger` row.**
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets.external import ExternalToolset


class UninterceptableTool(Exception):
    """Raised when a tool cannot be routed through the ledger boundary.

    `spec/08` row 30c: an adapter that cannot disable native execution for a
    tool CANNOT REGISTER THAT TOOL. This exception is that rule, executable.
    """


@dataclass(frozen=True)
class LedgerRow:
    """One row of the effect ledger. Mirrors `spec/01-schema.md.effect_ledger`.

    `status` follows the five-phase lifecycle from `spec/02-consistency.md`:
    intended -> awaiting_approval -> claimed -> dispatched -> settled.
    """

    run_id: str
    tool_call_id: str
    tool_name: str
    args_json: str
    status: str
    result_json: str | None = None


class EffectLedger:
    """Append-only ledger. The authority; there is no other record of an effect."""

    def __init__(self) -> None:
        self._rows: list[LedgerRow] = []

    def append(self, row: LedgerRow) -> None:
        self._rows.append(row)

    def settle(self, tool_call_id: str, status: str, result_json: str | None) -> None:
        for i, r in enumerate(self._rows):
            if r.tool_call_id == tool_call_id and r.status in ("claimed", "intended"):
                self._rows[i] = LedgerRow(r.run_id, r.tool_call_id, r.tool_name,
                                          r.args_json, status, result_json)
                return
        raise AssertionError(f"settle for an unledgered call: {tool_call_id}")

    @property
    def rows(self) -> list[LedgerRow]:
        return list(self._rows)

    def rows_for(self, tool_call_id: str) -> list[LedgerRow]:
        return [r for r in self._rows if r.tool_call_id == tool_call_id]

    def names(self) -> list[str]:
        return [r.tool_name for r in self._rows]


@dataclass
class PhoenixHarness:
    """Wraps a Pydantic AI agent so every tool call crosses the ledger.

    Tools are registered as DECLARATIONS plus a platform-side dispatcher. The
    SDK is told the tool exists so the model can call it; the SDK is given no
    way to run it.
    """

    ledger: EffectLedger
    policy: Callable[[str, dict[str, Any]], str] = lambda name, args: "allow"
    _defs: list[ToolDefinition] = field(default_factory=list)
    _dispatch: dict[str, Callable[..., Any]] = field(default_factory=dict)

    def register(self, name: str, schema: dict[str, Any], impl: Callable[..., Any],
                 *, sdk_executable: bool = False) -> None:
        """Register a tool. `sdk_executable=True` is REFUSED (row 30c)."""
        if sdk_executable:
            raise UninterceptableTool(
                f"{name!r} cannot disable native execution, so it cannot be registered")
        self._defs.append(ToolDefinition(name=name, parameters_json_schema=schema))
        self._dispatch[name] = impl

    def build_agent(self, model: Any) -> Agent:
        """An agent whose tools are all external, so the SDK cannot execute any."""
        toolset = ExternalToolset(self._defs) if self._defs else None
        return Agent(model,
                     output_type=[str, DeferredToolRequests],
                     toolsets=[toolset] if toolset else [])

    # ---- the boundary itself -------------------------------------------------

    def intend(self, run_id: str, call: Any) -> None:
        """Phase 1: record intent BEFORE any dispatch decision."""
        self.ledger.append(LedgerRow(run_id, call.tool_call_id, call.tool_name,
                                     json.dumps(call.args, sort_keys=True), "intended"))

    def dispatch(self, run_id: str, call: Any) -> Any:
        """Phases 2-5. Nothing reaches the impl except through here."""
        verdict = self.policy(call.tool_name, call.args or {})
        if verdict == "deny":
            self.ledger.settle(call.tool_call_id, "denied", None)
            return "DENIED by policy"
        impl = self._dispatch.get(call.tool_name)
        if impl is None:
            self.ledger.settle(call.tool_call_id, "failed", None)
            raise UninterceptableTool(f"no platform dispatcher for {call.tool_name!r}")
        args = call.args if isinstance(call.args, dict) else json.loads(call.args or "{}")
        # `spec/02-consistency.md:326-348`: a DISPATCHED effect must never be left with
        # no verdict. If the body raises, we cannot know whether the customer system was
        # touched, so the row becomes `indeterminate` -- which is exactly the state that
        # surfaces for a human. Leaving it at `intended` would be a lie: `intended` is
        # indistinguishable from an effect that never started.
        try:
            result = impl(**args)
        except Exception:
            self.ledger.settle(call.tool_call_id, "indeterminate", None)
            raise
        self.ledger.settle(call.tool_call_id, "settled", json.dumps(result, sort_keys=True))
        return result

    def resolve(self, run_id: str, requests: DeferredToolRequests) -> dict[str, Any]:
        """Ledger and dispatch every pending call; return results by call id."""
        out: dict[str, Any] = {}
        for call in requests.calls:
            self.intend(run_id, call)
            out[call.tool_call_id] = self.dispatch(run_id, call)
        return out
