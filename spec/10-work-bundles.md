# 10 — Work bundles
<!-- status: draft -->

This settles the six nouns `00-overview.md` owes — `WorkBundle`, `Resource`, `Action`,
`ActionReceipt`, `Verifier`, `effect_class` — as schema, states how an `Action` lands on
the effect ledger `01` and `02` already define, and fixes the compile boundary: OKF v0.2
in, a signed content-addressed package out. Registration of bundles, verifiers and
resources is a northbound surface `06` owns; this fixes the tables and the constraints
registration must satisfy, not its routes, status codes or credential class.
**Amended 2026-09-03 (OQ-154): `06` owns it and does not yet carry it** — no route for
bundles, verifiers or resources exists in [`06-api.md`](06-api.md) or in
`contracts/openapi.yaml`. The sentence above states an assignment, and it was being read
as a delivery. `06` §Registration surfaces this document is owed now names the gap from
its own side, and `00-overview.md` §Not yet specified carries the row again. It does
**not** settle `tasks`/`routines` (spec 11), knowledge retrieval or its access control,
connector authentication, or artifact storage, and it adds no scheduler: nothing here
polls, waits, or drives an external operation toward settlement.

## The six nouns

| Noun | Is | Evidence |
|---|---|---|
| `WorkBundle` | a signed, content-addressed package of nodes plus the domain-`type` → role table used to compile it | `spikes/04-work-bundle/map_bundle.py:72 @ abfb206` |
| `Resource` | a registered target in the customer's estate: `kind`, `provider`, `canonical_id`, `environment`, `classification`, every field an open value | `map_bundle.py:89 @ abfb206` |
| `Action` | one narrow operation against one `Resource`, carrying an `effect_class` and, where it came from a bundle, the executable's digest | `map_bundle.py:99 @ abfb206` |
| `ActionReceipt` | what the connector observed at dispatch. Factual, immutable, carrying no reconciliation status | `map_bundle.py:113 @ abfb206`, asserted at `:310` |
| `Verifier` | an independently pinned artifact grading a completed `Action` `pass`/`fail`/`unverified` | `map_bundle.py:146 @ abfb206`; RESULT.md finding 1 |
| `effect_class` | `observation` \| `idempotent_mutation` \| `non_idempotent_mutation` \| `long_running_operation` | `map_bundle.py:49 @ abfb206` |

Spike 04 mapped all 133 nodes of a real bundle, plus a mutation-shaped sequence the bundle
knows nothing about, onto these six with **no domain noun entering the core** (RESULT.md:
F1 and F3 not triggered) — the licence for what follows, not a claim the model survives a
live connector, which spike 04 did not test.

## Source format, and what the runtime enforces

OKF v0.2 — markdown with YAML frontmatter — is the **source**
(`synthesis/scope-reconciliation.md` §7, "signed bundles (OKF v0.2 profile)";
`map_bundle.py:152,203 @ abfb206`, where the frontmatter is parsed from the `*.md` bytes).
A compile step, run out of band, digests each file's raw bytes into `content_digest`,
assigns `roles = type_roles[frontmatter.type]`, and digests the manifest through `03`'s
envelope under `kind = "work_bundle"`. `03` §`work_bundle` states the manifest's fields,
their ordering and the exclusions — including `revision`, whose exclusion is why
re-registering an identical recompile is idempotent; `UNIQUE (tenant_id, digest)` on
`bundles` is what makes that a fact rather than a convention. The two digests are
deliberately different, because a node body is arbitrary bytes — the real bundle's verifier
is a `.py` file (`map_bundle.py:215 @ abfb206`) — and `03`'s profile digests JSON only.
Changing one node's `content_digest` changes the bundle digest (`map_bundle.py:415 @
abfb206`, the spike's own negative control). **Normative: no run-path component reads
bundle source bytes** — the run path resolves `bundle_nodes` digests, and `source_format`
names what the compiler consumed, not what the runtime opens.

## The domain-`type` → role table is bundle-supplied

The seven behavioural roles are fixed: `knowledge`, `procedure`, `executable`, `executor`,
`verifier`, `resource_descriptor`, `template` (`map_bundle.py:46 @ abfb206`,
`BEHAVIOURAL_ROLES`; all 133 nodes of the real bundle mapped onto these seven — RESULT.md,
"Role distribution"). The mapping from a domain `type` onto them is **bundle content**,
stored in `bundles.type_roles` and digested with the bundle; the real bundle used 15 open
`type` values against those 7 roles. **Normative: nothing in the control plane or the
harness may branch on `bundle_nodes.domain_type`** — it reads `roles`. A second domain
therefore ships a different `type_roles` table and no code changes.

## A verifier declared on a node is pinned by a different publisher

Spike 04 finding 1: in the real bundle the attester sits in the same repository, revision
and publisher as the SQL it checks, so whoever can edit a sanctioned computation can edit
its checker. A `Verifier` is **not** a bundle node — it is a row in `verifiers` with its
own digest, signature and `published_by` — and `bundle_nodes` carries both publishers as
columns, each pinned by a composite foreign key, so one `CHECK` compares two values the
database vouches for, the redundancy `approvals.decided_by_kind` uses in `01`. That is
structural **for a verifier declared on a bundle node**. **Amended 2026-08-30 (OQ-086): the
customer nominates the verifier publisher** — not a first-party verifier registry we operate
— so onboarding a bundle must produce a distinct, customer-designated `verifiers.published_by`
before any of that bundle's graded results are trusted; a bundle with no nominated verifier
publisher has no independent grading.

The other path — `action_receipts.verifier_digest`, the verifier that actually graded a given
`Action` — was **unknown — OQ**: the receipt named a verifier by digest with no relation to
the publisher of the bundle whose executable it graded, so finding 1's co-publication was
reachable there. **Amended 2026-08-30 (OQ-087): fixed, with a trigger** — see
§Verifier independence on the receipt path.

## Freshness is evidence, never bundle state

Spike 04 finding 2: 4 of 10 dataset documents in the real bundle carry freshness prose
about external systems. A content-addressed bundle cannot hold mutable external state
without forcing a revision per staleness change — at which point people stop revising.
**Neither `bundles` nor `bundle_nodes` has a freshness column, and that absence is
normative.** A `resource_descriptor` node pins the *contract*; how fresh the resource is
right now arrives as an `observation` `Action` whose receipt carries the reading. The spike
asserts the core resolves this rather than asserting the bundle has the defect — its own
control caught that reversed polarity (RESULT.md, "Two defects in this test").
`bundle_nodes.stale_after` is not an exception: a constant the publisher wrote at publish
time about how long to trust their own attestation, immutable like the node.

## Schema

```sql
CREATE TYPE behavioural_role AS ENUM ('knowledge','procedure','executable',
    'executor','verifier','resource_descriptor','template');
-- The comment on each value is what `indeterminate` MEANS for it, and therefore
-- what a human may do next; dispatch requirements are CHECKs, stated below.
CREATE TYPE effect_class AS ENUM (
    'observation',             -- we do not know whether the read happened; a fresh Action is safe
    'idempotent_mutation',     -- a re-attempt is safe only if the provider honours the token
    'non_idempotent_mutation', -- a human must look; there is no safe automatic re-attempt
    'long_running_operation'); -- even ACCEPTANCE is unknown
-- finding 4 for 'inspects'; 'verifies' is the same shape applied to
-- VerifierVerdict (map_bundle.py:146 @ abfb206)
-- 'retries' added 2026-08-30 (OQ-088): points a re-attempt Action at its predecessor.
CREATE TYPE action_relation   AS ENUM ('inspects','verifies','retries');
CREATE TYPE transport_outcome AS ENUM ('response','timeout','disconnect');
CREATE TYPE verifier_verdict  AS ENUM ('pass','fail','unverified');

CREATE TABLE resources (            -- registered BEFORE it can be targeted, so
    tenant_id      BIGINT NOT NULL, -- environment and classification are the
    resource_id    TEXT   NOT NULL, -- platform's facts, not an agent's claim
    revision       BIGINT NOT NULL, -- APPEND-ONLY: reclassifying writes a NEW row
    kind           TEXT   NOT NULL, -- OPEN: 'dataset', 'deployment', ...
    provider       TEXT   NOT NULL, -- OPEN: 'bigquery', 'kubernetes', ...
    canonical_id   TEXT   NOT NULL,
    environment    TEXT   NOT NULL, -- both are inputs to the policy request, so
    classification TEXT   NOT NULL, -- neither may be rewritten in place (ADR-0013)
    registered_by  TEXT   NOT NULL,
    superseded_at  TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, resource_id, revision),
    FOREIGN KEY (tenant_id, registered_by) REFERENCES principals (tenant_id, principal_id)
);
CREATE UNIQUE INDEX resources_current ON resources
    (tenant_id, provider, canonical_id, environment) WHERE superseded_at IS NULL;
CREATE TABLE bundles (
    tenant_id      BIGINT NOT NULL,
    bundle_id      TEXT   NOT NULL,
    revision       TEXT   NOT NULL,
    digest         TEXT   NOT NULL,     -- 03, kind='work_bundle'
    source_format  TEXT   NOT NULL,     -- 'okf/0.2'
    type_roles     JSONB  NOT NULL,     -- BUNDLE-SUPPLIED; never core logic
    published_by   TEXT   NOT NULL,
    signature      BYTEA  NOT NULL,     -- over `digest`, checked at registration
    signing_key_id TEXT   NOT NULL,
    compiled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, bundle_id, revision),
    UNIQUE (tenant_id, digest),
    UNIQUE (tenant_id, bundle_id, revision, digest),         -- pins the run's pin
    UNIQUE (tenant_id, bundle_id, revision, published_by),   -- pins the publisher
    FOREIGN KEY (tenant_id, published_by) REFERENCES principals (tenant_id, principal_id),
    CHECK (digest ~ '^[0-9a-f]{64}$')
);
CREATE TABLE verifiers (
    tenant_id       BIGINT NOT NULL,
    verifier_digest TEXT   NOT NULL,    -- sha256 of the artifact bytes
    published_by    TEXT   NOT NULL,
    interface       TEXT   NOT NULL,    -- e.g. 'attest/v1'
    artifact_ref    TEXT   NOT NULL,
    signature       BYTEA  NOT NULL,
    signing_key_id  TEXT   NOT NULL,
    PRIMARY KEY (tenant_id, verifier_digest),
    UNIQUE (tenant_id, verifier_digest, published_by),
    FOREIGN KEY (tenant_id, published_by) REFERENCES principals (tenant_id, principal_id),
    CHECK (verifier_digest ~ '^[0-9a-f]{64}$')
);
CREATE TABLE bundle_nodes (
    tenant_id      BIGINT NOT NULL,
    bundle_id      TEXT   NOT NULL,
    revision       TEXT   NOT NULL,
    path           TEXT   NOT NULL,
    content_digest TEXT   NOT NULL,     -- sha256 of the RAW BYTES
    artifact_ref   TEXT   NOT NULL,     -- where the bytes live; resolution is BY DIGEST
    roles          behavioural_role[] NOT NULL,
    domain_type    TEXT   NOT NULL,     -- OPEN; nothing may branch on it
    verified_by    TEXT,                -- a NAME from the node's frontmatter, NOT a
    verified_at    TIMESTAMPTZ,         -- principals FK: the publisher attested and we
                                        -- did not (map_bundle.py:206 @ abfb206)
    stale_after    DATE,                -- and NO freshness column, ever
    bundle_published_by   TEXT NOT NULL,
    verifier_digest       TEXT,
    verifier_published_by TEXT,
    PRIMARY KEY (tenant_id, bundle_id, revision, path),
    UNIQUE (tenant_id, bundle_id, revision, path, content_digest),
    FOREIGN KEY (tenant_id, bundle_id, revision, bundle_published_by)
        REFERENCES bundles (tenant_id, bundle_id, revision, published_by),
    FOREIGN KEY (tenant_id, verifier_digest, verifier_published_by)
        REFERENCES verifiers (tenant_id, verifier_digest, published_by),
    CHECK (array_length(roles, 1) >= 1),
    CHECK ((verifier_digest IS NULL) = (verifier_published_by IS NULL)),
    CHECK ((verified_by IS NULL) = (verified_at IS NULL)),
    CHECK (content_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT verifier_is_independently_published        -- finding 1, structural
        CHECK (verifier_published_by IS NULL OR verifier_published_by <> bundle_published_by),
    -- Content the model reads and code the platform executes must not be the same
    -- artifact. `16-knowledge.md` §Layers states the rule; it is enforced here, so a
    -- both-roles node never reaches the compiler (16 compiles what this table admits).
    -- Relaxed 2026-08-30 (OQ-076, amended): the real bundle carries 150 role assignments
    -- over 133 nodes, so a node MAY carry several roles -- the blanket refusal was too
    -- strict for that. The rule narrows to the literal artifact-identity conflict this
    -- comment states: only the 'executable' role (an executable body) is mutually
    -- exclusive with a content role. 'executor' and 'verifier' may now co-occur with one,
    -- because neither names an artifact the model reads AS knowledge (an 'executor' is a
    -- platform-side role over other nodes; a 'verifier' is graded by its own independent-
    -- publisher CHECK above, a different risk).
    CONSTRAINT node_roles_are_content_or_executable
        CHECK (NOT (roles && ARRAY['knowledge','procedure','template',
                                   'resource_descriptor']::behavioural_role[]
                AND roles && ARRAY['executable']::behavioural_role[]))
);
CREATE INDEX bundle_nodes_by_role ON bundle_nodes USING GIN (roles);
CREATE TABLE actions (          -- status, claim, lease, request_digest and
    tenant_id       BIGINT NOT NULL,   -- result_ref live in effect_ledger and
    action_id       TEXT   NOT NULL,   -- are NOT repeated here
    run_id          TEXT   NOT NULL,
    idempotency_key TEXT   NOT NULL,
    operation       TEXT   NOT NULL,   -- OPEN: 'query', 'rollback_deployment', ...
    resource_id       TEXT NOT NULL,   -- the exact registry row the policy request saw
    resource_revision BIGINT NOT NULL,
    effect_class    effect_class NOT NULL,
    requested_by    TEXT   NOT NULL,   -- the ACTING principal, not the run's owner
    external_idempotency_token TEXT,   -- supplied at dispatch; carrying it across
                                       -- a re-attempt is unknown — OQ
    bundle_id         TEXT,            -- the bundle pin: all four, or none
    bundle_revision   TEXT,
    executable_path   TEXT,
    executable_digest TEXT,
    relation             action_relation,  -- an inspection, a verification or a retry is
    relates_to_action_id TEXT,             -- its own Action (finding 4; 'retries' added 2026-08-30)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, action_id),
    UNIQUE (tenant_id, idempotency_key),         -- one Action per ledger row
    UNIQUE (tenant_id, action_id, effect_class), -- FK targets for the receipt's
    UNIQUE (tenant_id, action_id, relation),     -- two CHECKs
    FOREIGN KEY (tenant_id, idempotency_key, run_id)
        REFERENCES effect_ledger (tenant_id, idempotency_key, run_id),
    FOREIGN KEY (tenant_id, resource_id, resource_revision)
        REFERENCES resources (tenant_id, resource_id, revision),
    FOREIGN KEY (tenant_id, requested_by) REFERENCES principals (tenant_id, principal_id),
    FOREIGN KEY (tenant_id, bundle_id, bundle_revision, executable_path, executable_digest)
        REFERENCES bundle_nodes (tenant_id, bundle_id, revision, path, content_digest),
    FOREIGN KEY (tenant_id, relates_to_action_id) REFERENCES actions (tenant_id, action_id),
    CHECK (num_nulls(bundle_id, bundle_revision, executable_path, executable_digest) IN (0,4)),
    CHECK ((relation IS NULL) = (relates_to_action_id IS NULL)),
    CHECK (relates_to_action_id IS NULL OR relates_to_action_id <> action_id),
    -- 'retries' (2026-08-30, OQ-088) points at a predecessor of ANY effect_class; only
    -- 'inspects'/'verifies' are restricted to 'observation' (finding 4's own shape).
    CHECK (relation IS NULL OR relation = 'retries' OR effect_class = 'observation'),
    -- an idempotent mutation with no external token cannot be re-attempted safely
    CHECK (effect_class <> 'idempotent_mutation' OR external_idempotency_token IS NOT NULL)
);
CREATE TABLE action_receipts (
    tenant_id        BIGINT NOT NULL,
    action_id        TEXT   NOT NULL,
    connector_digest TEXT   NOT NULL,   -- which connector build dispatched it
    dispatched_at    TIMESTAMPTZ NOT NULL,
    transport_outcome     transport_outcome NOT NULL,
    external_operation_id TEXT,         -- a RECOVERY HANDLE, not a work queue
    response_received_at  TIMESTAMPTZ,
    external_response_ref TEXT,
    evidence_refs    JSONB  NOT NULL DEFAULT '[]'::jsonb,
    effect_class     effect_class NOT NULL,  -- both pinned by the FKs below, so
    action_relation  action_relation,        -- the CHECKs can see them
    verdict          verifier_verdict,
    verifier_digest  TEXT,
    PRIMARY KEY (tenant_id, action_id),
    FOREIGN KEY (tenant_id, action_id, effect_class)
        REFERENCES actions (tenant_id, action_id, effect_class),
    FOREIGN KEY (tenant_id, action_id, action_relation)
        REFERENCES actions (tenant_id, action_id, relation),
    FOREIGN KEY (tenant_id, verifier_digest) REFERENCES verifiers (tenant_id, verifier_digest),
    CHECK ((transport_outcome = 'response') = (response_received_at IS NOT NULL)),
    CHECK (verdict IS NULL OR action_relation = 'verifies'),
    CHECK ((verdict IS NULL) = (verifier_digest IS NULL)),
    -- an unaskable verifier never answers `fail` (ADR-0012)
    CHECK (verdict IS NULL OR transport_outcome = 'response' OR verdict = 'unverified'),
    -- an accepted long-running operation with no handle is unobservable forever
    CHECK (effect_class <> 'long_running_operation'
           OR transport_outcome <> 'response' OR external_operation_id IS NOT NULL)
);

-- A run pins a bundle exactly as it pins a definition
-- (ADR-0011; `00-overview.md` non-negotiable 4). The three `pinned_bundle_*` columns and
-- their all-or-nothing CHECK are declared with `runs` in `01-schema.md`, which owns
-- schema; only the FK is here, because `bundles` is created above and cannot be
-- referenced before it exists.
ALTER TABLE runs ADD CONSTRAINT runs_bundle_pin_fk
    FOREIGN KEY (tenant_id, pinned_bundle_id, pinned_bundle_revision, pinned_bundle_digest)
    REFERENCES bundles (tenant_id, bundle_id, revision, digest);

GRANT SELECT, INSERT ON bundles, bundle_nodes, verifiers, actions,
                        action_receipts, resources TO app_role;
GRANT UPDATE (superseded_at) ON resources TO app_role;
```

No `DELETE` on any of the six tables, and no `UPDATE` except the `resources.superseded_at`
tombstone: a receipt that can be edited is not a receipt, and a `Resource` whose
`classification` can be edited rewrites the basis of every past decision about it, since
`01.policy_decisions` records no request inputs. A reclassification is a new `resources`
row, and an `Action` pins the `resource_revision` it was authorised against, which keeps an
old decision comparable (ADR-0013). The **platform** resolves an executable from
`bundle_nodes.artifact_ref` and re-verifies it against `content_digest` before dispatch —
the harness resolves nothing and executes nothing (spike 06) — so the artifact that
executes is the artifact whose digest was checked, taken from the registry and never from
the caller (`00` non-negotiable 6). The bundle pin is compared in step 4 of `05`'s resume
ordering, field by field, with the same terminal `INCOMPATIBLE` outcome: a bundle supplies
the executables *and* the `type_roles` table, so a changed bundle changes what the run may
do.

## Verifier independence on the receipt path

**Amended 2026-08-30 (OQ-087): fixed.** `action_receipts.verifier_digest` named a verifier by
digest with no relation to the publisher of the bundle whose executable it graded, so spike
04 finding 1's co-publication — the same principal publishing both the sanctioned computation
and its checker — was reachable on the receipt path even though `bundle_nodes`'
`verifier_is_independently_published` closed it on the declared-node path. A `CHECK` alone
cannot express this: it needs the bundle publisher of the `Action`'s pinned executable, reached
through `actions` and `bundle_nodes`, which is a join a `CHECK` cannot perform. A trigger does:

```sql
CREATE FUNCTION check_receipt_verifier_independent() RETURNS trigger AS $$
DECLARE bundle_pub TEXT; verifier_pub TEXT;
BEGIN
  IF NEW.verifier_digest IS NULL THEN RETURN NEW; END IF;

  SELECT bn.bundle_published_by INTO bundle_pub
    FROM actions a
    JOIN bundle_nodes bn
      ON bn.tenant_id = a.tenant_id AND bn.bundle_id = a.bundle_id
     AND bn.revision = a.bundle_revision AND bn.path = a.executable_path
   WHERE a.tenant_id = NEW.tenant_id AND a.action_id = NEW.action_id;

  IF bundle_pub IS NULL THEN RETURN NEW; END IF;   -- no bundle pin: nothing to compare

  SELECT published_by INTO verifier_pub FROM verifiers
   WHERE tenant_id = NEW.tenant_id AND verifier_digest = NEW.verifier_digest;

  IF verifier_pub = bundle_pub THEN
    RAISE EXCEPTION 'action_receipts.verifier_digest (published by %) must not be published '
                    'by the same principal as the bundle whose executable it graded (%)',
                    verifier_pub, bundle_pub
      USING ERRCODE = 'invalid_parameter_value';       -- 22023, as in 01 and 14
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER action_receipts_verifier_independent
  BEFORE INSERT OR UPDATE ON action_receipts
  FOR EACH ROW EXECUTE FUNCTION check_receipt_verifier_independent();
```

Structural now on both paths: the declared-node path by `verifier_is_independently_published`
(§Schema above), the receipt path by this trigger. A trigger is weaker than a `CHECK` in the
usual way ([`01-schema.md`](01-schema.md) §Polymorphic scope enforcement makes the same
point) — it does not run under `session_replication_role`-suppressed replication — which is
why the exception is stated here rather than assumed structural.

## An `Action` is one `effect_ledger` row

The ledger in `01` and `02` is the authority. Status, claim, lease, completion and the
stored outcome live in `effect_ledger`, the key and request digest in its
`idempotency_key` and `.request_digest` (`03`); `actions` holds only the operation, the
resource pin, the class and the executable pin, and `action_receipts` only what the
connector observed at dispatch.

The `actions` row is written in the **same statement batch as the intent insert** (`02`
phase 1), under the same `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING`, so the
replay branch — where the intent insert returns no row — inserts neither row. (`action_id`
is derived from the same deterministic key, so the two conflict targets cannot disagree.) A
ledger row for a bundle action therefore never exists without its `Action`. Everything
after is `02` unchanged: approval binds to the intent, the claim is one atomic `UPDATE`,
dispatch happens outside a transaction, settlement is fenced by `claim_owner` +
`claim_token` + `status='claimed'`. `effect_ledger.kind` is not extended — an `Action`
reached through a `ToolCall` frame stays `kind = 'tool_call'`; the value is `01`'s
(`effect_ledger.kind`, 01:365), reached through `07`'s typed `ToolCall` frame (07:123),
whose `step_id` feeds the same effect key (`07` §step_id and the effect key). The `Action`
row is how the platform knows which pinned executable that call resolved to.

### Settlement, from the receipt

Spike 04 asserted two transport outcomes against the ledger (`map_bundle.py:126 @
abfb206`). It tested transport only, so failure sat inside `response`; the mapping splits
it, because `01` already has a `failed` status and an external refusal is knowledge, not
uncertainty. A `response` whose connector reports the operation refused settles `failed` —
we know it did not happen; any other `response` settles `succeeded`; `timeout` and
`disconnect` settle `indeterminate` — claimed, dispatched, contact lost.

The first two use `02` phase 5 unchanged. `indeterminate` uses the same three fenced
predicates (`claim_owner = $worker AND claim_token = $token AND status = 'claimed'`) but
sets `status = 'indeterminate'` and leaves `completed_at` NULL, because `01`'s
`CHECK ((status IN ('succeeded','failed')) = (completed_at IS NOT NULL))` forbids a
completion time on an effect that never completed — `02` phase 5's `SET ... completed_at =
now()` applies to `succeeded|failed` only. Such a settlement retains
`external_operation_id` on the receipt: a recovery handle for a human, **not** a work
queue. Nothing polls it, and per `05` a run whose adapter is gone with this effect
unsettled ends `indeterminate`. Spike 04 asserts the core holds no polling or scheduling
code, matching with comments and docstrings stripped after its first version matched the
word inside a docstring saying the opposite (`map_bundle.py:327-333 @ abfb206`).

### Inspection, and verification, are each a separate `Action`

Finding 4. To learn what became of a lost operation, a **new** `Action` is created with
`relation = 'inspects'`, `effect_class = 'observation'`, its own `action_id`, its own
deterministic key and its own ledger row. It does not reopen the original — `01` is
explicit that effect rows are never re-claimed. A `Verifier` runs the same way, with
`relation = 'verifies'` and a receipt carrying `verdict` plus the `verifier_digest` that
produced it. Two consequences: **a verdict is not a settlement** — a `fail` undoes nothing,
because v0.1 ships no compensation engine (`v01-boundary.md` Never #1), so it is evidence a
human acts on; and **a `verifies` Action whose receipt is `timeout` or `disconnect` records
no verdict**, reading `unverified` and never `fail` — the `action_receipts` CHECK above,
not a convention (ADR-0012 rule 2: an implementation that could not be asked must never be
recorded as having answered no).

## Resource registration is a ledgered effect

**Amended 2026-08-30 (OQ-083, owner override, reversing the registry-first rule this section
stated until today): a connector MAY auto-register a `Resource` on first sight.** The
registry-first requirement — every `Resource` exists before an `Action` may target it, an
admin approves what a connector proposes — is dropped. In its place: **`Resource` creation is
itself a ledgered, policy-evaluated effect**, `kind = 'resource_registration'` on
`effect_ledger` (open text, `01-schema.md` §Effect ledger, alongside `tool_call` and
`delegation`), going through the same intend → policy → claim → dispatch → settle path as any
other effect. The consequence is stated because it is the one the registry-first rule existed
to avoid, and the override accepts it deliberately: **an agent's first call can create what
policy then governs** — the `INSERT INTO resources` is the dispatch, `environment` and
`classification` are what the connector observed and reported, and Cedar evaluates the
registration exactly as it would evaluate the `Action` that depends on it, so an
unauthorised-by-policy first sight is refused before the row exists rather than after.
`resources.registered_by` already carries the acting principal; nothing about the table
changes, only who may cause the insert and under what governance.

## `effect_class`, and what each value changes

`effect_class` is **derived from the bundle, not guessed**: the real bundle's executor
contract states read-only, which is what makes `observation` a derivation
(`map_bundle.py:280 @ abfb206`, F4 not triggered). Where a bundle does not state it,
registration refuses the executable rather than inferring one. Dispatch requires nothing
extra for `observation` and `non_idempotent_mutation`; an `idempotent_mutation` requires a
non-null `external_idempotency_token` (the CHECK on `actions`), and a
`long_running_operation` the provider accepted must carry an `external_operation_id` on its
receipt (the CHECK on `action_receipts`). A `response` settles `succeeded` for all four —
for a `long_running_operation`, `succeeded` means **accepted**, never completed. What
`indeterminate` means per value is the comment on each `CREATE TYPE effect_class` value.

**`effect_class` does not decide approval.** Cedar does (ADR-0013, `01` `policies`); the
class is an *input* to the policy request beside `Principal`, `Action`, `Resource` and
context. Making it a second approval authority would put one decision in two places, and
agents do not decide approvals at all (`01` `approvals.decided_by_kind CHECK (= 'human')`
plus its composite FK to `principals (principal_id, kind)`; `06` §credential classes).

**An `Action` must be narrow.** No operation may mean "do X and then wait until Y". Spike
04 decomposed an SRE deployment into four Actions and asserted no operation name joins two
(`map_bundle.py:351-352 @ abfb206`); `long_running_operation` exists because some
operations genuinely return a handle instead of a result, not as a licence to fold a wait
into a dispatch. Narrowness is enforced at bundle registration, on the operations an
executable declares — not by the schema, where `operation` is open text; whether it can be
enforced mechanically is **unknown — OQ**. **A retry is a new `Action`:** v0.1 never
re-attempts a settled effect, so a second attempt takes a new key and follows a human
decision. **Amended 2026-08-30 (OQ-088):** that new `Action` carries `relation = 'retries'`
and `relates_to_action_id` naming its predecessor — the same shape `inspects`/`verifies` use,
now open to any `effect_class` rather than only `observation` — so the chain is a query over
`action_relation` rather than a connector convention. Carrying the predecessor's
`external_idempotency_token` forward is still the connector's business, not the platform's:
this ties the two `Action` rows together; it does not decide what the retry sends.

## Trust grading

Computed at read time from `bundle_nodes`, never stored: no `verified_by` grades
`UNVERIFIED`, a past `stale_after` grades `STALE`, otherwise `VERIFIED`
(`map_bundle.py:368-383 @ abfb206`, the `trust()` function and its four checks, including
"a past stale_after grades STALE, not VERIFIED"). `UNVERIFIED` never degrades to `false`
and is never silently trusted (ADR-0012). The instance is real, not constructed: one of the
six attested computations carries no `verified` field while the other five do (RESULT.md
finding 3).

## Open questions

- **Amended 2026-08-30 (OQ-083, owner override):** yes — a connector may auto-register a
  `Resource` on first sight. See §Resource registration is a ledgered effect above.
- Signing-key lifecycle for bundle and verifier publishers — rotation, revocation, and what
  a revoked key means for an already-pinned bundle. **unknown — OQ**.
- The verifier calling convention — what `verifiers.interface` names, and how a grader is
  invoked against a completed `Action` — **unknown — OQ**, alongside that signature scheme.
- **Amended 2026-08-30 (OQ-086):** the customer nominates the second (verifier) publisher —
  see §A verifier declared on a node is pinned by a different publisher above. Onboarding
  must produce one before any trusted result.
- **Amended 2026-08-30 (OQ-087):** independence on the receipt path is now enforced — see
  §Verifier independence on the receipt path above.
- Nothing here ties a re-attempt `Action` to its predecessor's
  `external_idempotency_token`: **amended 2026-08-30 (OQ-088)**, the linkage itself is
  `relation = 'retries'` / `relates_to_action_id` (§Schema); carrying the token forward
  remains a connector convention.

## Tests, with negative controls

| Invariant | Test | Negative control |
|---|---|---|
| A verifier declared on a node is published by a different principal than the bundle | insert a node whose `verifier_published_by` equals `bundle_published_by` | drop `verifier_is_independently_published` ⇒ the co-published verifier of finding 1 is accepted |
| Neither bundle table can hold external freshness | assert no column of `bundles`/`bundle_nodes` names freshness or last-refreshed state, and that a staleness change creates **no** revision | add the column ⇒ every staleness change forces a revision, and people stop revising |
| Nothing branches on `domain_type` | compile a second bundle whose `type_roles` maps unseen `type` values onto the same 7 roles; run it with no code change | branch on `domain_type` ⇒ the second bundle needs a platform change |
| No run-path component reads bundle source bytes | assert the run path resolves only `bundle_nodes` digests, never `source_format` bytes | let the run path read OKF source ⇒ a run's behaviour changes with no revision and no pin change |
| An `Action` never duplicates ledger state | assert `actions` has no status, claim, lease or completion column, and that settlement reads only through `effect_ledger` | add `actions.status` ⇒ two authorities disagree after a fenced settle |
| An indeterminate receipt keeps its handle, and nothing polls it | force `disconnect`, assert `external_operation_id` survives and no scheduler ran (comments and docstrings stripped) | poll it ⇒ an effect we may already have performed is re-attempted |
| An indeterminate settlement carries no completion time | settle a `disconnect` receipt, assert `status='indeterminate'` and `completed_at IS NULL` | set `completed_at = now()` ⇒ `01`'s status/completion CHECK rejects the settle and the effect never closes |
| Inspecting a lost operation is a new `Action` with a new key | inspect, assert a second `action_id` and `idempotency_key`, and the original ledger row untouched | reuse the original key ⇒ `ON CONFLICT DO NOTHING` swallows the inspection and the first settlement can be overwritten |
| An accepted long-running operation always carries a handle | insert a `response` receipt for an LRO with `external_operation_id` NULL | drop the CHECK ⇒ an accepted operation nobody can ever inspect |
| A verifier that could not run reads `unverified` | receipt with `transport_outcome='timeout'` and `verdict='fail'` on a `verifies` Action | drop the CHECK ⇒ an unaskable verifier is recorded as having answered no |
| An idempotent mutation cannot dispatch without an external token | insert an `idempotent_mutation` Action with a NULL `external_idempotency_token` | drop the CHECK ⇒ a mutation dispatches with no external token and double-applies on re-attempt |
| No operation folds a wait into a dispatch | register a bundle whose executable declares an operation that blocks until a condition, and assert registration refuses it | accept it ⇒ a dispatch whose completion is unobservable settles `succeeded` on acceptance |
| An unattested node never grades VERIFIED, and a past `stale_after` never grades VERIFIED | grade a node with no `verified_by` and one whose `stale_after` has passed | default a missing `verified_by` to trusted ⇒ the unattested computation of finding 3 reads VERIFIED |
| A `Resource`'s policy inputs cannot be rewritten | reclassify a resource, assert a new `revision` row and the old row unchanged | grant `UPDATE` on `classification` ⇒ a past decision's inputs are silently rewritten |
| A node carrying both a content and an executable role is rejected | insert a node with `roles = {knowledge, executable}` | drop `node_roles_are_content_or_executable` ⇒ one artifact is both what the model reads and what the platform executes ([`16-knowledge.md`](16-knowledge.md) §Layers) |
| A bundle change is `INCOMPATIBLE` on resume | resume with a different `pinned_bundle_digest` | compare only the definition digest ⇒ the run executes a different executable set |

## What this does not guarantee

- **The registration surface is unspecified.** Three rules here — signature checking,
  idempotent re-registration, and refusal of an executable with no declared `effect_class`
  — are requirements on a component `06` has not yet defined.
- **No live connector was exercised.** Spike 04 shows `ActionReceipt` *fits* the declared
  receipt fields of a real bundle; it made no BigQuery or Kubernetes call.
- **No authorization was evaluated.** No Cedar decision over `Principal × Action × Resource
  × Context` is in evidence and the resolve-then-reauthorize ordering is unverified
  (RESULT.md, "Not tested"): this places `effect_class` and `Resource` in the policy
  request, it does not prove the ordering is right.
- **A different publisher is not proof of independence.** Two principals can be one human;
  the schema makes co-publication impossible on a declared node, not collusion.
- **Where the compiler runs is unspecified**, as is whether recompiling the same source is
  byte-reproducible. Only the boundary is settled here.
- **Knowledge retrieval is untouched** — filtering what reaches a model or an embedding
  index is the largest untested area spike 04 named.
- **Artifact storage is untouched** — the byte store behind `artifact_ref`, plus ACLs,
  retention, classification and redaction of `external_response_ref` and `evidence_refs`
  targets, are owed elsewhere.
