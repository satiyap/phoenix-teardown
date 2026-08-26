# Sources — Cloudflare Agents

## Repository

- repo: https://github.com/cloudflare/agents
- commit: `2f957bc2a3ffb7aee14792bb3cb658ad3176ed93`
- commit date: 2026-08-26
- cloned on: 2026-08-26 (`--depth 1` to `~/dev/_teardown_src/cloudflare-agents`)
- size: 35MB
- language: TypeScript
- license: MIT
- structure: `nx`/`pnpm` monorepo — packages `agents`, `ai-chat`, `channels`, `codemode`, `hono-agents`, `shell`, `think`, `voice`, `worker-bundler`

## Verification

Built and ran the fiber test suite, 2026-08-26. Three obstacles, recorded because
they are the DX finding:

```
pnpm install                    → FAILS: better-sqlite3 native build errors on Node 26
pnpm install --ignore-scripts   → OK
vitest run src/tests/run-fiber.test.ts
                                → FAILS: cannot resolve agents/dist/vite.js
pnpm --filter agents run build  → OK
vitest ...                      → FAILS: cannot resolve @cloudflare/codemode (optional peer)
pnpm --filter codemode run build → OK
vitest run src/tests/run-fiber.test.ts
                                → 48/48 PASS
```

The decisive run, isolating the `C6` evidence:

```
vitest --run src/tests/run-fiber.test.ts -t "dedupe managed fibers by idempotency key"
  ✓ 1 passed | 47 skipped
```

That test (`src/tests/run-fiber.test.ts:578-595`) asserts:

| Assertion | Meaning |
|---|---|
| `first.accepted === true` | the first start did the work |
| `second.accepted === false` | the duplicate was recognised, not re-run |
| `second.fiberId === first.fiberId` | it returns the *existing* record |
| `executionLog === ["managed:first"]` | **the side effect executed exactly once** |

The last assertion is why this counts as closing `C6` rather than merely
short-circuiting a call.

## Design documents (43 in `design/`)

Read first, per the Phase 3 method. The four that mattered:

| Document | Lines | Why |
|---|---|---|
| `retries.md` | 183 | The retry system: `tryN`, full jitter, eager validation, per-call-site config, and *why* overload errors are excluded |
| `durable-object-lifecycle.md` | 82 | `Lifecycle` capability phases, host context, hibernating WebSockets, identity |
| `channels.md` | 173 | Why channels is **stateless**; rejects its own previous durable host. The best-argued document in the study |
| `rfc-sub-agents.md` | — | Storage boundary as enforcement boundary; the "LLM can bypass the queue by writing SQL" argument |

`channels.md` opens by stating it "deliberately describes no API, so nothing in it
goes stale as the package changes" — a documentation practice worth copying.

## Key source files

| Path | Why it matters |
|---|---|
| `packages/agents/src/index.ts` (13,214 lines) | The `Agent` class: state, RPC, schedules, queues, fibers, MCP, workflows, sub-agents |
| `index.ts:2280-2291` | `cf_agents_fibers` schema — **`idempotency_key TEXT UNIQUE`** |
| `index.ts:2250-2256` | `cf_agents_runs` schema (durable; the orphan-join partner) |
| `index.ts:2258-2261` | v5 root-side index of descendant facet fibers — "only lets the root alarm owner know which facets need recovery checks while they are idle" |
| `index.ts:5522-5590` | `startFiber` — pre-execution key check, `accepted: false`, throws on conflicting identity |
| `index.ts:5379-5404` | `cancelFiber` / `cancelFiberByKey` — durable status flip + `AbortController`, guarded against re-cancelling a terminal fiber |
| `index.ts:6500-6600` | `_scheduleNextAlarmBody` — hung detection, overdue catch-up, orphan recovery, exponential backoff on no-progress scans |
| `index.ts:1197,2081-2087` | `CURRENT_SCHEMA_VERSION = 11`, stored as a row, checked on wake |
| `index.ts:1215-1224` | Sub-agent identity = logical name + SHA-256 digest |
| `index.ts:8139-8153` | `parentAgent()` — typed stub, with a comment on why the direct parent is the *last* path entry |
| `packages/agents/src/retries.ts` | `tryN`, `jitterBackoff`, `isErrorRetryable`, `validateRetryOptions` |
| `packages/agents/src/agent-routing.ts:73-84` | `onBeforeConnect` / `onBeforeRequest` — auth as a developer hook |
| `packages/agents/src/sub-routing.ts:489-491` | Documents its own auth bypass |
| `packages/agents/src/observability/genai/attributes.ts:1-25` | GenAI semconv adherence and the vendor-namespace rule |
| `packages/agents/src/observability/tracing/tracer.ts:24-31,298` | `boundToInvocation` span lifetimes; refusal to invent `otel.status_code` |
| `packages/channels/src/identity.ts:1-8` | `ChannelIdentity{channelKey, scope, subject}` — a **human** correspondent |
| `packages/agents/src/chat/wire-types.ts:36,207` | `cf_agent_tool_approval` message type |
| `packages/agents/src/tests/run-fiber.test.ts:555-600` | The idempotency and dedupe tests |

## Negative findings

| Searched for | Result |
|---|---|
| agent-to-agent messaging | **Nothing.** `channels` is human↔agent (Slack/Telegram/email/voice). Sub-agents use typed RPC. Seven for seven |
| adapter/harness contract for third-party agents | **Nothing** — by design. You write the agent as a subclass |
| authentication / authorization / principals | **Nothing.** Auth is `onBeforeConnect`, a developer hook |
| tenancy, quotas, cost accounting | Nothing |
| agent versioning / revocation | Nothing (sub-agent identity does embed a content digest) |
| declared capability model | Nothing |
| snapshot version column | **Nothing** — `snapshot TEXT` with no version, on both fiber and run tables |
| compensation / rollback | Nothing |
| pluggable storage backend | Nothing, and impossible — DO storage is the design |
| `getSharedMemory` as an SDK primitive | **Not one** — appears only in a docstring example as a user-defined RPC method |

## Documentation

| Path | Read on | Notes |
|---|---|---|
| `README.md` @ 2f957bc | 2026-08-26 | SDK overview |
| `design/` (43 docs) @ 2f957bc | 2026-08-26 | RFCs and design notes; several marked `accepted` |
| `AGENTS.md` @ 2f957bc | 2026-08-26 | Repo conventions |
