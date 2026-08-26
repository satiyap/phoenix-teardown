# DX log — OpenHands (Agent Canvas + SDK)

Timeboxed hands-on, 2026-08-26. Structural probing only, no LLM keys used.

- Got to a running agent: **not attempted end-to-end** (needs an LLM key and a
  backend); SDK installed and exercised structurally in under 10 minutes.

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | Cloned `OpenHands/OpenHands` expecting Python | Found TypeScript/React — repo is now **Agent Canvas**, not the agent |
| 0:05 | Read README to reorient | Confirmed: control center for OpenHands, Claude Code, Codex, Gemini, any ACP agent |
| 0:10 | Located the real runtime | `OpenHands/software-agent-sdk` — agent-server, workspace providers, hooks |
| 0:20 | `pip install openhands-sdk` | Clean install, 1.43.1 |
| 0:22 | Imported SDK | Prints a promotional banner on import (suppressible via `OPENHANDS_SUPPRESS_BANNER=1`) |
| 0:25 | Exercised the three confirmation policies | Fail-safe on UNKNOWN confirmed; invalid threshold rejected |
| 0:35 | Probed `LocalWorkspace` for capability queries | None exist; `pause()` silently no-ops — the session's most consequential finding |
| 0:45 | Enumerated event classes and state fields | 17 event types; `PauseEvent` and `InterruptEvent` separate |

## Friction points

1. **The repo is not what its name implies.** `OpenHands/OpenHands` being a
   TypeScript control plane while the agent lives in `software-agent-sdk` cost
   about ten minutes of reorientation. Anyone with a stale mental model will hit
   this. It also means the "OpenHands" teardown is really two projects.
2. **A promotional banner on library import.** Printing a bordered ad to stdout
   when a library is imported is intrusive for programmatic use. It is
   suppressible, but the default is wrong for a library.
3. **`LocalWorkspace.pause()` returning success while doing nothing.** This is the
   worst kind of API behaviour: the caller cannot detect it, and there is no
   capability query to check first. Discovering it required deliberately probing
   for it.
4. **Two object models, no published domain model.** Canvas thinks in
   Backend/Conversation; the SDK thinks in Conversation/Workspace/Event. Nothing
   reconciles them in one place.

## What was genuinely good

1. **The ACP provider registry is a readable, honest adapter catalogue.** Each
   provider is a key, a launch command, and credential env vars. The Codex
   comment documenting a silent handshake deadlock is the kind of hard-won note
   that saves someone a day.
2. **Policy objects are unit-testable in isolation.** Confirmation policies could
   be exercised across the whole risk matrix with no infrastructure, which is why
   this teardown has verified rather than inferred findings for G5.
3. **`STUCK` as an execution status.** Someone operated these agents in anger and
   discovered that "running but not progressing" needed a name.
4. **pause vs interrupt documented at the endpoint.** The distinction is explained
   exactly where a reader needs it, not buried in a guide.
5. **Mock-LLM Playwright configs and a mutation-testing config.** Real investment
   in testability, including offline testing of agent flows.
6. **`oasdiff` contract checking**, with a code comment explaining why a field is
   deliberately kept non-nullable. API stability treated as a real constraint.

## Answers to R1–R7

- **R1 clone to running agent:** SDK usable in ~10 min. Full agent run needs an
  LLM key and a backend, so not measured.
- **R2 concepts before hello world:** Canvas hides this well (add backend, pick
  provider, go). The SDK needs Conversation, Workspace, Agent, ConfirmationPolicy
  — four or five.
- **R3 local dev loop:** strong. Vite dev server, Electron app, Playwright with a
  mock-LLM harness.
- **R4 debugging a stuck run:** strong. Typed event stream, `STUCK` status, plus
  file and git inspection of the workspace.
- **R5 unit testing an agent:** good. Mock-LLM configs for flows; policy and state
  objects testable directly.
- **R6 deployment:** best in study so far — npm, Docker, Electron desktop, Helm chart.
- **R7 CLI ergonomics:** Canvas *is* the `agent add` experience, which is the
  right shape. Adding an ACP agent is: pick provider, supply credential.

## Lesson for our own DX

Two things to copy and one to avoid.

Copy: **an adapter catalogue as plain data** (key, launch command, credential
requirements) makes "add an agent" a configuration act rather than a coding act.
And **document adapter failure modes next to the adapter definition** — the Codex
note is more valuable than any amount of prose elsewhere.

Avoid: **an optional operation that silently no-ops.** Our SandboxProvider must
declare `pause` support and raise if unsupported (ADR-0012). A false success is
worse than a refusal, because the caller builds on a belief that was never true.
