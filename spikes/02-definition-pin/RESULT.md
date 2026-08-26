# Spike 02 — the definition pin, end to end

**Verdict: PASS**, on the revised gate. **24/24 tests**, plus a cross-process proof.
**Date:** 2026-08-26 · **Revised** after review found v1 was a unit sketch with
unsafe canonicalisation.

## What was wrong with v1

The review was right on both counts.

**It was tautological.** Hash an object, keep the hash, compare it later — all in one
process, with a dict for state, no adapter, no restart, and no assertion that the
check happened *before* execution.

**The canonicalisation was unsafe.** Demonstrated, not argued:

| Defect | v1 behaviour |
|---|---|
| `default=str` admitted arbitrary objects | digest embedded `<Obj object at 0x104663e00>` — **a memory address**, so identical definitions in two processes produce different digests and *nothing would ever resume* |
| NaN / Infinity | accepted; not canonical JSON |
| Non-string keys | accepted |
| Unicode | `café` (NFC) ≠ `cafe\u0301` (NFD) |
| Tools | hashed **by name only** — schema, version, execution binding, approval mode and credential all invisible |
| Duplicate tool names | silently collapsed |

The first is the serious one, and it inverts the failure mode: a pin that varies per
process does not cause false compatibility, it causes *nothing to resume at all*.

## What v2 fixes

**Canonicalisation now fails loudly.** `_canon()` walks the structure and raises
`NonCanonical` with a JSON path for anything not stably serialisable. No `default=`
fallback. NFC normalisation on all strings and keys. `allow_nan=False`.

**A tool is not a name.** `ToolBinding(name, schema_digest, version,
execution_binding, approval_mode, credential_ref)` — everything that changes what the
agent *can do* is in the digest. Tools sort by name (order is not semantic) and
duplicate names raise.

**The adapter digest is derived, not supplied.** `AdapterContract(identity,
protocol_version, integration_mode, declared_capabilities).digest`. A caller-supplied
string was a hole.

**Extensions are in the digest.** ADR-0012's installed behaviour changes execution, so
it changes the pin. This resolves a question v1 left open.

**Durable everything.** SQLite `definitions` (content-addressed, digest as primary
key) and `runs` (pin columns + state), with a FK from run to definition.

## The revised gate — all eight properties

| # | Property | Tests |
|---|---|---|
| 1 | Equivalent definitions → identical digests | 2 (incl. tool reordering) |
| 2 | **Every** execution-relevant change mismatches | 9 parametrised: instructions, tool name, schema, version, execution binding, approval mode, credential ref, added tool, extension |
| 3 | Version-only change does not; forgetting to bump still caught | 2 |
| 4 | Non-canonical values rejected | 6: object, NaN, Inf, non-string key, unicode, duplicate tools |
| 5 | **Survives process restart** | 1 + a two-interpreter proof |
| 6 | Definition / adapter-identity / adapter-digest fail **distinctly** | 1 (three assertions) |
| 7 | **No adapter method runs before validation** | 2, via a tripwire adapter that raises if touched |
| 8 | The executed artifact is the one whose digest was checked | 2 |

### The cross-process proof

Two separate OS processes, one file:

```
PROCESS-A wrote run r1, digest 42fc5a52cdc5
PROCESS-B resumed : {'resumed_from': {'progress': '23 files'}}
PROCESS-B refused edit: Cannot resume run r1: definition_digest changed
                        ('42fc5a52cdc5fa21…' -> …)
```

The digest is stable across interpreters — which v1's `default=str` would have broken
— and the edit is still refused after a genuine restart.

### The ordering proof

`TripwireAdapter` records every call and can raise on any. Two assertions:

- on a pin mismatch, `tripwire.calls == []` — **the adapter was never touched**;
- `start()` does not invoke the adapter either, and a valid resume invokes it
  **exactly once**.

### The artifact-identity proof

`resume()` resolves the definition **from the registry by pinned digest**, so deleting
the artifact makes resume refuse (`"no longer in the registry"`) rather than trusting
the caller's in-memory object. The registry is content-addressed: storing the same
definition twice yields one row.

## Design decisions this settles

1. **The declared version is excluded from the digest** — bumping it must not
   invalidate a checkpoint, and forgetting to bump it must not hide a change.
2. **Canonicalisation is a fail-closed contract**, not best-effort serialisation.
3. **Tool identity is the full binding.** Renaming a schema or widening an approval
   mode is an execution-relevant change.
4. **Adapter digests are derived from a declared contract.**
5. **Extensions are digested.**
6. **`mismatch()` returns the field name**, so the error names what moved.

## What is still not proven

- **SQLite, not Postgres**; no concurrent-resume test. Two workers resuming one run
  simultaneously is a control-plane single-writer question, deferred to the spec.
- **The checkpoint payload is a dict.** Real adapter state is opaque bytes whose own
  format is what `checkpoint_schema_version` versions.
- **No escape hatch** (OQ-037). Accepted: a false incompatibility costs a restart, a
  false compatibility costs LangGraph's silent corruption.
- **Cross-language canonicalisation is unspecified.** If a non-Python adapter ever
  computes a digest, the JSON canonicalisation rules must be written down in the spec
  (RFC 8785 / JCS is the obvious candidate).

## Reproduce

```bash
cd spikes/02-definition-pin
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m pytest test_gate.py -q      # 24 passed
```

| File | What it is |
|---|---|
| `pin.py` | Canonical digest, `ToolBinding`, `AdapterContract`, `AgentDefinition`, `Pin` |
| `runtime.py` | Durable `Store`, `Runtime`, `TripwireAdapter` |
| `test_gate.py` | The eight-property gate |
