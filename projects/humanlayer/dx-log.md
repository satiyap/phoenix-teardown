# DX log — HumanLayer

Targeted pass, 2026-08-26, scoped to the G-section and `C11`. Built the daemon and
ran the approval, bus and store test suites.

- Clone to passing approval tests: **~12 minutes**, one blocking obstacle
- The whole data model is three tables, readable in one sitting

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | Cloned; found `hld/` with `approval/`, `bus/`, `store/`, `PROTOCOL.md` | Exactly the subsystems this pass existed to read |
| 0:03 | Read `hld/approval/types.go` | A six-method `Manager` — approve carries a *comment*, deny carries a *reason* |
| 0:07 | Grepped the approvals schema | **A real `Approval` table**, with a status `CHECK` and a partial index on pending |
| 0:12 | Read `conversation_events` | `approval_id`/`approval_status` denormalised onto the tool-call row |
| 0:17 | `GOWORK=off go build ./...` | OK (the `GOWORK=off` workaround learned from Google AX applied directly) |
| 0:19 | `go test ./approval/...` | **Failed**: `undefined: store.NewMockConversationStore` |
| 0:23 | Found `make mocks` in the Makefile, installed `mockgen` | Six mock files generated |
| 0:26 | Re-ran tests | Approval, bus and store suites all pass, including `_AlreadyDecided` |
| 0:31 | Read `store.go:274-284` | The nine session states — `waiting_input`, and `interrupting` vs `interrupted` |
| 0:36 | Grepped `dangerously_skip_permissions` | It has an **`expires_at`**, and expiry emits an event |
| 0:42 | Traced `ApprovalReconciler` to its call sites | Restart reconciliation, keyed by run, non-fatal — answered my own open question |

## Friction points

1. **Tests do not run on a fresh clone.** `go test ./approval/...` fails with
   undefined mock constructors until `make mocks` generates them. The `Makefile`
   documents it; the error message does not point there. A generated-code check in
   CI or a `go:generate` directive at the interface would remove the guess.
2. **`mockgen` is an unmanaged prerequisite.** Not vendored, not in a tools file —
   `go install go.uber.org/mock/mockgen@latest` first, and it lands in `~/go/bin`
   which may not be on `PATH`.
3. **The commit is two months older than everything else I read.** Not a fault, but
   it means absences (no OTel especially) may reflect timing rather than position,
   and I recorded that caveat rather than treating the gap as a design stance.
4. **Two overlapping API surfaces.** `PROTOCOL.md` documents JSON-RPC over the
   socket, and `hld/api/server.gen.go` is a generated OpenAPI server. Which is
   canonical for a new client is not stated.

## What was genuinely good

1. **Three tables, and every column earns its place.** `sessions`,
   `conversation_events`, `approvals`. I understood the entire data model in about
   fifteen minutes, and the indexes tell you the access patterns: a *partial* index
   on pending approvals says "the hot query is what needs a human now".
2. **A protocol document with the boring details.** Socket path, `0600`
   permissions, line-delimited framing, and the JSON-RPC request/response/error
   shapes. That is what makes a third-party UI possible, and it is the same
   discipline as AX's proto comments.
3. **Errors that carry context.** `AlreadyDecidedError{ID, Status}` renders as
   *"approval %s already decided with status: %s"*. A retrying UI learns what the
   decision already was, not merely that it failed.
4. **Comments that state the semantics, not the mechanics.** `interrupting` —
   "received interrupt signal and is shutting down"; `interrupted` — "was
   interrupted but can be resumed". Two comments that define a state machine.
5. **`dangerously_` as a prefix.** You cannot enable the bypass without typing the
   word, and you cannot leave it on forever because it expires.
6. **`ApprovalReconciler` as a named interface** rather than inline restart logic,
   with the fail-open choice visible at the call site.
7. **Interfaces plus generated mocks throughout** — store, bus, approval, session,
   client. Once generated, the daemon is testable with no SQLite and no Claude Code.

## Answers to R1–R7

- **R1 clone to running:** build is immediate; tests need `make mocks` first, so
  ~12 min including installing `mockgen`.
- **R2 concepts before hello world:** three — session, conversation event,
  approval. Among the lowest in the study.
- **R3 local dev loop:** excellent, and local is the *only* mode: one daemon, one
  SQLite file, a Unix socket, a CLI, a desktop app. Nothing to provision.
- **R4 debugging:** strong. Full transcript with approval correlation, typed events,
  a `run-with-logging.sh`, and a documented protocol for attaching a client.
- **R5 unit testing:** strong once mocks exist — every dependency is an interface,
  plus `integration_test.go`, `e2e/`, and `TESTING.md`.
- **R6 deployment:** a developer-machine daemon; `docker-compose.yml` for supporting
  services. No production deployment story, by design.
- **R7 CLI ergonomics:** `hlyr` plus a desktop UI plus an MCP server, all onto one
  daemon.

## Lessons for our own DX

**Let the indexes document the access patterns.** The partial index on pending
approvals told me what the product is for before I read any handler code. When our
schema lands, the indexes should be chosen for the queries we actually intend, and a
reader should be able to infer the workload from them.

**Put the semantics in the enum comment.** `interrupting` versus `interrupted` is
two lines of comment that define a state machine, resolve an ambiguity I had been
carrying since Phase 2, and prevented me from misreading the code. Our run states
each need one sentence explaining what is true while the run is in them.

**Generated code must not be a hidden prerequisite.** A `Makefile` target the test
command does not mention is a five-minute tax on every new reader. Either check the
generated artefacts in, or fail with a message naming the command to run.
