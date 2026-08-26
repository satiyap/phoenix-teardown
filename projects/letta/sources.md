# Sources — Letta (letta-code)

## Repository

**Repo moved** (OQ-004). `letta-ai/letta` is now a landing page; the Python V1
memory server is retired to an `archive` branch. Active source read here:

- repo: https://github.com/letta-ai/letta-code
- commit: `852ca244b00253e7871e1e878bb8272d4b4a696a`
- commit date: 2026-08-25
- cloned on: 2026-08-26 (`--depth 1` to `~/dev/_teardown_src/letta`)
- installed for testing: `@letta-ai/letta-code` 0.31.0 via npm

Citations below are against `letta-code` at that commit. Nothing here relies on
the retired `letta` archive branch.

## Key source files

| Path | Why it matters |
|---|---|
| `src/permissions/memory-paths.ts:115-129` | `deriveAgentId` — identity resolution precedence: explicit → session context → `AGENT_ID`/`LETTA_AGENT_ID` |
| `src/permissions/cross-agent-guard.ts:1-30` | The architecture statement: guard runs at decision step 0, deny is unbypassable, "the guard is the in-process safety net; the kernel is the enforcement boundary". Also documents the **abandoned** shell-parsing design and why |
| `src/permissions/cross-agent-guard.ts:75-110` | `resolveAllowedAgents` → `{self, parent}`; enumeration-attempt sentinel for the bare agents-tree root |
| `src/permissions/types.ts:9-57` | `PermissionDecision`, `PermissionScope`, `PermissionEngine v1\|v2`, `PermissionTraceEvent`, `PermissionShadowComparison`, `PermissionCheckTrace` |
| `src/permissions/mode.ts:3-30` | `PermissionMode` union and `DEFAULT_PERMISSION_MODE = "unrestricted"` |
| `src/memory-confinement.ts:14-21` | Fail-closed memory confinement: "cannot read or write other agents' memory. Throws when no supported kernel sandbox is available rather than silently running with a weaker policy." |
| `src/sandbox/availability.ts:7-45` | `SandboxAvailability { backend \| null, bwrapPath?, reason }` with a real user-namespace mount probe. Best capability signalling in the study |
| `src/sandbox/bwrap.ts`, `src/sandbox/seatbelt.ts`, `src/sandbox/policy.ts`, `wrap.ts` | Kernel-level sandbox backends |
| `src/tools/descriptions/Memory.md` | The agent-facing memory contract: `$MEMORY_DIR`, auto-commit, `system/` always in prompt, `[[path]]` cross-refs, required `reason` argument |
| `src/agent/memory-constants.ts` | `READ_ONLY_BLOCK_LABELS = ["memory_filesystem"]` |
| `src/cron/cron-file.ts:26-80` | `CronTaskStatus`, `CronRunOutcome`, nine `CronRunReason` values, `SchedulerOwner` (pid + token + `process_start_ticks` + `boot_id`), `CronTask` |
| `src/cron/cron-file.ts:340` | `LockHandle` |
| `src/channels/access-control.ts:23-95` | `ChannelAccessScope`, allowed/admin users, `ChannelSenderAccessDecision = allow\|deny\|pair` |
| `src/channels/access-control.ts:241-281` | `ChannelCommandGate`, `floorOnlyChannelCommandGate()` |
| `src/channels/types.ts:81-125` | Per-channel default permission mode, `DiscordChannelMode = open\|mention-only`, thread context, reactions |
| `src/channels/pending-control-requests.ts` | Durable approvals persisted to disk |
| `src/agent/subagents/` | `manager.ts`, `subagent-launcher.ts`, `context-budget.ts`, `sandbox.ts` |
| `src/queue/turn-queue-runtime.ts` | Turn queue, with TUI/headless parity tests |
| `src/backend/backend-mode.ts` | `local \| api \| dev` backends |

## Test names as evidence

Several durability claims are supported by the existence of dedicated hardening
tests. Worth recording because the test names are themselves a design statement.

| Test | What it implies |
|---|---|
| `src/headless-approval-recovery.test.ts` | Approval state recovers after failure; asserts shared `extractConflictDetail` is used rather than inline parsing |
| `src/headless-bootstrap-pending-approval.test.ts` | Startup handles a pending approval blocking new messages |
| `src/headless-interrupt-latch.test.ts` | Interrupt is latched, not lost |
| `src/headless-interrupt-recovery.test.ts` | Interrupt state recovers |
| `src/headless-backend-lifecycle.test.ts` | Backend lifecycle transitions |
| `src/backend/local-compaction-parity.test.ts` | Compaction behaves identically local vs API |
| `src/permissions/sandbox-gate.test.ts`, `workspace-sandbox.test.ts` | Sandbox gating |
| `src/agent/memory-worktree.test.ts`, `memory-git.auth.test.ts` | Git-backed memory incl. auth |
| `src/reminders/engine-parity.test.ts` | Reminder engine parity |

## Verification — CLI surface

`@letta-ai/letta-code` 0.31.0 installed and interrogated 2026-08-26.

| Command | Finding |
|---|---|
| `letta --help` | Confirms `--agent <id>`, `--new-agent`, `--base-tools`, `teleport`, `server`, `mods`, `skills`, `install`, `connect`, `backend` |
| `letta agents --help` | `list` with `--name`, `--query` (fuzzy), `--tags` with `--match-all-tags`, `--include-blocks`, **`--shared`**, `--limit`; plus `create` and `config` |
| `letta memory --help` | `status`, `diff`, `backup`, `backups`, `restore`, `export`, `pull`, `tokens` (with `--top N`). States plainly: "Memory is git-backed. Use git commands for commit/push." `tokens` reports estimated `system/` size and notes "Policy (whether a size is concerning) is up to the caller." |

## Negative findings

| Searched for | Result |
|---|---|
| `opentelemetry` in `src/` and `package.json` | **Nothing.** `src/telemetry/` is error reporting + product analytics |
| MCP / A2A / ACP | Nothing in the read tree |
| CPU / memory / pid quotas in `src/sandbox/` | Nothing; filesystem confinement only |
| tenant / organization resource | Nothing; permission *scopes* are `project\|local\|user` |
| agent versioning / revocation | Nothing |

## Documentation

| URL | Read on | Notes |
|---|---|---|
| https://docs.letta.com | 2026-08-26 | Letta Cloud framing, channels, agent SDK |
| `letta-ai/letta` README @ archive-era | 2026-08-26 | Confirms the repo move and the retirement of the V1 server |

Letta Cloud (hosted memory, identity, cross-device continuity) is closed and is
class B evidence at best.
