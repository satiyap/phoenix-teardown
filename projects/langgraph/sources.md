# Sources — LangGraph / LangSmith

## Repository

- repo: https://github.com/langchain-ai/langgraph
- commit: `38031739e551638e373fb553453256c23feeb41f`
- commit date: 2026-08-24
- cloned on: 2026-08-26 (`--depth 1` to `~/dev/_teardown_src/langgraph`)
- installed for testing: `langgraph` 1.2.11, `langgraph-checkpoint` 4.2.0, `langgraph-sdk` 0.4.3

## Key source files

| Path | Why it matters |
|---|---|
| `libs/checkpoint/langgraph/checkpoint/base/__init__.py:38-160` | `CheckpointMetadata`, `Checkpoint`, `CheckpointTuple` — the durable state contract |
| `libs/checkpoint/langgraph/checkpoint/base/__init__.py:176-745` | `BaseCheckpointSaver` — the southbound storage interface |
| `libs/checkpoint-conformance/langgraph/checkpoint/conformance/capabilities.py` | BASE vs EXTENDED capability split with runtime detection. Best reusable idea in the project |
| `libs/langgraph/langgraph/types.py:89` | `Durability = sync \| async \| exit` |
| `libs/langgraph/langgraph/types.py:418` | `RetryPolicy` |
| `libs/langgraph/langgraph/types.py:521` | `CachePolicy` (perf cache, not idempotency) |
| `libs/langgraph/langgraph/types.py:851-878` | `interrupt()` — including the "re-executing all logic" caveat at :864 |
| `libs/langgraph/langgraph/pregel/_algo.py:550,616,662,834` | Deterministic task IDs (xxhash for v>1, uuid5 below) + checksum assertion |
| `libs/langgraph/langgraph/pregel/_loop.py:466,1023,1134,1324` | Where durability mode changes persistence behaviour |
| `libs/checkpoint/langgraph/store/base/__init__.py:51,545,578,708` | `Item`, `TTLConfig`, `IndexConfig`, `BaseStore` — memory separate from execution state |
| `libs/sdk-py/langgraph_sdk/schema.py:23,34,81,246-383` | Platform object model: statuses, `MultitaskStrategy`, `Assistant`, `Thread`, `Run`, `Cron` |
| `libs/sdk-py/langgraph_sdk/auth/__init__.py:98-225` | Auth handler specificity fallback |
| `libs/sdk-py/langgraph_sdk/auth/types.py:152-202` | `BaseUser` — the only principal type |

## Verification experiments

Written and run 2026-08-26 against langgraph 1.2.11 in a throwaway venv.
Scripts were temporary; behaviour and output recorded in the teardown.

| Probe | Experiment | Result |
|---|---|---|
| `S2` | Node appends to a list, then calls `interrupt()`. Invoke, then resume. | Side effect ran **twice** (`['EFFECT']` → `['EFFECT','EFFECT']`). At-least-once at node granularity. |
| `S3` a | Suspend under V1, resume against same-topology graph with changed node body. | New code ran (`['V2:yes']`). No version pinning. |
| `S3` b | Suspend under V1, resume against graph with the node **renamed**. | Returned `[]` with **no error**. Pending work silently dropped. |
| `S5` | Long-running sync node, caller abandons the invoke. | Worker thread kept running; state showed `log: []`, `next: ('child',)`. No cancel token in the sync path. |

## Negative findings (searched, not present)

| Searched for | Result |
|---|---|
| `opentelemetry` across `libs/` | Nothing. Telemetry is LangSmith-proprietary |
| `agent_id`, `class Agent`, `AgentVersion` in `libs/langgraph/` | Nothing |
| `tenant`, `organization` in `libs/langgraph/` | Nothing |

## Documentation

| URL | Read on | Notes |
|---|---|---|
| https://langchain-ai.github.io/langgraph/ | 2026-08-26 | Runtime concepts |

Platform and LangSmith server are closed source; their behaviour is class B
evidence at best and is marked as such in `facts.yaml`.
