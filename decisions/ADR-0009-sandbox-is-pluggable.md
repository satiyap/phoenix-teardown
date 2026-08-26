# ADR-0009 — Sandbox is a provider interface; we do not build a sandbox runtime

- **Status:** Provisional (pre-evidence, Phase 0)
- **Date:** 2025-08-26
- **Supersedes:** —
- **Superseded by:** —

## Context

Written before the teardown as a strawman to be attacked. Phase 2 drafts these
from three deep probes; Phase 3 runs the remaining projects against them. Each
pass must record `confirms`, `amends`, `challenges` or `neutral` in its
`facts.yaml` `adr_impact`.

A provisional ADR is a hypothesis with a falsification condition, not a
commitment.

## Decision

Define a SandboxProvider interface with Local, Docker, Kubernetes, Daytona and E2B implementations. The platform does not implement its own isolation technology.

## Rationale

Isolation is deep infrastructure with a mature vendor landscape. Building it consumes the entire engineering budget and competes with specialists.

## Implications

- Isolation guarantees vary by provider; surface that to policy.
- Snapshot/restore may be unavailable on some providers.
- Secret injection must work across all of them.
- Zombie sandbox reaping is our problem regardless (see S10).

## Falsification

If no provider supports a capability we consider mandatory (e.g. fast snapshot for checkpoint/resume), reconsider for that path.

## Deciding probes

`K1`, `K5`, `K9`, `K7`, `S10`

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | neutral | `libs/langgraph/langgraph/pregel/main.py @ 3803173` | No sandbox at all; nodes run in the host process. Zero evidence either way. |
| OpenHands | confirms | `openhands-sdk/.../workspace/base.py:27,261 @ 760eea2` | Direct precedent: five providers (Local, Docker, Apptainer, RemoteAPI, Cloud) behind one ABC. Apptainer proves the abstraction is load-bearing. Negative lesson: optional capabilities signalled by NotImplementedError with no query method, and LocalWorkspace.pause() silently no-ops. Isolation is thin - only --ulimit nofile, no CPU/memory/pid quota. |
| Letta | amends | `src/sandbox/availability.ts:7-45 @ 852ca24`; `src/sandbox/{bwrap,seatbelt}.ts @ 852ca24` | Sandbox providers should include KERNEL-LEVEL backends (bwrap user namespaces, macOS Seatbelt), not only containers — a different and lighter bet than OpenHands. The interface should report availability with a reason rather than throwing on use. But filesystem confinement without CPU/memory/pid quotas leaves S9 unanswered, same gap as OpenHands. |
| Google AX | confirms | `internal/ate/client.go @ b777313`; `internal/config/config.go:95-97` | Delegates isolation entirely to SubstrATE, an external actor system, and lets users supply their own `ActorTemplate` and container image. A provider interface rather than an implementation, arrived at independently. AX implements no isolation itself. |

## Open questions

-
