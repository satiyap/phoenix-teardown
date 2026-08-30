# 14 — Credential, exchanger, refresher
<!-- status: draft -->

What an action carries **outward**, and why none of it is ever inside the sandbox. This is
the second half of ADR-0007: [§01](01-schema.md) settles `Principal` (who is acting), and
this settles the `Credential` resource, the three named flows a token is obtained through,
how delegation depth is set and capped, the separation of the `Exchanger` from the
`Refresher`, and the secretless egress contract that keeps material out of the container.

**What it deliberately does not settle.** The egress proxy's *placement* is
[§15](15-sandbox.md)'s and is already settled there — **one proxy deployment per tenant
data plane** ([`15-sandbox.md`](15-sandbox.md) §5 Placement); this states only the contract that boundary
must honour. The platform's own model-provider keys are out of scope: not held by a tenant
principal, not `credentials` rows. They necessarily traverse the same proxy — §15's egress
policy admits one destination and no second path ([`15-sandbox.md`](15-sandbox.md) §3
Pod-spec constraints and §5 Placement) —
but whether they ride this document's **rewrite table** or the proxy's own configuration is
**unknown — OQ**.

It also does not settle: the mapping of the three flows onto RFC 6749/8693 grant types (the
`Exchanger` interface is ours, the grant is the implementation's, and the interactive half
is blocked on the consent OQ below); the admin HTTP surface, [§06](06-api.md)'s and its
OpenAPI contract's, subject to the constraint that no route may return `secret_ref`,
`material_ref` or any placeholder value; and the `credential.exchanged` /
`credential.refreshed` / `credential.placeholder_rejected` rows, which belong to
[§04](04-events.md)'s closed set.

**A word collides, so it is named here.** [§06](06-api.md)'s *credential class*
(`agent | admin`) is what a **northbound token** may do; this document's `Credential` is
southbound material an agent presents to a customer system. They are different subsystems
and this document specifies only the southbound half. §06's create route refuses a
`credentials` row whose `egress_host` names a control-plane host —
`422 credential_targets_control_plane`, added 2026-08-30 — which is what turns this
document's "a credential cannot be minted against the control plane" from prose into a
refusal something performs.

---

## The resource

`Credential` is a tenant-scoped resource held by a `Principal` of kind `agent` or `service`
— the *workload identity* of DESIGN §4.4, for which AgentCore is the reference shape
(`projects/aws-agentcore/teardown.md:120-131 @ 826416a`). ADK has the credential half and
no principal at all (`projects/google-agent-platform/teardown.md:240-242 @ 85b52f6`).

```sql
CREATE TYPE credential_kind AS ENUM
    ('api_key', 'http', 'oauth2', 'oidc', 'service_account');

-- The three flows, named. `as_itself` is AgentCore's `M2M`.
CREATE TYPE credential_flow AS ENUM
    ('as_itself', 'user_federation', 'on_behalf_of_token_exchange');

CREATE TABLE credentials (
    tenant_id      BIGINT NOT NULL,
    credential_id  TEXT   NOT NULL,
    name           TEXT   NOT NULL,
    kind           credential_kind NOT NULL,
    flow           credential_flow NOT NULL,
    scheme         TEXT   NOT NULL,        -- OpenAPI-derived, e.g. 'bearer' (ADK)
    issuer         TEXT   NOT NULL,        -- the authority that mints the token
    audience       TEXT   NOT NULL,
    -- The ONE host the proxy may present this to: a credential valid everywhere
    -- is one the leak guard below cannot bind.
    egress_host    TEXT   NOT NULL,
    scopes         TEXT[] NOT NULL DEFAULT '{}',
    -- the FK PINS the kind, as approvals.decided_by pins 'human' in §01
    held_by        TEXT   NOT NULL,
    held_by_kind   principal_kind NOT NULL
                   CHECK (held_by_kind IN ('agent', 'service')),
    -- policy's cap, written by an admin route; 0 means this credential delegates
    -- nothing. The CHECK is the ceiling policy cannot raise (§01).
    max_delegation_depth SMALLINT NOT NULL DEFAULT 0
                   CHECK (max_delegation_depth BETWEEN 0 AND 8),
    secret_ref     TEXT   NOT NULL          -- the CLIENT secret, by reference only
                   CHECK (secret_ref LIKE 'kms://%'),
    revoked_at     TIMESTAMPTZ,            -- revocation is a STATE, not a DELETE
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (tenant_id, credential_id),
    UNIQUE (tenant_id, name),
    -- lets a placeholder put the host INSIDE its foreign key (below)
    UNIQUE (tenant_id, credential_id, egress_host),
    FOREIGN KEY (tenant_id, held_by, held_by_kind)
        REFERENCES principals (tenant_id, principal_id, kind),

    -- acting as itself is not delegation
    CHECK (flow <> 'as_itself' OR max_delegation_depth = 0)
);
```

**A credential is never an identity.** ADR-0007's amendment names the failure that rule
prevents: treating possession of a key as proof of identity is what makes an agent reading
IMDS *become* the instance. No `credentials` row may stand where a `principals` row belongs.

### Issued material has its own lifetime

`credential_issuances` is not a new noun: it is the Credential's material, given a row of
its own because the material expires and the resource does not.

```sql
CREATE TABLE credential_issuances (
    tenant_id      BIGINT NOT NULL,
    issuance_id    TEXT   NOT NULL,
    credential_id  TEXT   NOT NULL,
    flow           credential_flow NOT NULL,
    -- on whose behalf. NULL for as_itself and ONLY for as_itself; this FK pins NO
    -- kind, because a chain may pass through an agent.
    subject_principal_id TEXT,
    -- set BY THE AUTHORITY (us), never by the caller; see the trigger below
    delegation_depth SMALLINT NOT NULL DEFAULT 0
                     CHECK (delegation_depth BETWEEN 0 AND 8),
    material_ref   TEXT   NOT NULL CHECK (material_ref LIKE 'kms://%'),
    obtained_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL,
    refreshed_at   TIMESTAMPTZ,
    refresh_count  INTEGER NOT NULL DEFAULT 0,
    superseded_at  TIMESTAMPTZ,
    revoked_at     TIMESTAMPTZ,

    PRIMARY KEY (tenant_id, issuance_id),
    FOREIGN KEY (tenant_id, credential_id)
        REFERENCES credentials (tenant_id, credential_id),
    FOREIGN KEY (tenant_id, subject_principal_id)
        REFERENCES principals (tenant_id, principal_id),
    CHECK ((flow = 'as_itself') = (subject_principal_id IS NULL)),
    CHECK ((flow = 'as_itself') = (delegation_depth = 0)),
    -- lets a placeholder bind (issuance, credential) TOGETHER, so it cannot bind
    -- an issuance of a DIFFERENT credential
    UNIQUE (tenant_id, issuance_id, credential_id)
);

-- At most one live issuance per (credential, subject): an exchange is NOT idempotent,
-- so a retry storm mints a token per attempt unless the database says otherwise.
-- NULLS NOT DISTINCT needs PostgreSQL 15; the floor is 16+ (spec/02-consistency.md:12-19).
CREATE UNIQUE INDEX credential_issuance_live
    ON credential_issuances (tenant_id, credential_id, subject_principal_id)
    NULLS NOT DISTINCT
    WHERE superseded_at IS NULL AND revoked_at IS NULL;
```

The index does **not** treat expiry as retirement: an expired issuance still holds the
slot. An `Exchanger` that finds one therefore sets its `superseded_at` and inserts the
replacement **in one transaction**; a replacement outside that transaction raises `23505`,
and under contention the loser BLOCKS first and only receives it once the winner commits
(`spikes/03-postgres/RESULT.md`:37-45), so a `statement_timeout` is mandatory here too.

## Delegation depth — incremented by the authority, capped by policy

`principals.delegation_depth` (§01) is incremented by us and capped at 8 in a `CHECK`, "so
a runaway delegation chain is rejected by the database rather than by policy code that might
not run". One level down, an issuance's depth is likewise computed, never accepted.

```sql
CREATE FUNCTION check_issuance_depth() RETURNS trigger AS $$
DECLARE subj SMALLINT; cap SMALLINT;
BEGIN
  IF NEW.flow = 'as_itself' THEN RETURN NEW; END IF;
  -- retiring an issuance is not a re-authorisation, so it is not blocked by the
  -- subject or credential it retires
  IF TG_OP = 'UPDATE'
     AND (NEW.revoked_at IS NOT NULL OR NEW.superseded_at IS NOT NULL)
  THEN RETURN NEW; END IF;

  SELECT p.delegation_depth, c.max_delegation_depth INTO subj, cap
    FROM principals p, credentials c
   WHERE p.tenant_id = NEW.tenant_id AND p.principal_id = NEW.subject_principal_id
     AND c.tenant_id = NEW.tenant_id AND c.credential_id = NEW.credential_id
     AND p.revoked_at IS NULL AND c.revoked_at IS NULL;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'subject % or credential % is absent or revoked in tenant %',
      NEW.subject_principal_id, NEW.credential_id, NEW.tenant_id
      USING ERRCODE = 'invalid_parameter_value';       -- 22023, as in §01
  END IF;
  -- ASSIGNED, not compared: the caller states no depth and cannot state one
  NEW.delegation_depth := subj + 1;
  IF NEW.delegation_depth > cap THEN
    RAISE EXCEPTION 'delegation depth % exceeds the cap % on credential %',
      NEW.delegation_depth, cap, NEW.credential_id
      USING ERRCODE = 'invalid_parameter_value';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

-- UPDATE OF, not bare UPDATE: it governs the four columns that decide a depth, so
-- a refresh and a retirement do not re-run a check they cannot pass.
CREATE TRIGGER credential_issuances_depth_check
  BEFORE INSERT OR UPDATE OF flow, credential_id, subject_principal_id, delegation_depth
  ON credential_issuances
  FOR EACH ROW EXECUTE FUNCTION check_issuance_depth();
```

Two caps, deliberately: `max_delegation_depth` is what policy set, the column `CHECK` is
the ceiling policy cannot raise, so a policy that fails to evaluate cannot uncap a chain.
`USING ERRCODE` is not cosmetic, for the reason §01 gives — a bare `RAISE` is `P0001` and
indistinguishable from any other trigger failure. The trigger fires at issuance time only;
a subject revoked *after* it is caught at the swap instead (§Revocation).

**`ON_BEHALF_OF_TOKEN_EXCHANGE` is a flow, not a flag.** AgentCore names it alongside
`M2M` and `USER_FEDERATION` in one literal (`projects/aws-agentcore/teardown.md:79-80,240
@ 826416a`), for the reason its teardown records: delegation is not a special case of
login, and a boolean would put an exchange and a login on one code path.

**Consent is not modelled here.** AgentCore drives `USER_FEDERATION` through a browser
consent with an `on_auth_url` callback, a poller, and `custom_state` for callback
validation (`projects/aws-agentcore/teardown.md:156-160 @ 826416a`). Where an interactive
consent surfaces in the run state machine is **unknown — OQ**: `waiting_input → running`
requires a terminal `approvals` row ([§05](05-state-machine.md)), and consent is not
approval. Any callback we implement **must** carry the equivalent of `custom_state`.

## Exchanger and Refresher are separate components

ADK ships `BaseCredentialExchanger` and `BaseCredentialRefresher` as **separate registries
behind separate interfaces** (`projects/google-agent-platform/teardown.md:224-239 @
85b52f6`) because obtaining a credential and keeping it alive have different failure modes,
and conflating them pushes refresh onto every tool author. That rule, made normative:

| Rule | Statement |
|---|---|
| E1 | An **Exchanger** is selected by `(kind, flow)`; a **Refresher** by `kind` alone — a flow is a property of obtaining, not of renewing, and E3 below is what makes that safe: a renewal that would change the flow is an exchange. The keys are ours, because ADK has no flow. |
| E2 | A Refresher **may not create an issuance**. No live row means an exchange is owed, and an exchange re-evaluates policy, subject and depth; a Refresher that could mint one would perform an unpoliced delegation. |
| E3 | A refresh **preserves** `flow`, `subject_principal_id`, `scopes` and `delegation_depth`. A renewal that would change any of them is an exchange and must be performed as one. |
| E4 | Neither returns material to its caller. Both write `material_ref` and `expires_at`; plaintext exists only in the **Exchanger's or Refresher's** memory and the egress proxy's rewrite table. |
| E5 | Both run **outside** the effect's claim window (below). |

### Exchange and refresh run before the claim, never under it

[§02](02-consistency.md) splits an effect into intent, approval, claim, dispatch, settle,
and a `claimed` row whose lease expires unsettled is `indeterminate` — terminal, and routed
to a human. A token request is a call to somebody else's identity provider, with unbounded
latency; performing one under a lease turns a slow provider into a human escalation.

Normative ordering, before the claim of any effect that will present a credential:

```
1. INTENT (§02 phase 1) writes the effect_ledger row
2. APPROVAL (§02 phase 2), if policy requires it, completes
3. resolve the Credential and the live issuance
4. if expires_at <= now + interval '5 minutes' + headroom -> Refresher.renew()
5. if no live issuance                                    -> Exchanger.obtain()
6. THEN claim (§02 phase 3)
7. mint the placeholder, bound to the CLAIMED effect       (below)
8. dispatch
```

Steps 3–5 run **after** approval, so a token is not minted against a decision a human has
not yet made, and **before** the claim, so provider latency is never under a lease. Five
minutes is §02's effect lease (`spec/02-consistency.md` §Claiming and performing an effect); the headroom above it is
**unknown — OQ**, no evidence in the repo fixing a provider's token-exchange latency. The
mint is step 7, *after* the claim: a local `INSERT` with no provider latency, so it does
not reintroduce the risk steps 3–5 avoid, and a worker that loses the claim race or is
fenced out of the run (`spec/02-consistency.md` §Claiming and performing an effect, phase 3) holds no placeholder.

A failure at step 4 or 5 is refused **before** the claim at step 6, so it leaves no claimed
row and can never be reported as `indeterminate`. The intent moves to `abandoned`
(`spec/02-consistency.md` §Denial, expiry, abandonment) carrying `error_code`; `failed` is unreachable, because
§01's `effect_claim_fields_together` admits it only for a row that holds a claim owner,
token and lease (`01-schema.md` §Effect ledger).

## Credentials never enter the sandbox

Injecting a real token into a sandbox "defeats much of the point of the sandbox", because
any code the agent was tricked into running "can read the token out of `os.environ` /
`~/.gitconfig` and exfiltrate it" (`projects/omnigent/teardown.md:365-390 @ ba9e371`).
Omnigent's secretless proxy is the only design in the study where a sandboxed agent
authenticates without ever holding a secret, and it is ported here.

The contract [§15](15-sandbox.md) must honour, stated as obligations:

| # | Obligation |
|---|---|
| 1 | **No secret material crosses the frame boundary.** No [§07](07-adapter-protocol.md) frame has a typed credential field, so nothing in the protocol *asks* for one; the platform is additionally forbidden to place credential material in the opaque byte fields §07 does define (`Start.config` `spec/07-adapter-protocol.md`:52, `Input.data` :68, `Opaque.data` :129). The first half is structural; the second is the obligation, and the test row below is what checks it. |
| 2 | **The proxy injects on the way out for a platform-executed effect**, keyed by the `effect_ledger` row the dispatch carries; it holds the rewrite table, resolves `material_ref` through KMS, and sets `Authorization` outbound. The sandbox sends no credential. |
| 3 | **A client the platform's tool executor runs on behalf of a platform-executed effect, which refuses to make a request without seeing a credential, gets a placeholder**: random, single-use, host-bound, swapped at the proxy for the real secret. The executor is outside the sandbox (spike 06: the harness never executes a tool), so the placeholder does not cross the frame boundary either; the in-sandbox case is out of scope — see §What this does not guarantee. |
| 4 | **Leak guard.** A placeholder presented for a host it is not bound to is `403`, as is any unknown value of placeholder shape. Replay against an attacker's host attaches nothing. |
| 5 | **No clobbering.** An `Authorization` header the client set itself is forwarded untouched. |
| 6 | **The metadata blocklist is not negotiable** (ADR-0009 amendment), including the public `168.63.129.16` no private-range check would catch. A proxy that holds secrets while its sandbox can reach IMDS has isolated nothing. |

`credential_placeholders` is not a new noun either: it is the rewrite table's durable half,
given rows because the leak guard's three properties — host binding, single use, and the
ledger tie — are constraints and not conventions
(`projects/omnigent/teardown.md:377-387 @ ba9e371`).

```sql
CREATE TABLE credential_placeholders (
    tenant_id      BIGINT NOT NULL,
    placeholder    TEXT   NOT NULL,        -- opaque random; shape is recognisable
    credential_id  TEXT   NOT NULL,
    issuance_id    TEXT   NOT NULL,
    run_id         TEXT   NOT NULL,
    effect_key     TEXT   NOT NULL,        -- the effect_ledger row it serves
    host           TEXT   NOT NULL,        -- the ONE host it may be presented to
    issued_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- bounded by the issuance's expiry; the swap re-checks it, no FK can compare
    -- columns across tables
    expires_at     TIMESTAMPTZ NOT NULL,
    consumed_at    TIMESTAMPTZ,

    PRIMARY KEY (tenant_id, placeholder),
    FOREIGN KEY (tenant_id, issuance_id, credential_id)
        REFERENCES credential_issuances (tenant_id, issuance_id, credential_id),
    -- the host is IN the FK: no placeholder for a host the credential is not valid for
    FOREIGN KEY (tenant_id, credential_id, host)
        REFERENCES credentials (tenant_id, credential_id, egress_host),
    -- run_id is IN the FK, so a placeholder cannot serve an effect of another run
    FOREIGN KEY (tenant_id, effect_key, run_id)
        REFERENCES effect_ledger (tenant_id, idempotency_key, run_id),
    CHECK (placeholder ~ '^ph_[0-9a-f]{32}$')
);

CREATE INDEX credential_placeholders_live
    ON credential_placeholders (tenant_id, expires_at) WHERE consumed_at IS NULL;

-- Step 7 runs once per effect, not once per racing worker: without this, N workers
-- racing one ledger row mint N individually-single-use placeholders for it.
CREATE UNIQUE INDEX credential_placeholders_one_live
    ON credential_placeholders (tenant_id, effect_key) WHERE consumed_at IS NULL;
```

`effect_key` is `NOT NULL` on purpose: [§07](07-adapter-protocol.md) requires that nothing
reach a customer system without an `effect_ledger` row, and depending on one turns that
rule into a foreign key. Obligation 2's injection path mints no placeholder, so the proxy
keeps the same rule there by keying the rewrite entry on the dispatch's `idempotency_key`
rather than on host; the invariant row below checks it. The recognisable shape is
Omnigent's — it lets the guard reject an unknown value of that shape instead of forwarding.

**Consumption is a conditional `UPDATE`, not a read-then-act check.** Spike 01 proved
read-then-act double-executes (`['w1','w2']`), and the lesson is the same primitive here:

```sql
UPDATE credential_placeholders SET consumed_at = now()
 WHERE tenant_id = $1 AND placeholder = $2
   AND host = $3 AND consumed_at IS NULL AND expires_at > now()
   -- the effect must still be CLAIMED: a placeholder minted for an effect that was
   -- denied, abandoned or lost to another worker swaps for nothing
   AND EXISTS (SELECT 1 FROM effect_ledger e
                WHERE e.tenant_id = credential_placeholders.tenant_id
                  AND e.idempotency_key = credential_placeholders.effect_key
                  AND e.run_id = credential_placeholders.run_id
                  AND e.status = 'claimed')
   AND EXISTS (SELECT 1 FROM credential_issuances i
                JOIN credentials c
                  ON c.tenant_id = i.tenant_id AND c.credential_id = i.credential_id
                JOIN principals p
                  ON p.tenant_id = c.tenant_id AND p.principal_id = c.held_by
               WHERE i.tenant_id = credential_placeholders.tenant_id
                 AND i.issuance_id = credential_placeholders.issuance_id
                 AND i.credential_id = credential_placeholders.credential_id
                 AND i.revoked_at IS NULL AND i.superseded_at IS NULL
                 AND i.expires_at > now()
                 AND c.revoked_at IS NULL
                 AND p.revoked_at IS NULL
                 -- the SUBJECT, not only the holder: a user deprovisioned after the
                 -- exchange must not keep a working delegated token
                 AND NOT EXISTS (SELECT 1 FROM principals sp
                                  WHERE sp.tenant_id = i.tenant_id
                                    AND sp.principal_id = i.subject_principal_id
                                    AND sp.revoked_at IS NOT NULL))
RETURNING credential_id, issuance_id;
```

The revocation predicates are IN the statement, not in a read before it, or a revoked
credential keeps working until its material expires. The holder join is an inner `JOIN`: a
missing principal row must fail the guard, not pass it. Zero rows is a `403` whatever the
reason, and the proxy does not distinguish them to the caller.

### The driver holds only `run_token`

`sdk_subprocess` means the Go driver is PID 1 of the run's container and spawns the Python
harness as a child ([§07](07-adapter-protocol.md) §Transport, amended 2026-08-29 after
spike 05 T2), and a child inherits its parent's environment. The driver therefore holds no
secret but `run_token`: no credential env var, no mounted secret file, no KMS decrypt grant
on the container's identity. A credential mounted for the driver's convenience is one the
harness reads out of `/proc/1/environ`.

## Storage: a KMS reference, never a column

No table here has a column able to hold plaintext: `credentials.secret_ref` and
`credential_issuances.material_ref` are `kms://` URIs constrained by `CHECK`. The
application role has no decrypt authority — that belongs to the Exchanger and the egress
proxy, neither of which is the database.

```sql
GRANT SELECT, INSERT, UPDATE
   ON credentials, credential_issuances, credential_placeholders TO app_role;
```

No `DELETE`, following §01's grants discipline (`01-schema.md` §Grants required): revocation is
a state, so a row recording what a credential could reach is never removable by the
application role.

Which KMS, the envelope format, and whether the key is per tenant are **unknown — OQ**.

## Revocation

Revocation is credential-level, following the only project that ships it: AgentCore
revokes by deleting the credential provider, so "you can revoke what an agent can reach,
not the agent itself" (`projects/aws-agentcore/teardown.md:140-148 @ 826416a`). Agent-level
revocation is not a v0.1 shipment ([§09](09-decisions.md) 2).

- `credentials.revoked_at` stops exchange, refresh and swap: exchange and refresh read it,
  and the swap statement above carries it as a predicate. Live issuances are marked
  `revoked_at` in the same transaction. Whether the KMS material is destroyed or merely
  orphaned depends on the KMS, which is **unknown — OQ** (see §Storage).
- A revoked **principal** is equally fatal: the depth trigger refuses an issuance whose
  subject is revoked, and the proxy refuses a swap for a credential held by a revoked
  principal **or issued on behalf of one**.
- Neither is a `DELETE`. The rows are the record of what the credential could reach.

---

## Tests, with negative controls

Per [`../spikes/VERIFICATION-RULES.md`](../spikes/VERIFICATION-RULES.md): every row is
tested through the public boundary, with a control proving it fails when the guard is gone.

| Invariant | Test | Negative control |
|---|---|---|
| No secret reaches the sandbox | run an agent whose tool authenticates; grep the container's env, mounts and every §07 frame — `Start.config`, `Input.data`, `Opaque.data` included — for the material | inject the token as an env var ⇒ the grep finds it |
| A placeholder is host-bound | present a valid placeholder to a second host | drop the `host` predicate ⇒ the swap succeeds and the attacker's host receives a real credential |
| A placeholder is single-use | replay a consumed placeholder against its bound host | swap the conditional `UPDATE` for read-then-act, N presenters ⇒ N swaps |
| An unknown placeholder-shaped value is refused | present `ph_` + 32 random hex | drop the shape guard ⇒ it is forwarded upstream |
| A credential cannot be used outside a ledgered effect | mint a placeholder for a non-existent `effect_key` | drop the composite FK ⇒ a credential is used with no ledger row |
| A placeholder serves only a claimed effect | mint, then move the effect to `abandoned`; present the placeholder | drop the `status = 'claimed'` predicate ⇒ a credential is presented for an effect nobody claimed |
| One live placeholder per ledgered effect | race N workers through the pre-dispatch path for one effect | drop the partial unique index ⇒ N live placeholders, N authenticated requests for one claimed effect |
| Injected `Authorization` is bound to a ledger row | dispatch two effects to one host, one with no ledger row; capture the upstream requests at a stand-in origin and assert only the ledgered one arrives credentialed | key the rewrite table by host alone ⇒ both arrive credentialed, so any request to that host is credentialed |
| A placeholder cannot be minted off its credential's host | mint against a host that is not `egress_host` | drop the composite FK ⇒ the mint succeeds and the guard has nothing to bind |
| A credential cannot be minted against the control plane | POST a credential whose `egress_host` is the control-plane host | drop the route check ⇒ a southbound credential is presentable to the northbound API |
| Delegation depth is set by us | POST an exchange asserting `delegation_depth = 0` on an OBO flow | drop the trigger ⇒ the caller's value is stored and the cap is bypassed |
| The cap is not policy-dependent | set `max_delegation_depth = 9` | drop the column `CHECK` ⇒ a chain exceeds the schema ceiling |
| A Refresher cannot mint | call `renew()` with no live issuance | let it fall through to `obtain()` ⇒ an unpoliced OBO exchange with no depth evaluation |
| A refresh cannot change the subject | `renew()` an issuance while altering `subject_principal_id` | drop the E3 assertion ⇒ one user's token renews as another's |
| A replacement exchange is not blocked by an expired issuance | expire an issuance without superseding it, call `obtain()` | supersede outside the insert's transaction ⇒ `23505` and the credential is permanently unobtainable |
| Token latency never yields `indeterminate` | stall the provider past the effect lease, run the sweeper | move the refresh between claim and dispatch ⇒ a `claimed` row expires and a human is paged for a token hiccup |
| Revocation is immediate | revoke, then present an unexpired placeholder | check revocation only at exchange ⇒ a revoked credential keeps working until expiry |
| A revoked subject cannot keep a delegated token | revoke the subject principal, present its unexpired OBO placeholder | check the subject only at issuance ⇒ a deprovisioned user's delegated token works until material expiry |

## What this does not guarantee

- **It does not stop exfiltration of what the credential fetched.** The proxy
  authenticates a request; it does not police the response's onward journey.
- **It does not defend against a compromised egress proxy or control plane.** Both hold
  plaintext by construction; a KMS reference moves the secret out of the database, not out
  of the trust boundary.
- **Within its TTL, against its bound host, a stolen placeholder works.** That is what it
  is for; the bound host and the single use are the blast radius, not zero.
- **It does not revoke an agent** — only a credential or a principal, AgentCore's gap
  inherited knowingly.
- **It does not authenticate arbitrary egress from inside the sandbox.** A CLI the agent
  starts on its own is not a platform-executed effect, has no `effect_ledger` row, and
  therefore cannot be given a placeholder — Omnigent's in-sandbox `gh` case is out of scope
  for v0.1 (`projects/omnigent/teardown.md:365-390 @ ba9e371`).
- **It says nothing about vendor-hosted tools**, unsupported in v0.1
  ([§07](07-adapter-protocol.md)): there is no interception point to swap at.
