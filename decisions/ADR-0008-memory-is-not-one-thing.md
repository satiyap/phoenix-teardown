# ADR-0008 — Agent memory, task context and workspace knowledge are separate

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

Context is decomposed into ephemeral execution context, task context, agent memory, workspace knowledge, user context and enterprise knowledge. Each has its own owner, lifetime and permission model. None of these is called 'memory' generically.

## Rationale

Ownership and permissions differ per type. One 'memory' bucket makes sharing and expiry policy impossible to express, and is the most common conflation in this product category.

## Implications

- Six context types to specify, with an owner named for each.
- Cross-type retrieval needs an assembly step at prompt time.
- Permissions attach per type, not globally.
- Provenance tracking required to keep types from bleeding together.

## Falsification

If Letta and others show a unified store with typed views is sufficient, the split is a modelling exercise with no payoff.

## Deciding probes

`H1`, `H2`, `H3`, `H4`, `H5`, `S4`, `S6`

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | confirms | `libs/checkpoint/langgraph/store/base/__init__.py:708,545 @ 3803173` | Checkpointer (execution state) vs BaseStore (cross-thread memory) vs BaseCache is a real, useful separation with TTL and namespaces. BUT no permissions (H4) and no provenance (H5) — namespaces look like an isolation boundary and are not one. |
| OpenHands | amends | `openhands-agent-server/.../skills_router.py:62-125 @ 760eea2` | Condensation-only context management with no long-term or shared memory. But org-level skills loaded from a git repository suggest organizational knowledge may be better served by versioned git-backed instructions than by a memory store. |
| Letta | confirms | `src/tools/descriptions/Memory.md @ 852ca24`; `src/memory-confinement.ts:14-21 @ 852ca24` | **Strongest H-section evidence in the study.** Memory separated by RESIDENCY COST (`system/**` always in prompt vs metadata-only-until-read) and by OWNERSHIP (one git repo per agent, cross-agent access hard-denied). First `first_class` H4: permissions are kernel-enforced and fail-closed. Provenance is free from git, plus a required `reason` on every mutation. |
| Google AX | confirms | `internal/skills/ @ b777313`; `internal/config/config.go:119-133` | No memory subsystem at all; skills are registry- or filesystem-sourced and explicitly harness-agnostic. **Third project to choose filesystem/git-backed skills over a memory store** (with Letta and OpenHands). Strong convergence for the Knowledge node. |
| Omnigent | confirms | `omnigent/spec/AGENTSPEC.md @ ba9e371` | No memory subsystem. Knowledge is `skills/<dir>/SKILL.md` plus `AGENTS.md` inside a portable, versioned agent image. **Fourth consecutive project** to choose filesystem/git-backed skills over a memory store (with Letta, OpenHands, Google AX). Strongest positive convergence in the study — I consider this settled for v0.1. |

## Open questions

-
