# 13 — The sdk_subprocess adapter
<!-- status: draft -->

What this settles: how [§07](07-adapter-protocol.md)'s frames travel between the Go driver and
the Python harness inside one run's container. The process model, the record framing on the
inherited socketpair, what `Start` carries, deadline and cancel propagation, the size limits,
what each side does when the other dies, the checks the driver performs **before it creates a
process**, and the contract the driver registers in `adapter_contracts`.

What it deliberately does not settle: what the harness does with a frame once it holds one (spec
12 owns the policy over Pydantic AI's seams); the sandbox's three boundaries and the egress
guard (Tier 2); OTel span names (Tier 2); the remote TCP + mTLS transport §07 retains as a
design commitment rather than a v0.1 requirement (`07-adapter-protocol.md` §Transport, authentication, and limits); and the
northbound half of a run, which is [§06](06-api.md).

The mode is `sdk_subprocess`, the only value `adapter_contracts.integration_mode` may take
(`01-schema.md` §Adapter contracts). It was renamed twice — 2026-08-28 and 2026-08-29 — and
`01-schema.md` §Adapter contracts records both names it superseded.

---

## 1. Process model

The sandbox unit is the pod and it holds **one container** (`ADR-0016:63`). Two containers were
specified until spike 05 T2 measured that a Unix-socket inode on a shared `emptyDir` never
appears in the sibling container under gVisor `release-20260817.0`, while a regular file on the
same volume does and the identical pod without the `RuntimeClass` connects
(`spikes/05-sandbox-sidecar/T2-FINDING.md:4, 20-41 @ 9f21e88`).

1. The **Go driver is PID 1** of that container. It is the process Kubernetes starts and the
   process whose exit ends the pod. It is **not** the worker of §05's actor column: the
   **control plane** is, and it holds the `run_leases` row and its `fence_token`
   (`01-schema.md` §Leases). The driver holds no route to that database and no credential but
   `run_token` ([`15-sandbox.md`](15-sandbox.md) §6,
   [`14-credentials.md`](14-credentials.md) §The driver holds only `run_token`), so §6's
   outcomes are **reports the plane turns into worker writes** — which is why §5 keeps two
   transitions away from it and why this document never gives the driver a database
   predicate.
2. Before any spawn the driver creates an `AF_UNIX`, `SOCK_STREAM` **socketpair** and passes
   one end to the child by fd inheritance, at **fd 3** — the descriptor number is this
   document's convention, not `ADR-0016:65-70`'s, and is owed to the spike 05 socketpair gate
   alongside the record framing (§What this does not guarantee). There is no filesystem socket,
   so no later process in the container — a `kubectl exec`, a same-UID sibling — has a path to
   connect to (`ADR-0016:65-70`). Access is spawn-bound, not UID-bound; `0600` ownership was
   never the authentication and saying so was superseded on 2026-08-29
   (`07-adapter-protocol.md` §Authentication — both directions).
3. The driver closes its copy of the child's end immediately after the fork. If it does not,
   the harness's exit never surfaces as EOF and rule 5 below can never fire.
4. As PID 1 the driver reaps children and must not exit while the harness lives. A driver
   that exits first takes the PID namespace with it (§6).
5. **One harness process per `Run` stream, and the driver never re-spawns it within one
   stream.** A run may have several spawns — checkpoint-and-kill makes that ordinary
   (`ADR-0016:75-79`) — but each is a fresh container, a fresh pair and a fresh `Start`.
   Re-spawning *onto an existing stream* is mid-run reconnection under another name, and §07
   refuses that because a reconnecting adapter would have to prove which frames were already
   durably recorded (`07-adapter-protocol.md` §Limits and backpressure). Resumption exists at the run level,
   with a pin and a lease, and §7 below is how the driver reaches it.

## 2. The channel: one `Run` stream, record-framed

The pair carries exactly one §07 `Run` stream and nothing else. `Describe` never travels on it —
it is queried before any `Run` (`spec/contracts/adapter.proto:10-12`), when neither process
exists, so the contract is a property of the **driver image**, read from it at
build/registration time rather than from a live process (§8).

Each frame is one record:

```
record := length:uint32be | kind:uint8 | payload:bytes
          length counts kind + payload
          kind 1 = ControlFrame   (driver  -> harness)
          kind 2 = AdapterFrame   (harness -> driver)
          payload = the proto3 encoding of that message (spec/contracts/adapter.proto)
```

The messages are §07's, unchanged; only the envelope is new. The `kind` byte is redundant with
direction and is carried anyway, because it turns a stream desync into an immediate refusal
instead of a mis-parsed frame.

**Why not gRPC on the pair.** A socketpair yields a *connected fd*, and a gRPC server binds an
address rather than adopting a connection. Whether `grpcio` can serve on an inherited connected
fd is **unknown — OQ**; nothing in this repository has run it. The record framing is specified
because it is implementable and testable today, and because §07's contract — frame order,
terminator count, limits — is independent of its carrier (`07-adapter-protocol.md` §Contract, stated precisely).
gRPC remains the transport for the remote half that does not ship.

**Both sides read and write independently.** Neither may stop draining its read side while it
waits for something else: a driver that blocks reading while it awaits a control-plane decision,
and a harness that blocks writing `Output`, deadlock the pair. The socket buffer is the
backpressure *(amended 2026-08-30: `07-adapter-protocol.md` §Limits and backpressure says `Flow control | gRPC
windowing`, which the socketpair half supersedes; the remote half retains it)*.

## 3. `Start`

`Start` is sent once, first (`07-adapter-protocol.md` §Contract, stated precisely, rule 1), and carries:

| Field | Source | Note |
|---|---|---|
| `run_id` | `runs.run_id` | `Start` carries no tenant field; the driver holds the run's tenant from its spawn parameters, and every row it writes is keyed `(tenant_id, …)` (`01-schema.md` §Adapter contracts, `:732`). One container serves one run |
| `config` | the registered contract | opaque; the control plane never parses it (`07-adapter-protocol.md` §`config` is opaque) |
| `resumed_payload` | the adapter checkpoint artifact | empty on first start |
| `payload_schema_digest` | `runs.pinned_payload_schema` | the format `resumed_payload` is in |
| `traceparent` / `tracestate` | the control plane | full W3C header value, verbatim |
| `deadline` | `Deadline.unix_millis`, absolute | unchanged across resumes (§5) |
| `run_token` | minted by the driver, per spawn | protocol authentication (`ADR-0016:71`) *(amended 2026-08-30: `07-adapter-protocol.md` §Authentication — both directions scopes a control-plane-minted bearer token to one `run_id`; a token the control plane mints and never verifies stores a secret for no verifier, and checkpoint-and-kill makes several spawns per run ordinary — `ADR-0016:75-79`)* |

`run_token` is a 256-bit random value the driver mints immediately before the spawn (amended
2026-08-30: `07-adapter-protocol.md` §Authentication — both directions scoped a control-plane-minted
bearer token to one `run_id`; this document reverses that for the socketpair half, for the reason
in the table above, and §07's own bullet now records the reversal), passes it to the child in the
child's environment only, and then sends it on `Start`. The harness refuses a `Start` whose
`run_token` differs from the value it was spawned with, and refuses any second `Start`
(`07-adapter-protocol.md` §Contract, stated precisely, rule 1); either refusal exits
non-zero without `End`, which is §6's path. The token's job is to bind this stream to this spawn
— a `Start` replayed from an earlier spawn of the same run, which checkpoint-and-kill makes an
ordinary occurrence (`ADR-0016:75-79`), does not authenticate. It is **not** a defence against a
process that holds a socketpair end; §What this does not guarantee says so plainly.

`run_token` is `Start` field **tag 8** (`07-adapter-protocol.md:50-66`;
`spec/contracts/adapter.proto`). The tag was assigned 2026-08-30 together with
`turn_ordinal_seed` at tag 9 ([`12-harness.md`](12-harness.md) §5), because this document and
that one each claimed tag 8 independently and only one wire format can be right.

`run_token` is never written to `run_events.payload`. The frame is logged as `adapter.frame`,
whose payload is `{kind, data}` (`04-events.md` §Adapter); the driver elides the token from `data`
before the insert. Nothing is lost by it — the token is minted per spawn and is never an input
to the fold — and `04-events.md` §Adapter records the exclusion on the event row itself.

**The checkpoint bytes ride `Start`, and they are bounded.** The encoded `Start` frame carrying
`resumed_payload` is subject to the 4 MiB ceiling (`07-adapter-protocol.md` §Limits and backpressure), and `Start`
also carries `config`, `traceparent`, `tracestate` and `run_token`, so the driver measures the
encoded frame, not the payload alone. A stored checkpoint whose `Start` does not fit is refused
**before the spawn**, and the run fails with `error_code = checkpoint_too_large`. Chunking it
would be a second resumption protocol, which is the thing §07 refuses.

## 4. Frame mapping

| Frame | Direction on the pair | Driver's obligation |
|---|---|---|
| `Start` | driver → harness | exactly one, first; refuses to send it before §7's checks pass |
| `Input` | driver → harness | forwarded verbatim |
| `ToolResult` / `ToolDenied` | driver → harness | exactly one per outstanding `call_id` (`07-adapter-protocol.md` §Contract, stated precisely, rules 2-3); a second answer for an answered `call_id` is refused |
| `Cancel` | driver → harness | at most one; see §5 |
| `Output{text,thought}` | harness → driver | opaque; forwarded for the log |
| `Output{tool_call}` | harness → driver | `call_id` must be unseen in this **run**, not merely in this spawn |
| `Output{usage}` | harness → driver | typed; forwarded to the log for pricing against the pinned snapshot ([`18-cost.md`](18-cost.md)) — the harness reports tokens and never money (`07-adapter-protocol.md` `message Usage`) |
| `Output{checkpoint}` | harness → driver | `payload_schema_digest` must equal `runs.pinned_payload_schema` |
| `End` | harness → driver | exactly one, last; a frame after `End` is refused |

**`call_id` uniqueness is per run, not per spawn.** The `call_id` correlates an `effect_ledger`
row whose key already carries `request_digest` (`01-schema.md` §Effect ledger), and spike 06 showed
what a mismatched correlation buys: intending one call and dispatching another under one id ran
the second and settled the first (`spikes/06-tool-interception/RESULT.md:52-54`). A repeated
`call_id` is therefore a refusal by the driver, not a best-effort match. The driver keeps the
answered set in the log rather than in memory, because the harness may not rely on process
memory surviving and neither may its driver (`ADR-0016:85-87`).

**A checkpoint follows the tool calls of a step, before the harness waits.** With
`DeferredToolRequests` as the output type the SDK run *ends* at the deferred calls
(`07-adapter-protocol.md:320-322`), so the harness has a natural boundary there: after the last
`Output{tool_call}` of a `step_id` and before it awaits any answer, it emits exactly one
`Output{checkpoint}` covering that step. The driver **forwards** it; the **control plane**
persists it only while **no** `effect_ledger` row for the run is `claimed` — non-negotiable 7,
`00-overview.md:83-84`: a checkpoint may not hold a half-applied mutation — as
[`12-harness.md`](12-harness.md) §9 rule 1 states. The driver cannot evaluate that predicate;
it reads no ledger. In the case this rule exists for the calls are
`intended` or `awaiting_approval`, so it stores; a checkpoint emitted over a `claimed` row is
dropped, and the resume falls back to the previous step. Without the rule, checkpoint-and-kill
during a human approval (`ADR-0016:75-79`) has nothing newer than the previous step to resume
from.

**Output budget.** §07's 100,000-output ceiling (`07-adapter-protocol.md` §Limits and backpressure) is counted per
**run**, summed from the log across spawns. Counting per spawn would let a resume reset the
budget — the same defect as a `step_id` counter reset on resume (`07-adapter-protocol.md:411`).

## 5. Deadline and cancel

`Deadline.unix_millis` is absolute, so a slow spawn does not extend the budget, and the same
value is re-sent on every resumed `Start`. The driver arms a timer on it. On expiry it sends
`Cancel{TIMEOUT}` and starts the shutdown sequence below. The driver does not write `running →
expired` or `running → indeterminate`: both are **system only** (`05-state-machine.md:86-87`,
`:114-116`). It reports; the system decides those two.

Shutdown sequence, after `Cancel` for any reason:

1. Wait for `End`. §07 rule 6 requires one, and it may be `SUCCEEDED` — cancellation is a
   request, not a fact (`07-adapter-protocol.md:200-201`).
2. After a configurable grace window with no `End`, `SIGTERM` the harness; after a second
   window, `SIGKILL`. Both are driver configuration, never visible to the harness — the same
   treatment `ADR-0016:80-82` gives the warm window — and no value is fixed here: a number
   chosen without a measured `End` latency would be evidence-free.
3. A kill before the grace window elapses manufactures a rule-5 close and is a defect, not a
   shortcut: it converts a run whose outcome the harness was about to state into one the
   control plane must classify.

`cancelling → cancelled` still requires that no `effect_ledger` row for the run is `claimed`, or
that the lease has expired (`05-state-machine.md:154`). Nothing in the shutdown sequence weakens
that.

## 6. Loss

**Harness gone (SIGCHLD).** The driver's read side reaches EOF and `wait4` yields the exit
status. Mapping:

The driver reports the left column. The right column is the **system's** classification,
made against the ledger the driver cannot read:

| What the driver OBSERVED and reported | How the system classifies it |
|---|---|
| `End`, then exit | §07's terminal governs; the exit status is recorded as evidence only |
| exit before `End` (EOF, then a `wait4` status), **with some `effect_ledger` row for this run still `claimed`** | `indeterminate`, set by the system (`05-state-machine.md:104-106`) |
| exit before `End`, with no unsettled effect | `failed`, `error_code = adapter_disconnected` (`07-adapter-protocol.md:191-195`) |
| the driver refused a frame and closed, reporting the rule it refused on | `failed`, `error_code = adapter_protocol_violation`, detail naming the rule — unless an effect is `claimed`, in which case `indeterminate` wins |

The last row is a different event from rule 5: rule 5 classifies a close the driver did not
cause, and an unclassified failure cannot be branched on by retry logic
(`07-adapter-protocol.md:202-203`). The exit status is evidence, never a verdict about an effect
— the same rule that forbids a sandbox provider asserting an effect outcome (`ADR-0016:44-45`).

**Driver gone.** PID 1's death ends the container's PID namespace and the kernel kills the
harness. If the harness observes EOF on its read side before the kill lands it MUST exit
non-zero without attempting further work; if the kill lands first it never runs again, and
neither ordering is relied on. The *harness* cannot have started a tool: it is given no
executable body at all (`07-adapter-protocol.md:300-302`). What the *platform* dispatched on its
behalf is not covered by that — which is why an effect left `claimed` by the lost holder is the
case the next sentence handles, and why model requests in flight are evidence for §05's two
rules and nothing more. The control plane learns of the loss the way it learns of any lost
holder — the run lease expires and is reclaimed (`02-consistency.md:449-466`), and an effect
claim left `claimed` by the lost holder expires into `indeterminate` on its own sweeper
(`02-consistency.md:470-476`), which is §05's first rule; a run with no unsettled effect takes
§05's second (`05-state-machine.md:104-108`).

## 7. Resume: the checks that precede the spawn

**A spawn is an adapter invocation.** §05's ordering guarantee says no adapter method may be
invoked before the final step (`05-state-machine.md:166-196`), and a harness process that has
been created has already read a checkpoint and may already be talking to a model. So no process
exists until, in order:

```
CONTROL PLANE, before it asks the provider to Create (15 §1):
1. the run and its pin are loaded
2. the artifact is resolved from the registry BY DIGEST        -> artifact_missing
3. the artifact hashes to its own key                          -> artifact_corrupted
4. the pin is compared field by field                          -> incompatible (names the field)
5. the fenced lease is held, unexpired, with its token          -> concurrent_resume

DRIVER, inside the container, on the plane's go-ahead:
4b. the materialised knowledge tree is verified against
    manifest.json in BOTH directions, and the manifest
    projection digests to the pinned package digest            -> knowledge_missing | knowledge_corrupted
6. THEN socketpair, THEN spawn, THEN Start
```

(§05's step 5, the `revoked_definitions` check, is renumbered away because v0.1 does not ship it
— `05-state-machine.md:179, 188`; when it ships it lands between 4 and 5 here.)

**This list is the complete pre-spawn order, and three documents write into it. The split is
not cosmetic:** steps 1-5 each read the control-plane database — the registry, the pin, the
lease — and the run container has no route to it ([`15-sandbox.md`](15-sandbox.md) §6), so they
are the plane's and the driver never performs them. What the driver performs is step 4b, the
in-container tree walk [`16-knowledge.md`](16-knowledge.md) §Materialisation already assigns to
it, and it MUST NOT send `Start` until the plane's go-ahead has arrived: the driver walks the
materialised tree and the manifest in both directions before it spawns anything, because a
harness reading an unverified tree is a run executing unpinned content. Step 4's field list
below likewise names a pin this document does not own.

Steps 2 and 3 are re-performed by the plane on the bytes it resolved, not trusted from the
caller: the artifact that executes must be the artifact whose digest was checked
(`00-overview.md` non-negotiable 6). Step 4 is `05-state-machine.md:174-176` in full —
`runs.pinned_definition_digest` first, and the knowledge-package digest *through the definition
body*, which is a different check from step 4b's tree walk — of which the three fields this
document owns are `runs.pinned_adapter_identity` and `runs.pinned_adapter_digest` against the
contract compiled into the driver image, and `runs.pinned_payload_schema` against the harness's
declared checkpoint format (`01-schema.md` §Run), **and, where the run pins one,
`runs.pinned_bundle_id` / `_revision` / `_digest` against the registered bundle
([`10-work-bundles.md`](10-work-bundles.md) §Schema)**, because a bundle supplies the
executables and the `type_roles` table, so a changed bundle changes what the run may do. Step 5
is `run_leases` with `fence_token` (`01-schema.md` §Leases), the same predicate the effect claim
re-checks (`02-consistency.md:246-249`).

The observable form of this is a spawn counter: on every failure path the number of processes
created is **zero** — for steps 1-5 because the plane never asks for a container at all, for
step 4b because the driver stops before `fork` — which is spike 02's tripwire adapter restated in process terms and what
ADR-0016's spike 05 gate 2 asserts across a sandbox replacement (`ADR-0016:119-121`).

An emitted `Output{checkpoint}` whose `payload_schema_digest` differs from the schema digest
the driver was given on spawn is **not forwarded**, and the run fails with `error_code =
checkpoint_schema_mismatch`. The driver compares a value it was handed and declines to relay;
it does not decide storage — that predicate is the plane's (§4). Relaying it would offer the
plane a checkpoint the next resume cannot read, which is the failure ADR-0011 exists to
prevent.

## 8. The driver's own capability declaration

The contract is a property of the **driver image**, not of a live process: `Describe` is queried
before any `Run` (`spec/contracts/adapter.proto:10-12`), a moment at which neither the driver
nor the harness of any run exists. The `adapter_contracts` row is therefore written **once per
driver image at deploy time**, from the `AdapterContract` compiled into that image; no run is
involved, and a `Describe` at any later moment is answered from the same compiled-in value.
Which `tenant_id` the row carries — one row per tenant at first use, or a single platform-tenant
row every tenant reads — is **unknown — OQ**; the key is `(tenant_id, identity, digest)`
(`01-schema.md` §Adapter contracts) and this document does not get to drop the tenant from it. Which component
performs the registration — the deploy pipeline, or the control plane on first sight of an image
— is likewise **unknown — OQ**. The row (`01-schema.md` §Adapter contracts):

| Column | Value |
|---|---|
| `tenant_id`, `identity`, `digest` | the composite primary key; `identity` is `sdk:pydantic-ai`, `digest` is derived from the contract, never supplied |
| `protocol_version` | §07's, which the driver and harness must both satisfy |
| `integration_mode` | `sdk_subprocess` |
| `payload_schema_digest` | the harness's checkpoint format, which `runs.pinned_payload_schema` pins |
| `declared_capabilities` | every capability in the registry, explicitly, including `UNKNOWN` (`08-conformance.md:41-43`) — the registry itself is **unknown — OQ** (below), so completeness is assertable only once it exists |

`effect_ledger_participation` is declared `TRUE` with confidence `ASSERTED`, not `VERIFIED`.
Spike 06 proved the tool boundary — 64 gate assertions, negative control at
`spikes/06-tool-interception/RESULT.md:3, 210` — but its simplification 2 records that replay
determinism of the effect key is **untested** (`spikes/06-tool-interception/RESULT.md:331`), and
`step_id` stability across replay is the property the capability names
(`07-adapter-protocol.md` §`step_id` and the effect key). The design intent is right — `step_id` is derived from the
harness's position in its own plan rather than from a counter or a UUID — but intent is not
evidence. `VERIFIED` is owed a spike that replays one logical step across two spawns and
compares the derived `idempotency_key`; until then the declaration may not gate a safety
decision (`07-adapter-protocol.md` §Capability declaration, `Confidence`).

Which registry key covers "survives a spawn of its own process" is **unknown — OQ**: §07 names
only `effect_ledger_participation`, and the capability registry itself is not yet written down.

## 9. Errors this document adds

| `error_code` | Raised when | Who observes it |
|---|---|---|
| `checkpoint_too_large` | the encoded `Start` carrying `resumed_payload` exceeds the frame ceiling; refused before spawn | driver, pre-spawn |
| `checkpoint_schema_mismatch` | an emitted checkpoint's schema digest ≠ the digest the driver was given on spawn; the driver declines to forward it | driver observes and reports, mid-run; the plane sets the outcome |
| `adapter_protocol_violation` | the driver refused a frame and closed: oversize length, unknown `kind`, repeated `call_id`, frame after `End` — frames the harness sent | driver |
| `adapter_protocol_violation` | the harness refused a driver-sent frame — a second `Start`, or a `Start` whose `run_token` differs from the spawn's — and exited non-zero without `End`; the driver reads the exit status and classifies per §6, `indeterminate` still winning over an unsettled effect | driver, on `SIGCHLD` |
| `knowledge_missing` | step 4b: a path in `manifest.json` is absent from the materialised tree | driver, pre-spawn (defined by [`16-knowledge.md`](16-knowledge.md)) |
| `knowledge_corrupted` | step 4b: a materialised file's digest differs, a file is present that the manifest does not name, or the manifest projection ≠ the pinned package digest | driver, pre-spawn (defined by [`16-knowledge.md`](16-knowledge.md)) |

`adapter_disconnected` and `output_flood` are §07's and are unchanged.

## Tests, with negative controls

| Invariant | Test | Negative control |
|---|---|---|
| The knowledge tree is verified before the spawn | corrupt one materialised file, and separately add one the manifest does not name; assert the spawn count is 0 and the code is `knowledge_corrupted` | skip step 4b ⇒ the run executes unpinned content |
| The bundle pin is compared before the spawn | resume a run whose registered bundle revision moved | compare only the adapter and payload pins ⇒ the run executes a different executable set |
| No process exists before the resume order completes | tripwire on `fork`/`exec`: assert the spawn count is 0 on artifact-missing, corrupted, pin-mismatch and concurrent-resume | reorder to lease-before-pin ⇒ a process is created on a mismatch |
| A `Start` with the wrong `run_token` is refused | send a `Start` carrying a token from a previous spawn | accept any token ⇒ a replayed `Start` drives the run |
| A second `Start` is refused **by the harness** | send two on one pair; assert the harness exits non-zero without `End` and the driver classifies that exit per §6 as `adapter_protocol_violation` | accept the second ⇒ two `Start`s on one stream, contradicting `07-adapter-protocol.md` §Contract, stated precisely |
| A repeated `call_id` within a run is refused | resume, then emit a `call_id` already answered in an earlier spawn | scope uniqueness to the spawn ⇒ one answer settles the wrong ledger row |
| Disconnect mid-run with an unsettled effect ⇒ `indeterminate` | `SIGKILL` the harness while one `effect_ledger` row is `claimed` | map it to `failed` ⇒ a false "we know it failed" |
| Disconnect mid-run with every effect settled ⇒ `failed`, `adapter_disconnected` | `SIGKILL` with nothing `claimed` | map it to `indeterminate` ⇒ manufactured uncertainty |
| A frame longer than the ceiling is refused on its header | declare 4 MiB + 1 in the length prefix and send no payload; assert the driver closes and fails the run without having read a byte of body (the sender's next write blocks, then `EPIPE`s) | wait for the declared length ⇒ the sender chooses when the driver stops |
| `Cancel` still yields `End` | cancel, assert `End` arrives within the grace window | kill at once ⇒ a rule-5 close the harness was about to classify itself |
| A checkpoint covers the step whose calls are outstanding | drive to a `ToolCall`, delete the pod, resume | omit the rule ⇒ the resume rebuilds from the previous step |
| The deadline does not extend across a resume | resume twice, compare `Deadline.unix_millis` | recompute it per spawn ⇒ an unbounded run |
| The output budget does not reset on resume | resume, assert the count continues from the log | count per spawn ⇒ the ceiling is per spawn |
| `run_token` never reaches the log | assert no `run_events.payload` contains it | log the frame verbatim ⇒ the token is durable and readable |
| A checkpoint whose schema digest ≠ the pin is not stored | emit one | store it ⇒ the next resume cannot read its own checkpoint |
| The effect key is stable across a replay of one logical step | replay one step across two spawns, compare the derived `idempotency_key` | derive the key from `tool_call_id` ⇒ two rows for one step |
| An oversize stored checkpoint is refused before the spawn | store a `resumed_payload` that puts the encoded `Start` one byte over the ceiling, resume | measure the payload rather than the frame ⇒ a `Start` the pair cannot carry passes the pre-spawn check |
| A refused frame with an unsettled effect is `indeterminate`, not `adapter_protocol_violation` | send a second `Start` while one `effect_ledger` row is `claimed`; the harness exits non-zero without `End`, and the driver's `SIGCHLD` path must still yield `indeterminate` | let the violation win ⇒ a false "we know it failed" over an unsettled effect |

Every row goes through the public boundary — the pair, the process table, and the run's rows —
never through the driver's internals, per `spikes/VERIFICATION-RULES.md` rules 3 and 4.

## What this does not guarantee

- **`run_token` is not a defence against a process holding a socketpair end.** It binds a
  stream to one spawn. A same-UID process can read the child's environment through `/proc`,
  but it has no end of the pair to use the token on — *unless it can attach to the harness
  itself*: a same-UID process permitted to `ptrace` the harness can use its fd directly, and
  neither a Yama scope nor a seccomp filter is specified here (the sandbox's three boundaries
  are ADR-0009 and Tier 2). The boundary the pair buys is against a process that must *find* a
  channel, not against one that may attach to a process that already holds one
  (`ADR-0016:65-70`).
- **The socketpair itself has not been exercised under gVisor.** Spike 05 T2 measured a
  *filesystem* Unix socket working within one container at `0600`
  (`spikes/05-sandbox-sidecar/T2-FINDING.md:67-76 @ 9f21e88`); the inherited-pair form, the
  descriptor number and the record framing are owed evidence, and gVisor's cross-container
  behaviour is parked as OQ-070
  rather than fixed. The PID-namespace teardown behaviour §6 relies on is likewise unmeasured
  under gVisor — owed to spike 05 alongside the socketpair gate.
- **A boundary inside the harness process is not claimed here.** Spike 06's invariant is
  scoped to a cooperating in-process caller (`spikes/06-tool-interception/RESULT.md:86-89`).
  What the process split buys is that the control plane, the ledger and the socket the answers
  arrive on are outside that process — not that arbitrary code inside it is contained. Egress
  containment is the sandbox's, and it is Tier 2.
- **The exit status classifies nothing external.** It is evidence for §05's two rules and no
  more.
- **Nothing here makes a second adapter exist.** The boundary is retained so a second SDK can
  be added without touching the control plane (`07-adapter-protocol.md` §Who executes a tool); this
  document specifies one driver.
