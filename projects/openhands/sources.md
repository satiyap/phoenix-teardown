# Sources — OpenHands (Agent Canvas + Software Agent SDK)

## Repositories

**Important:** `OpenHands/OpenHands` is no longer the Python agent. It is now
**Agent Canvas**, a self-hosted control center. The agent, sandbox and runtime
live in `OpenHands/software-agent-sdk`. Both were read.

| Repo | Commit | Date | Role |
|---|---|---|---|
| `OpenHands/OpenHands` | `f48eca6ab9149b3aa532e86842c85da43e370108` | 2026-08-25 | Agent Canvas: control plane UI, ACP provider registry, manifests |
| `OpenHands/software-agent-sdk` | `760eea2845509ceb446db11f73ca5aa666bd01bb` | 2026-08-25 | agent-server, SDK, workspace/sandbox providers, hooks, security |

Cloned `--depth 1` to `~/dev/_teardown_src/openhands` and `~/dev/_teardown_src/oh-sdk` on 2026-08-26.
Installed for testing: `openhands-sdk` 1.43.1.

Org renamed from `All-Hands-AI` to `OpenHands`; the old path redirects.

## Key source files — Canvas (`@ f48eca6`)

| Path | Why it matters |
|---|---|
| `src/types/settings.ts:98-110` | `AgentKind = "openhands" \| "acp"` — the peer-adapter decision, with the note that credentials come via Secrets, never a per-agent env channel |
| `src/constants/acp-providers.ts:69-135` | ACP provider registry: stable key, `default_command`, models. Mirrored from the Python SDK source of truth |
| `src/constants/acp-providers.ts:85-92` | The Codex warning: a plausible-looking command that is not a real ACP server silently deadlocks the handshake |
| `src/constants/acp-providers.ts:221-254` | Per-provider credential env vars (`CODEX_AUTH_JSON`, `CLAUDE_CODE_OAUTH_TOKEN`, Google creds) |
| `src/manifests/manifest-capabilities.ts:14,36` | Capability assessment where `unknown` is a distinct outcome, returning which requirements were unmet |
| `src/api/backend-registry/types.ts:1-23` | `Backend`, `BackendKind = local\|cloud`, `connectionRevision` |
| `src/types/agent-server/core/base/common.ts:59-75` | `SecurityRisk` and `ExecutionStatus` (incl. `STUCK`, `WAITING_FOR_CONFIRMATION`) |
| `src/types/agent-server/core/events/action-event.ts:46,61` | `security_risk` predicted by an LLM risk analyzer |
| `src/types/agent-server/core/events/conversation-state-event.ts:85` | Goal status `running\|complete\|capped\|interrupted` |
| `specs/backend-management.md` | Behavioural specs BM-001..003 for backend switching |
| `helm/agent-canvas/`, `docker/`, `electron/` | Deployment surfaces |

## Key source files — SDK (`@ 760eea2`)

| Path | Why it matters |
|---|---|
| `openhands-sdk/openhands/sdk/workspace/base.py:27-281` | `BaseWorkspace` ABC: abstract `execute_command`, `file_upload/download`, `git_changes/diff`; optional `pause`/`resume` via `NotImplementedError`; cost registration |
| `openhands-workspace/openhands/workspace/{docker,apptainer,remote_api,cloud}/workspace.py` | Five provider implementations; `pause` in three of five |
| `openhands-workspace/.../docker/workspace.py:240-258` | Container run flags — only `--ulimit nofile`, no CPU/memory/pid quota |
| `openhands-sdk/.../conversation/state.py:170-200,310-370` | Event **tree**: `leaf_event_id` movable HEAD, `append_event` single chokepoint, incremental O(k) replay |
| `openhands-sdk/.../security/confirmation_policy.py` | `AlwaysConfirm`, `NeverConfirm`, `ConfirmRisky(threshold, confirm_unknown=True)` with validator |
| `openhands-sdk/.../conversation/secret_registry.py:35,77,143,161` | Lazy resolution, output masking per output and per ACP chunk, masks rotated secrets' previous values |
| `openhands-sdk/.../hooks/config.py:39-60`, `types.py` | `HookType = COMMAND\|PROMPT\|AGENT`; `HookEventType = PreToolUse\|PostToolUse\|UserPromptSubmit\|SessionStart\|SessionEnd\|Stop` |
| `openhands-sdk/.../hooks/conversation_hooks.py:92,164` | Hooks can **block** actions; `HookExecutionEvent.blocked` |
| `openhands-sdk/.../observability/laminar.py:400-430` | OTel via Laminar; deliberate span severing and `delegate.parent_trace_id` re-linking (cites bug #4365) |
| `openhands-agent-server/.../conversation_router.py:236-268` | **pause vs interrupt** with the semantic difference documented at the endpoint |
| `openhands-agent-server/.../conversation_router.py:89-429` | Full conversation API surface |
| `openhands-agent-server/.../mcp_router.py:632-790` | MCP with OAuth: start / status / callback / test |
| `openhands-agent-server/.../config.py:23-51` | `SESSION_API_KEY` / `OH_SESSION_API_KEYS_0` — shared secret, not per-agent identity |
| `openhands-agent-server/.../skills_router.py:62-125` | Organization-level skills from a pre-authenticated git URL |
| `openhands-agent-server/.../sub_agents_router.py:117` | Sub-agent delegation |

## Verification experiments

Run 2026-08-26 against `openhands-sdk` 1.43.1. No LLM calls — structural behaviour only.

| Probe | Experiment | Result |
|---|---|---|
| `G5` / `I9` | Evaluate all three confirmation policies across every risk level | `ConfirmRisky` is **fail-safe on UNKNOWN** (CONFIRM); `threshold=UNKNOWN` rejected with `ValidationError` |
| `K9` | Introspect `LocalWorkspace` for any capability-query attribute | **NONE.** `pause()` silently succeeds as a no-op |
| `C3` | Inspect `ConversationState` fields and tree methods | `leaf_event_id`, `head_is_empty`, `secret_registry`, `confirmation_policy` present; `append_event` is the chokepoint |
| `E4` / `M1` | Enumerate event classes | 17, including `PauseEvent` and `InterruptEvent` as **separate** classes, plus `TokenEvent`, `HookExecutionEvent`, `ACPToolCallEvent` |

## Negative findings

| Searched for | Result |
|---|---|
| `opentelemetry` in SDK | Only inside `observability/laminar.py` — no direct OTel instrumentation |
| CPU/memory/pids limits in Docker workspace | Only `--ulimit nofile=65536` |
| `tenant` in agent-server | Nothing; only org-level *skills* config |
| capability query on `BaseWorkspace` | No `supports_*` / `capabilities` method |

## Documentation

| URL | Read on | Notes |
|---|---|---|
| https://docs.openhands.dev | 2026-08-26 | Referenced for ACP agents and backends |
| `README.md`, `docs/SELF_HOSTING.md` @ f48eca6 | 2026-08-26 | Product framing, self-hosting path |

OpenHands Cloud and Enterprise are closed; quota enforcement and organizations
are cloud-side and therefore class B evidence at best.
