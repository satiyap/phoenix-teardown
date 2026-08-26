# ADR-0013 — Policy decisions are traced and shadow-comparable

- **Status:** Accepted (2026-08-26, Phase 5) — 10 projects. Cedar for the language and static analysis; Agent Control for observe-mode and steer. Both halves now precedented.
- **Date:** 2026-08-26
- **Supersedes:** —
- **Superseded by:** —

## Context

Raised by the Letta teardown, which is the only project in the study with a
production-grade policy engine and therefore the only one that had to solve
policy *evolution*.

Letta's permission types (`src/permissions/types.ts:30-57 @ 852ca24`) include:

```typescript
export type PermissionEngine = "v1" | "v2";
export interface PermissionTraceEvent { ... }
export interface PermissionShadowComparison { ... }
export interface PermissionCheckTrace { ... }
export interface PermissionCheckResult { ... }
```

Two capabilities beyond simply making a decision:

1. **Tracing** — `PermissionCheckTrace` records *why* a decision was reached, not
   just what it was. With a layered model (unbypassable guard at step 0, then
   rules, then modes) a bare `deny` is not actionable; the operator needs to know
   which layer denied and on what rule.
2. **Shadow comparison** — the engine is explicitly versioned, and v2 can be
   evaluated alongside v1 on live traffic with decisions compared before cutover.

This matters more for us than for Letta. Our policy layer will deny real work:
tool calls, delegations, spawns. A policy change that silently broadens access is
a security incident; one that silently narrows it is an outage. Neither is
detectable from a boolean return value.

Letta also demonstrates the failure this prevents. It once analysed shell
commands by parsing them and abandoned that design because it "was bypassable by
symlinks, command substitution, globbing, and subprocesses"
(`src/permissions/cross-agent-guard.ts:11-14 @ 852ca24`). Replacing an
enforcement mechanism wholesale is exactly the change that needs shadow
evaluation, because the new mechanism's decisions must be compared against the
old before anyone trusts it.

## Decision

Every policy decision emits a trace, and the policy engine supports shadow
evaluation.

**Tracing.** A decision record carries: the decision (`allow` / `deny` / `ask`),
the layer that produced it, the specific rule or guard matched, the principal,
the capability, the resource, and the inputs consulted. A `deny` must be
explainable to the operator and to the agent without reading source.

**Shadow evaluation.** The engine is versioned. A candidate version can be
evaluated in parallel with the active one, with divergences recorded and not
enforced. Promotion requires an explicit decision informed by observed
divergence, not a deployment.

**Layer attribution is mandatory.** Given a layered model with an unbypassable
floor, a trace that does not name the deciding layer is incomplete.

## Rationale

Policy is the subsystem where silent behaviour change is most dangerous and least
observable. Traces make individual decisions auditable; shadow evaluation makes
*changes* to the decision function auditable. They address different risks and we
need both.

There is a second benefit specific to agents. When a capability is denied, the
agent should be able to explain the refusal to the human, and ideally adapt.
That requires a machine-readable reason, which follows from tracing. It also
connects to ADR-0012's rule that a refusal names the unmet capabilities rather
than merely reporting failure — same principle applied to policy rather than
capability.

## Implications

- Policy decision records are a first-class event type in the canonical schema
  (ADR-0010), and they carry audit weight, so they need durability guarantees
  stronger than best-effort telemetry.
- The engine interface must accept a version and support parallel evaluation.
- Divergence reporting needs a home: a comparison log plus a way to sample
  disagreements.
- Trace volume is a cost concern — every tool call produces one. Needs sampling
  for observability while retaining all `deny` and `ask` decisions for audit.
- Interacts with ADR-0007: the trace must identify the principal, and for a
  delegated action must record both the acting agent and the authority under
  which it acted (see S1).

## Falsification

If our policy layer stays simple enough that decisions are self-evident from
inputs — a single flat ruleset, no layering, no delegation — tracing is overhead
and shadow evaluation is ceremony.

Also falsifiable if trace volume proves unmanageable in practice: if the honest
choice becomes tracing only denials, then "every decision emits a trace" is wrong
as stated and should be narrowed.

## Deciding probes

`I8`, `J10`, `J9`, `M1`, `M4`

## Amendment — 2026-08-26 (Phase 4, AWS AgentCore): adopt Cedar

This was the weakest-supported ADR in the study for twelve projects. Traceability
had precedent — Omnigent's `deciding_policies`, AG2's `on_envelope_rejected`,
HumanLayer's decision record — but the **shadow-comparison half had none at all**,
and I was close to concluding it was either a differentiator or a bad idea with no
way to tell which.

AgentCore answers it by not writing a policy engine at all.

**Policy is Cedar** (`src/bedrock_agentcore/policy/client.py:30-37 @ 826416a`):

```python
client.create_policy(
    policy_engine_id=engine["policyEngineId"],
    name="my_policy",
    definition={"cedar": {"statement": "permit(principal, action, resource);"}},
)
```

Three properties matter here, and only the first is obvious:

1. **Cedar has a formal semantics**, so a policy set is a mathematical object rather
   than a pile of callbacks. That is what makes shadow comparison *tractable*:
   "is policy set B strictly more permissive than A" is a decidable question about
   Cedar, and an intractable one about arbitrary Python predicates.
2. **`principal`, `action`, `resource` are language primitives**, aligning exactly
   with ADR-0007's amended split. The agent's workload identity is nameable as a
   Cedar `principal`; there is no impedance mismatch to bridge.
3. **The policy engine is a resource with its own lifecycle**, separate from the
   agent — the cleanest separation of policy from execution in the study.

And `start_policy_generation` (`policy/client.py:240-290`) turns natural language
into Cedar policies as **reviewable assets**: `content={"rawText": "allow
refunds..."}` → poll to `GENERATED` → `list_policy_generation_assets` →
`generatedPolicies`. The candidate policy is *data you inspect before it takes
effect*. That is a weaker cousin of shadow comparison — review-before-enforce rather
than run-both-and-diff — and it is the only instance of the instinct in twelve
projects.

### Amended decision

**Policy is expressed in Cedar, not in a bespoke rule engine.**

The reasoning is the same as ADR-0010's for OpenTelemetry: adopting an existing
formally-specified standard buys an ecosystem — analysis tooling, a validator, a
published semantics, other people's correctness proofs — that we would otherwise
have to build from nothing and would build worse. A bespoke DSL would mean
implementing the shadow-comparison analysis ourselves against semantics we invented
and never proved anything about.

The traced half is unchanged and still assembled from three projects:

- **Which policies decided** — Omnigent's `deciding_policies` (one on DENY, all
  ASKing policies in order).
- **Every refusal observable** — AG2's `on_envelope_rejected` firing for *every*
  attempt, not just successes.
- **The decision record** — HumanLayer's approval row: what was asked, what was
  decided, when, and why.
- **Which rule required it** — ADR-0015 rule 6, still ours to build.

The shadow half now has a concrete plan rather than an aspiration:

1. **Shadow evaluation**: run candidate policy set B alongside enforced set A,
   record both decisions, diff them over real traffic. Needs only that decisions be
   traced, which the above provides.
2. **Static comparison**: use Cedar's analysis tooling to answer whether B is more
   permissive than A *without* traffic — the part that was impossible with a
   bespoke engine.
3. **Review-before-enforce**: a candidate policy set is a durable, inspectable
   artefact with its own status, following AgentCore's generation-assets pattern.

**Open question kept honest.** Whether AgentCore's *managed service* exposes Cedar's
analysis capability, or only its evaluation, is OQ-033 and unresolved. But Cedar's
analysis tooling is open source and independent of AWS, so the capability is
available to us regardless of what the managed service surfaces. That converts this
ADR's hardest requirement from a research question into a tooling one.

## Amendment 2 — 2026-08-26 (Phase 4, Agent Control): three outcomes, and the shadow half ships

Amendment 1 adopted Cedar and turned shadow comparison from a research question
into a tooling one. Agent Control closes it the other way — empirically — and adds
an outcome category I did not have.

### `observe` is the shadow half

`observe` is a **canonical control action**, not a logging flag
(`models/actions.py:8-17 @ 7cb21af`), verified live:

```text
canonical actions: ['deny', 'steer', 'observe']
legacy aliases  -> {'allow': 'observe', 'warn': 'observe', 'log': 'observe'}
```

And it is genuinely A/B rather than merely non-blocking. All controls bound to a
target evaluate **concurrently**, each recording its own `ControlExecutionEvent`,
with only `deny`/`steer` affecting the outcome (`engine/core.py:662-780`). So a
candidate control runs against the same live traffic as the enforced ones and its
verdicts are recorded without changing behaviour.

The other half of why this works is the observability model: `ControlStats`,
`StatsRequest`, `TimeseriesBucket`, `EventQueryRequest`. **Shadow evaluation is
worthless without aggregation** — knowing that a candidate policy fired 4,102 times
matters, knowing it fired *once* does not. The two features are one design.

**A caveat we must design around.** A `deny_found` event cancels remaining
evaluations once any control denies (`engine/core.py:673-677`), which is correct for
latency and wrong for shadow data: observe controls may record no verdict for denied
traffic, biasing the sample away from exactly the cases a candidate policy most
needs comparing on. **Our observe-mode evaluations must be exempt from
deny-triggered cancellation**, accepting the latency cost on the deny path.

### `steer` is a third outcome

Fifteen projects treat policy as binary plus an optional human gate. Agent Control
adds a third decision that returns **structured remediation guidance**
(`models/controls.py:244-275`), and the shipped examples are procedures rather than
messages:

> "This large transfer requires user verification. Request 2FA code from user,
> verify it, then retry the transaction with `verified_2fa=True`."

> "Transfer exceeds daily limit. Steps: 1) Ask user for business justification,
> 2) Request manager approval with amount and justification, 3) If approved, retry
> with `manager_approved=True` and justification filled in."

For an LLM-driven caller that is far more actionable than a denial, and it is
enforced structurally: a composite control with `decision="steer"` and no
`steering_context` fails validation with *"Composite steer controls require
action.steering_context"*. **You cannot ship a steer control that does not say how
to comply.**

### Amended decision

**Policy decisions are three-way, traced, aggregable, and comparable both
empirically and statically.**

```text
decision ∈ { deny, steer, observe }
  deny     refuse; the operation does not proceed
  steer    refuse AND return machine-readable remediation guidance
           (required, validated — a steer without guidance is invalid)
  observe  evaluate and RECORD only; never affects the outcome
```

With four supporting rules:

1. **Every decision is recorded as a queryable, aggregable event**, not a log line.
   Rejections included (AG2), with stats and timeseries over them (Agent Control).
2. **Observe-mode controls run on live traffic alongside enforced ones**, and are
   **exempt from short-circuit cancellation** so the shadow sample is unbiased.
3. **Static comparison via Cedar** (Amendment 1) answers "is B more permissive than
   A" without traffic; **empirical comparison via observe mode** answers "what would
   B have done to real requests". Both, because each catches what the other misses:
   static analysis finds cases traffic has not yet produced, empirical evaluation
   finds cases the policy author did not anticipate.
4. **Policy has ownership precedence** (MAF/Purview): organisation policies bind
   agent policies and an agent-level control cannot weaken an org-level one. And the
   governed cannot edit the governor — **separate credentials for submitting
   evaluations and for managing controls** (Agent Control's agent vs admin API keys,
   the only instance of this separation in the study).

### Status of this ADR

It entered Phase 4 as the weakest-supported decision in the set — traceability had
precedent, shadow comparison had none in twelve projects. It leaves with **both
halves precedented and a third outcome category I had not conceived of**. Cedar
supplies the language and the static analysis; Agent Control supplies the empirical
mode, the aggregation, and `steer`.

## Amendment 3 — 2026-08-26 (verification): Cedar's static analysis is a Rust-boundary dependency

Amendment 1 adopted Cedar partly on the claim that it makes "is policy set B more
permissive than A" decidable. **I tested that claim and it is only half right.**

Installed `cedarpy` and ran real policies. What works:

```
risk      A(baseline)   B(tighter)   C(typo'd attr)
low          Allow        Allow        Allow
medium       Allow         Deny        Allow
high          Deny         Deny        Allow    ← silently permits a high-risk call
```

Policy C forbids on `resource.riskLevel` instead of `resource.risk` — a one-word typo
that silently disables the guard. Cedar's validator catches it **statically, with no
traffic**:

```
correct attr  -> validation_passed=True,  num_errors=0
typo'd attr   -> validation_passed=False, num_errors=1
```

In a hand-rolled predicate that typo is a missing attribute and the high-risk guard
evaporates. **That is the strongest argument for Cedar, and it is a better one than
the argument I originally made.**

What does **not** work: `cedarpy` exposes `validate_policies` (schema conformance) and
`is_authorized_partial` (evaluation with unknowns). It does **not** expose equivalence,
implication or permissiveness comparison. Those live in Cedar's Rust/Lean analysis
tooling.

**Amended decision.** Cedar stays, for schema-validated policies and the typo class of
bug it catches. But the two shadow halves are now scoped honestly:

- **Empirical shadow — v0.1.** `observe` mode (Agent Control's mechanism): run the
  candidate on live traffic, record what it would have done, aggregate. Available
  immediately in Python.
- **Static shadow — deferred, and a Rust-boundary dependency.** Permissiveness
  comparison requires calling Cedar's analysis crate across an FFI or service
  boundary. Not a v0.1 commitment.

Amendment 1 said this ADR's hardest requirement had become "a tooling question rather
than a research one". That is still true, but the tooling is in another language, which
is a materially different cost than I implied.

## Evidence log

| Project | Effect | Evidence | Note |
|---|---|---|---|
| Letta | raised | `src/permissions/types.ts:30-57 @ 852ca24` | `PermissionEngine v1\|v2`, `PermissionCheckTrace`, `PermissionShadowComparison`, `PermissionTraceEvent`. The only project in the study to treat policy evolution as a design problem. |
| Letta | supports | `src/permissions/cross-agent-guard.ts:11-19 @ 852ca24` | Documents abandoning shell-command parsing as bypassable and moving enforcement to the kernel — precisely the wholesale mechanism change that requires shadow comparison. |
| LangGraph | neutral | `libs/sdk-py/langgraph_sdk/auth/__init__.py:98 @ 3803173` | Has a specificity fallback chain but no trace and no engine versioning. |
| OpenHands | neutral | `openhands-sdk/.../hooks/conversation_hooks.py:92 @ 760eea2` | `HookExecutionEvent.blocked` records that a block happened, but not which rule decided or why. |
| Google AX | neutral | `internal/server/server.go:82-83 @ b777313` | No policy engine at all, so nothing to trace. |
| Omnigent | confirms | `omnigent/policies/types.py:244-252 @ ba9e371` | **First implementation of the traceability half.** `PolicyResult.deciding_policies` names every policy that drove a composed verdict — a single policy on DENY, all ASKing policies in YAML order on ASK. Policies also *transform* content in a chain, each seeing the previous one's output, which makes PII redaction a policy rather than a special case. No shadow-comparison mode exists, so that half of the ADR remains without precedent after six projects. |
| Cloudflare Agents | neutral | `packages/agents/src/chat/tool-state.ts @ 2f957bc` | No policy engine. Tool approval exists as a protocol message type, but nothing evaluates rules, so there is no decision to trace. |
| AG2 | confirms | `ag2/network/rule.py:12 @ 90f490a`; `ag2/network/hub/core.py:1861-1866,24-25` | Access and limits are "enforced at the **hub**, never the client", decisions route through a **replaceable `arbiter`** so "federation / custom permission protocols can replace the default rule-based behavior without forking the hub", and every refusal fires `on_envelope_rejected`. The trust boundary is architectural: the hub "never calls `Agent.ask`, executes tenant transforms, or imports tenant modules". Still **no shadow-comparison mode after eight projects** — that half of this ADR remains without precedent. |
| Pydantic AI | neutral | `pydantic_ai_slim/pydantic_ai/capabilities/hooks.py @ b48ee38` | No policy engine. Typed wrap points and `Hooks` are real interception seams, and `RaiseContentFilterError` is a shipped guard, but there is no decision object to trace. |
| Google Agent Platform | neutral | `src/google/adk/plugins/base_plugin.py:114-396 @ 85b52f6` | Sixteen named lifecycle hooks — including four distinct error callbacks (`on_model_error`, `on_tool_error`, `on_agent_error`, `on_run_error`) — are real interception seams, but there is no policy decision object to trace. **Still no shadow-comparison mode after ten projects**; that half of this ADR remains entirely without precedent. |
| HumanLayer | confirms | `hld/store/sqlite.go:201-217 @ 99abe67` | **Traces the decision but not the policy.** The record is strong — which tool, what input, what status, when responded, and a free-text rationale — but nothing records *the rule that required approval*, because that is delegated to the harness's permission mode. That is precisely the half AG2 (`deciding_policies`) and Omnigent supply, and it confirms both halves are needed: a decision trail without the rule cannot answer "why was this gated", and a rule trail without the decision cannot answer "what did the human say". |
| AWS AgentCore | confirms | `src/bedrock_agentcore/policy/client.py:30-37,240-290 @ 826416a` | **The first real precedent for this ADR, and it changes the plan.** Policy is **Cedar** — `definition={"cedar": {"statement": "permit(principal, action, resource);"}}` — a language with a formal semantics and an existing analysis toolchain, exposed through a dedicated `PolicyEngine` resource separate from the agent. That matters specifically because "is policy set B more permissive than A" becomes a **tractable question**, which is exactly what the shadow-comparison half needs and what twelve projects offered nothing for. Additionally `start_policy_generation` turns natural language into Cedar policies as **reviewable assets** (`content={"rawText": …}` → poll to `GENERATED` → `list_policy_generation_assets`) — the only instance in the study of treating a policy as something you evaluate *before* enforcing. **Amend the ADR to adopt Cedar rather than building a bespoke rule engine.** |
| Microsoft Agent Framework | amends | `python/packages/purview/README.md @ e34bf48`; `python/packages/purview/agent_framework_purview/_middleware.py:24,150` | **Adds an axis Omnigent's per-phase model lacks.** `agent-framework-purview` enforces policy on "both the *prompt* (user input + conversation history) and the *model response*", blocking "at both ingress (prompt) and egress (response)", from **centrally managed** DLP policy applied "without rewriting agent logic". So an agent author **cannot bypass an org policy by editing their agent**. Omnigent answers *where* in the enforcement path to fail closed; Purview answers *who owns the rule*. **Amendment: our policy model needs explicit ownership precedence — organisation policies bind agent policies, and an agent cannot weaken one.** Audit also flows into an existing compliance system (Audit, Communication Compliance, Insider Risk, eDiscovery) rather than a bespoke log. |
| Agent Control | confirms | `models/src/agent_control_models/actions.py:8-17 @ 7cb21af`; `models/src/agent_control_models/controls.py:244-275`; verified live: canonical actions ['deny','steer','observe']; engine tests 115 passed | **The shadow half, finally, after fifteen projects with no precedent.** `observe` is a *canonical* action — evaluate and record without enforcing — verified live alongside `deny` and `steer`. And it is genuinely A/B: all bound controls evaluate concurrently, so an observe control runs on the same live traffic as enforced ones (`engine/core.py:662-780`). Paired with `ControlStats`/`TimeseriesBucket`, which is what makes shadow data actionable. **Plus `steer`, a category I did not have**: structured remediation guidance (`SteeringContext.message`) returned instead of a refusal, with a validator rejecting a composite steer control that omits it. **One caveat to design around**: a `deny_found` event cancels remaining evaluations, so observe controls may not record verdicts for denied traffic — biasing shadow data away from exactly the cases that matter. Our observe evaluations must be exempt from that cancellation. |

## Open questions

- Should a policy trace be retained for the same period as the audit log, or is
  a shorter window acceptable for `allow` decisions?
- Can shadow evaluation run safely against an engine with side effects (an
  `AGENT`-type hook that itself invokes a model, as in OpenHands)?
