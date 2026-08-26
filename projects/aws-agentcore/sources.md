# Sources — AWS Bedrock AgentCore

## Repository

- repo: https://github.com/aws/bedrock-agentcore-sdk-python
- commit: `826416a2493131f79137c77575bc1e10b9589d56`
- commit date: 2026-08-25
- cloned on: 2026-08-26 (`--depth 1` to `~/dev/_teardown_src/agentcore`)
- size: 7.8MB
- language: Python
- license: Apache-2.0 (`LICENSE.txt`, `NOTICE.txt`)
- package: `bedrock-agentcore` **1.22.0**

**Recon correction:** triaged class B. Upgraded to **class A** — the identity and
policy modules are substantive and independently verifiable. Fourth stale-recon
correction across Phases 3–4.

## Evidence-class caveat (important)

This is a **client SDK over managed AWS services**. I read the SDK surface — API
shapes, enums, allow-lists, documented semantics — not a service implementation.

**52 of 173 probes are recorded `unknown`, not `absent`**, concentrated where a
client surface genuinely cannot answer: `K` sandbox (8), `L` orchestration (7),
`B` runtime (6), `A` and `C` (5 each), `P` storage (4). Coding those as `absent`
would have overstated nine gaps in the capability matrix. This is the only project
in the study where the evidence class degrades at subsystem scale, and it is
tracked as OQ-036.

## Verification

```
python3 -m venv .venv && ./.venv/bin/pip install bedrock-agentcore
```

Clean install. Then inspected the live types:

```python
from bedrock_agentcore.identity.auth import requires_access_token
inspect.signature(requires_access_token).parameters['auth_flow'].annotation
# Literal['M2M', 'USER_FEDERATION', 'ON_BEHALF_OF_TOKEN_EXCHANGE']

from bedrock_agentcore.policy.client import PolicyEngineClient
len(PolicyEngineClient._ALLOWED_CP_METHODS)          # 14

from bedrock_agentcore.services.identity import IdentityClient
sorted(IdentityClient._ALLOWED_DP_METHODS)
# ['get_resource_api_key', 'get_resource_oauth2_token',
#  'get_workload_access_token_for_jwt', 'get_workload_access_token_for_user_id']
```

No live service calls — that would need an AWS account with AgentCore access.

## Key source files

| Path | Why it matters |
|---|---|
| `src/bedrock_agentcore/services/identity.py:140-155` | **Workload identity** — three token variants: bare, `_for_jwt`, `_for_user_id` |
| `services/identity.py:64-73` | `UserTokenIdentifier` / `UserIdIdentifier` as distinct types |
| `services/identity.py:94-111` | Control-plane and data-plane method **allow-lists**, split by plane |
| `services/identity.py:113-128` | `__getattr__` forwarding only allow-listed names, error points at boto3 docs |
| `services/identity.py:76-90` | Two boto3 clients (`bedrock-agentcore-control`, `bedrock-agentcore`) with endpoint overrides |
| `identity/auth.py:23-35` | `requires_access_token` — `auth_flow`, `scopes`, `resources`, `audiences`, `on_auth_url`, `custom_state`, `force_authentication` |
| **`policy/client.py:30-37`** | **Cedar**: `definition={"cedar": {"statement": "permit(principal, action, resource);"}}` |
| `policy/client.py:39-57` | Policy engine + policy + generation CRUD allow-list (14 methods) |
| `policy/client.py:240-290` | `start_policy_generation` — natural language → reviewable Cedar assets, with `clientToken` |
| `policy/client.py:18` | `_FAILED_STATUSES = {CREATE_FAILED, UPDATE_FAILED, DELETE_FAILED}` |
| `memory/constants.py:13-35` | Typed strategies: `SEMANTIC`, `SUMMARIZATION`, `USER_PREFERENCE`, `CUSTOM` (+ `*_OVERRIDE`) |
| `memory/constants.py:76-78` | Namespace templates: `/strategies/{memoryStrategyId}/actors/{actorId}/` |
| `memory/client.py:131-134` | `namespace` (exact) vs `namespace_path` (prefix): `/org/MyOrg/`, `/actor/Jane/` |
| `_utils/namespace.py:18-25` | **Refuses wildcards**: "Wildcards (*) are not supported in namespaces" |
| `_utils/namespace.py:32-50` | `DeprecationWarning` path for `namespaces` → `namespace_templates` |
| `runtime/models.py:9-13,168` | `PingStatus.Healthy` vs `HealthyBusy`; `force_healthy` task action |
| `runtime/a2a.py`, `runtime/ag_ui.py` | A2A and AG-UI as edge protocol adapters |
| `_utils/polling.py`, `_utils/config.py` | `wait_until`, `wait_until_deleted`, `WaitConfig` |
| `_utils/user_agent.py` | `build_user_agent_suffix(integration_source)` for call attribution |
| `gateway/`, `knowledge_base/`, `tools/`, `payments/`, `evaluation/`, `config_bundle/` | Adjacent managed services |

## Negative findings

| Searched for | Result |
|---|---|
| agent versioning | **Nothing.** Credential providers have `update_*` but carry no version |
| agent-level revocation | **Nothing** — only `delete_*_credential_provider`, i.e. revoke what the agent *reaches* (OQ-034) |
| durable agent-to-agent messaging | Nothing; A2A is an edge adapter |
| approval / elicitation resource | Nothing beyond OAuth consent |
| declared capability model | Nothing |
| OpenTelemetry | Nothing in the SDK; CloudWatch/X-Ray server-side |
| SSRF / egress guard | Nothing (contrast Pydantic AI) |
| local / in-memory implementation of any service | **Nothing** — endpoint overrides only. The least favourable local-dev story in the study |
| agent-level cost budget | Nothing; a `payments/` module exists but is not a budget control |

## Documentation

| Path | Read on | Notes |
|---|---|---|
| `README.md` @ 826416a | 2026-08-26 | SDK overview |
| `AGENTS.md`, `TESTING.md` @ 826416a | 2026-08-26 | Repo conventions and test layout |
| `docs/proposals/ag-ui-protocol-support.md` @ 826416a | 2026-08-26 | AG-UI proposal |
| `SECURITY.md` @ 826416a | 2026-08-26 | Reporting policy |
