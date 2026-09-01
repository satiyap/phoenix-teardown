# 17 — Messaging (ag2.network behind our compatibility layer)
<!-- status: draft -->

Settles the Tier 3 messaging row owed by [§00](00-overview.md): the public surface of
the compatibility layer over `ag2.network` (channel lifecycle, `post`, `receive`,
`subscribe`), the `Envelope` as stored data, how the channel lease from
[§02](02-consistency.md) binds a hub, and the delivery guarantee we actually make.

It does **not** settle: any northbound messaging endpoint — [§06](06-api.md) is the
northbound contract and declares no channel route, so channels are a data-plane surface
in v0.1; federation between hubs; or the retention default, which is
recorded below as **unknown — OQ-124**. OQ-124 to OQ-129 are raised here, and are rows in
[`../open-questions.md`](../open-questions.md) and §00's OQ table.

The route this document implements is the one spike 01 passed. Its other route failed:
*"Clean `ag2.network` integration (contract intact) — **FAIL**; AG2 behind an owned
compatibility layer — **PASS**"* (`spikes/01-ag2-storage/RESULT.md` §Verdicts).

---

## Where the layer sits

Composition over the public API, not a fork. Spike 01 asserted from AG2's own source that
`CoreHub.post_envelope` contains no reference to `find_envelope_by_causation`, and that
the method's single internal self-call is the RPC dispatch table routing a *remote*
request (`RESULT.md` §Gate 01c). The hub makes no dedupe decision while accepting an
envelope, so a wrapper that claims first and delegates second touches no privates.

What we take from AG2: the `Envelope` shape, channel protocols and expectation
enforcement, delivery, cursors and replay (ADR-0003 amendment,
`ag2/network/envelope.py:5-11 @ 90f490a`; `RESULT.md` §The decision). What we own and AG2
never decides: dedupe, tenancy, the effect ledger, the storage schema, and which process
may serve a channel.

AG2 has no tenancy of its own (`RESULT.md` §What is still untested). Every entry point
below therefore takes `tenant_id` explicitly, and **a hub instance is keyed by
`(tenant_id, channel_id)`** — the same key as its lease — so no AG2 object (hub, channel,
passport or index) is reachable from two tenants' calls. AG2 checks nothing itself; this
holds only while the wrapper constructs hubs by that key.

The layer is a Python data-plane component. Storage is the Postgres of
[§02](02-consistency.md), reached through AG2's `KnowledgeStore` `Protocol` (eight
methods, satisfied structurally — no fork, no subclass; `RESULT.md` §Criterion 1),
implemented **row-per-envelope** rather than as spike 01's growing BLOB, which that spike
labels "wrong for production".

An agent never calls this surface itself: a post attributable to a run arrives as a
platform-executed tool call over [§07](07-adapter-protocol.md), which the harness declares
and does not execute.

---

## Public surface

Five operations: three on an existing channel, and the two that bring one into existence
and end it. Everything else AG2 exposes is internal to the layer.

```
open_channel(tenant_id, channel_id, protocol, created_by,
             depth_cap?, expires_at?)      -> {channel_id}

post(tenant_id, channel_id, sender_id, event_type, event_data,
     audience?, causation_id?, run_id?, task_id?, idempotency_key?,
     priority?, ttl_seconds?)            -> {envelope_id, seq}

receive(tenant_id, channel_id, subscriber_id, from_seq?, limit)
                                         -> {envelopes[], next_seq}

subscribe(tenant_id, channel_id, subscriber_id, from_seq?)
                                         -> stream of envelope, ended by the
                                            caller, by channel close, or by
                                            loss of the channel lease

ack(tenant_id, channel_id, subscriber_id, seq)   -> advances the cursor

close_channel(tenant_id, channel_id)     -> {closed_at}
```

`ack` is not a sixth capability; it is how `receive` and `subscribe` commit progress, and
it is separated from delivery on purpose — see §Delivery. `from_seq` is a **replay**
argument, not a delivery position: omitted, both operations deliver from `acked_seq + 1`;
supplied, it may only move the read BACKWARD — `min(from_seq, acked_seq + 1)` — so a
replay can re-read history and can never skip an unacked envelope. `ack` remains the only
thing that moves the cursor.

**Channel lifecycle.** `open_channel` inserts the `channels` row ([§01](01-schema.md)) and
is the one operation carrying no lease predicate: `channel_leases` references `channels`,
so no lease can exist before the row does. It is a single `INSERT`; a duplicate
`(tenant_id, channel_id)` raises `23505` on the primary key and is refused
`channel_exists`, never retried. `close_channel` does require the lease, carries the same
predicate in its `UPDATE ... WHERE` as the accepting statement below, and writes
`state = 'closed'` and `closed_at` in that one statement, because §01's
`CHECK ((state = 'closed') = (closed_at IS NOT NULL))` refuses either alone. It is
idempotent, returning the recorded `closed_at` on an already-closed channel. A closed
channel still serves `receive`; only `post` is refused.

**The caller supplies none of the stamped fields.** `envelope_id`, `seq`, `depth` and
`created_at` are assigned by the authority on accept, never by the sender (ADR-0003
rule 1). A `post` that carries any of them is refused rather than corrected, because
silently overwriting a forged field teaches a caller that it worked.

| Refusal | When |
|---|---|
| `channel_lease_not_held` | the calling hub does not hold an unexpired, unfenced lease on the channel |
| `channel_closed` | `channels.state = 'closed'` |
| `unknown_channel` | no `channels` row for `(tenant_id, channel_id)` |
| `channel_exists` | `open_channel` on a `(tenant_id, channel_id)` that already has a row |
| `stamped_field_supplied` | the caller set `envelope_id`, `seq`, `depth` or `created_at` |
| `expectation_violated` | the channel protocol does not permit this sender to speak now (AG2's `can_send()` probe; ADR-0003 rule 4) |
| `depth_exceeded` | the incremented `depth` would exceed the channel's cap |
| `unknown_event_type` | `event_type` is outside the closed set compiled into the build ([§04](04-events.md) naming rule; ADR-0003 rule 3) |
| `not_a_member` | a listed `audience` principal is not a member of the channel |

**Amended 2026-08-30 (OQ-125),** superseding "None of these refusals reaches a `run_events`
row in v0.1 … the entries are owed to §04 rather than invented here: unknown — OQ-125": one
`message.refused {code}` event, `code` one of the nine
refusals in the table above, registered in [§04](04-events.md)'s closed set and appended to
`run_events` wherever the refused `post` names a `run_id` (a refusal on a run-attributed
post has somewhere to land; a refusal on a post with no `run_id` — none exists in v0.1, since
an agent never calls this surface itself, §Where the layer sits — is out of scope). Non-negotiable
10 is satisfied by the one event type rather than nine.

Channel **membership**, which `not_a_member` reads, is now a table: **amended 2026-08-30
(OQ-126)**, superseding "defined by no resource in this spec … The membership record is
unknown — OQ-126; until it exists, `not_a_member` is a rule without a table":
`channel_members (tenant_id, channel_id, principal_id, role)`, defined in
[§01](01-schema.md) §Leases beside `channels`. AG2 keeps passports in hub memory only; this
makes membership durable and queryable, and `not_a_member` is a rule with a table behind it.

---

## The Envelope, as data

Fields are ADR-0003's amended envelope. Three tables; all three carry `tenant_id` in the
primary key, and every cross-table reference is a composite foreign key including it, with
the one exception §01's preamble records — `audience`, below. (`task_id`'s composite FK is
added by [§11](11-routines.md), because `tasks` is created there.)

`channels`, `channel_envelopes` and `channel_cursors` are defined **once**, in
[§01](01-schema.md), beside `channel_leases` and `channel_lease_history`. *(Moved there
2026-08-30, on the precedent §02 records for the lease tables: one resource defined in two
documents is how an implementer builds two tables. §01's DDL is what the Postgres gate
applies.)* This document names the columns it reasons about and defines none of them.

`audience` holds principal ids in a JSON array, which SQL cannot constrain — the third
exception [§01](01-schema.md)'s preamble states (added there 2026-08-30). The hub checks
membership and refuses `not_a_member`; the database does not.

`depth` carries a hard ceiling of 8 in the `CHECK`, matching `principals.delegation_depth`
([§01](01-schema.md)); `channels.depth_cap` is the policy limit the hub enforces per
channel. Two limits, different jobs: one bounds the data type, one a conversation.

---

## One hub per channel

[§02](02-consistency.md) decided it and [§01](01-schema.md) holds the DDL: `channel_leases`
and `channel_lease_history`, the fenced mechanism of `run_leases` on a different resource.
Acquire, renew, release and reclaim are §02's mechanism unchanged, fence tokens monotonic
across reclaims because the high-water mark lives in the history table. §02 tunes the **run**
lease (60s TTL, renewed every 20s, `spec/02-consistency.md` §Renew) and gives no channel figure;
v0.1 adopts those defaults rather than inventing a second pair, and channel-specific tuning
is **unknown — OQ-127**.

`channel_leases.hub_id` is a worker identity in exactly the sense `run_leases.holder` is
([§01](01-schema.md)): self-asserted, with no registry behind it and not a resource.

**A hub must hold the lease before `post_envelope`.** The lease predicate is carried in
the accepting insert, so nothing is decided across two reads:

```sql
WITH claimed AS (
    UPDATE channels c SET max_seq = c.max_seq + 1
     WHERE c.tenant_id = $1 AND c.channel_id = $2 AND c.state = 'open'
       AND EXISTS (SELECT 1 FROM channel_leases l
                    WHERE l.tenant_id = $1 AND l.channel_id = $2
                      AND l.hub_id = $hub AND l.fence_token = $fence
                      AND l.expires_at > now())
    RETURNING c.max_seq AS seq
)
INSERT INTO channel_envelopes (tenant_id, channel_id, seq, envelope_id, sender_id,
                               event_type, event_data, depth, accepted_fence, ...)
SELECT $1, $2, claimed.seq, $3, $4, $5, $6, $7, $fence, ...
  FROM claimed
RETURNING seq, envelope_id;
-- 0 rows is TWO-valued — closed, or fenced out — and must not be acted on blind.
-- Re-read `channel_leases` for (tenant, channel, $hub, $fence, expires_at > now()):
--   lease present => the channel is closed: refuse `channel_closed`, keep serving.
--   lease absent  => we are FENCED OUT: drop the channel's in-memory state, stop serving.
-- One 0-row result cannot decide both: the absent/unknown conflation §Dedupe refuses.
```

A channel that does not exist cannot reach this statement: the hub is keyed by
`(tenant_id, channel_id)` and holds that channel's lease, and `channel_leases`'s composite
FK ([`01-schema.md`](01-schema.md) §Leases, `channel_leases`) makes a lease on an absent channel unrepresentable. A `post`
naming an unknown channel is refused `unknown_channel` before the statement runs.

`expires_at > now()` is not optional, for the reason §02 gives about every fenced write:
without it a stalled holder whose channel was reclaimed still matches the `EXISTS`.

**The seq comes from `channels.max_seq`, not from `MAX(seq)` over the envelopes** — §02's
own precedent for a counter that must outlive its rows: "fence tokens must be monotonic
ACROSS reclaims, so the high-water mark lives in `run_lease_history` and outlives the lease
row" ([§02](02-consistency.md) §Acquire). Deriving it from the envelope table would re-issue
seq numbers once retention compacted that table; see §Retention.

Accepting an envelope runs at `READ COMMITTED`, which [§02](02-consistency.md) §Isolation
levels gives every operation whose guarantee comes from a single conditional statement —
named, not left to a global setting. Two concurrent posts through one hub both take the
`channels` row: the loser blocks on the winner's **row lock**, re-reads the committed row
and increments again, so it is issued the next seq rather than colliding. (A row lock, not
spike 03's blocking on an uncommitted *index entry*: that case ends in `23505`, this one in
a fresh seq. `REPEATABLE READ` would raise `40001` here, and is not used.)
`statement_timeout` is mandatory exactly as on the run-event append, and `57014` is
retryable ([§02](02-consistency.md) §Sequence assignment, §Error mapping).

A `23505` on `channel_envelopes` is **not** retryable and is not a seq race: the counter is
issued under the `channels` row lock, so the only constraint that can fire is
`UNIQUE (tenant_id, envelope_id)` ([`01-schema.md`](01-schema.md) §Leases, `channel_envelopes`), which means the post already
landed. Read the existing row and return it — §02's action for `23505` on `effect_ledger`,
not its action for `run_events`. §02's error-mapping table has no `channel_envelopes` row;
it is owed two, one per code.

**Losing the lease is not recoverable in place.** AG2 keeps passports, rules, channel
state, adapter folds and indexes in process memory (`RESULT.md` §What is still untested),
so a hub that loses a lease must discard that channel's in-memory state, and one that
acquires a lease must hydrate from `channel_envelopes` before accepting a post. Hydration
does **not** restore AG2's causation index for a terminal channel — deliberate upstream
behaviour (`hub/core.py:2907-2911 @ 90f490a`, quoted in `RESULT.md` §Criterion 2) — which
is exactly why nothing downstream may depend on it.

---

## Dedupe is ours, entirely

**`find_envelope_by_causation` is never called on a correctness path.** Not as a fallback,
not as a fast path with a slow path behind it. Spike 01 measured what it returns after a
channel closes: `None`, while the durable log holds exactly one matching envelope. `None`
therefore means "no duplicate **or** cannot tell" and the caller cannot distinguish them —
the `absent`/`unknown` conflation, inside the dedupe path (`RESULT.md` §Criterion 2, five
scenarios). This is the resolution of **OQ-024**. A three-valued lookup would not be enough
even without the horizon: it is still a read, and two hubs can both read `NOT_FOUND`, both
act, and both append — the known-bad control produced `['w1','w2']`, a real double
execution (`RESULT.md` §Gate 01b).

The primitive is instead the atomic claim of [§02](02-consistency.md), keyed on
`effect_ledger.idempotency_key`, derived per [§01](01-schema.md) from
`(tenant_id, run_id, logical_step_path, request_digest)`. That derivation contains **no
message identifier**, which is what makes it survive retention.

Consequences, normative:

1. A post that is an external effect — `effect_ledger.kind` `notify` or `delegation`
   ([§01](01-schema.md)) — runs the five-phase lifecycle of §02 (intent, approval,
   claim, dispatch, settle) with `post_envelope` as the dispatch. The claim precedes the
   call; a lost claim means no call.
2. `causation_id` is a threading field and, at most, a lookup hint. It is not a key
   source and may not appear in any predicate that decides whether an effect runs
   ([§02](02-consistency.md) §Claiming and performing an effect, step 1: the key is
   derived "never from a message id, so intent survives message-log retention").
   ADR-0003's amended envelope calls it "also the reply dedupe key" (§Amended decision;
   its field table, "doubles as the dedupe key"), and `spikes/01-ag2-storage/RESULT.md`
   §The decision keeps it as "one derivation path". Both are **amended 2026-08-30**: a key
   derived from a message field cannot be re-derived past the retention horizon, so
   `causation_id` is threading only. §01's derivation carries the same amendment and
   already agrees. What the ADR meant by "derivation path" is **OQ-129**, against ADR-0003 and
   spike 01, not §01.
3. An envelope's `idempotency_key` is an **input to the effect's `request_digest`, not a
   key** (decided 2026-08-30; §01 carries the same amendment). The ledger key stays
   [§03](03-canonicalisation.md)'s four-field derivation over `tenant_id`, `run_id`,
   `logical_step_path` and `request_digest`, so a replayed envelope carrying the same
   client key at the same logical step derives the same row — and a client key cannot
   collide with a key the platform derived. It is client-supplied and stable across
   retention, which is what makes it usable as a digest input; `envelope_id` and `seq` are
   neither, and neither may be used at all.

---

## Retention

`channel_envelopes` rows may be deleted or compacted past a horizon. **Amended 2026-08-30
(OQ-124): 90 days per tenant, default.** It stays a tenant-configurable policy; 90 days is
the value a tenant gets until it configures another.

**Compaction never lowers `channels.max_seq`.** Seq is monotonic for the life of the
channel, not for the life of its rows: an emptied channel still issues its next seq
above every seq it ever issued, so no cursor is left ahead of a live envelope.

The binding rule is not the number. **No predicate outside the messaging layer may read
`channel_envelopes`** — not the effect claim, not the settle, not the approval gate, not
the run fold. Enforced the way [§01](01-schema.md) enforces append-only — by grant, not by
prose: `channel_envelopes` is readable only by the messaging role
(`GRANT SELECT, INSERT ON channel_envelopes TO messaging_role;`), while the effect,
approval and fold paths run as `app_role`, which is granted no `SELECT` on it; the audit
read of §Delivery is a third, operator role. Those `GRANT` lines belong beside §01's grant
block, where the channel DDL now lives, and are owed to it. The channel's own hydration
does read the table, and losing those rows degrades messaging only; it can never change
whether an effect runs. Invariant 3 of [§00](00-overview.md) states the guarantee; spike 01
proved it by closing the channel *and deleting the WAL entirely*, then asserting the claim
still held (`test_C_claim_is_independent_of_channel_lifetime`).

What retention costs is **audit**: past the horizon, "what was withheld from whom" is no
longer answerable for that channel. A deliberate trade against storage, and the only thing
the horizon is allowed to change.

---

## Delivery

**At-least-once, and we say so** rather than implying more (ADR-0003, from AG2).

- Ordering holds **within a channel**, by `seq`, because exactly one hub writes it.
  There is no ordering across channels and none is offered.
- `receive` and `subscribe` deliver from `acked_seq + 1`, or from an earlier `from_seq`
  supplied for replay (§Public surface). A subscriber that crashes after handling an
  envelope and before `ack` sees it again: the guarantee, not a bug to be closed.
- A redelivered envelope carries the same `envelope_id`. A subscriber whose handling has
  an external effect must go through the ledger, where the duplicate is refused by the
  claim; a subscriber whose handling is internal may compare `envelope_id` locally.
- The WAL records every accepted envelope; `notify` lands only on the listed audience. A
  subscriber outside the audience does not receive it and can still read it in an audit
  query, which is the point of the wider audit scope.

That audit read is a direct query of `channel_envelopes`, not a further operation of this
layer: [§06](06-api.md) declares no channel route, so v0.1 has no northbound audit surface
and the test row below reads the table directly. An operator-facing audit read is
**unknown — OQ-128**, owed to §06.

---

## Tests, with negative controls

Per [`../spikes/VERIFICATION-RULES.md`](../spikes/VERIFICATION-RULES.md): each row is
tested through the public boundary, with a control proving the test fails when the guard is
removed.

| Invariant | Test | Negative control |
|---|---|---|
| One hub per channel | two hubs, same channel, both post | remove the lease predicate ⇒ both posts land |
| A fenced hub cannot post | expire the lease, reacquire elsewhere, old hub posts | drop `expires_at > now()` ⇒ the stale hub's write lands |
| The claim survives retention | claim an effect, close the test's own channel, delete every `channel_envelopes` row for that `(tenant_id, channel_id)`, assert a neighbouring channel's rows survive, redispatch | derive the key from `envelope_id` ⇒ the second dispatch proceeds |
| Correctness never consults AG2's index | make `find_envelope_by_causation` raise on call; run the whole suite | route the claim through it ⇒ the suite goes red after a channel close |
| At-least-once redelivery | handle an envelope, kill before `ack`, resubscribe | advance the cursor on delivery ⇒ the envelope is lost, not redelivered |
| The authority stamps identity | post with a caller-supplied `envelope_id` and `depth` | accept and overwrite them ⇒ a sender can forge an id and reset its hop count |
| Ordering within a channel | N posts through one hub, assert `seq` is `1..N` | remove the PK ⇒ duplicate `seq` |
| seq survives compaction | post N to the test's own channel, delete that channel's `channel_envelopes` rows, assert a neighbouring channel's rows survive, post again | source seq from `MAX(seq)` ⇒ the new envelope re-uses seq 1 and every acked subscriber skips it |
| One tenant per hub instance | ask the hub cache for `(A,c)` and `(B,c)` | key the cache on `channel_id` alone ⇒ tenant B is handed tenant A's hub, passports and index |
| Tenant scoping | read channel `c` as tenant B | drop `tenant_id` from the key ⇒ tenant B reads tenant A's envelopes |
| Audit is wider than delivery | post with a narrow `audience`, assert a non-member sees nothing from `receive` and the row from an audit read | write only delivered envelopes ⇒ what was withheld is unrecoverable |
| Depth is capped by the platform | post a reply chain past `channels.depth_cap` | let the sender set `depth` ⇒ runaway delegation is bounded by prompts |

Both deletions are scoped to a channel the test created: rule 7 forbids a verifier
destroying state it does not uniquely own, and the surviving-neighbour assertion is the
clause that proves the scope held. The fourth row's oracle is independent of our code —
AG2's method is replaced with one that raises, so a green suite is evidence about *absence
of a dependency*, not about our wrapper.

---

## What this does not guarantee

- **Not exactly-once delivery.** Duplicate delivery is expected; duplicate *effects* are
  what the ledger prevents.
- **Not ordering across channels**, and not causal ordering within one beyond `seq`.
- **Not a delivery receipt.** `ack` records that a subscriber consumed an envelope, not
  that it acted on it.
- **Not horizontal capacity per channel.** One hub, one channel; sharding channels across
  hubs is the scaling path, and a hub failure blocks its channels for up to the lease TTL.
- **Not audit beyond the retention horizon.**
- **Not proven under production storage.** Spike 01's store was SQLite with one BLOB per
  channel, and it says so: row-oriented storage, Postgres contention, indexing, transaction
  boundaries and concurrent writers are all untested. The two-hub race above is an
  implementation gate, not a spike result.
- **Not tenancy inside AG2.** Isolation is a property of our wrapper's calls, not of any
  check the vendor performs.
