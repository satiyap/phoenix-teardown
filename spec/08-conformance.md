# 08 — Conformance and CI
<!-- status: final -->

What CI must enforce, and why the bench is split in two.

---

## Two layers — Omnigent's actual CI split

| Layer | Runs | Needs | Fails the build | In v0.1? |
|---|---|---|---|---|
| **Offline** | every commit | nothing | yes | **yes** |
| **Live** | nightly + on demand | credentials, a running adapter, money | yes, on the nightly | **no — deferred** |

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
   explicit, not absent.
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
| 2 | An effect executes at most once under N claimers | stub the claim ⇒ N executions |
| 3 | A fenced worker's writes are rejected | drop the `EXISTS` fence clause ⇒ write lands |
| 4 | An expired claim becomes `indeterminate`, never retried | make the sweeper retry ⇒ double execution |
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
| 22 | Close without `End` ⇒ `indeterminate` | map to `failed` ⇒ false certainty |
| 23 | Unset capability reads `UNKNOWN` | treat as `FALSE` ⇒ silent degradation |
| 24 | `ASSERTED` cannot gate a safety decision | allow it ⇒ unproven claim trusted |
| 25 | Stable `step_id` across replay | counter-based ⇒ duplicate execution |
| 26 | One trace id spans client → plane → adapter | drop propagation ⇒ two traces |
| 27 | `tenant_id` never read from a request | read from body ⇒ cross-tenant access |
| 28 | Agent tokens cannot reach admin routes | drop the class check ⇒ 201 |
| 29 | `decided_by` from the token, not the body | trust the body ⇒ impersonation |
| 30 | Cross-tenant read is `404` not `403` | return 403 ⇒ existence leak |

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
