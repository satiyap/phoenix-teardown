# Spike 02 — the definition pin, end to end

**Verdict: PASS.** ADR-0011's mechanism works and is cheap.
**Date:** 2026-08-26 · **Duration:** ~20 min · **8/8 tests pass**

## The gate

> Digest an agent definition, checkpoint, edit the definition, resume, confirm
> `INCOMPATIBLE`.

Plus one addition I made, because it is the entire justification for the ADR: prove
the **verified LangGraph failure mode** is actually prevented.

## Result

```
Cannot resume run r1: definition_digest changed
  ('d920fe4d...' -> 'f57514c7...'). The agent definition or adapter was modified
  after this run checkpointed. Start a new run, or restore the prior definition.
```

The message has the three parts DESIGN.md §5 requires: **what was refused**, **the
mechanism** (which field changed, with both values), and **the alternative**.

## What the 8 tests establish

| Test | Property |
|---|---|
| `resume_after_edit_is_incompatible` | **The gate.** An edited definition cannot resume |
| `resume_unchanged_succeeds` | The pin is not so brittle that nothing resumes |
| **`langgraph_failure_mode_is_prevented`** | A renamed tool **raises** instead of silently returning `[]` |
| `version_bump_alone_does_not_invalidate` | A declared version is informational; bumping it does not break resume |
| **`forgetting_to_bump_still_detected`** | Content changed, version did not → still caught. **This is the failure Omnigent cannot catch** |
| `adapter_change_detected_separately` | Names *which* pin field moved (AX pins identity; we pin both) |
| `digest_is_canonical_not_ordering_sensitive` | Key order does not change the digest |
| `tool_reordering_does_not_invalidate` | Reordering a list is not a semantic change |

The two bolded tests are the ones that matter. Together they show the mechanism
catches both failure modes the study found in the field: LangGraph's silent work loss
(no version at all) and Omnigent's undetected upgrade (a version nobody pins).

## Design decisions this settles

1. **`version` is excluded from the digest.** Deliberate: bumping it must not
   invalidate checkpoints, and *forgetting* to bump it must not hide a real change.
   Declared versions are for humans; digests are for compatibility. This is
   ADR-0011 amendment 3 made concrete.
2. **`mismatch()` returns the field name, not a boolean.** An error saying
   "incompatible" sends an operator hunting; one saying `adapter_identity changed
   ('acp:claude-code' -> 'acp:codex')` does not.
3. **Canonicalisation is part of the contract, not an implementation detail.**
   `sort_keys=True, separators=(",", ":")` and sorted tool lists. A pin that varies
   by key order fails *randomly*, which is worse than one that never fires.
4. **Four pin fields are enough** for v0.1: `definition_digest`,
   `adapter_identity`, `adapter_digest`, `checkpoint_schema_version`. The
   six-field version in ADR-0011 amendment 2 included two declared versions that
   amendment 3 removed.

## Cost

~90 lines of implementation. This is the cheapest of the four BUILD items and the
one with the clearest verified justification, which is a good argument for doing it
first in Tier 1.

## What this does not prove

- **No real checkpoint payload.** State is a dict; a production checkpoint carries
  adapter-specific bytes whose *own* version is the `checkpoint_schema_version`
  field.
- **No escape hatch** (OQ-037). Accepted for v0.1: a false incompatibility costs a
  restart, a false compatibility costs LangGraph's silent corruption. If operators
  hit false positives often, the fix is an explicit recorded operator assertion —
  never a loosened default.
- **Digest inputs are not final.** `name`, `instructions`, `tools`, `capabilities`
  today. Whether declared *extensions* (ADR-0012) belong in the digest is an open
  design question for the spec: they change behaviour, so probably yes.

## Reproduce

```bash
cd spikes/02-definition-pin
./.venv/bin/python -m pytest test_pin.py -q -s
```
