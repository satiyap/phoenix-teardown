# DX log — Letta (letta-code)

Timeboxed hands-on, 2026-08-26. CLI installed and interrogated; no agent run
(needs provider credentials).

- Got to a usable CLI: **yes**, under 5 minutes via npm
- Got to a running agent: not attempted (requires provider auth)

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | Cloned `letta-ai/letta-code` | TypeScript, ~100 files at `src/` root plus 27 subdirectories |
| 0:05 | Scanned directory names | `permissions/`, `sandbox/`, `channels/`, `cron/`, `queue/`, `reminders/` — far broader than the "memory server" I expected |
| 0:10 | Read `memory-confinement.ts` | Fail-closed kernel confinement; the session's best single finding |
| 0:20 | Read `cross-agent-guard.ts` header | Documents an abandoned design and why. Rare and valuable |
| 0:30 | `npm install @letta-ai/letta-code` | Clean, 0.31.0 |
| 0:35 | `letta --help`, `agents --help`, `memory --help` | Confirmed agents are first-class registry resources; memory is git-backed |
| 0:45 | Read `cron-file.ts` | `SchedulerOwner` with `boot_id` + `process_start_ticks`; nine named run reasons |

## Friction points

1. **`DEFAULT_PERMISSION_MODE = "unrestricted"`.** Reasonable for a local CLI
   where the user is the operator, but it means the safe configuration is
   opt-in. Combined with shell confinement also being opt-in
   (`LETTA_FS_SANDBOX=1`), the shipped default is the least confined mode.
2. **Two storage locations for memory** depending on backend
   (`~/.letta/agents/<id>/` for API, `<storage>/memfs/<id>/` for local). Correct
   but something to hold in your head when reasoning about paths.
3. **The repo move is not signposted from the old path's clone.** Cloning
   `letta-ai/letta` gives you a landing page and an archive branch; nothing warns
   you that the interesting code is elsewhere until you read the README.
4. **`src/` has ~100 files at its root** alongside 27 directories, so the top
   level is hard to skim. Test files and implementation are interleaved.

## What was genuinely good

1. **`letta memory tokens` with an explicit policy boundary.** It reports the
   estimated token size of `system/` and says outright: "Policy (whether a size is
   concerning) is up to the caller." A tool that measures and declines to
   moralise is the right split of responsibility.
2. **Memory as human-readable markdown in git.** You can `cd` into an agent's
   memory and read it. `letta memory diff` shows what the agent changed this
   session. That is a debugging and trust affordance nothing else in the study
   offers.
3. **The abandoned-design comment.** Explaining that shell-command parsing was
   removed because it was "bypassable by symlinks, command substitution,
   globbing, and subprocesses" saves the next person from rebuilding it.
4. **Test names that document the hardening.** `headless-interrupt-latch`,
   `headless-bootstrap-pending-approval`, `local-compaction-parity` —
   the suite reads as a list of failure modes someone actually hit.
5. **JSON-only machine subcommands.** `letta agents list` and `letta memory
   status` emit JSON, making the CLI scriptable without a separate SDK.
6. **`letta teleport`.** Moving a live conversation between environments is a
   capability I did not expect to find anywhere in this study.

## Answers to R1–R7

- **R1 clone to running CLI:** under 5 minutes. Full agent run needs provider auth.
- **R2 concepts before hello world:** two — agent and conversation. Bare `letta`
  resumes the last conversation for the current project.
- **R3 local dev loop:** strong. Dev backend with smoke tests, fake headless
  backend, Nix flake, TUI/headless parity tests.
- **R4 debugging:** best in study. `memory status/diff/tokens`, `agents config`,
  `--info`, permission traces, web memory viewer.
- **R5 unit testing:** extensive, including source-level wiring assertions (tests
  that read `headless.ts` and assert it calls shared helpers rather than inlining
  logic) and engine parity tests.
- **R6 deployment:** npm global, desktop app for three platforms,
  chat.letta.com, `letta server` self-hosted, Nix flake, Cloud.
- **R7 CLI ergonomics:** closest to the ideal journey of anything so far —
  `letta --new-agent --base-tools memory,web_search`, `letta agents create`,
  `letta install`, `letta backend`, `letta connect`.

## Lesson for our own DX

**Make the agent's memory inspectable with ordinary tools.** Letta's decision to
store memory as markdown in git means `git log`, `git diff` and any text editor
are debugging tools. Compare with an opaque vector index, where "what does the
agent know?" requires bespoke tooling to answer.

Second: **measure, then leave policy to the caller.** `letta memory tokens`
reports cost and explicitly refuses to judge it. Our platform should expose
context cost, budget consumption and policy decisions as data, and let the
operator set the thresholds.
