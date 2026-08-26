# DX log — Cloudflare Agents

Timeboxed hands-on, 2026-08-26. Built the monorepo and ran the fiber suite; did not
deploy to Workers (needs a Cloudflare account).

- Clone to passing tests: **~25 minutes**, three blocking obstacles
- Tests once building: 48/48 pass in ~5s, in the *real* workers runtime

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | Cloned; found `design/` with 43 documents and a `channels` package | `channels` looked like the first agent-to-agent messaging evidence in the study |
| 0:06 | Read `retries.md` | First structured retry policy anywhere in this study, and it explains *why* it excludes overload errors |
| 0:15 | Grepped for `hungScheduleTimeoutSeconds` | Led to `_scheduleNextAlarmBody` — the best lost-worker recovery logic I have read |
| 0:22 | Grepped the fiber table schema | **`idempotency_key TEXT UNIQUE`** — the `C6` gap, closed |
| 0:26 | Found the dedupe test asserting the execution log | Decided to run it rather than trust it |
| 0:30 | `pnpm install` | **Failed**: `better-sqlite3` native build errors on Node 26 |
| 0:36 | `pnpm install --ignore-scripts` | OK |
| 0:38 | `vitest run src/tests/run-fiber.test.ts` | **Failed**: cannot resolve `agents/dist/vite.js` — the vitest config imports the package's own build output |
| 0:42 | `pnpm --filter agents run build` | OK, then **failed** on `@cloudflare/codemode`, an optional peer |
| 0:46 | `pnpm --filter codemode run build`, rerun | **48/48 pass.** Idempotency verified: side effect ran once |
| 0:55 | Read `channels.md` and `identity.ts` | Not agent-to-agent — human↔agent transport. Seven for seven confirmed |
| 1:05 | Read `observability/genai/attributes.ts` | Best OTel convention discipline in the study |
| 1:15 | Checked for a snapshot version column | None. The ADR-0011 amendment |

## Friction points

1. **Three sequential build obstacles before any test runs.** A native module that
   will not compile on current Node, a vitest config that imports the package's own
   `dist/`, and an optional peer that must be built anyway. Each error message was
   accurate, but none suggested the fix, and the chain is only discoverable by
   working through it. A `pnpm bootstrap` script would remove all three.
2. **A 13,214-line `index.ts`.** The `Agent` class holds fibers, schedules, queues,
   MCP, workflows, sub-agents, state and RPC. Navigating it meant grepping for
   table names and reading outward. The `design/` docs are what made it tractable.
3. **Platform coupling means you cannot evaluate it in isolation.** Every mechanism
   assumes Durable Objects. I could run tests (the vitest workers pool emulates the
   runtime) but not reason about portability, because there is none.
4. **`channels` is a misleading name for an architecture reader.** I spent time
   expecting agent-to-agent messaging. That is my inference, not their error — but
   it cost twenty minutes.

## What was genuinely good

1. **Tests run in the real runtime.** The vitest workers pool executes agents as
   actual Durable Objects with real SQLite, so a passing durability test means
   something. Contrast the usual mock-a-store approach.
2. **A test that asserts the side effect, not the return value.** The idempotency
   test checks `executionLog === ["managed:first"]`. That is the difference between
   testing a guard and testing the guarantee.
3. **`design/` explains reasoning, including rejected alternatives.** `retries.md`
   has a "Key decisions" section answering "why full jitter, not equal or
   decorrelated jitter" with a citation. `channels.md` has "What we rejected" and
   includes its *own previous implementation*.
4. **Comments that name the hazard they prevent.** On `parentAgent()`: destructuring
   the first path entry "silently routes to the wrong DO" for chains deeper than one
   level. On the recovery alarm: without a follow-up alarm "those leftovers would
   starve, since the orphans hold no keepAlive ref."
5. **Documented auth bypasses.** `getSubAgentByName` states that it does not run the
   parent's hook and that the caller is assumed to have done its own checks.
6. **Refusing the unsafe convenience.** "There is no in-memory WebSocket mode."
7. **A design doc that describes no API on purpose**, so it cannot go stale.

## Answers to R1–R7

- **R1 clone to running:** ~25 min for the monorepo, with three obstacles. A
  single-agent `wrangler` quickstart would be minutes — the friction is
  monorepo-specific, not SDK-specific.
- **R2 concepts before hello world:** very few. Extend `Agent`, add a wrangler
  binding, call `getAgentByName`. Durability, hibernation and storage are ambient
  rather than concepts you must learn first. Lowest conceptual load in the study.
- **R3 local dev loop:** excellent. `wrangler dev` runs Workers and DOs locally with
  real SQLite; tests run in the real runtime.
- **R4 debugging:** strong. `inspectFiber` / `inspectFiberByKey` / `listFibers`, a
  typed observability event stream with retry attempts, and OTel spans following
  GenAI semconv.
- **R5 unit testing:** among the best. 48 fiber tests covering idempotency,
  recovery, cancellation and orphans, in the real runtime.
- **R6 deployment:** `wrangler deploy`. One target, no self-hosting.
- **R7 CLI ergonomics:** `wrangler` plus a `shell` package. No agent-management CLI,
  because agents are code rather than registry entries.

## Lessons for our own DX

**Test the guarantee, not the guard.** The single most valuable artefact in this
repo is a test asserting that a deduped call left one entry in an execution log.
Every durability claim in our platform needs an equivalent: not "the second call
returned early" but "the effect happened once". Our conformance bench should be
structured around observable effects for exactly this reason.

**Run tests in the real runtime.** Cloudflare's durability tests are credible
because they execute against actual Durable Objects. If we test durable execution
against a mock store, we are testing our mock. This argues for a test harness that
runs the genuine control plane against a real (if ephemeral) database.

**Ship a bootstrap script.** Three sequential, individually-reasonable build
obstacles cost twenty minutes. A `make bootstrap` that installs, builds
dependencies in order, and verifies would have cost the maintainers ten lines.
