# 20 - Ory-managed local human accounts

**Forward amendment, 2026-09-10:** this specification adopts the Phoenix document
`docs/ORY-PLATFORM-RESET-PLAN.md`. The lifecycle/profile design below is not yet
implemented. Existing migrations and generated contracts remain current artifacts
until source-owned forward changes and normal generation implement this contract.

This amendment supersedes customer-token exchange and independently minted human
bearers in the initial API specification. Customer identity federation is deferred.
Kratos owns credentials, verification, MFA, recovery and browser sessions. Phoenix
owns invitations, membership, permissions and audit. Machine credentials remain a
separate, revocable path and may name only an actual agent or service principal.

## Tenant authority

An operator-controlled exact browser-origin registry selects a Kratos realm. Each
self-hosted tenant realm has its own Kratos database and stable keys; the platform
operator realm is separate. Host selection is not authorization. Only a valid Ory
session plus an enabled (realm_id, identity_id) binding to an unrevoked human in an
active tenant grants access, and then only to the operations its current membership
authorizes and whose capability requirements are separately satisfied. Email and
request tenant fields never supply authority.
A configured realm must agree with the binding's tenant. Unknown, disabled, revoked
or suspended membership grants nothing.

A member receives the existing own-run capability class. A tenant administrator
receives administrator capabilities only after email verification and aal2. Global
tenant listing additionally requires an explicit, live platform-operator grant in
the operator realm. Tenant administrators cannot create that grant. Fine-grained
team membership remains an additional resource-level authorization requirement.

## Browser request boundary

The sole browser credential is the host-only Kratos session cookie. Phoenix validates
it against the configured trusted Kratos public endpoint on every request, without a
positive cache. It never accepts an endpoint URL supplied by a request. Redirects,
inactive/expired sessions, disabled identities and malformed upstream responses fail
closed. Cookies and bearer/fire/native-session credentials cannot be combined as a
fallback. Human bearer tokens and the old discovery/exchange routes are refused by
Ory-configured servers.

GET /v1/auth/session returns only bound account display information, effective
permissions, expiry, verification/MFA requirements, and a session-bound CSRF token.
It returns no independent human bearer. A linked account needing verification or
administrator MFA can bootstrap with no effective permissions; other Phoenix API
calls remain denied. The response is private/no-store. The CSRF value alone grants
nothing: writes need a currently valid session, exact configured Origin and matching
X-Phoenix-CSRF. Missing or foreign origins do not authorize writes.

Request lifetime is bounded by the Ory session expiry. Long-running requests must
revalidate the session and membership at least every five seconds and cancel on
revocation, identity/role changes or dependency failures. HTTP stream handlers must
honor that cancellation. Logout/recovery/offboarding acceptance must demonstrate
revocation through real Ory and the deployed API, not only request middleware fakes.

## Delivery status

This is the target contract, not a claim of completed cutover. Invitation enrollment,
public-flow proxying, SPA lifecycle, runtime wiring on every substrate, real-browser
acceptance, machine caller migration and deletion of legacy fixtures are tracked in
Phoenix issues #103 through #110. Applied Phoenix migration bytes are immutable;
source-owned additions live in spec/migrations and append after existing migrations.

## Invitation browser transport

The browser-only `/auth/enrollment/` surface is mounted beside the allowlisted
Kratos browser proxy, outside the generated northbound `/v1` machine/resource
API. It never returns or accepts a Phoenix human bearer. Unknown body fields,
query parameters and machine/native credential headers are refused; mutations
require the exact configured Origin and responses are private/no-store.

- `POST start {token}` checks a live, unredeemed invitation in the host-selected
  realm. It sets a signed HttpOnly host-only SameSite=Lax continuation, Secure and
  `__Host-` prefixed on HTTPS. Its lifetime is at most one hour and cannot exceed
  the invitation deadline. It stores the digest, realm, tenant and random nonce,
  not the original secret; it is permission to continue registration, not access.
- `GET status` returns invited email, role, continuation expiry, next_action
  (`register_or_login`, `verify`, `mfa`, or `accept`) and csrf_token. Confirmation
  CSRF is bound to the continuation and freshly checked Ory session/identity.
- `POST accept {}` requires `X-Phoenix-Enrollment-CSRF` and a fresh Ory browser
  session. Only server evidence supplies identity ID, currently verified email,
  realm and assurance to the atomic redemption transaction. Changing accounts
  invalidates a previously displayed confirmation. Invitation possession alone
  must never authenticate or activate a principal.
- `POST issue` requires current verified AAL2 administrator membership and
  `X-Phoenix-CSRF`. Body fields are email, display_name, optional principal_id,
  role, purpose, optional teams, expires_at and reason. Optional realm_id selects
  another configured tenant only for a live platform operator; tenant_id is never
  accepted from the body. Default expiry is 24 hours, maximum seven days. First
  admin issuance requires an operator grant and no existing Ory tenant binding.
  The response contains invitation_id, expires_at and a one-time delivery URL.
- `POST revoke` requires the same administrator and CSRF checks, invitation_id
  and reason, with the same operator-only cross-realm selection rule.

Delivery URLs put the secret in `/auth/enroll#token=...`, never a query. The SPA
removes the fragment before posting the secret and does not persist it. A boolean
navigation marker can preserve progress through credential, verification and MFA
flows but grants nothing. Acceptance requires an explicit confirmation action.
Every proxied registration create/read/submit checks the continuation and live
invitation again. Dependency failure is 503, not an apparent invitation withdrawal.

These are separate Ory and Phoenix writes, not a distributed transaction. A race
with revocation or a failed Phoenix commit can leave only an unlinked Ory identity;
retry must never infer an identity link from an email match or restore removed
membership. A lost successful response may be recovered by normal bound-account
sign-in. This amendment does not claim initial operator bootstrap, recipient email
delivery, offboarding reconciliation or full browser acceptance are complete.

### Deployment-owned customer realm registration

`tools/ory-realm` is an offline deployment job, not a browser endpoint. It requires
an already-active customer tenant, its expected slug, a complete current realm
registry, a dedicated browser cookie hostname and Kratos public upstream, and a
stable request ID with deployment actor and reason. Attaching a realm to a tenant
that is already active is a narrower operation than preparing a pending one, and it
is not the canonical provisioning workflow described below. It creates no identities,
principal links, invitations, memberships, or operator grants. Realm metadata and
the provisioning receipt commit atomically; configuration publication and plane
restart remain explicit subsequent deployment steps.

Migration 128 adds an immutable provisioning receipt and a port-independent unique
cookie-host index. Different browser ports do not create separate cookie scopes.
Existing duplicate-host topology must be reconciled before that migration; it is
not silently merged or deleted. A matching retry recovers the receipt, including
after database commit but before registry publication. Changes to actor, request,
reason, tenant, slug, origin, or upstream are not retries. Disabled realms and
inactive tenants are not restored, operator realms cannot become customer realms,
and older rows without a receipt require explicitly audited reconciliation.

The deployment tool validates configured metadata against Phoenix's realm registry;
it does not prove DNS ownership, actual Kratos database isolation, or live runtime
health. Those belong to deployment acceptance. Once the matching registry has been
published, a verified AAL2 Phoenix operator can issue the first-admin invitation
through the existing enrollment browser boundary. No new human HTTP or bearer-token
contract is introduced by this provisioning job.

### Fresh-tenant Ory preparation and activation

The canonical deployed plane workflow owns plan, apply and status. Existing developer
commands must wrap that policy or retire; neither the service nor the database may
maintain a second interpretation of activation. Exact command/wire shapes are pending
source-contract implementation, not a claim that profile flags already ship.

Persist desired `control-plane` or `execution-enabled` profile independently from
observed credential-storage and execution capabilities. Observed states distinguish
not configured, pending, ready, failed and disabled, with configuration revision,
verifier version, timestamp and sanitized reason. Profile intent and historical
`not_applicable` receipts never prove readiness.

The stored tenant states remain `pending`, `active`, `suspended`, `offboarded`.
`active` means policy/identity control-plane prerequisites agree and authorized
members can use supported operations. It does not require an adapter, data key or
worker pool. Genuine adapter metadata, protected credentials and isolated placement
are prerequisites for dependent execution, not all human sign-in.

Pending tenants grant no ordinary tenant data access. Only a valid explicitly scoped
setup/enrollment continuation or bound setup authority permits its narrow setup
operations; an arbitrary Ory identity receives no tenant existence or status details.
Operators inspect/retry an authorized customer using separate current operator grants,
not by becoming customer administrators. Suspension/offboarding override valid Ory
sessions and cannot be reversed by provisioning retries. Machine read policy remains
separately enumerated and tested.

Prepare the operator realm and consume its deployment-issued one-time bootstrap with
verified email and MFA. Then record customer identity/profile and versioned intent;
prepare its policy and dedicated Kratos realm/runtime; reconcile registry publication;
activate the control plane under the common transaction. The authenticated operator
can now issue first-admin enrollment. Activation grants no principal link or membership;
first-admin delivery and explicit verified-email/AAL2 acceptance are separate receipts.
An active empty customer is not onboarding complete. This ordering avoids requiring
an enrolled customer administrator before an offer can be issued to that administrator.

The workflow requires explicit database/registry inputs, immutable tenant ID/slug/region,
realm/origin/upstream, actor, stable request ID and reason. HTTPS and cookie-host
isolation are not relaxed by a limited profile. Plan is non-mutating. Apply uses locked
persisted lifecycle/authority, structured versioned intent and configuration-bound
bounded readiness results. Do not hold database locks while waiting for remote work.
Status distinguishes activation, capabilities, registry publication and enrollment.

Identical retries recover the committed receipt without duplicate grants or restoring
later-withdrawn authority. Conflicting intent requires explicit reconciliation. Audit
reason text is not a machine protocol. Crash after remote success, database commit,
output or registry publication must be resumable without direct SQL activation.
Do not change existing migration 129 to reinterpret old receipts; use forward migration
and explicit reconciliation for new profile/intent semantics.

Missing execution or protected credential storage refuses dependent operations while
supported control-plane access remains available. A configured mandatory provider
failure remains a hard error, not a silent dev-sealer/environment fallback. Installing
OpenBao is not proof of spec/14 storage. Admission rechecks current capabilities;
queued work becomes explicitly blocked and workers recheck before dispatch. Already
external effects follow bounded reconciliation, not blind retries. Authorized historical
reads do not require a running worker.

Typed bootstrap/status errors must distinguish missing authentication, verification,
MFA, no membership, setup, suspension, capability unavailability and dependency outage.
One operation matrix declares credential class, roles, lifecycle and capabilities;
new routes without a row fail the check. Shared realm validation must use exact origins
and port-independent normalized cookie hosts at all entry points.

Milestone A is real HTTPS/image acceptance for operator plus two independent customer
realms, without a customer IdP, development relaxations or seeded identity links.
It includes safe absence/refusal, retries, permissions, session lifecycle, mail,
private admin isolation, replicas and restore. Actual protected workload completion
is the separate harness release, not a prerequisite for initial human identity.

### Recovery and password-change session withdrawal

The shared Kratos configuration must run `revoke_active_sessions` after successful
recovery and after a persisted password settings change. In the pinned v26.2.0
implementation, each hook revokes the identity's other sessions while retaining
the current recovery/password-changing session. This is an Ory operation, not a
Phoenix bearer revocation or a second session store. Matching email in a separate
realm does not expand the revocation target.

Current-session logout remains a separate, explicit browser action. No device-list
or all-session management UI is implied by these hooks. The configured behavior
requires real-browser acceptance, including fresh login with the replacement
password, rejection of an old password/session, stable Phoenix principal mapping,
and no authority upgrade through recovery. Administrator MFA recovery and account
removal remain distinct acceptance requirements.

### Self-service withdrawal of other Ory sessions

The Phoenix sign-out page provides separate explicit actions for current-browser
logout and withdrawal of the account's other sessions. The latter calls exactly
`DELETE /auth/ory/sessions`, routed to the configured realm's public Kratos
`DELETE /sessions` operation. Ory identifies the account from its browser cookie,
revokes other sessions, preserves the current session, and returns a revocation
count. Phoenix does not choose an identity from user input or issue a replacement
credential. This privilege-reducing account operation does not grant Phoenix access.

The proxy requires exactly one matching Origin on this DELETE as on browser form
mutations. It rejects bearer/native credentials, query parameters, request bodies,
and arbitrary session/identity paths. Public session inventories and Ory admin
APIs are not implied or exposed. Failure or an invalid receipt must not be reported
as completed revocation. Other realms, including same-email identities, are outside
the operation's scope.

Current logout plus other-session withdrawal are two operations, not an atomic
account lock against concurrent login. Administrative all-session withdrawal and
account removal require separately defined and tested lifecycle guarantees.

### Durable Ory cleanup after principal withdrawal

For an Ory-linked human, principal revocation and creation of Ory cleanup intent
must commit together. Migration 130 stores pending/completed cleanup jobs bound by
foreign key to the exact realm, identity, tenant, and principal. Outstanding jobs
are deduplicated per identity; completed receipts remain. Existing withdrawn linked
humans are backfilled for reconciliation.

Phoenix access ends with principal withdrawal, independently of Ory availability.
The revoke response does not imply Ory cleanup has completed. Restore must refuse
while cleanup is pending; compromise remains irreversible. Cleanup failure must
not undo withdrawal or record completion. Workers use bounded private admin access,
confirm the identity before session deletion, and require explicit acknowledgement.
Wrong-realm/unknown identity responses are reconciliation errors, not success.

The deployment command `tools/ory-revoke` processes one explicitly configured realm,
with no default endpoint or migration-on-start. Row locking excludes concurrent
claims; a crash or failed acknowledgement commit leaves retryable intent. Nonzero
pending work is an unsuccessful drain result and must remain operationally visible.
Only sanitized cleanup failure codes belong in durable records.

This removes sessions, not Ory credentials or historical principals. New Ory login
while Phoenix remains revoked does not regain workspace access. Any subsequent
restoration is an explicit Phoenix regrant. Private deployment scheduling, account
disabling, tenant-wide cleanup, and real-browser offboarding acceptance remain
separate requirements before production cutover.

### Preserving tenant administrator availability during withdrawal

Withdrawing an enabled Ory tenant administrator must leave another enabled admin
identity link to a non-revoked human principal in that tenant. An ordinary member,
a disabled identity link, an unlinked legacy human, or a revoked administrator is
not a substitute. Refuse the last administrator with an actionable HTTP 409 before
changing the principal, writing the withdrawal audit, or enqueueing session cleanup.

Serialize withdrawals on the tenant row before locking a target principal or
counting remaining administrators. This prevents two concurrent withdrawals from
each relying on the other's target, and avoids cross-principal audit foreign-key
lock inversion. Future membership-demotion or link-disable mutations must preserve
the same availability invariant under the same tenant-level serialization. Keep
legacy last-human protection; do not equate that count with Ory admin authority.
This tenant-admin invariant is separate from platform-operator grant policy and
per-team membership permissions.

Identity mutation lock ordering includes enrollment authority, not just withdrawal.
Before locking authority/principal/realm rows, invitation issuance and withdrawal must
lock both the actor and target tenants in ascending tenant-ID order, deduplicating the
same-tenant case. The actor realm lookup supplies a lock key only; live binding, tenant
state and operator-grant checks still run under locks. Principal withdrawal/restoration,
ordinary enrollment acceptance and operator-bootstrap acceptance lock their tenant before
principal/realm rows. A cross-tenant operator invitation must not hold the operator's
principal while waiting on a tenant lock already held by withdrawal of that operator.

### Team role transition and resource authority

New team membership and invitation grants use member/steward; tenant administration
remains a separate role. Migration 131 preserves legacy owner rows as history, not an
automatic steward promotion. Existing owner memberships retain assigned-team read access
only; pending owner invitations require explicit reissue. An already-redeemed retry must
not rewrite or restore old memberships. Administrator reassignment/reconciliation remains
an explicit audited operation to deliver, not an inference from an old role label.

Non-admin Ory humans list only their assigned teams and connections. Ungranted or
cross-tenant team lookups are not found. Team membership is read from live Phoenix state;
lookup failure must not fall back to tenant-wide access. A steward can test connections
only in its own non-archived team. Connection credential rotation remains tenant-admin
only because credential references currently lack a team-ownership boundary. Do not
delegate tenant-wide knowledge, credential or policy operations as if they were scoped
by an arbitrary supplied team ID. Machine/run permissions remain separately authenticated
and tested. The remaining team mutation, resource and stream matrix is tracked in #109.

Package catalogue and direct package metadata reads must agree on publication
visibility. Ordinary Ory humans may read a package published in a current,
non-archived team only through their current membership. Resolve a team layer's
immutable slug to the internal team ID used by membership; string equality between
those two identifiers is not authority. An explicit non-team layer publication is
tenant-visible, matching the non-team layer catalogue; publishing the same digest
in both a team layer and a non-team layer therefore grants shared visibility.
Unpublished and other-team-only packages are absent from the ordinary-human list
and return the same 404 as an unknown digest. A known digest or historical run
reference is not a permanent grant to this tenant-level endpoint. Membership
withdrawal, team archive and publication rebinding affect subsequent reads without
requiring sign-out. Failed authority/publication lookup must not fall back to an
unfiltered list. Existing tenant-admin and machine read policy remains separate.
This package-metadata boundary does not settle node classification, skill resolution,
run materialization or historical-provenance authorization; those need their own
contract and evidence rather than inheriting a grant from digest possession.

Runtime layer resolution is captured with run creation, in the same transaction as
run.created. Migration 133 stores a versioned immutable snapshot and a domain-separated
resolution checksum; run.created records that checksum. The snapshot binds tenant,
run, team, agent and definition IDs, the effective manifest, and each winning node's
source package, bundle, scope and registering principal. Its effective package digest
uses the existing knowledge manifest canonicalisation. This execution snapshot is
separate from an agent definition's optional knowledge_package_digest assertion.
Resolve a team layer by the stored team's immutable slug, never its internal ID;
exclude other teams, other agents, other tenants and unbound persona scopes. Capture
all selected publications in one database statement. A run with no knowledge still
gets an explicit empty snapshot, so later publication cannot change its inputs.
Scheduled runs capture through the same routine. Delegated verification children
inherit their origin's team and snapshot content, not the current publication stack;
standalone reconciliation supplies the trusted origin explicitly. Child definition
and identity remain their own. Layer edits, archive and membership withdrawal do not
rewrite an admitted run's inputs; live human read/stream authorization remains separate.
Every worker knowledge consumer uses this snapshot. Computation independence uses the
winning package's captured publisher, not the latest registration with that bundle ID.
Materialized content is checked against the stored manifest as well as its local tree
manifest. Missing or inconsistent snapshots fail rather than reconstructing historical
knowledge from current layers. A configured worker without a knowledge source cannot
execute a run with nonempty pinned knowledge. Node classification, persona ownership,
and the complete definition-declared package/cutover audit remain separate requirements.

## Human run-creation idempotency

For Ory-authenticated POST /v1/runs, a retry key belongs to the tenant and stable
Phoenix principal, not the tenant alone and not the Ory session. Different human
principals may reuse a client key without replaying one another's run responses
or reserving one another's keys. The same principal's changed request body under
an answered key is refused. Machine requests retain their existing key namespace.

An answered legacy tenant-wide record may replay to a human only after the
referenced run proves the same tenant and creator. Another creator's completed
record is not a grant and does not occupy the human's new namespace. Unanswered
legacy reservations do not establish an actor: refuse with conflict until the
writer completes or the outcome is explicitly reconciled. Do not automatically
reclaim one into a new namespace and potentially duplicate work. Corrupt or
unresolvable recorded responses fail closed; existing retention still applies.

This retry isolation does not complete team authorization. The explicit run-team
boundary below governs the primary run namespace; historical reconciliation and
authorization on the remaining resource families are still required. Creator
membership is not a substitute for a run's explicit team ownership.

## Explicit run team ownership

New human run creation requires an explicit team_id in POST /v1/runs. Phoenix
checks the current realm-linked principal and tenant role; a non-admin needs
member or steward membership in that non-archived team. The creation transaction
locks the authorization rows and records the same team binding in the run row
and run.created payload. Team reassignment is not a routine update.

The human run list is filtered before pagination. Direct /v1/runs/{id} resource
routes and run-event streams require a current tenant administrator or current
membership in the run's bound team; historical owner membership remains readable
without gaining mutation authority. Stream permission is checked before each
poll batch (currently every 300 ms) and the stream terminates on withdrawal or
lookup failure. Existing transition rules still govern who may mutate a run.

Unassigned historical or machine runs are visible to a current tenant admin,
not to arbitrary human members or inferred creator teams. Historical assignment
requires a separately audited reconciliation path; migration 132 does not guess
one and the ordinary UPDATE path cannot reassign ownership. Registered machine
requests retain their existing authentication and scope behavior. Other resource
families outside the run URL namespace still need their own run/team enforcement
before the complete role matrix or production cutover can be accepted.

## Run-linked queues, reports, and approval decisions

Human approval queues, effect queues, and report galleries use the same current
run/team visibility predicate before ordering and limits. Report access checks
its run before resolving templates or rendering output. An ungranted report is
indistinguishable from a missing report. Membership-store failure never becomes
an unfiltered tenant-wide result. Existing machine paths remain separate.

Approval decisions remain tenant-admin-only; steward membership is not approval
administration. Human decisions recheck the current realm, identity link, human
principal, active tenant, and administrator role in the decision transaction,
using the shared tenant-authority lock order. An earlier HTTP authentication
result is not authority after a concurrent withdrawal. The decision records the
Phoenix principal and preserves single-terminal-decision/409 semantics.

## Audited team administration through Ory sessions

Tenant administrators may create teams and manage existing enrolled-human team
memberships through the Ory-only operations in [the API contract](06-api.md#ory-only-team-administration).
The administrator's current Phoenix authority is rechecked under the same tenant
transaction lock used by identity withdrawal. Authentication at request entry is
not sufficient authority for a write that waited behind a concurrent demotion.

Team creation atomically creates its initial steward grant and audit record.
Subsequent additions, role changes and removals atomically record the human actor,
realm, request identifier, non-empty reason and membership transition. Failure to
record the audit rolls back the resource change. Unchanged grants and already
absent memberships do not manufacture extra audit history.

A team grant cannot create or restore an Ory identity link, revive a revoked
principal, or grant tenant administration. Targets must already be active humans
enrolled in the same tenant and realm. New team roles are `member` and `steward`;
historical `owner` rows are not silently promoted. An administrator may deliberately
promote an eligible historical owner through an attributed membership change.

Removing or demoting a steward requires another active enrolled steward and is
serialized with other team/identity management. Revoked principals and disabled
identity links or realms do not count as a replacement. This guard applies to
team management, not security offboarding: compromised account access must remain
revocable even if an administrator must subsequently repair a stewardless team.

Team removal preserves other team access, the Ory account/session and historical
activity. Its authorization effect begins at the next request or documented
stream access check, not by pretending to revoke an entire account. Browser forms
must name that scope, require a removal reason and explicit target confirmation,
and discard previous-account form state and late receipts on account replacement.
