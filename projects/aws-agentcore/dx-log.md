# DX log — AWS Bedrock AgentCore

Targeted pass, 2026-08-26, scoped to identity, IAM, tools and sandbox. Installed
the SDK and inspected live types; made no service calls (needs an AWS account with
AgentCore access).

- `pip install bedrock-agentcore` to inspecting types: **~50 seconds, clean**
- Nothing beyond type inspection is possible without an AWS account

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | Cloned; listed `src/bedrock_agentcore/` | `identity/`, `policy/`, `memory/`, `gateway/`, `payments/` — far more than class-B triage implied |
| 0:04 | Read `identity/auth.py` | `auth_flow: M2M \| USER_FEDERATION \| ON_BEHALF_OF_TOKEN_EXCHANGE` — three *named* delegation flows |
| 0:09 | Read `services/identity.py` | **Workload identity**, with three token variants. The first real agent principal in the study |
| 0:15 | Read `policy/client.py` | **Cedar.** The single most consequential finding of Phase 4 |
| 0:21 | Found `start_policy_generation` | Natural language → reviewable Cedar assets |
| 0:26 | `pip install`, inspected live | 1.22.0; all three flows and both plane allow-lists confirmed |
| 0:32 | Read `memory/constants.py` | Typed strategies including `USER_PREFERENCE`; hierarchical namespaces |
| 0:38 | Read `_utils/namespace.py` | Wildcards refused — bounds the blast radius of a path convention |
| 0:43 | Read `runtime/models.py` | `Healthy` vs `HealthyBusy` |
| 0:48 | Assessed what I could *not* determine | 52 probes genuinely unknowable from a client surface; recorded as `unknown` |

## Friction points

1. **Nothing runs locally.** The SDK installs cleanly and the types are inspectable,
   but every capability is a call to a managed service. `CP_ENDPOINT_OVERRIDE` /
   `DP_ENDPOINT_OVERRIDE` let you point at a test endpoint; there is no in-memory or
   local implementation of identity, policy, memory or gateway. Compare ADK, which
   ships `InMemory*` for six subsystems behind identical interfaces and still sells
   the managed versions — the same company-scale constraint, solved.
2. **Most of the architecture is unreadable.** I could determine what the *API*
   offers, not what the *system* does. Durability, orchestration, sandboxing and
   storage are all server-side. This is the only project where I had to record
   `unknown` at subsystem scale, and it took deliberate discipline not to code those
   as `absent` — the matrix would have shown nine gaps that may not exist.
3. **`__version__` is not exposed on the package.** `bedrock_agentcore.__version__`
   raises; I read the version from `pyproject.toml` and confirmed via pip metadata.
   Minor, but it is the first thing a diagnostic script reaches for.
4. **Real behaviour is untestable without an account.** Unit-testing anything means
   mocking boto3, because no service has a local double.

## What was genuinely good

1. **Allow-lists as an SDK design pattern.** `_ALLOWED_CP_METHODS` and
   `_ALLOWED_DP_METHODS` with `__getattr__` forwarding *only* those names, and an
   `AttributeError` that names the boto3 docs to consult. The SDK cannot accidentally
   expose an unvetted control-plane call, and the allow-list doubles as documentation
   of the intended surface — I learned the resource model by reading two sets.
2. **The control/data plane split is visible in the code**, not just in AWS docs.
   Two clients, two allow-lists, two endpoint overrides. Administration and use are
   different surfaces with different permissions.
3. **Choosing Cedar over inventing a DSL.** The same instinct as choosing OTel over
   a proprietary trace format, and it is the reason ADR-0013's hardest requirement
   became tractable.
4. **Naming `ON_BEHALF_OF_TOKEN_EXCHANGE` as a flow.** Most systems treat delegation
   as a flag on user auth; naming it makes the distinction reviewable.
5. **`Healthy` vs `HealthyBusy`.** Two enum values that resolve a real ambiguity in
   supervisor design.
6. **`wait_until_deleted` as a separate helper.** Someone noticed deletion is
   asynchronous and that code assuming otherwise races.
7. **Refusing wildcards in namespaces.** A one-line guard that prevents
   `/actor/*/` from becoming a cross-tenant read.
8. **A `DeprecationWarning` path for a renamed kwarg.** The same
   one-deprecation-window discipline I adopted into ADR-0010 from Pydantic AI,
   applied to an API parameter.

## Answers to R1–R7

- **R1 install to running:** ~50s to install and inspect; *running* requires an AWS
  account, so effectively unbounded for a local evaluator.
- **R2 concepts before hello world:** few SDK concepts (workload, credential
  provider, policy engine, memory), but each maps to a managed service with its own
  AWS-side setup.
- **R3 local dev loop:** **the weakest in the study.** No local mode, no in-memory
  implementations. Endpoint overrides only.
- **R4 debugging:** tracing hooks and explicit `*_FAILED` statuses help; real
  debugging is CloudWatch and X-Ray.
- **R5 unit testing:** `tests/` and `tests_integ/` with `TESTING.md`, and endpoint
  overrides make integration tests possible — but agent behaviour cannot be
  unit-tested without mocking boto3.
- **R6 deployment:** AWS-managed, with a `config_bundle` for packaging. Strong.
- **R7 CLI ergonomics:** a library; agent management is via AWS tooling.

## Lessons for our own DX

**An interface without a local implementation is a dependency, not an abstraction.**
This is the sharpest DX contrast in the study: ADK and AgentCore are both
company-backed SDKs fronting managed services, both Apache-2.0, and ADK ships a
working in-memory implementation of every one of six subsystems while AgentCore ships
none. The result is that I could exercise ADK's memory service in a throwaway venv
and could only read AgentCore's. Our pluggable interfaces must each ship a local
sibling, or they are not really pluggable.

**Allow-lists document intent better than prose.** Reading two Python sets told me
AgentCore's resource model, which operations are administrative, and which are
runtime — faster and more reliably than the README did. Where we expose a
pass-through or a plugin surface, an explicit allow-list is both the guard and the
spec.

**Record what you could not determine.** Half this pass was deciding which
`absent` verdicts were really `unknown`. Fifty-two probes came out `unknown`, and
the capability matrix is more honest for it. A study that cannot distinguish "I read
the source and it does not do this" from "I could not see" produces confident
nonsense.
