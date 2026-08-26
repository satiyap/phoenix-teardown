# ADR-0004 — Agent runtime is adapter-based; the platform does not author agents

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

Execution is delegated to pluggable harness adapters behind one interface. Claude Code, Codex, OpenHands, LangGraph, A2A endpoints and raw containers are all adapters.

## Rationale

Framework neutrality is the product thesis. Owning an agent framework means competing with every framework instead of orchestrating them.

## Implications

- The adapter interface is one of the most important in the system.
- Lowest-common-denominator risk: not all harnesses can checkpoint.
- Capability negotiation needed so adapters can declare what they support.
- Cancellation and resume semantics must degrade gracefully.

## Falsification

If harness capabilities diverge so far that the common interface becomes useless, a narrower supported set beats a leaky abstraction.

## Deciding probes

`E1`, `E2`, `E3`, `E7`, `E8`, `B1`

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | confirms | `libs/checkpoint-conformance/.../capabilities.py @ 3803173` | Supplies the capability-negotiation pattern: BASE vs EXTENDED capabilities, runtime detection via method-override check, spec tests gated on detected set. Adopt this shape for harness adapters. |
| OpenHands | confirms | `src/constants/acp-providers.ts:82-92 @ f48eca6` | Strongest evidence yet: own agent is a peer of foreign ACP agents behind one enum, with a registry of launch commands. Plus a concrete failure mode - a plausible but wrong ACP command silently DEADLOCKS the handshake, so adapters need validation not just configuration. |
| Letta | amends | `src/permissions/canonical.ts @ 852ca24`; `src/permissions/cross-agent-guard.ts:6-8 @ 852ca24` | Letta is a harness not a host, yet still pays adapter tax: `canonicalToolName` must map Codex/Gemini aliases onto one vocabulary INSIDE the policy layer. Tool-name canonicalisation is a prerequisite for policy under adapter neutrality, not an afterthought. |

## Open questions

-
