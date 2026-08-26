# Phase 2 — Cross-Anchor Findings

Three deep teardowns complete: **LangGraph**, **OpenHands**, **Letta**. Chosen for
maximum divergence so the strawman would be stressed rather than confirmed.

All three at 99.4% probe coverage. One `unknown` each, all tracked in
`open-questions.md`.

| | LangGraph | OpenHands | Letta |
|---|---|---|---|
| Runtime class | in-process lib + worker queue | attached harness | durable actor |
| Core bet | Pregel super-steps over versioned channels | control plane owns workspace/log/policy, agent is a subprocess | agent is durable, memory is a git filesystem |
| Durability | snapshot checkpoints, 3 timing modes | event-sourced tree | git commits + lease-owned scheduler |
| Verdict | INTEGRATE | INTEGRATE | REFERENCE_ONLY |

## 1. The universal gaps

Sixteen probes are `absent` or `undefined` in **all three**. These are where the
study offers no prior art, and therefore where we are either differentiating or
about to repeat someone's unsolved problem.

| Probe | Gap |
|---|---|
| `A4` | Task separate from Run — **no project has it** |
| `C6` | Idempotency model for tool side effects |
| `C12` | Definition upgrade while runs in flight |
| `D9` | Agent suspend / revoke / deprecate |
| `F1` `F2` `F5` `F6` `F8` `F11` | **The entire agent-to-agent messaging section** |
| `J6` | Agent acting as a user (impersonation vs delegation) |
| `J7` | Tenant isolation |
| `L8` | Compensation / rollback |
| `N3` | Quotas and cost limits |

`Q3`/`Q5` are also universal but trivially so — all three are permissively
licensed with no copyleft.

### The F-section result is the most significant finding of Phase 2

Six consecutive probes on agent-to-agent communication return `absent` across
three mature, popular, architecturally dissimilar projects. Not partial, not
implicit — absent.

What each does instead:

- **LangGraph**: multi-agent = multiple nodes in one graph sharing mutable channel
  state. No delivery guarantee, no ordering beyond super-step sequencing, no
  correlation.
- **OpenHands**: delegation = a nested sub-agent conversation inside the parent's
  tool span. Synchronous, no mailbox.
- **Letta**: delegation = spawning a subagent *process* with `{self, parent}`
  memory scope. Channels exist but carry **humans**, not agents.

Two readings, and they have opposite implications:

1. **Opportunity.** Durable agent messaging is genuinely unbuilt, and ADR-0003 is
   proposing something with no competition.
2. **Warning.** Three teams independently found nested/synchronous delegation
   sufficient. Perhaps durable inter-agent messaging is a solution to a problem
   real users do not yet have.

The evidence cannot distinguish these. What it does establish is that ADR-0003
must justify itself from *our* requirements, not from precedent — there is none.
Google AX (distributed harness runtime) and AG2 (whose entire thesis is
multi-agent conversation) are the Phase 3 projects that will resolve this. If AG2
also lacks durable messaging, reading 1 weakens considerably.

Letta's split additionally suggests a domain-model correction: **human
collaboration channels and agent transport may be different resources.** Letta
built the first properly and never needed the second.

## 2. The universal strengths

Thirty-four probes are `first_class` in all three. The consensus is worth stating
because it defines the table stakes:

- **Durable execution with replay** (`C1`, `C3`, `M8`) — all three, three different
  mechanisms (snapshots, event tree, git).
- **Durable HITL** (`C11`, `G5`, `G6`, `G10`) — approvals survive restart, humans can
  intervene mid-run and inspect agent context, in all three. This is solved.
- **Observable tool calls and event streams** (`E4`, `E5`).
- **First-class subagents and dynamic spawning** (`L4`, `L6`).
- **Policy enforced somewhere explicit** (`J10`).
- **Testability** (`R5`) — all three invested in it.

Anything on that list is not a differentiator. Shipping it is necessary; shipping
it *well* is not a story.

## 3. What changed in the ADRs

| ADR | Trajectory | Outcome |
|---|---|---|
| 0001 Agent is persistent | challenged ×2, then **confirmed** | Rationale rebased on delegation/policy/audit. Ready to promote. |
| 0002 Task ≠ Run | confirmed ×3 | No project has the split; all three suffer for it. Amended with `CANCELLING` and `STUCK`. |
| 0003 Durable messages | confirmed ×2, **amended** ×1 | No precedent at all. Must justify from requirements. Split human channels from agent transport. |
| 0004 Adapter-based runtime | confirmed ×2, amended ×1 | OpenHands proves it works. Tool-name canonicalisation is a prerequisite, not an afterthought. |
| 0005 MCP is protocol | confirmed ×1, neutral ×2 | OpenHands validates the split exactly. |
| 0006 A2A is interop | neutral ×3 | No evidence either way. ACP is the live adapter protocol, not A2A. |
| 0007 Humans and agents are principals | confirmed ×3 | Letta gives two genuinely different principal mechanisms. |
| 0008 Memory is not one thing | confirmed ×2, amended ×1 | Letta is decisive. Separate by *residency cost* and *ownership*. |
| 0009 Sandbox is pluggable | confirmed ×2, amended ×1 | Add kernel-level backends. Report availability, don't throw. |
| 0010 OTel is canonical | confirmed ×3 | **Zero OTel in any project.** Industry-wide gap. |
| 0011 Version-pinned checkpoints | raised, confirmed ×3 | Nobody pins. Verified silent work loss in LangGraph. |
| 0012 Declared capabilities | raised, confirmed ×2 | Letta's `SandboxAvailability` is the reference implementation. |
| 0013 Traced, shadow-comparable policy | raised ×1 | Only Letta treats policy evolution as a design problem. |

Thirteen ADRs, three of which did not exist before the evidence. That ratio is
roughly what the falsification-pass design was meant to produce.

### ADR-0001's arc is the methodological result

It was challenged by LangGraph (40k stars, no agent identity, successful),
challenged again by OpenHands (agent is a *kind* plus a launch command), then
confirmed by Letta on completely different grounds than originally written.

The original rationale — durable identity makes registry, delegation, policy and
audit coherent — bundled four claims. Two projects showed durability needs none of
them. Letta showed that the moment you need *delegated authority*, you need
identity: `AGENT_ID` decides which memory tree a process may touch, kernel
enforced, and a subagent's authority is exactly `{self, parent}`.

Letta is also the only project where S1 is answerable at all. The correlation is
the argument: identity is required for delegation, not for durability.

## 4. Three designs for one problem: capability signalling

All three projects have pluggable backends with optional operations. Each solved
the "does this implementation support X?" question differently, and the
comparison produced ADR-0012.

| Project | Mechanism | Assessment |
|---|---|---|
| LangGraph | `Capability` enum split BASE/EXTENDED, detected by method-override check, conformance tests gated on detected set | Good. Declarative and verified. |
| OpenHands | `NotImplementedError` from base class; **no query method**; `LocalWorkspace.pause()` silently no-ops | Bad. Verified: a false success. |
| Letta | `SandboxAvailability { backend \| null, reason }` from a **real user-namespace mount probe**; dependent code fails closed | Best. Distinguishes unavailable from unknown, explains which, refuses to degrade. |

OpenHands is instructive twice over: its *manifest* layer states the correct
principle explicitly — "'unknown' is a real outcome, not an error: a deployment
that cannot be asked must not be treated as one that answered no" — while its
*workspace* layer violates it. Getting it right and wrong in one codebase is
evidence the failure is easy.

## 5. Verified behaviours

Findings from execution rather than reading. These are the highest-confidence
items in the study.

| Scenario | Project | Result |
|---|---|---|
| S2 torn side effect | LangGraph | Side effect ran **twice** (`['EFFECT']` → `['EFFECT','EFFECT']`). At-least-once at node granularity. |
| S3 upgrade mid-flight | LangGraph | Same-topology change silently runs new code. **Renamed node → resume returns `[]` with no error**; pending work discarded. |
| S5 cancellation | LangGraph | No cancel token in sync path; abandoned invoke leaves worker running, task pending. |
| G5 approval policy | OpenHands | `ConfirmRisky` **fail-safe on UNKNOWN**; `threshold=UNKNOWN` rejected by validator. |
| K9 capability query | OpenHands | **Zero** capability-query attributes; `LocalWorkspace.pause()` returns success as a no-op. |
| D1/D5 agent registry | Letta | `letta agents list` with fuzzy query, tag filters (ANY/ALL), and `--shared`. |
| H1/H5 memory contract | Letta | Git-backed; `system/` always resident; `reason` required on every mutation. |

## 6. Ideas worth stealing, ranked

1. **Letta's `SandboxAvailability{backend\|null, reason}` + fail-closed** — the
   ADR-0012 reference implementation.
2. **LangGraph's conformance suite** — BASE/EXTENDED with spec tests gated on
   declared capabilities. Combine with 1.
3. **Letta's git-backed memory** — provenance, audit, diff, revert and conflict
   detection free from the substrate. Only `first_class` H4 in the study.
4. **OpenHands' pause vs interrupt** — two grades of stop, both durable and
   resumable, semantics documented at the endpoint.
5. **Letta's `SchedulerOwner`** with `process_start_ticks` + `boot_id` — lease
   liveness that survives PID reuse and host reboot.
6. **LangGraph's durability modes** (`sync|async|exit`) — name the tradeoff, let
   the caller choose.
7. **Letta's unbypassable policy floor at decision step 0**, beneath configurable
   modes and rules.
8. **Letta's `PermissionShadowComparison`** — basis for ADR-0013.
9. **OpenHands' `ConfirmRisky(confirm_unknown=True)`** with a validator forbidding
   an incoherent threshold.
10. **LangGraph's deterministic task IDs** hashed from checkpoint + namespace +
    step, with a checksum assertion.
11. **Letta's `system/` vs referenced memory** as a context-budget cost model.
12. **Letta's nine named cron run reasons** — `started_too_late`, `queue_full`,
    `runtime_unavailable`.
13. **OpenHands' `STUCK` status** — running but not progressing.
14. **LangGraph's `MultitaskStrategy`** — `reject|interrupt|rollback|enqueue`.
15. **Letta's `allow|deny|pair`** — a pending-authorisation state.

## 7. Anti-patterns to avoid

1. **A no-op that reports success** (OpenHands `LocalWorkspace.pause()`).
2. **Silent resume onto a changed definition** (all three; LangGraph verified to
   lose work outright).
3. **Node/step-granularity resume with side effects inside the unit** (LangGraph);
   the docs treat a double-charge risk as a footnote.
4. **Namespaces that look like an isolation boundary but carry no permissions**
   (LangGraph's Store).
5. **Proprietary telemetry** (all three) — locks observability behind a product.
6. **Defaulting to the least confined mode** (Letta's `unrestricted`, plus opt-in
   shell confinement).
7. **Security boundaries with probabilistic inputs** (OpenHands' LLM-predicted
   risk) — defensible only with a fail-safe default.
8. **Parsing shell commands to enforce policy** — Letta tried, documented why it
   failed (symlinks, command substitution, globbing, subprocesses), moved to the
   kernel.

## 8. What Phase 3 must resolve

Ordered by how much they affect the design.

1. **Agent versioning and revocation** (`D4`, `D9`) — no precedent in any of the
   three. `AgentVersion` and the revocation lifecycle are currently unjustified
   nodes in the domain model. → Cloudflare Agents, Google AX `manifests/`.
   (OQ-013)
2. **Durable agent-to-agent messaging** (F-section) — zero precedent. → AG2
   (multi-agent is its whole thesis), Google AX, Microsoft Agent Framework.
3. **Task vs Run** (`A4`) — no project separates them. → Google AX, Google Agent
   Platform.
4. **Side-effect idempotency** (`C6`) — nobody has a key. → Google AX
   (single-writer + event log), Cloudflare Agents.
5. **Tenant isolation** (`J7`) and **quotas** (`N3`) — absent everywhere OSS. →
   AWS AgentCore, Google Agent Platform (both class B).
6. **Runaway spend** (S9) — no hard ceiling anywhere. (OQ-016)
7. **Remote adapter transport** — is ACP stdio sufficient for a remote agent? →
   Google AX, Omnigent. (OQ-012)

Phase 3 order stands as planned, with **Google AX and Omnigent first**: AX
addresses gaps 1, 3, 4 and 7, and Omnigent is the closest existing analogue to our
own design and therefore the most important falsification target.
