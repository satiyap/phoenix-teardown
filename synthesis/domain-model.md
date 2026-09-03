# Canonical domain model — v0.1
<!-- status: final -->

Derived from 13 teardowns and 15 accepted ADRs. Every node below cites the
project that justifies it. Nodes that were in the Phase 0 strawman and are now
**deleted** are listed at the end with the reason, because the deletions are as
load-bearing as the additions.

---

## The model

```text
Tenant  (tenant_id)                     in every composite PRIMARY key
 │                                      AND in composite FOREIGN keys
 ├── Principal                          who is acting
 │    ├── kind: human | agent | service
 │    ├── authenticated_by
 │    ├── delegation: on_behalf_of, depth (bounded by policy)
 │    └── revoked_at                    a lifecycle state, not a delete
 │
 ├── Credential                         what an action carries outward
 │    ├── kind: api_key | http | oauth2 | oidc | service_account
 │    ├── obtained_by  → Exchanger      obtaining and renewing are
 │    ├── kept_alive_by → Refresher     DIFFERENT interfaces
 │    └── never enters a sandbox in plaintext
 │
 ├── Agent
 │    ├── Identity (immutable)          id; mutation ⇒ new id
 │    ├── Definition (versioned)        manifest: instructions, tools,
 │    │    ├── digest                   capabilities, approval modes
 │    │    └── version                  informational only, never compared
 │    ├── Capability[]                  DECLARED metadata (see below)
 │    ├── Extension[]                   INSTALLED behaviour (see below)
 │    └── lifecycle: active | deprecated | revoked
 │
 ├── Project                            grouping of sessions
 │
 ├── Task                               the durable INTENT
 │    ├── trigger: manual | rrule + tz | event
 │    ├── budget: max_cost, max_runs
 │    ├── state: active | paused | archived
 │    └── Run[]                         attempts at this intent
 │         ├── state (see state machine)
 │         ├── pin { definition_digest, adapter_identity,
 │         │        adapter_digest, checkpoint_schema_version }
 │         ├── error, error_code        error_code is QUERYABLE
 │         ├── rewind_marker            logical history reduction
 │         └── EffectLedgerEntry[]      one per side effect
 │
 ├── Session                            durable conversational container
 │    ├── State (four scopes by prefix)
 │    │    ├── "app:"                   tenant-wide
 │    │    ├── "user:"                  per-principal, cross-session
 │    │    ├── (unprefixed)             run-scoped, SCHEMA-VALIDATED
 │    │    └── "temp:"                  NEVER persisted
 │    ├── Event[]                       append-only, sequence-ordered
 │    └── Grant[]                       (principal, session, level)
 │
 ├── Channel                            addressable conversation
 │    ├── protocol                      conversation | discussion |
 │    │                                 consulting | workflow
 │    ├── Participant[]                 principals of any kind
 │    ├── Expectation[]                 turn order, max_silence
 │    └── Envelope[]                    append-only WAL
 │
 ├── Approval                           durable, with an approver
 │    ├── action_ref                    correlated BOTH ways
 │    ├── status: pending | approved | denied | expired | superseded
 │    ├── requested_by_rule             WHICH policy required it
 │    ├── decided_by → Principal        the field nobody has
 │    ├── decision_rationale            on approve AND deny
 │    └── expires_at
 │
 ├── Policy                             Cedar
 │    ├── scope: tenant | project | agent | session
 │    ├── ownership_precedence          org binds agent; agent cannot weaken
 │    ├── decision: deny | steer | observe
 │    ├── steering_guidance             REQUIRED when decision = steer
 │    └── PolicyBinding                 attachment is its own resource
 │
 ├── Knowledge                          filesystem/git-backed skills
 ├── Recall                             semantic memory service
 │    ├── kind: semantic | summarization | user_preference | custom
 │    ├── scope: (tenant, principal)
 │    └── author, event_time            provenance, not storage time
 │
 └── Sandbox                            three boundaries
      ├── process/filesystem            pluggable provider
      ├── egress                        mandatory guard + credential proxy
      └── storage                       the LLM must not reach the control DB
```

## The Run state machine

```text
        DRAFT ──────────► DISCARDED
          │
          ▼
       QUEUED ──► RUNNING ──► SUCCEEDED
                    │  ▲          
                    │  └──────────── (resume)
                    ├──► WAITING_INPUT ─────┘     blocked on a human; INDEXED
                    ├──► CANCELLING ──► CANCELLED  cancellation takes time
                    ├──► FAILED                    with a queryable error_code
                    ├──► EXPIRED                   distinct from FAILED
                    ├──► INDETERMINATE             effect dispatched, unconfirmed
                    └──► INCOMPATIBLE              pin mismatch on resume
```

Six of these states came from evidence rather than the strawman:

| State | Source | Why it exists |
|---|---|---|
| `DRAFT` / `DISCARDED` | HumanLayer | A run can be composed before it starts and abandoned without running |
| `WAITING_INPUT` | HumanLayer, MAF (`IDLE_WITH_PENDING_REQUESTS`) | "Blocked on a human" must be an indexed query, not an inference |
| `CANCELLING` | HumanLayer (`interrupting` → `interrupted`) | Cancellation is not instantaneous; a machine that pretends otherwise lies during the gap |
| `EXPIRED` | AG2 (`TaskExpired` ≠ `TaskFailed`) | Different cause, different handling |
| `INDETERMINATE` | ADR-0014 | An effect dispatched but unconfirmed is not retryable and must surface |
| `INCOMPATIBLE` | Google AX, MAF | A pin mismatch is a distinct terminal state, not a generic failure |

## Two kinds of "capability"

Five projects used one word for two things. Splitting them was the most useful
conceptual correction of the study.

| | `Capability` | `Extension` |
|---|---|---|
| **What** | declared metadata: what a thing *can do* | installed object: what behaviour *is present* |
| **Consumed by** | routing, degradation, fail-closed decisions | the execution pipeline |
| **Shape** | tri-state (`true \| false \| unknown`), classified by enforcement position, carrying confidence (`verified \| asserted`) | declared position (`outermost \| innermost`) + ordering + typed wrap points |
| **Verified by** | a two-layer conformance bench (offline every commit, live gated) plus continuous observed statistics | tests |
| **Source** | Omnigent, AG2, LangGraph, Letta | Pydantic AI |

`unknown` never degrades to `false`. Absence of a claim is not a claim of absence —
the same discipline this study ran on.

## Contested nodes, resolved

| Node | Resolution |
|---|---|
| **`Session` as a resource** | **Kept**, but as a conversational container scoped `(tenant, principal, session)`, not as an execution unit. Omnigent and ADK both key it this way in the primary key. |
| **`Step` as a resource** | **Deleted.** It is a log entry. Google AX makes `Step` a typed event in the log and nothing addresses it directly; treating it as a resource invites per-step APIs nobody needs. |
| **`Conversation` distinct from `Session`** | **Deleted.** One concept. AX's `Conversation`, Omnigent's `Conversation`, ADK's `Session` and HumanLayer's `Session` are the same node under four names. |
| **`Channel` vs `AgentTransport`** | **Split confirmed.** `Channel` is the addressable durable conversation (AG2); transport is how an envelope moves (gRPC, in-process, remote hub) and is not a domain concept. |
| **`Task` vs `Run`** | **Both kept**, on one real precedent (Omnigent) plus the argument that `error_code` and budget belong to the intent rather than the attempt. Weakest-supported node in the model — flagged in the v0.1 boundary. |
| **`Approval` as a Run status** | **Rejected; promoted to a resource.** A status cannot hold the question, the decision, the rationale, the approver, or two concurrent approvals in one run (ADR-0015). |
| **`AgentRuntime` as durable** | **Deleted as durable.** AG2 marks it explicitly "cache-only" — transport binding and last heartbeat. Making connection state authoritative was a strawman error. |
| **`Memory` as one node** | **Deleted; split three ways** into `Knowledge`, `Recall` and `State` (ADR-0008). Seven projects chose files for knowledge; two have a recall service; ADK supplies the four state scopes. |
| **`Principal` as one node** | **Split** into `Principal` and `Credential`. Four projects have exactly one half, which proves they are separable subsystems (ADR-0007). |

## Invariants

These are the properties the schema must make impossible to violate, not merely
discourage.

1. **`tenant_id` is in every composite primary key *and* every composite foreign
   key.** An unscoped lookup finds nothing (Omnigent, ADK); a cross-tenant
   *relationship* cannot be created (Agent Control — "Composite FKs enforce
   same-namespace references on both sides").
2. **A Run's pin is compared on every resume**, and a mismatch is `INCOMPATIBLE`
   rather than a silent continuation (Google AX, MAF).
3. **Every side effect has a ledger entry written before it is attempted**
   (ADR-0014).
4. **An Approval's terminal decision requires a `decided_by` Principal.**
5. **`temp:` state is never persisted** — enforced in every storage backend, not
   in application code (ADK).
6. **Envelope identity and hop count are stamped by the authority**, never by the
   sender (AG2).
7. **The log records every accepted envelope in full, regardless of audience.**
   Audit scope exceeds delivery scope (AG2).
8. **Only committed state is checkpointed.** A checkpoint can never hold a
   half-applied mutation (MAF).
9. **A `steer` policy decision without steering guidance fails validation**
   (Agent Control).
10. **Organisation policy binds agent policy**; an agent-scoped rule cannot weaken
    a tenant-scoped one (MAF/Purview).

## What this model deliberately omits

`Workflow`/`Graph` (belongs to an external engine — MAF, Pydantic AI),
`Compensation`/`Saga` (zero precedent in 13 projects; the workflow engine's job),
`Model`/`Provider` (an explicit anti-goal), and `Tool` as a first-class registry
entry (tools belong to the agent definition and to MCP, per ADR-0005).
