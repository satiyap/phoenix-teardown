# 16 — Knowledge and state
<!-- status: draft -->

Boundary tier 2, item 11 (`v01-boundary.md`): **Knowledge (files) + State (four
scopes)**. This document settles what a knowledge package *is*, how it is compiled and
resolved, how it enters the definition digest, and the rules under which `state_entries`
([§01](01-schema.md)) may be read and written. Every edit it needed in another file — spec
01, 03, 04, 05, 06, 12 and 15 — has landed as of 2026-08-30 and is cited in the present
tense, so this document owes nothing and is owed nothing.

It deliberately does **not** settle: how the harness assembles a system prompt from the
package (spec 12 owns context assembly), how the package is mounted (the sandbox document
owns the storage boundary), the `WorkBundle` the bundle layer comes from
(`10-work-bundles.md`), or semantic recall — **`Recall` is deferred**, its trigger "a user
needing cross-session semantic recall that files cannot serve" (`v01-boundary.md`).

---

## Three parts, and only two of them ship

ADR-0008 (Accepted, amended 2026-08-26) decomposes memory rather than unifying it: its
amended decision names three parts, and v0.1 builds two.

| Part | v0.1 | Substrate | Writable at run time |
|---|---|---|---|
| **Knowledge** | yes | files, git-backed, compiled to a content-addressed package | **no** |
| **State** | yes | `state_entries` (three scopes) + `temp:`, which has no row | yes, through a platform-executed tool |
| **Recall** | deferred | — | — |

Knowledge being read-only at run time is what makes the split usable: the writable half
is `state_entries`, whose scopes carry the permissions, and the read-only half is pinned
by digest like any other artifact. Letta is the counter-example v0.1 does *not* follow —
its agents edit their own git-backed memory — so agent-authored knowledge is an OQ.

Files rather than a service is settled by convergence, not preference — seven projects
with filesystem or git-backed skills and no memory service between them: Letta
(`src/tools/descriptions/Memory.md @ 852ca24`), OpenHands
(`agent_server/skills_router.py:62,96 @ 760eea2`, org-level skills from a git repository),
Google AX (`internal/config/config.go:119-133 @ b777313`), Omnigent
(`omnigent/spec/AGENTSPEC.md @ ba9e371`), Cloudflare (`design/skills.md @ 2f957bc`), AG2
(`ag2/network/identity.py:15-16 @ 90f490a`) and Pydantic AI (`_history_processor.py @
b48ee38`) — ADR-0008 evidence log.

---

## Knowledge

**The word `skill` is overloaded, and this document owns only one sense of it (added
2026-09-03, OQ-152).** Here a skill is **Knowledge**: files, git-backed, compiled to a
content-addressed package, **read-only at run time**, resolved over the five layers below.
That is ADR-0008's sense and the one seven projects converged on. It is *not*
[`10-work-bundles.md`](10-work-bundles.md)'s `executable`, `procedure` or `executor`
behavioural roles, which are the invocable sense a customer usually means by "turn this skill
on" — different owner (`bundle_nodes`, not `knowledge_sources`), different digest
(`work_bundle`, not `knowledge_package`, [`03-canonicalisation.md`](03-canonicalisation.md)),
and a different enablement mechanism: a knowledge skill is enabled by a `knowledge_sources`
row at the right layer, an invocable one by a binding in the **pinned** definition. Nothing in
this document governs the second sense, and a control written here believing otherwise governs
nothing.

### Layers and resolution order

**Amended 2026-08-30 (OQ-081, owner override): five layers, not three.** `team` and `persona`
are added between `tenant` and `agent`. Resolved per **exact path**, highest precedence
first:

| Precedence | Layer | Source | Owner |
|---|---|---|---|
| 5 (highest) | `agent` | a git commit registered in `knowledge_sources` | the agent's operator |
| 4 | `persona` | a git commit registered in `knowledge_sources`, keyed by `persona_key` | the persona |
| 3 | `team` | a git commit registered in `knowledge_sources`, keyed by `team_id` | the team |
| 2 | `tenant` | a git commit registered in `knowledge_sources` | the tenant |
| 1 (lowest) | `bundle` | nodes of the pinned `WorkBundle` (spec 10) | the bundle publisher |

Resolution falls back **persona → team → tenant → bundle** beneath `agent`, unchanged at the
top: the highest layer that declares a path wins, exactly as the three-layer rule already
worked, extended over two more layers.

**Two new nouns, defined here because owner decision 2026-08-30 introduces them and no other
document does:**

- **`team`** is a principal-group id — an uninterpreted `TEXT` naming a group of principals,
  with no `teams` resource of its own in v0.1 (the same shape `state_entries.scope_key` takes
  for `user`/`session` scope, [§01](01-schema.md) exception 1 — a value this table stores and
  does not resolve).
- **`persona`** is a role label — an uninterpreted `TEXT` naming a role an agent may be
  operating under, likewise not a resource in its own right.

Both are stored, not enforced: `knowledge_sources.team_id` and `.persona_key` carry them, and
nothing in v0.1 validates that a `team_id` names a real group of principals or that a
`persona_key` names a real role — the same trust the `agent_id`-scoped `agent` layer already
places in its git remote, extended to two more open identifiers.

The layer set is the evidence log's, not an invention: the tenant layer is OpenHands'
org-level skills from a git repository (`agent_server/skills_router.py:62,96 @ 760eea2`),
the agent layer is AG2's per-agent `SKILL.md` plus `knowledge/` package
(`ag2/network/identity.py:15-16 @ 90f490a`), both ADR-0008, and the bundle layer is spec
10's pinned `WorkBundle`. Precedence runs narrowest-owner-first because the narrower owner
is the one accountable for the override; `team` and `persona` extend that same rule rather
than break it — a persona override is narrower than a team's and wider than one agent's.

**Amended 2026-08-30 (OQ-081, owner override),** superseding "Three layers, not four: a layer
between `tenant` and `agent` would need a resource neither the boundary nor the ADRs name,
and `policies.scope = 'project'` has no v0.1 referent ([§01](01-schema.md), exception 2).
Whether one is needed is unknown — OQ": that question is moot for v0.1 now that `team` and
`persona` are added. The trigger that raised it — the first customer with two teams on one
bundle — is likewise moot; it fired.

**Whole-file override, never a merge.** The file is the unit because it is what carries a
digest and a diff — Letta's file-granular memory (`projects/letta/teardown.md:39-43`).
If two layers resolve the same path, the higher
layer's bytes win and the lower file does not appear in the package: a merged file has a
digest nobody authored and no diff anyone can review, and an override is both. A higher
layer may introduce a path no lower layer has, but may **not remove** one — v0.1 has no
tombstone, so a bundle file can be replaced and not suppressed. Deletion across layers is
unknown — OQ.

Not every bundle node is knowledge. Spike 04 mapped a real 133-node bundle onto seven
bundle-supplied behavioural roles — `knowledge 108 · resource_descriptor 24 · executable
6 · procedure 6 · template 3 · executor 2 · verifier 1`
(`spikes/04-work-bundle/RESULT.md`). `roles` is an **array**
([`10-work-bundles.md`](10-work-bundles.md) §Schema, `bundle_nodes.roles`, indexed GIN at `:181`), so the rule is over the whole set: a
node compiles into the package **iff** its roles intersect {`knowledge`, `procedure`,
`template`, `resource_descriptor`} **and** are disjoint from {`executable`} (**amended
2026-08-30, OQ-076**, superseding "disjoint from {`executable`, `executor`, `verifier`}":
`executor` and `verifier` may now co-occur with a content role; only `executable`, an
executable body, is mutually exclusive with one). A node carrying both a content role and
an `executable` one is refused by `bundle_nodes`' `node_roles_are_content_or_executable` CHECK
([`10-work-bundles.md`](10-work-bundles.md) §Schema), so it never reaches the compiler —
content the model reads and code the platform executes must not be the same artifact, and
one document states that rule while one enforces it. The executable side is Actions, pinned by spec 10, and a
verifier must be pinned by a different publisher than the bundle it verifies (spike 04,
finding 1). A
`resource_descriptor` pins a contract, never live status: freshness is evidence, not
bundle state (finding 2).

### Layout of the compiled package

```
<package root>/
  manifest.json        every other file, with its digest
  system/**            always-resident: assembled into the system prompt every turn
  **                   listed in the manifest; read on demand
```

The `system/` split is Letta's, and it is a context-budget mechanism rather than a
taxonomy: `system/**` is always in the prompt, everything else costs a manifest line plus
an optional read (`projects/letta/teardown.md:39-43,215-221 @ 852ca24`). Which files a
harness reads on demand is spec 12's business. `system/**` is the **always-resident set**:
spec 12 MUST include every `system/**` file in each model request's context, and a
`system/` tree that does not fit ends the run
`End{FAILED, error_code = context_exhausted}` ([`12-harness.md`](12-harness.md) §4 rule 5)
rather than dropping files. [§12](12-harness.md) §8 carries this as a set of its own,
entered alongside the symbolic closure rather than through it, and draws both from the
compiled package rather than from the pinned bundle.

### Closure selection

**Amended 2026-08-30 (OQ-080): owned here, beside `manifest.json`.**
[`12-harness.md`](12-harness.md) §8 names the **closure selection** — the entry nodes and the
admitted digests that `Start.config` carries, a projection of `manifest.json` — without
defining it or naming an owner; that gap is closed by this paragraph. The closure selection
is: the set of entry-node paths a step declares, together with the `content_digest` each
resolved to in the compiled package at closure time. It is a *projection* in exactly
§What the digest covers' sense — a derived view of `manifest.json`, not a new artifact — and
`Start.config`'s byte layout stays opaque to the control plane by design ([§07](07-adapter-protocol.md)
§`config` is opaque), so this paragraph names what the projection *is*, not its wire shape.
[`12-harness.md`](12-harness.md) §8 rules 3-4 govern how it constrains context; this document
governs where it comes from.

### Path rules, enforced at compile time

- Relative POSIX paths only: a leading `/`, any `..` segment, or a symlink is a compile
  error — the materialised tree must contain exactly the manifest's paths and nothing
  outside the package root, which is non-negotiable 6 ([`00-overview.md`](00-overview.md))
  applied to a tree rather than a blob.
- Paths are **NFC-normalised** before resolution, matching the digest profile's treatment
  of strings ([§03](03-canonicalisation.md) step 2). Two source paths that collide after
  NFC are a compile error, not a silent override.
- Two paths differing only by case are a compile error: they resolve to one file on a
  case-insensitive filesystem, so the materialised tree would disagree with its manifest —
  the same invariant, and the bidirectional walk of §Materialisation would then find one
  tree path for two manifest entries.
- Package size, file count and single-file size are bounded, and the compiler rejects a
  package that exceeds a bound rather than truncating it. **Amended 2026-08-30 (OQ-121):
  provisional limits — 64 MiB per package, 10 000 files, 8 MiB per file.** Configuration, not
  schema: no column enforces them, the compiler does, and they move without a migration.
  Spike 04's real bundle (133 nodes / 108 `knowledge`) sits far under all three, so the
  numbers are provisional against no real ceiling pressure yet, not a measured limit.
  **Amended 2026-08-30 (OQ-121):** a compiled package persists until explicitly removed;
  no horizon expires one.

### Compilation

Deterministic, and re-runnable offline from its inputs:

```
1. resolve the bundle layer from the pinned WorkBundle (bundle_id, revision) — spec 10
2. resolve the tenant, team, persona and agent layers at their registered commit_sha
   (**amended 2026-08-30, OQ-081**, superseding "resolve the tenant and agent layers at
   their registered commit_sha": team and persona are two more layers this step resolves)
3. apply the path rules; reject on any violation
4. overlay by precedence, per exact path
5. emit manifest.json: [{path, digest}], sorted by path in UTF-8 byte order (03 step 4)
6. package_digest = digest of the manifest PROJECTION, kind `knowledge_package`
```

Step 5 sorts explicitly because [§03](03-canonicalisation.md) does **not** sort arrays for
us — vector #7 exists to prove array order is significant — so a compiler emitting files
in filesystem order would digest the same package differently.

### What the digest covers, and what it deliberately excludes

**Included:** every resolved path and the digest of its bytes. Step 6's **projection** is
exactly `{"files": [{"path", "digest"}]}` — which is `manifest.json` in full, so the file
does not digest itself and carries nothing the digest omits.

**Excluded:** the source `layer` (it lives in `knowledge_compilations`, per-path, with the
rest of the provenance), `commit_sha`, git author, commit message, tree ids, file mtimes,
modes, the repo remote, `bundle_id` and `bundle_revision`.

The exclusions follow [§03](03-canonicalisation.md)'s rule for `declared_version`, proven
in spike 02: a label must not invalidate a checkpoint, and forgetting to change a label
must not hide a real change. A commit sha is such a label. Two layer stacks that compile
to the same bytes **are** the same package — the runtime cannot tell them apart, so
neither should the digest. Provenance is not lost but moved: it lives in
`knowledge_compilations`, readable without being load-bearing.

### Digest participation

A knowledge package participates in the definition digest through exactly **one** field,
`knowledge_package_digest`: [§03](03-canonicalisation.md) §The algorithm's domain-separation table registers `knowledge_package`
as a digest `kind` and `:269` defines its projection, and its `agent_definition`
field-inclusion rules (`:201-202`) carry `knowledge_package_digest` and `state_schema`
(§State below) alongside `name`, `instructions`, `tools` and `extensions`. Nothing else
about knowledge enters that digest,
because the package digest already covers it. Three consequences:

- **The run's pin covers knowledge with no new column.** `runs.pinned_definition_digest`
  ([§01](01-schema.md)) covers the whole definition body, so the package digest is compared
  on every resume at [§05](05-state-machine.md) **step 4** — through the definition body —
  and the materialised tree at **step 4b**; the run reads the knowledge it was pinned to,
  and cannot silently receive different bytes (non-negotiable 6).
- **A knowledge edit does not disturb a live run.** Recompiling produces a new package
  digest and a new definition digest; repointing the agent affects new runs only, and
  in-flight runs resume against their own pinned artifact
  ([`09-decisions.md`](09-decisions.md) §2, reversed after review). Stopping a run on
  dangerous knowledge is cancellation, not a pointer move.
- **Definitions that declare no knowledge digest are unmoved.** The field is absent from
  the canonical body rather than null, so no existing pin changes. The profile itself is
  untouched — [§03](03-canonicalisation.md) §Profile evolution governs a change to the
  canonicalisation *rules*, and adding an optional field to `agent_definition` is not one.

### Materialisation, and the check before the spawn

The compiled package is materialised **read-only** into the run's container before the
driver spawns the harness ([§07](07-adapter-protocol.md), `sdk_subprocess`). The mount
mechanics belong to the sandbox document; two rules belong here. First, **the runtime may
not write to it** — the writable surface is `state_entries`. Second, **the tree that is
read is the tree whose digest was pinned**: **before it spawns the harness**, the driver
walks the materialised tree and the manifest **in both directions** — every manifest path
present with a matching digest, and **no path in the tree that the manifest does not
list** — then digests the manifest projection and compares it with the pinned package
digest. That is non-negotiable 6 — *the artifact that executes is the artifact whose
digest was checked* — one level over. The check sits between sandbox creation and the
harness: the control plane resolves the package digest and verifies the definition artifact
before `Create`, and the driver re-verifies the materialised tree inside the container
**before `Start`** — not the provider ([`15-sandbox.md`](15-sandbox.md) §1,
[§05](05-state-machine.md) step 4b).

Its two failures are `run.knowledge_missing {digest}` and
`run.knowledge_corrupted {digest, path, recomputed}` ([§04](04-events.md) §Pin and compatibility), folding to
`state=failed` with the matching `error_code`, on §04's own reasoning that a distinct
operator remedy earns a distinct event.

| Condition | Outcome |
|---|---|
| No `knowledge_packages` row for the pinned digest | `failed`, `error_code = knowledge_missing` |
| Materialised tree disagrees with its manifest, in either direction | `failed`, `error_code = knowledge_corrupted` |
| Package row's `canon_profile` differs from `agent_definitions.canon_profile` for the pinned definition | `incompatible`, naming the profile ([§03](03-canonicalisation.md) §Profile evolution) |

---

## State — four scopes

Three scopes are rows; the fourth deliberately is not. `state_scope` is
`('app','user','session')` and `temp` is absent from it ([§01](01-schema.md) §Session and
state).

| Scope | `scope_key` | Lifetime | ADK precedent |
|---|---|---|---|
| `app` | `''` | durable, tenant-wide | `app:` |
| `user` | `principals.principal_id` | durable, across sessions | `user:` |
| `session` | `sessions.session_id` | durable, one session | unprefixed, schema-validated |
| `temp:` | **no row** | one run, in the harness process | `temp:` |

ADK is the mechanism's source: `sessions/state.py:64-66 @ 85b52f6`, with the `temp:`
exclusion independently enforced in three backends (`firestore_session_service.py:565`,
`_redis_session_service.py:128,214`) rather than documented — which is why ours is a
`CHECK`, not a convention.

### `temp:` never persists, checked twice

`temp:`-prefixed keys never become rows: they live in the harness process for one run and
are gone on resume. A run may *attempt* a `temp:` write; both guards below refuse it. ADK
pairs the prefix with `ResumabilityConfig`'s
warning that temporary state "will be lost upon resumption"
(`projects/google-agent-platform/teardown.md:94`); the prefix is what makes that warning
actionable at the point of use.

Two independent guards, because non-negotiable 9 requires storage-layer enforcement: the
platform refuses a state-write tool call whose key matches `temp:%` and answers the
adapter with `ToolDenied` ([§07](07-adapter-protocol.md)); `CHECK (key NOT LIKE
'temp:%')` on `state_entries` rejects it anyway, and a `23514` reaching the caller is a
bug that is never retried ([§02](02-consistency.md) §Error mapping, which names this
exact violation).

### Who may write which scope

The harness never writes state directly. A state write is an ordinary
platform-executed tool call — `Output{ToolCall}` out, `ControlFrame{ToolResult}` or
`ControlFrame{ToolDenied}` back ([§07](07-adapter-protocol.md)); spike 06's boundary
holds here exactly as it does for every other tool.

The tool is `state.write` / `state.delete`, declared in the `agent_definition` body's
`tools` array like any other binding ([§03](03-canonicalisation.md) §`tool_binding`), so
an agent that writes state says so in its pinned definition. It takes the full
[§07](07-adapter-protocol.md) handshake — pinned-definition check, Cedar, intent, claim,
dispatch, settle — because the boundary is the same one spike 06 verified for every other
tool.

A state write is an **internal** effect, not an `Action` against a `Resource`: it gets an
`effect_ledger` row with `kind = 'state_write'` ([§01](01-schema.md) §Effect ledger) and produces **no**
`actions` row. `10-work-bundles.md`'s `effect_class` classifies external operations, and
`:187-188,:217` require a registry `Resource` and an `external_idempotency_token` that an
internal write has neither of.

| Scope | A run may write | Rule |
|---|---|---|
| `app` | **not at all** for a `kind='agent'` principal in v0.1 | refused at the tool boundary with `ToolDenied{SCOPE_FORBIDDEN}` |
| `user` | `scope_key ∈ {self, parent}` | **amended 2026-08-30 (OQ-123):** `self` is `runs.created_by`, unchanged; `parent` is `principals.on_behalf_of` for that principal — the run's delegation parent, Letta's `{self, parent}` cross-agent guard. Any other `scope_key`, including a grandparent, is refused |
| `session` | the run's own session only | `scope_key = runs.session_id`; refused when it is NULL |

The `app` refusal is a **platform rule, not a Cedar verdict**. **Amended 2026-08-30 (OQ-079),
superseding "a refusal that names no policy cannot be recorded as `policy.evaluated` … It is
recorded as the `ToolDenied` on the run's log":** `policy_decisions.policy_id`'s `NOT NULL` FK
to `policies` ([§01](01-schema.md) §Policy) is satisfied by the reserved, per-tenant-seeded
`platform:app_scope_deny` row ([§01](01-schema.md), the platform-rule seeding amendment) —
the refusal is recorded as `policy.evaluated` ([§04](04-events.md) §Policy) against that row,
in addition to the `ToolDenied` on the run's log.

Cedar decides `deny | steer | observe` ([§01](01-schema.md) §Policy) and has no `allow`
value, so a *grant* cannot be expressed in v0.1 — the default-deny is a platform rule, and
widening it needs a policy decision value the enum does not have.

`app` defaults to deny because a shared namespace without permissions is a known defect,
not a hypothetical one: LangGraph's store namespaces "look like an isolation boundary and
are not one" (`libs/checkpoint/langgraph/store/base/__init__.py:708,545 @ 3803173`,
ADR-0008 evidence log), while Letta's cross-agent memory guard is kernel-enforced and
fail-closed (`src/memory-confinement.ts:14-21 @ 852ca24`). A state write that a Cedar policy
evaluates is recorded like any other evaluation ([§04](04-events.md) `policy.evaluated`); a
platform-rule refusal is recorded as a denial, so a refusal is never indistinguishable from
silence (non-negotiable 10). Reads take the same boundary and the same three rules: a read outside them is `ToolDenied`
([§07](07-adapter-protocol.md)), never an empty `ToolResult`, because "no rows" and "not
allowed" must not be indistinguishable (non-negotiable 10, refusals are as observable as
successes).

**Session scope binds through `runs.session_id`.** `runs` carries a nullable `session_id`
with a composite FK to `sessions` ([§01](01-schema.md) §Run, §Session and state), so a run
names the session whose state it may touch. A run with `session_id IS NULL` may reach only
`app` and `user` scope, and a `session`-scoped write from it is `ToolDenied`.

### Validating the run's own state

ADR-0008's amended rules require the run's own state to be validated against a declared
schema while the shared namespaces stay open — ADK raises `StateSchemaError` for an
undeclared or mistyped key in unprefixed state and deliberately exempts prefixed ones. The
declaration is a `state_schema` field of the agent definition body, included in the
`agent_definition` digest ([§03](03-canonicalisation.md) §`agent_definition`). It constrains
`session` scope only; `app` and `user` stay open, because they are shared and a run does
not own their contract. An undeclared or mistyped `session` key is refused with
`ToolDenied`.

### Transactionality

The dispatch transaction ([§02](02-consistency.md) phase 4) writes the row and appends its
log event together — `state.written {scope, scope_key, key, value_digest}`, with
`state.deleted {scope, scope_key, key}` for a removal ([§04](04-events.md) §State),
neither folding onto `runs.state` — so a crash cannot leave a state
mutation the log cannot explain (non-negotiable 7, MAF: only committed state is
checkpointed). The fenced settle is phase 5. A crash after dispatch and before settle
leaves the mutation logged and the effect `claimed`, which is exactly the `indeterminate`
path of [§05](05-state-machine.md). The write is an upsert; concurrent writers to one
key serialise on the row. The event carries the **digest** of the value, not the value:
the row is the value, and a state payload may be large or sensitive. ADK's answer to
concurrent state writes is decomposition rather than locking
(`projects/google-agent-platform/teardown.md:380`), and scoping is that decomposition —
it shrinks the surface where a conflict is possible instead of resolving conflicts.

### Retrieval authorisation

**Amended 2026-08-30 (OQ-103): owner named, one paragraph, not the full design — to be
written before the analytics pack.** [`12-harness.md`](12-harness.md) §8 constrains *which*
package nodes may enter context (rule 3, the closure and the always-resident set) but not
*who* may see a node's content once it is admitted; spike 04 names this the largest untested
area in the study. The shape this document owes before the analytics pack: a Cedar `read`
decision over the node's `classification` (the same field `10-work-bundles.md`'s `Resource`
already carries for a different noun) filters the closure **before** content reaches the
model or an embedding index — not after, and not as a second veto on top of rule 3, but as a
precondition rule 3's admission check also evaluates. The full policy shape — what principal,
what classification levels, what the refusal looks like on a `system/**` file the run cannot
function without — is deliberately not decided here.

---

## Schema

```sql
-- Content-addressed and immutable, exactly like agent_definitions: the digest IS
-- the key, and there is no UPDATE path.
CREATE TABLE knowledge_packages (
    tenant_id      BIGINT NOT NULL,
    digest         TEXT   NOT NULL,      -- kind 'knowledge_package' (03)
    manifest       JSONB  NOT NULL,      -- [{path, digest}], sorted by path — exactly
                                         -- the digested projection
    canon_profile  TEXT   NOT NULL,      -- e.g. 'nfc+intjson/v1'
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, digest),
    CHECK (digest ~ '^[0-9a-f]{64}$')
);

-- Amended 2026-08-30 (OQ-081, owner override): 'team' and 'persona' added between
-- 'tenant' and 'agent'.
CREATE TYPE knowledge_layer AS ENUM ('bundle', 'tenant', 'team', 'persona', 'agent');

-- The git-backed layers we register. The `bundle` layer is NOT here: it arrives with
-- the pinned WorkBundle (spec 10), so the enum value exists only for the manifest.
CREATE TABLE knowledge_sources (
    tenant_id      BIGINT NOT NULL,
    source_id      TEXT   NOT NULL,
    layer          knowledge_layer NOT NULL,
    agent_id       TEXT,                 -- NULL unless layer = 'agent'
    -- Added 2026-08-30 (OQ-081): a principal-group id and a role label, both
    -- uninterpreted TEXT -- new nouns with no resource of their own in v0.1, the
    -- same shape state_entries.scope_key takes (01 exception 1).
    team_id        TEXT,                 -- NULL unless layer = 'team'
    persona_key    TEXT,                 -- NULL unless layer = 'persona'
    git_remote     TEXT   NOT NULL,
    commit_sha     TEXT   NOT NULL,
    subpath        TEXT   NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, source_id),
    FOREIGN KEY (tenant_id, agent_id) REFERENCES agents (tenant_id, agent_id),
    CHECK (layer IN ('tenant','team','persona','agent')),
    CHECK ((layer = 'agent') = (agent_id IS NOT NULL)),
    CHECK ((layer = 'team') = (team_id IS NOT NULL)),
    CHECK ((layer = 'persona') = (persona_key IS NOT NULL)),
    CHECK (commit_sha ~ '^[0-9a-f]{40}$'),
    -- one source per layer per agent/team/persona; NULLS NOT DISTINCT (PG15+, within
    -- 01's PG16 floor) makes the tenant-layer NULLs collide
    UNIQUE NULLS NOT DISTINCT (tenant_id, layer, agent_id, team_id, persona_key)
);

-- Provenance, append-only. Two compilations may produce the SAME package digest from
-- different commits — the point of excluding commit_sha — so it is keyed by
-- compilation, never by package.
CREATE TABLE knowledge_compilations (
    tenant_id       BIGINT NOT NULL,
    compilation_id  TEXT   NOT NULL,     -- sortable ULID
    package_digest  TEXT   NOT NULL,
    bundle_id       TEXT   NOT NULL,     -- spec 10's WorkBundle
    bundle_revision TEXT   NOT NULL,     -- its revision
    sources         JSONB  NOT NULL,     -- [{source_id, commit_sha}]
    resolution      JSONB  NOT NULL,     -- [{path, layer, source_id}] — per-path
                                         -- provenance, kept out of the digested row
    compiled_by     TEXT   NOT NULL,
    compiled_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, compilation_id),
    FOREIGN KEY (tenant_id, package_digest)
        REFERENCES knowledge_packages (tenant_id, digest),
    FOREIGN KEY (tenant_id, compiled_by)
        REFERENCES principals (tenant_id, principal_id)
);
```

```sql
GRANT SELECT, INSERT ON knowledge_packages TO app_role;      -- immutable artifacts
GRANT SELECT, INSERT ON knowledge_compilations TO app_role;  -- append-only
GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_sources TO app_role;
```

The grants are the mechanism, not the comments ([§01](01-schema.md) §Grants required).

`bundle_id` and `bundle_revision` are columns and not a foreign key on purpose:
`10-work-bundles.md` owns the `WorkBundle` resource, and the composite FK lands when that
table does.

Both are registered in [§01](01-schema.md)'s enumerated exception list as of 2026-08-30 —
exception 4 for the JSON-array membership the compiler checks and the database does not (the
same shape as `channel_envelopes.audience`), exception 5 for the FK-less
`bundle_id` / `bundle_revision` with that FK named as its closing condition — so the promise
that the exceptions are stated rather than hidden keeps holding.

The registration path is [§06](06-api.md)'s `POST /v1/knowledge-packages` and
`GET /v1/knowledge-packages/{digest}`, and `POST /v1/definitions` carries the optional
`knowledge_package_digest` and `state_schema` that §Digest participation reads (added
2026-08-30, mirrored in `spec/contracts/openapi.yaml`).

## Tests, with negative controls

Per [`../spikes/VERIFICATION-RULES.md`](../spikes/VERIFICATION-RULES.md): through the
public boundary, each with a control proving the test fails when its guard is removed.

| Invariant | Test | Negative control |
|---|---|---|
| Layer precedence is agent > persona > team > tenant > bundle (**amended 2026-08-30, OQ-081**, superseding "agent > tenant > bundle") | same path in all five layers; read the compiled bytes | reverse the overlay ⇒ the bundle file wins |
| Compilation is deterministic | compile the same five layers (**amended 2026-08-30, OQ-081**, superseding "the same three layers") in two processes, compare digests | emit files in filesystem order ⇒ digests differ across machines |
| A commit that changes no bytes changes no digest | recommit identical content, recompile | put `commit_sha` in the digest payload ⇒ the digest moves and pins break |
| A knowledge edit does not move a pinned run | edit one file, recompile, repoint the agent, resume the run | compare against `agents.current_digest` ⇒ the run refuses to resume on a cosmetic edit (the behaviour `09-decisions.md` §2 reversed) |
| Definitions declaring neither new field are unchanged | recompute a stored definition digest after both fields are added | serialise either as `null` ⇒ every existing pin breaks |
| The tree read is the tree pinned | corrupt one materialised file before the spawn | skip the pre-spawn verification ⇒ the run executes unpinned content |
| An unlisted file cannot be smuggled into the tree | materialise the package, add one file absent from the manifest, start the run | check only manifest→tree ⇒ the extra file is readable by the run |
| A missing package fails before the spawn | pin a definition whose `knowledge_package_digest` has no row | skip the lookup ⇒ the harness spawns with an empty knowledge mount |
| A node carrying both a content and an executable role is rejected | compile a bundle with `roles = {knowledge, executable}` | admit it on the content role ⇒ an executable body is materialised into the model-readable mount |
| A compilation cannot name a source outside its tenant | insert a compilation whose `sources[]` names another tenant's `source_id` | drop the compiler's membership check ⇒ it inserts, because no FK exists |
| The knowledge mount is read-only to the runtime | from inside the run, open a manifest path `O_WRONLY` and a new path under the package root | mount it read-write ⇒ the write succeeds and the tree stops matching its manifest |
| `system/**` is never silently dropped ([§12](12-harness.md) §8's always-resident set) | compile a package whose `system/` tree exceeds the context budget, start a run | drop the overflow files instead ⇒ the run proceeds on partial system knowledge with no signal |
| A `temp:` write never persists | write `temp:x` through the tool boundary | drop the boundary refusal ⇒ the `CHECK` catches it; drop both ⇒ it persists |
| Cross-principal `user` write is refused | run owned by A writes `scope_key = B`, where B is not A's `on_behalf_of` delegation parent (**amended 2026-08-30, OQ-123**, superseding "run owned by A writes `scope_key = B`") | drop the scope check ⇒ it succeeds |
| A forbidden read is refused, not empty | read `user` state for a principal that is neither `runs.created_by` nor its `on_behalf_of` parent (**amended 2026-08-30, OQ-123**, superseding "a principal that is not `runs.created_by`": a `parent` read is now permitted, so the old input would wrongly assert a refusal) | return an empty `ToolResult` instead of `ToolDenied` ⇒ "no rows" and "not allowed" are indistinguishable (non-negotiable 10) |
| `app` write by an agent principal is denied by default | agent-owned run writes `app` scope with no allow policy | default to allow ⇒ one run rewrites tenant-wide state |
| An undeclared `session` key is refused | write a key absent from `state_schema` | skip validation ⇒ a typo becomes durable state |
| State write and log event are atomic | crash between them | commit them separately ⇒ a mutation with no log record |
| Case-colliding paths are rejected | two layers supply `A.md` and `a.md` | accept them ⇒ the materialised tree disagrees with its manifest |
| NFC-colliding paths are rejected | two layers supply the same path in NFC and NFD form | accept them ⇒ one file silently overrides the other with no diff |

## What this does not guarantee

- **No compare-and-set on state.** Two runs writing one key serialise on the row and the
  later write wins; scoping shrinks the surface rather than resolving a conflict.
- **No deletion across layers.** A higher layer replaces a path, never removes it.
- **No agent-authored knowledge.** Letta's model — an agent editing its own git-backed
  memory with a required `reason` on every mutation — is precedent v0.1 has not adopted.
- **No semantic retrieval.** `Recall` is deferred; a package is files and a manifest, with
  no index and no relevance ranking.
- **No access control *inside* a package.** Every file materialised for a run is readable
  by that run; retrieval filtering before content reaches a model or an embedding index is
  spike 04's own largest untested area (§Not tested).
- **No freshness.** A `resource_descriptor` pins a contract; whether the system it
  describes is current is evidence gathered elsewhere (spike 04, finding 2).
