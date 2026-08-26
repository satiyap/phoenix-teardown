# ADR-0014 — Side effects are made idempotent by a durable effect ledger

- **Status:** Provisional (raised from evidence, Phase 3)
- **Date:** 2026-08-26 (after Cloudflare Agents closed `C6`)
- **Supersedes:** —
- **Superseded by:** —
- **Related:** ADR-0002 (Task ≠ Run), ADR-0011 (pins), ADR-0004 (adapter contract), ADR-0012 (declared capabilities)

## Why this ADR exists

It was not in the original ten. It exists because `C6` — an idempotency key on
side-effecting work — was **absent in the first six projects read**, making it the
most robust negative finding in the study after agent-to-agent messaging, and then
**Cloudflare Agents closed it outright**.

A gap that survives six projects and is then solved cleanly by the seventh is not
an oversight in those six. It is a hard problem with a known-good answer that has
not yet diffused. That is exactly the kind of finding this study was run to
produce, and it deserves a decision rather than a footnote.

## Context

Every durable execution system in this study replays work after a failure. None
of the first six protected the *effects* of that work:

| Project | Behaviour at a resume boundary |
|---|---|
| LangGraph | **Verified:** a side effect before `interrupt()` executes **twice** on resume, because the whole node re-runs |
| OpenHands | No idempotency concept |
| Letta | No idempotency concept |
| Google AX | Atomic per-step log appends and an explicitly idempotent `CreateActor`, but **tool** effects unprotected |
| Omnigent | Found and fixed a *lost-update* race on usage deltas (bug #9, `BEGIN IMMEDIATE`), but tool effects unprotected |
| Cloudflare Agents | **`idempotency_key TEXT UNIQUE` on the durable execution ledger** |

The LangGraph result is the one that makes this urgent, because it was verified
empirically rather than inferred: a resumed graph re-executes the node containing
the effect. Any system with checkpoint-and-resume semantics has this problem
unless it explicitly addresses it, and "developer discipline" is not an answer when
the platform is the thing doing the replaying.

## The precedent, in detail

Cloudflare's mechanism (`packages/agents/src/index.ts:2282,5522-5590 @ 2f957bc`):

```sql
CREATE TABLE IF NOT EXISTS cf_agents_fibers (
  fiber_id        TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE,
  name            TEXT NOT NULL,
  status          TEXT NOT NULL,
  snapshot        TEXT,
  ...
)
```

```text
startFiber(name, fn, { idempotencyKey }):
    existing = readFiberByKey(idempotencyKey)
    if existing:  return { ...inspection, accepted: false }   // do NOT re-run
    INSERT row (status='pending')
    execute
```

Three properties worth copying exactly:

1. **The ledger row is written before the work runs**, so a crash mid-effect
   leaves evidence.
2. **A duplicate returns `accepted: false`** alongside the existing record — an
   honest "this already exists, here it is" rather than a silent success or an
   error.
3. **Ambiguity is refused.** If `fiberId` and `idempotencyKey` refer to different
   fibers, it throws `"fiberId and idempotencyKey refer to different fibers"`
   rather than picking one.

**Verified locally** (`vitest run src/tests/run-fiber.test.ts`, 48/48 pass). The
decisive assertion is not the return value but the side effect:

```
✓ should dedupe managed fibers by idempotency key
    first.accepted  === true
    second.accepted === false
    second.fiberId  === first.fiberId
    executionLog    === ["managed:first"]     // the effect ran ONCE
```

## Decision

**Every side-effecting operation the platform performs on behalf of an agent is
recorded in a durable effect ledger, keyed by a deterministic idempotency key, and
the ledger is consulted before the effect is attempted.**

Concretely:

```text
effect_ledger
  run_id            FK to the run that owns this effect
  idempotency_key   TEXT UNIQUE NOT NULL     -- deterministic, see below
  kind              tool_call | delegation | notification | schedule_fire | ...
  status            pending | succeeded | failed | abandoned
  attempt           INTEGER
  request_digest    hash of the effect's inputs
  result_ref        pointer to the stored outcome
  created_at, started_at, completed_at
  error, error_code                          -- error_code queryable (Omnigent)
```

Five rules:

1. **The key is deterministic, derived from position rather than time.** It is a
   hash of `(run_id, logical_step_path, request_digest)`. Two things follow: a
   replay of the same logical step produces the same key, and a *genuinely
   different* call at the same step (different arguments) produces a different key
   and is correctly allowed through.

2. **Write the ledger row before attempting the effect.** A crash between the
   write and the effect leaves a `pending` row, which is the signal for recovery
   rather than an invisible loss. This is the AX lesson (log before act) applied
   to effects rather than steps.

3. **On a duplicate key, return the recorded outcome without re-executing**, and
   report that it was a replay. Callers must be able to distinguish "I did this"
   from "this was already done" — Cloudflare's `accepted: false`.

4. **Refuse ambiguity.** Conflicting identity inputs raise an error. Never guess
   which record is authoritative.

5. **A `pending` row older than a lease threshold is `INDETERMINATE`, not
   retryable.** This is the honest and uncomfortable part: if we crashed after
   dispatching an effect but before recording its outcome, we do not know whether
   it happened. Such a row must be surfaced — to a human, or to a
   compensating path — and never silently retried. Retrying it is precisely the
   double-charge bug this ADR exists to prevent.

## Consequences

**What this buys.** Replay becomes safe by default rather than by discipline. The
`STUCK`/`INDETERMINATE` states in the domain model gain a concrete producer. Audit
gets a complete record of every attempted effect, not just successful ones.

**What it costs.** A write before every side effect, so effects are slower and the
ledger is a hot table. Deterministic keying requires a stable notion of "logical
step path", which constrains how adapters report progress — an adapter that cannot
tell us where it is cannot participate. Per ADR-0012 this becomes a **declared
capability**: `effect_ledger_participation: verified | asserted | unsupported`,
and an adapter that does not support it gets at-most-once-attempted semantics with
that limitation stated in its capability record rather than hidden.

**What it does not solve.** Effects that are inherently non-idempotent at the far
end and offer no dedupe token of their own. For those the ledger converts a silent
double-execution into a *detected* indeterminate state, which is strictly better
but is not exactly-once. Following Cloudflare's own standard on this — see below —
we say so rather than claiming a guarantee we cannot keep.

## The rule this ADR is really enforcing

From `design/channels.md`, explaining why Cloudflare *deleted* its own durable
messaging host:

> It also never delivered exactly-once ingress — a crash between the callback and
> its receipt write replays the callback anyway — so the guarantee it appeared to
> offer was not one it could keep.

**A guarantee you cannot keep is worse than an honest limitation.** This ADR
therefore claims exactly what the mechanism delivers: *at-most-once effects where
the effect target cooperates, and detected indeterminacy where it does not.* It
does not claim exactly-once.

## Alternatives considered

- **Developer discipline** (the status quo in six of seven projects). Rejected:
  the platform performs the replay, so the platform owns the hazard.
- **Idempotency only at the adapter boundary.** Rejected: adapters differ in
  capability (ADR-0012), so a per-adapter answer gives inconsistent guarantees —
  the same reason Cloudflare's channels doc rejects hiding durability in each
  provider adapter.
- **Exactly-once via distributed transactions.** Rejected: not available across
  arbitrary third-party tool endpoints.
- **Deferring until a consumer needs it.** Rejected on evidence — LangGraph's
  double execution is verified, not hypothetical. Note this is the *opposite* call
  from ADR-0003, where seven projects showed no consumer for agent messaging. The
  asymmetry is deliberate: here the failure is demonstrated and silent, there the
  demand is speculative.

## Evidence log

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | raises | `libs/langgraph/langgraph/types.py @ 3803173`; verified empirically | Side effect before `interrupt()` runs **twice** on resume. The finding that makes this ADR necessary. |
| OpenHands | confirms gap | openhands-sdk 1.43.1 | No idempotency concept. |
| Letta | confirms gap | @letta-ai/letta-code 0.31.0 | No idempotency concept. |
| Google AX | partial | `internal/harness/substrate/substrate.go:92-95 @ b777313` | `CreateActor` idempotent with the reasoning stated in a comment, and atomic per-step log appends — but tool effects unprotected. |
| Omnigent | partial | `omnigent/stores/conversation_store/__init__.py:1035-1049 @ ba9e371` | Fixed an adjacent lost-update race (bug #9) with `BEGIN IMMEDIATE`/`SELECT FOR UPDATE`; tool effects unprotected. |
| Cloudflare Agents | **confirms** | `packages/agents/src/index.ts:2282,5522-5590 @ 2f957bc`; test verified 48/48 | `idempotency_key TEXT UNIQUE` on the fiber ledger, checked pre-execution, `accepted: false` on duplicate, throws on conflicting identity. Verified the *side effect* ran once, not merely that the call returned early. |
| AG2 | confirms | `ag2/network/hub/core.py:2626-2644 @ 90f490a`; `ag2/network/client/handlers.py:198-211`; verified: 39 tests pass | **Second independent precedent, with a better key for reply-shaped work.** Rather than generating and propagating an explicit key, `find_envelope_by_causation(channel_id, sender_id, causation_id)` returns the prior accepted envelope "so the handler can **skip the side effect**" after an at-least-once redelivery. The reply *is* the idempotency record. Critically it is checked **before** the turn-ownership probe, "so a redelivery is a no-op regardless of whose turn it now is". Our ledger should support both key kinds. One caveat to design around: terminal-channel pruning clears the causation index, so AG2's guarantee has a retention horizon that conflates "no duplicate" with "cannot tell". |
| Pydantic AI | confirms | `pydantic_ai_slim/pydantic_ai/durable_exec/AGENTS.md @ b48ee38` | Confirms by honest delegation: no effect ledger, because idempotency is the durable engine's job and the integration guidelines require retries to survive the boundary. A legitimate answer for a library — and a reminder that **our ledger must interoperate with an engine that has its own.** If a caller runs our platform inside Temporal, two idempotency mechanisms must not fight. |
| Google Agent Platform | confirms | `src/google/adk/apps/_configs.py:38-40 @ 85b52f6` | **States this ADR's requirement more precisely than I did.** `ResumabilityConfig` documents the hazard directly: "ADK resumes the invocation in a best-effort manner: 1. **Tool call to resume needs to be idempotent because we only guarantee an at-least-once behavior once resumed.** 2. Any temporary / in-memory state will be lost upon resumption." A platform naming its guarantee exactly and pushing the remaining obligation to the developer — which is honest in the way Cloudflare's channels doc demands. Our ADR should quote it, then explain why we take the obligation **back**: a platform that performs the replay owns the hazard, and asking every tool author to be idempotent asks each of them to solve a distributed-systems problem correctly. |
| HumanLayer | confirms | `hld/store/errors.go:13-42 @ 99abe67`; verified: approval, bus and store tests pass after `make mocks` | **Confirms the ADR in a place I had not considered: the approval decision itself.** `ErrAlreadyDecided` and `AlreadyDecidedError{ID, Status}` produce `"approval %s already decided with status: %s"` rather than overwriting or failing opaquely — verified by `TestApprovalErrors/UpdateApprovalResponse_AlreadyDecided`. An approval UI *will* retry, so the decision needs the same guard as an agent side effect. **Generalises the ADR: any operation a human or a UI can retry needs an idempotency guard that returns the existing outcome.** |
| AWS AgentCore | confirms | `src/bedrock_agentcore/policy/client.py:250,267-268 @ 826416a` | Third precedent, and the most **uniform**. `clientToken` is a caller-supplied idempotency token on mutating control-plane calls — the AWS-wide convention, applied consistently rather than per-feature. Cloudflare has explicit keys on durable work, AG2 dedupes replies by causation, AWS makes idempotency a platform-wide contract. **The transferable lesson is uniformity: one convention across every mutating operation beats three mechanisms in three subsystems.** |
| Microsoft Agent Framework | confirms | `python/packages/core/agent_framework/_workflows/_checkpoint.py:55-58 @ e34bf48` | Confirms weakly but usefully: checkpoints capture **only committed state** — "pending state changes are not included in checkpoints" — which is the effect-ledger instinct applied at state granularity. A checkpoint can never record a half-applied mutation. |
| Agent Control | neutral | `engine/src/agent_control_engine/core.py @ 7cb21af` | Not an execution layer. |
