# Build / reuse map — v0.1
<!-- status: final -->

Generated from the 203 component decisions recorded across 13 `facts.yaml` files:
**98 ADOPT_AS_STANDARD, 71 REUSE, 23 BUILD (reject), 11 INTEGRATE.**

Reading order: what we **integrate** (someone else's running code), what we
**port** (their design, our code), what we **build** (no adequate precedent), and
what we **reject** (patterns we deliberately do not copy).

---

## 1. INTEGRATE — run someone else's code

**Three** survive the test "Apache-2.0 or MIT, in our language or language-agnostic,
independently useful, and solves a subsystem we would otherwise invent."

> **Corrected 2026-08-26.** Agent Control was listed here and simultaneously in the
> PORT section below — two incompatible architectures in one table. It is now PORT
> only: it carries its own PostgreSQL persistence and its own `namespace_key`
> tenancy, and **has no `Principal` model**, so running it as a dependency would mean
> a second policy store structurally unable to name the principal ADR-0007 requires
> on every decision. See
> [`scope-reconciliation.md`](scope-reconciliation.md) §3.

| What | From | Why it wins | Risk |
|---|---|---|---|
| **`ag2.network`** — envelope schema, hub contract, channel protocols **(CONTINGENT: gated on a storage spike, §4 of scope-reconciliation)** | AG2 (Apache-2.0, Python) | The only durable agent-to-agent messaging in 13 projects. Opt-in package, 49 test files, verified 39 passing. Adopting it removes the single largest BUILD with no prior art. | Its WAL is file-based with in-memory indexes, and terminal-channel pruning clears the causation index — so its dedupe guarantee has a retention horizon we must replace. |
| **Cedar** — the policy language | via AWS AgentCore | Formal semantics + existing analysis toolchain. Makes "is policy set B more permissive than A" decidable, which is the only path to ADR-0013's static shadow comparison. `principal`/`action`/`resource` align with our ADR-0007 split. | Cedar is a language, not a service; we own the evaluation and the integration. |
| **`genai-prices`** — cost data | via Pydantic AI | Externally maintained pricing dataset rather than a table we keep current. | Pair with Omnigent's fail-closed-on-unpriced rule; verify maintenance cadence before depending on it for *enforcement* (OQ-028). |

**Deliberately not integrated** despite being technically eligible: LangGraph's
checkpointers and graph runtime (we are not adopting its graph model), Letta's
kernel sandbox backends and OpenHands' `BaseWorkspace` set (superseded by ADK's
seven-executor range and our three-boundary requirement), and Omnigent's cost policy
(the *design* ports, the implementation is entangled with its session model).

## 2. PORT — their design, our code

The 98 ADOPT_AS_STANDARD and 71 REUSE decisions collapse into these, grouped by the
component they land in.

### Run engine and durability
| Pattern | Source |
|---|---|
| Derive state by folding an append-only log; no parallel state table | Google AX |
| Composite PK with the sequence computed inside the insert transaction (single-writer without a lock service) | Google AX |
| Content-derived pin, canonicalised before hashing, compared on resume | **MAF** |
| Refuse resume on a definition change, with an error naming the likely cause | Google AX, MAF |
| Checkpoint only *committed* state | MAF |
| `previous_checkpoint_id` chaining; checkpoint bound to a definition not an instance | MAF |
| Hung-work detection by `execution_started_at` cutoff + a re-check alarm | Cloudflare |
| Orphan detection by outer-joining the ledger against live run rows | Cloudflare |
| Exponential backoff when a recovery scan makes no forward progress | Cloudflare |
| Root-side index of descendant work needing recovery (who checks a sleeping child) | Cloudflare |
| `Healthy` vs `HealthyBusy` — idle-alive ≠ working-alive | AgentCore |
| Explicit `*_FAILED` terminal statuses; failure is a state, not a timeout | AgentCore |
| Reflect-and-retry rather than retry-identically | ADK |
| Eager validation of retry config at enqueue time | Cloudflare |
| `isErrorRetryable` excluding overload errors (retrying a self-protecting service worsens congestion) | Cloudflare |
| Event rewind with a single documented source of truth for which events are live | ADK |

### Effect ledger
| Pattern | Source |
|---|---|
| `idempotency_key UNIQUE`, checked before execution, `accepted: false` on duplicate | Cloudflare |
| Causation-based dedupe for reply-shaped work (the reply *is* the record) | AG2 |
| Guard checked before any ownership or turn test | AG2 |
| Throw when two identity keys disagree | Cloudflare |
| `clientToken` idempotency as a platform-wide convention, not per-feature | AgentCore |

### Policy
| Pattern | Source |
|---|---|
| `deny \| steer \| observe`; steer invalid without guidance | Agent Control |
| Recursive condition trees with shape validation | Agent Control |
| Positional fail-closed set, defined once so sites cannot drift | Omnigent |
| `deciding_policies` named on a composed verdict | Omnigent |
| Refusals observable for *every* attempt | AG2 |
| Stats + timeseries over decisions | Agent Control |
| Ownership precedence: org binds agent | MAF/Purview |
| Bidirectional ingress + egress content policy | MAF/Purview |
| Policy generation as reviewable assets | AgentCore |
| Policy binding as its own queryable resource with an `enabled` flag | Agent Control |
| Replaceable arbiter so custom protocols need no fork | AG2 |

### Identity, credentials, approval
| Pattern | Source |
|---|---|
| Immutable Passport + mutable definition + cache-only runtime | AG2 |
| `kind: human \| agent \| service \| remote` — one type, discriminated | AG2 |
| Workload identity; three token variants; `ON_BEHALF_OF_TOKEN_EXCHANGE` named | AgentCore |
| Exchange and refresh as *separate* interfaces and registries | ADK |
| Secretless credential proxy: swap on egress, host-bound placeholder, 403 leak guard | Omnigent |
| Hub-incremented delegation depth capped by rule | AG2 |
| RFC 8628 device grant with per-request revocation and a path allow-list | Omnigent |
| `Approval` table: status CHECK, partial index on pending, rationale both ways, `ErrAlreadyDecided` | HumanLayer |
| Reconciliation on restart, keyed by run, non-fatal | HumanLayer |
| Expiring dangerous overrides that emit an event on lapse | HumanLayer |
| Typed user identifiers (never a bare string) | AgentCore |

### Capability and extension
| Pattern | Source |
|---|---|
| Declared capabilities as public API, bench-verified, DRIFT = failure | Omnigent |
| Two-layer bench: offline every commit, live gated | Omnigent |
| `unknown` never degrades to `false`; confidence `verified \| asserted` | Omnigent |
| Continuous observed statistics per capability | AG2 |
| Declared composition position and ordering; typed wrap points | Pydantic AI |
| Serializability as an enforced project rule | Pydantic AI |
| Optional method whose error names the fallback | ADK |
| Conformance-suite pattern for capability negotiation | LangGraph |

### Memory, state, knowledge
| Pattern | Source |
|---|---|
| Four state scopes by prefix, `temp:` never persisted (enforced per backend) | ADK |
| Schema-validated run-scoped state; open prefixed namespaces | ADK |
| `MemoryEntry{author, event_timestamp}` — provenance, not storage time | ADK |
| Declared memory *kinds* orthogonal to scopes | AgentCore |
| Hierarchical namespaces with prefix queries; **wildcards refused** | AgentCore |
| Filesystem/git-backed skills | 7 of 13 projects |
| Compaction as a configured strategy, honest about its limits | AG2, ADK |

### Sandbox
| Pattern | Source |
|---|---|
| Provider interface that ships a *local* implementation | ADK |
| SSRF + cloud-credential guard, unclosable by configuration | Pydantic AI |
| Escape hatch scoped so it cannot open the worst hole | Pydantic AI |
| Bounded downloads with size-limitable encodings only | Pydantic AI |
| Storage boundary as an LLM enforcement boundary | Cloudflare |
| Naming the unsafe option `unsafe_local` / `dangerously_` | ADK, HumanLayer |
| Allow-listed unpickler | ADK |

### Adapters and protocol
| Pattern | Source |
|---|---|
| Four-method adapter; durability in the control plane | Google AX |
| Opaque adapter config the control plane refuses to parse | Google AX |
| Precisely specified stream terminator | Google AX |
| gRPC southbound; ACP behind an adapter, not as the transport | Google AX |
| Five-mode integration taxonomy including `NATIVE_TUI` | Omnigent |
| Entry-point plugins that cannot override builtins | Omnigent |
| Control-plane / data-plane split with per-plane allow-lists | AgentCore |
| Typed `CancelReason`; cancel *request* ≠ cancel *fact* | Google AX, AG2 |
| Envelope: `causation_id`, `depth`, `ttl`, `priority`, `trace_id`, `audience` | AG2 |
| Log records every accepted envelope regardless of audience | AG2 |

### Tenancy
| Pattern | Source |
|---|---|
| `tenant_id` in every composite **primary** key | Omnigent, ADK |
| `tenant_id` in every composite **foreign** key | **Agent Control** |
| Single-tenant runs as tenant 0 — same code path, one value | Omnigent |

### Observability and DX
| Pattern | Source |
|---|---|
| GenAI semconv + declared vendor namespace, never squatting | Cloudflare |
| Declared semconv version with one deprecation window | Pydantic AI |
| Stability tiers separated by module; experimental marked unguaranteed | ADK |
| Deployment-pinnable telemetry schema version | ADK |
| Span lifetime bound to the owning invocation | Cloudflare |
| Response id *is* the trace id | Omnigent |
| In-memory implementation of every pluggable interface | ADK, LangGraph, AX, Pydantic AI |
| Per-package `AGENTS.md` design rules | Pydantic AI |
| Design docs that describe no API so they cannot go stale | Cloudflare |
| Naming your unsafe default in the README | Agent Control |
| Errors that state the mechanism *and* the alternative | Pydantic AI, ADK |
| Strict-in / lenient-out enum normalisation | Agent Control |
| Idempotent column-checked migrations | HumanLayer |

## 3. BUILD — no adequate precedent

Four **target-architecture** items, each with the evidence for why it is genuinely
ours. **Two ship in v0.1** (1 and 2); item 3 ships its offline layer only, and item 4
ships attributable approvals with revocation deferred. See
[`scope-reconciliation.md`](scope-reconciliation.md) §1.

| # | What | Evidence that nobody does it | Confidence |
|---|---|---|---|
| 1 | **Content-derived pinning applied to the *agent definition***, compared on every resume | MAF proves the mechanism on *workflows* (bytecode digest, enforced). AX pins adapter identity without versions; Omnigent versions agents without pinning; ADK versions storage and telemetry schemas but not agents; Cloudflare versions its schema but leaves user snapshots unversioned. **13 projects, nobody pins an agent.** | **High** — mechanism proven, only the target is new |
| 2 | **A platform-owned effect ledger** | Cloudflare (explicit key) and AG2 (causation key) each solve half in their own scope. ADK states the requirement precisely and *delegates it to tool authors*. `C6` negative in 8 of 13. | **High** — two working precedents to combine |
| 3 | **Unified `Capability` + `Extension` with a two-layer bench** | Omnigent has the bench and declared capabilities; Pydantic AI has composition with ordering; AG2 has observed statistics. Nobody has all three, and five projects conflate the two meanings of the word. | **Medium** — three partial precedents, integration is the work |
| 4 | **Agent-level revocation and an approver identity on approvals** | `D9` negative in 10 of 13, `implicit` in 3 — best available is credential-level (AgentCore) or attachment-level (Agent Control). HumanLayer has the only real approval resource and records *why*, never *who*. | **Medium** — conceptually simple, unprecedented in combination |

## 4. REJECT — patterns not to copy

From the 23 recorded BUILD-as-rejection decisions:

| Anti-pattern | Source | Why |
|---|---|---|
| Auth as a developer-supplied hook / no auth at all | Cloudflare, Google AX | A platform must own authN; AX exposes sandbox provisioning unauthenticated |
| Approval without an approver identity | HumanLayer | Durable decisions that still fail an audit |
| Idempotency delegated to tool authors | ADK | The platform performs the replay, so it owns the hazard |
| No egress control alongside web-fetching tools | ADK | The SSRF path Pydantic AI closes is left open |
| Mutable rows as source of truth | Omnigent | Durability by transaction rather than replay |
| Hard-delete agents | Omnigent | Revocation is a lifecycle state, not a `DELETE` |
| In-process scheduler with no cross-replica claim | Omnigent | Correct on one instance, double-fires horizontally |
| Declared-but-unenforced rate limits | AG2 | Config that does not do what it says is worse than none |
| Lifetime observed counters with no decay | AG2 | Reputation routing needs a window |
| File WAL with in-memory indexes | AG2 | A dedupe guarantee must not have a retention horizon |
| Early cancellation applied to observe-mode controls | Agent Control | Biases shadow data away from denied traffic |
| Namespaces as the *only* scoping mechanism | AgentCore | A path is a convention; a key is a constraint |
| An SDK with no local implementation | AgentCore | ADK proves the alternative at the same company scale |
| Default unrestricted permission mode | Letta | Safe defaults, not convenient ones |
| Capability signalling via `NotImplementedError` with a silent local no-op | OpenHands | Silent fail-open is the one thing ADR-0012 forbids |
| 13k-line god class / 35-package surface | Cloudflare, MAF | Scope discipline |

## 5. Licensing

All 13 projects are Apache-2.0 or MIT. **No copyleft anywhere**, so nothing in the
port list carries a licence obstacle. One process note worth carrying: GitHub's API
reports HumanLayer as `NOASSERTION` while its `LICENSE` file says Apache-2.0 plainly
— **licence metadata is not licence evidence**, and an automated scan would have
excluded a project whose patterns we are porting.

Full detail in [`licensing.md`](licensing.md).
