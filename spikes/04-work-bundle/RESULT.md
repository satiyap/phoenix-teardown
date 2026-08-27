# Spike 04 — is the generic core actually domain-neutral?

**Verdict: NOT FALSIFIED.** 27 assertions against the real
`phoenix-onboarding/okf/bundles/sonyliv-analytics` bundle (133 nodes), plus a
mutation-shaped action sequence the bundle knows nothing about.

## The claim under test

Not "the model is expressive" — that is unfalsifiable. The specific claim:

> A domain-neutral core of `{WorkBundle, Resource, Action, ActionReceipt,
> Verifier, effect_class}` can express every executable in the OKF bundle **and** a
> mutation-shaped action, **without the platform learning any domain noun.**

Six failure conditions were written down before running:

| | Condition | Result |
|---|---|---|
| F1 | a domain noun must be understood by the core | not triggered — 0 of 12 nouns appear in the core dataclasses |
| F2 | an OKF executable needs a field the generic Action/Receipt lacks | not triggered — all 6 mapped; `{job_id, executed_sql, result}` fits `ActionReceipt` unextended |
| F3 | a mutation needs a settlement path the ledger lacks | not triggered — the same 3 outcomes cover it |
| F4 | `effect_class` cannot be derived, so it is a guess | not triggered — `run-on-bq.md` states read-only, so `observation` is *derived* |
| F5 | the verifier cannot be pinned independently | not triggered, but see finding 1 |
| F6 | freshness forces mutable state into an immutable bundle | resolved by construction, see finding 2 |

## Role distribution over the real bundle

```
knowledge 108 · resource_descriptor 24 · executable 6 · procedure 6
template 3 · executor 2 · verifier 1
```

Every one of the 133 nodes mapped to one of the fixed 7 behavioural roles, from
15 open domain `type` values. The `type → roles` table is **bundle-supplied
metadata**, not core logic: another domain ships a different table and the core is
untouched. That is the concrete form of "the platform must not add a database
table for every domain noun".

## Findings

**1. The verifier lives inside the bundle it verifies.**
`references/attesters/sql_equality.py` sits in the same repo, revision and
publisher as the SQL it checks — so whoever can edit a sanctioned computation can
edit its checker. The independence is *conventional, not structural*. It does
carry its own digest, so it **can** be pinned separately by a different publisher,
which is what `10-work-bundles.md` must require.

Third appearance of this defect class in the project: `default=str` embedding a
memory address, testing the mechanism instead of the claim, and now a verifier
co-published with its subject.

**2. Freshness in an immutable bundle is a real conflict, not hypothetical.**
4 of 10 dataset documents carry freshness/status prose about external systems.
A content-addressed bundle cannot hold mutable external state without forcing a
revision per staleness change — at which point people stop revising. Resolved by
keeping freshness out of `BundleNode` entirely: a `resource_descriptor` pins the
*contract*, freshness arrives as **evidence**.

**3. An unverified computation exists in the corpus.**
`computations/rai-per-million.md` has no `verified:` field, while the other five
do. It grades `UNVERIFIED` — never silently trusted, and never degraded to
`false`. A real instance of the ADR-0012 rule rather than a constructed one.

**4. `indeterminate` keeps the external operation id as a recovery handle.**
A disconnected receipt settles `indeterminate` and retains
`external_operation_id`, but the core has **no** polling code: inspection is a
separate `Action` producing an immutable `EffectObservation` with its own
`action_id`. The handle is evidence, not a work queue.

## Two defects in this test, both found by its own controls

- The scheduler check matched the word "schedules" inside a docstring stating the
  core *never* schedules — the same negation-spanning false positive that
  produced 4 bad hits in the capability map. Now matches code with comments and
  docstrings stripped.
- The freshness check **asserted the defect was present**, so a green run meant
  "the conflict exists". Wrong polarity: it now asserts the *core resolves* it and
  reports the bundle observation separately.

## Reproduce

```bash
../../.venv/bin/python map_bundle.py
```

## Not tested

- **Authorization.** No Cedar evaluation over `Principal × Action × Resource ×
  Context`; the resolve-then-reauthorize ordering fix is unverified.
- **Real connectors.** No BigQuery or Kubernetes call was made. `ActionReceipt` is
  shown to *fit* OKF's declared receipt fields, not to survive a live executor.
- **Artifact storage.** ACLs, retention, classification and redaction are untouched.
- **Knowledge access control.** Retrieval filtering before content reaches a model
  or an embedding index is the largest untested area.
