# Teardown — HumanLayer

| | |
|---|---|
| Repo | https://github.com/humanlayer/humanlayer |
| Commit read | `99abe673498cf8bdcd5f989aebe9406a27185b3b` (2026-06-18) |
| License | Apache-2.0 (GitHub reports NOASSERTION; verified manually) |
| Read on | 2026-08-26 |
| Evidence class | A |
| Depth | targeted (G-section, `C11`) |
| Runtime class | `attached_harness` — a local daemon supervising Claude Code sessions |

A **targeted pass**, scoped to the human-interaction section and durable approval,
because HumanLayer is the only project in the study *architected to answer* those
questions. That framing was set in the Phase 3 final findings after three passes
where I mis-budgeted a project by trusting a cheap signal.

It delivers what was predicted and one thing that was not: the only **`Approval`
table** in the study, and the only **expiring permission bypass**.

Note the commit date — 2026-06-18, roughly two months older than every other
project read. Claims are pinned accordingly.

---

## 1. What problem it solves

Putting a human in the loop of an autonomous coding agent without the human having
to babysit a terminal. A local daemon (`hld`) owns sessions, persists pending
approvals, and publishes events so a CLI (`hlyr`), a desktop UI
(`humanlayer-wui`), or an MCP client can present them.

## 2. Core architectural thesis

**An approval is a durable resource with its own lifecycle, not a blocked function
call.**

Everything follows from that. The daemon persists approvals to SQLite so a pending
decision outlives the process that requested it; the tool call in the transcript
carries the approval's id and status inline; and the decision itself is recorded
with a comment or a reason. The agent does not block on a callback — it reaches a
state, and the state is stored.

## 3. Resource / object model

```text
Session                      (hld/store/sqlite.go:95-130)
 ├── status                  draft | starting | running | completed | failed
 │                           | waiting_input | interrupting | interrupted
 │                           | discarded
 ├── cost_usd                per-session spend
 ├── dangerously_skip_permissions          bool
 ├── dangerously_skip_permissions_expires_at   TIMESTAMP  ← the bypass EXPIRES
 └── ConversationEvent[]     (sequence-ordered)
      ├── tool_id, tool_name, tool_input_json
      ├── tool_result_for_id, tool_result_content
      ├── is_completed         TRUE when tool result received
      ├── approval_status      NULL | pending | approved | denied
      ├── approval_id          correlated approval
      └── parent_tool_use_id   sub-task tracking (migration 6)

Approval                     (hld/store/sqlite.go:201-220)
  id PRIMARY KEY
  run_id, session_id
  status        CHECK (status IN ('pending','approved','denied'))
  created_at, responded_at
  tool_name, tool_input        (JSON)
  comment                      denial reason OR approval note
```

## 4. Runtime model

A long-lived Go daemon over a **Unix domain socket** with JSON-RPC 2.0,
line-delimited, at `~/.humanlayer/daemon.sock` with permissions **0600**
(`hld/PROTOCOL.md`). Sessions wrap Claude Code via `claudecode-go`.

The socket choice is the security model: filesystem permissions are the
authentication. For a single-user local daemon that is correct and honest — no
tokens to leak, no port to expose. It also means the design does not generalise to
multi-user without replacement, which the project does not pretend otherwise.

## 5. Execution lifecycle

**The session state machine is the best in the study for this problem**
(`hld/store/store.go:274-284`):

```text
draft → starting → running → completed
                 ↘ failed
                 ↘ waiting_input        ← blocked on a human
                 ↘ interrupting → interrupted   ← resumable
        draft    ↘ discarded
```

Three things nothing else has:

- **`waiting_input` as a first-class status.** Google AX handles approvals as
  content and needs no such state; every other project leaves "blocked on a human"
  implicit. Making it a status means a supervisor UI can list exactly the sessions
  needing attention with an indexed query.
- **`interrupting` distinct from `interrupted`**, commented as "received interrupt
  signal and is shutting down" versus "was interrupted **but can be resumed**".
  This is precisely the `CANCELLING` transitional state my revised domain model
  proposed, and HumanLayer is the only project that has it. Cancellation is not
  instantaneous, so a state machine that pretends it is will lie during the gap.
- **`draft` and `discarded`**, so a session can be composed before it runs and
  abandoned without ever having run.

## 6. Durability model

SQLite with numbered migrations (at least six, each guarded by a
column-existence check before `ALTER TABLE` — so migrations are idempotent and
re-runnable).

**Approvals are durable by design, which is the `C11` answer.** The
`approvals` table has a `CHECK` constraint restricting status to
`pending | approved | denied`, and a **partial index** on pending rows only:

```sql
CREATE INDEX idx_approvals_pending ON approvals(status) WHERE status = 'pending';
```

A partial index for the pending set is a small thing that signals the access
pattern was designed rather than discovered: the common query is "what needs a
human right now", and it stays cheap regardless of history size.

**Decisions are guarded against double-resolution.** `store/errors.go` defines
`ErrAlreadyDecided` and an `AlreadyDecidedError{ID, Status}` whose message is
`"approval %s already decided with status: %s"`. **Verified by running the tests**
— `TestApprovalErrors/UpdateApprovalResponse_AlreadyDecided` passes, along with
`_NotFound` and `_DeniedApproval`.

That is idempotency on the *decision*, and it matters for the same reason
ADR-0014 does: an approval UI will retry, and a double-approve must not
re-execute or silently overwrite the first decision. Returning the *existing*
status rather than a bare conflict is what makes the error actionable.

## 7. Agent identity and lifecycle

No agent identity. Sessions have ids and `run_id`s; the agent is Claude Code. No
registry, versioning or revocation.

## 8. Multi-agent communication

Absent. `parent_tool_use_id` (migration 6, "for sub-task tracking") gives a
sub-agent tree within a session, but there is no messaging between agents. AG2
remains the sole F-section answer.

## 9. Human interaction model

The strongest single-user HITL design in the study, and the section this pass
existed to read.

**Approval is a resource, not a callback.** `approval.Manager`
(`hld/approval/types.go`) is six methods:

```go
CreateApproval(ctx, runID, toolName, toolInput) (string, error)
CreateApprovalWithToolUseID(ctx, sessionID, toolName, toolInput, toolUseID) (*store.Approval, error)
GetPendingApprovals(ctx, sessionID) ([]*store.Approval, error)
GetApproval(ctx, id) (*store.Approval, error)
ApproveToolCall(ctx, id, comment string) error
DenyToolCall(ctx, id, reason string) error
```

Two details worth taking:

- **Approve carries a `comment`, deny carries a `reason`**, both landing in one
  `comment` column documented as "for denial reasons or approval notes". A human
  who approves something unusual can say why, and that note is as durable as the
  decision. Google AX's `DeclineDecision.reason` field was `reserved` (removed);
  here it is used.
- **`CreateApprovalWithToolUseID` correlates the approval to the specific tool
  call.** The transcript row carries `approval_id` and `approval_status` inline, so
  reading the conversation shows approval state without a join — the approval and
  the thing approved are visibly the same event.

**The event bus** (`hld/bus/types.go`) publishes five typed events —
`new_approval`, `approval_resolved`, `session_status_changed`,
`conversation_updated`, `session_settings_changed` — with an `EventFilter` on
type, session and run. Subscribers get a channel and a context. So a UI is
push-driven rather than polling, and the daemon does not care how many surfaces
are attached (CLI, desktop, MCP).

**The expiring bypass is the find of this pass.** `dangerously_skip_permissions`
paired with `dangerously_skip_permissions_expires_at`, and an expiry that emits
`session_settings_changed` with `reason="expired"` and `expired_at`
(`hld/bus/types.go:20-32`).

Every other project treats "skip approvals" as a mode you are in or out of. Modes
get switched on during a frustrating session and never switched off — approval
fatigue turns into a permanently disabled control. **A bypass with a TTL that
announces its own expiry converts a permanent hole into a temporary one, and tells
the operator when it closed.** The naming (`dangerously_`) does the same work as
ADK's `unsafe_local_code_executor`.

## 10. Context and memory

None. Context is Claude Code's; the daemon stores the transcript for display and
correlation, not for recall.

## 11. Tools and capabilities

Tools belong to Claude Code. HumanLayer intercepts them for approval and exposes
an MCP server (`hld/mcp/`) so approvals can be driven by another agent. No
capability model.

## 12. Security and IAM

Local-only by design: a 0600 Unix socket, so filesystem permissions are the
authorization model. No principals, no multi-user auth, no tenancy.

Within that scope the security thinking is good: the bypass is named
`dangerously_`, it expires, and the expiry is an event. What is absent is any
notion of *who* approved — the `comment` records a rationale but not an identity,
so an audit trail cannot answer "which human approved this" in a shared setting.
That is the honest consequence of a single-user socket model.

## 13. Sandboxing

None. Claude Code runs with the daemon's privileges.

## 14. Orchestration

Session management and interruption, plus `parent_tool_use_id` for sub-task
trees. `claudecode-go` wraps the agent process. No workflow engine, no scheduling,
no compensation (`L8` — ten for ten).

## 15. Observability

`cost_usd` per session (third project with cost tracking, after Omnigent and
Pydantic AI), the full conversation event stream with sequence ordering, and the
typed event bus. No OpenTelemetry — notable given four of nine deep projects have
it, though the commit predates several of those.

## 16. Multi-tenancy

Absent, and out of scope for a local single-user daemon.

## 17. Protocols and APIs

JSON-RPC 2.0 over a Unix socket, documented in `hld/PROTOCOL.md` with request,
response and error formats spelled out. Also a generated OpenAPI surface
(`hld/api/server.gen.go`), an MCP server, a Go SDK, and TypeScript packages.

Documenting the wire protocol in the repo — with the socket path, permissions, and
line-delimited framing stated — is the same discipline as AX's proto comments, and
it is what makes a third-party UI possible.

## 18. Storage

SQLite, one file, with idempotent numbered migrations that check for column
existence before altering. Partial and composite indexes chosen per access pattern
(`idx_approvals_pending`, `idx_conversation_session(session_id, sequence)`).

## 19. Deployment architecture

A local daemon plus clients: `hlyr` (CLI), `humanlayer-wui` (desktop), MCP server,
`apps/`, `packages/`. `docker-compose.yml` for supporting services.

## 20. OSS / license / commercial model

Apache-2.0 — verified by reading `LICENSE` ("Apache Software License 2.0,
Copyright (c) 2024, humanlayer Authors") because GitHub's API reports
NOASSERTION. Worth recording: **licence metadata is not licence evidence.**

The commercial product is a hosted approval service; the OSS daemon is the local
half.

Verdict: **REUSE (targeted).** Apache-2.0 and the `Approval` schema plus state
machine port directly. Go, single-user, and Claude-Code-specific, so the code does
not.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | undefined | Filesystem permissions are the whole model; no principals. |
| S2 Torn side effect | **inferable** | Not a tool-call ledger, but the *decision* is idempotent: `ErrAlreadyDecided` with the current status, verified by test. Relevant to ADR-0014 because an approval UI retries. |
| S3 Upgrade mid-flight | undefined | No version pinning. |
| S4 Concurrent memory write | n/a | No memory store. |
| S5 Cancellation tree | **first_class_answer** | **Only project with a transitional cancel state.** `interrupting` ("received interrupt signal and is shutting down") is distinct from `interrupted` ("was interrupted **but can be resumed**"). Cancellation is not instantaneous and the state machine says so. |
| S6 Silent context loss | undefined | No compaction. |
| S7 Poison message | undefined | No queue or retry policy. |
| S8 Tenant leak | undefined | Single-user by design. |
| S9 Runaway spend | **inferable** | `cost_usd` per session is recorded, and the *expiring* permission bypass bounds unattended autonomy in time. Measured and time-bounded, not enforced by budget. |
| S10 Zombie sandbox | undefined | No sandbox. |
| **C11 durable approval** | **first_class_answer** | The reason for this pass. A durable `approvals` table with a status `CHECK`, a partial index on pending, `responded_at`, correlation onto the transcript event, and `ErrAlreadyDecided` on double-resolution. **The only real `Approval` resource in the study.** |

## 22. Strongest ideas

1. **An `Approval` table with a status `CHECK` constraint** — the only durable
   approval resource in the study.
2. **A partial index on pending approvals only.** "What needs a human now" stays
   cheap forever.
3. **`ErrAlreadyDecided` carrying the current status**, so a retried decision
   reports what it already was instead of failing opaquely.
4. **`approval_id` and `approval_status` denormalised onto the transcript event**,
   so approval state reads inline with the tool call it governs.
5. **`waiting_input` as a first-class session status**, making "blocked on a human"
   an indexed query rather than an inference.
6. **`interrupting` distinct from `interrupted`** — a transitional cancel state,
   with resumability noted in the comment.
7. **`draft` and `discarded` states**, so a session can exist before it runs and be
   abandoned without running.
8. **An expiring permission bypass** (`dangerously_skip_permissions_expires_at`)
   that emits `session_settings_changed` with `reason="expired"`.
9. **Naming the dangerous flag `dangerously_`**, same instinct as ADK's
   `unsafe_local_code_executor`.
10. **Approve-with-comment and deny-with-reason**, both durable.
11. **A typed event bus with filters on type, session and run**, so many UI
    surfaces attach without the daemon knowing about them.
12. **The wire protocol documented in the repo**, including socket path,
    permissions and framing.
13. **Idempotent migrations** that check for column existence before altering.
14. **0600 Unix socket as the authentication model** — correct and honest for a
    single-user daemon.

## 23. Weakest architectural choices

1. **No record of *who* approved.** The `comment` captures a rationale but not an
   identity, so the audit trail cannot answer "which human decided this".
2. **Single-user by construction.** Filesystem permissions do not generalise.
3. **No OpenTelemetry**, where four of nine deep projects have it.
4. **No agent identity, versioning or revocation.**
5. **No sandboxing** — Claude Code runs with daemon privileges.
6. **Tightly coupled to Claude Code** via `claudecode-go`.
7. **Tests need generated mocks** (`make mocks`) before they run, so a fresh clone
   fails `go test ./approval/...` until you know that.

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| `Approval` table schema + status `CHECK` | **REUSE (port)** | The only durable approval resource found; port nearly verbatim |
| Partial index on pending approvals | ADOPT_AS_STANDARD | The hot query stays cheap as history grows |
| `ErrAlreadyDecided` with current status | **ADOPT_AS_STANDARD** | Retried decisions must be idempotent and informative |
| `approval_id`/`approval_status` on the transcript event | ADOPT_AS_STANDARD | Approval state reads inline with what it governs |
| `waiting_input` session status | **ADOPT_AS_STANDARD** | Blocked-on-human becomes queryable |
| `interrupting` → `interrupted` | **ADOPT_AS_STANDARD** | Confirms the `CANCELLING` state in our domain model |
| `draft` / `discarded` | REUSE | Pre-run composition and abandonment |
| Expiring permission bypass + expiry event | **ADOPT_AS_STANDARD** | Converts a permanent hole into a temporary one |
| `dangerously_` naming | ADOPT_AS_STANDARD | Make the unsafe path visible |
| Approve-with-comment / deny-with-reason | ADOPT_AS_STANDARD | Rationale is as durable as the decision |
| Typed event bus with filters | REUSE (pattern) | Many surfaces, one daemon |
| Protocol documented in-repo | REUSE (practice) | Enables third-party clients |
| Idempotent column-checked migrations | REUSE (pattern) | Re-runnable schema evolution |
| Filesystem-permission auth | BUILD | Reject; we are multi-user |
| Approval without an approver identity | BUILD | Reject; audit requires the principal |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | neutral | No agent identity; sessions and runs only. |
| ADR-0002 | **confirms** | `Session.status` carries nine states including `draft`, `waiting_input`, `interrupting` and `discarded` — richer than any run state machine in the study, and evidence that a Run's lifecycle needs states for *before it starts* and *while it stops*. |
| ADR-0003 | confirms | No agent-to-agent messaging; `parent_tool_use_id` gives a sub-task tree only. |
| ADR-0004 | confirms | An `attached_harness` wrapping Claude Code through `claudecode-go`, with the daemon owning durability — the same split AX established (control plane owns the log, adapter streams). |
| ADR-0005 | neutral | MCP is exposed as a *surface for approvals*, an inversion worth noting: MCP as the channel by which another agent answers a human-in-the-loop request. |
| ADR-0006 | neutral | No A2A. |
| ADR-0007 | **challenges** | Sharpens the amendment ADK prompted. HumanLayer has an excellent approval *record* and **no approver identity** — the `comment` says why, never who. So a system can have durable human decisions and still fail an audit. **Our `Approval` must reference a `Principal`, not just carry a note.** |
| ADR-0008 | neutral | No memory or knowledge subsystem. |
| ADR-0009 | neutral | No sandbox. |
| ADR-0010 | **challenges (weakly)** | No OTel at all, where four of nine deep projects have it. The typed event bus is good for UIs and useless for tracing. Confirms the ADR by contrast: an event bus and a trace are not substitutes. |
| ADR-0011 | neutral | No version pinning. |
| ADR-0012 | neutral | No capability model. |
| ADR-0013 | **confirms** | The decision record is the traceability: which tool, what input, what status, when responded, and a free-text rationale. Missing the *rule* that required approval, so it traces the decision but not the policy — which is exactly the half AG2 and Omnigent supply. |
| ADR-0014 | **confirms (in a new place)** | Idempotency applied to the *approval decision* rather than the tool effect: `ErrAlreadyDecided` returns the existing status instead of re-deciding. Generalises the ADR — **any operation a human or UI can retry needs the same guard**, not only agent side effects. |

**Three things to change now.**

1. **`Approval` becomes a real resource in the domain model.** My strawman had it as
   a state on a Run. HumanLayer shows it needs its own table: id, run reference,
   correlated tool-call id, status with a constraint, `created_at`/`responded_at`,
   the request payload, a decision rationale — and, per §25 ADR-0007, an
   **approver principal**, which HumanLayer lacks.

2. **The Run state machine gains four states.** `DRAFT` (composed, not started),
   `WAITING_INPUT` (blocked on a human, indexed), `CANCELLING` (interrupt received,
   still shutting down — HumanLayer's `interrupting`, and the only precedent for the
   state my domain model proposed), and `DISCARDED`. The `interrupting`/`interrupted`
   split is the important one: cancellation takes time, and a state machine that
   pretends otherwise reports a lie during the gap.

3. **Dangerous overrides expire.** Adopt `dangerously_skip_permissions_expires_at`
   as a general rule: any control that disables a safety check carries a TTL and
   emits an event when it lapses. Modes get switched on under pressure and never
   switched off; a grant that expires cannot become permanent by neglect.

**One process note.** GitHub's API reports this repo's licence as NOASSERTION; the
`LICENSE` file says Apache-2.0 plainly. Phase 1 flagged the discrepancy and
verified manually, which was correct. **Licence metadata is not licence evidence** —
worth carrying into the build/reuse map, since an automated scan would have
excluded a project whose patterns we are now porting.

## 26. Open questions

- **Answered by tracing it.** Yes, and it is an explicit abstraction:
  `session.ApprovalReconciler` is documented as an "interface for reconciling
  approvals after session restart", with `ReconcileApprovalsForSession(ctx, runID)`
  invoked from three call sites in `session/manager.go` (:522, :1849, :2067). On
  session start it waits 2s for the session to come up (cancellable), then
  reconciles by `run_id` — and **logs the error rather than failing the session** if
  reconciliation fails. That fail-open choice is defensible precisely because the
  approvals themselves are durable: a failed reconcile leaves the pending row
  intact for the next attempt, whereas failing the session would strand work. Note
  the pattern for our design: **reconciliation keyed on the run, triggered by
  restart, non-fatal on failure.** (→ OQ-031, resolved)
- Does the hosted (commercial) service add an approver identity, making the audit
  gap a local-only limitation? (→ OQ-032)
