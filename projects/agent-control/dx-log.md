# DX log — Agent Control

Targeted pass, 2026-08-26. Installed the SDK, inspected the action vocabulary and
condition model, and ran the engine test suite.

- `pip install agent-control-sdk` to inspecting types: **~40 seconds**
- Engine tests green after one missing dev dependency: **115 passed in 0.63s**
- Did not start the server (would need Docker + Postgres; the compose path is a
  single curl and looks clean)

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | Cloned; read the README thesis | "Define controls once, apply across agents, **update without redeploying**" |
| 0:04 | Listed `models/` | `controls.py`, `policy.py`, `actions.py`, `observability.py` — the whole target |
| 0:07 | Read `actions.py` | **`observe` is a canonical action.** Shadow mode, shipped — the thing fifteen projects lacked |
| 0:12 | Noticed `steer` | A third outcome I had no category for |
| 0:17 | Read `SteeringContext` examples | Procedures, not messages: "Request 2FA…, then retry with `verified_2fa=True`" |
| 0:22 | Read `ConditionNode` | Recursive `and`/`or`/`not` with a shape validator rejecting ambiguous nodes |
| 0:27 | `pip install`, inspected live | Actions confirmed; `validate_action('allow')` correctly rejected |
| 0:33 | `pytest engine/tests` | **64 failed** — then read one failure: missing `pytest-asyncio` |
| 0:36 | Installed it, reran | **115 passed** |
| 0:41 | Grepped for tenancy in `models/` | Found `namespace_key` as a field. Recorded it as "just a filter" |
| 0:47 | Checked the *server* schema | **Wrong.** Composite FKs enforce same-namespace references. Corrected the teardown |
| 0:53 | Read `engine/core.py` | Concurrent evaluation; `deny_found` early cancellation — and the shadow-bias caveat |

## Friction points

1. **A fresh clone looks broken.** `pytest engine/tests` reports 64 failures, all
   from `async def functions are not natively supported` — `pytest-asyncio` is not in
   the default install path. The first failure message does explain it, but the
   headline number says "this project is broken" when it is not.
2. **I got tenancy wrong from the API models.** `models/server.py` shows
   `namespace_key` as a response field, which reads like a filter parameter. Only the
   server schema (`server/src/agent_control_server/models.py`) reveals composite
   foreign keys with an explicit comment. **Third time in this study that checking
   the schema overturned an inference from an API surface** — the pattern is now
   reliable enough to be a rule.
3. **Server-side behaviour needs Docker.** Not a fault, and the compose path is
   unusually good (a single curl, no clone), but it meant I read the engine rather
   than exercised it end to end.
4. **`Policy` and `Control` are both first-class and the distinction took reading to
   pin down** — `Policy` groups `Control`s via an association table, and bindings
   attach either to targets. The README does not draw the layering.

## What was genuinely good

1. **`observe` as a canonical action rather than a flag.** Putting shadow mode in the
   same enum as `deny` means every code path that handles a decision must handle it,
   and it cannot be forgotten. A boolean `enforce=false` would have been the easy
   version and would have rotted.
2. **Steering guidance as procedures.** The example messages tell the agent *the
   exact steps and the exact retry parameters*. That is written by someone who
   thought about the LLM as the consumer of an error, which almost nobody does.
3. **Structural enforcement of steer completeness.** A composite steer control
   without `steering_context` fails validation. The feature cannot be half-adopted.
4. **`validate_action` versus `normalize_action`, with docstrings explaining which
   to use where.** Strict at the API boundary, lenient on internal reads. That is the
   correct asymmetry for evolving a vocabulary, and it is documented rather than
   inferred.
5. **A README that names its own unsafe default**: "This starts server without API
   keys configured which is dangerous for any real world usage."
6. **Separate agent and admin API keys.** The governed cannot edit the governor.
   Obvious once seen, and unique in the study.
7. **A comment that states an invariant**: "Composite FKs enforce same-namespace
   references on both sides." One line that told me the tenancy guarantee.
8. **Deployable from a curl'd compose file with no repo clone.** The lowest-friction
   evaluation path of any server-based project here.

## Answers to R1–R7

- **R1 clone to running:** SDK in ~40s; the server is one `docker compose up` from a
  remote compose file, with no clone required.
- **R2 concepts before hello world:** four — control, condition, action, binding. The
  quickstart is four steps.
- **R3 local dev loop:** strong. `docker-compose.dev.yml`, a `Makefile`, `TESTING.md`,
  and the whole control plane runs locally.
- **R4 debugging:** strong, and distinctive — a dashboard plus queryable decision
  events plus **observe mode**, so you can watch what a control *would* do before
  enforcing it. That is a debugging affordance no other project offers.
- **R5 unit testing:** 115 engine tests plus per-migration test suites plus codecov —
  once you know about `pytest-asyncio`.
- **R6 deployment:** Docker Compose with env-var configuration and Podman notes.
- **R7 CLI ergonomics:** no CLI; management is API, SDK, or UI.

## Lessons for our own DX

**Put the safe-but-boring mode in the enum, not behind a flag.** `observe` sits
beside `deny` and `steer` as a first-class decision, so every handler must deal with
it and the shadow path stays alive. Had it been `enforce: bool`, it would have been
special-cased once and quietly broken later. Anything we want people to actually use
in production — dry-run, shadow, audit-only — belongs in the primary vocabulary.

**Write errors for the LLM that will read them.** The steering examples name the
parameter to set on retry (`verified_2fa=True`). Our policy denials, capability
rejections and pin mismatches are all read by an agent before a human sees them, and
an error that says what to do next is worth more than one that says what went wrong.

**Read the schema, not the API models.** Three times now an inference drawn from
response types was contradicted by the table definitions — twice in my favour
(Agent Control's FKs, ADK's composite PK) and once against. For any claim about
tenancy, uniqueness, or referential integrity, the migration or table definition is
the only evidence that counts.
