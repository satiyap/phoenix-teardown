# Sources — Google AX (Agent Executor)

## Repository

- repo: https://github.com/google/ax
- commit: `b77731302075b3630b200af5e2cf63ac93b5f315`
- commit date: 2026-08-19
- cloned on: 2026-08-26 (`--depth 1` to `~/dev/_teardown_src/ax`)
- language: Go 1.26
- homepage: https://agentexecutor.io

The repo header warns: "This file is in active development and significant
changes can be made with breaking changes." External PRs are paused. Every claim
is pinned to the commit above.

## Verification

Built and tested locally 2026-08-26 (a stray parent `go.work` required `GOWORK=off`):

```
GOWORK=off go build ./...                        → OK
GOWORK=off go test ./internal/controller/...     → ok (controller, eventlog)
GOWORK=off go test ./internal/controller/ -run "Resum|Canonical" -v
```

All four resumption tests pass, including
`TestExec_ResumeExplicitDifferentHarnessRejected`, which asserts the error
"harness ID changed from harness-a to harness-b". That is the `S3` / ADR-0011
evidence.

## Key source files

| Path | Why it matters |
|---|---|
| `proto/ax.proto` (235 lines) | The entire contract. Northbound `InteractionsService`, southbound `HarnessService`, `StepEvent`, `State`, `CancelReason`, `Step` types |
| `proto/ax.proto:27-29` | "A conversation cannot be continued before the last execution is completed or failed" |
| `proto/ax.proto:85-91` | `HarnessService.Connect` — bidirectional stream, "zero or more outputs frames terminated by exactly one end" |
| `proto/ax.proto:94-109` | `State` (4 values) and `CancelReason` (`USER_REQUESTED\|TIMEOUT\|INTERNAL_ERROR`) |
| `proto/ax.proto:125-131` | `CreateInteraction` with implicit resumption, plus the `TODO` that Interaction should become a pollable resource |
| `proto/content.proto:28-47` | `ApprovalDecision`, `DeclineDecision`, `ConfirmationContent(id, question, oneof decision)` — approvals as protocol content |
| `internal/controller/controller.go:15,33` | "single-writer orchestrator" / "single-writer system for managing agentic loops" |
| `internal/controller/controller.go:74-76` | `TODO`: "We need to consolidate agents and harness registration" |
| `internal/controller/controller.go:82-85` | **Refuses resume on harness change** — the ADR-0011 behaviour |
| `internal/controller/controller.go:224-241` | `ResumptionState` folds the event log to recover state + harness id |
| `internal/controller/eventlog/eventlog.go:28-40` | Three-method `EventLog` interface; "replaying the log in order brings the executor back to a consistent state" |
| `internal/controller/eventlog/sql.go:38-66` | `MAX(step)+1` computed **inside** the insert transaction |
| `internal/controller/eventlog/postgres.go:44-50` | `PRIMARY KEY (conversation_id, step)` |
| `internal/controller/registry.go:38-51` | In-memory harness registry; refuses duplicate registration |
| `internal/harness/harness.go:42-63` | `Harness{Start}` → `Execution{Run, Queue, ID, Close}` — four-method adapter contract, no checkpoint/restore |
| `internal/harness/substrate/substrate.go:86-133` | `CreateActor` (idempotent) → `ResumeActor` → dial worker IP → `waitForHealthy` |
| `internal/harness/substrate/substrate.go:135-138` | Harness without a health service is "treated as ready" — the fail-open case |
| `internal/telemetry/telemetry.go:23-28,48-86` | OpenTelemetry: OTLP gRPC exporter, propagation, `TracerProvider` |
| `internal/server/server.go:82-83` | **Only** logging interceptors — no authN, no authZ |
| `internal/config/config.go:47-133` | Declarative YAML: server, eventlog, registry (harnesses), skills, telemetry |
| `internal/skills/` | Gemini Enterprise registry + local dir sources, harness-agnostic |
| `manifests/` | Kubernetes deployment + Postgres + install script (deployment manifests, **not** agent manifests) |

## Negative findings

| Searched for | Result |
|---|---|
| auth interceptor, TLS creds in server path | **Nothing.** Only `LoggingInterceptor` / `StreamLoggingInterceptor` |
| tenant / organization | Nothing |
| agent versioning / revocation | Nothing; registry is in-memory, keyed by id only |
| subagents / agent-to-agent messaging | Nothing — no subagent concept at all |
| memory subsystem | Nothing; skills are the only knowledge mechanism |
| policy / interception | Nothing |
| cost / quota / budget | Nothing |
| MCP / A2A / ACP | Nothing |

## Notable dependencies

| Dependency | Role |
|---|---|
| `github.com/agent-substrate/substrate` | The actor system providing suspendable/resumable sandboxes. AX implements no isolation itself |
| `go.opentelemetry.io/otel` + OTLP | Tracing |
| Gemini Enterprise Skill Registry | Optional skill source |
| Vertex GenAI Interactions API | Backs the `antigravity-interactions` harness |

## Documentation

| URL | Read on | Notes |
|---|---|---|
| `README.md` @ b777313 | 2026-08-26 | "distributed harness runtime", single-writer, event log, resumption |
| https://agentexecutor.io | 2026-08-26 | Project homepage |
