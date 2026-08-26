# ADR-0013 — Policy decisions are traced and shadow-comparable

- **Status:** Provisional (raised by evidence, Phase 2)
- **Date:** 2026-08-26
- **Supersedes:** —
- **Superseded by:** —

## Context

Raised by the Letta teardown, which is the only project in the study with a
production-grade policy engine and therefore the only one that had to solve
policy *evolution*.

Letta's permission types (`src/permissions/types.ts:30-57 @ 852ca24`) include:

```typescript
export type PermissionEngine = "v1" | "v2";
export interface PermissionTraceEvent { ... }
export interface PermissionShadowComparison { ... }
export interface PermissionCheckTrace { ... }
export interface PermissionCheckResult { ... }
```

Two capabilities beyond simply making a decision:

1. **Tracing** — `PermissionCheckTrace` records *why* a decision was reached, not
   just what it was. With a layered model (unbypassable guard at step 0, then
   rules, then modes) a bare `deny` is not actionable; the operator needs to know
   which layer denied and on what rule.
2. **Shadow comparison** — the engine is explicitly versioned, and v2 can be
   evaluated alongside v1 on live traffic with decisions compared before cutover.

This matters more for us than for Letta. Our policy layer will deny real work:
tool calls, delegations, spawns. A policy change that silently broadens access is
a security incident; one that silently narrows it is an outage. Neither is
detectable from a boolean return value.

Letta also demonstrates the failure this prevents. It once analysed shell
commands by parsing them and abandoned that design because it "was bypassable by
symlinks, command substitution, globbing, and subprocesses"
(`src/permissions/cross-agent-guard.ts:11-14 @ 852ca24`). Replacing an
enforcement mechanism wholesale is exactly the change that needs shadow
evaluation, because the new mechanism's decisions must be compared against the
old before anyone trusts it.

## Decision

Every policy decision emits a trace, and the policy engine supports shadow
evaluation.

**Tracing.** A decision record carries: the decision (`allow` / `deny` / `ask`),
the layer that produced it, the specific rule or guard matched, the principal,
the capability, the resource, and the inputs consulted. A `deny` must be
explainable to the operator and to the agent without reading source.

**Shadow evaluation.** The engine is versioned. A candidate version can be
evaluated in parallel with the active one, with divergences recorded and not
enforced. Promotion requires an explicit decision informed by observed
divergence, not a deployment.

**Layer attribution is mandatory.** Given a layered model with an unbypassable
floor, a trace that does not name the deciding layer is incomplete.

## Rationale

Policy is the subsystem where silent behaviour change is most dangerous and least
observable. Traces make individual decisions auditable; shadow evaluation makes
*changes* to the decision function auditable. They address different risks and we
need both.

There is a second benefit specific to agents. When a capability is denied, the
agent should be able to explain the refusal to the human, and ideally adapt.
That requires a machine-readable reason, which follows from tracing. It also
connects to ADR-0012's rule that a refusal names the unmet capabilities rather
than merely reporting failure — same principle applied to policy rather than
capability.

## Implications

- Policy decision records are a first-class event type in the canonical schema
  (ADR-0010), and they carry audit weight, so they need durability guarantees
  stronger than best-effort telemetry.
- The engine interface must accept a version and support parallel evaluation.
- Divergence reporting needs a home: a comparison log plus a way to sample
  disagreements.
- Trace volume is a cost concern — every tool call produces one. Needs sampling
  for observability while retaining all `deny` and `ask` decisions for audit.
- Interacts with ADR-0007: the trace must identify the principal, and for a
  delegated action must record both the acting agent and the authority under
  which it acted (see S1).

## Falsification

If our policy layer stays simple enough that decisions are self-evident from
inputs — a single flat ruleset, no layering, no delegation — tracing is overhead
and shadow evaluation is ceremony.

Also falsifiable if trace volume proves unmanageable in practice: if the honest
choice becomes tracing only denials, then "every decision emits a trace" is wrong
as stated and should be narrowed.

## Deciding probes

`I8`, `J10`, `J9`, `M1`, `M4`

## Evidence log

| Project | Effect | Evidence | Note |
|---|---|---|---|
| Letta | raised | `src/permissions/types.ts:30-57 @ 852ca24` | `PermissionEngine v1\|v2`, `PermissionCheckTrace`, `PermissionShadowComparison`, `PermissionTraceEvent`. The only project in the study to treat policy evolution as a design problem. |
| Letta | supports | `src/permissions/cross-agent-guard.ts:11-19 @ 852ca24` | Documents abandoning shell-command parsing as bypassable and moving enforcement to the kernel — precisely the wholesale mechanism change that requires shadow comparison. |
| LangGraph | neutral | `libs/sdk-py/langgraph_sdk/auth/__init__.py:98 @ 3803173` | Has a specificity fallback chain but no trace and no engine versioning. |
| OpenHands | neutral | `openhands-sdk/.../hooks/conversation_hooks.py:92 @ 760eea2` | `HookExecutionEvent.blocked` records that a block happened, but not which rule decided or why. |
| Google AX | neutral | `internal/server/server.go:82-83 @ b777313` | No policy engine at all, so nothing to trace. |
| Omnigent | confirms | `omnigent/policies/types.py:244-252 @ ba9e371` | **First implementation of the traceability half.** `PolicyResult.deciding_policies` names every policy that drove a composed verdict — a single policy on DENY, all ASKing policies in YAML order on ASK. Policies also *transform* content in a chain, each seeing the previous one's output, which makes PII redaction a policy rather than a special case. No shadow-comparison mode exists, so that half of the ADR remains without precedent after six projects. |
| Cloudflare Agents | neutral | `packages/agents/src/chat/tool-state.ts @ 2f957bc` | No policy engine. Tool approval exists as a protocol message type, but nothing evaluates rules, so there is no decision to trace. |
| AG2 | confirms | `ag2/network/rule.py:12 @ 90f490a`; `ag2/network/hub/core.py:1861-1866,24-25` | Access and limits are "enforced at the **hub**, never the client", decisions route through a **replaceable `arbiter`** so "federation / custom permission protocols can replace the default rule-based behavior without forking the hub", and every refusal fires `on_envelope_rejected`. The trust boundary is architectural: the hub "never calls `Agent.ask`, executes tenant transforms, or imports tenant modules". Still **no shadow-comparison mode after eight projects** — that half of this ADR remains without precedent. |
| Pydantic AI | neutral | `pydantic_ai_slim/pydantic_ai/capabilities/hooks.py @ b48ee38` | No policy engine. Typed wrap points and `Hooks` are real interception seams, and `RaiseContentFilterError` is a shipped guard, but there is no decision object to trace. |
| Google Agent Platform | neutral | `src/google/adk/plugins/base_plugin.py:114-396 @ 85b52f6` | Sixteen named lifecycle hooks — including four distinct error callbacks (`on_model_error`, `on_tool_error`, `on_agent_error`, `on_run_error`) — are real interception seams, but there is no policy decision object to trace. **Still no shadow-comparison mode after ten projects**; that half of this ADR remains entirely without precedent. |
| HumanLayer | confirms | `hld/store/sqlite.go:201-217 @ 99abe67` | **Traces the decision but not the policy.** The record is strong — which tool, what input, what status, when responded, and a free-text rationale — but nothing records *the rule that required approval*, because that is delegated to the harness's permission mode. That is precisely the half AG2 (`deciding_policies`) and Omnigent supply, and it confirms both halves are needed: a decision trail without the rule cannot answer "why was this gated", and a rule trail without the decision cannot answer "what did the human say". |

## Open questions

- Should a policy trace be retained for the same period as the audit log, or is
  a shorter window acceptable for `allow` decisions?
- Can shadow evaluation run safely against an engine with side effects (an
  `AGENT`-type hook that itself invokes a model, as in OpenHands)?
