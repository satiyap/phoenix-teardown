# ADR-0015 — Approval is a durable resource that names its approver

- **Status:** Accepted (2026-08-26, Phase 5) — 3 projects. Raised from HumanLayer; approver identity remains unprecedented and is ours to build.
- **Date:** 2026-08-26 (after HumanLayer)
- **Supersedes:** —
- **Superseded by:** —
- **Related:** ADR-0002 (Task ≠ Run), ADR-0007 (principals), ADR-0013 (traced policy), ADR-0014 (idempotency)

## Why this ADR exists

The strawman modelled approval as a *status on a Run* — `WAITING_FOR_HUMAN` — with
the request and decision implied. Eleven projects show that is wrong in two
different ways, and the correction is specific enough to be its own decision.

**Nobody in the study models an approval well *and* records who approved.**
HumanLayer has the only real approval resource and no approver identity. Everyone
else has an approver implicitly (a single-user CLI) or no approval resource at all.

## Context: eleven projects, four designs

| Project | How a pending approval is represented | Approver recorded |
|---|---|---|
| LangGraph | `interrupt()` — a checkpointed graph pause | no |
| OpenHands | thread state + `ConfirmRisky` policy | no |
| Letta | a JSON file of pending approvals | no |
| Google AX | **`ConfirmationContent{id, question, oneof decision}`** — wire-protocol content in the event log | no |
| Omnigent | policy `ASK` + `pending_approvals`, five elicitation surfaces | user_id known via session ACL, not on the decision |
| Cloudflare | `cf_agent_tool_approval` protocol message | no |
| AG2 | (human is a `Passport` kind, but approval is not a resource) | **identity exists**, approval does not |
| Pydantic AI | `DeferredToolRequests.approvals` — a typed *return value* | no |
| ADK | long-running call + `ResumabilityConfig` pause | no |
| **HumanLayer** | **an `approvals` table** with status `CHECK`, `responded_at`, rationale, partial index | **no** |

Two designs are genuinely good and neither is complete:

**AX makes the approval part of the log.** `ConfirmationContent` carries a stable
`id`, the `question`, and a `oneof decision` — so question and answer are the same
durable object, replayable, with no separate store. Durability is free because the
log is durable.

**HumanLayer makes the approval a row.** A `CHECK`-constrained status, a partial
index on pending so "what needs a human now" stays cheap, `created_at`/
`responded_at` for latency, a rationale on both approve and deny, correlation onto
the tool-call event via `approval_id`, `ErrAlreadyDecided` on double-resolution, and
an `ApprovalReconciler` that re-syncs after restart.

**Neither records the principal who decided.** In HumanLayer that is a coherent
consequence of a 0600 Unix socket — the operator is implicit. For a multi-user
platform it is a straightforward audit failure: the system can prove *that* a
dangerous action was approved and *why*, but not *by whom*.

## Decision

**An `Approval` is a first-class durable resource, correlated to the action it
gates, and it names the principal who decided.**

```text
Approval
  id                    stable, referenced by the gated action
  run_id                the run this belongs to
  action_ref            the tool call / effect being gated
                        (correlated BOTH ways — see rule 2)
  status                pending | approved | denied | expired | superseded
  requested_at
  requested_by_rule     WHICH policy required approval (ADR-0013)
  decided_at
  decided_by            → Principal          ← the gap this ADR closes
  decision_rationale    free text, durable on approve AND deny
  expires_at            optional; unanswered approvals can lapse
  request_payload       what the human was actually shown
```

Six rules:

1. **The approval is durable independently of the process that requested it.** A
   restart must not lose a pending approval, and must reconcile on the way back up
   — HumanLayer's `ApprovalReconciler`, keyed on the run, non-fatal on failure so a
   failed reconcile leaves the pending row for the next attempt.

2. **Correlate in both directions.** The approval references the action; the action
   record carries `approval_id` and `approval_status` inline. HumanLayer
   denormalises onto the transcript event so reading the conversation shows approval
   state without a join. A reader of either side can see the other.

3. **Decisions are idempotent and informative.** Re-deciding returns the existing
   decision, not a conflict and not an overwrite — HumanLayer's
   `AlreadyDecidedError{ID, Status}` producing *"approval %s already decided with
   status: %s"*. Approval UIs retry; this is ADR-0014 applied to a human action.

4. **`decided_by` is a `Principal` and is mandatory on any terminal decision.** An
   approval that cannot name its approver does not satisfy audit. Where the platform
   runs single-user, the principal is the local operator — still recorded, not
   implied.

5. **Rationale is durable on approve as well as deny.** HumanLayer's single
   `comment` column serves "denial reasons or approval notes". The interesting audit
   question is usually why something *was* permitted.

6. **Record the rule that required the approval** (`requested_by_rule`). HumanLayer
   traces the decision but not the policy; AG2's `deciding_policies` traces the
   policy but has no approval resource. Both halves are needed: without the rule you
   cannot answer "why was this gated", without the decision you cannot answer "what
   did the human say".

## Corollary: dangerous overrides expire

HumanLayer pairs `dangerously_skip_permissions` with
`dangerously_skip_permissions_expires_at`, and emits `session_settings_changed`
with `reason="expired"` and `expired_at` when it lapses
(`hld/store/sqlite.go:117-118`, `hld/bus/types.go:20-32`).

Every other project treats "skip approvals" as a mode. **Modes get switched on
during a frustrating session and never switched off**, so approval fatigue quietly
converts a safety control into a permanently disabled one.

**Adopted as a general rule:** any control that disables a safety check carries a
TTL, and its expiry is an observable event. A bypass that cannot become permanent
by neglect is a different kind of object from a mode.

The naming convention travels with it — `dangerously_` (HumanLayer) and
`unsafe_local_code_executor` (ADK) both make the operator type the word. Cheap, and
it works.

## Consequences

**What this buys.** Durable HITL by construction. An audit trail that answers who,
what, why, and under which rule. Cheap "what needs attention" queries via a partial
index on pending. A `WAITING_INPUT` run state that is indexed rather than inferred.

**What it costs.** An extra table and an extra write on the hot path of any gated
action. Bidirectional correlation means two writes to keep consistent, so the
approval row and the action record should be written in one transaction.

**What is deliberately not decided here.** *Which* actions require approval is
policy (ADR-0013), not this ADR. And the elicitation *surface* — how the question
reaches a human — stays pluggable, since Omnigent found five distinct ones
(`NONE | HOOK | JSONRPC | APPROVAL_MIRROR | SSE_PERMISSION`) and none is universal.

## Alternatives considered

- **Approval as a Run status** (the strawman). Rejected: cannot hold the question,
  the decision, the rationale, or the approver, and cannot express two concurrent
  approvals in one run.
- **Approval as log content** (Google AX). Genuinely good — durability is free and
  replay is exact. Rejected as the *primary* model because a log gives no efficient
  "all pending approvals" query and no place for an approver reference without
  extending the content type. **Adopted as a secondary rule instead**: the approval
  request and its decision are *also* appended to the event log, so replay stays
  faithful.
- **Approval as a typed return value** (Pydantic AI's `DeferredToolRequests`).
  Elegant for a library, where the caller holds the pending state. Rejected for a
  platform: the platform must answer "what is pending" without a caller present.
- **No approval resource; rely on the harness's permission mode.** Rejected:
  eleven projects show the harness cannot record the platform's audit trail.

## Evidence log

| Project | Effect | Evidence | Note |
|---|---|---|---|
| Google AX | confirms | `proto/content.proto:28-47 @ b777313` | `ConfirmationContent{id, question, oneof{ApprovalDecision, DeclineDecision}}` — question and answer as one durable log object. Best durability story; no approver, and `DeclineDecision.reason` is `reserved` (removed). |
| Omnigent | confirms | `omnigent/policies/types.py @ ba9e371` | Policy `ASK` with five elicitation surfaces and server-side approval round-trips applying `state_updates` only on accept. Traces the *rule*; the approval is not a resource. |
| Letta | partial | @ `852ca24` | Pending approvals in a JSON file — durable, but no schema, status constraint, or query surface. |
| Pydantic AI | amends | `pydantic_ai/_deferred.py:27-61 @ b48ee38` | HITL as a typed *output* with `approvals` and a decline-and-fallthrough handler chain. Correct for a library, insufficient for a platform. |
| ADK | confirms | `apps/_configs.py:32-36 @ 85b52f6` | Long-running call pauses the invocation and resumability restores it, so an approval outlives the process — but as a pattern, with no `Approval` resource. |
| **HumanLayer** | **raises** | `hld/store/sqlite.go:201-220 @ 99abe67`; `hld/store/errors.go:13-42`; verified by test | The only real `Approval` table: status `CHECK`, partial index on pending, `responded_at`, rationale, inline correlation onto the tool-call event, `ErrAlreadyDecided` returning the existing status, and an `ApprovalReconciler` on restart. **And no approver identity** — the gap that makes this ADR necessary. |
| AWS AgentCore | neutral | `src/bedrock_agentcore/identity/auth.py:23-35 @ 826416a` | No approval resource. Human interaction is OAuth consent only — `USER_FEDERATION` with an `on_auth_url` callback and a `TokenPoller`, plus `custom_state` for CSRF-protecting the redirect. Consent is not approval-of-an-action. |
| Microsoft Agent Framework | confirms | `python/packages/core/agent_framework/_workflows/_checkpoint.py:59-61 @ e34bf48` | **A second route to rule 1**, alongside HumanLayer's reconciler. `pending_request_info_events` are stored *inside* the checkpoint, so an unanswered human request survives a restart by virtue of the checkpoint — no separate approval store needed. Combined with `IDLE_WITH_PENDING_REQUESTS`, durable HITL is integrated into the orchestration rather than bolted alongside it. Still no approver identity, so rule 4 remains unprecedented. |
| Agent Control | amends | `models/src/agent_control_models/controls.py:262-275 @ 7cb21af` | **`steer` reframes the approval question.** Many approvals exist only because a policy can say nothing but *no*. Here a control returns actionable remediation — *"This large transfer requires user verification. Request 2FA code from user, verify it, then retry the transaction with `verified_2fa=True`"* — so the agent self-services and no human is interrupted. **Amendment: approval is the escalation path when steering is impossible, not the default response to a policy violation.** Note the steering examples are *procedures*, including one that instructs the agent to go obtain manager approval — so steering can route *into* the approval flow rather than replacing it. |
