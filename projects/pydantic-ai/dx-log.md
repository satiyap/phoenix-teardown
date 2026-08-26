# DX log — Pydantic AI

Focused pass, 2026-08-26. Installed from PyPI and inspected live objects; did not
run a provider-backed agent or a Temporal worker.

- `pip install pydantic-ai-slim` to working import: **~40 seconds, clean first try**
- Fewest concepts to hello-world in the study

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | Cloned; listed the package | `_deferred_capabilities.py`, `capabilities/`, `_cancel.py`, `_cost.py`, `_ssrf.py`, `_otel_messages.py` — a security module and a capability package, both unexpected |
| 0:05 | Read `capabilities/AGENTS.md` | "Prefer a capability over a new `Agent` constructor kwarg" — capabilities as *extension*, not metadata. Different concept from Omnigent's |
| 0:12 | Found `durable_exec/{temporal,dbos,prefect}` | First project to delegate durability to established engines rather than build it |
| 0:18 | Read `durable_exec/AGENTS.md` | "first-class compatibility targets, not peripheral adapters" |
| 0:24 | Read `_runtime_toolsets.py` | The cancellation-token rejection message — explains the mechanism *and* names the alternative |
| 0:30 | `pip install pydantic-ai-slim`, inspected | **2.35.0**, not the 1.0 my recon claimed. 63 capabilities, `CapabilityPosition` literal confirmed |
| 0:36 | Read `_ssrf.py` | The find of the pass. Credential endpoints blocked even with the escape hatch open |
| 0:45 | Read `docs/logfire.md` | Semconv *versioned*, with deprecated formats and a warning. Better than Cloudflare |
| 0:52 | Read `_cost.py` | Real cost from a maintained external dataset (`genai-prices`) |
| 0:58 | Nearly stopped; checked `docs/` listing | Found `agent-spec.md` — declarative YAML agents. Would have recorded `D10` as absent |

## Friction points

1. **351MB clone for a library.** Mostly docs, examples and lockfiles. Not a
   problem, but it makes `ls` unhelpful as a first orientation step.
2. **Two meanings of "capability" in one ecosystem.** After reading Omnigent's
   declared-metadata capabilities, `pydantic_ai.capabilities` reads as the same
   concept and is not. I had to read `AGENTS.md` to realise the word had shifted
   under me — which turned into the most useful conceptual finding of the pass.
3. **63 capabilities with load-bearing ordering** is a lot of surface. The project
   knows: "Preserve composition order. If a capability wraps model/tool/output/event
   behavior, check how it interacts with `CombinedCapability` and adjacent
   capabilities." That is a warning, not a guarantee.
4. **Stale recon nearly cost me `D10`.** I had the version wrong by a major
   release, and almost finished the pass without finding Agent Specs. Checking the
   `docs/` index before writing conclusions is now part of my per-project routine.

## What was genuinely good

1. **`AGENTS.md` per package.** Short, rule-shaped, and directory-scoped:
   `capabilities/AGENTS.md` and `durable_exec/AGENTS.md` each state what belongs
   there and what must not break. This is the single most efficient documentation
   pattern I have encountered in the study — better than a long design doc, because
   it sits where the decision gets made.
2. **The cancellation-token error message.** It refuses the operation, explains the
   mechanism (`a same-process handle cannot cross the durable execution boundary`),
   and names the fix (`Cancel the durable workflow or flow instead`). Every
   fail-closed message we emit should look like this.
3. **Comments explaining threat models.** `_ssrf.py` says *why* Azure needs an
   explicit entry (public IP), *why* brotli is rejected (single-step expansion),
   *why* Teredo needs its own decode. Security code that teaches while it defends.
4. **Named types for every wrap point.** Seven `Wrap*Handler` types means I could
   enumerate the extension surface without reading the implementation.
5. **Versioned telemetry formats with a deprecation warning.** Someone thought
   about the operator whose dashboard breaks.
6. **`TestModel` / `FunctionModel`.** Provider-free testing, so agent logic is
   testable without credentials or spend.
7. **Type checking that actually helps.** `Agent[DepsT, OutputT]` means a wrong
   output type is a type error, not a runtime surprise.

## Answers to R1–R7

- **R1 install to running:** ~40s, clean. `pydantic_ai_slim` keeps the dependency
  surface small.
- **R2 concepts before hello world:** fewest in the study — an `Agent`, a model
  string, an output type.
- **R3 local dev loop:** excellent. Nothing to stand up; `TestModel` and
  `FunctionModel` run without a provider; `clai` gives an interactive loop.
- **R4 debugging:** strong. OTel spans on GenAI semconv, typed message history,
  Logfire integration, and `pydantic_evals` for systematic measurement.
- **R5 unit testing:** best-in-study for a library. Provider-free model doubles plus
  a whole evaluation package with online evals.
- **R6 deployment:** a library; deployment is your Python host or a durable-engine
  worker.
- **R7 CLI ergonomics:** `clai` is real, and `Agent.from_file` makes a YAML-defined
  agent runnable with no Python.

## Lessons for our own DX

**Write `AGENTS.md` per package, not one design doc per subsystem.** A short
rule-shaped file in the directory where decisions get made is read; a long document
elsewhere is not. Ours should state what belongs in the directory, what must not
break (serializability, ordering, boundary-crossing), and what to check before
adding a feature.

**Make every refusal actionable.** The three-part shape — what was refused, the
mechanism that makes it impossible, the correct alternative — should be the template
for every capability rejection, pin mismatch, and policy denial we emit. A
fail-closed system whose errors do not say what to do instead just relocates the
confusion.

**Ship provider-free test doubles.** `TestModel` and `FunctionModel` mean the
interesting logic is testable with no credentials and no spend. Same lesson as
LangGraph's `InMemorySaver` and AX's `eventlogtest`, now three times over: **ship an
in-memory or fake implementation of every external dependency, or nobody tests the
paths that matter.**
