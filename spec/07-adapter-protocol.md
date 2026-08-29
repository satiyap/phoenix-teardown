# 07 — Southbound adapter protocol
<!-- status: final -->

gRPC bidirectional streaming. **Two RPCs** (`Run`, `Describe`), and the durability lives in
the control plane — **not** in the adapter. (Amended 2026-08-27: this said "Four methods";
AX's contract is the upstream precedent, not our shape; superseded 2026-08-27.)

The reason is ADR-0012: not every harness can checkpoint. Putting `checkpoint`/`restore`
in the adapter interface guarantees a lowest-common-denominator problem, where either
most adapters declare the capability unsupported or the platform cannot rely on it.
Google AX's contract avoids that, and we copy the *principle* — durability in the control plane — not its method count (amended 2026-08-27).

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
    Start      start       = 1;   // exactly one, first
    Input      input       = 2;   // zero or more
    Cancel     cancel      = 3;   // at most one
    ToolResult tool_result = 4;   // the platform's ANSWER to a ToolCall
    ToolDenied tool_denied = 5;   // policy or an approver refused
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

// The platform's answer to a ToolCall. It travels CONTROL PLANE -> ADAPTER,
// because the platform executes the tool. See "Who executes a tool" below.
message ToolResult {
  string call_id    = 1;
  bool   ok         = 2;
  string content    = 3;
  string error_code = 4;   // required when ok = false
}

// A distinct frame, not ToolResult{ok:false}, because "refused" and "failed" are
// operationally different and an adapter should be able to branch on it.
message ToolDenied {
  string call_id  = 1;
  enum Reason { REASON_UNKNOWN = 0; POLICY = 1; APPROVAL_DENIED = 2;
                APPROVAL_EXPIRED = 3; }
  Reason reason   = 2;
  string guidance = 3;   // remediation text; Agent Control's `steer` payload
}

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

// FOUR frames MUST be typed, because the control plane makes decisions about
// them: ToolCall inbound, ToolResult and ToolDenied outbound, and the Checkpoint
// ENVELOPE. The rest stay opaque. See "What must be typed, and why" below.
message Output {
  string step_id = 1;      // stable across replay; feeds logical_step_path

  oneof body {
    Opaque   text      = 2;   // display only
    Opaque   thought   = 3;   // display only
    ToolCall tool_call = 4;   // TYPED: a REQUEST to execute, not an execution
    Checkpoint checkpoint = 5; // envelope typed, payload opaque
  }
}

message Opaque { bytes data = 1; }

message ToolCall {
  string tool_name  = 1;   // must match a tool in the pinned definition
  string arguments  = 2;   // canonical JSON, per profile nfc+intjson/v1
  string call_id    = 3;   // adapter-scoped; correlates the ToolResult
}

// ToolResult and ToolDenied are defined ABOVE, with the ControlFrame they travel
// in — they are platform-to-adapter, not adapter output.

// NOTE: there is no ApprovalRequest frame. The adapter does not ask for approval;
// it requests a tool call, and the PLATFORM decides whether that needs a human,
// from the tool's approval_mode in the pinned definition and from policy. An
// adapter that could choose when to seek approval could also choose not to.

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
makes a **second** adapter implementable from the contract alone — which is how we keep SDKs
swappable (amended 2026-08-27: this said "a third-party adapter", and no third party writes
adapters for us).

1. The control plane sends **exactly one `Start`**, first.
2. It may then send **zero or more `Input`** frames, **zero or more `ToolResult` /
   `ToolDenied`** frames (one per outstanding `ToolCall`), and **at most one `Cancel`**.
   Every `ToolCall` the adapter emits receives **exactly one** `ToolResult` *or* one
   `ToolDenied`, correlated by `call_id`.
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

## Who executes a tool

**The platform executes tools. The adapter requests them.** This is the decision review
correctly identified as unmade, and it determines the direction of every frame above.

The first draft had `ToolCall` *and* `ToolResult` as adapter **outputs**, which is
incoherent given everything else in this spec: it let an adapter report the result of an
effect the platform is supposed to own, settle a platform-owned claim, and skip policy
entirely. There was also no authorization step — nothing between "adapter says it wants to
call a tool" and "the tool ran".

### The handshake

```
adapter  --> ToolCall{call_id, tool_name, arguments}          Output
                 |
                 |  control plane, in order:
                 |    1. tool_name must exist in the PINNED definition   (else ToolDenied)
                 |    2. evaluate Cedar policy                          (deny -> ToolDenied)
                 |    3. derive the effect key from the canonical args   (03)
                 |    4. record INTENT in the effect ledger             (02, phase 1)
                 |    5. if approval required -> awaiting_approval, create Approval
                 |            ... a human answers, minutes or hours later ...
                 |            denied -> ToolDenied{APPROVAL_DENIED}
                 |    6. CLAIM atomically (02, phase 3)
                 |    7. DISPATCH the tool
                 |    8. SETTLE the claim, fenced (02, phase 5)
                 v
adapter  <-- ToolResult{call_id, ok, content} | ToolDenied{call_id, reason}   ControlFrame
```

The adapter blocks on `call_id` and continues when the answer arrives. It never learns
whether a human was involved, and it cannot tell a fast approval from no approval — which
is the property that makes approval policy changeable without touching adapters.

### Why not let the adapter execute and report

It is the more common design, and most harnesses in the study work that way. It is
incompatible with three things we have already committed to:

| Commitment | Broken by adapter-side execution |
|---|---|
| effect ledger owns at-most-once (ADR-0014) | the claim would be advisory; the adapter has already acted |
| policy decides before the act (ADR-0013) | policy becomes an audit log of things that already happened |
| approval gates the action (ADR-0015) | the adapter chooses whether to wait |

> **Retracted 2026-08-27 (redo 2).** Two paragraphs stood here in turn and both are gone.
> The first accepted "an adapter cannot bring its own tools" as a deliberate cost. The second
> tried to admit vendor-hosted tools under an `observed` ledger status — **a guarantee the
> platform cannot keep**, because a vendor-side tool that executes and then loses the
> connection is never reported, and a deterministic key can collapse two provider executions
> into one row. It also had no test behind it: the spike inserted the row by hand, which is
> asserting the guard's output rather than the guard.

**Tools the platform cannot intercept (vendor-hosted execution) are unsupported in v0.1.**
**Spike 06 decided this on 2026-08-27, and the reason is structural rather than a judgement
call**: `ExternalToolset` withholds a *local* body, and a vendor-hosted tool has no local body to
withhold. The mechanism that makes every other tool safe cannot express them at all. An adapter
that cannot route a tool through the ledger **must not register that tool** — enforced, not
asserted (`UninterceptableTool`, gate 6). Any future admission must be stated as
*"provider-reported use"* rather than as an effect the platform
owns, must require a durable provider receipt for anything stronger, and must carry egress
and confidentiality constraints — not only a mutation-pack restriction.

### In-process SDK adapters route tool calls the same way

`sdk_subprocess` (renamed from `sdk_in_process` 2026-08-29) is the only mode shipped, and it is the mode most likely to cheat: the SDK
ships a working tool executor and calling it is one line.

**One harness, on Pydantic AI.** Pin: **`pydantic-ai-slim == 2.35.0`**, fixed by spike 06 on
2026-08-27 (was a placeholder). The version string is a label for **twenty-two** file digests *(amended 2026-08-28, superseding "nineteen", which superseded "sixteen": round 5 added `tool_manager.py` — where the tool body is actually invoked, `await self.toolset.call_tool(...)` at `:1008` inside `_raw_execute` — plus `capabilities/_tool_search.py` and `toolsets/_tool_search.py`, after a scratch-copy edit at that line turned `ExternalToolset`'s fail-closed refusal fail-OPEN with `pin holds: 19 files` and all 53 gates green. The round-4 note it supersedes, kept rather than erased, said: that pin omitted `models/__init__.py`, where native-tool ADMISSION is decided — `resolve_request_tools` at `models/__init__.py:1812-1930` filters native tools against `supported_native_tools` — so the filter could be neutered with all 47 gates green; `profiles/__init__.py` and `capabilities/__init__.py` were added for the same reason)*: the
source tree uses `uv-dynamic-versioning` (`pyproject.toml:5-6`) and carries no git tags, so it
cannot state its own version. Spike 06 installed 2.35.0 from PyPI and verified every file the
boundary's behaviour depends on is **byte-identical** to the read source at `b48ee38`:
`__init__.py`, `agent/__init__.py`, `_tool_execution.py`, `_deferred.py`, `tools.py`,
`messages.py`, `exceptions.py`, `toolsets/{__init__,abstract,external,approval_required,function}.py`,
`native_tools/{__init__,_tool_search}.py`, `models/{__init__,function,test}.py`, `profiles/__init__.py` and `capabilities/__init__.py`
*(amended 2026-08-27, superseding "five file digests" naming only `agent/__init__.py`,
`_tool_execution.py`, `toolsets/external.py`, `toolsets/approval_required.py` and `_deferred.py`:
that pin left `native_tools/__init__.py` — the module that decides which vendor-hosted tools may
be admitted — unpinned, so it could be edited with every gate still green)*. The digests are
checked before the gate suite is collected; see `spikes/06-tool-interception/verify_pin.py`.

**The boundary is a TOOLSET, not a decorator** *(corrected 2026-08-27 by spike 06; the earlier
text said "the `ToolCall → ledger` boundary is a **decorator** rather than a fork", naming
`@agent.tool` at `agent/__init__.py:2423`/`:2460`)*. That framing assumed Phoenix must intercept
an executor that wants to run. It does not, and interception is the weaker design. Phoenix
declares tools through `ExternalToolset`, whose `call_tool` raises
`NotImplementedError('External tools cannot be called directly')` **unconditionally**
(`toolsets/external.py:46 @ b48ee38` *(citation corrected 2026-08-28: the unconditional raise is at `:46`; `:44` is the `call_tool` parameter line)*) while `get_tools` still advertises them to the model with
`kind='external'` (`:36`). **The SDK is never given an executable body**, so there is no executor
to disable and no wrapper for a future version to route around. `@agent.tool` is not used by
Phoenix at all; spike 06's negative control shows it *is* the bypass.

**Declaring the tool is necessary and not sufficient** *(added 2026-08-27, round 3)*. An
adapter must additionally expose **no `Agent` object** to its caller. `Agent.override` accepts
`native_tools=` (`agent/__init__.py:1969`), and `FunctionModel.supported_native_tools()` returns
every native tool the SDK ships (`models/function.py:242-244`) — so a caller holding the agent
can deliver a vendor-hosted tool to the model with no adapter involvement at all. The v0.1
harness therefore exposes only `register` / `run` / `resume` / `stream_output` / `resolve`, and
refuses `native_tools=`, `toolsets=` and `tools=` at registration. Spike 06 asserts this by
scanning every public name for one that is, or returns, an `Agent`, with a negative control that
re-exposes it and shows the override succeeding.

The adapter boundary is retained so a **second** SDK can be added later without touching the
control plane.

**There is no executor to disable.** The wording that stood here before, asserting that "that
executor MUST be disabled", was superseded 2026-08-27 by spike 06. An in-process adapter routes every tool call across the
same typed boundary as a remote one, and Pydantic AI supplies both halves natively:
`DeferredToolRequests` as an `output_type` **ends the run** and returns the pending calls
(`_deferred.py:27,37`), and `deferred_tool_results=` supplies the platform's results on resume
(`agent/__init__.py:1189` *(citation corrected 2026-08-28: `:1139` is inside the first `@overload` stub of `Agent.iter` — `@overload` at `:1132`, `def iter(` at `:1133`, body `...`; the implementation is `@asynccontextmanager async def iter(` at `:1183`, whose `deferred_tool_results` parameter is at `:1189`. This is the `@overload`-stub error OQ-043's own row records correcting for `:2399`.)*):

```
SDK asks for a tool
   -> adapter emits Output{ToolCall}          (one §07 frame over the pod-local socket)
   -> control plane: pinned-definition check, policy, intent, approval, claim, dispatch
   -> adapter receives ControlFrame{ToolResult | ToolDenied}
   -> adapter hands the result back to the SDK as that tool's return value
```

**Decided 2026-08-28 (OQ-056).** The control plane is Go and the harness is Python, so the transport does not collapse to a function call *(superseded 2026-08-28: this sentence previously said it did)*. `sdk_subprocess` (renamed from `sdk_in_process` 2026-08-28 and from `sdk_sidecar` 2026-08-29 — spike 05 T2 showed two containers cannot share a Unix socket under gVisor) means **the Go driver is PID 1 of the run's container, spawns the Python harness as its child, and hands it one end of an `AF_UNIX` socketpair; these frames travel on that pair** *(amended 2026-08-29; superseded: "a Unix socket in a `0700` directory the driver created")* — the deferred-tool design from spike 06 makes each `DeferredToolRequests` stop exactly one frame exchange. **The contract does not change.** Nothing may reach a
customer system without an `effect_ledger` row, because a tool the SDK executes directly is
an effect the platform cannot claim, police, or attest.

This is why "an adapter cannot bring its own tools" moved from a cost to **the design**
(2026-08-27, with the SaaS repositioning): we build every adapter, so no third party is asking
to bring tools.

**The cost is real, and naming it is the point.** Vendor-hosted tools are **unsupported in
v0.1** — settled by spike 06 (OQ-043 resolved 2026-08-27), not pending it — and the analytics
pack loses web search. An earlier
version of this paragraph (superseded 2026-08-27) claimed the restriction was free while buying
the entire guarantee — the guarantee is real, the zero cost was not.

**Required by §08 inventory rows 30a–30e.** **VERIFIED 2026-08-27 by
`spikes/06-tool-interception/` — 64 gate assertions** *(amended 2026-08-28: 57 → 64 with OQ-065/066 gates)* *(amended 2026-08-28: was "18", the round-1 count; rounds 2 to 5 took it 18 → 26 → 47 → 53 → 57, and nothing in `tools/` reads this number)*, whose negative control runs the same
function through `FunctionToolset` and observes the body execute with **zero ledger rows**. Its
oracle is a filesystem side channel the harness never touches, so the assertions are about
observable effects rather than the SDK's own accounting.

**One finding changed this section.** `_tool_execution.py:399` sets
`executable_function_kinds = ('function', 'unknown', 'external', 'unapproved')` on the **resume**
path — external kinds *do* flow through the regular execution pipeline when
`tool_call_results` is supplied. Resume was therefore a real bypass candidate, not a
hypothetical one; it holds (gate 4), but it is now an inventory row (30d) rather than an
assumption.

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

- **Typed**, because the control plane decides on them: `ToolCall` (inbound),
  `ToolResult` and `ToolDenied` (outbound), and the `Checkpoint` *envelope*.
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

## Transport, authentication, and limits — the socket half SHIPS, the remote half does not

> **Amended 2026-08-28 (OQ-056).** This heading said NOT SHIPPED IN v0.1 and the note said nothing
> below is exercised by the first release *(superseded 2026-08-28)*. The **Unix-socket** transport
> and its `0600` authentication now **ship** — they are how the Go plane reaches the Python
> sidecar. The **remote (TCP + mTLS)** half remains unshipped: there is no remote adapter to authenticate. It is **retained rather than deleted
> because the security reasoning must not be rediscovered** — Google AX ships a distributed
> harness runtime with logging-only interceptors, no authN and no TLS, on a service that
> provisions sandboxes. The first time we add a remote adapter, this section is the answer
> already worked out. Treat it as a design commitment, not a v0.1 requirement.

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
- **Inherited socketpair — SHIPPED (amended 2026-08-29):** the driver creates an `AF_UNIX`
  socketpair and passes one end to the harness it spawns. There is no filesystem socket, so
  nothing else in the container can connect; local access control is spawn-bound rather than
  UID-bound. Protocol authentication is `run_token` on `Start`. *(Superseded 2026-08-29: "`0600`
  socket ownership is the authentication (HumanLayer's model); the sidecar and the driver share a
  pod" — a same-UID process can open a `0600` socket, so ownership was never authentication.)*
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
| Close without `End` **and an unsettled effect** ⇒ `indeterminate` | kill the adapter mid-stream with a `claimed` effect | map it to `failed` ⇒ a false "we know it failed" |
| Close without `End` and **no** unsettled effect ⇒ `failed`, `adapter_disconnected` | kill it with every effect settled | map it to `indeterminate` ⇒ manufactured uncertainty (see rule 5) |
| `FAILED` requires `error_code` | omit it | allow it ⇒ retry logic cannot branch |
| `Cancel` still yields `End` | cancel, assert `End` arrives | allow silent close ⇒ run hangs in `cancelling` |
| `config` is never parsed | send malformed bytes | parse it ⇒ control-plane coupling |
| Unset capability reads `UNKNOWN` | omit a capability | treat as `FALSE` ⇒ silent degradation |
| `ASSERTED` cannot gate a safety decision | assert-only capability on a safety path | allow it ⇒ unproven claim trusted |
| Stable `step_id` across replay | replay a step, compare effect keys | counter-based ids ⇒ duplicate execution |
| One trace id end to end | assert propagation client→plane→adapter | drop propagation ⇒ two traces |
