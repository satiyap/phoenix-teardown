# Deliverable 5 — Build / Reuse Map

> Status: **updated from Phase 2 evidence** (LangGraph, OpenHands, Letta).
> Confidence rises as projects corroborate. Finalised at Phase 5.

Decision vocabulary (`schema/facts.schema.yaml`):

| Decision | Meaning |
|---|---|
| `BUILD` | We write and own it. Core differentiation or nothing else fits. |
| `INTEGRATE` | Call across a boundary to an existing system. |
| `ADOPT_AS_STANDARD` | Implement someone else's specification faithfully. |
| `REUSE` | Vendor or embed existing code, licence permitting. |
| `DEFER` | Explicitly out of scope for v0.1. |

## Map

| Subsystem | Decision | Confidence | Evidence | Notes |
|---|---|---|---|---|
| Agent registry | BUILD | **medium** | Letta `agents list` (fuzzy, tags, `--shared`) | Letta proves the shape. Nobody else has one. |
| Agent identity / IAM | BUILD | **medium** | Letta `AGENT_ID` as kernel-enforced boundary | Justified by delegation/policy/audit, not durability (ADR-0001). |
| Agent versioning | BUILD | low | **absent ×3** (`D4`) | No precedent, but ADR-0011 requires it. Phase 3 must confirm. |
| Agent revocation | BUILD | low | **absent ×3** (`D9`) | No precedent anywhere. |
| Task lifecycle | BUILD | **medium** | **absent ×3** (`A4`) | No project separates Task from Run; LangGraph's lack of it is why retry has no home. |
| Run lifecycle | BUILD | **medium** | OpenHands `ExecutionStatus`, Letta cron reasons | Adopt `STUCK`, `CANCELLING` (two entry paths), named failure reasons. |
| Durable HITL / approvals | BUILD | **high** | `first_class` ×3 (`C11`, `G5`) | Table stakes, not a differentiator. Copy OpenHands `ConfirmRisky` + Letta durable pending requests. |
| Human-agent channels | BUILD | **medium** | Letta channels (Slack/Discord/Telegram) | Strong precedent for the shape; not our code. |
| Agent-to-agent transport | **DEFER → decide in Phase 3** | low | **absent ×3** (F-section) | Zero precedent. Must justify from requirements or drop. AG2 is the test. |
| Harness adapters | BUILD | **high** | OpenHands `AgentKind = openhands\|acp` | Proven achievable. Tool-name canonicalisation is a prerequisite. |
| Capability declaration | BUILD | **high** | Letta `SandboxAvailability`, LangGraph conformance suite | ADR-0012. Reference implementation exists; combine both patterns. |
| Conformance test suite | BUILD | **medium** | LangGraph `checkpoint-conformance` | Copy the pattern for adapters and providers. |
| MCP | INTEGRATE | **high** | OpenHands MCP + full OAuth flow | ADR-0005 validated exactly. |
| ACP | ADOPT_AS_STANDARD | **medium** | OpenHands: real Claude Code / Codex / Gemini adapters | Live and working. Note stdio may force co-location (OQ-012). |
| A2A | ADOPT_AS_STANDARD | low | **absent ×3** | Nobody implements it. Reconsider priority. |
| Workflow engine | INTEGRATE | **medium** | LangGraph is the engine; OpenHands/Letta have none | Do not rebuild. Orchestration ≠ agent coordination. |
| Sandbox providers | INTEGRATE via interface | **high** | OpenHands 5 providers, Letta bwrap/seatbelt | ADR-0009. Include **kernel-level** backends, not only containers. |
| Resource quotas (CPU/mem/pid) | BUILD | **medium** | **absent ×3** (`K6`, `N3`, S9) | Nobody does this. Genuine gap; likely control-plane concern. |
| Policy engine | BUILD or INTEGRATE | **medium** | Letta: rules × scope × mode, traced, shadow-comparable | Letta's is the only production-grade one. ADR-0013. |
| Policy trace + shadow eval | BUILD | **medium** | Letta `PermissionShadowComparison` | ADR-0013. |
| Observability / OTel | ADOPT_AS_STANDARD | **high** | **no OTel ×3** | Industry-wide gap. Differentiator rather than checkbox. |
| Canonical event schema | BUILD | **medium** | OpenHands 17 typed events, LangGraph debug payloads | Good vocabularies exist to borrow from. |
| Cost accounting | BUILD | **medium** | OpenHands cost-per-workspace, Letta `memory tokens` | Interesting: OpenHands attaches cost to the *sandbox run*. |
| LLM gateway | INTEGRATE | **high** | all three integrate providers | Never build routing. |
| Vector store | DEFER | **high** | Letta uses **none** — filesystem + explicit reads | Notable: the memory-focused project has no vector DB. |
| Agent memory store | BUILD | **medium** | Letta git-backed, kernel-isolated | Only `first_class` `H4` in the study. Separate by residency cost *and* ownership. |
| Shared knowledge (skills) | INTEGRATE (git) | **medium** | Letta skills/mods, OpenHands org skills from git | Both chose git. Cheap provenance. |
| Secret management | INTEGRATE + BUILD masking | **medium** | OpenHands `SecretRegistry` with output masking | Masking rotated secrets' previous values is worth copying. |
| Artifact storage | INTEGRATE | low | no first-class Artifact ×3 | Outputs are workspace files or memory everywhere. |
| Event bus | INTEGRATE | low | none needed at this scale ×3 | All three are single-node or service-mediated. |
| Control-plane datastore | INTEGRATE | **medium** | Postgres/SQLite ×2, files+git ×1 | Postgres. |
| Scheduler / durable timers | BUILD | **medium** | Letta cron: lease + `boot_id` + 9 named reasons | Best-modelled subsystem in the study. Copy the lease design. |
| Side-effect idempotency | BUILD | low | **absent ×3** (`C6`) | Nobody has a key. Likely a durable effect-ledger on deterministic task id. |
| Tenant isolation | BUILD | low | **absent ×3** OSS (`J7`) | Every project defers this to a commercial tier. |
| Capability gateway | BUILD | **medium** | OpenHands blocking `PreToolUse` hooks | Interception point proven to work. |

## Confidence changes from Phase 2

Raised to **high**: harness adapters, capability declaration, MCP integration,
sandbox provider interface, OTel adoption, durable HITL, LLM gateway, vector-store
deferral.

Still **low** and needing Phase 3: agent versioning, agent revocation,
agent-to-agent transport, side-effect idempotency, tenant isolation, A2A priority.

## Justification bar

`BUILD` requires an answer to all three:

1. Which studied system does this badly enough to justify our doing it?
2. What breaks if we integrate instead?
3. Is this differentiation, or just work?

Phase 2 note: for eight subsystems the answer to (1) is now "**none of them has it
at all**" — Task/Run separation, idempotency, agent versioning, revocation, agent
transport, tenancy, quotas, and OTel. That is a stronger position than "theirs is
bad," but it also means no design to borrow, and for `AgentTransport` specifically
it may mean the requirement is imagined rather than real.
