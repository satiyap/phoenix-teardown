# Teardown — Letta (letta-code)

| | |
|---|---|
| Repo | https://github.com/letta-ai/letta-code |
| Commit read | `852ca244b00253e7871e1e878bb8272d4b4a696a` (2026-08-25) |
| Version tested | `@letta-ai/letta-code` 0.31.0 |
| Docs | https://docs.letta.com |
| License | Apache-2.0 |
| Read on | 2026-08-26 |
| Evidence class | A (harness + App Server); B for Letta Cloud |
| Depth | deep |
| Runtime class | `durable_actor` (agent identity is a security boundary) |

**Repo moved since the shortlist was drawn** (recorded as OQ-004).
`letta-ai/letta` is now a landing page; the Python V1 memory server is retired to
an `archive` branch. Active source is `letta-ai/letta-code`: TypeScript, and it
contains the harness, terminal UI, App Server, channels, permissions, sandbox and
scheduler.

**OQ-004 is resolved: the memory architecture is fully inspectable**, and it is
not what the old Python server did. Memory is a git-backed markdown filesystem
with kernel-enforced per-agent isolation. That is a better answer than the V1
block store would have given.

---

## 1. What problem it solves

An agent that forgets everything between sns cannot accumulate expertise.
Letta gives an agent durable identity plus a persistent, editable memory
filesystem that survives conversations, machines and interfaces — terminal,
desktop, browser, Slack, Discord, Telegram. The agent curates its own memory as
files, and those files are versioned in git.

## 2. Core architectural thesis

**The agent is the durable unit, and its memory is a version-controlled
filesystem it edits with tools.** Not a vector index, not an opaque block store —
markdown files in a git repository, where `system/` files are always resident in
the system prompt and everything else carries only metadata until explicitly
read.

The second, less obvious bet: **agent identity is a security boundary enforced by
the kernel, not by convention.** `AGENT_ID` determines which memory paths a
process may touch, and the enforcement point is a filesystem sandbox
(`bwrap` on Linux, Seatbelt on macOS), with an in-process guard as a safety net.

## 3. Resource / object model

```text
Agent                          (agent-<id>; durable, addressable, shareable)
 ├── AGENT_ID                  (identity; propagated into processes as env)
 ├── Memory                    (git repo at ~/.letta/agents/<id>/ or <storage>/memfs/<id>/)
 │    ├── system/**            always in system prompt
 │    └── **                   metadata only until read; [[path]] cross-refs
 ├── Blocks                    (agent.blocks, per `letta agents list --include-blocks`)
 ├── Tags                      (filterable, ANY or ALL matching)
 ├── Conversation[]            (default | new | specific id)
 │    ├── Turn queue
 │    └── PendingControlRequest    (durable approvals, persisted to disk)
 ├── Subagent[]                (own process; LETTA_PARENT_AGENT_ID scope)
 ├── CronTask[]                (scheduled prompts, lease-owned)
 ├── Skills / Mods             (installable packages)
 └── Permissions               (rules × scope × mode)

Channel                        (Slack | Discord | Telegram | public)
 ├── AccessControl             (allowed users, admin users, scope dm|group)
 ├── ThreadContext
 └── CommandGate

Environment                    (remote; `letta teleport` moves conversations)
Backend                        (local | api | dev)
```

Root resource is the **Agent**, and unlike the two previous teardowns that is not
a euphemism: agents are listable, searchable by name/tag, shareable
(`--shared`), and carry their own memory and configuration.

## 4. Runtime model

Letta launches agent processes and subagent processes, each carrying `AGENT_ID`
in its environment. Subagents run as separate processes with the
`memory-subagent` profile confined as whole processes by default
(`src/permissions/cross-agent-guard.ts:16 @ 852ca24`).

Execution substrate is a local process wrapped in a kernel filesystem sandbox,
or a remote environment. Backends are `local | api | dev`
(`src/backend/backend-mode.ts`), and `letta teleport` moves a conversation
between environments — a capability no other project in the study has.

## 5. Execution lifecycle

Two state machines worth recording.

**Cron task** (`src/cron/cron-file.ts:26-43 @ 852ca24`):

```text
status:  active → fired
              ↘ paused
              ↘ missed
              ↘ cancelled     (reason: conversation_not_found | expired)

run outcome:  queued | missed | failed | skipped
run reason:   scheduled_time_matched | one_off_due | scheduler_inactive
              started_too_late | queue_full | runtime_unavailable
              task_cancelled | invalid_cron | scheduler_error
```

Nine distinct run reasons is the most careful failure-mode enumeration in the
study. `started_too_late`, `queue_full` and `runtime_unavailable` are exactly the
conditions that get silently swallowed elsewhere.

**Approvals** are durable: `PendingControlRequest` events persist to disk
(`src/channels/pending-control-requests.ts @ 852ca24`) and there are dedicated
tests for recovery — `headless-approval-recovery.test.ts`,
`headless-bootstrap-pending-approval.test.ts`,
`headless-interrupt-recovery.test.ts`, `headless-interrupt-latch.test.ts`.
Test names as evidence: someone deliberately hardened restart-with-pending-approval.

## 6. Durability model

Memory durability is **git**. `letta memory status | diff | backup | backups |
restore | export | pull` are first-class commands, and the CLI states plainly:
"Memory is git-backed. Use git commands for commit/push." The `memory` tool
"automatically commits changes" and "the harness pushes clean committed memory
changes after the turn for remote MemFS agents"
(`src/tools/descriptions/Memory.md @ 852ca24`).

Consequences worth noting: every memory mutation has an author, a timestamp, a
diff and a revert path, for free. Provenance and audit come from the storage
substrate rather than from bespoke fields. No other project in this study gets
memory provenance this cheaply.

**Scheduler durability** uses lease-based ownership with genuine care
(`cron-file.ts:45-52`):

```typescript
export interface SchedulerOwner {
  pid: number;
  token: string;
  started_at: string;
  process_start_ticks?: string | null;
  boot_id?: string | null;
}
```

`process_start_ticks` and `boot_id` exist to defeat PID reuse and to detect that
the host rebooted. That is the difference between a lock that works and a lock
that works until a machine restarts. There is also an explicit `LockHandle`
(`:340`).

What is missing: no declared persistence-timing contract for conversation state
(no `sync|async|exit` equivalent), and no conformance suite for storage.

## 7. Agent identity and lifecycle

**The strongest agent-identity evidence in the study, and it changes the ADR-0001
picture.**

- Agents are addressable: `letta --agent <id>`, `LETTA_AGENT_ID`, `AGENT_ID`.
- Identity resolution has a documented precedence: explicit argument → session
  context → `AGENT_ID` / `LETTA_AGENT_ID` env
  (`src/permissions/memory-paths.ts:115-129 @ 852ca24`).
- Agents are listable and discoverable: `letta agents list` with exact name,
  fuzzy `--query`, `--tags` with ANY/ALL matching, `--include-blocks`.
- Agents are **shareable**: `letta agents list --shared` lists "agents shared
  with the current user."
- Identity is a **security boundary**: `AGENT_ID` determines which memory tree a
  process may read or write.
- Subagents carry `LETTA_PARENT_AGENT_ID`, and the allowed set is exactly
  `{self, parent}` (`cross-agent-guard.ts:75-88`).

No agent versioning, and no revocation lifecycle. But identity here does real
work rather than being a label.

## 8. Multi-agent communication

Subagents are separate processes with their own memory confinement and a context
budget (`src/agent/subagents/context-budget.ts`). Communication is
parent↔subagent via streams, not a mailbox — no durable inter-agent messaging, no
channels between agents, no correlation IDs.

Channels are for **humans**, not agents. Which is the right call, but it means F
section is thin: delegation happens by spawning, not by message.

## 9. Human interaction model

**Best in study, and it partly resolves OQ-003.** Letta ships real multi-party
collaboration surfaces that GroupMind was supposed to supply.

Channels for Slack, Discord and Telegram (`src/channels/ @ 852ca24`) with:

- `ChannelAccessScope = "dm" | "group"` and per-channel allowed/admin user lists
  (`access-control.ts:23-72`)
- `ChannelSenderAccessDecision = "allow" | "deny" | "pair"` — `pair` is a
  pending-authorisation state, so an unknown sender can be linked rather than
  simply refused (`:95`)
- Per-channel default permission mode (`types.ts:81`), so a Slack channel can be
  more restricted than the terminal
- `DiscordChannelMode = "open" | "mention-only"` — mentions as an addressing
  mechanism (`:92`)
- Thread context entries, reaction notifications, attachments
- A command gate with a `floorOnlyChannelCommandGate()` — a minimum floor of
  allowed commands regardless of configuration
- Durable pending control requests, so an approval asked in Slack survives a
  restart

`letta teleport` moves a live conversation between environments, and sessions
follow the user across terminal, desktop, browser and phone.

## 10. Context and memory

The centre of the project, and the richest H-section evidence available.

| Concept | Mechanism | Scope |
|---|---|---|
| Always-resident context | `system/**` memory files | agent |
| Referenced memory | non-`system` files, metadata only until read | agent |
| Read-only projection | `memory_filesystem` block (`READ_ONLY_BLOCK_LABELS`) | agent |
| Conversation state | turn queue, compaction | conversation |
| Skills / Mods | installable packages | project or user |
| Shared agents | `agents list --shared` | user |

The `memory` tool (`src/tools/descriptions/Memory.md @ 852ca24`) supports
`str_replace`, `insert`, `delete`, `rename`, `update_description`, `create`, and
**requires a `reason` argument on every call**. Provenance is enforced by the
tool signature, not left to convention.

Two design details worth stealing:

1. **The system/ vs referenced split is a context-budget mechanism, not a
   taxonomy.** Files in `system/` cost context permanently; everything else costs
   a metadata line plus an optional read. `letta memory tokens` reports the
   estimated token size of `system/` and explicitly leaves policy to the caller:
   "Policy (whether a size is concerning) is up to the caller."
2. **`[[path]]` cross-references** with tool guidance to keep them consistent, so
   discoverability is maintained by the agent as it edits.

**Memory permissions are real and kernel-enforced** — the first `first_class`
answer to H4 in this study. `src/memory-confinement.ts @ 852ca24`:

> "The process can read the host broadly, write harness state and its own memory,
> and **cannot read or write other agents' memory**. Throws when no supported
> kernel sandbox is available rather than silently running with a weaker policy."

Fail-closed, and it refuses to run degraded.

## 11. Tools and capabilities

Tools have schemas and descriptions as separate artifacts
(`src/tools/schemas/*.json`, `src/tools/descriptions/*.md`). Skills and mods are
installable packages (`letta install`, `letta skills`), and mods have a
`capabilities.ts`. Tool names are canonicalised across harnesses —
`canonicalToolName` maps "Codex/Gemini aliases" onto one vocabulary
(`src/permissions/canonical.ts`), which is the practical cost of adapter
neutrality showing up in the policy layer.

## 12. Security and IAM

The most developed security model in the study so far.

**A real policy engine** (`src/permissions/types.ts @ 852ca24`):

```text
PermissionDecision = "allow" | "deny" | "ask" | "alwaysAsk"
PermissionScope    = "project" | "local" | "user"
PermissionMode     = "unrestricted" | "standard" | "acceptEdits" | "strict"
PermissionEngine   = "v1" | "v2"
```

Plus `PermissionCheckTrace`, `PermissionTraceEvent` and
`PermissionShadowComparison` — the v2 engine can run in shadow mode against v1
and compare decisions before cutover. That is how you migrate a policy engine
without breaking users, and it is worth copying directly.

**Layered enforcement with an unbypassable floor.** The cross-agent guard "runs
BEFORE any other permission logic (decision step 0 in checkPermission). Its deny
is **unbypassable by modes and permission rules**"
(`cross-agent-guard.ts:20-22`). A hard floor beneath the configurable layer.

**A documented abandoned design**, which is unusually honest and directly useful:

> "Spawned shell commands are intentionally no longer analyzed here (the old
> token/raw-command scanner is gone — it was bypassable by symlinks, command
> substitution, globbing, and subprocesses). When the opt-in cross-agent shell
> sandbox is enabled, the kernel confines spawned shells instead."
> — `cross-agent-guard.ts:11-19`

The architectural conclusion is stated plainly: "The guard is the in-process
safety net; **the kernel is the enforcement boundary**." Anyone planning to
police agent shell commands by parsing them should read that paragraph first.

**Weaknesses.** `DEFAULT_PERMISSION_MODE = "unrestricted"`
(`src/permissions/mode.ts:11`) — a developer-tool default that would be wrong for
a platform. The cross-agent shell sandbox is opt-in (`LETTA_FS_SANDBOX=1`); by
default "agent shells run unconfined." No tenancy, no RBAC, no audit log
distinct from git history.

**S1 is partially answered**, which is a first. A subagent's authority is exactly
`{self, parent}` for memory, enforced by kernel confinement. That is a real
delegation scope — narrower than the parent, explicitly derived from it, and not
bypassable. It does not cover tool credentials or a delegation token, so it is
not a complete answer, but it is the only project so far where the question can
be posed at all.

## 13. Sandboxing

Kernel-level, OS-native, and a different bet from OpenHands' containers.

`src/sandbox/`: `bwrap` (Linux bubblewrap, user namespaces), `seatbelt` (macOS
`sandbox-exec`), with `policy.ts`, `wrap.ts` and `availability.ts`.

**`availability.ts` is the best capability-signalling design in the study**, and
it directly vindicates ADR-0012:

```typescript
export interface SandboxAvailability {
  backend: SandboxBackend | null;      // null when none available
  bwrapPath?: string;
  reason: string;                      // human-readable, esp. for the null case
}
```

Detection "prob[es] for real (Seatbelt: binary presence; bwrap: an actual
user-namespace mount probe)." Not a version check, not a `try/except` — an actual
mount probe. The result is cached "for the process since it cannot change
mid-run," and the null case carries an explanation.

Compare the three projects on the same problem:

| Project | Optional-capability signalling |
|---|---|
| LangGraph | Declared enum, detected by method override, conformance-tested |
| OpenHands | `NotImplementedError` from base; no query; local `pause()` silently no-ops |
| **Letta** | **Probed for real, returns `backend \| null` plus a `reason`, fails closed** |

Letta's is best because it distinguishes unavailable from unknown *and* explains
which, and because the dependent code refuses to run rather than degrade.

Weaknesses: no CPU/memory/pid quotas, no snapshot/restore, and no network egress
policy. Filesystem confinement is the whole story.

## 14. Orchestration

Cron with timezone-aware schedules (IANA), one-off and recurring tasks, and a
`conversation_id` target of `default | new | <specific>`. A turn queue with
parity tests between the TUI and headless listener. Subagent spawning with
context budgets. Reminders with an engine plus `memory-git-sync`.

No DAG, no graph, no compensation. Orchestration is scheduling plus delegation.

## 15. Observability

No OpenTelemetry — **three for three across the deep teardowns**.
`src/telemetry/` is error reporting, fatal error handling, batched flushing and
input telemetry. Product analytics, not distributed tracing.

Notable partial: `letta memory tokens` gives per-agent context cost with a
`--top N` breakdown, and permission checks emit `PermissionTraceEvent`. So there
is good introspection into the two things that actually cost money and create
risk, without a tracing backend.

## 16. Multi-tenancy

Agent sharing (`--shared`) implies a user model, and channels have per-channel
user allowlists and admin lists. But there is no organization, project or tenant
resource in the OSS tree; Letta Cloud provides "agent memory, identity, and
conversations available across computers" and is closed (class B).

## 17. Protocols and APIs

CLI is the primary surface and is unusually complete: `letta agents`, `memory`,
`messages`, `environments`, `teleport`, `sandbox`, `server`, `connect`,
`backend`, `install`, `skills`, `mods`. JSON-only output on the machine-facing
subcommands, which makes the CLI scriptable as an API.

An App Server (`letta server`) serves desktop, web and channels. Websocket
listener with a command surface (`src/websocket/listener/commands/`) including
`memory` and `memory-command-sync`.

Standards: no MCP in the tree I read, no A2A, no ACP, no OTel. Letta is its own
harness rather than a host for others — the inverse of OpenHands.

## 18. Storage

- Memory: **git repositories**, one per agent, under `~/.letta/agents/<id>/` (API
  backend) or `<storage>/memfs/<id>/` (local backend).
- Pending approvals: JSON file on disk.
- Cron tasks: file-based with lease ownership.
- Conversations: backend-dependent (local vs API vs Cloud).

Authoritative state for memory is the git repo, which is an interesting choice:
the audit log *is* the storage layer.

## 19. Deployment architecture

npm global CLI (`@letta-ai/letta-code`), desktop app for macOS/Windows/Linux,
`chat.letta.com`, `letta server` for self-hosted App Server and channels, Nix
flake, and Letta Cloud. Remote environments with teleport between them.

## 20. OSS / license / commercial model

Apache-2.0. Letta Cloud (hosted memory, identity, cross-device continuity) is the
commercial layer. No copyleft, no SaaS restriction.

Verdict: **REFERENCE_ONLY** on architectural grounds — TypeScript, and the design
is tightly coupled to a git-backed memory filesystem and OS-native sandboxes. The
*ideas* are the most valuable in the study; the code is not what we would embed.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | **inferable (partial)** | Subagent authority is exactly `{self, parent}` for memory, kernel-enforced and unbypassable. First project where the question is answerable. Does not cover tool credentials or a delegation token. |
| S2 Torn side effect | undefined | Memory commits are atomic per git operation, but no idempotency key on tool calls. |
| S3 Upgrade mid-flight | undefined | `system-prompt-versioning.test.ts` exists, but no version pin on a suspended conversation. |
| S4 Concurrent memory write | **inferable** | Memory is git, so concurrent writes surface as a git conflict rather than silent last-write-wins. `extractConflictDetail` and conflict routing appear in the headless recovery paths. Better than any other project here. |
| S5 Cancellation tree | **inferable** | `headless-interrupt-latch.test.ts` and `headless-interrupt-recovery.test.ts` show interrupt is latched and recoverable. No documented propagation to subagent processes. |
| S6 Silent context loss | **inferable** | Compaction exists, and `letta memory tokens` makes context cost measurable, but nothing detects a specific dropped constraint. `system/` files are permanently resident, which structurally protects the constraints placed there. |
| S7 Poison message | **inferable** | Cron enumerates `queue_full`, `started_too_late`, `runtime_unavailable`, `scheduler_error` as distinct outcomes, and tasks can reach `missed`. No DLQ, but failures are named rather than swallowed. |
| S8 Tenant leak | **inferable** | No tenant, but cross-agent memory access is hard-denied at decision step 0 and kernel-confined. The enumeration case (bare agents-tree root) is explicitly handled with a sentinel. |
| S9 Runaway spend | undefined | Context budgets for subagents and token reporting, but no cost ceiling. |
| S10 Zombie sandbox | **inferable** | `SchedulerOwner` with `pid` + `token` + `process_start_ticks` + `boot_id` detects a stale owner across PID reuse and reboot. Best liveness detection in the study. |

## 22. Strongest ideas

1. **Git-backed memory.** Provenance, audit, diff, revert and conflict detection
   come free from the substrate. `letta memory status/diff/backup/restore/export`
   are thin wrappers over git.
2. **`system/` vs referenced memory as a context-budget mechanism.** Always-resident
   versus metadata-only-until-read is a cost model, not a taxonomy, and
   `memory tokens` measures it while leaving policy to the caller.
3. **A `reason` argument required on every memory mutation.** Provenance enforced
   by tool signature.
4. **Memory permissions enforced by kernel sandbox, fail-closed.** "Cannot read or
   write other agents' memory. Throws when no supported kernel sandbox is
   available rather than silently running with a weaker policy."
5. **`SandboxAvailability { backend | null, reason }` with a real mount probe.**
   The best capability-signalling design seen; distinguishes unavailable from
   unknown and explains which.
6. **An unbypassable policy floor at decision step 0**, beneath the configurable
   modes and rules.
7. **`PermissionShadowComparison`** — run the v2 policy engine in shadow against
   v1 and compare decisions before cutover.
8. **`SchedulerOwner` with `process_start_ticks` and `boot_id`.** Lease ownership
   that survives PID reuse and host reboot.
9. **Nine named cron run reasons.** `started_too_late`, `queue_full`,
   `runtime_unavailable` are the failure modes everyone else swallows.
10. **`ChannelSenderAccessDecision = allow | deny | pair`.** A pending-authorisation
    state for an unknown sender, instead of a binary refusal.
11. **`floorOnlyChannelCommandGate()`** — a guaranteed minimum command set no
    configuration can remove.
12. **A documented abandoned design.** The comment explaining why shell-command
    parsing was removed (symlinks, command substitution, globbing, subprocesses)
    is worth more than most design docs.
13. **`letta teleport`** — moving a live conversation between environments.
14. **JSON-only machine subcommands**, making the CLI a scriptable API.

## 23. Weakest architectural choices

1. **`DEFAULT_PERMISSION_MODE = "unrestricted"`.** Defensible for a local
   developer tool, wrong for a platform, and a trap if the same code is later
   hosted.
2. **Shell confinement is opt-in** (`LETTA_FS_SANDBOX=1`); by default "agent
   shells run unconfined." The kernel is the stated enforcement boundary, and by
   default it is not engaged for shells.
3. **No OTel**, and telemetry is product analytics rather than tracing.
4. **No agent versioning or revocation**, despite strong agent identity.
5. **No resource quotas or cost ceilings.** Filesystem confinement only.
6. **No inter-agent messaging.** Delegation is process spawning; no mailbox, no
   ordering, no correlation.
7. **Git as the memory substrate cuts both ways** — excellent provenance, but
   conflicts become the agent's problem, and repository growth is unbounded.
8. **No tenancy in OSS**; sharing exists without an org model to scope it.

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| Git-backed memory with provenance | REUSE (pattern) | Strongest answer to H4/H5 in the study |
| `system/` vs referenced context budget | ADOPT_AS_STANDARD | Cost model for prompt residency |
| Required `reason` on memory mutation | REUSE (pattern) | Provenance by signature |
| `SandboxAvailability{backend\|null, reason}` | ADOPT_AS_STANDARD | Best capability signalling; ADR-0012 |
| Fail-closed confinement | ADOPT_AS_STANDARD | Refuse to run degraded |
| Unbypassable policy floor (step 0) | REUSE (pattern) | Hard floor beneath configurable policy |
| `PermissionShadowComparison` | REUSE (pattern) | Safe policy-engine migration |
| `SchedulerOwner` lease fields | REUSE (pattern) | Liveness that survives reboot and PID reuse |
| Named cron run reasons | ADOPT_AS_STANDARD | Failure taxonomy for our scheduler |
| `allow \| deny \| pair` access decision | REUSE (pattern) | Pending-authorisation state |
| `allow \| deny \| ask \| alwaysAsk` decisions | ADOPT_AS_STANDARD | Policy decision vocabulary |
| Kernel sandbox backends (bwrap/seatbelt) | INTEGRATE | Provider options alongside containers |
| Default `unrestricted` mode | reject | Wrong default for a platform |
| Channels implementation | INTEGRATE | Pattern for human surfaces; not our code |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | **confirms** | The affirmative evidence the first two teardowns could not supply. Agents are addressable, listable, searchable by tag, shareable, and identity is a *security boundary*: `AGENT_ID` decides which memory tree a process may touch, enforced by kernel confinement. Crucially this is identity doing work that a durable conversation/thread cannot do — which is exactly the revised rationale (delegation, policy, audit) rather than durability. Promote on these grounds. |
| ADR-0002 | confirms | Cron's nine run reasons and the `active/paused/fired/missed/cancelled` status set show the value of naming failure modes. Adopt `missed` and `started_too_late` thinking for scheduled Runs. |
| ADR-0003 | amends | Letta has excellent *human* channels and no inter-agent messaging at all. Suggests separating the two: human collaboration channels and agent-to-agent transport are different problems, and conflating them under one "Channel" resource may be a mistake in our domain model. |
| ADR-0004 | amends | Letta is a harness, not a host, yet it still pays adapter tax: `canonicalToolName` must map "Codex/Gemini aliases" onto one vocabulary *inside the policy layer*. Lesson: tool-name canonicalisation is a prerequisite for policy under adapter neutrality, not an afterthought. |
| ADR-0005 | neutral | No MCP in the read tree; tools are native with separate schema and description artifacts. |
| ADR-0006 | neutral | No A2A or ACP. |
| ADR-0007 | confirms | Channels model humans as first-class participants with access control, admin roles and a `pair` authorisation state, while agents are separate principals with kernel-enforced boundaries. Two distinct principal types with genuinely different mechanisms — supports Principal as root with subtypes. |
| ADR-0008 | **confirms strongly** | Memory is separated by *residency cost* (`system/` vs referenced) and *ownership* (per-agent git repos, cross-agent access hard-denied). First `first_class` H4 in the study. Also validates keeping agent memory distinct from workspace knowledge: skills/mods are separately installable packages. |
| ADR-0009 | amends | Sandbox providers should include **kernel-level** backends (bwrap, seatbelt), not only containers. `SandboxAvailability` shows the interface should report availability with a reason, not throw on use. But Letta proves the negative too: filesystem confinement without CPU/memory quotas leaves S9 unanswered. |
| ADR-0010 | confirms | Three for three: no OTel in any deep-teardown project. The gap is now clearly an industry-wide one rather than a per-project oversight, which strengthens the case for adopting it as a differentiator rather than a checkbox. |
| ADR-0011 | confirms | No version pin on suspended conversations here either, despite `system-prompt-versioning` tests existing. Three for three. |
| ADR-0012 | **confirms strongly** | `SandboxAvailability{backend\|null, reason}` with a real mount probe is the pattern the ADR asks for, plus the fail-closed rule: "Throws when no supported kernel sandbox is available rather than silently running with a weaker policy." Three projects, three designs, and this is the reference implementation. |

**New decision needed:** policy engine changes must be verifiable before cutover.
Letta's `PermissionShadowComparison` runs v2 against v1 and compares decisions on
live traffic. For a platform where policy denies real work, this is the only safe
migration path. Proposing **ADR-0013 — Policy decisions are traced and
shadow-comparable**, covering `PermissionCheckTrace` (why a decision was made) and
shadow evaluation (what a new engine would have decided).

## 26. Open questions

- Does Letta Cloud add agent versioning and revocation, or is that absent
  end-to-end? Closed. (→ OQ-013)
- How does git-backed memory behave at scale — repository growth, history
  rewriting, and conflict frequency in unattended operation? (→ OQ-014)
- Is `pair` (pending sender authorisation) durable across restart like
  `PendingControlRequest`, or in-memory? (→ OQ-015)
