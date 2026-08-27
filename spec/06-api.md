# 06 — Northbound API
<!-- status: final -->

HTTP/JSON at `/v1`. Resource-oriented, with two credential classes and the transition
table from §05 enforced at the edge.

---

## Two credential classes — the governed cannot edit the governor

The only project in the study that separates these is Agent Control, and it is the
whole point of a control plane.

| Class | May | May not |
|---|---|---|
| **agent** | create/submit runs it owns, read them, and **read** approvals on them | **decide any approval**; touch policies, adapters, tenants, or other principals' runs |
| **admin** | everything the API exposes, including policy and adapter registration | — |

Separate header, separate key material: `Authorization: Bearer <token>` where the token
carries its class. An agent token presented to a policy endpoint is `403`, not `401` —
it authenticated fine, it is simply not permitted.

**An agent credential may not decide an approval.** `POST /v1/approvals/{id}/decide` with an
agent token is `403 wrong_credential_class`.

Two axes, and conflating them is a mistake worth naming because the first draft of this
paragraph made it:

- **Credential class** (`agent` | `admin`) says what a *token* may do. There are two, and
  adding a third for approvals would have been wrong.
- **Principal kind** (`human` | `agent` | `service` | `remote`) says what the *actor* is.
  `approvals.decided_by` must reference a principal of kind **`human`** — enforced in the
  schema by a composite foreign key (§01), not merely by this route.

**Deciding an approval requires an admin credential AND a principal of kind `human`.** The
credential class is checked by the route; the kind is pinned by a composite foreign key in
§01, so an admin token held by a `service` principal is rejected **by the database** rather
than by convention. That is the whole point of ADR-0015.

> **Retracted 2026-08-27 (redo 3).** Two wordings stood here in turn, and both are gone.
> The first (superseded 2026-08-27) let an agent answer approvals on its own runs, which reads
> as *the requester decides* — the opposite of what an approval is for. The second (superseded
> 2026-08-27) named an approver-assignment that does not exist — **an assignee model with no
> column to hold it**, since `approvals` has `decided_by` and not `assigned_to`.
>
> Whether an agent may ever be an approver is deferred **with** the multi-party question, for
> the same reason: it needs a real organisational policy to answer, not a schema guess. See
> [§09](09-decisions.md) 7.

**Every request resolves to a `Principal`.** There is no anonymous path. `tenant_id` is
derived from the token and **never** read from the body or a path parameter, so
cross-tenant access is not expressible in a request.

---

## Resources

### Agent definitions — immutable, content-addressed

```http
POST /v1/definitions
{ "name": "reviewer", "instructions": "...", "tools": [...], "extensions": [...] }

201 { "digest": "a1b2...", "canon_profile": "nfc+intjson/v1" }
200 { "digest": "a1b2...", "canon_profile": "nfc+intjson/v1" }   # already existed
```

`200` versus `201` distinguishes "created" from "already present". Posting the same
definition twice is **idempotent by construction** — the digest is the key — so no
idempotency header is needed here.

```http
GET /v1/definitions/{digest}          → the body, or 404
```

There is **no PUT or DELETE.** Editing an agent means posting a new definition and
repointing the name.

### Agents — the mutable pointer

```http
POST  /v1/agents            { "name": "reviewer", "digest": "a1b2..." }
PATCH /v1/agents/{id}       { "digest": "c3d4...", "declared_version": 2 }
GET   /v1/agents/{id}
```

`PATCH` is how an agent is "edited": it moves the pointer. **It affects new runs only.**
Runs already pinned to the old digest keep running and resume against *their own* pinned
artifact, which is still verified by digest on every resume.

An earlier version of this document said such runs became `INCOMPATIBLE` on resume. That
was reversed: a pointer update and a security invalidation are different operations, and
overloading one to mean the other turned any edit — however cosmetic — into a global
resume blocker. Stopping in-flight work needs an audited digest revocation, which **v0.1
does not ship**; until then the way to stop a run is `POST /v1/runs/{id}/cancel`. See
[§09](09-decisions.md) 2.

### Runs

```http
POST /v1/runs
Idempotency-Key: <client-supplied>
{ "agent_id": "ag_1", "prompt": "review the diff" }

201 { "run_id": "01J8...", "state": "draft",
      "pin": { "definition_digest": "...", "adapter_identity": "...",
               "adapter_digest": "...", "payload_schema_digest": "...",
               "checkpoint_schema_version": 1 } }
```

The pin is **computed and returned at creation**, so a client can see exactly what its
run is bound to.

```http
POST /v1/runs/{id}/submit        → 202, state=queued
POST /v1/runs/{id}/cancel        { "reason": "..." }  → 202, state=cancelling
POST /v1/runs/{id}/discard       { "reason": "..." }  → 200, state=discarded
GET  /v1/runs/{id}
GET  /v1/runs?state=waiting_input&limit=50&cursor=...
GET  /v1/runs/{id}/events?since_seq=0
```

`cancel` returns `202` and `cancelling`, never `cancelled`. The API does not pretend a
cancel is instantaneous.

`GET /v1/runs?state=waiting_input` is backed by the partial index, so it stays cheap as
history grows.

**There is no endpoint that sets `running`, `expired`, or `indeterminate`.** Per §05
those are worker- and system-only, and the absence of a route is the enforcement.

### Approvals

```http
GET  /v1/approvals?status=pending
POST /v1/approvals/{id}/decide
{ "status": "approved", "rationale": "verified with the customer" }

200 { "approval_id": "...", "status": "approved",
      "decided_by": "pr_alice", "decided_at": "..." }
409 { "error": "already_decided", "status": "denied",
      "decided_by": "pr_bob", "decided_at": "..." }
```

`decided_by` comes from the **token**, never the body — an approver cannot be
impersonated by a request field. The `409` returns the *existing* decision, following
HumanLayer's `AlreadyDecidedError`: a retrying UI learns what the decision already was
rather than getting an opaque conflict.

`rationale` is accepted on approve as well as deny. The interesting audit question is
usually why something *was* permitted.

### Policies — admin only

```http
POST /v1/policies
{ "name": "block-prod-writes", "scope": "tenant",
  "cedar_source": "forbid(principal, action == Action::\"write\", resource) when {...};",
  "decision": "observe" }
```

`decision: "steer"` **requires** `steering_guidance`; omitting it is `422`, matching the
schema `CHECK`. Validation happens in both places on purpose — the API gives a good
error, the schema makes the bad state impossible.

```http
POST /v1/policies/{id}/promote     { "to": "steer" }   # observe → steer → deny
GET  /v1/policies/{id}/decisions?enforced=false&since=...
GET  /v1/policies/{id}/stats?window=24h
```

The last two are what make `observe` mode usable: shadow verdicts are queryable and
aggregable. Shadow evaluation without aggregation tells you a policy fired once, not
that it would have fired 4,102 times.

### Adapters — registration is admin only, the catalogue is not

```http
POST /v1/adapters
{ "identity": "sdk:claude-agent-sdk", "protocol_version": "1.0",
  "integration_mode": "sdk_in_process", "declared_capabilities": {...} }
# amended 2026-08-27: was "acp:claude-code" with an acp_subprocess mode;
# see synthesis/scope-reconciliation.md section 7

201 { "identity": "...", "digest": "<derived>" }
```

The digest is **derived from the contract**, never accepted from the caller — a
caller-supplied adapter digest was a hole spike 02 closed.

```http
GET /v1/adapters                  # the capability catalogue — ANY authenticated class
```

Publishing capabilities is deliberate (Omnigent): a caller can degrade knowingly
instead of discovering limits by failure. That only works if the callers who must degrade
can read it, so the catalogue is readable by an **agent** token while registration stays
admin-only. The section heading previously said "admin only" for both, which contradicted
the line above it.

---

## Approval authority — what this API does not do

`POST /v1/approvals/{id}/decide` records **one** attributable terminal decision. There is no
quorum, no m-of-n, no role requirement and no separation-of-duties enforcement beyond the
quorum. There is **no self-approval prohibition in v0.1** — §09 7 defers it with the
multi-party question, and an earlier version of this sentence referred to a rule that does not
exist. That is a deliberate refusal on the evidence, recorded 2026-08-27 — see
[§09](09-decisions.md) 7 — and workloads requiring more must delegate authorization to an
external governed system.

## Idempotency

`Idempotency-Key` is **required** on POST /v1/runs and POST /v1/approvals/{id}/decide.
It is optional elsewhere. Keys are scoped `(tenant_id, endpoint, key)` and retained 24h.

A replay returns the original response with `Idempotency-Replayed: true`. A key reused
with a *different* body is `422` — silently returning the first response would hide a
client bug.

---

## Errors

```json
{ "error": "incompatible_checkpoint",
  "message": "Cannot resume run 01J8: definition_digest changed (a1b2… → c3d4…). The agent definition was modified after this run checkpointed.",
  "remedy": "Start a new run, or repoint the agent to digest a1b2…",
  "details": { "field": "definition_digest", "pinned": "a1b2…", "current": "c3d4…" } }
```

Three parts, always: **what was refused**, **the mechanism**, **the alternative**. Our
errors are read by an agent before a human sees them, so an error that names the retry
parameter is worth more than one that names an exception class.

| HTTP | `error` | When |
|---|---|---|
| 403 | `wrong_credential_class` | agent token on an admin route |
| 404 | `not_found` | absent, **or** another tenant's (indistinguishable on purpose) |
| 409 | `already_decided` | approval re-decision; returns the existing decision |
| 409 | `concurrent_resume` | another worker holds the lease |
| 409 | `incompatible_checkpoint` | pin mismatch |
| 422 | `artifact_missing` / `artifact_corrupted` | distinct remedies, distinct codes |
| 422 | `steer_requires_guidance` | policy validation |
| 429 | `rate_limited` | with `Retry-After` |

A `404` for another tenant's resource is deliberate: `403` would confirm the resource
exists, which is an information leak.

---

## Streaming

```http
GET /v1/runs/{id}/stream        # SSE
```

Events as in §04, replayable via `Last-Event-ID` (mapped to `seq`). The stream is a
projection of the log, never a separate channel — so a client that reconnects and
replays sees exactly what a client that stayed connected saw.

---

## Tests, with negative controls

| Invariant | Test | Negative control |
|---|---|---|
| `tenant_id` never comes from the request | forge it in body and path | read it from the body ⇒ cross-tenant access |
| Agent tokens cannot reach admin routes | agent token → `POST /v1/policies` | drop the class check ⇒ 201 |
| `decided_by` comes from the token | put a different principal in the body | trust the body ⇒ impersonation |
| No route sets `running` | enumerate routes | add one ⇒ duplicate execution possible |
| Idempotent replay returns the original | same key twice | ignore the key ⇒ two runs |
| Same key, different body ⇒ 422 | change the body | return the first ⇒ hides a client bug |
| Cross-tenant read is `404` not `403` | read another tenant's run | return 403 ⇒ existence leak |
