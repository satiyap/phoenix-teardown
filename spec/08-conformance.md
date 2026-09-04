# 08 — Conformance and CI
<!-- status: final -->

What CI must enforce, and why the bench is split in two.

---

## Two layers — Omnigent's actual CI split

| Layer | Runs | Needs | Fails the build | In v0.1? |
|---|---|---|---|---|
| **Offline** | every commit | nothing | yes | **yes** |
| **Live** | nightly + on demand | credentials, a running adapter, money | yes, on the nightly | **no — deferred** |

> **Purpose note (2026-08-27).** We build and operate every adapter, so this bench is no
> longer about third-party honesty — nobody else declares capabilities to us. Its purpose is
> **SDK-version drift**: Pydantic AI changes behaviour under a version bump and a declaration
> silently becomes false (amended 2026-08-27: named two SDKs; there is one). That is a weaker, slower risk than
> an untrusted declaration, which is why the bench moves from Tier 2 to **Tier 3**
> (`v01-boundary.md`). ADR-0012 is unaffected: declarations still beat discovery, and
> `UNKNOWN` still never degrades to `false`.

> **Scope correction.** `v01-boundary.md` defers the live layer, and an earlier version of
> this document mandated it. The live layer is **specified here but not shipped in v0.1**;
> its trigger is "the third adapter, or the first capability-related production incident".
> Everything below marked *live* is therefore a design commitment, not a v0.1 CI
> requirement.

Live probes cost credentials and spend, so they cannot gate every commit. But
**declaration completeness costs nothing**, and putting it offline is what stops the
capability table rotting: a new adapter with no declarations fails CI immediately, even
though nobody has yet proved what it can do.

That split is verified behaviour, not a guess — it is how
`tests/harness_bench/test_bench.py` works in Omnigent.

### Offline layer

Every commit:

1. **Declaration completeness.** Every registered adapter declares every capability in
   the registry. A missing declaration is `UNKNOWN`, which is *allowed* — but it must be
   explicit, not absent. **Amended 2026-08-30 (OQ-107):** the registry this check
   enumerates holds two keys, both defined in
   [`07-adapter-protocol.md`](07-adapter-protocol.md) §Idempotent step ids —
   `effect_ledger_participation ∈ {verified, asserted, unsupported}` and
   `resumable_after_process_loss ∈ {verified, asserted, unsupported}` — named here because
   this document defines no enumerated registry of its own.
2. **Every declared capability has a probe defined.** A capability nobody can test is a
   claim, not a capability.
3. **Declaration coverage is reported**, per adapter, as a number. Omnigent's tri-state
   is designed and plumbed but *unpopulated* — all 26 harnesses declare `None` on all
   four optional axes. A tri-state nobody fills buys nothing, so coverage is a metric we
   track rather than a box we tick.
4. **Reconciliation semantics.** The DRIFT comparison logic itself is unit-tested,
   without needing a live adapter.
5. **Canonicalisation vectors** (§03) reproduce, including the cross-process test.
6. **Schema invariants** — the constraint tests from §01/§02 against a real Postgres.

### Live layer

Nightly:

1. Probe each adapter for each declared capability.
2. **Reconcile declared against observed. DRIFT fails the build.**
3. Promote `ASSERTED → VERIFIED` where a probe passes.
4. **Demote `VERIFIED → ASSERTED` where a probe cannot run** — a capability that was
   verified once and is now unprobeable is not still verified.

Rule 4 is the one that keeps the table honest over time.

---

## DRIFT is a build failure, not a report

The point of the bench is that the capability table is **self-enforcing**: "you can't lie
in the declarations without the bench catching it on the next live run."

A drift report that nobody must act on decays into a dashboard. So: DRIFT fails.

The one exception, stated so it is not discovered as a surprise: a capability declared
`UNKNOWN` cannot drift, because no claim was made. That is the correct behaviour and it
is also the loophole — hence coverage reporting in the offline layer.

---

## Required test inventory

Every invariant in this spec, with its negative control. Consolidated from §01–§07.

| # | Invariant | Negative control |
|---|---|---|
| 1 | Concurrent appends produce a dense `seq` with no duplicates | remove the PK ⇒ duplicates |
| 1a | An ordinary event carries exactly `runs.current_epoch` | let the caller pass an epoch ⇒ events invent epochs and `live()` breaks |
| 1b | Only `run.rewound` moves the epoch, and only to `+1` | allow any epoch ⇒ non-dense history, `to_epoch` names a future epoch |
| 1c | A run CONTINUES after a rewind | use the naive `seq >=` rule ⇒ post-rewind events vanish |
| 1d | `seq` is monotonic across epochs, so `seq` order == `(epoch, seq)` order | reset `seq` per epoch ⇒ folding reorders history |
| 2 | An effect executes at most once under N claimers | stub the claim ⇒ N executions |
| 3 | A fenced worker's writes are rejected | drop the `EXISTS` fence clause ⇒ write lands |
| 3a | Every fenced write includes `expires_at > now()` | omit it ⇒ an expired holder's write lands |
| 3b | NFC-colliding keys are REJECTED, not merged | normalise-then-assign ⇒ one field silently overwrites another |
| 3c | Keys sort by UTF-8 byte order, asserted with non-BMP characters | rely on the language default ⇒ UTF-16 vs code-point divergence |
| 3d | Reordering extensions changes the definition digest | sort them ⇒ a behavioural change preserves the pin |
| 3e | Every reject vector actually raises, in every implementation | list without executing ⇒ the fixture is decoration |
| 3f | The vectors reproduce in a SECOND language | compare against the generator ⇒ proves only determinism |
| 4 | An expired **claim** becomes `indeterminate`, never retried | make the sweeper retry ⇒ double execution |
| 4a | An effect `awaiting_approval` NEVER becomes `indeterminate`, however slow the human | claim before approval ⇒ a slow approver produces `indeterminate` for an effect that never ran |
| 4b | A denied effect is never dispatched | check approval outside the claim ⇒ read-then-act dispatches it |
| 4c | Settlement requires owner + token + `status='claimed'` | settle by key alone ⇒ a fenced worker overwrites an `indeterminate` verdict |
| 4d | An approval cannot gate an effect in another run | drop `run_id` from the FK ⇒ cross-run gating accepted |
| 5 | `temp:` state cannot be persisted | drop the `CHECK` ⇒ it persists |
| 6 | Cross-tenant FK is impossible | drop the composite FK ⇒ succeeds |
| 7 | Terminal approval requires `decided_by` | drop the `CHECK` ⇒ anonymous approval |
| 8 | One hub per channel | remove the channel lease ⇒ both hubs post |
| 9 | Fold is deterministic and ordered by `seq` | order by `created_at` ⇒ wrong state |
| 10 | Unknown event type fails loudly | skip unknowns ⇒ silently wrong state |
| 11 | Resume order: artifact → integrity → pin → lease → adapter | reorder ⇒ adapter runs on a mismatch |
| 12 | No adapter call before validation | tripwire adapter; `calls == []` on every failure path |
| 13 | Executed artifact == checked artifact | pass the caller's object ⇒ check/use gap |
| 14 | Tool `artifact_digest` required | allow empty ⇒ mutable code under a stable pin |
| 15 | Only a worker enters `running` | drop the actor check ⇒ owner can start |
| 16 | Only the system sets `indeterminate`/`expired` | expose a route ⇒ client skips a safety gate |
| 17 | `succeeded` requires no claimed effects | drop it ⇒ success with unknown outcome |
| 18 | Canonicalisation vectors reproduce cross-process | add a `default=` fallback ⇒ memory address in a digest |
| 19 | NFC and NFD digests agree | remove normalisation ⇒ differ |
| 20 | Domain separation holds | drop `kind` ⇒ collision |
| 21 | Exactly one `End` frame | accept two ⇒ two terminal states |
| 29a | An **agent** token on `POST /v1/approvals/{id}/decide` is refused `403 wrong_credential_class` | drop the credential-class check ⇒ the response is no longer `403`. **NOT YET EXECUTABLE — no server exists**; this is an HTTP-boundary test owed by the first API implementation, listed rather than pretended |
| 29b | A non-`human` `decided_by` is rejected **by the schema** | drop the kind from the FK ⇒ an agent principal is stored as the approver. **Executed** — spike 03 scenario 9, with that exact negative control |
| 30a | An in-process SDK adapter's tool call produces an `effect_ledger` row | let the SDK's native executor run the tool ⇒ **no ledger row**, so the effect is unclaimed, unpoliced and unattested. **VERIFIED — spike 06 gate 3**, whose negative control runs the same function through `FunctionToolset` and observes the body execute with zero rows |
| 30b | Corrected 2026-08-27 — the earlier claim that "the SDK's native tool executor is disabled at adapter construction" is superseded: **the SDK is never given an executable body**: tools are declared through `ExternalToolset`, whose `call_tool` raises unconditionally (`toolsets/external.py:46` *(citation corrected 2026-08-28: the unconditional raise is at `:46`; `:44` is the `call_tool` parameter line)*) | Reworded 2026-08-27 after spike 06, because the claim that the "native tool executor is disabled" at construction was superseded: there is no executor to disable, and that phrasing described a mechanism we do not use. Give the SDK a real function ⇒ two execution paths, one ungoverned — **VERIFIED, spike 06 gate 2 + its `FunctionToolset` control** |
| 30c | An adapter that cannot route a tool through the ledger **cannot register that tool** | allow registration ⇒ an effect path the ledger never sees. *Vendor-hosted tools remain unsupported in v0.1 (retracted 2026-08-27); spike 06 did not admit them — `ExternalToolset` cannot express them, because there is no local body to withhold.* **VERIFIED — spike 06 gate 6**, against `pydantic_ai.native_tools` rather than a Phoenix-declared flag: every vendor-hosted tool the SDK ships is refused by name, the refusal list is asserted complete against the installed SDK, and `_tool_execution.py` is shown to contain no `NativeToolCallPart` — they never enter the module that runs tool bodies *(corrected 2026-08-28, superseding that last clause: `_tool_execution.py` ORCHESTRATES tool execution; the body is invoked one level down at `tool_manager.py:1008` (`_raw_execute`), which `_tool_execution.py:15` imports. Round 4 pinned and grepped only the outer module, and a scratch-copy edit making `ExternalToolset`'s refusal fail open at that line left `pin holds: 19 files` and 53 gates green. Both modules are now pinned and both are grepped.)*. *(Corrected 2026-08-27: the first gate asserted only on `sdk_executable=True`, a boolean we invented.)* |
| 30d | **Resume with platform-supplied results must not re-execute the tool body.** Added 2026-08-27: `_tool_execution.py:399` makes `external` and `unapproved` kinds executable on the resume path, so this is a real path and not a hypothetical | re-execute ⇒ **the effect happens twice** while the ledger shows one row. **VERIFIED — spike 06 gate 4**, with a control that supplies a result without dispatching and observes no execution |
| 30e | A dispatched effect whose body **raised** settles `indeterminate`, never `intended` | leave it `intended` ⇒ indistinguishable from an effect that never started, so a crashed charge looks like no charge. **VERIFIED — spike 06 gates 11 + 12.** *Corrected 2026-08-27: this row was first labelled VERIFIED against a harness that moved `intended` straight to `indeterminate`, skipping the claim phase `spec/02-consistency.md:326` requires — so the lifecycle the row names was absent and the label was false. Gate 12 now asserts `intended → claimed → settled`, that `indeterminate` is refused on an unclaimed row, and that a stale claim token is fenced out.* |
| 22 | Close without `End` **and an unsettled effect** ⇒ `indeterminate` | map to `failed` ⇒ false certainty. **Corrected 2026-09-04: the platform did exactly what this control forbids.** `indeterminate` was a declared, terminal run state that NO event could produce — there was no `run.indeterminate` event and no fold case — and the worker wrote `failed` carrying `error_code = indeterminate` instead. The test covering this row asserted on the effect ledger and stated the invariant only in a comment, so it stayed green over the damage. Now: a `run.indeterminate` event, a fold case, and a test that asserts the run's STATE |
| 22a | Close without `End` and **no** unsettled effect ⇒ `failed`, `adapter_disconnected` | map to `indeterminate` ⇒ manufactured uncertainty, human time spent on a known outcome |
| 23 | Unset capability reads `UNKNOWN` | treat as `FALSE` ⇒ silent degradation |
| 24 | `ASSERTED` cannot gate a safety decision | allow it ⇒ unproven claim trusted |
| 25 | Stable `step_id` across replay | counter-based ⇒ duplicate execution |
| 26 | One trace id spans client → plane → **driver → harness** (four hops; §19) | drop the hop-3 environment carrier ⇒ two traces. The receiving span must have a REMOTE parent — asserting the variable was written is Omnigent's `get_traceparent_env()` defect |
| 27 | `tenant_id` never read from a request | read from body ⇒ cross-tenant access |
| 28 | Agent tokens cannot reach admin routes | drop the class check ⇒ 201 |
| 29 | `decided_by` from the token, not the body | trust the body ⇒ impersonation |
| 30 | Cross-tenant read is `404` not `403` | return 403 ⇒ existence leak |
| 31 | A declared verifier is published by a different principal than the bundle it verifies (§10) | drop `verifier_is_independently_published` ⇒ spike 04 finding 1's co-published verifier is accepted |
| 32 | A node carrying both a content and an executable role is rejected (§10, §16) | drop `node_roles_are_content_or_executable` ⇒ one artifact is both what the model reads and what the platform executes |
| 33 | An `Action` never duplicates ledger state (§10) | add `actions.status` ⇒ two authorities disagree after a fenced settle |
| 34 | A doubled cron tick creates **one** Run (§11) | read-then-act instead of the firing key ⇒ spike 01's `['w1','w2']` at the routine layer |
| 35 | A Run and its firing record are one transaction (§11) | commit them separately ⇒ a decided tick with no Run, or a Run no tick names |
| 36 | `system/**` is never silently dropped from a model request (§12, §16) | drop the overflow instead of failing ⇒ the run proceeds on partial system knowledge with no signal |
| 37 | A nominated node outside the closure and the manifest is refused (§12) | admit it ⇒ discovery where ADR-0012 requires declaration |
| 38 | Zero processes exist on every pre-spawn failure path (§13) | reorder to lease-before-pin ⇒ a process is created on a mismatch |
| 39 | A `Start` carrying the wrong `run_token` is refused (§13) | accept any token ⇒ a replayed `Start` drives the run |
| 40 | No secret reaches the sandbox (§14) | mount the credential for convenience ⇒ the blast radius of a compromised run container becomes the credential |
| 41 | A placeholder is host-bound and single-use (§14) | present it to a second host, and twice to its own ⇒ a leaked placeholder is a bearer token |
| 42 | `delegation_depth` is set by us and capped independently of policy (§14) | take the depth from the caller ⇒ the cap is advice |
| 43 | No control-plane database path from the run container (§15) | inject the database credential into the container ⇒ it connects |
| 44 | A run holding a non-terminal sandbox cannot acquire a second (§15) | scope `sandboxes_one_live` to `state IN ('creating','live')` ⇒ a suspended row lets a second sandbox in with no violation |
| 45 | A sandbox event never changes run state (§15) | fold `sandbox.lost` onto `runs.state` ⇒ run identity depends on sandbox identity, which ADR-0016 forbids |
| 46 | A higher knowledge layer's bytes win and the lower file is absent from the package (§16) | ship both ⇒ two files claim one path and the model reads whichever the walker reached first |
| 47 | A forbidden state read is refused, not empty (§16) | return an empty `ToolResult` ⇒ "no rows" and "not allowed" are indistinguishable (non-negotiable 10) |
| 48 | A fenced hub cannot post (§17) | drop the fence predicate ⇒ two hubs write one channel |
| 49 | The effect claim survives channel-WAL deletion (§17) | derive the effect key from a message field ⇒ retention deletes the basis of idempotency |
| 50 | An unpriced call fails the **total** closed and is never zero (§18) | price it as 0 ⇒ an under-count that reads as a total |
| 51 | Every cost record in a pricing interval names that interval's pinned digest (§18) | price against the current dataset ⇒ one interval carries two price bases |
| 52 | No identifier enters a span name or a metric attribute (§19) | put `run_id` in a metric label ⇒ unbounded cardinality, ADR-0010's stated failure |

**Every row needs both columns implemented.** A test without its negative control is
unproven: it may be passing for an unrelated reason, which is exactly what happened in
spike 01, where a test passed because two hubs hydrated before a close rather than
because the mechanism worked.

---

## The propagation test is not optional

Test 26 exists because Omnigent depends on **six** OpenTelemetry packages and its own
design audit found trace context "never propagated over the wire",
`HTTPXClientInstrumentor` "never wired", and `get_traceparent_env()` as "dead code — zero
call sites".

**A dependency list is not telemetry.** The exit criterion is a passing propagation
assertion, not a line in a lockfile.

---

## In-memory implementation of every pluggable interface

Not a test, a build requirement — and the strongest DX finding in the study, confirmed
four times (ADK's `InMemory*` for six subsystems, LangGraph's `InMemorySaver`, AX's
`eventlogtest`, Pydantic AI's `TestModel`).

Every interface ships a working local implementation, so **the development path and the
production path are the same code with a different injection** — not a mock, not a
separate mode.

The counter-example is AWS AgentCore: an Apache-2.0 SDK where nothing runs without the
managed service. Same company scale as ADK, opposite choice, and it is the reason the
AgentCore teardown has 52 `unknown` probes.

CI must therefore run the **entire** suite against in-memory implementations *and* the
schema/consistency subset against real Postgres.

---

## The reproduce rule

From [`../spikes/VERIFICATION-RULES.md`](../spikes/VERIFICATION-RULES.md) rule 6, and it
applies to CI documentation as much as to spikes:

> Do not write PASS until the exact reproduction command includes every gate test.

No `--deselect` in the documented command. If a test must be excluded, it is not a gate
test, and the exclusion is stated in the result rather than hidden in the invocation.
