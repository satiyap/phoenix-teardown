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

## Amendment — 2026-08-26 (Phase 3, Pydantic AI): egress is part of the sandbox

This ADR treated sandboxing as *process* isolation. Pydantic AI, which has no
process isolation at all, identifies a threat the ADR missed entirely:

**An agent with a URL-fetching tool is an SSRF primitive pointed at your own
infrastructure.** A prompt-injected agent asked to "fetch this URL" can reach
`169.254.169.254` and read the instance's IAM credentials. No amount of process
isolation prevents this, because the request is exactly what the tool is for.

`_ssrf.py @ b48ee38` is the most thorough answer found in this study:

- Protocol validation, hostname→IP resolution, and blocking of private ranges,
  link-local (`169.254.0.0/16`), and CGNAT (`100.64.0.0/10`, noted as including
  Alibaba's metadata service).
- **Teredo prefix decoding** (`2001::/32`) because obfuscated IPv6 forms would
  otherwise slip through: "the raw low-32 bytes are meaningless, so it needs its
  own decode".
- An **enumerated cloud credential blocklist**: `169.254.169.254` (AWS IMDS, GCP,
  Azure, OCI, DigitalOcean, Hetzner, IBM, OpenStack), `169.254.170.2` (**AWS ECS
  task IAM role credentials**), `169.254.170.23` (**AWS EKS Pod Identity Agent**),
  `168.63.129.16` (Azure WireServer), `100.100.100.200` (Alibaba),
  `192.0.0.192` (Oracle Classic), `169.254.42.42` (Scaleway), plus IPv6 forms.
- **Bounded downloads** with `Accept-Encoding` restricted to `identity, gzip`,
  rejecting brotli/zstd/deflate even when returned, because they "can expand a few
  compressed bytes into multi-MiB output in one decoder step" and `deflate` "has to
  be buffered whole" before its framing can be determined.

**The design principle, and the reason this is an amendment rather than a note:**

> Cloud metadata / credential endpoints — always blocked, **even with
> `allow_local=True`**. When `allow_local=True` we skip the private-IP check, so
> these must be caught explicitly. Most are also covered by the private ranges
> above, but `168.63.129.16` (Azure) is a **public IP**, so the metadata guard is
> the only thing that blocks it.

**An escape hatch must be scoped so it cannot open the worst hole.** The local-access
option exists for legitimate development, and deliberately does not grant access to
credential endpoints. Most escape hatches are all-or-nothing; this one is not.

**Amended decision.** The sandbox provider interface covers three boundaries, not
one:

1. **Process/filesystem isolation** — as originally specified (bwrap, seatbelt,
   containers, isolates, external actor systems).
2. **Egress control** — a mandatory guard on every outbound request an agent can
   cause, including tool fetches. Blocks private ranges, link-local, CGNAT, and an
   enumerated cloud-metadata list that no configuration option can disable. Bounded
   response sizes with size-limitable encodings only.
3. **Storage boundary** — from Cloudflare Agents: if the LLM can write SQL, a
   policy enforced in the same database is a convention rather than a control.

All three are required. A sandbox that isolates the process but lets a tool read
IMDS has not isolated anything that matters.

## Evidence log

Append one row per project as evidence lands. Keep the reasoning, not just the verdict.

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | neutral | `libs/langgraph/langgraph/pregel/main.py @ 3803173` | No sandbox at all; nodes run in the host process. Zero evidence either way. |
| OpenHands | confirms | `openhands-sdk/.../workspace/base.py:27,261 @ 760eea2` | Direct precedent: five providers (Local, Docker, Apptainer, RemoteAPI, Cloud) behind one ABC. Apptainer proves the abstraction is load-bearing. Negative lesson: optional capabilities signalled by NotImplementedError with no query method, and LocalWorkspace.pause() silently no-ops. Isolation is thin - only --ulimit nofile, no CPU/memory/pid quota. |
| Letta | amends | `src/sandbox/availability.ts:7-45 @ 852ca24`; `src/sandbox/{bwrap,seatbelt}.ts @ 852ca24` | Sandbox providers should include KERNEL-LEVEL backends (bwrap user namespaces, macOS Seatbelt), not only containers — a different and lighter bet than OpenHands. The interface should report availability with a reason rather than throwing on use. But filesystem confinement without CPU/memory/pid quotas leaves S9 unanswered, same gap as OpenHands. |
| Google AX | confirms | `internal/ate/client.go @ b777313`; `internal/config/config.go:95-97` | Delegates isolation entirely to SubstrATE, an external actor system, and lets users supply their own `ActorTemplate` and container image. A provider interface rather than an implementation, arrived at independently. AX implements no isolation itself. |
| Omnigent | confirms | `omnigent/sandbox/ @ ba9e371`; `omnigent/inner/egress/proxy.py` | **Most pluggable sandbox layer in the study**: bwrap (Linux) and seatbelt (macOS) locally, ten cloud providers (Modal, Daytona, Blaxel, Islo, E2B, CoreWeave, Kubernetes, OpenShell, Boxlite, Databricks), and a mandatory L7 egress MITM proxy with an allow-list. Unlike Google AX it ships local implementations as well as the provider interface. |
| Cloudflare Agents | challenges | `design/rfc-sub-agents.md @ 2f957bc` | No pluggable sandbox provider, because the Durable Object *is* the isolate — the only project where the agent runtime is itself the isolation unit. The insight worth keeping is sharper than the challenge: a child DO's private SQLite makes a policy **structural** rather than conventional, because otherwise "the LLM can bypass the queue by writing SQL" and enforcement degrades to "a convention (*don't call `this.sql` directly*)". **Our sandbox interface should therefore also be a storage boundary, not only a process boundary.** |
| AG2 | neutral | `ag2/ @ 90f490a` | No sandbox or isolation model at all; code execution is treated as a tool concern. |
| Pydantic AI | amends | `pydantic_ai_slim/pydantic_ai/_ssrf.py:98-120 @ b48ee38` | **Adds a threat this ADR does not mention.** No process sandbox, but `_ssrf.py` is *egress* sandboxing and it identifies the hazard directly: **an agent that fetches URLs is an SSRF primitive aimed at your own infrastructure and your cloud credential endpoints.** Cloud metadata is "always blocked, **even with `allow_local=True`**", enumerating AWS IMDS, **AWS ECS task IAM role credentials**, **AWS EKS Pod Identity**, Azure WireServer (a *public* IP no private-range check would catch), Alibaba, Oracle, Scaleway, plus IPv6 and Teredo-obfuscated forms. Also a decompression-bomb defence: `Accept-Encoding` restricted to `identity, gzip` because brotli/zstd "can expand a few compressed bytes into multi-MiB output in one decoder step". **The principle to adopt: an escape hatch must be scoped so it cannot open the worst hole.** |
| Google Agent Platform | confirms | `src/google/adk/code_executors/ @ 85b52f6` | **Widest range of shipped implementations in the study:** `BaseCodeExecutor` with container, GKE, Vertex AI, Agent Engine sandbox, model-native built-in, and `unsafe_local_code_executor`. **Naming the dangerous one `unsafe_local` is itself a design decision worth copying** — it cannot be selected without reading the word "unsafe", the same instinct as Cloudflare refusing to ship an in-memory WebSocket mode. Also `_restricted_pickle.py`, an allow-listed unpickler treating session-state deserialization as an attack surface. **Gap: no egress guard**, and ADK ships web-fetching tools, so the SSRF hazard Pydantic AI closes is open here. Our three boundaries — process, egress, storage — are each best-answered by a different project. |
| HumanLayer | neutral | `hld/session/manager.go @ 99abe67` | No sandbox at all — Claude Code runs with daemon privileges, and *approval* is the control instead of isolation. A coherent single-user choice, and a reminder that HITL and sandboxing are alternative answers to the same risk. |

## Open questions

-
