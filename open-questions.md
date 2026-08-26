# Open Questions

Anything that would otherwise become "we'll figure it out later." Every entry
needs an owner and a decide-by date. This register is what stops the exit
criteria being silently dodged.

Rules:
- A `verdict: unknown` on a deep project belongs here.
- An unresolved conflict between two projects' designs belongs here.
- Closing an entry means linking the ADR or document that resolved it.

## Status key

`open` · `investigating` · `resolved` · `deferred` (with a reason and a revisit date)

---

## Register

| ID | Question | Raised by | Owner | Decide by | Status | Resolution |
|---|---|---|---|---|---|---|
| OQ-001 | Does the LLM gateway (`freellm.kaapibyte.com`) have a durable provider-key configuration, or will availability keep flapping? First probe returned `no_providers_configured`, second succeeded. Affects any tooling that depends on it. | Phase 0 setup | | | open | Non-blocking: no teardown claim may come from a model. |
| OQ-002 | Several shortlist projects may be announcement-only with no readable source. Need substitutes that answer the same architectural question. | Phase 0 planning | | 2026-08-26 | resolved | Phase 1 recon: Google AX (`google/ax`) and Omnigent (`omnigent-ai/omnigent`) are both class A and highly relevant. GroupMind and Agent Control could not be located — downgraded to `recon`, questions reassigned in `synthesis/recon.md`. |
| OQ-003 | G-section (human-agent workspace) had the thinnest expected evidence after GroupMind could not be located. | Phase 1 recon | | Phase 5 | **partly resolved** | Letta supplies far more than expected: Slack/Discord/Telegram channels with allowed/admin user lists, `dm\|group` scope, `allow\|deny\|pair` access decisions, per-channel permission modes, mention-only mode, thread context, and durable approvals delivered to whichever channel the human is on. G-section now has a strong primary source. Still worth confirming with Omnigent's session sharing. |
| OQ-004 | Letta's source moved to `letta-ai/letta-code`; is the memory architecture still inspectable or has it moved behind Letta Cloud? | Phase 1 recon | | Phase 2 | **resolved** | Fully inspectable, and better than the V1 block store would have been: memory is a git-backed markdown filesystem with kernel-enforced per-agent isolation. Produced the first `first_class` H4 in the study. ADR-0008 confirmed strongly. |
| OQ-005 | Four projects (LangGraph/LangSmith, Letta, AWS AgentCore, Google Agent Platform) keep their control plane closed — exactly the layer we intend to build. Prior art for identity, hosted memory, multi-tenancy and observability backends is thin across the whole study. | Phase 1 recon | | Phase 5 | open | Structural limit of the exercise. Weight Google AX and Omnigent more heavily; both keep their control plane open. |
| OQ-006 | `web_search` / `web_fetch` were unavailable during recon (no local Ollama) and the GitHub search API was IP-rate-limited, so recon relied on direct repo-path probing. A project could have been missed. | Phase 1 recon | | Phase 2 | resolved | **Re-checked 2026-08-26 via npm + PyPI registries.** Agent Control located at `agentcontrol/agent-control` (Apache-2.0, 299★) and restored to `targeted`. GroupMind confirmed absent across GitHub, npm and PyPI. Lesson: package registries beat GitHub search for discovery, since they carry the canonical repo URL. |
| OQ-007 | Does LangGraph Platform add definition-version pinning on resume, or does it inherit the silent work-loss hazard proven in OSS (renamed node → resume returns empty, no error)? Platform is closed source. | LangGraph teardown | | Phase 5 | open | Docs review only; class B evidence at best. Relates to ADR-0011. |
| OQ-008 | What lease/heartbeat mechanism does LangGraph Platform use to detect lost workers, and how does it recover their runs? Closed source, so `C8` stayed `unknown`. | LangGraph teardown | | Phase 5 | open | Look for the same answer in Google AX (`single-writer` + event log) where it is open. |
| OQ-009 | Is there any accepted pattern for side-effect idempotency across a node-level resume boundary, or is developer discipline the entire answer? LangGraph re-executes a whole node on resume, so any effect before an `interrupt()` runs twice (verified). | LangGraph teardown | | Phase 5 | open | Our own answer likely needs a durable effect-ledger keyed on the deterministic task id. Check how OpenHands and Google AX handle it. |
| OQ-007 | Does LangGraph Platform add definition-version pinning on resume, or does it inherit the silent work-loss hazard proven in OSS (renamed node → resume returns empty, no error)? Platform is closed source. | LangGraph teardown | | Phase 5 | open | Docs review only; class B evidence at best. Relates to ADR-0011. |
| OQ-008 | What lease/heartbeat mechanism does LangGraph Platform use to detect lost workers? Closed source, so `C8` stayed `unknown`. | LangGraph teardown | | Phase 5 | **partly resolved** | Letta answers the general question well: `SchedulerOwner` with pid + token + `process_start_ticks` + `boot_id` detects stale ownership across PID reuse and reboot (`src/cron/cron-file.ts:45-52 @ 852ca24`). Adopt that pattern; LangGraph's specific mechanism remains unknown. |
| OQ-009 | Is there any accepted pattern for side-effect idempotency across a resume boundary, or is developer discipline the entire answer? LangGraph re-executes a whole node, so an effect before `interrupt()` runs twice (verified). | LangGraph teardown | | Phase 5 | open | **Three for three: none of the deep projects has an idempotency key on tool calls.** Our answer likely needs a durable effect-ledger keyed on a deterministic task id. Check Google AX (single-writer + event log) and Cloudflare Agents. |
| OQ-010 | Does the OpenHands agent-server define crash-recovery semantics for a conversation interrupted mid-action, or is the event log the only contract? | OpenHands teardown | | Phase 3 | open | `C5` left `unknown` for both OpenHands and Letta. |
| OQ-011 | How does OpenHands Cloud enforce the quotas the OSS Docker workspace lacks (no CPU/memory/pid limits)? Closed. | OpenHands teardown | | Phase 5 | open | Relevant to S9, which is unanswered in all three deep projects. |
| OQ-012 | Is ACP's stdio transport sufficient for a genuinely remote agent, or does it force co-location of adapter and agent? Determines whether our A2A adapter and ACP adapter can share a code path. | OpenHands teardown | | Phase 3 | open | Check against Google AX (distributed harness runtime) and Omnigent (meta-harness). |
| OQ-013 | Does Letta Cloud add agent versioning and revocation, or are they absent end-to-end? **No deep project has either**, so `AgentVersion` and the revocation lifecycle in our domain model currently lack any precedent. | Letta teardown | | Phase 3 | open | Highest-priority gap for Phase 3. Watch Cloudflare Agents (durable actors) and Google AX (`manifests/`). |
| OQ-014 | How does git-backed memory behave at scale — repository growth, history rewriting, conflict frequency under unattended operation? | Letta teardown | | Phase 5 | open | Affects whether we borrow the pattern or only the ideas. |
| OQ-015 | Is Letta's `pair` (pending sender authorisation) durable across restart like `PendingControlRequest`, or in-memory only? | Letta teardown | | Phase 3 | open | Minor, but the pattern is one we want to copy. |
| OQ-016 | **S9 (runaway spend) is `undefined` or partial in all three deep projects.** None has a hard cost ceiling; the best available are goal-loop `capped` status (OpenHands) and subagent context budgets (Letta). No infrastructure-level quota anywhere. | Phase 2 synthesis | | Phase 5 | open | Likely a genuine differentiation opportunity. Budget enforcement may need to be a control-plane concern rather than a runtime one. |

---

## Deferred with intent

Things consciously not decided in v0.1, recorded so they are not mistaken for
oversights.

| ID | Deferred | Why | Revisit when |
|---|---|---|---|
| | | | |
