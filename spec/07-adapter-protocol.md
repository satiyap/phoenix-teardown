# 07 — Southbound adapter protocol
<!-- status: final -->

gRPC bidirectional streaming. Four methods, and the durability lives in the control
plane — **not** in the adapter.

The reason is ADR-0012: not every harness can checkpoint. Putting `checkpoint`/`restore`
in the adapter interface guarantees a lowest-common-denominator problem, where either
most adapters declare the capability unsupported or the platform cannot rely on it.
Google AX's four-method contract avoids that, and we copy it.

---

## Service

```protobuf
syntax = "proto3";
package platform.adapter.v1;

service Adapter {
  // The control plane sends exactly one Start, then zero or more Input or
  // Cancel frames. The adapter streams zero or more Output frames terminated
  // by EXACTLY ONE End frame.
  rpc Run(stream ControlFrame) returns (stream AdapterFrame);

  // Declared capabilities, queried before any Run. Answers a request the
  // control plane makes to decide whether to attempt an operation at all.
  rpc Describe(DescribeRequest) returns (AdapterContract);
}

message DescribeRequest {
  // empty today; present so the RPC can gain fields without a breaking change
}
```

## Frames

```protobuf
message ControlFrame {
  oneof frame {
    Start start = 1;      // exactly one, first
    Input input = 2;       // zero or more
    Cancel cancel = 3;     // at most one
  }
}

message Start {
  string run_id                = 1;
  bytes  config                = 2;  // OPAQUE — see below
  bytes  resumed_payload       = 3;  // adapter's own checkpoint bytes, may be empty
  string payload_schema_digest = 4;  // which format resumed_payload is in
  string traceparent           = 5;  // W3C traceparent header value, verbatim:
                                     //   "00-<32 hex trace>-<16 hex span>-<2 hex flags>"
                                     // NOT a bare trace id — propagation needs the
                                     // parent span and the sampled flag.
  string tracestate            = 6;  // W3C tracestate, may be empty
  Deadline deadline            = 7;
}

message Input  { bytes data = 1; }

message Deadline {
  // absolute, so a slow start does not silently extend the budget
  int64 unix_millis = 1;
}

message Cancel {
  enum Reason {
    REASON_UNSPECIFIED = 0;
    USER_REQUESTED     = 1;
    TIMEOUT            = 2;
    POLICY_DENIED      = 3;
    INTERNAL_ERROR     = 4;
  }
  Reason reason  = 1;
  string detail  = 2;
}

message AdapterFrame {
  oneof frame {
    Output output = 1;     // zero or more
    End    end    = 2;     // EXACTLY ONE, last
  }
}

// Three frames MUST be typed, because the control plane makes decisions about
// them. The rest stay opaque. See "What must be typed, and why" below.
message Output {
  string step_id = 1;      // stable across replay; feeds logical_step_path

  oneof body {
    Opaque          text             = 2;   // display only
    Opaque          thought          = 3;   // display only
    ToolCall        tool_call        = 4;   // TYPED: policy, digest, claim
    ToolResult      tool_result      = 5;   // TYPED: settles the claim
    ApprovalRequest approval_request = 6;   // TYPED: binds to an Approval row
    Checkpoint      checkpoint       = 7;   // envelope typed, payload opaque
  }
}

message Opaque { bytes data = 1; }

message ToolCall {
  string tool_name  = 1;   // must match a tool in the pinned definition
  string arguments  = 2;   // canonical JSON, per profile nfc+intjson/v1
  string call_id    = 3;   // adapter-scoped; correlates the ToolResult
}

message ToolResult {
  string call_id    = 1;
  bool   ok         = 2;
  string content    = 3;
  string error_code = 4;   // required when ok = false
}

message ApprovalRequest {
  string call_id      = 1;   // the ToolCall being gated
  string question     = 2;   // shown to the human, verbatim
  string risk_summary = 3;
}

message Checkpoint {
  bytes  payload               = 1;   // OPAQUE — the adapter's own format
  string payload_schema_digest = 2;   // which format; pinned on the run
}

message End {
  enum Terminal {
    TERMINAL_UNSPECIFIED = 0;
    SUCCEEDED            = 1;
    FAILED               = 2;
    CANCELLED            = 3;
  }
  Terminal terminal   = 1;
  string   error_code = 2;   // required when terminal = FAILED
  string   error_detail = 3;
}
```

## Contract, stated precisely

Google AX's practice: state the *terminator count* in the contract, because that is what
makes a third-party adapter implementable without reading our source.

1. The control plane sends **exactly one `Start`**, first.
2. It may then send **zero or more `Input`** frames and **at most one `Cancel`**.
3. The adapter streams **zero or more `Output`** frames.
4. The adapter sends **exactly one `End`** and then closes.
5. **A stream that closes without `End` is a protocol violation.** The resulting run
   state depends on whether anything external may have happened:
   - some effect for this run is still `claimed` ⇒ **`indeterminate`** (a human must look);
   - no effect is unsettled ⇒ **`failed`, `error_code = adapter_disconnected`** (we know
     nothing external occurred).

   An earlier version made *every* abnormal close indeterminate, which manufactures
   uncertainty and spends human attention on runs whose outcome is known. See
   [§05](05-state-machine.md).
6. After `Cancel`, the adapter must still send `End`. It **may** send `SUCCEEDED` if it
   finished first; cancellation is a request, not a fact (AG2).
7. `error_code` is **required** when `terminal = FAILED`. An unclassified failure cannot
   be branched on by retry logic.

Rule 5 is the one implementers get wrong, and it is why `indeterminate` exists as a run
state.

---

## What must be typed, and why

An earlier version made `TOOL_CALL`, `APPROVAL_REQUEST` and `CHECKPOINT` undifferentiated
`bytes`. That is incompatible with the platform owning effects, policy and approval — with
opaque bytes the control plane cannot:

| do this | without |
|---|---|
| evaluate a Cedar policy on a tool call | the tool name and its arguments |
| derive `request_digest` for the effect key | a canonical form of the arguments |
| **claim the effect atomically before it runs** | knowing a tool call is happening at all |
| bind an approval to the action it gates | a `call_id` to correlate |
| verify the tool is in the pinned definition | the tool name |

So the rule is narrow rather than absolute:

- **Typed**, because the control plane decides on them: `ToolCall`, `ToolResult`,
  `ApprovalRequest`, and the `Checkpoint` *envelope*.
- **Opaque**, because only the adapter and the human care: `text`, `thought`, and the
  checkpoint *payload*.

This does not reopen the boundary AX closed. `Start.config` stays opaque bytes (below),
and a checkpoint's payload stays opaque. What is typed is exactly the set of frames on
which a platform decision depends — and no more, because every typed field is a field a
new adapter must satisfy.

**Consequence for `ToolCall.arguments`:** it is canonical JSON under
[§03](03-canonicalisation.md), so `request_digest` is reproducible. An adapter emitting
non-canonical arguments gets a `422`-equivalent stream error rather than a digest nobody
else can recompute.

## `config` is opaque

`Start.config` is `bytes`, and **the control plane never parses it** (Google AX's
`agent_config`). It is produced by whoever registered the adapter and interpreted by the
adapter alone.

The temptation is to make it structured so the control plane can validate it. Resist it:
the moment the control plane understands adapter configuration, every new adapter needs
a control-plane change, and the boundary is gone.

---

## `step_id` and the effect key

`Output.step_id` must be **stable across a replay of the same logical step**. It feeds
`logical_step_path` in the effect key (§01), so:

- an adapter that emits `step_id` from a counter reset on resume **breaks idempotency**;
- an adapter that emits a UUID per emission **breaks idempotency**;
- an adapter that derives it from position in its own plan is correct.

This is a real requirement on adapter authors and it is the least obvious thing in this
document. It is a **declared capability**: `effect_ledger_participation ∈ {verified,
asserted, unsupported}`. An adapter that cannot provide stable step ids declares
`unsupported` and gets at-most-once-*attempted* semantics, with that limitation recorded
in its contract rather than hidden.

---

## Capability declaration

```protobuf
message AdapterContract {
  string identity            = 1;
  string protocol_version    = 2;
  string integration_mode    = 3;   // §01's enum
  string payload_schema_digest = 4;
  map<string, Capability> capabilities = 5;
}

message Capability {
  // BOTH enums put the unknown case at zero, because proto3 cannot distinguish
  // "absent" from "default". An undeclared capability must never read as a claim,
  // and an undeclared CONFIDENCE must never read as "asserted".
  enum Value      { VALUE_UNKNOWN = 0; TRUE = 1; FALSE = 2; }
  enum Confidence { CONFIDENCE_UNKNOWN = 0; ASSERTED = 1; VERIFIED = 2; }
  Value      value      = 1;
  Confidence confidence = 2;
}
```

**`UNKNOWN` is the zero value on purpose.** A capability nobody declared reads as
"unknown", never as `FALSE` — the `absent` ≠ `unknown` discipline this whole study runs
on, encoded in the wire format. Omnigent is the only project that does this, and it
matters most in a proto3 message where unset fields default silently.

`confidence` separates a claim from a proven claim (AG2/Omnigent). Only `VERIFIED`
capabilities may be relied on for a **safety** decision. An `ASSERTED` capability is
usable for optimisation.

---

## Transport, authentication, and limits

gRPC over TCP or a Unix socket. A remote adapter needs **no co-location** — the reason we
chose a gRPC shape over ACP-over-stdio, with ACP sitting *behind* an adapter rather than
being the transport (ADR-0006).

### Authentication — both directions

Google AX ships a distributed harness runtime with **logging-only interceptors**: no
authN, no TLS, on a service that provisions sandboxes and runs arbitrary harnesses. That
is the anti-pattern this section exists to avoid, and the earlier version of this document
had the same hole.

- **Remote adapters: mTLS required.** The certificate subject must match
  `adapter_contracts.identity`; a mismatch is refused before `Start`. A remote adapter is a
  *principal* (§01), not an anonymous endpoint.
- **Unix-socket adapters:** `0600` socket ownership is the authentication (HumanLayer's
  model). Acceptable only for a same-host, same-user adapter, and the contract records
  which mode applied.
- **Control plane → adapter:** a short-lived bearer token scoped to one `run_id`, so a
  leaked token cannot start unrelated runs.

### Limits and backpressure

| Limit | Value | On breach |
|---|---|---|
| Max frame size | 4 MiB | stream error; the adapter must chunk |
| Max outputs per run | 100,000 | run → `failed`, `error_code = output_flood` |
| `Deadline` | absolute, carried on `Start` | run → `expired` |
| Flow control | gRPC windowing | — |
| Reconnect | **not permitted mid-run** | a dropped stream is a close; see rule 5 |

**No mid-run reconnect.** A reconnecting adapter would have to prove which frames the
control plane already durably recorded — a resumption protocol in its own right.
Resumption already exists at the *run* level, with a pin and a lease; a second, weaker
mechanism at the stream level would be a way to bypass it.

`traceparent` on `Start` is the full W3C header value, so one trace spans client → control
plane → adapter. §08 requires a test asserting that, because **a bare trace id does not
propagate** — without the parent span and sampled flag the adapter starts a new trace.

## Tests, with negative controls

| Invariant | Test | Negative control |
|---|---|---|
| Exactly one `End` | adapter sends two | accept the second ⇒ two terminal states |
| Close without `End` ⇒ `indeterminate` | kill the adapter mid-stream | map it to `failed` ⇒ a false "we know it failed" |
| `FAILED` requires `error_code` | omit it | allow it ⇒ retry logic cannot branch |
| `Cancel` still yields `End` | cancel, assert `End` arrives | allow silent close ⇒ run hangs in `cancelling` |
| `config` is never parsed | send malformed bytes | parse it ⇒ control-plane coupling |
| Unset capability reads `UNKNOWN` | omit a capability | treat as `FALSE` ⇒ silent degradation |
| `ASSERTED` cannot gate a safety decision | assert-only capability on a safety path | allow it ⇒ unproven claim trusted |
| Stable `step_id` across replay | replay a step, compare effect keys | counter-based ids ⇒ duplicate execution |
| One trace id end to end | assert propagation client→plane→adapter | drop propagation ⇒ two traces |
