# 06 — Northbound API
<!-- status: final -->

HTTP/JSON at `/v1`. Resource-oriented, with two credential classes and the transition
table from §05 enforced at the edge.

---

## Ory human authentication amendment

The human authentication rules in [20-human-auth.md](20-human-auth.md) supersede
references below to exchanging customer tokens or minting Phoenix human bearers.
The two capability classes remain for machine callers and internal authorization;
they are not a second authority for Ory browser sessions.

```http
GET /v1/auth/session
Cookie: ory_kratos_session=...
```

Returns the realm-bound tenant/principal, role, effective permissions, session expiry,
a session-bound CSRF value, and verification/MFA requirements. No password, Ory
administrative metadata, or Phoenix human bearer is returned. Unknown membership is
403, missing/invalid session is 401, and unavailable identity dependencies are 503.
Cookie-authenticated mutations require the exact Origin and `X-Phoenix-CSRF`.

## Two credential classes — the governed cannot edit the governor

The only project in the study that separates these is Agent Control, and it is the
whole point of a control plane.

| Class | May | May not |
|---|---|---|
| **agent** | create/submit runs it owns, read them, and **read** approvals on them | **decide any approval**; touch policies, adapters, tenants, or other principals' runs |
| **admin** | permitted tenant-scoped machine administration, including policy and adapter registration | human sign-in; Ory-only administration; Phoenix operator authority |

Separate header, separate key material: `Authorization: Bearer <token>` where the token
carries its class. An agent token presented to a policy endpoint is `403`, not `401` —
it authenticated fine, it is simply not permitted.

**An agent credential may not decide an approval.** `POST /v1/approvals/{id}/decide` with an
agent token is `403 wrong_credential_class`.

Two axes, and conflating them is a mistake worth naming because the first draft of this
paragraph made it:

- **Credential class** (`agent` | `admin`) says what a *token* may do. There are two, and
  adding a third for approvals would have been wrong.
- **Principal kind** (`human` | `agent` | `service`) records who acted. An Ory
  session binds a human principal; a governed external approval system uses its
  own service principal. The approval composite foreign key rejects agent actors.

**A human approval decision requires a current Ory-authenticated tenant admin.**
Verification, MFA and current Phoenix authority are checked independently of the
cookie's existence; authority is rechecked in the decision transaction after any
wait behind identity withdrawal. An explicitly authorized external service may
instead use the separate machine-admin path. It decides as itself, not as a human
named in the request. See ADR-0015 and the approval-authority section below.

> **Retracted 2026-08-27 (redo 3).** Two wordings stood here in turn, and both are gone.
> The first (superseded 2026-08-27) let an agent answer approvals on its own runs, which reads
> as *the requester decides* — the opposite of what an approval is for. The second (superseded
> 2026-08-27) named an approver-assignment that does not exist — **an assignee model with no
> column to hold it**, since `approvals` has `decided_by` and not `assigned_to`.
>
> Whether an agent may ever be an approver is deferred **with** the multi-party question, for
> the same reason: it needs a real organisational policy to answer, not a schema guess. See
> [§09](09-decisions.md) 7.

**Every protected data request resolves to a validated principal.** Tenant scope
comes from the Ory realm/membership resolution or the separate machine credential,
never a caller-selected body field. Tenant resources stay within that scope.
Explicit cross-tenant operator operations require an independent Phoenix operator
grant, not merely tenant administration or a machine admin token.

The old `/v1/auth/discover`, `/v1/auth/exchange`, and `/v1/identity-providers` operations are removed from the
router and generated clients. There are no deployed customer clients to preserve,
so no compatibility handlers or anonymous exceptions remain. Phoenix no longer
wires customer-ID-token verification into sign-in or exposes a human bearer-minting HTTP handler. Optional
federation must be implemented through Ory in a later release.

---

## Resources

### Agent definitions — immutable, content-addressed

```http
POST /v1/definitions
{ "name": "reviewer", "instructions": "...", "tools": [...], "extensions": [...],
  "knowledge_package_digest": "e5f6...", "state_schema": {...} }        # both optional

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

`knowledge_package_digest` and `state_schema` are optional and, when declared, participate
in the definition digest ([§03](03-canonicalisation.md) §`agent_definition`,
[`16-knowledge.md`](16-knowledge.md) §Digest participation). An undeclared field is
**absent** from the body, never `null`, so no existing digest moves.

### Knowledge packages — immutable, content-addressed

```http
POST /v1/knowledge-packages
{ "bundle_revision": "7", "sources": [{ "source_id": "tenant-kb", "commit_sha": "9ab..." }] }

201 { "digest": "e5f6...", "canon_profile": "nfc+intjson/v1" }
200 { "digest": "e5f6...", "canon_profile": "nfc+intjson/v1" }   # already existed

GET /v1/knowledge-packages/{digest}   → the manifest projection, or 404
```

Registration is **admin only** — a package is compiled from layers we operate — while the
digest is derived from the compiled bytes and never accepted from the caller, for the same
reason an adapter digest is not. Two layer stacks that compile to the same bytes **are** the
same package, so `200` and `201` differ only in whether the row already existed
([`16-knowledge.md`](16-knowledge.md) §What the digest covers).

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
{ "agent_id": "ag_1", "team_id": "tem_1", "input": { "prompt": "review the diff" } }

201 { "run_id": "01J8...", "state": "draft",
      "pin": { "definition_digest": "...", "adapter_identity": "...",
               "adapter_digest": "...", "payload_schema_digest": "...",
               "checkpoint_schema_version": 1 } }
```

The pin is **computed and returned at creation**, so a client can see exactly what its
run is bound to. An Ory human must select an authorized active team. The binding is
immutable; historical unassigned runs are not silently attributed to a team.
Machine-created runs may retain their separate, documented unassigned behavior.

```http
POST /v1/runs/{id}/submit        → 202, state=queued
POST /v1/runs/{id}/cancel        { "reason": "..." }  → 202, state=cancelling
POST /v1/runs/{id}/discard       { "reason": "..." }  → 200, state=discarded
GET  /v1/runs/{id}
GET  /v1/runs?state=waiting_input&limit=50&cursor=...
GET  /v1/runs/{id}/events?since_seq=0
GET  /v1/runs/{id}/cost
```

`GET /v1/runs/{id}/cost` returns `priced_nanos_lower_bound` and `unpriced_calls` **as a
pair**, never one without the other: a total presented alone would read as the run's cost
when some calls could not be priced ([`18-cost.md`](18-cost.md) §The cost record).

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

`decided_by` comes from the **validated actor**, never the body — an approver cannot be
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
  "integration_mode": "sdk_subprocess", "declared_capabilities": {...} }
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

### Tasks (routines) — admin only

```http
POST  /v1/tasks
{ "name": "nightly-review", "agent_id": "ag_1", "prompt": "...",
  "trigger_kind": "cron", "cron_expression": "0 2 * * *", "timezone": "Europe/London",
  "overlap_policy": "skip", "misfire_grace_seconds": 30 }        → 201

PATCH /v1/tasks/{id}          # prompt, overlap_policy, misfire_grace_seconds only
POST  /v1/tasks/{id}/pause    → 200, state=paused
POST  /v1/tasks/{id}/resume   → 200, state=active
POST  /v1/tasks/{id}/disable  → 200, state=disabled
POST  /v1/tasks/{id}/fire     → 201 fired, or 200 replayed
```

Schedule fields are **immutable**: `cron_expression` and `timezone` are inputs to the
firing key, so changing one would rename every future tick and reopen ticks already
decided. A PATCH naming either is `422 schedule_immutable`
([`11-routines.md`](11-routines.md) §Idempotent firing).

There is **no route that writes a `task_firings` row or sets `runs.task_id` directly.** A
firing is created only inside the transaction that inserts the firing record, and the
absence of a route is the enforcement — the same argument §05's system transitions use.

**Amended 2026-08-30 (OQ-099).** `POST /v1/tasks/{id}/fire` on a `trigger_kind = 'webhook'`
task is the one route in this document that does **not** take the admin bearer token: it
authenticates with the task's own `fire_key_ref` key ([`11-routines.md`](11-routines.md)
§Schema, [`14-credentials.md`](14-credentials.md)), presented however the relay convention
requires (e.g. a header), and is otherwise unauthenticated. Every other `trigger_kind`'s
`/fire` keeps the admin-only rule above.

### Task catalogue — readable by any authenticated class

```http
GET /v1/tasks
GET /v1/tasks/{id}
GET /v1/tasks/{id}/firings?since=...
```

An agent may need to know why it is running. Registration and lifecycle stay admin-only for
the same reason policy registration does; reading is not the governed editing the governor.

### Credentials — admin only

```http
POST   /v1/credentials
{ "name": "github-app", "kind": "oauth2", "flow": "on_behalf_of_token_exchange",
  "egress_host": "api.github.com", "holder_principal_id": "pr_1" }   → 201

GET    /v1/credentials
GET    /v1/credentials/{id}
POST   /v1/credentials/{id}/revoke   → 200, revoked_at set
```

**No route returns `secret_ref`, `material_ref`, or any placeholder value**, in any
response, at any credential class — a route that can read the pointer is a route that can
be used to find the secret ([`14-credentials.md`](14-credentials.md) §Credentials never
enter the sandbox).

The create route **refuses** a row whose `egress_host` names a control-plane host,
`422 credential_targets_control_plane`. That refusal is the mechanism behind §14's
invariant "a credential cannot be minted against the control plane": without it the rule
is prose, because nothing else in the schema forbids the value.

Revocation is a **state**, never a delete (`01-schema.md` §Identity, `revoked_at`): a revoked credential's
issuances remain readable, which is what makes "what did this reach, and when did it stop"
answerable.

### Registration surfaces this document is owed and does not yet carry

**Added 2026-09-03 (OQ-154).** [`10-work-bundles.md`](10-work-bundles.md) §Preamble assigns
registration of bundles, verifiers and resources to this document. It is not here, and it is
not in `contracts/openapi.yaml` either — nor is any route for **knowledge sources**, the git
remotes [`16-knowledge.md`](16-knowledge.md) §Schema stores in `knowledge_sources`, as distinct
from `POST /v1/knowledge-packages`, which registers the compiled artifact and not the source it
was compiled from. Naming the gap here rather than leaving it to be discovered is the point:
every customer-onboarding step in the platform is currently asserted by one document and
implemented by none.

Two constraints bind whatever fills it, and both come from rules already stated:

| Constraint | Source |
|---|---|
| Registration is **admin class**; an agent credential may not register what governs it | §Two credential classes — the governed cannot edit the governor |
| Admitting a thing is not activating it — a registered server, bundle or source is reachable by nothing until a **pinned definition** binds it | `01-schema.md` §Agent definition (`tools`/`extensions` are bindings carrying `artifact_digest`), `07-adapter-protocol.md` handshake step 1 |

MCP registry and admission operations are now declared in the resource inventory
below. That does not fill the separate bundle, verifier, resource or knowledge-source
registration gaps above. A compiled package endpoint is not source onboarding,
and a declared route is not evidence that its complete authorization matrix ships.

---

## Approval authority — what this API does not do

`POST /v1/approvals/{id}/decide` records **one** attributable terminal decision. There is **no
quorum, no m-of-n, and no separation-of-duties enforcement**. There is also **no self-approval
prohibition in v0.1**: §09 7 defers it with the multi-party question.

The decision must identify an authorized human or governed external service,
pinned by the composite actor-kind foreign key. Ory establishes a human identity;
Phoenix establishes current tenant-admin authority. A service acts as its own
principal through the machine boundary. Neither path accepts a request-body
approver identity. This preserves ADR-0015 amendment 4's external-system model,
including an external ticket reference in the rationale, without creating quorum
or separation-of-duties semantics that are not implemented.

## Idempotency

`Idempotency-Key` is **required** on POST /v1/runs and POST /v1/approvals/{id}/decide and
POST /v1/tasks/{id}/fire. It is optional elsewhere. Machine keys are scoped `(tenant_id, endpoint, key)` and retained 24h. Human run creation additionally namespaces the endpoint by the stable Phoenix principal, so another human cannot replay its response. Replays still require current run access; a rotating Ory session does not create a new idempotency owner.

A replay returns the original response with `Idempotency-Replayed: true`. A key reused
with a *different* body is `422` — silently returning the first response would hide a
client bug.

One narrowing, stated by [`11-routines.md`](11-routines.md) §Who may create: on
POST /v1/tasks/{id}/fire the key is also the firing key's `value`, and the `task_firings`
record outlives the 24-hour retention. Past that window a reused key **replays the recorded
firing** rather than being refused `422 idempotency_key_reused` — the route carries no
request body beyond the task it names, so a reused key and a changed body cannot be told
apart, and refusing would strand a legitimate retry.

---

## Request headers read on every route

`traceparent` and `tracestate` are read on **every** route as W3C Trace Context, and the
value is the full header — a bare trace id does not propagate
([`19-telemetry.md`](19-telemetry.md) §Propagation hop 1). Neither is ever an
authorization input: `tenant_id` comes from the validated Ory membership or machine credential and nothing else, so a forged
`traceparent` joins a trace and buys nothing.

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
| 422 | `trigger_kind_unsupported` | `trigger_kind: "event"` has no referent in v0.1 (11) |
| 422 | `overlap_policy_unsupported` | `overlap_policy: "allow"` is reserved; no defined concurrency behaviour (11) |
| 422 | `schedule_immutable` | `cron_expression` / `timezone` cannot be PATCHed; the firing key derives from them (11) |
| 422 | `credential_targets_control_plane` | a `credentials` row whose `egress_host` names a control-plane host (14) |
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

`Last-Event-ID` is a declared header parameter on the route
(`contracts/openapi.yaml`, `components/parameters/LastEventId`). *(Added 2026-09-04:
this section required the behaviour while the contract declared no parameter for it, so
a server generated from the contract — which is how the Go server is built — could not
see the header at all, and the resume failed silently.)*

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

## Ory-only team administration

These operations require a current Ory-authenticated tenant administrator with
MFA, the configured exact browser origin, and Phoenix's session-bound CSRF token.
A machine `admin` credential is not a substitute. Actor tenant, realm and
principal come from the authenticated session, never from request fields.

```
POST /v1/teams
  { "slug": "delivery", "display_name": "Delivery", "steward_principal_id": "pri_...", "reason": "..." }
  -> 201, Team
PUT /v1/teams/{id}/members/{principal_id}
  { "role": "member|steward", "reason": "..." }
  -> 200, { "principal_id": "pri_...", "role": "member|steward" }
POST /v1/teams/{id}/members/{principal_id}/remove
  { "reason": "..." }
  -> 204
```

Creation requires an active Ory-enrolled human in the same tenant and realm as
initial steward. The lowercase, hyphen-separated key is immutable. Membership
grants accept only `member` or `steward`, never tenant administration or a new
historical `owner` grant. Invite and enroll an unavailable person first.

Each effective change commits with an attributed administrator audit event.
Repeated identical membership grants and already-absent removals are no-ops,
not duplicate audit events. Removing or demoting a steward requires another
active enrolled human steward; concurrent requests must preserve that invariant.
Archived teams cannot receive new or changed membership grants.

Refusals distinguish `403` authority failure, `404` tenant-scoped unavailable
team or human, `409` immutable-key/last-steward/archive conflict, and `422` invalid
input. Storage and audit failures fail closed. Team removal withdraws only that
team's access on subsequent request/stream checks; it does not log the person out
of Ory, remove other memberships, or erase historical actor identity. Account-wide
security offboarding remains a separate operation.

## Additional declared resource operations

These operations supplement the detailed resource contracts above. The OpenAPI
schemas define request and response shapes; `20-human-auth.md` defines the human
boundary. Authentication alternatives are not grants: an Ory session still needs
current Phoenix authority, and a machine admin is not a platform operator. The
complete per-resource authorization matrix remains a release gate, not something
this inventory alone proves.

### Inventory and team reads

```http
GET /v1/agents
GET /v1/teams
GET /v1/teams/{id}/members
GET /v1/knowledge-layers
GET /v1/knowledge-packages
GET /v1/skills
GET /v1/mcp-servers
GET /v1/cost
```

Team and membership reads apply current human membership scope; an ungranted team
is indistinguishable from a missing team. Catalogue entries, compiled artifacts
and cost projections do not themselves confer permission to execute an agent or
use a connection. Tenant cost reports retain the priced-lower-bound/unpriced pair.

### Governance and run-linked projections

```http
GET /v1/policies
GET /v1/policies/{id}
GET /v1/decisions
GET /v1/trust/findings
GET /v1/claims/{id}
POST /v1/claims/{id}/vet
POST /v1/claims/{id}/withdraw
GET /v1/inputs
POST /v1/inputs/{id}/answer
GET /v1/effects
GET /v1/reports
GET /v1/reports/{id}
```

Vetting, answering input and deciding an approval are distinct attributed acts,
not interchangeable status edits. Human approval/effect/report lists filter by
current run access before limiting results; report rendering checks the linked
run before loading a private visual. An empty list is an array, never `null`.

### Connections, people and tenant administration

```http
GET /v1/connections
POST /v1/connections/{id}/test
POST /v1/connections/{id}/rotate
GET /v1/admin-events
GET /v1/principals
POST /v1/principals/{id}/revoke
POST /v1/principals/{id}/restore
GET /v1/retention
GET /v1/settings
PUT /v1/settings
```

A connection test is not a credential rotation. Human steward testing is limited
to the granted, active team; rotating a shared credential remains administrative.
Principal offboarding is separate from team removal: it withdraws tenant-wide
access and requires durable Ory session cleanup. Restoration must not reactivate
old sessions. Settings and administrative events retain actor attribution, and
retention reports do not silently perform deletions.

### Phoenix operator operations

```http
GET /v1/tenants
GET /v1/tenants/{id}/provisioning
```

These require an explicit live Phoenix operator grant in the operator realm.
A customer tenant administrator cannot enumerate the platform directory or use
the provisioning path to cross the tenant boundary. An admin bearer alone is
not operator authority; the contract declares the Ory credential and the distinct
`platform-operator` requirement.

### Onboarding evidence

```http
GET /v1/onboarding/candidates
POST /v1/onboarding/candidates/{id}/decide
GET /v1/onboarding/rescan
POST /v1/onboarding/sessions
GET /v1/onboarding/scans/{id}/quality
GET /v1/onboarding/findings
POST /v1/onboarding/sign-off
GET /v1/onboarding/gaps
```

Candidate decisions, scan quality, attributed work sessions and sign-off are
separate evidence records. Accepting a candidate or signing off a scan does not
establish a human login, link an Ory identity, or grant team membership.

### Governed skill and MCP mutations

```http
POST /v1/agents/{id}/skills
POST /v1/mcp-servers
POST /v1/mcp-servers/{id}/revoke
POST /v1/mcp-servers/{id}/drift
```

Admission is not activation. A registered server or skill becomes executable only
through the appropriate pinned agent binding. Revocation and drift retain the
historical identity needed to explain previous execution.
