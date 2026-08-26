# Teardown — Agent Control

| | |
|---|---|
| Repo | https://github.com/agentcontrol/agent-control |
| Commit read | `7cb21af33e46ae5122288acc92d8ce5b3f7159e7` (2026-08-21) |
| Version tested | `agent-control-sdk` (PyPI) |
| License | Apache-2.0 |
| Read on | 2026-08-26 |
| Evidence class | A |
| Depth | targeted (`I8`, `J10`, `N` tenancy, `L8`) |
| Runtime class | `hybrid` — a policy control plane external to the agent |

The final targeted pass, scoped to policy enforcement, tenancy, and `L8`
(compensation) — the last remaining universal gap.

Its self-description is exactly the target: "Centralized agent control plane for
governing runtime agent behavior at scale." And it delivers the one thing
ADR-0013 needed and fifteen projects had not provided: **`observe` as a
first-class control action** — shadow mode, shipped.

---

## 1. What problem it solves

Enforcing runtime guardrails on agents you did not write, without changing their
code. From the README: "Enforce runtime guardrails through a centralized control
layer—configure once and apply across all agents… evaluates inputs and outputs
against configurable rules to block prompt injections, PII leakage, and other risks
without changing your agent's code."

It is the only project in the study whose *entire* purpose is the policy layer.

## 2. Core architectural thesis

**Policy is a control plane, not a library: controls are runtime-configurable
resources bound to targets, and an evaluated control can deny, steer, or merely
observe.**

Three commitments follow:

1. **"Update without redeploying."** Controls live in the server and are managed
   via API or UI, so a policy change does not require an agent release.
2. **A three-way outcome.** `deny | steer | observe` rather than allow/deny.
3. **A `@control()` decorator** as the integration point, wrapping a model or tool
   call, with the agent registered against the control plane.

## 3. Resource / object model

```text
Namespace (namespace_key)     the tenancy/scoping boundary
 ├── Agent                     registered against the control plane
 ├── Control                   the policy definition
 │    ├── ConditionNode        RECURSIVE boolean tree:
 │    │    ├── leaf            (selector + evaluator) — both required
 │    │    ├── and[]           at least one child
 │    │    ├── or[]            at least one child
 │    │    └── not             single child
 │    └── action
 │         ├── decision        deny | steer | observe
 │         └── steering_context  {message} — required for composite steer
 └── ControlBinding            (namespace_key, target_type, target_id,
                                control_id, enabled, created_at, updated_at)

Step                          the evaluated payload; selectors use dot-notation
                              paths: 'input', 'input.query', 'context.user_id'
Evaluator                     builtin (regex, list, JSON, SQL) or contrib
ControlExecutionEvent         observability; plus ControlStats, TimeseriesBucket
```

**Verified live** against the published SDK:

```text
canonical actions: ['deny', 'steer', 'observe']
legacy aliases  -> {'allow': 'observe', 'warn': 'observe', 'log': 'observe'}
validate_action("allow") rejected: Invalid action 'allow'. Must be one of: deny, steer, observe
SteeringContext fields: ['message']
```

## 4. Runtime model

A server (FastAPI + PostgreSQL, `docker-compose up`) with a UI, plus SDKs for
Python and TypeScript. The agent calls out to the control plane at enforcement
points via the `@control()` decorator; framework adapters exist for LangChain,
CrewAI, Google ADK, and AWS Strands.

So it is *not* an agent runtime at all — it is a policy service that agent runtimes
call. That makes it the only project here that could sit alongside our platform
rather than compete with it.

## 5. Execution lifecycle

No agent execution lifecycle; the unit is a `Step` submitted for evaluation.

`ControlExecutionEvent` records each evaluation, with batch submission
(`BatchEventsRequest`), querying (`EventQueryRequest`), and aggregation
(`ControlStats`, `TimeseriesBucket`). So the evaluation history is a first-class
queryable dataset rather than log lines.

## 6. Durability model

PostgreSQL for controls, bindings, and execution events. Batch event submission
suggests the enforcement path is designed not to block on the audit write, which is
the right tradeoff for a synchronous guardrail.

## 7. Agent identity and lifecycle

Agents are *registered* with the control plane and controls are bound to them via
`ControlBinding(target_type, target_id)`. So there is an agent identity here, but it
exists to be a policy *target* — which is precisely ADR-0001's rebased rationale
(identity exists for policy attachment and audit) seen from the policy side.

No agent versioning, no revocation. `D9` absent at fourteen projects.

## 8. Multi-agent communication

Out of scope. AG2 remains the sole answer.

## 9. Human interaction model

No approval resource. But **`steer` is a genuinely new answer to the same problem**,
and worth reading carefully (`models/controls.py:244-275`):

```
SteeringContext.message: "Guidance message explaining what needs to be
                          corrected and how"
```

With examples from the source:

> "This large transfer requires user verification. Request 2FA code from user,
> verify it, then retry the transaction with `verified_2fa=True`."

> "Transfer exceeds daily limit. Steps: 1) Ask user for business justification,
> 2) Request manager approval with amount and justification, 3) If approved, retry
> with `manager_approved=True` and justification filled in."

That is a policy that **repairs rather than refuses**. Instead of blocking and
leaving the agent stuck, the control returns machine-readable remediation
instructions the agent can act on — including instructions to go get human
approval.

Every other project in the study treats policy as binary plus an optional human
gate. `steer` is a third option: the agent is told *how to become compliant*. For
an LLM-driven caller that is far more actionable than a denial, and it converts
many would-be approval prompts into self-service corrections.

**And it is enforced structurally**: a composite control with `decision="steer"`
and no `steering_context` raises `"Composite steer controls require
action.steering_context"` (`controls.py:539-543`). You cannot ship a steer control
that fails to say how to comply.

## 10. Context and memory

Out of scope.

## 11. Tools and capabilities

Tool calls are an enforcement point — `@control()` wraps "a model or tool call".
Evaluators are pluggable: builtin `regex`, `list`, `JSON`, `SQL`, plus
`evaluators/contrib` for third-party ones.

`SQL` as a builtin evaluator is notable: it suggests evaluating structured
tool arguments (a generated query) rather than only free text.

## 12. Security and IAM

**The strongest policy-layer implementation in the study, unsurprisingly.**

- **Separate agent and admin API keys** (`AGENT_CONTROL_API_KEYS` vs
  `AGENT_CONTROL_ADMIN_API_KEYS`), so the agent that is *subject to* controls
  cannot *modify* them. That separation is the whole point of a control plane and
  no other project makes it.
- **A candid security warning in the quickstart**: "This starts server without API
  keys configured which is dangerous for any real world usage." A README that tells
  you the default is unsafe is doing more for security than one that omits the
  default.
- **`namespace_key`** on bindings as the scoping boundary.
- **Recursive condition trees** with structural validation — exactly one of
  leaf/`and`/`or`/`not` per node, empty groups rejected.

What it does not have: principals, authentication of *end users*, or any notion of
who a decision was made on behalf of. It governs agent behaviour, not authority.

## 13. Sandboxing

Out of scope.

## 14. Orchestration

Out of scope — and deliberately so. This is the cleanest instance in the study of
the separation ADR-0013 assumes: policy is a service, orchestration is elsewhere.

**`L8` (compensation) is absent here too.** That completes **fifteen projects with
no compensation or rollback**, and I now consider the question settled — see §25.

## 15. Observability

A properly modelled observability surface: `ControlExecutionEvent`,
`BatchEventsRequest/Response`, `EventQueryRequest/Response`, `ControlStats`,
`StatsRequest`, `TimeseriesBucket`, plus a `telemetry/` directory and a dashboard
UI.

**This is what makes `observe` mode useful.** Shadow evaluation is worthless without
a way to aggregate what the shadow policy *would* have done, and the stats and
timeseries models are that aggregation. The two features are one design.

## 16. Multi-tenancy

**Stronger than I first assumed, and stronger than any other project in the
study.** My initial read of the API models suggested `namespace_key` was a filter
field; the server schema shows otherwise
(`server/src/agent_control_server/models.py:41-80`):

```python
# Composite FKs enforce same-namespace references on both sides.
policy_controls = Table(
    "policy_controls",
    Column("namespace_key", String(255), primary_key=True, ...),
    Column("policy_id",  Integer, primary_key=True, index=True),
    Column("control_id", Integer, primary_key=True, index=True),
    ForeignKeyConstraint(["namespace_key", "policy_id"],
                         ["policies.namespace_key", "policies.id"], ...),
    ForeignKeyConstraint(["namespace_key", "control_id"],
                         ["controls.namespace_key", "controls.id"], ...),
)
```

Omnigent and ADK put the tenant in the **primary** key, so an unscoped *lookup*
finds nothing. Agent Control additionally puts it in every **foreign** key, so a
cross-namespace *relationship cannot be created at all* — binding a policy in
namespace A to a control in namespace B violates a constraint rather than
succeeding quietly.

That is a meaningfully stronger guarantee, and it is the right one for a policy
system specifically: the dangerous failure is not reading another tenant's control,
it is *attaching* one. The same pattern applies to `agent_policies`.

## 17. Protocols and APIs

REST server with an OpenAPI surface, a UI dashboard, Python and TypeScript SDKs, and
framework adapters (LangChain, CrewAI, Google ADK, AWS Strands). Docker Compose for
both production and dev.

The framework-adapter list is the interesting part: Agent Control is designed to sit
*beside* whatever runtime you already use. It is the only project in the study built
on the assumption that it is not the whole platform.

## 18. Storage

PostgreSQL. Controls, bindings, and execution events, with pagination throughout.

## 19. Deployment architecture

`docker compose up` with Postgres, server, and UI — deployable from a single curl'd
compose file with no repo clone. Env vars for ports, API keys, and DB password.

## 20. OSS / license / commercial model

Apache-2.0, with the whole control plane in the repo: server, engine, models,
evaluators, UI, SDKs. `agentcontrol.dev` and hosted docs suggest a commercial
offering, but nothing appears withheld — the self-hosted path is complete and
documented.

Verdict: **INTEGRATE-candidate.** Apache-2.0, Python, self-hostable, and it solves a
subsystem we would otherwise build. **The second INTEGRATE-candidate in the study**
after AG2, and for the same reason: a well-factored, independently useful component
that does not assume it owns the platform.

## 21. Hard scenarios

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | undefined | Governs behaviour, not authority. No principals. |
| S2 Torn side effect | undefined | Not an execution layer. |
| S3 Upgrade mid-flight | undefined | No versioning. |
| S4 Concurrent memory write | undefined | Out of scope. |
| S5 Cancellation tree | undefined | Out of scope. |
| S6 Silent context loss | undefined | Out of scope. |
| S7 Poison message | undefined | Out of scope. |
| S8 Tenant leak | **first_class_answer** | **Strongest mechanism in the study**, found by reading the schema after my first pass through the API models got it wrong. `namespace_key` is in the composite **primary** key *and* in composite **foreign** keys on association tables — "Composite FKs enforce same-namespace references on both sides" (`server/models.py:41-80`). Omnigent and ADK prevent unscoped *reads*; this also prevents cross-namespace *writes*, so a policy in one namespace cannot be bound to a control in another. |
| S9 Runaway spend | undefined | No cost model — though a `deny` control on an expensive tool is an available mechanism. |
| S10 Zombie sandbox | undefined | Out of scope. |
| **I8 / J10 policy** | **first_class_answer** | The reason for this pass. Controls as runtime-configurable resources, recursive boolean condition trees with structural validation, pluggable evaluators, bindings as their own resource, separate agent/admin keys, and a three-way `deny \| steer \| observe` outcome. |

## 22. Strongest ideas

1. **`observe` as a first-class control action** — evaluate and record without
   enforcing. Shadow mode, shipped, and the only instance in fifteen projects.
2. **`steer` as a third outcome**, returning machine-readable remediation
   instructions rather than a refusal.
3. **Requiring `steering_context` on composite steer controls** — you cannot ship a
   steer decision that fails to say how to comply.
4. **Steering examples that are procedures**, not messages: "1) Ask user for
   business justification, 2) Request manager approval…, 3) If approved, retry with
   `manager_approved=True`".
5. **Recursive `ConditionNode` trees** (`leaf`/`and`/`or`/`not`) with a validator
   enforcing exactly one node kind and rejecting empty groups.
6. **Strict-in, lenient-out action normalisation**: `validate_action` rejects legacy
   values at the API boundary while `normalize_action` accepts them on internal read
   paths, with the reasoning stated in both docstrings.
7. **Separate agent and admin API keys**, so a governed agent cannot alter its own
   governance.
8. **A README that names its own unsafe default**: "This starts server without API
   keys configured which is dangerous for any real world usage."
9. **`ControlBinding` as a first-class resource** — policy *attachment* is queryable,
   auditable, and independently enable-able.
10. **Dot-notation selectors** (`input.query`, `context.user_id`) so a control
    targets a precise field rather than a whole payload.
11. **A full stats and timeseries model** (`ControlStats`, `TimeseriesBucket`) —
    which is what makes `observe` mode actionable.
12. **Batch event submission**, so the audit write does not block the enforcement
    path.
13. **`SQL` as a builtin evaluator**, implying structured-argument evaluation rather
    than text-only matching.
14. **Framework adapters for runtimes it does not own** (LangChain, CrewAI, ADK,
    Strands) — built on the assumption that it is a component, not a platform.
15. **Deployable from a curl'd compose file** with no repo clone.

## 23. Weakest architectural choices

1. **No principals and no end-user authentication.** It governs agent behaviour and
   cannot express on-whose-behalf.
2. **No row-level security**, so tenancy relies on the application always supplying
   the namespace — though composite FKs make cross-namespace *relationships*
   structurally impossible, which is the more dangerous case.
3. **No agent versioning or revocation.**
4. **No policy analysis.** Controls are evaluated, never compared — so `observe`
   mode gives empirical shadow comparison but not the static kind Cedar enables.
5. **Tests need `pytest-asyncio`** which is not in the default install path, so a
   fresh clone reports 64 spurious failures.
6. **Narrow by design**, which is a strength for integration and means it answers
   very few probes.

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| `observe` as a first-class action | **ADOPT_AS_STANDARD** | Shadow mode; the only precedent in fifteen projects |
| `steer` with required remediation guidance | **ADOPT_AS_STANDARD** | Policy that repairs beats policy that refuses |
| Structural validation of steer completeness | ADOPT_AS_STANDARD | A steer control that cannot say how to comply is a bug |
| Recursive condition trees with shape validation | **REUSE (port)** | A real policy expression language, validated |
| Strict-in / lenient-out enum normalisation | **ADOPT_AS_STANDARD** | Correct asymmetry for schema evolution |
| Separate agent vs admin credentials | **ADOPT_AS_STANDARD** | A governed subject must not edit its governance |
| `ControlBinding` as a queryable resource | ADOPT_AS_STANDARD | Policy attachment is auditable, not implicit |
| Dot-notation field selectors | REUSE (pattern) | Target a field, not a payload |
| Stats + timeseries over decisions | **ADOPT_AS_STANDARD** | What makes observe mode actionable |
| Batch event submission | REUSE (pattern) | Audit must not block enforcement |
| Naming your unsafe default in the README | REUSE (practice) | Honest defaults documentation |
| The whole control plane | **INTEGRATE** | Second INTEGRATE-candidate after AG2 |
| **Composite FKs enforcing same-namespace references** | **ADOPT_AS_STANDARD** | Prevents cross-tenant *relationships*, not just reads. Strongest tenancy mechanism found |

## 25. Lessons for our platform

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | **confirms** | Agents are registered so that controls can be *bound* to them (`ControlBinding.target_id`). The rebased rationale seen from the policy side: identity exists so policy can attach to it. |
| ADR-0002 | neutral | No run lifecycle; the unit is a `Step`. |
| ADR-0003 | neutral | Out of scope. |
| ADR-0004 | **confirms** | Framework adapters for LangChain, CrewAI, ADK and Strands mean it governs runtimes it did not author — the adapter thesis applied to policy rather than execution. |
| ADR-0005 | neutral | Tool calls are enforcement points; no capability model. |
| ADR-0006 | neutral | No A2A. |
| ADR-0007 | **challenges (again)** | Fourth project to have half the model: it governs *behaviour* thoroughly and cannot express *authority* at all — no principals, no on-behalf-of. With ADK (credentials, no principals), HumanLayer (decisions, no approver) and AgentCore (both), the pattern is now unmistakable: **the principal model is the field's most consistent omission**, and it is what ties policy, approval and delegation together. |
| ADR-0008 | neutral | Out of scope. |
| ADR-0009 | neutral | Out of scope. |
| ADR-0010 | **confirms** | Decisions are a modelled, queryable dataset — `ControlExecutionEvent`, stats, timeseries — not log lines. Reinforces the amendment that *refusals* must be as observable as successes, and adds that they must be **aggregable**. |
| ADR-0011 | neutral | No versioning. |
| ADR-0012 | confirms | Evaluators are pluggable with a declared spec (`EvaluatorSpec`) and builtin/contrib separation, and controls declare their evaluator rather than discovering it. |
| ADR-0013 | **confirms — the shadow half, finally** | Fifteen projects with no shadow-comparison precedent, and this ships it: **`observe` is a canonical action** that evaluates and records without enforcing, paired with the stats/timeseries models that make the recorded data useful. Plus `steer`, which is a category I did not have. **Amend ADR-0013 to a three-way outcome and to require that observe-mode data be aggregable, not merely logged.** Note it gives *empirical* shadow comparison (run it, see what it would have done) where Cedar gives *static* comparison (prove B ⊇ A) — the two are complementary and we should have both. |
| ADR-0014 | neutral | Not an execution layer. |
| ADR-0015 | **amends** | `steer` reframes the approval question. Many approvals exist because a policy can only say no; if it can say *"get 2FA and retry with `verified_2fa=True`"*, the agent self-services and no human is interrupted. **Approval should be the escalation path when steering is impossible, not the default response to a policy violation.** |

**Three amendments to make.**

1. **ADR-0013 becomes three-way.** `deny | steer | observe`, not allow/deny.
   `observe` is shadow mode and it is the ADR's missing half. `steer` must carry
   structured remediation guidance, and a steer decision without it should fail
   validation — as it does here.

2. **ADR-0015 demotes approval to an escalation.** A policy that can only refuse
   generates an approval for every edge case. A policy that can steer resolves most
   of them without a human. Approval is what happens when steering cannot work.

3. **Separate the governed from the governor.** Distinct agent and admin
   credentials, so an agent subject to policy cannot modify policy. Obvious once
   stated, and only this project does it.

**And one closing conclusion, now that `L8` has been checked in all fifteen
projects.**

Compensation and rollback are **absent in fifteen of fifteen**, including the two
projects whose entire job is control (this one) and orchestration (MAF), and
including four managed enterprise platforms. Pydantic AI supplies the reason:
under Temporal, DBOS or Prefect, saga compensation is *the workflow engine's job*.

**`L8` is not a gap in this field; it is a boundary.** Compensation belongs to a
durable workflow engine, and an agent platform should integrate one rather than
reimplement it. I am recording that as a deliberate v0.1 exclusion with fifteen
projects of evidence behind it, rather than an unbuilt feature.

## 26. Open questions

- **Answered, and it corrected me.** `namespace_key` is enforced structurally:
  it is part of the composite primary key *and* of composite foreign keys on the
  association tables, with the intent stated in a comment — "Composite FKs enforce
  same-namespace references on both sides"
  (`server/src/agent_control_server/models.py:41-80`). So a cross-namespace binding
  is a constraint violation, not a silent success. **I had recorded this as a mere
  filter field after reading only the API models**; the schema says otherwise. Third
  time in this study that checking the schema overturned an inference drawn from an
  API surface. **Resolved.**
- **Answered by reading the engine: it is true A/B shadow.** All controls bound to
  a target are evaluated **concurrently** under a semaphore, each producing its own
  recorded result, and only `deny`/`steer` decisions affect the outcome
  (`engine/src/agent_control_engine/core.py:662-780`). An `observe` control
  therefore runs on the *same live traffic* as the enforced ones and its verdict is
  recorded as a `ControlExecutionEvent` without changing behaviour — which is
  exactly candidate-vs-enforced shadow comparison.
  One implementation detail worth stealing: a `deny_found` `asyncio.Event` lets the
  engine cancel the remaining evaluations once any control denies
  (`core.py:673-677`), so the fast path is not penalised by having many controls
  bound. But note the interaction — **early cancellation on deny means observe-mode
  controls may not record a verdict for denied traffic**, so shadow data is
  systematically missing exactly the cases a candidate policy most needs to be
  compared on. If we adopt this, observe-mode evaluations must be exempt from
  deny-triggered cancellation. **Resolved, with a caveat we must design around.**
