# Licensing and Commercial Reuse
<!-- status: final -->

Completed **2026-08-26** during Phase 1, before deep reading. A licence that
forbids embedding changes what a deep teardown is *for* — read for ideas rather
than for code.

This is engineering triage, not legal advice. Anything in the `AVOID` column, or
any copyleft project we intend to embed, needs review by someone qualified
before code is taken.

Evidence: GitHub `/repos` and `/repos/{r}/license` endpoints, read 2026-08-26.

## Verdicts

| Verdict | Meaning |
|---|---|
| `USE` | Permissive. Safe to vendor or embed with attribution. |
| `INTEGRATE` | Call across a process or network boundary; do not embed. |
| `REFERENCE_ONLY` | Read for architecture. Take no code. |
| `AVOID` | Licence or trademark makes it a liability even to study closely. |

## Table

| Project | License | Enterprise-only parts | SaaS restriction | Network copyleft | Trademark notes | Verdict |
|---|---|---|---|---|---|---|
| Google AX | Apache-2.0 | none found | none | no | Google marks; "AX"/"Agent Executor" naming | REFERENCE_ONLY |
| Omnigent | Apache-2.0 | Omnigent Cloud (hosted) | none | no | project name | INTEGRATE |
| AG2 | Apache-2.0 | none found | none | no | AG2 / AutoGen lineage naming | REFERENCE_ONLY |
| Letta | Apache-2.0 | **Letta Cloud** — hosted memory, identity, cross-device continuity | none | no | Letta / MemGPT marks | REFERENCE_ONLY |
| OpenHands | MIT | OpenHands Cloud (hosted) | none | no | project name | INTEGRATE |
| Cloudflare Agents | MIT | Cloudflare platform itself (Durable Objects, Workers) | none | no | Cloudflare marks | REFERENCE_ONLY |
| LangGraph | MIT | **LangSmith server is closed**; LangGraph Platform is commercial | none | no | LangChain marks | INTEGRATE |
| Pydantic AI | MIT | Pydantic Logfire (hosted observability) | none | no | Pydantic marks | INTEGRATE |
| Google Agent Platform | Apache-2.0 (ADK) | **Vertex AI Agent Engine control plane is closed** | n/a — is a SaaS | no | Google marks | INTEGRATE |
| GroupMind | n/a | — | — | — | — | not located |
| Microsoft Agent Framework | MIT | Azure AI Foundry (hosted) | none | no | Microsoft marks | REFERENCE_ONLY |
| AWS AgentCore | Apache-2.0 (SDK/CLI) | **AgentCore managed runtime, identity, gateway, memory are closed** | n/a — is a SaaS | no | AWS/Bedrock marks | REFERENCE_ONLY |
| HumanLayer | Apache-2.0 | HumanLayer Cloud (hosted) | none | no | project name | INTEGRATE |
| Agent Control | n/a | — | — | — | — | not located |

## Findings

**No copyleft anywhere in the set.** Every located project is Apache-2.0 or MIT.
For a product intended to ship as both SaaS and customer-deployed — the strictest
combination — this is the best possible outcome: no source-provision trigger from
hosting, and no problematic licence travelling with a redistributed artifact.
Apache-2.0 carries a patent grant and a NOTICE obligation; MIT needs attribution
only. Both are satisfiable.

Consequence: `REFERENCE_ONLY` verdicts in this table are **architectural**
judgements, not legal ones. Google AX is Go where we are not; Cloudflare Agents
is inseparable from Durable Objects; Microsoft Agent Framework and AG2 carry
framework opinions we do not want internally. We *could* legally embed any of
them.

**HumanLayer's licence needed manual verification.** GitHub reports
`NOASSERTION` / `key: other`, but the LICENSE file is the Apache-2.0 text with a
standard `Copyright (c) 2024, humanlayer Authors` header. The detector missed it
because of the leading `Apache Software License 2.0` title line. Treat as
Apache-2.0. This is a reminder that API-reported licence fields are a hint, not
evidence.

**The open-core boundary sits exactly where our interest is — four times over.**
This is the most consequential licensing finding, and it is a research constraint
rather than a legal one:

| Project | Open | Closed | Probes affected |
|---|---|---|---|
| LangGraph / LangSmith | graph runtime, checkpointers | LangSmith server, LangGraph Platform | M-section (observability), N-section |
| Letta | harness, App Server, channels | Letta Cloud: hosted memory, identity, cross-device continuity | H-section (memory), D-section |
| AWS AgentCore | SDK, CLI, starter toolkit | managed runtime, identity, gateway, memory | D, I, J, K |
| Google Agent Platform | ADK | Vertex Agent Engine control plane | B, C, N |

Every one of those closed components is a *control plane* — identity, hosted
memory, multi-tenancy, observability backend. Which is a finding in itself: the
industry consistently treats the control plane as the commercial layer and the
agent framework as the giveaway. That is precisely the layer we intend to build,
and it is the layer with the least available prior art.

Practical effect on the teardown: for these four, control-plane behaviour is
class B evidence at best. Mark confidence `low`, cite docs with dates, and never
record `absent` for something that is merely undocumented — the distinction
between `absent` and `unknown` exists for exactly this case.

**Two projects could not be located.** GroupMind and Agent Control have no
identifiable public repository. No licence assessment is possible; questions
reassigned in `recon.md`.
