# 03 — Canonicalisation profile `nfc+intjson/v1`
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

## Why not "RFC 8785"

Two reasons, and the second was found by review after this document first claimed
JCS compliance falsely.

**1. JCS does not normalise Unicode.** RFC 8785 specifies number formatting, key
ordering by UTF-16 code unit and string escaping — but `"café"` composed (U+00E9) and
decomposed (U+0065 U+0301) remain different strings, and therefore different digests. For
our purpose that is wrong: an operator retyping an instruction on a different keyboard has
not changed the agent's behaviour.

**2. Python cannot produce JCS numbers, and pretending otherwise was a real defect.**
RFC 8785 §3.2.2.3 mandates ECMAScript `Number::toString`. Python's `json` does not
implement it:

| value | Python `json` | ECMAScript / JCS |
|---|---|---|
| `1.0` | `1.0` | `1` |
| `4.50` | `4.5` | `4.5` ✓ |
| `1e-7` | `1e-07` | `1e-7` |

An earlier version of this document published `{"n":1.0}` as a **normative** vector
digested from Python's `1.0`. That would have forced every other language to reproduce a
Python quirk in order to interoperate — the exact opposite of the point.

**The fix is to constrain the domain rather than reimplement ECMAScript.** The profile
accepts only **integral numbers in the JS-safe range** (|v| ≤ 2^53−1), converts integral
floats to integers, and **rejects everything else with a loud error**. Fractional and
very large values must be encoded as strings by the caller.

This is a real restriction on callers and it is the correct trade: a rejected number is an
error someone fixes in minutes, while a silently mis-serialised one is a digest that
differs across languages — and therefore a run that can never resume.

Because the profile is no longer JCS, **it is not called JCS**. The name is
`nfc+intjson/v1`, and it is embedded in every digest so the rules can evolve
unambiguously.

## The algorithm

### Step 1 — validate (fail closed)

Walk the value. **Reject** anything not in the allowed set, with a JSON-path error:

| Allowed | Rejected |
|---|---|
| `null`, `true`, `false` | any other type — no stringification fallback |
| integers with \|v\| ≤ 2^53−1 | integers outside that range |
| **integral** floats (converted to int) | **non-integral** floats, `NaN`, `±Inf` |
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
  "canonicalization": "nfc+intjson/v1",
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

### Step 4 — serialise

- Object keys sorted by **UTF-8 byte order**. *Not* UTF-16 code units, *not* locale.

  This is the profile's own rule and it deliberately differs from RFC 8785 §3.2.3.
  The two disagree for non-BMP characters, because in UTF-16 a non-BMP character is a
  surrogate pair starting `0xD800`, which sorts *below* `U+E000`:

  | | first | second |
  |---|---|---|
  | UTF-8 byte order (**ours**) | `U+E000` | `U+1F600` |
  | UTF-16 code units (RFC 8785) | `U+1F600` | `U+E000` |

  UTF-8 order is chosen because it is trivially reimplementable with a byte comparator in
  any language, and because it coincides with code point order — so no implementation has
  to special-case surrogates to get the ordering right. Vectors #14–#16 pin it.
- No insignificant whitespace: separators are `,` and `:` exactly.
- Strings escaped per RFC 8785 §3.2.2.2 — only the mandatory escapes; **no `\uXXXX`
  for characters that need no escaping**.
- **Unpaired UTF-16 surrogates (U+D800–U+DFFF) are rejected**, in values and in keys.
  They are not characters, and languages disagree: Python raises `UnicodeEncodeError`
  while `JSON.stringify` accepts one and emits an escape. Leaving that latent means a
  future implementation can legitimately produce a different digest. Vectors
  `lone_surrogate` pin the rejection; a *valid* pair (#18, #21) is accepted.
- Output as **UTF-8**, not ASCII-escaped.
- Numbers: integers only, emitted without a fractional part. `-0.0` becomes `0`.
  Non-integral values never reach this step (rejected in step 1).

### Step 5 — digest

```
sha256( utf8_bytes( serialised_envelope ) )   →  64 lowercase hex characters
```

Lowercase hex, always. The schema enforces it: `CHECK (digest ~ '^[0-9a-f]{64}$')`.

---

## Reference vectors

**Normative.** An implementation is conformant iff it reproduces every digest below.
These belong in the test suite of every language binding.

| # | `kind` | payload | expected digest (sha256 hex) | asserts |
|---|---|---|---|---|
| 1 | `effect_key` | `{}` | `4fe8320e537447f9310c9e62684990617e18c3e748c537153b2a567a97e14ef6` | empty object |
| 2 | `effect_key` | `{"a": 1}` | `dcd367749cedc70ee9abc6f29f7daf0a3665a4bf0ac13cc3cdfee86df243abf6` | baseline |
| 3 | `agent_definition` | `{"a": 1}` | `a040c2b8fc415fc9447e8f74e1e52a4071479f1d91f29af92df80cedb630cb55` | domain separation: MUST DIFFER from #2 |
| 4 | `effect_key` | `{"s": "café"}` | `5f0b2a10ca64589a468496aa779ffa0138a2f451e05c6dd3b5d5bc094d64fa66` | NFC |
| 5 | `effect_key` | `{"s": "café"}` | `5f0b2a10ca64589a468496aa779ffa0138a2f451e05c6dd3b5d5bc094d64fa66` | NFD: MUST EQUAL #4 |
| 6 | `effect_key` | `{"b": 2, "a": 1}` | `4485a589208d3e24486f18e40800f23548580aab3063d6434d11f1a24623a58a` | key order normalised |
| 7 | `effect_key` | `{"k": [1, 2, 3]}` | `1cbf5b1ef23cb173f8e19bdde499226fbbacad50598810b27a5766835571cdc5` | array order IS significant |
| 8 | `effect_key` | `{"n": 1.0}` | `50153b6132668fbe3a1cbbb1f0c0a48e77d3e5a44a88f1850827e0a4feb8fc81` | integral float -> integer; MUST EQUAL #9 |
| 9 | `effect_key` | `{"n": 1}` | `50153b6132668fbe3a1cbbb1f0c0a48e77d3e5a44a88f1850827e0a4feb8fc81` | integer 1 |
| 10 | `effect_key` | `{"n": -0.0}` | `c2ee7c80535394bca7780f48a1fe59492970ceb43d362681eb5caf598b2d2466` | negative zero -> 0; MUST EQUAL #11 |
| 11 | `effect_key` | `{"n": 0}` | `c2ee7c80535394bca7780f48a1fe59492970ceb43d362681eb5caf598b2d2466` | integer 0 |
| 12 | `effect_key` | `{"n": 9007199254740991}` | `d574524f726f11abb503f1f52b7410d7342fa34e4d339d806ff8a0276b8af4ab` | 2^53-1: largest accepted integer |
| 13 | `effect_key` | `{"s": "4.5"}` | `be962f2baa1fc111e6346d639d9c6b0e6bca406461bc16d3d1bfad1119f23529` | fractional values encoded as STRINGS |

### Required rejections

| payload | reason |
|---|---|
| `"non-integral float"` | $ |
| `"integer > 2^53-1"` | $ |
| `"NaN"` | $ |
| `"Infinity"` | $ |
| `"arbitrary object"` | $ |
| `"non-string key"` | $: non-string key 1 |

Machine-readable fixture: [`canon_vectors.json`](canon_vectors.json). Load it; do not
retype it. It contains both the accept and the reject cases.

Four relations carry the weight:

- **#4 == #5** — NFC is applied.
- **#8 == #9** — an integral float digests as an integer (the JCS-derived rule).
- **#10 == #11** — negative zero normalises to zero.
- **#2 != #3** — domain separation: same payload, different `kind`, different digest.

And **#7** proves arrays are *not* sorted — order is semantic in a list, unlike in a key
set. An implementation that sorts arrays collides #7 with `{"k":[3,2,1]}`.

---

## Field inclusion rules

What goes into a digest is as load-bearing as how it is serialised.

### `agent_definition`

**Included:** `name`, `instructions`, `tools` (sorted by tool name), `extensions`
(**ordered**, see below).

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

### `extension_binding`

An earlier version digested extensions as **sorted strings**, which was wrong twice:

1. **Order is semantic.** Extensions compose, and Pydantic AI's `CapabilityPosition`
   (`outermost` | `innermost`) exists precisely because the order changes behaviour.
   Sorting them discards that.
2. **A name does not pin an implementation.** Changing extension code behind the same
   name left the definition digest unchanged — the same hole `artifact_digest` closes for
   tools, one level over.

So an extension is a full binding, and the list is digested **in declared order**:

```
ExtensionBinding {
    name              // e.g. "Instrumentation"
    artifact_digest   // REQUIRED: immutable code identity
    config_digest     // digest of its configuration
    position          // "outermost" | "innermost"
}
```

`extensions` is therefore an **array of objects in declared order**, not a sorted array of
strings. Reordering two extensions changes the digest, because it changes what the agent
does.

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

To change the rules, introduce `nfc+intjson/v2`. Do **not** modify v1.

- New digests are computed under v2 and carry `"canonicalization": "nfc+intjson/v2"`.
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
