"""SPIKE 06 — the Phoenix side of the tool boundary, on Pydantic AI 2.35.0.

This is the implementation under test. It is deliberately NOT the test oracle
(`VERIFICATION-RULES.md` rule 5): the gate asserts through a filesystem
side-channel that this module never touches.

The claim being tested is NOT "we can wrap the decorator". Reading the source
showed Pydantic AI already has the shape Phoenix needs:

  * `toolsets/external.py:46` — `ExternalToolset.call_tool` raises
    `NotImplementedError('External tools cannot be called directly')`
    UNCONDITIONALLY. An external tool has no executable body inside the SDK.
  * `_deferred.py:27` — `DeferredToolRequests` used as an `output_type` ENDS the
    run and hands back the pending `ToolCallPart`s.
  * `toolsets/approval_required.py:29` — raises `ApprovalRequired` BEFORE
    delegating to `super().call_tool`, i.e. fail-closed.

So the boundary is a TOOLSET, not a decorator. The claim under test is the
stronger one: **no registered tool reaches a customer system without an
`effect_ledger` row.**

REVISED 2026-08-27 (round 3), after review found the boundary was not actually
closed:

  * `build_agent()` returned a RAW `Agent`. Everything below was then advisory:
    a caller holding that object can call
    `agent.override(native_tools=[WebSearchTool()])`, and against a model that
    supports native tools (`FunctionModel` does — `models/function.py:242`) the
    native tool is delivered to the model with no Phoenix involvement at all.
    The old gate only showed that `TestModel` refuses built-in tools, which is a
    fact about `TestModel`, not about this boundary. **There is now no public
    accessor that yields an `Agent`**, and `native_tools=` / `toolsets=` from a
    caller are refused at registration.
  * The ledger used a status `'settled'` that `spec/01-schema.md:332` does not
    define, allowed `intended -> settled` with no claim, owner or token, and
    omitted the run-lease predicate of `spec/02-consistency.md:227`. It now
    implements the statuses and the phase predicates those two documents state.
"""
from __future__ import annotations

import inspect
import json
import secrets
import time
from dataclasses import dataclass, replace
from typing import Any, Callable

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets.external import ExternalToolset


class UninterceptableTool(Exception):
    """Raised when a tool cannot be routed through the ledger boundary.

    `spec/08` row 30c: an adapter that cannot route a tool through the ledger
    CANNOT REGISTER THAT TOOL. This exception is that rule, executable.
    """


class PolicyVerdictInvalid(Exception):
    """A policy returned something other than a known verdict. Fail CLOSED.

    ADDED 2026-08-28 (OQ-065). `dispatch` compared the verdict to the literal
    `"deny"` and ran the body on anything else — `"DENY"`, `None`,
    `"require_approval"` all executed. A verdict is an enum, not a string; an
    unknown one is a bug in the policy, never permission."""


POLICY_VERDICTS: frozenset[str] = frozenset({"allow", "deny", "require_approval"})


class LedgerRefused(Exception):
    """A ledger transition whose predicate did not hold.

    The SQL of `spec/02-consistency.md:196-322` expresses each phase as one
    `UPDATE ... WHERE <predicate>`; "0 rows updated" is the refusal. This
    exception is that zero-row result, in process.
    """


# Every vendor-hosted tool Pydantic AI 2.35.0 ships, BY KIND. These execute on the
# PROVIDER's side, so `ExternalToolset` cannot express them and no ledger row can be
# guaranteed.
#
# This list is written out DELIBERATELY rather than derived from
# `pydantic_ai.native_tools.NATIVE_TOOL_TYPES`. Deriving it would make the gate a
# tautology (rule 5): the harness and the oracle would read the same dict, and a new
# vendor-hosted tool would be admitted to the allow-list automatically, silently, by
# the very upgrade the gate exists to catch. `test_gate.py` compares this literal
# against the installed SDK's registry IN BOTH DIRECTIONS, so drift is a failure.
NATIVE_TOOL_NAMES: frozenset[str] = frozenset({
    "web_search", "code_execution", "file_search", "image_generation",
    "memory", "web_fetch", "x_search", "mcp_server", "advisor", "tool_search",
})

# `spec/01-schema.md:332` — `CREATE TYPE effect_status AS ENUM (...)`. There is no
# `settled`; the previous harness invented one. The three subsets below are the
# `effect_claim_fields_together` CHECK of `spec/01-schema.md:377-384`, in process.
EFFECT_STATUS: frozenset[str] = frozenset({
    "intended", "awaiting_approval", "claimed",
    "succeeded", "failed", "denied", "abandoned", "indeterminate",
})
UNCLAIMED_STATUS: frozenset[str] = frozenset(
    {"intended", "awaiting_approval", "denied", "abandoned"})
CLAIMED_STATUS: frozenset[str] = frozenset(
    {"claimed", "succeeded", "failed", "indeterminate"})
COMPLETED_STATUS: frozenset[str] = frozenset({"succeeded", "failed"})
SETTLEABLE_STATUS: frozenset[str] = frozenset({"succeeded", "failed", "indeterminate"})

# `spec/02-consistency.md:463` fixes the TTLs: "run lease 60s with renewal every 20s;
# effect claim 5 min, no renewal". CORRECTED 2026-08-28 (round 4): this was 300.0, five
# times the specified run lease, which is also why no gate could observe a run lease
# expiring while an effect claim was still open (the asymmetry of `spec/02:268-286`).
# The gates pin the clock, so no assertion depends on the value.
RUN_LEASE_SECONDS = 60.0
EFFECT_LEASE_SECONDS = 300.0


@dataclass(frozen=True)
class RunLease:
    """The run lease of `spec/02-consistency.md:246` predicate (b), simulated.

    Real form: a row in `run_leases` with `holder`, `fence_token`, `expires_at`,
    checked INSIDE the claim `UPDATE` so the check and the claim cannot interleave.
    Here it is an object the claim must be handed; the predicate is the same.
    """

    run_id: str
    holder: str
    fence_token: str
    expires_at: float

    def authorises(self, run_id: str, holder: str, fence: str | None,
                   now: float) -> bool:
        """ADDED 2026-08-28 (round 4): the FENCE half of predicate (b).

        `spec/02-consistency.md:248` states the predicate as
        `... AND l.holder=$worker AND l.fence_token=$fence AND l.expires_at > now()`,
        and `spec/02:440-443` says it must appear in every fenced write precisely
        because a lease row holding a *higher* token still matches an EXISTS that
        omits the token, so the stale worker's write lands. Until now `fence_token`
        was stored (`:113`) and never read anywhere in this spike, so only the
        holder and expiry halves were implemented. A caller that supplies no fence
        fails closed.
        """
        return (self.run_id == run_id and self.holder == holder
                and fence is not None and self.fence_token == fence
                and self.expires_at > now)


def args_json_of(args: Any) -> str:
    """The `request_digest` stand-in (`LedgerRow.args_json`), computed exactly ONE way.

    ADDED 2026-08-28 (round 5). `intend()` WRITES this string onto the row and
    `dispatch()` now COMPARES the call it is about to execute against it, so the two
    must not be able to disagree about the same arguments. A second, slightly
    different expression at the comparison site (`json.dumps(call.args or {}, ...)`)
    would make `args=None` and `args={}` collide.
    """
    return json.dumps(args, sort_keys=True)


@dataclass(frozen=True)
class LedgerRow:
    """One row of the effect ledger. Mirrors `spec/01-schema.md.effect_ledger`.

    `status` is one of `effect_status` (`spec/01-schema.md:332`) and NOTHING else.
    The lifecycle is `spec/02-consistency.md`'s five phases:
    intent -> (approval) -> claim -> dispatch -> settle.
    """

    run_id: str
    tool_call_id: str          # stands in for `idempotency_key`
    tool_name: str             # stands in for `kind`
    args_json: str             # stands in for `request_digest`
    status: str
    result_json: str | None = None      # `result_ref`
    error_code: str | None = None
    claim_owner: str | None = None
    claim_token: str | None = None
    lease_expires_at: float | None = None
    completed_at: float | None = None


class EffectLedger:
    """Append-only ledger. The authority; there is no other record of an effect.

    Every method below is one of the `UPDATE`s in `spec/02-consistency.md:196-322`,
    with the same predicate. A predicate that does not hold raises `LedgerRefused`,
    which is that statement's zero-row result.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._rows: list[LedgerRow] = []
        # Public, so the gate can pin the clock without poking a private attribute.
        self.clock = clock

    # ---- the schema CHECK constraints, in process ---------------------------
    @staticmethod
    def _check(row: LedgerRow) -> None:
        if row.status not in EFFECT_STATUS:
            raise LedgerRefused(
                f"{row.status!r} is not an effect_status (spec/01-schema.md:332); "
                f"valid: {sorted(EFFECT_STATUS)}")
        claimed = row.claim_owner is not None and row.claim_token is not None \
            and row.lease_expires_at is not None
        blank = row.claim_owner is None and row.claim_token is None \
            and row.lease_expires_at is None
        if row.status in UNCLAIMED_STATUS and not blank:
            raise LedgerRefused(
                f"effect_claim_fields_together: {row.status!r} must carry no owner, "
                "token or lease (spec/01-schema.md:378)")
        if row.status in CLAIMED_STATUS and not claimed:
            raise LedgerRefused(
                f"effect_claim_fields_together: {row.status!r} requires owner, token "
                "and lease (spec/01-schema.md:381)")
        if (row.status in COMPLETED_STATUS) != (row.completed_at is not None):
            raise LedgerRefused(
                "CHECK ((status IN ('succeeded','failed')) = (completed_at IS NOT NULL))"
                " (spec/01-schema.md:374)")

    def _index(self, tool_call_id: str) -> int:
        for i, r in enumerate(self._rows):
            if r.tool_call_id == tool_call_id:
                return i
        raise LedgerRefused(f"no ledger row for {tool_call_id!r}")

    def _replace(self, i: int, **kw: Any) -> None:
        row = replace(self._rows[i], **kw)
        self._check(row)
        self._rows[i] = row

    # ---- phase 1: intent ----------------------------------------------------
    def append(self, row: LedgerRow) -> None:
        """`spec/01-schema.md:366-367` — THE PRIMITIVE: recording intent is an
        insert, and `PRIMARY KEY (tenant_id, idempotency_key)` makes losing the race
        a conflict. `spec/02-consistency.md:202-204` makes a duplicate intent a
        no-op: `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING` — "no row => this
        effect already exists. Read it and DO NOT re-derive intent."

        ADDED 2026-08-28 (round 4). This appended unconditionally, so the ledger had
        no key uniqueness at all: intending the same call twice left TWO rows, and
        because `_index()` returns the FIRST match the duplicate was permanently
        unreachable and sat at `intended` forever — the exact state a stuck-effect
        sweep is meant to never see. DO NOTHING is chosen over raising to match the
        spec's statement, which is a no-op and not an error; the caller's next read
        finds the existing row.

        CORRECTED 2026-08-28 (round 5). The round-4 guard read
        `r.tool_call_id == row.tool_call_id and r.run_id == row.run_id`, which is the
        SECONDARY constraint `UNIQUE (tenant_id, idempotency_key, run_id)`
        (`spec/01-schema.md:372`), not the `PRIMARY KEY (tenant_id, idempotency_key)`
        (`spec/01-schema.md:367`) this docstring quotes, and not the conflict target of
        `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING`
        (`spec/02-consistency.md:202`), which does NOT contain `run_id`. Measured at
        that commit through the public surface: `resolve('run-1', ...)` then
        `resolve('run-2', ...)` for one call left TWO rows for one key —
        `[('run-1', ..., 'succeeded'), ('run-2', ..., 'intended')]` — and because
        `_index()` returns the FIRST match the run-2 row was permanently unreachable
        and sat at `intended` forever. The `run_id` conjunct is gone; which run a
        surviving row belongs to is now checked explicitly by
        `PhoenixHarness.dispatch`, which refuses to execute another run's effect.
        """
        self._check(row)
        if any(r.tool_call_id == row.tool_call_id for r in self._rows):
            return  # ON CONFLICT (tenant_id, idempotency_key) DO NOTHING (spec/02:202)
        self._rows.append(row)

    # ---- phase 2: approval --------------------------------------------------
    def await_approval(self, tool_call_id: str) -> None:
        """`spec/02:210` — `SET status='awaiting_approval' WHERE status='intended'`."""
        i = self._index(tool_call_id)
        if self._rows[i].status != "intended":
            raise LedgerRefused(
                f"awaiting_approval requires status 'intended', found "
                f"{self._rows[i].status!r}")
        self._replace(i, status="awaiting_approval")

    def deny(self, tool_call_id: str, *, error_code: str | None = None) -> None:
        """`spec/02:311` — a refusal moves a NEVER-CLAIMED row, so it can never
        produce `indeterminate`."""
        i = self._index(tool_call_id)
        if self._rows[i].status not in ("intended", "awaiting_approval"):
            raise LedgerRefused(
                f"denial requires an unclaimed row, found {self._rows[i].status!r}")
        self._replace(i, status="denied", error_code=error_code)

    def abandon(self, tool_call_id: str, *, error_code: str | None = None) -> None:
        """`spec/02:321` — the run ended, or the intent cannot proceed. Never
        dispatched, so never `failed`: `failed` requires a claim."""
        i = self._index(tool_call_id)
        if self._rows[i].status not in ("intended", "awaiting_approval"):
            raise LedgerRefused(
                f"abandon requires an unclaimed row, found {self._rows[i].status!r}")
        self._replace(i, status="abandoned", error_code=error_code)

    # ---- phase 3: claim -----------------------------------------------------
    def claim(self, tool_call_id: str, owner: str, token: str, *,
              lease: RunLease | None, fence: str | None = None,
              approved: bool = False) -> None:
        """`spec/02-consistency.md:227-248`, both predicates:

        (a) the effect is claimable — `intended`, or `awaiting_approval` WITH an
            approval;
        (b) AND we still hold the RUN lease. Review found this missing: a worker
            whose run was already reclaimed could still take a fresh effect claim
            and dispatch it, which is the duplicate execution the run lease exists
            to prevent.

        `fence` is the fence token the CLAIMANT believes it holds, checked against
        the lease's own token (`spec/02:248`). ADDED 2026-08-28 (round 4): predicate
        (b) previously compared holder and expiry only, so a worker holding a
        superseded token could claim under a lease that had been reclaimed at a
        higher one.
        """
        i = self._index(tool_call_id)
        row = self._rows[i]
        if row.status == "awaiting_approval":
            if not approved:
                raise LedgerRefused(
                    "claim of an awaiting_approval row requires an approval "
                    "(spec/02-consistency.md:241)")
        elif row.status != "intended":
            raise LedgerRefused(
                f"claim requires status 'intended' or an approved "
                f"'awaiting_approval', found {row.status!r}")
        if lease is None:
            raise LedgerRefused(
                "claim requires an unexpired run lease "
                "(spec/02-consistency.md:246, predicate (b))")
        now = self.clock()
        if not lease.authorises(row.run_id, owner, fence, now):
            raise LedgerRefused(
                "the run lease does not authorise this claim: it must be held by "
                f"{owner!r} for run {row.run_id!r}, under the fence token the lease "
                "carries, and unexpired "
                "(spec/02-consistency.md:246-248)")
        self._replace(i, status="claimed", claim_owner=owner, claim_token=token,
                      lease_expires_at=now + EFFECT_LEASE_SECONDS)

    # ---- phase 5: settle, fenced -------------------------------------------
    def settle(self, tool_call_id: str, status: str, result_json: str | None, *,
               owner: str | None = None, token: str | None = None,
               error_code: str | None = None) -> None:
        """`spec/02-consistency.md:294-303`, all three predicates:

            WHERE claim_owner = $worker   -- we still own it
              AND claim_token = $token    -- ...under THIS claim
              AND status     = 'claimed'  -- ...and nobody has already settled it

        The previous harness had none of them: it accepted `intended -> settled`
        with no owner and no token, so a settlement could invent a verdict for an
        effect nobody ever claimed or dispatched.
        """
        if status not in SETTLEABLE_STATUS:
            raise LedgerRefused(
                f"settle takes one of {sorted(SETTLEABLE_STATUS)}, not {status!r}; "
                "denial and abandonment move an UNCLAIMED row and have their own "
                "statements (spec/02-consistency.md:307)")
        i = self._index(tool_call_id)
        row = self._rows[i]
        if row.status != "claimed":
            raise LedgerRefused(
                f"settle requires status 'claimed', found {row.status!r} — a "
                "never-claimed row cannot be settled (spec/02-consistency.md:326)")
        if owner is None or token is None:
            raise LedgerRefused(
                "settle requires the claim owner AND its token "
                "(spec/02-consistency.md:301)")
        if owner != row.claim_owner or token != row.claim_token:
            raise LedgerRefused("claim fence: stale worker fenced out, not retrying")
        self._replace(i, status=status, result_json=result_json,
                      error_code=error_code,
                      completed_at=(self.clock() if status in COMPLETED_STATUS
                                    else None))

    # ---- reads --------------------------------------------------------------
    @property
    def rows(self) -> list[LedgerRow]:
        return list(self._rows)

    def rows_for(self, tool_call_id: str) -> list[LedgerRow]:
        return [r for r in self._rows if r.tool_call_id == tool_call_id]

    def row_for(self, tool_call_id: str) -> LedgerRow:
        """THE row a `tool_call_id` names, or `LedgerRefused` if there is none.

        ADDED 2026-08-28 (round 5). `PRIMARY KEY (tenant_id, idempotency_key)`
        (`spec/01-schema.md:367`) makes the row singular, so a caller that wants to
        compare a call against its intent should not have to index a list and guess
        what an empty one meant. `_index()` raises for the empty case, which is the
        zero-row `UPDATE ... WHERE idempotency_key = $1` result.
        """
        return self._rows[self._index(tool_call_id)]

    def names(self) -> list[str]:
        return [r.tool_name for r in self._rows]


@dataclass(frozen=True)
class Turn:
    """What a caller gets back from `run()` / `resume()`.

    Deliberately carries NO `Agent`: `output` and `messages` are data. This is the
    whole of the harness's return surface, so there is no object on which a caller
    could call `.override(native_tools=...)`.
    """

    output: Any
    requests: DeferredToolRequests | None
    messages: list[Any]

    @property
    def calls(self) -> tuple[Any, ...]:
        return tuple(self.requests.calls) if self.requests else ()

    @property
    def approvals(self) -> tuple[Any, ...]:
        return tuple(self.requests.approvals) if self.requests else ()


SDK_SURFACE_ARGS = ("native_tools", "toolsets", "tools", "capabilities")


def _reject_sdk_surface(where: str, kw: dict[str, Any]) -> None:
    """`native_tools=` and `toolsets=` are the two ways a caller could hand the SDK
    something Phoenix cannot ledger. Both are refused, at the door — whatever their
    value, so that even `native_tools=None` is a refusal rather than a near miss.

    AMENDED 2026-08-28 (round 4): THREE ways, not two. `capabilities=`
    (`agent/__init__.py:618`) is a first-class public route in 2.35.0 and delivers
    both native tools (`capabilities.NativeTool` — verified: it reaches a
    `FunctionModel` recorder as `WebSearchTool(kind='web_search', ...)`) and
    executable LOCAL bodies (`capabilities.Toolset`, `MCP(local=True)`,
    `WebSearch(local=...)`), i.e. exactly what `ExternalToolset` exists to withhold.
    `Agent.__init__` also auto-injects capabilities (`_inject_auto_capabilities`,
    `agent/__init__.py:630`). It was previously refused only by the catch-all
    "unknown arguments" branch below, with no gate on it; it is now refused BY NAME
    so the message says which surface was refused."""
    for name in SDK_SURFACE_ARGS:
        if name in kw:
            raise UninterceptableTool(
                f"{name}= is not accepted by {where}: every tool must be declared "
                "through register(), which routes it via ExternalToolset. A "
                f"caller-supplied {name} would reach the model without a ledger row "
                "(spec/08 row 30c)")
    if kw:
        raise UninterceptableTool(f"{where}: unknown arguments {sorted(kw)}")


class PhoenixHarness:
    """Wraps a Pydantic AI agent so every tool call crosses the ledger.

    Tools are registered as DECLARATIONS plus a platform-side dispatcher. The SDK
    is told the tool exists so the model can call it; the SDK is given no way to
    run it.

    NO PUBLIC NAME YIELDS THE AGENT. `build_agent()` used to return it, which made
    every guarantee in this file advisory — `agent.override(native_tools=[WebSearchTool()])`
    on a model that supports native tools delivers a vendor-hosted tool with no
    Phoenix involvement (demonstrated as a negative control in `test_gate.py`). The
    agent now lives behind a name-mangled attribute and the public surface is
    `register` / `run` / `resume` / `stream_output` / `resolve`.

    AMENDED 2026-08-28 (round 4). This docstring previously opened "THE AGENT IS NOT
    REACHABLE." That absolute claim was false and is superseded, not erased. Name
    mangling is not access control: `h._PhoenixHarness__build()` returns the Agent,
    and both `test_gate.py`'s `LeakyHarness` control and `mutate.py`'s "expose the
    Agent" mutation use exactly that idiom. Executed against this file:
    `override(native_tools=[WebSearchTool()])` on the mangled agent delivers the
    native tool to the model, and `override(toolsets=[FunctionToolset(...)])` runs a
    registered tool's BODY — both with zero ledger rows. In-process, the tool author
    and the platform share an interpreter; the ledger boundary here is enforced
    against ACCIDENT and against the SDK's own surface, not against a hostile
    in-process caller. A hostile-caller boundary needs the process split of OQ-056.
    `test_gate13_the_mangled_accessor_is_a_known_limitation` asserts that limitation
    is real rather than absent.
    """

    def __init__(self, *, ledger: EffectLedger, model: Any = None,
                 policy: Callable[[str, dict[str, Any]], str] | None = None,
                 lease: RunLease | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 **sdk_surface: Any) -> None:
        _reject_sdk_surface("PhoenixHarness()", sdk_surface)
        self.ledger = ledger
        self.policy = policy or (lambda name, args: "allow")
        self.lease = lease
        self.clock = clock
        self._defs: list[ToolDefinition] = []
        self._dispatch: dict[str, Callable[..., Any]] = {}
        self._minted: dict[str, RunLease] = {}
        self.__model = model
        self.__agent: Agent | None = None

    # ---- registration --------------------------------------------------------
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
                 *, sdk_executable: bool = False, **sdk_surface: Any) -> None:
        """Register a tool. Anything unroutable is REFUSED (spec/08 row 30c)."""
        _reject_sdk_surface("register()", sdk_surface)
        if not self._can_route(name, sdk_executable=sdk_executable):
            raise UninterceptableTool(
                f"{name!r} cannot be routed through the ledger, so it cannot be registered")
        if self.__agent is not None:
            raise UninterceptableTool(
                "the agent is already built; tools cannot be added behind its back")
        # ADDED 2026-08-28 (round 5). This accepted the same name twice, appending a
        # SECOND `ToolDefinition` and replacing the dispatcher: measured,
        # `defs: ['send_email', 'send_email']` and the SECOND impl ran, while the
        # single ledger row read `('send_email', 'succeeded')` -- so the ledger could
        # not say which body executed. That is the key-uniqueness hole round 4 closed
        # in `EffectLedger.append`, left open one layer up, in the registry the row's
        # `tool_name` refers to.
        if name in self._dispatch:
            raise UninterceptableTool(
                f"{name!r} is already registered; a second registration would "
                "silently replace the body a ledger row names")
        self._defs.append(ToolDefinition(name=name, parameters_json_schema=schema))
        self._dispatch[name] = impl

    # ---- the SDK, held privately ---------------------------------------------
    def __build(self) -> Agent:
        """An agent whose tools are all external, so the SDK cannot execute any.

        Private, and name-mangled. Nothing in the public surface returns it; the
        gate asserts that by scanning every public attribute.

        AMENDED 2026-08-28 (round 5), superseding — not erasing — the flat claim
        above. The agent does not run this `ExternalToolset` directly.
        `Agent.__init__` auto-injects `ToolSearch` and `PendingMessageDrainCapability`
        (`agent/__init__.py:630`, `_AUTO_INJECT_CAPABILITY_TYPES` at `:3955-3958`,
        `_inject_auto_capabilities` at `:3962-3970`) and `ToolSearch` ALWAYS wraps the
        toolset in `ToolSearchToolset` (`capabilities/_tool_search.py:191-196`), whose
        `call_tool` (`toolsets/_tool_search.py:435-437`) executes `search_tools`
        LOCALLY rather than delegating to the wrapped toolset. Measured by patching
        `ToolManager.for_run_step` and reading `r.toolset`: the toolset running inside
        this agent is `ToolSearchToolset`, wrapping
        `PreparedToolset -> CombinedToolset -> _AgentFunctionToolset -> ExternalToolset`,
        and `[type(c).__name__ for c in agent._root_capability.capabilities]` is
        `['ToolSearch', 'PendingMessageDrainCapability']` — two capabilities this
        harness never asked for, while `_reject_sdk_surface` refuses `capabilities=`
        by name. It emits no local tool here because no `ToolDefinition` we build sets
        `defer_loading`, which is a fact about the SDK's bytes rather than about this
        harness — so `capabilities/_tool_search.py` and `toolsets/_tool_search.py` are
        now pinned, and `test_gate13_the_agent_runs_only_the_delegating_wrapper`
        asserts both the wrapping and the fail-closed behaviour.
        """
        if self.__agent is None:
            toolset = ExternalToolset(self._defs) if self._defs else None
            self.__agent = Agent(self.__model,
                                 output_type=[str, DeferredToolRequests],
                                 toolsets=[toolset] if toolset else [])
        return self.__agent

    @staticmethod
    def __turn(result: Any) -> Turn:
        out = result.output
        return Turn(output=out,
                    requests=out if isinstance(out, DeferredToolRequests) else None,
                    messages=list(result.all_messages()))

    # ---- the public run surface ----------------------------------------------
    def run(self, prompt: str) -> Turn:
        return self.__turn(self.__build().run_sync(prompt))

    def resume(self, turn: Turn, *, results: dict[str, Any] | None = None,
               approve_all: bool = False) -> Turn:
        if turn.requests is None:
            raise UninterceptableTool("this turn has no pending calls to resume")
        kw: dict[str, Any] = {}
        if results is not None:
            kw["calls"] = results
        if approve_all:
            kw["approve_all"] = True
        return self.__turn(self.__build().run_sync(
            message_history=turn.messages,
            deferred_tool_results=turn.requests.build_results(**kw)))

    async def stream_output(self, prompt: str) -> Any:
        """The streaming path, driven to completion inside the harness.

        Streaming is a different code path through `_tool_execution.py`; a boundary
        that holds only on the buffered path is not a boundary. Exposed as the
        OUTPUT, not as the agent's stream context manager, so this method cannot be
        used to reach the `Agent`.
        """
        async with self.__build().run_stream(prompt) as stream:
            async for _ in stream.stream_output(debounce_by=None):
                pass
            return await stream.get_output()

    # ---- the boundary itself -------------------------------------------------
    def _lease_for(self, run_id: str) -> RunLease | None:
        if self.lease is not None:
            return self.lease
        lease = self._minted.get(run_id)
        if lease is None:
            # CORRECTED 2026-08-28 (round 5): `expires_at` was minted from
            # `self.clock()` -- the HARNESS's clock -- while `EffectLedger.claim`
            # judges `l.expires_at > now()` against the LEDGER's clock.
            # `spec/02-consistency.md:249` is one predicate evaluated inside one
            # statement, so the mint and the check cannot disagree; with two
            # independent clocks a harness whose only unusual argument was
            # `clock=lambda: 1000.0` minted `expires_at=1060.0` against a ledger
            # reading `time.monotonic()`, and every effect on it was refused
            # forever. One clock now decides both halves.
            lease = RunLease(run_id=run_id, holder=f"worker:{run_id}",
                             fence_token=secrets.token_hex(8),
                             expires_at=self.ledger.clock() + RUN_LEASE_SECONDS)
            self._minted[run_id] = lease
        return lease

    def intend(self, run_id: str, call: Any) -> None:
        """Phase 1: record intent BEFORE any dispatch decision."""
        self.ledger.append(LedgerRow(run_id, call.tool_call_id, call.tool_name,
                                     args_json_of(call.args), "intended"))

    def dispatch(self, run_id: str, call: Any, *, approved: bool = False) -> Any:
        """Phases 2-5. Nothing reaches the impl except through here.

        The two error routes are DIFFERENT statuses, and the difference is the whole
        reason `indeterminate` exists (`spec/01-schema.md:339`):

          * a raise BEFORE the body is entered  -> `failed`, with an error code.
            Nothing was dispatched, so the outcome is known.
          * a raise AFTER the body is entered   -> `indeterminate`. The customer
            system may or may not have been touched, and no one can tell.

        ADDED 2026-08-28 (round 5) — THE IDENTITY CHECK, and the reason it is first.
        Nothing here compared the call being executed against the row the ledger
        holds for it. `intend()` writes `tool_name` and `args_json` from ITS `call`;
        this method then looked the impl up by `call.tool_name` and claimed and
        settled by `call.tool_call_id` from a DIFFERENT object. Reproduced at the
        round-4 commit through this same public surface — `register('read_doc')`,
        `register('charge_card')`, `intend('run-1', Call('tc-1','read_doc',
        {'to':'benign'}))`, `dispatch('run-1', Call('tc-1','charge_card',
        {'to':'victim'}))` — the CHARGE body executed (`['CHARGE:victim']`) and the
        one ledger row settled `tc-1 read_doc {"to": "benign"} succeeded`. There WAS
        a row; it was a row for a different effect, which is exactly what
        `RESULT.md`'s "for that exact call" excludes. `spec/01-schema.md:403` settles
        it: `idempotency_key = sha256_hex(canon({tenant, run, logical_step_path,
        request_digest}))` puts the digest INSIDE the key, so a differing request is
        a different effect, not the same one — and the run is in the key too, which
        is why the run is checked here as well (`spec/01-schema.md:372`).

        It runs BEFORE the policy verdict deliberately: a call the row does not
        describe must not be able to move that row to `denied` or `abandoned`
        either.
        """
        row = self.ledger.row_for(call.tool_call_id)
        if row.run_id != run_id:
            raise LedgerRefused(
                f"{call.tool_call_id!r} is an effect of run {row.run_id!r}, not "
                f"{run_id!r}; the run is part of the key "
                "(spec/01-schema.md:372, spec/01-schema.md:403)")
        if row.tool_name != call.tool_name or row.args_json != args_json_of(call.args):
            raise LedgerRefused(
                f"the ledger row for {call.tool_call_id!r} describes "
                f"{row.tool_name!r}{row.args_json}, not {call.tool_name!r}"
                f"{args_json_of(call.args)}; a differing request_digest is a "
                "DIFFERENT effect, not this one (spec/01-schema.md:403)")

        if approved:
            # Phase 2 answered: a human approved an `awaiting_approval` row. The
            # policy is NOT re-evaluated; the approval is the verdict (spec/02:241).
            if row.status != "awaiting_approval":
                raise LedgerRefused(
                    f"approved dispatch requires an awaiting_approval row, found "
                    f"{row.status!r}")
            verdict = "allow"
        else:
            verdict = self.policy(call.tool_name, call.args or {})
            if verdict not in POLICY_VERDICTS:
                # FAIL CLOSED (OQ-065, 2026-08-28): nothing is claimed, nothing runs.
                raise PolicyVerdictInvalid(
                    f"policy returned {verdict!r}; expected one of "
                    f"{sorted(POLICY_VERDICTS)} — refusing to dispatch")
            if verdict == "require_approval":
                # Phase 2: park the row on the approval's own (long) clock; no lease.
                self.ledger.await_approval(call.tool_call_id)
                return "AWAITING approval"
        if verdict == "deny":
            self.ledger.deny(call.tool_call_id, error_code="policy_denied")
            return "DENIED by policy"

        impl = self._dispatch.get(call.tool_name)
        if impl is None:
            # Never claimed, never dispatched -> `abandoned`, not `failed`.
            # `spec/01-schema.md:381` forbids a `failed` row without a claim.
            self.ledger.abandon(call.tool_call_id, error_code="no_dispatcher")
            raise UninterceptableTool(f"no platform dispatcher for {call.tool_name!r}")

        # Phase 3: CLAIM before dispatching, under the RUN lease.
        lease = self._lease_for(run_id)
        owner = lease.holder if lease else f"worker:{run_id}"
        token = secrets.token_hex(16)
        self.ledger.claim(call.tool_call_id, owner, token, lease=lease,
                          fence=lease.fence_token if lease else None,
                          approved=approved)

        # --- everything to the `impl(...)` line below is BEFORE dispatch ---
        #
        # CORRECTED 2026-08-28 (round 4). Argument BINDING used to happen at the
        # `impl(**args)` call itself, inside the dispatch try — but Python raises
        # binding errors AT the call, before the body is entered, so a call whose
        # argument NAMES did not match the impl was recorded `indeterminate` /
        # `dispatch_lost_contact` although nothing was dispatched. That manufactures
        # uncertainty, which `spec/05-state-machine.md:110` says is never free, and
        # contradicts `spec/02-consistency.md:327-328`: "indeterminate now means only
        # 'we took a lease, dispatched, and lost contact' — real uncertainty, never
        # bookkeeping". Binding is now done here, with `inspect.signature().bind`, so
        # only exceptions raised by the BODY can reach the indeterminate branch. The
        # JSON-decode branch below is unreachable on the SDK path (args arrive as a
        # dict); the binding branch is the one a model actually hits.
        try:
            args = (call.args if isinstance(call.args, dict)
                    else json.loads(call.args or "{}"))
            if not isinstance(args, dict):
                raise TypeError(f"tool arguments must be an object, got {type(args).__name__}")
        except Exception:
            self.ledger.settle(call.tool_call_id, "failed", None,
                               owner=owner, token=token,
                               error_code="arguments_undecodable")
            raise
        try:
            bound = inspect.signature(impl).bind(**args)
        except Exception:
            self.ledger.settle(call.tool_call_id, "failed", None,
                               owner=owner, token=token,
                               error_code="arguments_unbindable")
            raise

        # --- the dispatch itself. After this line the outcome is unknowable. ---
        try:
            result = impl(*bound.args, **bound.kwargs)
        except Exception:
            self.ledger.settle(call.tool_call_id, "indeterminate", None,
                               owner=owner, token=token,
                               error_code="dispatch_lost_contact")
            raise
        # ADDED 2026-08-28 (OQ-066). Serialising the RESULT is also after dispatch:
        # the effect has happened, so a failure here must not strand the row at
        # `claimed`. It settles `indeterminate` -- we know it ran, not what it returned.
        try:
            result_json = json.dumps(result, sort_keys=True)
        except Exception:
            self.ledger.settle(call.tool_call_id, "indeterminate", None,
                               owner=owner, token=token,
                               error_code="result_unserialisable")
            raise
        self.ledger.settle(call.tool_call_id, "succeeded", result_json,
                           owner=owner, token=token)
        return result

    def resolve(self, run_id: str, requests: DeferredToolRequests) -> dict[str, Any]:
        """Ledger and dispatch every pending call; return results by call id."""
        out: dict[str, Any] = {}
        for call in requests.calls:
            self.intend(run_id, call)
            out[call.tool_call_id] = self.dispatch(run_id, call)
        return out
