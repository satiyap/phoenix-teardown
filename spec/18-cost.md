# 18 — Cost measurement
<!-- status: draft -->

Boundary Tier 3 (`../synthesis/v01-boundary.md` item 14): **INTEGRATE `genai-prices`, with
Omnigent's fail-closed-on-unpriced rule.** This document settles how token usage reaches the
platform, how it is priced, how a price that cannot be determined is recorded, and to whom the
money is attributed.

It deliberately does **not** settle enforcement. There is no budget, no cap, no gate and no
downgrade in v0.1 — the boundary says *measurement*, and OQ-016 records that no project in the
study has an *infrastructure-level* quota (`open-questions.md:38`). Omnigent has a
policy-level one, and it is the design to copy when a cap is specified; what is missing is the
control-plane primitive underneath it, which the boundary does not fund in v0.1. §What v0.1
does not do states the line precisely.

It also does not settle the northbound read endpoints (owed by [§06](06-api.md)) or repricing.

---

## Where usage comes from

We do not proxy model traffic — `v01-boundary.md` "Never" item 3 is *no model gateway or
provider abstraction* — so the control plane never sees a model request. The harness does, and
only the harness: Pydantic AI calculates cost from `genai-prices`
(`projects/pydantic-ai/teardown.md:328` @ `b48ee38`) over usage aggregated on `RunUsage`
(`:382`, S9). Per-model-request granularity is OUR requirement on the harness mapping, not
something the teardown evidences — **OQ-131**.

[§07](07-adapter-protocol.md) carries no usage, and none of its bodies can be repurposed:
`text` and `thought` are opaque by rule, and the control plane never parses `Start.config`.
Cost therefore needs **one new typed frame**, and it qualifies under §07's own narrow test —
*typed exactly where a platform decision depends on it* — because a platform decision does
depend on it: the control plane prices the call against a pinned snapshot, and neither the
provider, the model identifier nor the token classes are derivable from opaque bytes.
Attribution needs no field on the frame — it is computed from the run (§The cost record, and
attribution). §07's own table gains one row:

| do this | without |
|---|---|
| price a model call | the provider, model and token counts |

```protobuf
// Emitted once per model request as the harness observes it; `requests` counts
// the provider round-trips behind that observation when the SDK retries
// internally (normally 1). The harness reports USAGE and never money: pricing
// is a control-plane act against a pinned snapshot (spec/18).
message Usage {
  string provider           = 1;   // e.g. "anthropic"
  string model_ref          = 2;   // the provider's own model identifier
  uint64 input_tokens       = 3;
  uint64 output_tokens      = 4;
  uint64 cache_read_tokens  = 5;
  uint64 cache_write_tokens = 6;
  uint32 requests           = 7;   // provider round-trips behind this observation; normally 1
}
```

The frame is defined in `contracts/adapter.proto` (added to `Output.body` as field 6) and
mirrored in [§07](07-adapter-protocol.md); this block is a verbatim quotation of the proto,
not a second definition.

`Output.step_id` accompanies it and correlates the record with the effect key's
`logical_step_path` ([§07](07-adapter-protocol.md) §`step_id` and the effect key), where the adapter declares
`effect_ledger_participation ≠ unsupported`. It does **not** deduplicate: dedupe is the primary
key on the log position (§The cost record, and attribution), and a step re-executed in a later
epoch is a second real spend (§Rewind does not un-spend).

The harness reports usage. It never reports money: pricing is a control-plane act (§Pricing).

---

## Event types — additions to the [§04](04-events.md) registry

Four types, in §04's `<domain>.<subject>.<past-tense-verb>` form. They are a closed set added
in code, and by §04 rule 3 a reader older than a writer is an error, so these deploy readers
first.

| `event_type` | payload |
|---|---|
| `cost.snapshot.pinned` | `{price_snapshot_digest, source, source_version, fence_token}` |
| `cost.usage.recorded` | `{fence_token, step_id, provider, model_ref, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, requests}` |
| `cost.usage.priced` | `{usage_seq, price_snapshot_digest, amount_nanos, currency}` |
| `cost.usage.unpriced` | `{usage_seq, price_snapshot_digest?, unpriced_reason}` |

**Usage and price are separate events on purpose.** Usage is a fact the harness observed;
a price is a judgement the control plane made against a dataset that changes underneath it.
Splitting them follows §04's existing precedent — `run.cancel_requested` is not
`run.cancelled`, because a request is not a fact — and it buys three things: the usage survives
when pricing fails, an unpriced call is a *recorded* call rather than a gap, and a future
repricing appends rather than rewrites an append-only log.

**Exactly one of `cost.usage.priced` / `cost.usage.unpriced` follows each `cost.usage.recorded`,
in the same transaction** (the same-transaction obligation [§02](02-consistency.md) §`runs.state` is a projection, obligation 1
places on any projection), and it names the usage event by `usage_seq`. Neither may appear
without its usage event; neither may appear twice.

Two mechanisms, and they cover different halves. A **second** verdict for one usage event is
refused by `cost_records`' primary key `(tenant_id, run_id, usage_seq)`, which the same
transaction writes — so duplication is a constraint violation, not a review item. A **missing**
verdict has no constraint to violate; it is caught by the projection-equals-fold assertion
[§02](02-consistency.md) §`runs.state` is a projection, obligation 3 requires, which counts one verdict per `cost.usage.recorded`
in the fixture corpus. Reading a projection key this way does not breach
[§02](02-consistency.md) §`runs.state` is a projection, obligation 4: the key is being used to refuse a write, not consulted as
truth in a decision.

`price_snapshot_digest` is present on `cost.usage.unpriced` exactly when a snapshot was pinned,
and **absent, never `null`**, when `unpriced_reason = snapshot_unresolved` — §04's rule for
`task_id` and `firing_key` (`04-events.md` §Run lifecycle).

All money in a payload is an **integer**. [§03](03-canonicalisation.md) step 1 rejects
non-integral floats outright, and floating-point summation is not associative, so a total would
depend on iteration order. `amount_nanos` is nano-units of the currency's major unit
(1 USD = 1 000 000 000).

---

## Pricing — `genai-prices` consumed as data

The dataset is **snapshotted, digested and stored**; the pricing path reads the stored bytes,
never a live fetch and never a Python import. That is what makes it language-neutral: the Go
control plane prices, and the Python harness — which is where the SDK dependency lives — is not
in the pricing path at all. Pydantic AI's own integration is the evidence that the dataset is
usable this way and that a pricing failure is a first-class outcome rather than a zero
(`pydantic_ai/_cost.py:1-27` @ `b48ee38`: `preload_pricing_data`,
`CostCalculationFailedWarning`).

What that citation does **not** evidence is the shape this document depends on. `_cost.py`
imports the Python package; whether `genai-prices` publishes the dataset separably — versioned
bytes, a stable schema, a declared currency — is **not verified in the study**, and the Go
control plane cannot price against stored bytes unless it does. Recorded as **OQ-130**; it
blocks the pricing path and blocks nothing in usage capture, which is why §Where usage comes
from and the `Usage` frame stand on their own.

```sql
-- The pricing basis, content-addressed exactly like agent_definitions.
CREATE TABLE price_snapshots (
    tenant_id      BIGINT NOT NULL,
    digest         TEXT   NOT NULL,       -- sha256 hex over the fetched bytes
    source         TEXT   NOT NULL,       -- 'genai-prices'
    source_version TEXT   NOT NULL,       -- the dataset release the bytes came from
    currency       TEXT   NOT NULL,       -- ISO 4217; read from the snapshot if the
                                          -- dataset declares one, else the fetch records
                                          -- it (OQ-130)
    body           BYTEA  NOT NULL,       -- the dataset AS FETCHED, not as parsed
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, digest),
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
    CHECK (digest ~ '^[0-9a-f]{64}$'),
    CHECK (currency ~ '^[A-Z]{3}$')
);
```

The key is tenant-scoped because non-negotiable 1 admits no exception; the bytes are identical
across tenants, so the cost is duplication and the consequence is that two tenants may price the
same model against different snapshots on the same day. Whether a platform-scoped snapshot with
a tenant-scoped pin is the better shape is **OQ-136**.

Storing the bytes rather than a parsed table is the same discipline spike 02 established for
definitions: the artifact that is used is the artifact whose digest was checked
(`spikes/02-definition-pin/RESULT.md`; non-negotiable 6). A parsed table cannot be re-verified.
The digest is recomputed over `body` on load and compared to `digest` before any record prices
against it. A mismatch is not a pricing failure but a **snapshot** failure: the interval prices
nothing and every record in it is `snapshot_unresolved`.

**One snapshot is pinned per leased execution interval, and every record in that interval
prices against it.** `cost.snapshot.pinned` records the choice, appended in the same transaction as the lease
acquire: it is statement 3 of [§02](02-consistency.md) §Acquire, on the branch where the
`run_leases` insert returned a row, and skipped when it returned nothing. The statement
lives there rather than here, because a transaction specified in two places is a transaction
implemented once. It carries a `traceparent` like any append
(`01-schema.md` §The log) and is taken before the interval's first `Usage` frame. A fetch that
cannot be resolved pins nothing, appends nothing, and the interval's records are
`snapshot_unresolved`. Prices are computed once, at the time of the call, and **never
recomputed** — a later snapshot does not rewrite history, because `run_events` is append-only
and the money we already owe a provider does not change when a dataset does. Pinning per
interval rather than per run means a long-lived run picks up a corrected price on its next
resume without any row being rewritten.

Arithmetic is exact decimal; binary floating point is forbidden in the pricing path for the
reason above. The rounding mode at the nano is **half-up**; no project in the study evidences a
choice here, so this is a decision and not a finding, recorded as **OQ-135** (which mode, and
does an independent oracle exist for it).

---

## Fail closed on an unpriced model

Omnigent is the only project in the study with a real answer to runaway spend, and its cost
policy **fails closed when usage is present but unpriced, so an unpriced model cannot bypass
the cap** (`omnigent/policies/builtins/cost.py:1-52` @ `ba9e371`;
`projects/omnigent/teardown.md:521`). Omnigent also supplies the sharper rule about *where*
to fail closed: fail closed where the decision is the last line of defence, fail open where the
harm already happened (`omnigent/policies/types.py:59-80` @ `ba9e371`,
`FAIL_CLOSED_PHASES`; `projects/omnigent/teardown.md:344`).

Applied honestly to a system that measures and does not enforce, those two give a rule with two
halves, because the positions differ:

1. **At the record.** A usage frame arrives after the tokens are already spent, so refusing it
   would destroy evidence and prevent nothing — that is Omnigent's fail-open position. The call
   is recorded as `cost.usage.unpriced` with a reason. **An unknown price is never written as
   zero**, and the schema makes zero and unknown different values rather than a convention.

2. **At the total.** Reporting is the last line of defence, so it fails closed: any aggregate
   spanning a record with no price is a **lower bound, not a total**, and is published with its
   `unpriced_calls` count. A caller that receives a bare number when `unpriced_calls > 0` has
   been told something false. This is the trap SQL sets by default — `sum()` skips NULLs
   silently and returns a number that looks complete.

`unpriced_reason` is one of `model_not_in_snapshot`, `snapshot_unresolved`, `usage_incomplete`.
Three, because the operator remedies differ: refresh the dataset, fix the fetch, or fix the
harness mapping — the same reason §04 splits `run.incompatible` / `run.artifact_missing` /
`run.artifact_corrupted` ([§04](04-events.md) §Pin and compatibility). `snapshot_unresolved` is the only reason
that carries no digest — there is none to carry.

Whether `genai-prices` is maintained on a cadence that makes it safe for *enforcement* rather
than reporting is **OQ-028, still open**. v0.1 does not depend on the answer, because v0.1 does
not enforce. A cap would.

---

## The cost record, and attribution

`cost_records` is a **projection of the log**, carrying the obligations
[§02](02-consistency.md) §`runs.state` is a projection states for `runs.state`: written in the same transaction as its
event, rebuildable by a documented fold and asserted equal to it in CI, and never read as truth
in a correctness decision. §02's compare-and-swap obligation has no analogue here because the
projection is insert-only — the primary key on the log position plays its role. The log is the
authority.

```sql
CREATE TABLE cost_records (
    tenant_id      BIGINT NOT NULL,
    run_id         TEXT   NOT NULL,
    usage_seq      BIGINT NOT NULL,      -- run_events.seq of the cost.usage.recorded event
    fence_token    BIGINT NOT NULL,      -- the pricing interval; see below
    step_id        TEXT   NOT NULL,

    -- ATTRIBUTION, snapshotted at the call, not joined at read time
    principal_id   TEXT   NOT NULL,
    agent_id       TEXT   NOT NULL,

    provider       TEXT   NOT NULL,
    model_ref      TEXT   NOT NULL,
    input_tokens   BIGINT NOT NULL,
    output_tokens  BIGINT NOT NULL,
    cache_read_tokens  BIGINT NOT NULL DEFAULT 0,
    cache_write_tokens BIGINT NOT NULL DEFAULT 0,
    requests       INTEGER NOT NULL DEFAULT 1,

    price_snapshot_digest TEXT,          -- NULL only when the snapshot never resolved
    amount_nanos   BIGINT,               -- NULL means UNKNOWN, never free
    currency       TEXT,
    unpriced_reason TEXT,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, run_id, usage_seq),
    FOREIGN KEY (tenant_id, run_id, usage_seq)
        REFERENCES run_events (tenant_id, run_id, seq),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, run_id),
    FOREIGN KEY (tenant_id, principal_id)
        REFERENCES principals (tenant_id, principal_id),
    FOREIGN KEY (tenant_id, agent_id) REFERENCES agents (tenant_id, agent_id),
    FOREIGN KEY (tenant_id, price_snapshot_digest)
        REFERENCES price_snapshots (tenant_id, digest),

    -- priced XOR unpriced. Zero is a price; unknown is not.
    CONSTRAINT cost_priced_xor_unpriced CHECK (
        (amount_nanos IS NOT NULL AND currency IS NOT NULL
             AND unpriced_reason IS NULL AND amount_nanos >= 0)
     OR (amount_nanos IS NULL AND currency IS NULL
             AND unpriced_reason IS NOT NULL)
    ),

    -- the reason set is closed in the database, not by convention
    CONSTRAINT cost_unpriced_reason_known CHECK (
        unpriced_reason IS NULL
     OR unpriced_reason IN ('model_not_in_snapshot','snapshot_unresolved','usage_incomplete')
    ),

    -- one reason, and only one, can carry no digest
    CONSTRAINT cost_snapshot_known CHECK (
        price_snapshot_digest IS NOT NULL
     OR unpriced_reason = 'snapshot_unresolved'
    ),

    CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    CHECK (input_tokens >= 0 AND output_tokens >= 0
           AND cache_read_tokens >= 0 AND cache_write_tokens >= 0
           AND requests >= 1)
);

CREATE INDEX cost_records_by_run ON cost_records (tenant_id, run_id, fence_token);
CREATE INDEX cost_records_by_principal
    ON cost_records (tenant_id, principal_id, recorded_at);
CREATE INDEX cost_records_unpriced ON cost_records (tenant_id, recorded_at)
    WHERE amount_nanos IS NULL;
```

The primary key is the log position, so **replaying the same event cannot produce a second
record**. Double counting is a constraint violation, not a review item. The row carries no
`epoch` column: the epoch is reachable through the foreign key
(`JOIN run_events USING (tenant_id, run_id)` on `seq = usage_seq`), and a copy no query reads
and no constraint checks could disagree with the event it names.

**Four attribution levels, all present on the row.** `tenant_id` scopes it (non-negotiable 1).
`run_id` is the unit of work. `principal_id` is the run's acting principal (`runs.created_by`,
`01-schema.md` §Run), copied at the call rather than joined at read time, because `principals`
rows are mutable and revocable (`01-schema.md` §Identity, `revoked_at`, revocation is a state and not a delete) and
a bill must not change when an identity does. `agent_id` is copied for a weaker reason and it
is worth naming: the id itself is stable (`01-schema.md` §Agent definition), so this is denormalisation
for per-agent spend, not a snapshot — the mutable part, `current_digest`, is deliberately not
copied, because the run already pins a definition digest. Delegation needs no second
attribution: a delegated agent is its own Run with its own principal ([`12-harness.md`](12-harness.md) §6,
itself marked **NOT VERIFIED** there), and rolling its spend up to `on_behalf_of` is a query
over `principals`.

**The pricing interval is one leased execution interval**, identified by the run lease's
`fence_token` ([§01](01-schema.md) `run_leases`, [§02](02-consistency.md) fencing). It is not a
*turn*: `turn_ordinal` increments once per model request ([`12-harness.md`](12-harness.md) §5), and one
leased interval carries many. The interval is platform-observed and needs no adapter
cooperation: a resume takes a new fence and starts a new interval, and a reclaim does too,
which is the honest reading — a reclaimed run *is* doing the work again.

```sql
CREATE VIEW run_cost_totals AS
SELECT tenant_id, run_id,
       sum(amount_nanos) FILTER (WHERE amount_nanos IS NOT NULL)
                                                     AS priced_nanos_lower_bound,
       count(*) FILTER (WHERE amount_nanos IS NULL)   AS unpriced_calls,
       count(*)                                       AS calls,
       sum(input_tokens)        AS input_tokens,
       sum(output_tokens)       AS output_tokens,
       sum(cache_read_tokens)   AS cache_read_tokens,
       sum(cache_write_tokens)  AS cache_write_tokens
  FROM cost_records
 GROUP BY tenant_id, run_id;
```

There is no column named `total`. The lower bound and `unpriced_calls` are published as a pair,
and that pairing is an obligation on the read contract [§06](06-api.md) owes — this document
defines the projection, not the endpoint, so v0.1 enforces it in review rather than in the type.

---

## Rewind does not un-spend

[§04](04-events.md)'s `live()` filter supersedes events in a rewound range so that *state* folds
correctly. **Cost aggregates run over every epoch, including superseded ones.** Tokens burned in
an epoch we later abandoned were really burned and are really on the provider's invoice;
applying `live()` to money would produce a figure that cannot be reconciled against a bill.

This is a deliberate divergence from the state fold, and it is the one place in this document
where the log's default reading is the wrong one.

---

## Telemetry

ADR-0010 makes OTel canonical, and Cloudflare sets the convention bar: keys that have a GenAI
semconv home use it, keys that do not live under a declared vendor namespace, **never bare
top-level keys and never `ai.*`** (`packages/agents/src/observability/genai/attributes.ts:1-9`
@ `2f957bc`; ADR-0010:52). Token counts have a GenAI semconv home. Priced amounts do
not, so by [§19](19-telemetry.md) §Namespace they live under the declared vendor namespace, and
under its unstable tier until the shape has been used in anger:
`phoenix.experimental.cost.amount_nanos`, `phoenix.experimental.cost.currency`,
`phoenix.experimental.cost.unpriced_reason`, `phoenix.experimental.cost.price_snapshot_digest`.
`phoenix.experimental.*` carries no compatibility guarantee ([§19](19-telemetry.md) §Namespace), which
is the correct tier for a namespace whose pricing path is still OQ-130. [§19](19-telemetry.md)
§Attributes carries all four rows as of 2026-08-30, so the priced-amount key has an owner.

Spans are **not** the record. Traces are sampled; an invoice is not. The log is the durability,
and `run_events` is where cost lives.

---

## What v0.1 does not do

| Not done | Why |
|---|---|
| Budgets, caps, ask-thresholds, model downgrade | Tier 3 is measurement (`v01-boundary.md` 14). Omnigent's `cost_budget` is the design to copy when a cap is specified, including its documented overshoot limit |
| Block a run because a model is unpriced | Nothing to block: the tokens are spent before the frame arrives. The closed half is the total, not the call |
| Reprice historical records | Append-only. A corrected snapshot changes the next interval, never a written row |
| Price non-model spend (sandbox time, tool vendors, egress) | No evidence base in the study; a separate unit of account |
| Enforce a per-principal daily aggregate | Needs the cap that v0.1 does not have (OQ-016) |

---

## Tests, with negative controls

Binding: `../spikes/VERIFICATION-RULES.md`, seven rules. Each row states an externally
observable invariant, tests it through the public boundary, and pairs it with a control that
removes the guarantee and goes red.

| Invariant | Test | Negative control |
|---|---|---|
| Replaying one log event yields at most one cost record | replay the same `cost.usage.recorded` event | drop the `usage_seq` primary key ⇒ the run's total doubles |
| An unpriced call is recorded, not dropped | price against a snapshot missing the model | skip the record on pricing failure ⇒ the call vanishes from the ledger of calls |
| Unknown is never zero | assert `amount_nanos IS NULL` and `unpriced_reason` set | drop `cost_priced_xor_unpriced` and write 0 ⇒ the total looks complete and is wrong |
| A total containing an unpriced call is labelled | read `run_cost_totals` after one unpriced call | publish `priced_nanos_lower_bound` alone ⇒ a lower bound is reported as a total |
| Exactly one price event per usage event | append `recorded` with no `priced`/`unpriced` | drop the `(tenant_id, run_id, usage_seq)` key and the fold assertion ⇒ one usage event carries two prices and another carries none |
| Money is integral | price a fixture set whose amounts need more precision than a double, sum it in two different orders, assert both totals equal the oracle | store `amount_nanos` as `DOUBLE PRECISION` and price through binary floating point ⇒ the two orders disagree and both differ from the oracle |
| Rounding is reproducible | price a fixture whose exact amount lands on a half-nano | round half-even instead ⇒ the independent oracle disagrees |
| Pricing is reproducible from the snapshot bytes | second implementation prices the same fixture from `price_snapshots.body` | price from a live fetch ⇒ two runs of the same fixture disagree |
| The bytes priced against are the bytes that were digested | tamper with `price_snapshots.body`, price a fixture | skip the recompute ⇒ a corrupted dataset prices silently |
| Every record in a pricing interval names that interval's pinned digest | two calls in one leased interval, snapshot refreshed between them | let the writer read the current snapshot at pricing time ⇒ two records in one interval name different digests |
| Rewind does not reduce a total | rewind a run mid-log, re-aggregate | apply `live()` to `cost_records` ⇒ the total drops below the provider bill |
| Attribution is immutable after the call | record a call, then revoke and rename the principal | join `principals` at read time ⇒ the historical record changes |
| Cross-tenant totals are impossible | aggregate with a foreign `tenant_id` | drop `tenant_id` from the key ⇒ another tenant's spend appears |
| The projection equals the fold | rebuild `cost_records` from the log for a fixture corpus | let the projection be written outside the event's transaction ⇒ they diverge |

Rule 5 applies to rows 6, 7 and 8 specifically: the oracle must not be the pricing function
under test. Rule 7 applies to rows 1, 3, 5 and 13, whose controls remove a constraint, and to rows 9 and
12, whose tests mutate shared state: all six run against a uniquely-named schema created and
rolled back inside one transaction, never against a shared one, and assert neighbouring tables
survive. Row 9 tampers with `price_snapshots.body`, which is content-addressed and shared by
every run in the corpus — it must operate on a fixture snapshot the test inserted under its own
digest, and must assert the corpus snapshots are byte-identical afterwards. Row 12 mutates
`principals`, which `cost_records` references, and must own the principal row it revokes.

---

## What this does not guarantee

- **Not a bill.** Provider invoices include retries, minimum charges and negotiated rates we
  cannot see. This measures what our harness observed, priced against a public dataset.
- **No completeness claim against the provider.** If the harness never emits a `Usage` frame —
  a crash between the model response and the frame — the call is invisible here. The gap is
  bounded by the run, not detected within it.
- **No type-level guarantee that the pair travels together.** The view names its column
  `priced_nanos_lower_bound` so the shape carries the warning, but nothing prevents a caller
  from selecting that column alone. Pairing it with `unpriced_calls` is an obligation on the
  read contract [§06](06-api.md) owes, enforced in review in v0.1.
- **No freshness guarantee on prices.** A snapshot is as current as its last fetch, and OQ-028
  is open on the dataset's cadence.
- **No spend limit.** A single run can cost anything. Omnigent documents the same limit even
  *with* a cap — "a single very expensive turn can still overshoot before the next check"
  (`projects/omnigent/teardown.md:521`) — and we do not have the cap.
