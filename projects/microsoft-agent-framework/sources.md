# Sources — Microsoft Agent Framework

## Repository

- repo: https://github.com/microsoft/agent-framework
- commit: `e34bf48fa369a5b8d1f66a1558d8e03498153633`
- commit date: 2026-08-26
- cloned on: 2026-08-26 (`--depth 1` to `~/dev/_teardown_src/maf`)
- size: 75MB
- languages: Python, .NET, Go (three parallel SDK trees)
- license: MIT
- Python packages: **35** under `python/packages/`

## Scope of this pass

**Targeted**, per the Phase 3 findings: read for `F` (messaging), `L`
(orchestration), `D9` (revocation) and `D10` (manifests), plus the checkpoint model
once `graph_signature_hash` surfaced.

**52 of 173 probes are recorded `unknown`, not `absent`**, because I did not read
those subsystems. With a 75MB three-language repo the discipline matters: recording
`absent` for a section I never opened would be a fabrication. Sections left
`unknown` include most of `K` (sandbox), `N` (multi-tenancy), and several `S`
scenarios.

## Verification

```
python3 -m venv .venv && ./.venv/bin/pip install agent-framework-core
```

Clean install. Checkpoint shape confirmed live:

```python
from agent_framework._workflows._checkpoint import WorkflowCheckpoint
[f.name for f in dataclasses.fields(WorkflowCheckpoint)]
# ['workflow_name', 'graph_signature_hash', 'checkpoint_id',
#  'previous_checkpoint_id', 'timestamp', 'messages', 'state',
#  'pending_request_info_events', 'iteration_count', 'metadata', 'version']
```

**And the signature-hash mechanism reproduced independently**, to confirm the `C12`
claim rather than trust the code comment:

```
same name, different body -> DIFFERENT hash   2113619054c85e6b / 917aa3374149af7d
identical body            -> SAME hash
```

That is the evidence for the only working version-and-pin in thirteen projects.

## Key source files

| Path | Why it matters |
|---|---|
| `python/packages/core/agent_framework/_workflows/_checkpoint.py:31-82` | `WorkflowCheckpoint`; bound to a **definition**, not an instance |
| `_workflows/_checkpoint.py:48-49` | `graph_signature_hash` — "Hash of the workflow graph topology to validate checkpoint compatibility during restore" |
| `_workflows/_checkpoint.py:51-53` | `previous_checkpoint_id` — checkpoints chain into a history |
| `_workflows/_checkpoint.py:55-58` | **Only committed state** is checkpointed; pending changes excluded |
| `_workflows/_checkpoint.py:59-61` | `pending_request_info_events` — unanswered HITL requests survive |
| `_workflows/_checkpoint.py:62-66` | `iteration_count` is **not unique** per lifecycle; `IDLE_WITH_PENDING_REQUESTS` |
| **`_workflows/_functional.py:987-992`** | **The enforcement**: restore raises on a signature mismatch |
| **`_workflows/_functional.py:1210-1230`** | **The computation**: canonical JSON over name + sorted steps + `sha256(co_code)` + sorted `co_names` |
| `_workflows/_functional.py:1232-1240` | `_discover_step_names` and why the bytecode digest is still needed |
| `_workflows/_runner.py:46,110,122-160` | "Pregel supersteps"; checkpoint at each boundary; `superstep_started` events |
| `_workflows/_edge.py:76,295,470,501,616,650-808` | `Edge`, `EdgeGroup`, `SingleEdgeGroup`, `FanOutEdgeGroup`, `FanInEdgeGroup`, `SwitchCaseEdgeGroup` + `Case` + `Default` |
| `_workflows/_edge.py:399` | `EdgeGroup.register()` for custom topologies |
| `_workflows/_validation.py`, `_viz.py` | Graph validation before execution; graph rendering |
| `_workflows/_workflow_executor.py` | A workflow is itself an executor — composable nesting |
| `_workflows/_request_info_mixin.py:29` | `RequestInfoMixin` — mid-workflow human requests |
| `_workflows/_state.py` | Committed vs pending state |
| `_compaction.py`, `_skills.py`, `_filesystem.py`, `_middleware.py`, `_feature_stage.py` | Core concerns |
| `python/packages/purview/README.md` | **Bidirectional (ingress + egress) DLP policy**, centrally managed |
| `python/packages/purview/agent_framework_purview/_middleware.py:24,150` | `PurviewPolicyMiddleware`, `PurviewChatPolicyMiddleware` |
| `declarative-agents/agent-samples/foundry/MicrosoftLearnAgent.yaml` | Manifest with `kind`, `model.connection`, `tools[].approvalMode`, `allowedTools`, `=Env.` |
| `python/packages/hyperlight/` | Micro-VM package (integration depth not read) |

## Negative findings

| Searched for | Result |
|---|---|
| agent identity / version / **revocation** | **Nothing** — thirteen projects for `D9`. Striking given how rigorously *workflows* are versioned |
| agent-to-agent messaging outside a graph | **Nothing** — no mailbox, no addressing. Messages exist between graph *nodes* |
| principals / authorization of operations | Nothing in the framework; Azure identity externally |
| compensation / rollback | Nothing |
| escape hatch for a compatible workflow edit | **Nothing found** — a bytecode hash has no notion of a semantically-null change (OQ-037) |

## Documentation

| Path | Read on | Notes |
|---|---|---|
| `python/packages/purview/README.md` @ e34bf48 | 2026-08-26 | The clearest statement of ingress/egress policy in the study |
| `declarative-agents/agent-samples/**.yaml` @ e34bf48 | 2026-08-26 | Manifest format |
| `README.md`, `TRANSPARENCY_FAQ.md` @ e34bf48 | 2026-08-26 | Overview |
