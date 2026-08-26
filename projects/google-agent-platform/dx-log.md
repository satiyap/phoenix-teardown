# DX log — Google Agent Platform (ADK)

Focused pass, 2026-08-26. Installed from PyPI, inspected live objects, read the
subsystems recon said would not exist.

- `pip install google-adk` to working import: **~60 seconds, clean first try**
- In-memory implementations of every service mean nothing needs provisioning

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | Cloned; listed `src/google/adk/` | `memory/`, `auth/`, `sessions/`, `artifacts/`, `a2a/`, `code_executors/`, `plugins/`, `evaluation/` — far broader than class-B triage implied |
| 0:04 | Read `memory/base_memory_service.py` | **The only real memory service in the study.** Scoped `(app_name, user_id)`, with Vertex Memory Bank and RAG backends |
| 0:11 | Read `memory_entry.py` | `author` + `timestamp`, the latter being *event* time. First real memory provenance |
| 0:16 | Read `sessions/state.py` | `app:` / `user:` / `temp:` prefixes, plus schema validation on unprefixed keys |
| 0:21 | Grepped `TEMP_PREFIX` across backends | Exclusion independently enforced in Firestore and Redis services — not just documented |
| 0:26 | Listed `auth/` | Exchangers *and* refreshers, as separate registries. Best credential subsystem in the study |
| 0:33 | `pip install google-adk`, inspected | 2.7.1; all five credential types and three state prefixes confirmed live |
| 0:40 | Found `apps/_configs.py` | `ResumabilityConfig` — and the clearest statement of the idempotency requirement anywhere |
| 0:46 | Read `events/_rewind_events.py` | Rewind as first-class event semantics with a documented single source of truth |
| 0:52 | Read `telemetry/` | Stable vs experimental semconv as separate modules, plus a pinnable schema version |
| 1:00 | Checked the session schema | **Composite primary key** `(app_name, user_id, id)` — I had assumed convention-only and was wrong |

## Friction points

1. **Large surface with unclear stability boundaries.** `labs/`, `features/`,
   `optimization/`, `experimental` markers, and `@experimental` decorators all ship
   in the package. Working out what is production-ready required reading markers
   rather than docs. The telemetry module is the exception and shows the fix:
   separate stable from experimental into different *modules* so the import path
   tells you.
2. **Class-B triage cost me the most.** I budgeted a day on the assumption this was
   a thin SDK. It answers `H1`, `H5`, `I6`, `I7`, `J4`, `J7`, `K5`, `M3`, `S4`,
   `S6` and `S8` — several better than any other project. The triage signal (README
   plus package shape) was simply the wrong instrument.
3. **Nearly published a wrong claim.** I wrote that tenancy was "by convention, not
   enforcement" before checking the schema, which declares a composite primary key.
   Caught it only because the claim felt too weak for a team that versions its
   storage schema.
4. **Google-stack gravity.** The best implementations (Memory Bank, RAG, Agent
   Engine, Vertex Sessions) are Google-hosted. The interfaces are clean and the
   in-memory implementations work, so this is honest rather than coercive — but
   evaluating the *managed* behaviour is not possible without a GCP project.

## What was genuinely good

1. **An in-memory implementation of every single service.** Sessions, memory,
   artifacts, credentials, code execution. It means the local development path is
   not a mock of the production path — it is the same interface with a different
   injection. This is the most valuable single practice I found in this pass.
2. **`temp:` as a state prefix.** Non-durability marked in the key, so a developer
   sees "this will not survive resumption" at the moment they write it. Paired with
   `ResumabilityConfig`'s explicit warning, the design and the documentation
   reinforce each other.
3. **An error message that names the fallback.** "This memory service does not
   support adding event deltas. Call `add_session_to_memory(session)` to ingest the
   full session." Same shape as Pydantic AI's best message, arrived at
   independently.
4. **Naming the unsafe executor `unsafe_local_code_executor`.** You cannot pick it
   without typing "unsafe".
5. **`adk.experimental.*` declaring no compatibility guarantee**, in the module
   docstring, next to the constants.
6. **A pinnable telemetry schema version.** Someone thought about the operator whose
   dashboards break when span names change.
7. **`llms.txt` / `llms-full.txt`.** Machine-readable documentation shipped in the
   repo — the first project in the study to do this deliberately.
8. **Per-Python-version constraints files.** Reproducible installs across five
   interpreter versions.

## Answers to R1–R7

- **R1 install to running:** ~60s, clean. In-memory services mean no infrastructure.
- **R2 concepts before hello world:** small to start (agent + runner + model), large
  overall (App, Session, four state scopes, four service interfaces, plugins,
  executors).
- **R3 local dev loop:** excellent. In-memory everything, a CLI dev UI, a local
  SQLite span exporter, pinned constraints.
- **R4 debugging:** strong. Full event history, sixteen plugin hooks, a debug logging
  plugin, local trace inspection, and a dev UI.
- **R5 unit testing:** strong. Every service has an in-memory implementation, plus a
  whole `evaluation/` package with eval sets and scenario generation.
- **R6 deployment:** Agent Engine, Cloud Run, GKE, or self-hosted, via the CLI.
- **R7 CLI ergonomics:** real CLI with run, eval, web/dev UI, and deploy.

## Lessons for our own DX

**Ship an in-memory implementation of every pluggable interface, and treat it as a
first-class deliverable rather than a test fixture.** This is now the third
independent confirmation in the study — LangGraph's `InMemorySaver`, AX's
`eventlogtest`, Pydantic AI's `TestModel`, and now ADK's `InMemory*` for six
subsystems. The pattern is not "provide a mock for testing"; it is "the local path
and the production path are the same code". If our adapter, ledger, memory and
policy interfaces each ship a working in-memory sibling, a developer can run the
entire platform with no infrastructure, and every failure path becomes testable.

**Put stability in the import path.** ADK's `_stable_semconv` versus
`_experimental_semconv` means you cannot accidentally depend on an unstable
attribute without importing from a module named experimental. Markers and decorators
are easy to miss; a module name is not.

**Mark non-durability at the point of use.** `temp:` is a four-character prefix that
prevents a whole class of "why did my state vanish" bug. Any state we do not persist
should be named so at the call site.
