"""One-shot: write the ten provisional ADR stubs. Never overwrites.

    ./.venv/bin/python tools/seed_adrs.py

Every ADR carries a 'Falsification' field: the evidence that would overturn it.
An ADR you cannot imagine being wrong is a belief, not a decision.
"""

from __future__ import annotations

from probes import REPO_ROOT

DECISIONS_DIR = REPO_ROOT / "decisions"

ADRS: list[dict] = [
    dict(
        num=1, slug="agent-is-persistent",
        title="Agent identity is persistent; Run is not the Agent",
        decision=(
            "An Agent is a durable, addressable logical actor whose identity "
            "survives process restart. Execution happens in disposable Runs on "
            "interchangeable workers. `Run != Agent`."
        ),
        rationale=(
            "Provisional, pre-evidence. The prior is that durable actor "
            "identity is the abstraction that makes registry, delegation, "
            "policy attachment and audit coherent. Letta, Cloudflare Agents "
            "and AG2 are expected to supply the supporting evidence; "
            "LangGraph is expected to show the cost of not having it."
        ),
        implications=[
            "Runtime workers stay stateless and disposable.",
            "Agent record is authoritative, strongly consistent state.",
            "Requires an agent registry as a core control-plane service.",
            "Agent state must be separable from any single execution.",
        ],
        probes=["D1", "D2", "D3", "A3", "B10"],
        falsification=(
            "If mature systems converge on ephemeral agents with identity "
            "living entirely in an external orchestrator, and durable identity "
            "shows no operational benefit, this collapses into ADR-0004."
        ),
    ),
    dict(
        num=2, slug="task-is-not-run",
        title="Task and Run are separate resources with separate state machines",
        decision=(
            "Task represents intent and may outlive many attempts. Run "
            "represents one execution attempt. Each has its own state machine; "
            "a Task is not merely a Run with extra fields."
        ),
        rationale=(
            "Retry, human reassignment, delegation and cost attribution all "
            "need a stable handle for the intent that survives a failed "
            "attempt. Collapsing the two makes retry semantics ambiguous."
        ),
        implications=[
            "Two state machines to define, not one.",
            "Task-level and Run-level idempotency are different problems.",
            "Cost and telemetry roll up Run -> Task.",
            "A Task can exist with zero Runs (queued, or awaiting assignment).",
        ],
        probes=["A4", "C4", "L7", "S2"],
        falsification=(
            "If no studied system distinguishes them and retry works fine "
            "without the split, the extra resource is unjustified complexity."
        ),
    ),
    dict(
        num=3, slug="messages-are-durable-resources",
        title="Messages are first-class durable resources",
        decision=(
            "Inter-principal messages are persisted, addressable, ordered "
            "within a scope, and independently retrievable — not transient "
            "function arguments."
        ),
        rationale=(
            "Durable messages are the substrate for audit, replay, "
            "human-visible collaboration and asynchronous delegation. "
            "In-memory messaging cannot support any of those."
        ),
        implications=[
            "Message store needed with defined ordering guarantees.",
            "Requires a delivery-semantics decision (at-least-once assumed).",
            "Needs dead-letter handling (see S7).",
            "Message volume becomes a storage sizing concern.",
        ],
        probes=["A6", "F5", "F6", "F7", "F9", "S7"],
        falsification=(
            "If durable messaging proves to be write-amplification with no "
            "consumer, a lighter event log plus ephemeral delivery may suffice."
        ),
    ),
    dict(
        num=4, slug="runtime-is-adapter-based",
        title="Agent runtime is adapter-based; the platform does not author agents",
        decision=(
            "Execution is delegated to pluggable harness adapters behind one "
            "interface. Claude Code, Codex, OpenHands, LangGraph, A2A "
            "endpoints and raw containers are all adapters."
        ),
        rationale=(
            "Framework neutrality is the product thesis. Owning an agent "
            "framework means competing with every framework instead of "
            "orchestrating them."
        ),
        implications=[
            "The adapter interface is one of the most important in the system.",
            "Lowest-common-denominator risk: not all harnesses can checkpoint.",
            "Capability negotiation needed so adapters can declare what they support.",
            "Cancellation and resume semantics must degrade gracefully.",
        ],
        probes=["E1", "E2", "E3", "E7", "E8", "B1"],
        falsification=(
            "If harness capabilities diverge so far that the common interface "
            "becomes useless, a narrower supported set beats a leaky abstraction."
        ),
    ),
    dict(
        num=5, slug="mcp-is-protocol-not-capability-model",
        title="MCP is a tool protocol; Capability is the platform abstraction",
        decision=(
            "MCP is adopted as a transport for tool invocation. The "
            "authorisation, policy and approval unit is a Capability, which is "
            "protocol-independent and may be implemented by MCP or otherwise."
        ),
        rationale=(
            "Policy must outlive protocol churn. Binding governance to MCP "
            "server identity couples permissions to an implementation detail."
        ),
        implications=[
            "Capability registry distinct from tool/server registry.",
            "Capability -> implementation mapping layer required.",
            "Policy evaluated at capability granularity.",
            "Same capability can have several implementations.",
        ],
        probes=["I1", "I2", "I8", "O5"],
        falsification=(
            "If MCP's own scoping evolves to express capability-level policy "
            "adequately, the extra layer is redundant indirection."
        ),
    ),
    dict(
        num=6, slug="a2a-is-interop-not-internal",
        title="A2A is an interoperability protocol, not the internal state model",
        decision=(
            "A2A (and ACP) are implemented at the edge for external agent "
            "interop. Internal state, messaging and task lifecycle use our own "
            "model and are not defined by these wire protocols."
        ),
        rationale=(
            "Wire protocols are consensus artifacts that move slowly and "
            "encode others' compromises. Letting one define internal state "
            "surrenders architectural control."
        ),
        implications=[
            "Translation layer at the boundary.",
            "Some A2A semantics may not map cleanly; document the gaps.",
            "We can support several external protocols without internal churn.",
        ],
        probes=["O5", "F11", "E2", "E3"],
        falsification=(
            "If A2A becomes a genuinely universal substrate and our internal "
            "model adds no expressive power, adopt it natively instead."
        ),
    ),
    dict(
        num=7, slug="humans-and-agents-are-principals",
        title="Humans and agents are distinct subtypes of Principal",
        decision=(
            "Principal is the root security and participation abstraction, with "
            "Human, Agent and Service as subtypes. A human is not modelled as "
            "a kind of agent, but both participate in the same collaboration "
            "graph and both can hold permissions."
        ),
        rationale=(
            "Humans and agents differ in authentication, availability, "
            "accountability and consent. Flattening them into one type makes "
            "the IAM model wrong in ways that surface late."
        ),
        implications=[
            "Shared participation model; separate authN paths.",
            "Approval and escalation are Human-specific affordances.",
            "Audit must distinguish human from agent action.",
            "Delegation across subtypes needs explicit semantics (see S1).",
        ],
        probes=["G1", "G5", "J1", "J6", "S1"],
        falsification=(
            "If uniform treatment demonstrably simplifies the graph without "
            "weakening audit or consent, collapse the hierarchy."
        ),
    ),
    dict(
        num=8, slug="memory-is-not-one-thing",
        title="Agent memory, task context and workspace knowledge are separate",
        decision=(
            "Context is decomposed into ephemeral execution context, task "
            "context, agent memory, workspace knowledge, user context and "
            "enterprise knowledge. Each has its own owner, lifetime and "
            "permission model. None of these is called 'memory' generically."
        ),
        rationale=(
            "Ownership and permissions differ per type. One 'memory' bucket "
            "makes sharing and expiry policy impossible to express, and is the "
            "most common conflation in this product category."
        ),
        implications=[
            "Six context types to specify, with an owner named for each.",
            "Cross-type retrieval needs an assembly step at prompt time.",
            "Permissions attach per type, not globally.",
            "Provenance tracking required to keep types from bleeding together.",
        ],
        probes=["H1", "H2", "H3", "H4", "H5", "S4", "S6"],
        falsification=(
            "If Letta and others show a unified store with typed views is "
            "sufficient, the split is a modelling exercise with no payoff."
        ),
    ),
    dict(
        num=9, slug="sandbox-is-pluggable",
        title="Sandbox is a provider interface; we do not build a sandbox runtime",
        decision=(
            "Define a SandboxProvider interface with Local, Docker, Kubernetes, "
            "Daytona and E2B implementations. The platform does not implement "
            "its own isolation technology."
        ),
        rationale=(
            "Isolation is deep infrastructure with a mature vendor landscape. "
            "Building it consumes the entire engineering budget and competes "
            "with specialists."
        ),
        implications=[
            "Isolation guarantees vary by provider; surface that to policy.",
            "Snapshot/restore may be unavailable on some providers.",
            "Secret injection must work across all of them.",
            "Zombie sandbox reaping is our problem regardless (see S10).",
        ],
        probes=["K1", "K5", "K9", "K7", "S10"],
        falsification=(
            "If no provider supports a capability we consider mandatory (e.g. "
            "fast snapshot for checkpoint/resume), reconsider for that path."
        ),
    ),
    dict(
        num=10, slug="otel-is-canonical-telemetry",
        title="OpenTelemetry is the canonical telemetry transport",
        decision=(
            "Our canonical event schema is emitted over OpenTelemetry wherever "
            "it fits. Domain events carry stable names and become the substrate "
            "for audit and billing as well as debugging."
        ),
        rationale=(
            "OTel is the industry consensus and buys an ecosystem of backends "
            "for free. A proprietary transport buys nothing in return."
        ),
        implications=[
            "Event schema must be defined and versioned deliberately.",
            "Audit and billing need durability guarantees OTel may not give; "
            "may require a separate durable path for those.",
            "Span/event mapping for long-running agent runs needs care.",
            "Cardinality discipline required on agent and tenant ids.",
        ],
        probes=["M1", "M2", "M3", "M4", "M5", "M8"],
        falsification=(
            "If OTel cannot express long-lived, resumable runs without abuse, "
            "keep OTel for tracing and use a dedicated event log for audit."
        ),
    ),
]

BODY = """# ADR-{num:04d} — {title}

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

{decision}

## Rationale

{rationale}

## Implications

{implications}

## Falsification

{falsification}

## Deciding probes

{probes}

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| | | | |

## Open questions

-
"""


def main() -> int:
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    created, skipped = [], []
    for adr in ADRS:
        path = DECISIONS_DIR / f"ADR-{adr['num']:04d}-{adr['slug']}.md"
        if path.exists():
            skipped.append(path.name)
            continue
        path.write_text(BODY.format(
            num=adr["num"],
            title=adr["title"],
            decision=adr["decision"],
            rationale=adr["rationale"],
            implications="\n".join(f"- {i}" for i in adr["implications"]),
            falsification=adr["falsification"],
            probes=", ".join(f"`{p}`" for p in adr["probes"]),
        ))
        created.append(path.name)
    for name in created:
        print(f"  + {name}")
    if skipped:
        print(f"  kept {len(skipped)} existing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
