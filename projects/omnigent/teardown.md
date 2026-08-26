# Teardown — Omnigent

| | |
|---|---|
| Repo | https://github.com/omnigent-ai/omnigent |
| Commit read | `ba9e371464695018c8362967a6c23e8725f0cc8c` (2026-08-26) |
| Version tested | `omnigent 0.11.0` (built 2026-08-25), from PyPI |
| License | Apache-2.0 |
| Read on | 2026-08-26 |
| Evidence class | A |
| Depth | deep |
| Runtime class | `meta_harness` — a control plane over other people's agents |

Read against the Phase 2 strawman. Omnigent was second in the Phase 3 order
because it is the closest analogue to the platform this study exists to design:
its stated purpose is "a common orchestration layer over Claude Code, Codex,
Cursor, OpenCode, Hermes, Pi, and the agents you write yourself" (`README.md`).
It is therefore the most dangerous project to read (anchoring risk) and the most
useful (it has already hit the problems our ADRs predict).

**It closes seven gaps that were universal across the first five projects.** That
is by far the largest contribution of any single project in this study.

---

## 1. What problem it solves

Harness lock-in. Every coding agent (Claude Code, Codex, Cursor, OpenCode) ships
its own session model, approval surface, resume semantics, and auth. Omnigent
puts one orchestration, policy, and collaboration layer above all of them so a
session can move between harnesses, devices, and humans without rewriting the
agent.

Its second problem is *supervision*: multi-device access (terminal, browser,
phone, native desktop), shared sessions, and policy enforcement over agents the
platform did not write.

## 2. Core architectural thesis

**The harness is a driver, not the system. Declare what each driver can do, then
verify the declaration against live behaviour.**

Omnigent's differentiator is not that it adapts many harnesses — several projects
do — but that it treats harness heterogeneity as a *data* problem with a
*conformance* answer:

1. Every harness declares capabilities in a frozen dataclass
   (`omnigent/harness_capabilities.py`).
2. A bench probes the real behaviour live (`tests/harness_bench/`).
3. `reconcile()` compares the two and reports **DRIFT** when a harness's public
   claim is false (`tests/harness_bench/bench.py:44-66`).

That closes the loop my ADR-0012 only opened. See §11.

## 3. Resource / object model

The richest domain model in the study, and the only one with tenancy in the
primary key.

```text
Workspace (workspace_id)          tenant partition; part of EVERY composite PK
 ├── User / Account
 │    └── DeviceGrant             RFC 8628 delegated auth, revocable
 ├── Project                      first-class grouping of sessions
 ├── Agent                        id, name, bundle_location, VERSION (monotonic)
 ├── Policy                       scope: "default" (server) | "session"
 ├── Host                         a connected machine that can run sessions
 ├── ScheduledTask                name, prompt, rrule, timezone, state,
 │    │                           max_cost_usd, host_id
 │    └── ScheduledTaskRun        status, scheduled_at, fired_at, finished_at,
 │                                error, error_code, → conversation_id
 └── Conversation                 the session; parent/root ids for sub-agents
      ├── ConversationItem        the transcript (append)
      ├── ConversationLabel       session-scoped guardrail labels
      ├── SessionPermission       (user_id, conversation_id, level)
      └── Comment                 human review note anchored to a file range
```

Three things here are unique in the study:

- **`Agent.version` is a monotonic counter**, incremented on every bundle update
  (`omnigent/stores/agent_store/sqlalchemy_store.py:300`). First agent versioning
  found anywhere (see §7).
- **`ScheduledTask` and `ScheduledTaskRun` are separate tables**
  (`omnigent/db/db_models.py:1434,1546`). First real Task/Run separation (see §5).
- **`workspace_id` is part of every composite primary key**, defaulted from a
  `ContextVar` (`db_models.py:216-238`). First real tenant isolation (see §16).

## 4. Runtime model

A four-tier distributed system: **client → server → host daemon → runner
(harness subprocess)**.

The `IntegrationMode` enum names all five ways Omnigent drives a vendor agent
(`harness_capabilities.py:24-31`), which is the clearest statement of the adapter
problem I have found:

```text
SDK_IN_PROCESS   vendor SDK inside the harness subprocess
CLI_SUBPROCESS   drives a vendor CLI per turn
ACP_SUBPROCESS   vendor CLI in Agent Client Protocol mode
NATIVE_TUI       wraps a resident vendor TUI (tmux / file-inject)
NATIVE_SERVER    runner-owned vendor server + HTTP/SSE bridge
```

`NATIVE_TUI` is worth pausing on: Omnigent will screen-scrape a terminal UI and
mirror its approval pane to the web (`Elicitation.APPROVAL_MIRROR`) to bring a
harness with no API under one policy layer. That is a pragmatic answer to "adapt
an agent that offers no integration surface at all", and something my strawman
did not contemplate.

Sessions are pinned to a `host_id`/`runner_id`, so unlike Google AX work does not
float to any worker. Hosts may be user machines or server-provisioned cloud
sandboxes ("managed hosts").

## 5. Execution lifecycle

**First genuine Task/Run separation in the study** — the `A4` gap that was absent
in all five prior projects.

`ScheduledTask` is the durable *intent*: a prompt, an RFC 5545 `rrule`, a
timezone, a lifecycle `state` (`active | paused | ...`), a bound `agent_id`, and a
per-firing `max_cost_usd`. `ScheduledTaskRun` is one *attempt*, with its own
status (`scheduled | running | succeeded | failed | skipped`), `scheduled_at`,
`fired_at`, `finished_at`, an `error` blob, and — notably — a queryable
`error_code` "for future retry logic" (`db_models.py:1573-1575`).

So the intent survives failed attempts, and the attempt records why it failed in
a form a scheduler can branch on. That is exactly the shape ADR-0002 argues for.

The honest caveat: this separation exists **only for scheduled work**. An
interactive session is still a `Conversation` with turns, so Task/Run is not a
universal spine. But it is proof the split is implementable and useful, which is
more than any prior project offered.

## 6. Durability model

Persistence is a relational store (SQLAlchemy, SQLite or Postgres, Alembic
migrations) rather than an event log. `ConversationItem` rows are the transcript
and are appended.

Resume is per-harness and declared, which is the most honest treatment of
resumption in the study (`harness_capabilities.py:40-45`):

```text
Resume.NONE            prior conversations cannot be resumed
Resume.WARM_REATTACH   reattach to a live vendor session / terminal
Resume.COLD_ONLY       rebuild from Omnigent transcript / history replay
```

Rather than pretending all harnesses resume alike, Omnigent names the three real
behaviours and lets the platform branch. `ForkHistory` does the same for forking
(`none | rebuild | preamble`).

**Concurrency is handled with a documented fix for a real bug.** Usage deltas are
applied under `SELECT FOR UPDATE` on Postgres and `BEGIN IMMEDIATE` on SQLite,
because a plain deferred `SELECT`-then-`UPDATE` raises `SQLITE_BUSY_SNAPSHOT`
under concurrent writers — the race "that caused concurrent relay completions to
silently drop each other's cost / token deltas (#9)"
(`stores/conversation_store/__init__.py:1035-1049`). A codebase that cites the
bug number for its own lost-update race is one that actually hit it.

## 7. Agent identity and lifecycle

**First agent versioning in the study.** `Agent` carries a monotonic `version`,
starting at 1 and incremented whenever the bundle is replaced
(`agent_store/sqlalchemy_store.py:300`). Agents are stored as content-addressed
tarballs (`bundle_location`), so a version corresponds to an immutable artifact.

`Agent.session_id` distinguishes **template agents** (reusable, `session_id=None`)
from **session-scoped agents** created inline by a multipart `POST /v1/sessions`.
That is a distinction our domain model lacked and needs.

Two limits, recorded precisely because the probe is otherwise a rare
`first_class`:

- **A conversation does not pin the agent version it started on.** I searched
  `entities/conversation.py` for a version field and found none. So `version` is a
  change counter and audit aid, not a resumption guard — the ADR-0011 problem
  remains open even here. Google AX pins harness identity; Omnigent versions the
  agent; **nobody does both.**
- **`delete()` is a hard delete**, not a revocation or deprecation lifecycle
  (`agent_store/sqlalchemy_store.py:308-320`). `D9` stays absent.

`DeviceGrant` *does* have a real lifecycle (`pending | approved | denied | ...`)
with revocation enforced on every request (`server/auth.py`,
`set_grant_revocation_check`), so Omnigent has revocation for *delegated
credentials* but not for *agents*.

## 8. Multi-agent communication

**Absent — six for six.** This is now the single most robust negative finding in
the study.

Omnigent has sub-agents (`Conversation.parent_conversation_id`,
`root_conversation_id`, `kind="sub_agent"`) and a sophisticated routing gate for
spawning them, but no agent-to-agent messaging: no mailbox, no channels, no
addressing, no inter-agent RPC. Agents relate through *parentage and shared
session state*, never by sending each other messages.

`comments.py:send_to_agent` looked like a counterexample; it is not. A `Comment`
is a human review note anchored to a file range (`path`, `start_index`,
`end_index`, `anchor_content`) that gets formatted into a chat message for a
person to send. Human→agent, not agent→agent.

The **subagent routing gate** is the interesting design here
(`runner/subagent_routing.py`). A harness `PreToolUse` hook calls back to ask
which model a spawn should use, the decision is persisted as a
`routing_decision` transcript item, and the gate is **deliberately advisory**:
every transport failure, unreachable endpoint, unparseable verdict or timeout
allows the spawn unchanged, "because a spawn that dies on routing infrastructure
is worse than a spawn on the inherited model."

And the reason that gate works is a rule I had not seen stated anywhere:

> **Timeout budget.** Four hops wait on each other, so each one's budget is
> strictly larger than the hop it waits on — otherwise an inner hop's fail-open
> branch can never run.

12s → 8s → 7s → 6s → 5s, "never equal", because "a hook killed at the same
instant its request gives up never reaches its fail-open branch." Any layered
fail-open design needs this rule, and ours will have layered fail-open.

## 9. Human interaction model

The strongest in the study, and the only one built for more than one human.

- **Permissions**: `SessionPermission(user_id, conversation_id, level)` with
  numeric levels (read / edit / owner) plus a `"__public__"` sentinel grant for
  link sharing, resolved into `ResolvedAccess{is_admin, user_grant_level,
  public_grant_level}`.
- **Multi-device continuity**: the same session is driven from terminal, browser,
  phone, or a native macOS app.
- **Collaboration**: share a session so teammates chat with a running agent,
  co-drive it, or fork the conversation.
- **Elicitation is a declared capability**, naming five distinct approval
  surfaces (`NONE | HOOK | JSONRPC | APPROVAL_MIRROR | SSE_PERMISSION`). Omnigent
  accepts that approval plumbing differs per harness and models the difference
  rather than hiding it.
- **Comments**: file-range-anchored review notes with `draft | addressed` status —
  a code-review interaction that no other project has.

## 10. Context and memory

No memory subsystem. Knowledge is **skills as directories** inside the agent
image (`skills/<dir>/SKILL.md`), plus `AGENTS.md` for instructions
(`omnigent/spec/AGENTSPEC.md`).

**Fourth consecutive project to choose filesystem/git-backed skills over a memory
store.** With Letta, OpenHands, and Google AX this is now the strongest positive
convergence in the study, and I consider the question settled for v0.1.

`compaction` exists as a capability *axis* but is `None` (no claim) for all 26
harnesses — see §11.

## 11. Tools and capabilities

This is why Omnigent was worth 2.5 days.

`HarnessCapabilities` is a frozen dataclass with **16 fields** across typed enums
and tri-state booleans (`omnigent/harness_capabilities.py:124-141`). The module
docstring states the problem exactly as my strawman did:

> A harness's feature support was previously implicit — scattered across
> `if harness == "x"` branches and the presence/absence of companion modules...
> This module gives it one declared shape so the registry can answer "what can
> this harness do?" directly.

Verified live against 0.11.0:

```text
harnesses declared: 26
capability axes: 16
integration modes: sdk-in-process, cli-subprocess, acp-subprocess,
                   native-tui, native-server
```

Three design points worth adopting:

**1. `None` means "makes no claim", and is reported as UNKNOWN — not as
unsupported.** From the docstring: "Optional capability fields use `None` when the
harness makes no claim; the bench reports those declarations as `UNKNOWN` rather
than assuming the capability is unsupported." That is precisely the
`absent` ≠ `unknown` discipline this study runs on, implemented in a capability
model. Nobody else does this.

**2. Declared claims are verified by an executable bench.** `reconcile()` compares
declared against live-probed and emits **DRIFT** when they disagree, so "a DRIFT
now means *a harness's capability declaration is false*", making the table
"self-enforcing (you can't lie in `_BUILTIN_CAPABILITIES` without the bench
catching it on the next live run)"
(`designs/harness-capabilities-bench-seam.md`).

**3. Confidence is tracked explicitly.** Only four P0 harnesses have
`interrupt`/`streaming` verified live; "the other 19 harnesses' values are
declared best-effort by integration mode, not yet probe-verified... the bench
wiring must not treat those 19 as ground truth." A capability model that
distinguishes *verified* from *asserted* is a genuinely new idea for me.

There is a caution against over-deriving, too: don't equate `policy_deny` with
`elicitation`, because "policy DENY is enforcement, elicitation is the ASK
surface." And a rule learned from being wrong: declare `streaming=False` only from
a live observation of zero deltas, because a static grep for a delta-posting
forwarder gave the wrong answer for `pi-native`.

**Verified limit.** All four optional axes are unpopulated:

```text
axes left UNKNOWN (no claim): steering 26, live_queue 26, images 26, compaction 26
```

So the tri-state is designed and plumbed but not yet used. The mechanism is
proven; the data is not there. Recorded as `implicit` rather than `first_class`
for those axes.

Tools themselves: MCP declarations, local Python and TypeScript tools inside the
agent image, and a proxying MCP manager (`runner/proxy_mcp_manager.py`).

## 12. Security and IAM

The strongest security story in the study, and the sharpest contrast with Google
AX (which has none).

**Policy engine** (`omnigent/policies/`). Three actions — `ALLOW | ASK | DENY` —
evaluated per phase, with builtins for cost, safety, risk scoring, working
directory, GitHub, prompt, routing, and orchestration. Policies are Python
callables or HTTPS endpoints, scoped server-wide or per-session, and individually
`enabled`.

**Fail-closed decided per phase, with reasoning** — better than my ADR-0012
amendment written hours earlier (`policies/types.py:59-80`):

```python
FAIL_CLOSED_PHASES: tuple[str, ...] = ("PHASE_TOOL_CALL", "PHASE_REQUEST")
```

`PHASE_TOOL_CALL` fails closed because "for connector-native MCP tools the in-band
verdict is the only enforcement point — the call is never re-checked
server-side." `PHASE_REQUEST` fails closed because it is "the sole pre-turn
enforcement point." And `PHASE_TOOL_RESULT` deliberately fails **open** because
"by the time the result phase runs the tool has already executed, so failing it
closed would only block an already-incurred side effect."

That is the correct generalisation: **fail closed where the decision is the last
line of defence, fail open where the harm already happened.** My amendment split
capabilities by *category* (safety vs liveness); Omnigent splits by *position in
the enforcement path*, which is sharper. The constant is defined once so
enforcement sites "can't drift."

**Policy decisions are traceable.** `PolicyResult.deciding_policies` names every
policy that drove a composed verdict — one policy on DENY, all ASKing policies in
YAML order on ASK (`policies/types.py:244-252`). First implementation of
ADR-0013's traceability requirement. It also supports content *transformation*
(`data`), so a policy can redact PII from tool arguments and each subsequent
policy sees the previous one's output.

**Delegated authority — the first answer to S1 in the study.** RFC 8628 device
authorization grant (`designs/DEVICE_AUTH.md`, marked IMPLEMENTED) issues
scope-limited delegated tokens with revocation checked per request. Delegated
tokens fail closed against a path allow-list, and the prefix-confusion case is
handled explicitly: `/v1/hosts/h1/runners` passes, `/v1/hostsX` does not
(`server/auth.py:70-81`). Default-off (`OMNIGENT_DEVICE_GRANT_ENABLED`), and the
consent routes never mount in OIDC mode.

**Secretless credential proxy** — the best answer to `J4`/`K7` anywhere in the
study, and worth reading in full (`designs/SANDBOX_CREDENTIAL_PROXY.md`,
IMPLEMENTED). The threat model is stated plainly: injecting a real token into a
sandbox "defeats much of the point of the sandbox," because any code the agent
was tricked into running "can read the token out of `os.environ` / `~/.gitconfig`
and exfiltrate it."

The design:

1. The **parent** (unsandboxed) resolves the real secret and holds it in the
   proxy's rewrite table.
2. The mandatory L7 egress MITM proxy **injects `Authorization` on the way out**.
   The sandbox sends no credential and holds nothing to leak. `git`, `curl`,
   `python`, `node` all authenticate with zero in-sandbox wiring.
3. For clients that refuse to make a request without seeing a credential (`gh`
   short-circuits before touching the network), the parent mints a random
   single-use **placeholder** (`oa_cred_…`) and injects only that; the proxy swaps
   it for the real secret.
4. **Leak guard**: a placeholder presented for a host it is not bound to is
   rejected with 403, as is any unknown `oa_cred_*`-shaped value. Replay against
   an attacker host attaches no real credential.
5. **No clobbering**: a real `Authorization` header the client set itself is
   forwarded untouched.

I want this pattern in our platform. It is the only design in the study where a
sandboxed agent can authenticate without ever holding a secret.

## 13. Sandboxing

Local isolation via `bwrap` (Linux) and `seatbelt` (macOS)
(`omnigent/sandbox/`), plus a mandatory L7 egress proxy with an allow-list
(`omnigent/inner/egress/`). Ten cloud sandbox providers are supported (Modal,
Daytona, Blaxel, Islo, E2B, CoreWeave, Kubernetes, OpenShell, Boxlite,
Databricks), launched from the CLI or provisioned per session as managed hosts.

The most thoroughly pluggable sandbox layer in the study, and unlike AX it also
ships local implementations. Strong affirmative evidence for ADR-0009.

## 14. Orchestration

Sub-agents via `parent_conversation_id`/`root_conversation_id`, with a routing
gate deciding the spawn model. **`ScheduledTask` with an RFC 5545 `rrule`,
timezone, and lifecycle state is the first scheduled/background execution in the
study** (`B6`, `L3`) — absent in all five prior projects. Per-firing
`max_cost_usd` binds a budget to a trigger.

No DAG or graph engine, consistent with keeping workflow orchestration external.

## 15. Observability

**Second project with real OpenTelemetry, and more thorough than AX's**: OTel API
and SDK, both OTLP exporters (gRPC and HTTP), plus FastAPI, httpx, and SQLAlchemy
instrumentation (`pyproject.toml:93,145-150`). Only project instrumenting its
*database*.

`designs/OBSERVABILITY.md` is the most candid engineering document I read in this
study. It audits its own telemetry layer and lists what is broken: trace context
"never propagated over the wire," `HTTPXClientInstrumentor` "a declared
dependency but never wired," `FastAPIInstrumentor` "gated off by default,"
`get_traceparent_env()` "dead code — zero call sites," no SQLAlchemy
instrumentation. It even calls its own codebase "heavily vibe-coded" and lacking
"a clear mental map."

I verified the current state: `inject_trace_context` now has exactly two real
call sites (`host/frames.py:927`, `server/routes/sessions/routes_core.py:1267`),
so propagation is partially wired — better than the document's audit, short of
its goal.

One idea I am taking: **`trace_id_from_response_id`**
(`runtime/telemetry.py:508-540`). Response IDs are `resp_<32 hex>`, and the hex
suffix *is* the W3C trace id, so an operator jumps from a response id to its trace
by stripping a prefix — "no lookup table, no search query." Short ids are
zero-padded, preserving uniqueness. The design doc keeps this as the root
trace-id seed while moving cross-boundary continuity to real W3C propagation,
which is the right split.

## 16. Multi-tenancy

**First real tenant isolation in the study.** `workspace_id` is a `BigInteger`
**part of the composite primary key on every table**, defaulted from a
`ContextVar` (`db_models.py:216-238`):

> Defaults to `DEFAULT_WORKSPACE_ID` (0) — the single-workspace OSS deployment.
> Multi-tenant deployments set it per request so every primary-key lookup,
> filter, and insert scopes to that workspace.

`workspace_scope()` binds it for a block and "resets to the prior value on exit so
nested / concurrent contexts don't leak."

Two properties worth copying. Tenancy is in the **primary key**, not a filter
column, so a query that forgets to scope cannot silently return another tenant's
rows — it fails to find the row at all. And OSS runs as workspace 0, so the
single-tenant path is the multi-tenant path with one value, rather than a
separate code path that drifts.

Also present: `Project` as a first-class grouping (`N1`), `user_daily_cost` for
per-user spend, and `SessionPermission` levels (`N2`).

## 17. Protocols and APIs

A **72-path** OpenAPI surface (`openapi.json`), REST + SSE + WebSocket tunnels.
Speaks ACP (`ACP_SUBPROCESS`, `acp_cli_harnesses.py`) and MCP (declarations,
proxying manager). SDKs in `sdks/`, editor integrations in `editors/`, a Slack
integration in `integrations/slack/`.

`GET /v1/harnesses` publishes the capability catalog including the serialized
`capabilities` dict — capabilities are part of the **public API**, not an internal
detail. That is the northbound half of ADR-0012 and I had not planned to expose
it.

## 18. Storage

SQLAlchemy over SQLite or Postgres with Alembic migrations, stores behind
interfaces per aggregate (`agent_store`, `conversation_store`, `policy_store`,
`permission_store`, `project_store`, `scheduled_task_store`, `artifact_store`,
`file_store`, `comment_store`, `host_store`). Agent bundles are tarballs in an
artifact store. Compressed columns for opaque blobs (`CompressedText`), enums
stored as stable int codes with a codec layer.

Notable: **no database foreign keys** ("Rule R032; cascade is app-owned"). A
deliberate choice to own referential integrity in the application, presumably for
sharding and migration freedom.

## 19. Deployment architecture

Server (FastAPI), host daemon, runners, web UI (`web/`), native macOS app.
Deploys via Railway (`railway.toml`), Render (`render.yaml`), Docker (`deploy/`).
Local-first is a real mode: `omnigent run` spawns a managed local server with an
explicit single-user marker gating a "local" header-auth fallback that "deployed
multi-user servers" never set (`server/auth.py:84-88`).

## 20. OSS / license / commercial model

Apache-2.0 with a DCO and `NOTICE`. Alpha status declared. Optional harness
support ships as **separate PyPI packages** (`omnigent-kimi`) via entry points, so
`pip install omnigent` gets core harnesses only.

Verdict: **REFERENCE_ONLY, with two components worth porting**. It is Python
(matching our stack) and Apache-2.0, so embedding is legally and technically
possible, but it is a 111MB alpha product with a desktop app, web UI, and Slack
bot — far more product than platform. The **secretless credential proxy** and the
**capability + bench reconciliation** pattern are the two things I would port
directly.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | **first_class_answer** | **First answer in the study.** RFC 8628 device grant → scope-limited delegated token, path allow-list fails closed, revocation checked per request. Prefix-confusion (`/v1/hostsX`) explicitly handled. |
| S2 Torn side effect | inferable | Lost-update race found and fixed for usage deltas (`BEGIN IMMEDIATE` / `SELECT FOR UPDATE`, bug #9). Still no idempotency key on tool calls — `C6` absent six for six. |
| S3 Upgrade mid-flight | **inferable** | `Agent.version` increments on bundle update, but a conversation does not pin the version it started on, so resume does not detect the change. Versioning without pinning. |
| S4 Concurrent memory write | undefined | No memory store; `session_state` updates are ordered `StateUpdate` ops but not conflict-resolved. |
| S5 Cancellation tree | inferable | `interrupt` is a declared, bench-verified capability per harness. No documented tree propagation to sub-agent conversations. |
| S6 Silent context loss | undefined | `compaction` axis exists but is `None` (no claim) for all 26 harnesses. Designed, unpopulated. |
| S7 Poison message | **inferable** | `ScheduledTaskRun.error_code` is a queryable classification token ("timeout", "rate_limited") explicitly "for future retry logic", and `status="skipped"` exists. Closest thing to a DLQ so far; retry logic itself not implemented. |
| S8 Tenant leak | **first_class_answer** | **First answer in the study.** `workspace_id` in every composite PK, bound per request by `ContextVar`, reset on scope exit so concurrent contexts cannot leak. An unscoped query fails to find rows rather than returning another tenant's. |
| S9 Runaway spend | **first_class_answer** | **First answer in the study.** `cost_budget` builtin policy: soft `ask_thresholds_usd` checkpoints (approve to continue), hard `max_cost_usd` acting as a model-downgrade gate, per-user `user_daily_cost`, per-firing `max_cost_usd` on scheduled tasks. Fails closed when usage is present but unpriced, so unpriced models cannot bypass the cap. Honest limit documented: "a single very expensive turn can still overshoot before the next check." |
| S10 Zombie sandbox | inferable | Suspend/resume detection via monotonic-vs-wall-clock divergence prompts reconnect; sessions pinned to hosts with runner registries. No explicit reaping of an orphaned sandbox. |

## 22. Strongest ideas

1. **Declared capabilities verified by an executable bench**, where `reconcile()`
   emits DRIFT when a declaration is false — making the capability table
   self-enforcing.
2. **`None` = "no claim", reported as UNKNOWN, never assumed unsupported.** The
   `absent` ≠ `unknown` discipline inside a capability model.
3. **Verified vs asserted capabilities tracked separately** — only 4 of 26
   harnesses are probe-verified, and the bench must not treat the rest as ground
   truth.
4. **Fail-closed decided per enforcement phase, with stated reasoning**, and
   `PHASE_TOOL_RESULT` deliberately failing open because the side effect already
   happened.
5. **The secretless credential proxy**: swap-on-access at the egress MITM,
   host-bound single-use placeholders for credential-gating clients, 403 leak
   guard, no clobbering of client-set headers.
6. **`workspace_id` in the composite primary key**, so forgetting to scope a query
   finds nothing rather than leaking.
7. **Task/Run separation for scheduled work**, with a queryable `error_code` on
   the run for retry classification.
8. **Monotonic `Agent.version` over content-addressed bundles.**
9. **Template agents vs session-scoped agents** distinguished by
   `Agent.session_id`.
10. **The strictly-decreasing timeout ladder**: each hop's budget must exceed the
    hop it waits on, never equal, or inner fail-open branches never run.
11. **Advisory gates that fail open by design**, with the tradeoff stated: a spawn
    that dies on routing infrastructure is worse than a spawn on the wrong model.
12. **`deciding_policies`** naming every policy that drove a composed verdict.
13. **Policies that transform content**, chained so each sees the previous
    output — enables PII redaction as policy.
14. **`Resume` and `ForkHistory` as declared enums** naming the real behaviours
    instead of pretending uniformity.
15. **`trace_id_from_response_id`**: the response id *is* the trace id, so no
    lookup table.
16. **Suspend detection via monotonic-vs-wall-clock divergence**, which cannot
    false-fire on a GC pause.
17. **Optional harnesses as separate PyPI packages** via entry points, with core
    still able to emit a targeted "`pip install omnigent-foo`" hint.
18. **Plugin registry that rejects builtin overrides** and rejects plugins
    declaring lifecycle hooks that are not wired end to end.
19. **`NATIVE_TUI` / `APPROVAL_MIRROR`**: bring an agent with no API under one
    policy layer by scraping its terminal and mirroring its approval pane.
20. **A design doc that audits its own dead code** and names the gap between
    intent and implementation.

## 23. Weakest architectural choices

1. **No event log.** State lives in mutable relational rows, so durability rests
   on transactions rather than replay. Google AX's fold-the-log model is stronger,
   and Omnigent's own observability doc notes a durable append-only event log is
   "tracked separately."
2. **Agent versioning without pinning.** `version` increments but a conversation
   never records which version it started on, so resume cannot detect a change.
3. **Task/Run separation only for scheduled work**, not for interactive sessions.
4. **The optional capability axes are entirely unpopulated** — 26 of 26 harnesses
   make no claim on `steering`, `live_queue`, `images`, `compaction`. The
   mechanism is proven, the data absent.
5. **19 of 26 harnesses' capabilities are unverified**, declared best-effort by
   integration mode. Honestly documented, still a correctness risk for anything
   that trusts the table.
6. **No agent-to-agent messaging** despite being a multi-agent supervision
   product.
7. **Hard-delete agents**, with no deprecation or revocation lifecycle.
8. **No database foreign keys** ("cascade is app-owned") — defensible for
   sharding, but referential integrity now depends on application discipline.
9. **Enormous surface for an alpha**: 111MB, 72 API paths, desktop app, web UI,
   Slack bot, 26 harnesses. Its own docs call it "heavily vibe-coded" and lacking
   "a clear mental map." A caution about our own scope.
10. **Sessions pinned to hosts/runners**, so work does not float to any worker as
    it does in AX.

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| Secretless credential proxy (swap-on-access + host-bound placeholder + leak guard) | REUSE (port) | Best answer to J4/K7 in the study; port the pattern directly |
| Declared capabilities + conformance bench + DRIFT reconciliation | ADOPT_AS_STANDARD | Closes the loop ADR-0012 opened |
| `None` = no claim → UNKNOWN, never "unsupported" | ADOPT_AS_STANDARD | The absent/unknown discipline, in a capability model |
| Verified vs asserted capability confidence | ADOPT_AS_STANDARD | Prevents trusting best-effort declarations |
| Per-phase fail-closed set with stated reasoning | ADOPT_AS_STANDARD | Sharper than my category-based amendment |
| `workspace_id` in the composite primary key | ADOPT_AS_STANDARD | Unscoped queries find nothing instead of leaking |
| Task → Run tables with queryable `error_code` | REUSE (pattern) | First real Task/Run separation; ADR-0002 |
| `deciding_policies` on a composed verdict | ADOPT_AS_STANDARD | ADR-0013 traceability |
| Strictly-decreasing timeout ladder | ADOPT_AS_STANDARD | Required for any layered fail-open path |
| `Resume` / `ForkHistory` as declared enums | REUSE (pattern) | Name real behaviours instead of assuming uniformity |
| Response id *is* the trace id | REUSE (pattern) | Free operator jump from id to trace |
| Template vs session-scoped agents | REUSE (pattern) | Distinction our domain model lacks |
| Entry-point harness plugins in separate packages | REUSE (pattern) | Keeps core install small; targeted install hints |
| Suspend detection by clock divergence | REUSE | Cheap, no false positives on GC pauses |
| Cost policy (soft checkpoints + hard downgrade gate) | INTEGRATE | First real cost control; fails closed on unpriced models |
| Mutable-rows-as-truth (no event log) | BUILD | Reject; prefer AX's derived-from-log model |
| Hard-delete agents | BUILD | Reject; need deprecate/revoke |
| 111MB alpha scope | BUILD | Reject as a scope model |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | **amends** | Durable identity is the `Conversation`, and agents are versioned *definitions* bound to it — closer to my model than AX's, but the durable thing is still the session. Adds a distinction I lacked: **template agents vs session-scoped agents** (`Agent.session_id`). Our `Agent` needs both. |
| ADR-0002 | **confirms** | **First real Task/Run separation.** `ScheduledTask` (intent: prompt, rrule, state, budget) and `ScheduledTaskRun` (attempt: status, timestamps, `error_code`) are separate tables, so intent survives failed attempts. Caveat: only for scheduled work, not interactive sessions. The `error_code` "for future retry logic" is the field my strawman Run was missing. |
| ADR-0003 | **confirms** | No agent-to-agent messaging — **six for six**, and this from a product built for multi-agent supervision. Agents relate through parentage and shared session state. This is now decisive: durable agent messaging is speculative generality unless our own requirements demand it, and it must not be in v0.1. |
| ADR-0004 | **confirms strongly** | `IntegrationMode`'s five values are the clearest statement of the adapter problem I have found, and `NATIVE_TUI` extends the space I had considered: you can adapt an agent with *no* integration surface by scraping its TUI and mirroring its approval pane. Our adapter taxonomy should carry this enum. |
| ADR-0005 | confirms | MCP as declarations plus a proxying manager, with capabilities modelled separately from MCP. Protocol, not capability model. |
| ADR-0006 | confirms | Speaks ACP as one `IntegrationMode` among five. Interop, not the internal contract — exactly the ADR's position. |
| ADR-0007 | **confirms strongly** | The fullest principal model in the study: users, accounts, `SessionPermission` levels, a `__public__` sentinel, admin flags, and **RFC 8628 delegated grants with per-request revocation**. First answer to S1 anywhere. Confirms both the abstraction and that delegated authority is tractable. |
| ADR-0008 | **confirms strongly** | **Fourth consecutive project** with filesystem/git-backed skills and no memory store (`skills/<dir>/SKILL.md` in the agent image). I consider this settled for v0.1. |
| ADR-0009 | **confirms strongly** | bwrap + seatbelt locally, ten cloud providers, mandatory L7 egress proxy. Most pluggable sandbox layer in the study, and unlike AX it ships local implementations too. |
| ADR-0010 | **confirms** | Second real OTel, more thorough than AX (FastAPI + httpx + **SQLAlchemy**). Also a caution: its own design doc found the propagation "elegant but" bespoke, `FastAPIInstrumentor` gated off, and a propagation helper that was dead code. **Adopting OTel is not the same as wiring it** — our exit criteria need a propagation test, not a dependency check. |
| ADR-0011 | **challenges** | The most useful challenge in Phase 3. Omnigent has what no other project has — a monotonic `Agent.version` over content-addressed bundles — and **still cannot detect an upgrade mid-flight**, because a conversation never pins the version it started on. Versioning is necessary but not sufficient; the *pin* is the mechanism, and it must live on the run. AX pins identity without versions, Omnigent versions without pinning; **we need both**. |
| ADR-0012 | **confirms and extends** | The strongest confirmation in the study, and it goes further than the ADR: (a) capabilities are published on `GET /v1/harnesses`, so they are public API; (b) an executable bench reconciles declared against observed and reports **DRIFT**, making the table self-enforcing; (c) `None` means *no claim* and is reported UNKNOWN, never assumed unsupported; (d) verified and asserted capabilities are tracked separately. **Also supersedes my own amendment**: Omnigent splits fail-closed by *position in the enforcement path* (`PHASE_TOOL_RESULT` fails open because the side effect already happened), which is sharper than my safety-vs-liveness categories. |
| ADR-0013 | **confirms** | First implementation: `PolicyResult.deciding_policies` names every policy that drove a composed verdict — one on DENY, all ASKing policies in YAML order. Policies also transform content in a chain, so PII redaction is a policy. No shadow-comparison mode, so that half remains unprecedented. |

**Three amendments to make immediately.**

1. **ADR-0012's fail-closed rule should be positional, not categorical.** Replace
   my safety-vs-liveness split with Omnigent's: fail closed where the decision is
   the *last enforcement point*, fail open where the harm is already incurred.
   Define the set once, in one constant, so enforcement sites cannot drift.

2. **ADR-0011 needs the pin on the run, not just versions on the definition.**
   Omnigent proves versioning alone does not detect mid-flight upgrade. The run
   must record `(agent_id, agent_version, adapter_identity)` at start and compare
   on resume.

3. **ADR-0010 needs a wiring test, not a dependency.** Omnigent depends on six
   OTel packages and its own audit still found dead propagation helpers and
   disabled instrumentors. Our exit criterion must be "one trace id spans
   client → control plane → adapter, asserted by a test."

## 26. Open questions

- Does anything pin `Agent.version` onto a conversation at start, or is the
  version purely an audit counter? I found no field on `Conversation`. (→ OQ-020)
- Is the `harness_bench` DRIFT reconciliation actually run in CI, or is it a
  manual/local tool? Determines whether the capability table is *enforced* or
  merely *checkable*. (→ OQ-021)
- Why are all four optional capability axes unpopulated across 26 harnesses — is
  the tri-state new, or is populating it blocked on live probing? (→ OQ-022)
- **Answered while reading.** Scheduled task runs are *not* claimed with a lease.
  `ScheduledTaskScheduler` is explicitly an "**in-process** RRULE scheduler" that
  arms one timer per active task from `list_active_all_workspaces()`, with "no
  in-memory schedule state beyond the live timers"
  (`omnigent/server/scheduled/scheduler.py:1-24`). Overlap policy is SKIP and
  there is a 30s `MISFIRE_GRACE_TIME_S`, but both guard against *self*-overlap
  within one process. **Two server replicas would each arm timers and double-fire**,
  and missed fires while the server was down are deliberately not replayed. So
  scheduling is correct for a single server instance and unsafe horizontally —
  a useful warning for us, since our control plane is meant to scale out. A
  durable claim (`UPDATE ... WHERE status='scheduled'` returning rowcount, or
  `SELECT ... FOR UPDATE SKIP LOCKED`) is the missing piece. (→ OQ-023)
