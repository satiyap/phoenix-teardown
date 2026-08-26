# Teardown — AWS Bedrock AgentCore

| | |
|---|---|
| Repo | https://github.com/aws/bedrock-agentcore-sdk-python |
| Commit read | `826416a2493131f79137c77575bc1e10b9589d56` (2026-08-25) |
| Version tested | `bedrock-agentcore 1.22.0` |
| License | Apache-2.0 |
| Read on | 2026-08-26 |
| Evidence class | **A** (recon said B) |
| Depth | targeted (`D` identity/versioning/revocation, `I` tools, `J` IAM, `K` sandbox) |
| Runtime class | `hybrid` — an SDK over managed AWS control-plane and data-plane services |

A **targeted pass** scoped to identity and IAM, because that is what AWS is
architected to be good at and `D9` (revocation) plus `S1` (delegated authority) were
the weakest areas across eleven projects.

It delivers the strongest answer in the study to both, and one thing I did not
expect: **Cedar as the policy language**, which gives ADR-0013 its first real
precedent for verifiable policy — and `start_policy_generation`, which is the
closest thing anyone has to shadow-mode policy review.

Caveat stated up front: this is a **client SDK over managed services**. Much of the
architecture lives server-side where I cannot read it. Every claim below is from
the SDK surface — the API shapes, the enums, the documented semantics — not from an
implementation I inspected. That is a weaker class of evidence than the nine deep
passes and is marked as such throughout.

---

## 1. What problem it solves

Running agents on AWS with AWS's identity, authorization, memory, and gateway
services attached. The SDK is thin by design: it wraps `bedrock-agentcore-control`
(control plane) and `bedrock-agentcore` (data plane) boto3 clients and adds
ergonomics — decorators, polling, snake_case conversion.

## 2. Core architectural thesis

**An agent is a workload with its own identity, and everything it does is
authorized against a formally specified policy.**

Two structural commitments make it distinctive:

1. **The agent has a principal of its own** — a *workload identity* — which can
   obtain tokens as itself, on behalf of a user, or via a federated JWT.
2. **Authorization is Cedar**, not a bespoke rule engine. Policies are
   `permit(principal, action, resource)` statements in a language with a formal
   semantics and an existing verification toolchain.

## 3. Resource / object model

Inferred from the SDK's method allow-lists rather than from a schema.

```text
Workload (the agent)          has its own identity and access tokens
 └── workload_access_token    3 variants: bare | for_jwt | for_user_id

CredentialProvider            CRUD resources, control plane
 ├── OAuth2CredentialProvider create / get / list / update / delete
 └── ApiKeyCredentialProvider create / get / list / delete

PolicyEngine                  create / get / list / update / delete
 └── Policy                   Cedar: permit(principal, action, resource)
      └── PolicyGeneration    natural language → reviewable policy ASSETS

Memory                        create / update / delete
 ├── strategies[]             SEMANTIC | SUMMARIZATION | USER_PREFERENCE | CUSTOM
 │                            (+ *_OVERRIDE variants)
 └── MemoryRecord             addressed by hierarchical NAMESPACE
                              /org/MyOrg/ · /actor/Jane/
                              /strategies/{id}/actors/{actorId}/

Gateway, KnowledgeBase, Tools, Payments, Evaluation, ConfigBundle
Runtime                       PingStatus: Healthy | HealthyBusy
```

**Verified live** (1.22.0): `auth_flow` is
`Literal['M2M', 'USER_FEDERATION', 'ON_BEHALF_OF_TOKEN_EXCHANGE']`; the policy
client allow-lists 14 control-plane methods; identity data-plane methods are
`get_resource_api_key`, `get_resource_oauth2_token`,
`get_workload_access_token_for_jwt`, `get_workload_access_token_for_user_id`.

## 4. Runtime model

Managed. The SDK provides an app harness (`runtime/app.py`), A2A and AG-UI
adapters, a shell, tracing, and a client. Execution happens in AWS.

`PingStatus` distinguishes **`Healthy`** from **`HealthyBusy`**
(`runtime/models.py:9-13`), plus a `force_healthy` task action. That distinction
matters and almost nobody makes it: "alive and idle" and "alive but working" are
different answers to a health probe, and conflating them is how a supervisor either
kills busy workers or fails to detect stuck ones. Google AX's readiness gate treats
reachable-without-health-service as ready; this is the more precise model.

## 5. Execution lifecycle

Not modelled in the SDK beyond task actions and ping status. No Task/Run split
visible, no state machine.

**`clientToken` appears as an explicit idempotency token** on policy generation
(`policy/client.py:250`), which is the AWS-wide convention. Worth noting for
ADR-0014: the pattern of a caller-supplied idempotency token on every mutating
control-plane call is exactly the effect-ledger key, standardised across an entire
platform rather than per-feature.

## 6. Durability model

Server-side and not inspectable. The SDK contributes `wait_until` /
`wait_until_deleted` polling helpers with `WaitConfig`, and a `_FAILED_STATUSES`
set (`CREATE_FAILED`, `UPDATE_FAILED`, `DELETE_FAILED`) — so resources have
asynchronous lifecycles with explicit failure states, and the SDK polls rather than
pretending operations are synchronous.

`wait_until_deleted` as a distinct helper is a small honesty: deletion is
asynchronous too, and code that assumes otherwise races.

## 7. Agent identity and lifecycle

**The strongest agent identity story in the study, and the reason for this pass.**

The agent is a **workload** with its own identity, and it can obtain three kinds of
token (`services/identity.py:140-155`):

| Call | Meaning |
|---|---|
| `get_workload_access_token(workload_name)` | the agent acting **as itself** |
| `get_workload_access_token_for_jwt(workload_name, user_token)` | the agent acting **for a federated user**, via their IdP token |
| `get_workload_access_token_for_user_id(workload_name, user_id)` | the agent acting **for a known user** |

That is a genuine agent principal with a delegation model attached, and it is what
ADR-0001's rebased rationale asks for: identity exists *because* delegation, policy
attachment, and audit need it. AG2 has agent identity (`Passport`) without
delegation; Omnigent has delegation (RFC 8628) without an agent principal; **AgentCore
has both.**

`UserTokenIdentifier` and `UserIdIdentifier` are distinct model types, so "which
user" is never a bare string in the type system.

**Revocation.** Credential providers are full CRUD resources including
`delete_oauth2_credential_provider` and `delete_api_key_credential_provider`.
Deleting the provider revokes the agent's ability to obtain that credential — so
revocation exists **at the credential level**, and asynchronously
(`wait_until_deleted`). Still no *agent version* and no agent deprecation
lifecycle, so `D4` remains absent and `D9` is `implicit`: you can revoke what an
agent can reach, not the agent itself.

## 8. Multi-agent communication

Not in the SDK. `runtime/a2a.py` provides A2A protocol support — the fourth
independent instance of A2A-as-edge-adapter, alongside AG-UI (`runtime/ag_ui.py`)
and a proposal doc for it. AG2 remains the only durable internal messaging.

## 9. Human interaction model

Present only through OAuth: `USER_FEDERATION` flow with `on_auth_url` callback and
a `TokenPoller`, so a human completes an authorization in a browser while the agent
polls. `custom_state` exists so "applications can verify the validity of callbacks
to callback_url" — CSRF protection on the consent redirect, which is the kind of
detail that distinguishes a real OAuth implementation from a sketch.

No approval resource, no elicitation model, no notion of a human decision on a tool
call. HumanLayer remains the answer for `C11`.

## 10. Context and memory

The second real memory *service* in the study after ADK, and it is more structured.

**Typed strategies** (`memory/constants.py:13-35`):

```text
SEMANTIC | SUMMARIZATION | USER_PREFERENCE | CUSTOM
   plus SEMANTIC_OVERRIDE, USER_PREFERENCE_OVERRIDE, ...
```

`USER_PREFERENCE` as a *distinct kind of memory* is new to the study. Semantic
recall, conversation summarisation, and durable user preferences have different
write patterns, different lifetimes, and different privacy consequences, and every
other project either lumps them together or has none of them.

**Hierarchical namespaces** are the addressing model
(`memory/client.py:131-134`, `constants.py:76-78`):

```text
/org/MyOrg/
/actor/Jane/
/strategies/{memoryStrategyId}/actors/{actorId}/
```

With `namespace` for an exact match and `namespace_path` for a prefix query. This
generalises ADK's four fixed scopes (`app:`/`user:`/`temp:`/session) into an
arbitrary hierarchy — more flexible, and correspondingly less enforceable, since a
path convention is not a schema. ADK's four scopes cannot be misspelled; a namespace
can.

## 11. Tools and capabilities

`tools/`, `gateway/` (an MCP-style tool gateway), `knowledge_base/`, and
`payments/`. The gateway is the interesting piece architecturally — a managed
service that fronts tools, which is where credential injection and policy
enforcement belong.

No declared capability model.

## 12. Security and IAM

**The strongest in the study, and the clearest single finding of this pass.**

**Cedar is the policy language** (`policy/client.py:1,35`):

```python
client.create_policy(
    policy_engine_id=engine["policyEngineId"],
    name="my_policy",
    definition={"cedar": {"statement": "permit(principal, action, resource);"}},
)
```

Cedar matters for reasons specific to this study's ADRs. It has a formal semantics
and an analysis toolchain, so a policy set can be *reasoned about* rather than only
executed — you can ask whether one policy set is more permissive than another. That
is precisely the capability ADR-0013's shadow-comparison half needs, and eleven
projects offered nothing for it. Choosing an existing verifiable language over a
bespoke rule DSL is the same instinct as ADR-0010 choosing OTel over a proprietary
trace format.

And `principal` is a first-class term in the language, which pairs exactly with the
workload identity from §7: the agent is a principal Cedar can name.

**`start_policy_generation`** (`policy/client.py:240-290`) turns natural language
into Cedar policies as **reviewable assets**: `content={"rawText": "allow
refunds..."}` → poll to `GENERATED` → `list_policy_generation_assets` →
`generatedPolicies`. The policy is an artefact you inspect before it takes effect.

That is the closest thing in the study to shadow-mode policy work: not "run both and
compare decisions", but "produce the candidate and review it as data". A weaker form
of the same instinct, and the only precedent for any of it.

**Three delegation flows**, verified live:
`M2M | USER_FEDERATION | ON_BEHALF_OF_TOKEN_EXCHANGE`. Naming
on-behalf-of token exchange as a distinct flow — rather than treating delegation as
a special case of user auth — is more precise than anything else in the study.

**Control plane and data plane are separate clients with separate allow-lists.**
`IdentityClient` holds `_ALLOWED_CP_METHODS` (credential provider CRUD) and
`_ALLOWED_DP_METHODS` (token retrieval), and `__getattr__` forwards only
allow-listed names, raising `AttributeError` with a pointer to the boto3 docs
otherwise. So administration and use are different surfaces with different
permissions, and the SDK cannot accidentally expose an unvetted control-plane call.

## 13. Sandboxing

Managed and not inspectable from the SDK. There is a `runtime/shell` and a code
interpreter in the wider AgentCore product, but the SDK surface says little. Not
assessable — recorded as `unknown` where genuinely unknown rather than `absent`.

## 14. Orchestration

Not the SDK's concern. Task actions and ping status only.

## 15. Observability

`runtime/tracing.py` and a user-agent suffix mechanism (`build_user_agent_suffix`)
for attributing SDK calls to an integration source. Real telemetry is CloudWatch
and X-Ray, server-side. No OTel in the SDK.

`integration_source` for user-agent attribution is a small good idea: a managed
service can tell which client library generated a call, which is how you deprecate
a client version with data rather than by announcement.

## 16. Multi-tenancy

AWS accounts and regions are the tenancy boundary, plus memory namespaces
(`/org/MyOrg/`). Not modelled in the SDK because IAM already provides it — the
strongest form of tenancy in the study by inheritance rather than by design.

## 17. Protocols and APIs

Control plane + data plane boto3 clients, **A2A** (`runtime/a2a.py`), **AG-UI**
(`runtime/ag_ui.py`, plus a proposal doc), and an MCP-style gateway. Endpoint
overrides (`CP_ENDPOINT_OVERRIDE`, `DP_ENDPOINT_OVERRIDE`) for testing.

Fourth independent instance of A2A as an edge adapter rather than an internal model.

## 18. Storage

Managed services throughout. The SDK models namespaces and strategies; storage is
AWS's.

## 19. Deployment architecture

AWS-managed. The SDK runs in your process or in an AgentCore runtime.

## 20. OSS / license / commercial model

Apache-2.0 SDK over paid managed services. Unlike ADK — where every interface has a
working in-memory implementation — **there is no local implementation of anything
here.** No AgentCore account means no memory, no identity, no policy engine.

That is the least favourable open-core position in the study: the SDK is open, and
it is useless without the service. ADK proved you can ship the interfaces *and* a
local implementation while still selling the managed one.

Verdict: **REFERENCE_ONLY.** The *designs* — workload identity, three token
variants, Cedar, typed memory strategies, namespace addressing, `Healthy` vs
`HealthyBusy` — are all portable. The code is a thin client over services we cannot
run.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | **first_class_answer** | **Best answer in the study.** A workload identity for the agent, three token variants (as itself / for a federated JWT / for a known user id), three named flows including `ON_BEHALF_OF_TOKEN_EXCHANGE`, `custom_state` for callback validation, and Cedar policies where `principal` is a first-class term. Omnigent's RFC 8628 gives a *human* delegated grant; this gives the *agent* a principal and a way to act on someone's behalf. |
| S2 Torn side effect | **inferable** | No effect ledger in the SDK, but `clientToken` as a caller-supplied idempotency token on mutating control-plane calls is the AWS-wide convention — the ADR-0014 key, standardised platform-wide rather than per-feature. |
| S3 Upgrade mid-flight | undefined | No agent version, no pin. Twelve projects. |
| S4 Concurrent memory write | **inferable** | Namespaces partition memory by org and actor, and typed strategies separate semantic recall from summarisation from user preferences — so concurrent writes to *different kinds* of memory do not contend. Weaker than ADK's schema-validated scopes, since a namespace path is a convention rather than a constraint. |
| S5 Cancellation tree | undefined | Task actions exist; no cancellation semantics visible. |
| S6 Silent context loss | **inferable** | `SUMMARIZATION` is a declared memory strategy, so compaction is a configured, named behaviour rather than a side effect — but no loss signal is emitted. |
| S7 Poison message | undefined | Not visible in the SDK. |
| S8 Tenant leak | **inferable** | AWS accounts, regions, and IAM are the boundary, plus `/org/…` namespaces. Strong by inheritance; nothing SDK-side enforces it. |
| S9 Runaway spend | undefined | A `payments/` module exists but is not a budget control. AWS billing is the answer, which is not an agent-level one. |
| S10 Zombie sandbox | **inferable** | `PingStatus.Healthy` vs `HealthyBusy` distinguishes idle-alive from working-alive, and `force_healthy` is an explicit recovery action. The most precise health model in the study, though reaping is server-side. |

## 22. Strongest ideas

1. **A workload identity for the agent itself**, so the agent is a principal rather
   than a bearer of someone else's credentials.
2. **Three token variants** — as itself, for a federated JWT, for a known user id —
   making "on whose behalf" an explicit dimension of every token request.
3. **`ON_BEHALF_OF_TOKEN_EXCHANGE` as a named flow**, distinct from user
   federation.
4. **`UserTokenIdentifier` / `UserIdIdentifier` as distinct types**, so "which
   user" is never an untyped string.
5. **Cedar as the policy language** — formal semantics, existing verification
   tooling, `principal` as a first-class term. Choosing a verifiable standard over
   a bespoke DSL.
6. **`start_policy_generation`**: natural language → Cedar policies as *reviewable
   assets* you inspect before they take effect.
7. **Control-plane / data-plane split with per-plane method allow-lists**, so
   administration and use are different surfaces.
8. **`__getattr__` forwarding only allow-listed names**, with an error naming where
   to look — an SDK that cannot accidentally expose an unvetted API.
9. **Typed memory strategies**, with `USER_PREFERENCE` as a kind distinct from
   semantic recall and summarisation.
10. **Hierarchical memory namespaces** with exact-match and prefix-query variants.
11. **`PingStatus.Healthy` vs `HealthyBusy`** — idle-alive and working-alive are
    different answers.
12. **`wait_until_deleted` as a distinct helper**, acknowledging that deletion is
    asynchronous.
13. **Explicit `_FAILED_STATUSES`** (`CREATE_FAILED`, `UPDATE_FAILED`,
    `DELETE_FAILED`) so failure is a terminal state, not a timeout.
14. **`clientToken` idempotency as a platform-wide convention** rather than a
    per-feature afterthought.
15. **`custom_state` on the OAuth flow** for callback validation.
16. **`integration_source` in the user-agent**, so a service can attribute calls to
    a client library.

## 23. Weakest architectural choices

1. **No local implementation of anything.** Without an AWS account the SDK does
   nothing — the least favourable open-core position in the study, and ADK proves
   it was avoidable.
2. **Architecture is server-side and unreadable**, so most of this teardown is
   inference from API shapes. Weaker evidence than the nine deep passes.
3. **No agent versioning**; revocation is credential-level, not agent-level.
4. **Namespaces are conventions, not constraints** — `/actor/Jane/` can be
   misspelled in a way ADK's `user:` prefix cannot.
5. **No approval or elicitation model** beyond OAuth consent.
6. **No OTel in the SDK**; observability is CloudWatch and X-Ray.
7. **Total AWS coupling** — deeper than Cloudflare's, because even identity and
   policy are managed services rather than libraries.

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| Workload identity for the agent | **ADOPT_AS_STANDARD** | The agent must be a principal; best precedent found |
| Three token variants (self / for-JWT / for-user) | **ADOPT_AS_STANDARD** | Makes "on whose behalf" explicit per request |
| `ON_BEHALF_OF_TOKEN_EXCHANGE` as a named flow | ADOPT_AS_STANDARD | Delegation is not a special case of login |
| Typed user identifiers | REUSE (pattern) | "Which user" should not be a bare string |
| **Cedar as the policy language** | **INTEGRATE** | Formal semantics + verification tooling; the only path to ADR-0013's shadow half |
| Policy generation as reviewable assets | REUSE (pattern) | Inspect the candidate before it takes effect |
| Control/data plane split with allow-lists | ADOPT_AS_STANDARD | Administration and use are different surfaces |
| Allow-listed dynamic forwarding | REUSE (pattern) | An SDK that cannot leak an unvetted API |
| Typed memory strategies incl. `USER_PREFERENCE` | **ADOPT_AS_STANDARD** | Different memory kinds have different lifetimes and privacy |
| Hierarchical namespaces with prefix queries | REUSE (pattern) | Use *with* ADK's enforced scopes, not instead |
| `Healthy` vs `HealthyBusy` | **ADOPT_AS_STANDARD** | Idle-alive ≠ working-alive; matters for reaping |
| `wait_until_deleted` | REUSE (pattern) | Deletion is asynchronous |
| Explicit `*_FAILED` terminal statuses | ADOPT_AS_STANDARD | Failure should be a state, not a timeout |
| `clientToken` idempotency convention | ADOPT_AS_STANDARD | Platform-wide, not per-feature — feeds ADR-0014 |
| `custom_state` callback validation | REUSE | CSRF protection on consent redirects |
| Namespaces as the *only* scoping | BUILD | Reject alone; pair with enforced scopes |
| SDK with no local implementation | BUILD | Reject; ADK's in-memory siblings are the standard |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | **confirms strongly** | The best vindication of the *rebased* rationale. Phase 2 concluded agent identity is required for **delegation, policy attachment, and audit** rather than durability — and AgentCore is exactly that: a workload identity whose entire purpose is obtaining scoped tokens and being named as a Cedar `principal`. Nothing about durability requires it; everything about authorization does. |
| ADR-0002 | neutral | No Task/Run split visible in the SDK. |
| ADR-0003 | confirms | No durable agent-to-agent messaging; A2A is an edge adapter. AG2 remains the sole answer. |
| ADR-0004 | neutral | A client SDK, not an adapter contract. |
| ADR-0005 | confirms | A gateway service fronts tools; MCP-shaped, no capability model. |
| ADR-0006 | **confirms** | **Fourth independent instance** of A2A as an optional edge adapter alongside an internal model (with AG2, ADK, and now AG-UI here too). Settled. |
| ADR-0007 | **confirms strongly — closes the loop** | The amendment split `Principal` from `Credential` because ADK had credentials without principals and HumanLayer had decisions without principals. **AgentCore has both halves properly**: a workload identity (principal) *and* credential providers as CRUD resources (credential), with three flows connecting them. This is the reference shape for our ADR-0007. |
| ADR-0008 | **confirms and extends** | Second real memory service. Extends ADK's contribution with **typed strategies** — `SEMANTIC`, `SUMMARIZATION`, `USER_PREFERENCE`, `CUSTOM` — so memory *kind* is declared, not implied. `USER_PREFERENCE` as its own kind is new: durable preferences have different lifetime and privacy properties from semantic recall. Namespaces are more flexible than ADK's fixed scopes and correspondingly less safe; **use both — enforced scopes for the kinds we own, namespaces for hierarchy within them.** |
| ADR-0009 | unknown | Sandboxing is managed and not visible from the SDK. Recorded as `unknown`, not `absent`. |
| ADR-0010 | neutral | No OTel in the SDK; CloudWatch/X-Ray server-side. `integration_source` user-agent attribution is a nice minor idea. |
| ADR-0011 | confirms (negatively) | No agent version, no pin. **Twelve projects.** |
| ADR-0012 | neutral | No declared capability model. |
| ADR-0013 | **confirms strongly — the first real precedent** | Cedar changes this ADR from aspiration to plan. A formally specified policy language with existing analysis tooling means "is policy set B more permissive than A" is a *tractable question*, which is what shadow comparison needs. Plus `start_policy_generation` producing candidate policies as reviewable assets — the only instance in twelve projects of treating a policy as something you evaluate before enforcing. **Amend ADR-0013 to adopt Cedar rather than a bespoke rule engine.** |
| ADR-0014 | **confirms** | `clientToken` on mutating control-plane calls is the effect-ledger key as a *platform-wide convention*. Third precedent, and the most consistent: Cloudflare has explicit keys on durable work, AG2 has causation-based dedupe on replies, AWS applies caller-supplied idempotency tokens uniformly. **The lesson is uniformity — one convention across every mutating operation beats three mechanisms in three subsystems.** |
| ADR-0015 | neutral | No approval resource; human interaction is OAuth consent only. |

**Two amendments to make.**

1. **ADR-0013 adopts Cedar.** I had assumed a bespoke policy evaluator with a
   shadow-comparison mode bolted on. Cedar gives formal semantics, an analysis
   toolchain, and `principal`/`action`/`resource` as language primitives that align
   with ADR-0007's split. Writing our own DSL would mean building the verification
   story from nothing — the same mistake as inventing a trace format instead of
   using OTel.

2. **ADR-0008 gains declared memory *kinds*.** ADK gave us four *scopes* (who can
   see it, how long it lives). AgentCore adds orthogonal *kinds* (`SEMANTIC`,
   `SUMMARIZATION`, `USER_PREFERENCE`, `CUSTOM`) — what sort of thing it is, and
   therefore how it is written and expired. Scope and kind are independent
   dimensions, and our Recall interface needs both.

**One caveat on evidence class.** Recon called this class B and I upgraded it to A
because the identity and policy modules are substantive and verifiable. But it is
still a client over managed services, so §13, §14 and §6 rest on absence of
*SDK surface* rather than absence of *capability*. Where I could not tell, the fact
is `unknown` rather than `absent` — which is the distinction this whole study is
built on, and the first project where it applied at subsystem scale.

## 26. Open questions

- Does AgentCore's Cedar integration expose policy *analysis* (equivalence,
  permissiveness comparison), or only evaluation? That determines whether Cedar
  actually delivers ADR-0013's shadow-comparison half or merely makes it possible.
  (→ OQ-033)
- Is there an agent-level revocation — disabling a workload identity outright —
  rather than only deleting its credential providers? (→ OQ-034)
- **Partly answered by reading the helper.** Authorization is server-side and not
  visible, but the SDK *constrains the query shape* in a way that matters:
  `build_namespace_params` requires exactly one of `namespace` (exact match) or
  `namespace_path` (prefix), rejects both-or-neither, and — the important part —
  **refuses wildcards outright**: `"Wildcards (*) are not supported in namespaces."`
  (`_utils/namespace.py:18-25`). So `/actor/*/` cannot be used to sweep every
  actor's memory. That is a real narrowing of the blast radius even though the path
  itself remains a convention rather than a schema. Whether the service authorizes
  a *named* namespace against the caller is still unknown. Also of note:
  `resolve_namespace_templates` handles a deprecated `namespaces` kwarg alongside a
  new `namespace_templates` one, emitting a `DeprecationWarning` — the same
  one-deprecation-window discipline ADR-0010 adopted from Pydantic AI, applied to an
  API parameter. (→ OQ-035)
