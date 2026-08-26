# DX log — Omnigent

Timeboxed hands-on, 2026-08-26. Installed from PyPI and exercised the capability
model and policy constants live; did not run a full session (needs a vendor
harness CLI and credentials).

- `pip install omnigent` to working `omni --version`: **~90 seconds, clean first try**
- No system dependencies, no compiler step, no database to stand up

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | Cloned; found `designs/` with 19 documents | Read design docs first, per plan. `harness-plugin-interface.md` and `harness-capabilities-bench-seam.md` were exactly the ADR-0004 / ADR-0012 tests |
| 0:12 | Read the capability bench seam doc | Found the declare-then-reconcile loop, DRIFT semantics, and an explicit confidence caveat |
| 0:25 | Read `harness_capabilities.py` | 16 axes; `None` = "makes no claim", reported UNKNOWN. Same discipline this study runs on |
| 0:35 | `pip install omnigent` in a throwaway venv | 0.11.0, worked first try |
| 0:38 | Queried `harness_capabilities()` live | 26 harnesses — **and all four optional axes `None` for every one of them** |
| 0:45 | Read `policies/types.py` | `FAIL_CLOSED_PHASES` with per-phase reasoning; sharper than the ADR-0012 amendment I wrote this morning |
| 0:55 | Read `cost.py` | First real cost control in the study, and it documents its own overshoot limit |
| 1:05 | Grepped for tenancy | `workspace_id` in every composite PK, bound by `ContextVar` |
| 1:15 | Read `SANDBOX_CREDENTIAL_PROXY.md` | Best secret-handling design in the study |
| 1:25 | Grepped for a version pin on `Conversation` | **Nothing.** The ADR-0011 challenge |
| 1:35 | Read the scheduler | In-process, no cross-replica claim — answered my own open question |

## Friction points

1. **Enormous surface.** 111MB, 72 API paths, 26 harnesses, desktop app, web UI,
   Slack bot. Finding the architecture meant ignoring most of the repo. `designs/`
   was the only reason this was tractable in a day — without it I would have been
   grepping blind.
2. **Flat module namespace.** `omnigent/` has ~150 top-level modules, many named
   `<vendor>_native_<thing>.py` (nine variants for Claude alone). Real structure
   exists in the subpackages (`policies/`, `stores/`, `entities/`, `runner/`), but
   the flat files dominate the directory listing and obscure it.
3. **Its own docs call it "heavily vibe-coded"** and say it "lacks a clear mental
   map" (`designs/OBSERVABILITY.md`). Refreshingly honest, and accurate: the
   design quality in `policies/` and `entities/` is high, while the harness
   adapters are sprawling.
4. **Capability axes designed but unpopulated.** Discovering that all 26 harnesses
   declare `None` for all four optional axes required running the code — the docs
   describe the tri-state as if it were in use.
5. **Status lines in design docs need verification.** `OBSERVABILITY.md` is marked
   "Proposed" but parts are wired; `SANDBOX_CREDENTIAL_PROXY.md` is marked
   IMPLEMENTED and is. I checked each against the code rather than trusting either.

## What was genuinely good

1. **`designs/` as a first-class directory.** Nineteen documents that state intent,
   status, and open seams. The single biggest DX asset in this study so far — I
   understood Omnigent's architecture faster than Letta's despite it being far
   larger.
2. **A design doc that audits its own dead code.** `OBSERVABILITY.md` lists a
   dead propagation helper, a never-wired instrumentor, and a disabled one.
   Documents that admit their own gaps are worth more than documents that don't.
3. **Reasoning in comments, not just description.** `FAIL_CLOSED_PHASES` explains
   why each phase is in or out. `cost.py` explains why the hard cap is a downgrade
   gate rather than a stop. The timeout ladder explains why budgets must be
   strictly decreasing. This is the best-commented codebase in the study.
4. **A conformance bench for adapters.** `tests/harness_bench/` live-probes each
   harness and reconciles against declarations. No other project verifies its
   adapters' claims.
5. **Injectable timing seams.** The scheduler takes `now` / `schedule_call` /
   `cancel_call` so tests drive a fake clock and fire timers manually. Testing an
   rrule scheduler is otherwise miserable.
6. **Bug numbers in comments.** The `SQLITE_BUSY_SNAPSHOT` fix cites bug #9 and
   explains the race it closed.
7. **Clean install.** One `pip install`, no compiler, SQLite by default, a managed
   local server spawned by `omnigent run`.

## Answers to R1–R7

- **R1 install to running:** ~90s, clean. `omnigent run` spawns a managed local
  server so there is nothing to provision.
- **R2 concepts before hello world:** few for a basic run (session, harness,
  prompt); the largest full model in the study (workspace, project, agent, policy,
  host, runner, scheduled task, permission, comment, capability).
- **R3 local dev loop:** strong. SQLite, managed local server, REPL, TUI, and an
  explicit single-user marker that deployed servers never set.
- **R4 debugging:** strong. Searchable transcript, persisted routing and policy
  decisions, `deciding_policies` naming what drove a verdict, status edges with
  `blocked_on` reasons, `cli_diagnostics`, OTel with a local Jaeger backend in the
  design.
- **R5 unit testing:** strongest in the study. The harness conformance bench is a
  category of test no other project has, plus injectable clocks.
- **R6 deployment:** Railway, Render, Docker, Kubernetes, packaged macOS app.
- **R7 CLI ergonomics:** rich — `run`, `resume` with a cross-agent picker,
  `server`, `sandbox`, `auth`, `diagnostics`, and a documented CLI contract.

## Lessons for our own DX

**Ship a `designs/` directory and let documents admit their own gaps.** Omnigent's
is why a 111MB alpha was readable in a day. The specific practice to copy: a
status line at the top (`IMPLEMENTED` / `Proposed`), the file paths that implement
it, and an explicit list of what is *not* done. I will verify status lines against
code regardless, but they make that verification targeted instead of exploratory.

**Explain why in the code, not just what.** The three highest-value things I found
— per-phase fail-closed, the timeout ladder, the cost gate's downgrade behaviour —
were all discovered by reading comments that explained a *tradeoff*. A comment
that says what the code does is redundant with the code; a comment that says why
the alternative was rejected is irreplaceable.

**Build the conformance bench early.** Omnigent's capability table is trustworthy
in proportion to how much of it the bench has verified, and it knows that 4 of 26
is not enough. If we declare capabilities without a bench, we will have a
documentation artifact rather than a contract.
