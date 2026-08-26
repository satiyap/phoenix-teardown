# Deliverable 3 — Canonical Domain Model

> Status: **revised from Phase 2 evidence** (LangGraph, OpenHands, Letta).
> Phase 3 will attack it with seven more projects. Finalised at Phase 5.

Rule: every node must survive a "which project proved you need this?" challenge.
Nodes with no precedent and no scenario requiring them are marked **unjustified**
and must earn their place in Phase 3 or be deleted.

## Revised tree

```text
Organization                       [unjustified — no OSS precedent, J7 absent ×3]
   │
   ├── Policy                      (org-scoped defaults)
   │
   └── Workspace
        │
        ├── Principal              ✓ Letta: two genuinely different mechanisms
        │    ├── Human             ✓ Letta channels: allowed/admin, dm|group, pair
        │    ├── Agent             ✓ Letta: AGENT_ID as kernel-enforced boundary
        │    │    ├── AgentVersion     [unjustified — D4 absent ×3]
        │    │    ├── Capability       ✓ ADR-0012: declared, three-valued
        │    │    ├── Memory           ✓ Letta: per-agent, cross-access denied
        │    │    └── Identity         ✓ Letta: decides memory-tree access
        │    └── Service           [unjustified — defer to post-v0.1]
        │
        ├── Channel                ✓ Letta — but HUMAN surfaces only
        │    └── Message           ⚠ no precedent for durable agent messages
        │
        ├── Task                   ⚠ no project separates Task from Run
        │    ├── Run
        │    │    ├── Step             [telemetry only — not a resource]
        │    │    └── Event            ✓ all three: event stream + replay
        │    └── Artifact          ⚠ weak: implicit in all three
        │
        ├── Knowledge              ✓ Letta skills/mods, OpenHands org skills (git)
        │
        └── Policy                 ✓ Letta: rules × scope × mode, traced
```

Legend: ✓ evidenced · ⚠ thin or contested · [unjustified] no precedent found

## Contested nodes — resolved

| Node | Question | Resolution |
|---|---|---|
| `Session` | Needed, or just Channel + Run? | **Delete.** All three converge on *Conversation* as the durable unit, attached to an Agent. Our `Task` + `Channel` covers it; a separate Session adds nothing. |
| `Step` | Resource or telemetry? | **Telemetry only.** LangGraph's step is checkpoint metadata; OpenHands and Letta have no step resource. Keep it in the event schema, not the domain model. |
| `Capability` vs `Tool` | Split justified? | **Justified, and strengthened.** OpenHands validates it exactly: MCP is the protocol while policy lives in hooks/confirmation/risk. ADR-0012 makes Capability the declared unit. |
| `Knowledge` vs `Memory` | Different owners, or one store? | **Genuinely different.** Letta: agent memory is per-agent git with cross-access hard-denied; skills/mods are separately installable packages. OpenHands: org skills from a git repo. Different owner, lifetime and permission model. |
| `Service` principal | Needed in v0.1? | **Defer.** No precedent; nothing in the scenarios requires it. |
| `AgentVersion` | Immutable versions or mutable + history? | **Unresolved and unjustified.** `D4` absent in all three (LangGraph versions *Assistant config*, not graph topology). But ADR-0011 *requires* a definition version to pin checkpoints against. Phase 3 must settle this. (OQ-013) |
| `Workspace` vs `Project` | One level or two? | **One.** No project has two levels. Letta's permission scopes (`project\|local\|user`) are configuration scope, not a resource hierarchy. |

## New findings that change the model

**1. Channel is a human surface, not an agent transport.**
Letta built excellent human channels (Slack/Discord/Telegram with access control,
threading, mentions, durable approvals) and has *no* agent-to-agent messaging at
all. All three projects lack F-section entirely.

Consequence: `Channel → Message` as drawn conflates two things. Proposed split:

```text
Channel                    human-facing conversation surface
 └── Message               human ↔ agent, durable, threaded

AgentTransport             [PROPOSED — no precedent, must justify from requirements]
 └── Envelope              agent → agent, durable, ordered, correlated
```

Keeping one `Message` type for both would inherit a conflation none of the studied
systems actually made — they simply never built the second half.

**2. Memory divides by residency cost, not just ownership.**
Letta's `system/**` (always in the prompt) versus everything else (metadata only
until read) is a *cost model*. `letta memory tokens` measures it and explicitly
leaves policy to the caller. Our Memory node needs a residency dimension, not only
a scope dimension.

**3. Identity is the justification for Agent, not durability.**
Two projects deliver durable execution with no agent identity. Letta needs
identity because `AGENT_ID` gates memory access and scopes delegation to
`{self, parent}`. The `Identity` child node is therefore load-bearing: it is what
makes `Agent` distinct from a durable conversation.

**4. Capability belongs to both Agent and provider.**
ADR-0012 applies to harness adapters *and* sandbox providers. Capability should
probably be a shared shape used in two places rather than a child of Agent alone.

## State machines

Both revised from evidence. Still provisional.

### Task

```text
DRAFT → QUEUED → ASSIGNED → IN_PROGRESS → COMPLETED
                                  ↓
                          BLOCKED_ON_HUMAN     ✓ durable in all three
                                  ↓
                             IN_PROGRESS

terminal: COMPLETED | FAILED | CANCELLED | ABANDONED
```

No project has a Task resource, so this machine has no precedent to validate
against. The strongest supporting evidence is negative: LangGraph's lack of one is
exactly why "retry this intent" has nowhere to live.

### Run

```text
QUEUED → STARTING → RUNNING → COMPLETED
                       ↓
              WAITING_FOR_TOOL
              WAITING_FOR_HUMAN        ✓ OpenHands WAITING_FOR_CONFIRMATION
              WAITING_FOR_AGENT
                       ↓
                    RUNNING

              STUCK                    ✓ OpenHands — running but not progressing
              CANCELLING               ✓ OpenHands pause vs interrupt
                       ↓
terminal: COMPLETED | FAILED | CANCELLED | TIMED_OUT | SUSPENDED | LOST
                                                       | INCOMPATIBLE  ← ADR-0011
```

Additions from evidence:

- **`STUCK`** (OpenHands `ExecutionStatus.STUCK`). Nearly unique, and obviously
  needed once you operate agents in anger.
- **`CANCELLING`** must be durable, and OpenHands shows it needs *two* entry
  paths: graceful (`pause` — drain the current model call) and immediate
  (`interrupt` — cancel in-flight). Both resumable.
- **`INCOMPATIBLE`** terminal state for ADR-0011: resume attempted against a
  definition version that cannot accept the checkpoint.
- **`LOST`** retained. Letta's `SchedulerOwner` (pid + token +
  `process_start_ticks` + `boot_id`) shows how to detect it properly.

Also worth adopting from Letta's cron: name the *reasons*, not just the states.
`started_too_late`, `queue_full`, `runtime_unavailable`, `scheduler_inactive` are
failure modes that otherwise get swallowed into a generic `FAILED`.

## Cardinality questions — status

- Can a Task have Runs from more than one Agent? (`A8`) — **unresolved.** All three
  handle multi-agent by nesting, not by co-participation.
- Can a Run outlive the AgentVersion that started it? (`C12`, `S3`) — **must not,
  silently.** ADR-0011.
- Can Memory attach to a Workspace rather than an Agent? (`H2`, `H3`) — **yes, as
  `Knowledge`.** Letta and OpenHands both use git-backed shared skills, distinct
  from per-agent memory.
- Is a Message addressed to a Principal, a Channel, or both? (`F1`, `F2`) — **no
  precedent.** Depends on the Channel/AgentTransport split above.
- Does an Artifact belong to a Task or a Workspace? (`A7`) — **unresolved.** No
  project has a first-class Artifact; outputs are workspace files or memory.

## Open modelling questions

- `AgentVersion` has no precedent but ADR-0011 needs it. Either Phase 3 finds it
  (Cloudflare Agents, Google AX manifests) or we build it without precedent and
  say so.
- Is `AgentTransport` a real requirement or speculative generality? Zero precedent
  across three projects. AG2 in Phase 3 is the test.
- Should `Capability` be a shared value type rather than a child of `Agent`?
- Does `Organization` survive, given `J7` is absent in all three OSS projects and
  every studied system defers tenancy to a commercial tier?
