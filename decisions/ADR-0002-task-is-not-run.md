# ADR-0002 — Task and Run are separate resources with separate state machines

- **Status:** Provisional (pre-evidence, Phase 0)
- **Date:** 2025-08-26
- **Supersedes:** —
- **Superseded by:** —

## Context

Written before the teardown as a strawman to be attacked. Phase 2 drafts these
from three deep probes; Phase 3 runs the remaining projects against them. Each
pass must record `confirms`, `amends`, `challenges` or `neutral` in its
`facts.yaml` `adr_impact`.

A provisional ADR is a hypothesis with a falsification condition, not a
commitment.

## Decision

Task represents intent and may outlive many attempts. Run represents one execution attempt. Each has its own state machine; a Task is not merely a Run with extra fields.

## Rationale

Retry, human reassignment, delegation and cost attribution all need a stable handle for the intent that survives a failed attempt. Collapsing the two makes retry semantics ambiguous.

## Implications

- Two state machines to define, not one.
- Task-level and Run-level idempotency are different problems.
- Cost and telemetry roll up Run -> Task.
- A Task can exist with zero Runs (queued, or awaiting assignment).

## Falsification

If no studied system distinguishes them and retry works fine without the split, the extra resource is unjustified complexity.

## Deciding probes

`A4`, `C4`, `L7`, `S2`

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | confirms | `libs/sdk-py/langgraph_sdk/schema.py:362 @ 3803173` | No Task resource anywhere; Run exists only in the closed Platform. In OSS a run is a function call, so "retry this intent" has nowhere to live. Strong support for the split. |
| OpenHands | confirms | `openhands-agent-server/.../conversation_router.py:236-268 @ 760eea2` | `STUCK` and `WAITING_FOR_CONFIRMATION` enrich the state machine. pause (graceful) vs interrupt (immediate) refines the CANCELLING amendment into TWO operations. |
| Letta | confirms | `src/cron/cron-file.ts:26-43 @ 852ca24` | Nine named cron run reasons (`started_too_late`, `queue_full`, `runtime_unavailable`, `scheduler_inactive`, `invalid_cron`, `scheduler_error`...) plus a five-state task machine incl. `missed`. Best failure-mode enumeration in the study; adopt this discipline for scheduled Runs. |
| Google AX | amends | `proto/ax.proto:111-131 @ b777313` | `Conversation → Interaction` is the closest thing to the split yet — Interaction has its own id and terminal state. But a `TODO` admits it is not yet first-class: "CreateInteraction should return an Interaction message and the outputs should be polled from the Interaction." Even a Google team found this hard to land. |
| Omnigent | confirms | `omnigent/db/db_models.py:1434,1546 @ ba9e371` | **First real Task/Run separation in the study.** `scheduled_tasks` (intent: prompt, rrule, timezone, state, `max_cost_usd`) and `scheduled_task_runs` (attempt: status, `scheduled_at`/`fired_at`/`finished_at`, error, `error_code`) are separate tables, so the intent survives failed attempts. The bounded queryable `error_code` "for future retry logic" is the field my strawman `Run` was missing. Caveat: only for scheduled work, not interactive sessions. |
| Cloudflare Agents | neutral | `packages/agents/src/index.ts:2250-2291 @ 2f957bc` | No general Task/Run split. But `cf_agents_fibers` (durable intent, carrying the idempotency key) versus `cf_agents_runs` (live attempt) is the same shape for durable execution — and the outer join between them is precisely what detects a dead process, which is a concrete argument *for* keeping the two separate. |
| AG2 | confirms | `ag2/task.py:5-27 @ 90f490a` | `Task` is a first-class framework primitive with `TaskStarted/Progress/Completed/Failed/Expired/Cancelled`, `checkpoint()`, and `resume_from=prior_task_id` exposing `resumed_state`. **`TaskExpired` distinct from `TaskFailed`** is right and rare. And the division of labour is explicit: tasks are *agent-owned*, "the framework does not assign or schedule them". |
| Pydantic AI | neutral | `pydantic_ai_slim/pydantic_ai/durable_exec/_base.py @ b48ee38` | No Task or Run resource. Under a durable engine the *engine's* workflow is the durable run — which is itself a small argument that Run belongs to whoever owns durability. |
| Google Agent Platform | amends | `src/google/adk/apps/_configs.py:29-47 @ 85b52f6`; `src/google/adk/events/_rewind_events.py` | `Invocation` is a run with richer lifecycle than my model: **pausable** on a long-running function call, **resumable** "from the last event", and **rewindable** — an event carrying `rewind_before_invocation_id` drops itself and everything back to that invocation, with `_apply_rewinds` documented as "the single source of truth for which events are live". **Our `Run` should support a logical rewind marker, not only forward progress.** |
| HumanLayer | confirms | `hld/store/store.go:274-284 @ 99abe67` | **Richest run state machine in the study, and the only precedent for a transitional cancel state.** Nine states: `draft`, `starting`, `running`, `completed`, `failed`, `waiting_input`, `interrupting`, `interrupted`, `discarded`. Three are new to our model: **`draft`/`discarded`** (a run can be composed before it starts and abandoned without running), **`waiting_input`** (blocked-on-human becomes an indexed query rather than an inference), and **`interrupting` vs `interrupted`** — commented as "received interrupt signal and is shutting down" versus "was interrupted **but can be resumed**". That is exactly the `CANCELLING` state my revised domain model proposed, and nothing else in the study has it. Cancellation takes time; a state machine that pretends otherwise reports a lie during the gap. |
| AWS AgentCore | neutral | `src/bedrock_agentcore/runtime/models.py @ 826416a` | No Task or Run resource on the SDK surface; execution lifecycle is server-side. |

## Amendment — 2026-08-26 (Phase 2, LangGraph)

The Run state machine needs an explicit **`CANCELLING`** state. Verified in
LangGraph: abandoning a sync `invoke` leaves the worker thread running while
state shows the task still pending (`next: ('child',)`). Without a durable
`CANCELLING` state, cancellation is indistinguishable from abandonment, and a
still-executing worker has no way to learn it should stop.

Add to the provisional Run machine:

```text
RUNNING → CANCELLING → CANCELLED
```

`CANCELLING` must be durable, so a control-plane restart mid-cancel does not
lose the intent (ties to S5).

## Open questions

-
