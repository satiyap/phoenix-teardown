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
  string trace_id              = 5;  // W3C trace context
}

message Input  { bytes data = 1; }

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

message Output {
  enum Kind {
    KIND_UNSPECIFIED = 0;
    TEXT             = 1;
    THOUGHT          = 2;
    TOOL_CALL        = 3;
    TOOL_RESULT      = 4;
    APPROVAL_REQUEST = 5;   // the adapter needs a human
    CHECKPOINT       = 6;   // adapter-owned payload, opaque to us
  }
  Kind   kind    = 1;
  bytes  data    = 2;
  string step_id = 3;   // stable within a run; feeds logical_step_path
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
5. **A stream that closes without `End` is a protocol violation**, and the run becomes
   `indeterminate` — not `failed`. We do not know whether the work completed.
6. After `Cancel`, the adapter must still send `End`. It **may** send `SUCCEEDED` if it
   finished first; cancellation is a request, not a fact (AG2).
7. `error_code` is **required** when `terminal = FAILED`. An unclassified failure cannot
   be branched on by retry logic.

Rule 5 is the one implementers get wrong, and it is why `indeterminate` exists as a run
state.

---

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
  enum Value { UNKNOWN = 0; TRUE = 1; FALSE = 2; }   // TRI-STATE
  enum Confidence { ASSERTED = 0; VERIFIED = 1; }
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

## Transport

gRPC over TCP or a Unix socket. A remote adapter needs **no co-location** — the reason
we chose a gRPC shape over ACP-over-stdio, with ACP sitting *behind* an adapter rather
than being the transport (ADR-0006).

`trace_id` on `Start` is W3C trace context, so one trace spans client → control plane →
adapter, which §08 requires a test to assert.

---

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
