# 03 — Canonicalisation profile `nfc+jcs/v1`
<!-- status: final -->

The digest rules, written so a Go, Rust or TypeScript implementer produces
byte-identical output to the Python one. **This document is normative.** If an
implementation disagrees with it, the implementation is wrong.

Every pin, effect key and artifact identity in the system depends on this being
reproducible across languages, processes and machines. Spike 02 found the failure
mode the hard way: a `default=str` fallback embedded a **memory address** in a digest,
so two processes computing the same definition produced different digests and nothing
could ever resume.

---

## Why not just "RFC 8785"

**RFC 8785 (JCS) does not normalise Unicode.** It specifies number formatting, key
ordering by UTF-16 code unit, and string escaping — but `"café"` composed (U+00E9) and
decomposed (U+0065 U+0301) remain *different strings* under JCS, and therefore produce
different digests.

For our purpose that is wrong: an operator who retypes an instruction on a different
keyboard has not changed the agent's behaviour, and must not invalidate a checkpoint.

So the profile is named **`nfc+jcs/v1`** — NFC normalisation *then* JCS-style
serialisation — and the name is embedded in every digest so the rules can evolve
without ambiguity.

---

## The algorithm

### Step 1 — validate (fail closed)

Walk the value. **Reject** anything not in the allowed set, with a JSON-path error:

| Allowed | Rejected |
|---|---|
| `null`, `true`, `false` | any other type — no stringification fallback |
| integers within ±2^53−1 | integers outside that range |
| finite floats | `NaN`, `+Inf`, `-Inf` |
| strings | non-string object keys |
| arrays | — |
| objects | duplicate keys after NFC normalisation |

Rejection is an error, never a coercion. **There is no `default=` hook.** This rule
exists because its absence caused the memory-address bug.

> `$.tools[0].handler: Function is not canonically serialisable.`

### Step 2 — normalise strings

Apply **Unicode NFC** to every string value **and every object key**.

If two keys collide after normalisation, that is an error (step 1), not a silent
overwrite.

### Step 3 — wrap in the domain-separated envelope

```json
{
  "kind": "<domain>",
  "canonicalization": "nfc+jcs/v1",
  "payload": <the normalised value>
}
```

`kind` prevents cross-domain collision: a tool digest and a definition digest that
happen to canonicalise identically must not be equal. Registered domains:

| `kind` | Digests |
|---|---|
| `agent_definition` | an agent definition body |
| `tool_binding` | one tool binding |
| `adapter_contract` | an adapter contract |
| `effect_key` | an effect ledger key |
| `checkpoint_payload` | an adapter's checkpoint payload |

`canonicalization` makes a profile change **visible**. Without it, changing the
canonicaliser silently invalidates every stored pin, and "changed" is
indistinguishable from "recomputed differently".

### Step 4 — serialise (JCS rules)

- Object keys sorted by **UTF-16 code unit** (RFC 8785 §3.2.3), not by byte or locale.
- No insignificant whitespace: separators are `,` and `:` exactly.
- Strings escaped per RFC 8785 §3.2.2.2 — only the mandatory escapes; **no `\uXXXX`
  for characters that need no escaping**.
- Output as **UTF-8**, not ASCII-escaped.
- Numbers per RFC 8785 §3.2.2.3.

### Step 5 — digest

```
sha256( utf8_bytes( serialised_envelope ) )   →  64 lowercase hex characters
```

Lowercase hex, always. The schema enforces it: `CHECK (digest ~ '^[0-9a-f]{64}$')`.

---

## Reference vectors

**Normative.** An implementation is conformant iff it reproduces every digest below.
These belong in the test suite of every language binding.

| # | `kind` | payload | expected digest (sha256 hex) |
|---|---|---|---|
| 1 | `effect_key` | `{}` | `99b8e1c162394799246cfc64622837f444e7ec8b1c09a1fc8428a81128115f29` |
| 2 | `effect_key` | `{"a":1}` | `5ba8b395f3df58790a4e12060adbc9110dfd1aa877421ad4ec08fd28ac898bcb` |
| 3 | `agent_definition` | `{"a":1}` | `728021a557cbf3ef9483676c9c2da2952f23feb08c7b5797a9a0bd10a37f52a4` |
| 4 | `effect_key` | `{"s":"café"}` (NFC) | `57559b7e2b726eda36bc593080f468f8bfea9d1d195c078f0649179521d0e1e1` |
| 5 | `effect_key` | `{"s":"cafe\u0301"}` (NFD) | `57559b7e2b726eda36bc593080f468f8bfea9d1d195c078f0649179521d0e1e1` |
| 6 | `effect_key` | `{"b":2,"a":1}` | `cb9d48e93fa12f5f483075dc9a2a2c0415d8a87f6e44179d0c73b9686f6c4dc5` |
| 7 | `effect_key` | `{"k":[1,2,3]}` | `90aac871e9ac40d26d0352e50f151d8ebf57aea009413f1cfc3aca597718a89d` |
| 8 | `effect_key` | `{"n":1.0}` | `b43c826dcf9c5cb36251734fb9e39abe3c221476d42cf8e93c1aeda9cb8372ee` |

Machine-readable fixture: [`canon_vectors.json`](canon_vectors.json). Load it, do not
retype it.

Three equalities are the ones that catch real bugs:

- **#4 == #5** — proves NFC is applied. Both are `57559b7e2b726eda36bc593080f468f8bfea9d1d195c078f0649179521d0e1e1`.
- **#2 != #3** — proves domain separation. Same payload, different `kind`, different digest.
- **#6 == #2-with-sorted-keys** — proves key ordering is normalised.

And #7 proves arrays are **not** sorted — order is semantic in a list, unlike in a key
set. An implementation that sorts arrays will collide #7 with `{"k":[3,2,1]}`.

---

## Field inclusion rules

What goes into a digest is as load-bearing as how it is serialised.

### `agent_definition`

**Included:** `name`, `instructions`, `tools` (sorted by tool name), `extensions`
(sorted).

**Excluded:** `declared_version`, `created_at`, and any other metadata.

The exclusion of `declared_version` is deliberate and was proven in spike 02:

- bumping the version must **not** invalidate a checkpoint (it is a human label);
- forgetting to bump it must **not** hide a real change (the digest catches it anyway).

This is the failure Omnigent cannot catch despite having the study's only monotonic
agent version.

### `tool_binding`

**All of:** `name`, `schema_digest`, `version`, **`artifact_digest`**,
`execution_binding`, `approval_mode`, `credential_ref`.

`artifact_digest` is **required and non-empty**. A version string that points at
mutable code preserves the pin while changing behaviour — the same failure the pin
exists to prevent, one level down. The schema and the constructor both reject an empty
value.

Tools are **sorted by name** before digesting: tool *order* is not semantic, tool
*set* is. Duplicate tool names are an error, not a set-collapse.

### `adapter_contract`

`identity`, `protocol_version`, `integration_mode`, `declared_capabilities`.

Derived, never caller-supplied. A caller-provided adapter digest was a hole in spike
02's first version.

### `effect_key`

`tenant_id`, `run_id`, `logical_step_path`, `request_digest`.

**Position, not time.** A replay of the same logical step derives the same key; a
genuinely different call at the same step derives a different one. And note what is
absent: no channel id, no message id, **nothing tied to message-log retention** — so
channel deletion or compaction cannot change the safety guarantee for an unrelated
external effect (spike 01, criterion 2).

---

## Profile evolution

To change the rules, introduce `nfc+jcs/v2`. Do **not** modify v1.

- New digests are computed under v2 and carry `"canonicalization": "nfc+jcs/v2"`.
- Existing rows keep their v1 digests and their `canon_profile` column records it.
- A run pinned under v1 is compared under v1. Its digest is never recomputed.
- A profile mismatch on resume is an `INCOMPATIBLE` outcome naming the profile, not a
  silent recomputation.

`agent_definitions.canon_profile` exists for exactly this: the row records which rules
produced its key, so a v2 rollout does not orphan v1 artifacts.

---

## Conformance test requirements

| Test | Negative control |
|---|---|
| All reference vectors reproduce | corrupt one vector ⇒ suite fails |
| NFC and NFD forms agree (#4 = #5) | remove normalisation ⇒ they differ |
| Key order does not matter (#6) | remove `sort_keys` ⇒ digests differ |
| Array order **does** matter (#7) | sort arrays ⇒ #7 collides |
| Domain separation (#2 ≠ #3) | drop `kind` ⇒ they collide |
| Profile version changes digests | bump `CANON_VERSION` ⇒ digest changes |
| Unsupported types are rejected | add a `default=` fallback ⇒ a memory address enters the digest |
| Digest is stable across OS processes | — (spike 02 proved this; keep the test) |

That last one is not optional. Spike 02's cross-process test is what would have caught
the `default=str` bug, and a same-process test would not have.
