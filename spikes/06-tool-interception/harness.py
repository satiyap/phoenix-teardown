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
import secrets
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets.external import ExternalToolset


class UninterceptableTool(Exception):
    """Raised when a tool cannot be routed through the ledger boundary.

    `spec/08` row 30c: an adapter that cannot route a tool through the ledger
    CANNOT REGISTER THAT TOOL. This exception is that rule, executable.
    """


# Every vendor-hosted tool Pydantic AI 2.35.0 ships. These execute on the PROVIDER's
# side, so `ExternalToolset` cannot express them and no ledger row can be guaranteed.
# Derived from `pydantic_ai.native_tools.__all__`-style exports rather than restated,
# and asserted against the installed SDK by `test_gate.py` so a new one cannot appear
# in a future version without a gate failing.
NATIVE_TOOL_NAMES: frozenset[str] = frozenset({
    "web_search", "code_execution", "file_search", "image_generation",
    "memory", "web_fetch", "x_search", "mcp_server", "advisor", "tool_search",
})


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
    claim_owner: str | None = None
    claim_token: str | None = None


class EffectLedger:
    """Append-only ledger. The authority; there is no other record of an effect."""

    def __init__(self) -> None:
        self._rows: list[LedgerRow] = []

    def append(self, row: LedgerRow) -> None:
        self._rows.append(row)

    def claim(self, tool_call_id: str, owner: str, token: str) -> None:
        """Phase 3. `spec/02-consistency.md:326`: ONLY a claimed row can become
        `indeterminate`, because `indeterminate` must mean "we took a lease,
        dispatched, and lost contact" -- never bookkeeping.

        Review caught this: the first harness moved `intended` straight to
        `indeterminate`, which the spec explicitly forbids.
        """
        for i, r in enumerate(self._rows):
            if r.tool_call_id == tool_call_id:
                if r.status != "intended":
                    raise AssertionError(
                        f"claim requires status 'intended', found {r.status!r}")
                self._rows[i] = replace(r, status="claimed",
                                        claim_owner=owner, claim_token=token)
                return
        raise AssertionError(f"claim for an unledgered call: {tool_call_id}")

    def settle(self, tool_call_id: str, status: str, result_json: str | None,
               *, token: str | None = None) -> None:
        """Phases 4-5. A settlement that follows a claim must be FENCED by its token.

        `spec/02`: settling does not require the run lease, but it must not be
        possible for a stale worker to overwrite the verdict of the claim holder.
        """
        for i, r in enumerate(self._rows):
            if r.tool_call_id != tool_call_id:
                continue
            if status == "indeterminate" and r.status != "claimed":
                raise AssertionError(
                    f"indeterminate requires a claimed row, found {r.status!r} "
                    "(spec/02-consistency.md:326)")
            if r.status == "claimed":
                if token is None:
                    raise AssertionError("settling a claimed row needs its claim token")
                if token != r.claim_token:
                    raise AssertionError("claim token mismatch: stale worker fenced out")
            elif r.status != "intended":
                continue
            self._rows[i] = replace(r, status=status, result_json=result_json)
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

    def _can_route(self, name: str, *, sdk_executable: bool) -> bool:
        """Can this tool be routed through the ledger?

        Two ways a tool escapes the boundary, and only the SECOND is real:

          * `sdk_executable=True` -- a caller-declared flag. Review was right that
            asserting on this alone is mechanism-shaped evidence: it tests a boolean
            Phoenix invented, not anything the SDK does.
          * a **native tool** (`pydantic_ai.native_tools`: `WebSearchTool`,
            `CodeExecutionTool`, `FileSearchTool`, ...). These execute PROVIDER-SIDE.
            `grep NativeToolCallPart _tool_execution.py` returns nothing -- they never
            enter the tool-execution pipeline at all, so no toolset can gate them and
            `ExternalToolset` cannot express them: there is no local body to withhold.
        """
        return not sdk_executable and name not in NATIVE_TOOL_NAMES

    def register(self, name: str, schema: dict[str, Any], impl: Callable[..., Any],
                 *, sdk_executable: bool = False) -> None:
        """Register a tool. Anything unroutable is REFUSED (spec/08 row 30c)."""
        if not self._can_route(name, sdk_executable=sdk_executable):
            raise UninterceptableTool(
                f"{name!r} cannot be routed through the ledger, so it cannot be registered")
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

        # Phase 3: CLAIM before dispatching. `spec/02-consistency.md:326` -- only a
        # claimed row may become `indeterminate`, so a harness that dispatches without
        # claiming cannot express real uncertainty. Review caught the first version
        # moving `intended` -> `indeterminate` directly, which the spec forbids.
        owner, token = f"worker:{run_id}", secrets.token_hex(8)
        self.ledger.claim(call.tool_call_id, owner, token)

        try:
            result = impl(**args)
        except Exception:
            # Dispatched, outcome unknown: the customer system may or may not have been
            # touched. That is exactly `indeterminate`, and it surfaces for a human.
            self.ledger.settle(call.tool_call_id, "indeterminate", None, token=token)
            raise
        self.ledger.settle(call.tool_call_id, "settled",
                           json.dumps(result, sort_keys=True), token=token)
        return result

    def resolve(self, run_id: str, requests: DeferredToolRequests) -> dict[str, Any]:
        """Ledger and dispatch every pending call; return results by call id."""
        out: dict[str, Any] = {}
        for call in requests.calls:
            self.intend(run_id, call)
            out[call.tool_call_id] = self.dispatch(run_id, call)
        return out
