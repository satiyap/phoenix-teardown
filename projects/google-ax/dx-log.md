# DX log — Google AX

Timeboxed hands-on, 2026-08-26. Built and tested; no live harness run (needs
SubstrATE or Vertex credentials).

- Clone to successful build: **~3 minutes** (one `GOWORK` workaround)
- Tests green: yes, including the resumption suite

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | Cloned, looked for the contract | `proto/` — two files, 402 lines total. Whole API readable in one sitting |
| 0:08 | Read `ax.proto` | Northbound/southbound split immediately obvious; `CancelReason` typed |
| 0:15 | Read `content.proto` | `ConfirmationContent` with `oneof decision` — approvals as content, not state |
| 0:22 | Read `eventlog.go` | Three-method interface; the design comment says exactly what it guarantees |
| 0:30 | Read `sql.go` | `MAX(step)+1` inside the transaction; single-writer via primary key |
| 0:38 | `go build ./...` | Failed on an unrelated parent `go.work`; `GOWORK=off` fixed it |
| 0:42 | `go test ./internal/controller/...` | Green |
| 0:48 | Grepped for the resumption guard, found a dedicated test | `TestExec_ResumeExplicitDifferentHarnessRejected` passes — verified the ADR-0011 behaviour |
| 0:55 | Grepped for auth | Only logging interceptors. Checked twice because it was surprising |

## Friction points

1. **`go.work` interference.** A `go.work` file two directories up broke the build
   with an unrelated module's Go version constraint. Not AX's fault, but worth
   noting for anyone building inside a larger workspace: use `GOWORK=off`.
2. **No authentication anywhere.** Finding a distributed agent runtime with
   logging-only gRPC interceptors was the session's biggest surprise. Nothing in
   the README or config hints at whether auth is expected from a service mesh, so
   an operator has no guidance on how to deploy this safely.
3. **Agent vs harness is genuinely confusing**, and the code says so. `agent_id`
   on the wire actually identifies a *harness*; a `TODO` admits the two need
   consolidating. Reading requires holding that mismatch in mind.
4. **The registry is in-memory.** Harnesses come from YAML at startup, so there is
   no runtime registration and a restart loses nothing only because there was
   nothing to lose.

## What was genuinely good

1. **The whole contract is 235 lines.** I understood AX's entire model faster than
   any other project in this study. Small, typed, and the comments state
   guarantees rather than describing code.
2. **Comments that specify behaviour, not mechanics.** "Replaying the log in order
   brings the executor back to a consistent state from which execution can
   resume", and "the server streams zero or more outputs frames terminated by
   exactly one end". Those are contracts a third party can implement against.
3. **`MAX(step)+1` inside the transaction.** A one-line answer to concurrent
   append ordering that needs no lock service. Elegant.
4. **A test for the resumption guard.** The behaviour ADR-0011 wants is not just
   implemented but pinned by a test asserting the exact error string.
5. **Idempotency explained in a comment.** "CreateActor is idempotent here: on
   follow-up turns the actor was created (and suspended) on a previous turn, so
   AlreadyExists is expected and fine." Explains *why*, not just *what*.
6. **OTel from the start**, instrumenting storage and adapters, not bolted on.

## Answers to R1–R7

- **R1 clone to running:** ~3 min to build; `ax serve --config ax.yaml` with SQLite
  needs no external services.
- **R2 concepts before hello world:** four — conversation, interaction, step,
  harness. Lowest in the study.
- **R3 local dev loop:** good. A direct CLI mode (`ax --config ax.yaml --input
  "hello"`) alongside `ax serve`, SQLite for local state.
- **R4 debugging:** strong in principle — the event log is fully retrievable and
  replayable, plus OTel spans. No purpose-built inspection CLI though.
- **R5 unit testing:** strong. `harnesstest` and `eventlogtest` packages with an
  in-memory event log make controller behaviour testable without infrastructure.
- **R6 deployment:** Kubernetes manifests, `ko` image builds, single binary.
- **R7 CLI ergonomics:** thin. `ax serve` plus an input mode; no agent-management
  commands, because harnesses are YAML-declared rather than CLI-added.

## Lesson for our own DX

**A small, precisely specified contract beats a large documented one.** AX's proto
is 235 lines and I could implement an adapter against it from the comments alone.
The specific practice worth copying: state the *terminator condition* of a stream
("exactly one end frame") and the *idempotency expectation* of each call, in the
interface definition itself. Both are things an implementer would otherwise have
to discover by experiment.

Second: `harnesstest` + `eventlogtest` + an in-memory event log meant I could run
meaningful durability tests within minutes of cloning. Same lesson as LangGraph's
`InMemorySaver` — ship in-memory implementations of every pluggable interface, or
nobody tests the failure paths.
