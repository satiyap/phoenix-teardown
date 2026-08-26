# Sources — HumanLayer

## Repository

- repo: https://github.com/humanlayer/humanlayer
- commit: `99abe673498cf8bdcd5f989aebe9406a27185b3b`
- commit date: **2026-06-18** — roughly two months older than every other project
  read in this study. Claims pinned accordingly.
- cloned on: 2026-08-26 (`--depth 1` to `~/dev/_teardown_src/humanlayer`)
- size: 25MB
- languages: Go (`hld` daemon, `claudecode-go`), TypeScript (`hlyr`, `humanlayer-wui`, `packages/`)
- license: **Apache-2.0**, verified by reading `LICENSE` ("Apache Software License
  2.0, Copyright (c) 2024, humanlayer Authors"). GitHub's API reports NOASSERTION.

## Verification

```
cd hld
GOWORK=off go build ./...                    → OK
GOWORK=off go test ./bus/...                 → ok
GOWORK=off go test ./approval/...            → FAILS: undefined mocks
PATH=$PATH:~/go/bin GOWORK=off make mocks    → generates 6 mock files
GOWORK=off go test ./approval/...            → ok
GOWORK=off go test ./store/... -run Approval → ok
```

`make mocks` runs `mockgen` against six interface files (`session/types.go`,
`session/claudecode_wrapper.go`, `approval/types.go`, `client/types.go`,
`bus/types.go`, `store/store.go`). A fresh clone cannot run the approval tests
until this is done, which is discoverable only from the `Makefile`.

The tests that matter for `C11`:

```
TestApprovalErrors/GetApproval_NotFound                      PASS
TestApprovalErrors/UpdateApprovalResponse_AlreadyDecided     PASS
TestApprovalErrors/UpdateApprovalResponse_NotFound           PASS
TestApprovalErrors/UpdateApprovalResponse_DeniedApproval     PASS
```

`_AlreadyDecided` is the idempotency guard on the decision — the evidence for the
ADR-0014 generalisation.

## Key source files

| Path | Why it matters |
|---|---|
| `hld/store/sqlite.go:201-220` | **The `approvals` table** — status `CHECK`, `responded_at`, `tool_name`, `tool_input`, `comment`, and a **partial index** `WHERE status = 'pending'` |
| `hld/store/sqlite.go:132-161` | `conversation_events` with `approval_id` / `approval_status` denormalised onto the tool-call row, plus `is_completed` |
| `hld/store/sqlite.go:95-130` | `sessions` with `cost_usd`, `dangerously_skip_permissions`, and `dangerously_skip_permissions_expires_at` |
| `hld/store/sqlite.go:373-411` | Migration 6 (`parent_tool_use_id`) — column-existence check before `ALTER TABLE`, so migrations are idempotent |
| `hld/store/store.go:274-284` | The nine session states, including `waiting_input`, `interrupting`, `interrupted`, `draft`, `discarded` |
| `hld/store/errors.go:13-42` | `ErrAlreadyDecided`, `AlreadyDecidedError{ID, Status}` |
| `hld/approval/types.go:10-25` | The six-method `approval.Manager` interface, including `CreateApprovalWithToolUseID` |
| `hld/bus/types.go:9-60` | Five typed events, `EventFilter`, `Subscriber`, `EventBus`; the `reason="expired"` / `expired_at` payload for permission expiry |
| `hld/session/types.go:11-13` | `ApprovalReconciler` — "interface for reconciling approvals after session restart" |
| `hld/session/manager.go:512-528` | Reconciliation call site: 2s cancellable wait, then reconcile by `run_id`, **log on failure rather than fail the session** |
| `hld/PROTOCOL.md:1-40` | JSON-RPC 2.0 over a Unix socket; path, 0600 permissions, line-delimited framing, request/response/error formats |
| `hld/session/claudecode_wrapper.go` | The `ClaudeSession` adapter seam |
| `hld/mcp/` | MCP server — approvals answerable by another agent |
| `hld/api/server.gen.go` | Generated OpenAPI surface |

## Negative findings

| Searched for | Result |
|---|---|
| **approver identity on a decision** | **Nothing.** `comment` records *why*, never *who*. The audit gap that raised ADR-0015 |
| agent identity / versioning / revocation | Nothing |
| OpenTelemetry | **Nothing** — the typed event bus is the only observability |
| agent-to-agent messaging | Nothing; `parent_tool_use_id` is a sub-task tree |
| memory / knowledge / compaction | Nothing |
| sandboxing, egress control | Nothing — approval is the control instead of isolation |
| tenancy, principals, multi-user auth | Nothing; 0600 socket is the model |
| version pinning | Nothing |
| the rule that required an approval | **Nothing** — delegated to the harness's permission mode |
| compensation / rollback | Nothing |

## Documentation

| Path | Read on | Notes |
|---|---|---|
| `hld/PROTOCOL.md` @ 99abe67 | 2026-08-26 | The wire protocol, complete enough for a third-party client |
| `hld/TESTING.md` @ 99abe67 | 2026-08-26 | Test layout and mock generation |
| `README.md`, `humanlayer.md` @ 99abe67 | 2026-08-26 | Product overview |
| `CLAUDE.md`, `hld/CLAUDE.md` @ 99abe67 | 2026-08-26 | Agent-facing repo conventions |
