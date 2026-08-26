# DX log — LangGraph

Timeboxed hands-on, 2026-08-26. Goal: build something durable, then break it.

- Started: clone + venv install
- Got to a running agent: **yes**, under 5 minutes
- Time to a *durable* agent with HITL: ~15 minutes

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | `pip install langgraph` | Clean, pulled `langgraph-checkpoint` and `langgraph-sdk` automatically |
| 0:03 | Wrote a 3-node `StateGraph` with `InMemorySaver` | Ran first try |
| 0:08 | Added `interrupt()` for approval | Worked as documented; `__interrupt__` key present in the result |
| 0:12 | Resumed with `Command(resume="yes")` | Worked. Noticed the side-effect double-execution immediately |
| 0:20 | Wrote the S2 probe to confirm | Confirmed: effect ran twice |
| 0:35 | Wrote S3 probe (definition change under a suspended run) | Renamed-node case returned `[]` silently — the most surprising result of the session |
| 0:50 | Wrote S5 probe (cancellation) | No cancel token in the sync path; worker kept running |

## Friction points

1. **The S2 footgun is not signposted.** The re-execution caveat is one sentence
   inside a long docstring (`types.py:864`). Nothing in the quickstart warns that
   putting a side effect before `interrupt()` in the same node double-charges.
   A first-time user will hit this in production, not in dev.
2. **Silent failure on definition change.** Renaming a node while a run is
   suspended returns an empty result with no error. There is no way to discover
   this except by testing for it, which is not something a user thinks to do.
3. **Two object models to learn.** The OSS `thread_id`-in-a-config-dict model and
   the Platform `Assistant`/`Thread`/`Run` model are quite different. Docs move
   between them without always flagging which layer is in scope.
4. **`Capability` is overloaded.** The conformance suite's `Capability` enum means
   checkpointer storage operations, not agent capabilities. Momentarily confusing
   when reading with our own vocabulary in mind.

## What was genuinely good

1. **Testing durability needs no infrastructure.** `InMemorySaver` makes
   checkpoint/resume/interrupt behaviour unit-testable. All four scenario probes
   were written and run in about 45 minutes total, which is why this teardown has
   verified findings instead of inferred ones. Worth copying as a design goal.
2. **`get_state()` is an excellent debugging surface.** Returns current values
   *and* `next` pending tasks, so "why is this stuck" has a direct answer.
3. **Durability modes are discoverable.** `sync | async | exit` shows up in the
   type signature, so the tradeoff is visible without reading a guide.
4. **Errors are legible.** `GraphInterrupt` and friends carry useful context.

## Answers to R1–R7

- **R1 clone to running agent:** under 5 minutes; ~15 to durable + HITL.
- **R2 concepts before hello world:** four (State schema, node fn, edges,
  compile+invoke). A fifth (checkpointer) for durability. Low.
- **R3 local dev loop:** `langgraph_cli` provides a dev server; as a library it is
  just a normal Python import loop. No hot reload needed at library level.
- **R4 debugging a stuck run:** strong. `get_state()` plus the debug stream shows
  pending tasks and per-task detail.
- **R5 unit testing an agent:** best in class so far. Graphs are plain callables;
  `InMemorySaver` makes durability testable in-process.
- **R6 deployment:** `langgraph_cli` builds a container (needs Postgres + Redis);
  managed deploy is the commercial path.
- **R7 CLI ergonomics:** deployment-oriented (`build`, `deploy`, `dev`). There is
  no `agent add` equivalent because there are no agents — which is itself the
  finding.

## Lesson for our own DX

The single most valuable DX property here is that **durability semantics are
testable without infrastructure**. If our platform's checkpoint/resume behaviour
can only be exercised against a real control plane, nobody will write tests for
the failure paths, and the S2/S3-class bugs will ship. An in-memory
implementation of the sandbox and checkpoint interfaces should be a v0.1
requirement, not an afterthought.
