# ADR-0012 — Adapter and provider capabilities are declared, not discovered

- **Status:** Provisional (raised by evidence, Phase 2)
- **Date:** 2026-08-26
- **Supersedes:** —
- **Superseded by:** —

## Context

Not in the original strawman. Raised because the first two deep teardowns solved
the *same* problem in two different ways, and the comparison specifies the
requirement precisely.

Both LangGraph and OpenHands have a pluggable backend interface where some
operations are optional. Both had to answer: how does a caller know whether this
implementation supports `pause`, or `prune`, or snapshotting?

**LangGraph declares and detects.** `libs/checkpoint-conformance @ 3803173`
defines a `Capability` enum split into `BASE_CAPABILITIES` (mandatory) and
`EXTENDED_CAPABILITIES` (optional), detects which are implemented by checking
whether a method is overridden from the base class, and runs only the applicable
conformance tests. A backend can be partially implemented and still be validated
against what it claims.

**OpenHands raises and hopes.** `openhands-sdk/openhands/sdk/workspace/base.py:261
@ 760eea2` implements optional `pause()` / `resume()` by raising
`NotImplementedError` from the base class. Verified empirically with
`openhands-sdk` 1.43.1:

```text
LocalWorkspace methods: ['pause', 'resume', 'execute_command']
capability-query attributes: NONE
local pause(): no-op, succeeded
```

There is no way to ask. Worse, `LocalWorkspace.pause()` is documented as "for
local workspaces, this is a no-op" and returns successfully — so a caller pausing
a workspace to conserve resources receives success while nothing was paused.
Three of five providers actually implement it.

Separately, OpenHands' *automation manifest* layer gets this right, and states
the principle better than we did:

> "'unknown' is a real outcome, not an error: a deployment that cannot be asked
> must not be treated as one that answered no."
> — `src/manifests/manifest-capabilities.ts:14 @ f48eca6`

That is the same `absent` vs `unknown` distinction this teardown's methodology
insists on, arrived at independently in a different domain. Its assessment also
returns *which* requirements were unmet, so a refusal can explain itself.

This matters for us more than for either of them. ADR-0004 commits us to adapting
harnesses with genuinely different capabilities — Claude Code can checkpoint, a
raw HTTP A2A endpoint cannot — and ADR-0009 commits us to sandbox providers where
snapshot support varies. If capability mismatches surface as exceptions at the
moment of use, or worse as silent no-ops, the platform cannot schedule
intelligently or explain a refusal.

## Decision

Every adapter and provider **declares** its capabilities as data, queryable
before invocation. Three rules:

1. **Declared, not inferred.** A capability set is part of the registration
   contract, not something derived by introspection or discovered by calling.
2. **Three-valued, not boolean.** `supported` / `unsupported` /
   `unknown` are distinct. An implementation that cannot be asked must never be
   recorded as having answered no.
3. **Explicit failure over silent success.** Invoking an undeclared optional
   operation raises a typed error. A no-op that returns success is forbidden,
   because it converts a capability gap into a correctness bug.

A refusal must name the unmet capabilities, not merely report that some were
unmet.

Capability declarations are verified by a conformance suite, following LangGraph's
pattern: mandatory core, optional extensions, and spec tests gated on what the
implementation claims.

## Rationale

Declaration is what makes the control plane able to reason. Scheduling a run that
requires checkpoint/resume onto an adapter that cannot checkpoint should be
impossible at admission time, not a runtime surprise. That is only achievable if
capabilities are data before they are behaviour.

The three-valued rule follows from the two projects' own evidence: OpenHands
articulated it clearly in one subsystem (manifests) and violated it in another
(workspaces). Getting it right in one place and wrong in another within the same
codebase suggests the failure is easy and needs to be a stated rule.

The no-silent-no-op rule is the sharpest lesson available. A `pause()` that does
nothing and reports success is worse than one that refuses, because the caller
proceeds on a false belief. Any capability we cannot honour must be visible.

## Implications

- Adapter and provider registration includes a capability manifest.
- Needs a capability vocabulary spanning both harness adapters and sandbox
  providers, with distinct namespaces.
- Admission control consults declared capabilities before dispatch, so a Task can
  be rejected or routed based on requirements.
- Needs typed `UnsupportedCapability` errors carrying the unmet set.
- Needs a conformance test suite per interface, and a way for third-party
  implementations to run it.
- A capability declaration that lies is a conformance bug; the suite is how that
  gets caught.
- Interacts with ADR-0011: "can report a definition version" is itself a
  capability, and adapters that cannot must be admitted only for best-effort
  resume.

## Falsification

If the set of adapters we actually support converges on a uniform capability set,
declaration is ceremony over a constant and a simpler mandatory interface wins.

Also falsifiable if declaration proves unmaintainable — if declarations routinely
drift from behaviour despite conformance tests, runtime detection (LangGraph's
override check) may be more honest than a hand-maintained manifest, at the cost
of not being knowable before load.

## Deciding probes

`E1`, `E8`, `E9`, `K9`, `D7`, `C12`

## Amendment — 2026-08-26 (Phase 3, Google AX)

Rule 3 as originally written ("explicit failure over silent success", forbidding
no-ops) is too blunt. Google AX handles an optional capability by treating its
absence as acceptable: a harness that does not implement the gRPC health service
is "treated as ready", while `Unavailable` and `NOT_SERVING` are retried
(`internal/harness/substrate/substrate.go:135-138 @ b777313`). That is
**fail-open**, and it is correct there.

Four projects, four designs, and the split is not arbitrary:

| Project | Behaviour | What the capability guards |
|---|---|---|
| LangGraph | declared + detected + conformance-tested | storage operations |
| OpenHands | `NotImplementedError`, no query, silent local no-op | resource suspension |
| Letta | real probe, `backend \| null` + reason, **fails closed** | **memory isolation** |
| Google AX | no declaration, absence treated as OK, **fails open** | **readiness** |

The two fail-closed/fail-open choices correlate with what is at stake. Letta
refuses to run when the kernel sandbox is unavailable because the capability
enforces a security boundary; degrading there would silently weaken isolation. AX
proceeds when a health check is unavailable because the worst case is a slower
failure, not a breach.

**Amended rule 3:** capabilities are classified as *safety-relevant* or
*liveness-relevant* at declaration time.

- **Safety-relevant** (isolation, permission enforcement, audit, secret handling):
  absence or uncertainty must **fail closed**. An unavailable capability blocks
  the operation. Never degrade silently.
- **Liveness-relevant** (health checks, readiness probes, optional optimisations
  such as pause/suspend): absence **may fail open**, provided the degradation is
  logged and observable.

OpenHands' `LocalWorkspace.pause()` remains the anti-pattern under both
classifications: it is liveness-relevant, so failing open is acceptable, but it
reports *success* rather than logging a no-op, which makes the degradation
invisible. Fail-open is permitted; silent fail-open is not.

This classification is itself part of the declaration, so a caller can tell which
kind it is dealing with.

## Amendment 2 — 2026-08-26 (Phase 3, Omnigent): supersedes Amendment 1's categories

Omnigent solves the same problem better, hours after I wrote Amendment 1. Its
fail-closed set is decided by **position in the enforcement path**, not by
category of capability (`omnigent/policies/types.py:59-80 @ ba9e371`):

```python
FAIL_CLOSED_PHASES: tuple[str, ...] = ("PHASE_TOOL_CALL", "PHASE_REQUEST")
```

The reasoning is given inline, and it is the right reasoning:

- `PHASE_TOOL_CALL` fails **closed** because "for connector-native MCP tools the
  in-band verdict is the only enforcement point — the call is never re-checked
  server-side."
- `PHASE_REQUEST` fails **closed** because it is "the sole pre-turn enforcement
  point."
- `PHASE_TOOL_RESULT` fails **open**, deliberately: "by the time the result phase
  runs the tool has already executed, so failing it closed would only block an
  already-incurred side effect."

**Superseding rule.** Fail closed where the decision is the *last enforcement
point* before an irreversible action. Fail open where the harm is already
incurred, because blocking then costs availability and buys no safety.

This is sharper than Amendment 1's safety-vs-liveness split for two reasons.
First, it is decidable from the architecture (is anything downstream going to
check again?) rather than from a judgement call about what counts as
safety-relevant. Second, it explains Letta and AX as the *same* rule rather than
two: Letta's sandbox probe is the last gate before untrusted code runs, so it
fails closed; AX's health check has a retry loop and a dial attempt after it, so
it may fail open.

Amendment 1's classification is retained only as documentation on the capability
itself — useful for readers, not the deciding factor.

Two implementation details worth copying:

1. **Define the set once**, in one constant, "so the enforcement sites can't
   drift if the set of fail-closed phases changes." Omnigent has two enforcement
   sites reading one tuple.
2. **Silent fail-open remains forbidden** (unchanged from Amendment 1). Omnigent's
   advisory gates log and persist their fallback as a `routing_decision`
   transcript item, so a fail-open is visible after the fact.

## Extension — verification, publication, and confidence

Omnigent also closes the loop this ADR left open, in three ways this decision
now adopts.

**1. Declared capabilities are verified against live behaviour.** A conformance
bench probes each harness and `reconcile()` compares declared against observed,
emitting **DRIFT** when they disagree (`tests/harness_bench/bench.py:44-66`). The
design note states the consequence: a DRIFT means "a harness's capability
declaration is false", which makes the table self-enforcing — "you can't lie in
`_BUILTIN_CAPABILITIES` without the bench catching it on the next live run."

*Adopted:* every declared capability must have a conformance probe, and
declaration-vs-observation drift is a build failure.

**2. `None` means "makes no claim", reported as UNKNOWN — never as unsupported.**
From `harness_capabilities.py`: "Optional capability fields use `None` when the
harness makes no claim; the bench reports those declarations as `UNKNOWN` rather
than assuming the capability is unsupported."

This is the `absent` ≠ `unknown` discipline this whole study runs on, implemented
inside a capability model. No other project does it.

*Adopted:* capability fields are tri-state — `true`, `false`, or `unknown` — and
`unknown` never silently degrades to `false`.

**3. Verified is tracked separately from asserted.** Only 4 of Omnigent's 26
harnesses have `interrupt`/`streaming` probe-verified; the other 19 are "declared
best-effort by integration mode" and the docs warn the bench "must not treat
those 19 as ground truth."

*Adopted:* each capability carries a confidence — `verified` (a passing probe
exists) or `asserted` (declared, unproven) — and anything making a safety
decision may only rely on `verified`.

**4. Capabilities are public API.** Omnigent serialises them onto
`GET /v1/harnesses`, so a client can ask what a harness can do before starting
work. I had planned to keep the capability model internal; publishing it is
strictly better, because callers can degrade deliberately instead of discovering
limits by failure.

A caution learned from Omnigent being wrong once: it declares
`streaming=False` **only from a live observation of zero deltas**, because a
static grep for a delta-posting forwarder gave the wrong answer for one harness.
Declarations about behaviour should come from observation, not from reading code.

**5. Split the bench into an offline layer and a live layer.** Verified in
Omnigent's CI: `tests/harness_bench/test_bench.py` runs an **offline** layer on
every PR — registry membership, *profile completeness*, reconciliation semantics,
and that the matrix renders — with no network or credentials, while the **live**
probe layer that produces real DRIFT verdicts is gated on credentials and a
runnable harness CLI.

This split matters more than it first appears. Live capability probes need
credentials, a running vendor CLI, and money, so they cannot gate every PR. But
*declaration completeness* and *reconciliation logic* need none of those. Putting
them in the offline layer means the capability table cannot silently rot — a new
harness with no declarations fails CI immediately, even though nobody proved what
it can do yet.

*Adopted:* our conformance bench has two layers. Offline (every commit):
every registered adapter has a complete declaration, every declared capability has
a probe defined, and declaration coverage is reported. Live (nightly or on
demand): probes run and DRIFT fails the build.

Also worth noting as an honest limit — verified live against 0.11.0, all four of
Omnigent's optional axes (`steering`, `live_queue`, `images`, `compaction`) are
`None` for all 26 harnesses. The mechanism is proven; the data is not populated.
A tri-state nobody fills is a tri-state that buys nothing, so our conformance
bench must also report *declaration coverage*.

## Evidence log

| Project | Effect | Evidence | Note |
|---|---|---|---|
| LangGraph | raised | `libs/checkpoint-conformance/.../capabilities.py @ 3803173` | BASE vs EXTENDED, runtime detection by method override, spec tests gated on detected set. The good pattern. |
| OpenHands | raised | `openhands-sdk/.../workspace/base.py:261 @ 760eea2`; verified 2026-08-26 | `NotImplementedError` signalling, no query method, and `LocalWorkspace.pause()` silently no-ops. The anti-pattern. |
| OpenHands | confirms | `src/manifests/manifest-capabilities.ts:14,36 @ f48eca6` | Manifest layer states the three-valued rule explicitly and returns which requirements were unmet. |
| Letta | confirms | `src/sandbox/availability.ts:7-45 @ 852ca24`; `src/memory-confinement.ts:14-21 @ 852ca24` | **Reference implementation.** `SandboxAvailability { backend: SandboxBackend|null, bwrapPath?, reason }` detected by a REAL user-namespace mount probe, cached per process, with a human-readable reason for the null case. Dependent code fails closed: 'Throws when no supported kernel sandbox is available rather than silently running with a weaker policy.' Three projects, three designs; this is the one to copy. |
| Google AX | amends | `internal/harness/substrate/substrate.go:135-138 @ b777313` | AX has no capability declaration and treats absence as acceptable: a harness that does not implement the gRPC health service is "treated as ready". That is **fail-open**, the opposite of Letta's fail-closed rule. The correlation is instructive — Letta's optional capability guards *memory isolation*, AX's guards *readiness*. The ADR must distinguish safety-relevant capabilities (must fail closed) from liveness-relevant ones (may fail open) instead of issuing one blanket rule. |
| Omnigent | confirms | `omnigent/harness_capabilities.py:124-141 @ ba9e371`; `tests/harness_bench/bench.py:44-66`; `omnigent/policies/types.py:59-80` | **Strongest confirmation in the study, and it extends the ADR in four ways.** (a) Capabilities are published on `GET /v1/harnesses` — public API, not an internal detail. (b) An **executable conformance bench** reconciles declared against live-probed and emits **DRIFT** when a declaration is false, so the table is self-enforcing: "you can't lie in `_BUILTIN_CAPABILITIES` without the bench catching it on the next live run." (c) **`None` means "makes no claim" and is reported as UNKNOWN, never assumed unsupported** — the `absent` ≠ `unknown` discipline, inside a capability model. (d) **Verified** is tracked separately from **asserted**: only 4 of 26 harnesses are probe-verified and the docs warn the bench "must not treat those 19 as ground truth." **It also supersedes my own amendment**: `FAIL_CLOSED_PHASES = (PHASE_TOOL_CALL, PHASE_REQUEST)` splits fail-closed by *position in the enforcement path* — `PHASE_TOOL_RESULT` fails open because "by the time the result phase runs the tool has already executed" — which is sharper than my safety-vs-liveness categories. |

## Open questions

- Should capability declarations be versioned independently of the adapter, so a
  capability can be added without a new adapter version?
- Is one vocabulary right for both harness adapters and sandbox providers, or two
  with a shared shape?
