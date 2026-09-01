# 15 — Sandbox: provider interface and three boundaries
<!-- status: draft -->

Settles the row [`00-overview.md`](00-overview.md) §Not yet specified called *"Sandbox —
three boundaries"* until 2026-08-30, when this document closed it: the provider interface, the v0.1 provider and what inside it is
configuration rather than contract, the three boundaries (process, egress, storage), the
identity rule that keeps a recycled sandbox from being mistaken for a resumed run, and what
happens when a sandbox is lost mid-effect.

It deliberately does **not** settle: the credential exchange/refresh resource or the
secretless placeholder swap at the egress proxy ([`14-credentials.md`](14-credentials.md), Tier 1); what the
mounted knowledge package *contains* ([`16-knowledge.md`](16-knowledge.md)'s and
`10-work-bundles.md`'s); OTel span names; and any upgrade provider — ADR-0016 names none
(`decisions/ADR-0016-sandbox-placement-is-control-plane.md`:83-87).

There is also **no northbound surface for a sandbox**: [`06-api.md`](06-api.md) §Resources
(:56-202) exposes definitions, agents, runs, approvals, policy records and the adapter
catalogue, and placement is not a resource a caller may address — "is my run alive?" is
answered by the run.

---

## Status: what is decided, and what is proven

ADR-0016 is **Proposed**, gated on spike 05, which matters for how this reads.

| Claim | Standing |
|---|---|
| Lifecycle and placement are the control plane's; isolation is the provider's | decided (ADR-0016:35-47) |
| The three boundaries | decided (ADR-0009 §Amended decision, `decisions/ADR-0009-sandbox-is-pluggable.md`:81-92) |
| gVisor admission, and that a missing `runtimeClassName` is detectable | **proven** (`spikes/05-sandbox-sidecar/ENVIRONMENT.md` §T1 @ `9f21e88`) |
| A socket inode does not cross containers under gVisor | **proven** (`spikes/05-sandbox-sidecar/T2-FINDING.md`:20-35 @ `9f21e88`) |
| Idle costs nothing; resume gates hold; identity separation; log-only fallback | **unproven** — spike 05 gates 1-4 have not run; there is no `RESULT.md` |

Nothing here may be cited as verified beyond the two proven rows, and the gates below test
the claims made here rather than the mechanism implementing them
([`../spikes/VERIFICATION-RULES.md`](../spikes/VERIFICATION-RULES.md) rules 1 and 3).

---

## 1. The provider interface

Five *operations* (ADR-0016:37), and one non-operational declaration the placement layer reads
(`ADR-0009`:111, and :103-104 for the interface that reports rather than throws).

```go
// Nothing here may import runs, principals, tenants, policy or the effect ledger:
// ADR-0016:37-38, the provider "knows nothing about runs, principals, tenants,
// policies or approvals".
type Provider interface {
    Create(ctx context.Context, spec CreateSpec) (Handle, error)
    Suspend(ctx context.Context, h Handle) error
    Resume(ctx context.Context, h Handle, spec CreateSpec) (Handle, error)
    Destroy(ctx context.Context, h Handle) error
    Health(ctx context.Context, h Handle) (Report, error)

    // Declaration is read at registration, never per-run. It is not an operation.
    Describe(ctx context.Context) (Declaration, error)
}

type Handle struct{ SandboxID, ProviderHandle string }
type Limits struct{ CPUMillis, MemoryBytes, PIDs int } // amended 2026-08-30, OQ-119:
                                                        // provisional 1 CPU / 2 GiB,
                                                        // unmeasured; PIDs still unknown — OQ
type Report struct{ Gone bool; Detail string }         // named so it is not the method name

// ADR-0009:111 (isolation AND IPC semantics surfaced), :104 (availability reported
// with a reason, not thrown on use); see §4.
type Declaration struct {
    Isolation string       // the process boundary, e.g. "gvisor"
    IPC       IPCSemantics // the channel shape this provider can carry for §07
    Available bool
    Reason    string       // why not, when Available is false
}

// The three shapes spike 05 T2 left standing (`T2-FINDING.md`:57-73,:81-83 @ `9f21e88`;
// abstract-namespace fallback at ADR-0016:145).
type IPCSemantics string // inherited_socketpair | abstract_unix | loopback_tcp

type CreateSpec struct {
    Target     string  // opaque placement target the CONTROL PLANE resolved
    Image      string  // the run container image
    PackageRef string  // knowledge-package digest; the read-only mount source (16 §Materialisation)
    Limits     Limits  // cpu, memory, pids
    EgressVia  string  // the egress proxy: the only permitted destination
    Bootstrap  []byte  // OPAQUE to the provider; carries `run_token` (07 §Start) and
                       // TRACEPARENT/TRACESTATE (19 §Propagation hop 3)
}
```

| Operation | The plane guarantees before calling | The provider may not |
|---|---|---|
| `Create` | the provider sets `Bootstrap`'s contents into the container's environment **without parsing them**, which is how hop 3's trace carrier reaches PID 1 ([`19-telemetry.md`](19-telemetry.md) §Propagation); the package digest is resolved and the definition artifact verified ([`05-state-machine.md`](05-state-machine.md) §Ordering guarantee for resume, steps 2-3); the materialised tree is re-verified against `manifest.json` in both directions by the driver **before `Start`**, not by the provider ([`16-knowledge.md`](16-knowledge.md) §Materialisation, failing `error_code = knowledge_missing` / `knowledge_corrupted`) | inspect `Bootstrap`, or derive tenancy from `Target` |
| `Suspend` | the run holds no lease, and no `effect_ledger` row for the run is `claimed` (§7) | report success before the sandbox is unreachable |
| `Resume` | the pin has been compared and the fenced lease acquired (`05-state-machine.md` steps 4-6) | reuse a prior `Handle`'s identity as the plane's identity (§2) |
| `Destroy` | — | return an error for a sandbox it no longer has |
| `Health` | — | assert an *effect* outcome; a report is evidence, never a verdict (ADR-0016:45) |

**`Destroy` is idempotent**: destroying a gone sandbox is success. The plane, not the
provider, decides a sandbox is finished (ADR-0016:39-40), so an error on an already-gone one
would make the plane's decision depend on the provider's bookkeeping.

**`Bootstrap` is opaque bytes the provider never parses** — the discipline
[`07-adapter-protocol.md`](07-adapter-protocol.md) applies to adapter `config`. A provider
that parses it has coupled itself to the plane this interface exists to separate.

**Suspend and Resume stay distinct even though v0.1 implements suspend as destroy** (§3):
collapsing them would write checkpoint-and-kill into the interface. What keeps a future
provider swappable is that *the harness never relies on process memory surviving; the log
and the adapter checkpoint are the only durability* (ADR-0016:85-87).

**v0.1 reads one bit of the report, `Report.Gone`**, which is all §7 and the `sandboxes`
state machine consume. Any richer vocabulary, and whether the signal is polled or pushed, is
**unknown — OQ**: ADR-0016:37 says "a health signal" and no more. §7's liveness does not
wait on that answer — it polls.

---

## 2. Sandbox identity is not run identity

ADR-0016:73 requires this to be stated somewhere; it is stated here.

A `sandboxes` table keyed `(tenant_id, sandbox_id)` carries it. The DDL is
[`01-schema.md`](01-schema.md)'s, declared after `runs` so the FK target already exists:
`sandbox_id` minted by the plane, a `provider_handle` column, `state sandbox_state` over
`('creating','live','suspended','lost','destroyed')`, the composite FK to `runs`, the
`ended_at`/terminal-state CHECK, and the partial unique index `sandboxes_one_live`. Four
normative consequences follow from it, and they are this document's:

1. **The foreign key points one way only.** `runs` has no `sandbox_id` column and gains
   none. A run transition may not read this table, so no run state can depend on a sandbox's
   existence — what makes ADR-0016:41-43 ("a resumed sandbox is not a resumed run")
   structural, not a convention.
2. **`provider_handle` is never reverse-resolved.** A pod recreated with a prior pod's name
   and labels matches no row, acquires no lease, and reaches no adapter method — the
   property spike 05 gate 3 tests (ADR-0016:122-123).
3. **Sandbox events do not fold.** The `sandbox.*` types
   ([`04-events.md`](04-events.md) §Sandbox) fold to *nothing* in run state. A folding rule
   would reintroduce the dependency rule 1 removes.
4. **A run has at most one non-terminal sandbox**, and the index predicate is `ended_at IS
   NULL` rather than a state list, because `suspended` is non-terminal too: a predicate
   naming `('creating','live')` would let a run holding a suspended row acquire a second
   sandbox with no violation (§7).

---

## 3. The v0.1 provider — Kubernetes + gVisor, suspend as checkpoint-and-kill

Decided in ADR-0016:75-80. The unit is a **pod holding one container in which the Go driver
is PID 1 and spawns the Python harness as its child**, exchanging §07 frames over an
`AF_UNIX` socketpair passed by fd inheritance (ADR-0016:63-72) — the shipped
`integration_mode = 'sdk_subprocess'` ([`01-schema.md`](01-schema.md) §Adapter contracts). One
container rather than two is forced by evidence: under gVisor the socket inode written by
one container never appears in its sibling, while regular files on the same volume do
(`T2-FINDING.md`:20-35 @ `9f21e88`). *Suspend* is **checkpoint-and-kill**: past a
configurable warm window on `waiting_input` the pod is deleted, and resume rebuilds from the
run log and the adapter checkpoint.

### Scheduler configuration, not interface

All three sit under ADR-0016:80-82 as scheduler configuration; a harness that could observe them
would be depending on placement.

| Knob | Default | Visible to the harness |
|---|---|---|
| Warm window (keep the pod for short waits) | **10 minutes** (amended 2026-08-30, OQ-119: provisional, unmeasured — see ADR-0016's config table) | never |
| Warm pool size | **2 per `WorkerPool`** (amended 2026-08-30, OQ-119: provisional, unmeasured) | never |
| Image pre-pull | **a `DaemonSet`** (amended 2026-08-30, OQ-119: provisional, unmeasured) | never |

### Pod-spec constraints, each tied to a boundary

| Constraint | Boundary | Why |
|---|---|---|
| `runtimeClassName: gvisor`, admission-enforced | process | without it the pod runs on the host kernel and the difference is visible only if something checks (`ENVIRONMENT.md` §T1) |
| exactly one container | process | cross-container socket propagation does not hold (`T2-FINDING.md`:57-73) |
| no `host-uds` | process | the earlier Podman attempt used `host-uds=all`, "precisely the flag that makes a host socket reachable and the reason the earlier gates passed" (`T2-FINDING.md`:93-95) |
| no `hostNetwork`, no `hostPID`, no `hostIPC` | egress | a pod on the node's network namespace reaches the node's metadata endpoint directly, and no proxy-side blocklist is one "that no configuration option can disable" (`ADR-0009`:88) if there is a second route around the proxy |
| default-deny egress `NetworkPolicy`, one permitted destination (`CreateSpec.EgressVia`) | egress | `ADR-0009`:86-89 requires a guard on **every** outbound request an agent can cause; without the policy the container reaches the network directly and E1-E7 are advisory. CNI enforcement is assumed, not proven — **unknown — OQ** (§What this does not guarantee) |
| no `hostPath` volume | storage | the only permitted mounts are enumerated in §6 |
| no service-account token mount | storage | a token is a Kubernetes API path out of the sandbox, and the boundary must be structural rather than conventional (`ADR-0009`:90-92) |

---

## 4. Boundary 1 — process

gVisor `release-20260817.0`, **systrap**, no KVM and no ptrace — proven on k3s
v1.35.5+k3s1/arm64 with the handler registered as a containerd drop-in (`ENVIRONMENT.md`
§Stack @ `9f21e88`). The negative control is the point: the same pod without
`runtimeClassName` reports the host kernel (`6.19.7-200.fc43.aarch64`) where the sandboxed
pod reports `4.19.0-gvisor`. Any isolation assertion must tell those apart; the Podman
attempt could not, because `--runtime=runsc` with no `runsc` installed ran runc and reported
success (`ENVIRONMENT.md` §Known-bad reproduced).

**A provider declares its IPC semantics, not only its security properties.** T2 amended
ADR-0009 on exactly this point: both vary by provider and both must be surfaced to the
placement layer (`ADR-0009`:111, evidence row *Spike 05 T2*). The §07 channel depends on the
second, so the declaration is in the interface — `Describe`'s `Declaration.IPC` (§1).

---

## 5. Boundary 2 — egress

The threat, stated by the Pydantic AI teardown and adopted as an ADR-0009 amendment: **an
agent with a URL-fetching tool is an SSRF primitive pointed at your own infrastructure**,
and no process isolation prevents it, because the request is exactly what the tool is for
(`ADR-0009`:44-50).

### Placement: on the plane's side, not in the run container

The guard runs in a process the run cannot enter, and the run container's only route off the
pod is a default-deny egress policy naming one destination, the proxy — `ADR-0009`:86-89
requires the guard on **every** outbound request an agent can cause, and a container with a
second route has no such guard. It is **not** a second container in the run's pod:
containers of one pod share a network namespace (`T2-FINDING.md`:81-83), so a policy naming
"the proxy" could not distinguish it from the run beside it. The same argument puts the
credential swap at the proxy, so the secret never enters the sandbox
(`synthesis/reference-architecture.md`:147-149); that swap's obligations are
`14-credentials.md`'s.

**Granularity is one proxy deployment per tenant data plane**, addressed by
`CreateSpec.EgressVia` — the one decision `14-credentials.md` deferred here. Per run
re-enters the shared-namespace problem; per cluster would put one tenant's rewrite table
beside another's, against the plane's rule that it decides *which tenant's data plane* a run
occupies (ADR-0016:39-40).

Because the platform executes tools, the executor's own outbound traffic is subject to E1-E7
at the same proxy deployment. [`07-adapter-protocol.md`](07-adapter-protocol.md) §Who
executes a tool states this from its own side as of 2026-08-30 — the executor's traffic is
configured through `EgressVia` and has no direct route — so the rule has an owner on both
sides of the boundary.

**Model-provider requests are ordinary egress.** The harness issues them from inside the run
container (`12-harness.md` §1), so they leave through `EgressVia` and are subject to E1-E6
like any tool fetch. **Amended 2026-08-30 (OQ-075): the proxy injects a model-provider key**,
per [`14-credentials.md`](14-credentials.md) §What it deliberately does not settle — the egress
proxy is a Phoenix component holding and injecting the credential keyed on `run_token`/`run_id`
rather than on an `effect_ledger` row, because a model call is not an effect. This is the one
egress class in this document whose credential path is not `14-credentials.md`'s
ledger-keyed placeholder rewrite table: it is the proxy's own configuration, resolved by
`run_token` rather than by `effect_key`.

### The rules

| # | Rule | Evidence |
|---|---|---|
| E1 | Scheme allow-list: `http`, `https`. Everything else refused before resolution | `ADR-0009`:53 records "protocol validation" only; the two-scheme list and the before-resolution ordering are imposed here — **unknown — OQ** whether `_ssrf.py @ b48ee38` matches |
| E2 | Resolve hostname → IP, check the **resolved address**, then connect to that address | `ADR-0009`:53 records "hostname→IP resolution" only; the pinning is imposed here — **unknown — OQ** whether `_ssrf.py @ b48ee38` matches |
| E3 | Block private ranges, link-local `169.254.0.0/16`, CGNAT `100.64.0.0/10` | `ADR-0009`:53-55 |
| E4 | Decode the Teredo prefix `2001::/32` before checking — "the raw low-32 bytes are meaningless, so it needs its own decode" | `projects/pydantic-ai/teardown.md`:267-268 @ `b48ee38` |
| E5 | The enumerated cloud-metadata list below is blocked **unconditionally**; no configuration option disables it | `teardown.md`:250-256 @ `b48ee38` |
| E6 | `Accept-Encoding: identity, gzip` only, and brotli/zstd/deflate are rejected **even when returned**; responses are size-bounded | `teardown.md`:269-275 @ `b48ee38` |
| E7 | An escape hatch is scoped so it cannot open the worst hole: a local-access option skips E3 and never E5 | `ADR-0009`:77-80 |

### The enumerated blocklist

| Address | Serves | Note |
|---|---|---|
| `169.254.169.254` | AWS IMDS, GCP, Azure, OCI, DigitalOcean, Hetzner, IBM, OpenStack | |
| `169.254.170.2` | AWS ECS task IAM role credentials | |
| `169.254.170.23` | AWS EKS Pod Identity Agent | |
| `168.63.129.16` | Azure WireServer | **a public IP** — no private-range check catches it, so E5 is the only thing that blocks it |
| `100.100.100.200` | Alibaba | also inside CGNAT |
| `192.0.0.192` | Oracle Classic | |
| `169.254.42.42` | Scaleway | |
| `fd00:ec2::254` | IPv6 form | the one IPv6 equivalent the source enumerates (`teardown.md`:262-263); whether the other rows have IPv6 forms in `_ssrf.py` is **unknown — OQ** |

Read from `pydantic_ai_slim/pydantic_ai/_ssrf.py:98-120 @ b48ee38` on 2026-08-26
(`teardown.md`:258-263) — a point-in-time enumeration of someone else's list, and so a
standing maintenance obligation with no upstream feed behind it: who re-verifies it, and how
often, is **unknown — OQ**.

---

## 6. Boundary 3 — storage

Cloudflare's contribution to ADR-0009: if the model can write SQL, a policy enforced in the
same database is a convention, not a control, so enforcement must be **structural**
(`ADR-0009`:90-92). **A run may mount exactly two things:**

| Mount | Mode | Durability |
|---|---|---|
| The compiled knowledge package ([`16-knowledge.md`](16-knowledge.md) §Materialisation; `knowledge_packages.digest`, §Schema), carrying the pinned `WorkBundle` layer (§Layers and resolution order) | read-only | immutable; resolved by digest before `Create` |
| One `emptyDir` scratch | read-write | **destroyed by suspend** |

Nothing else: no `hostPath`, no persistent volume, no service-account token, no secret
volume, no database credential of any kind. The run container holds no route to the control
plane's database, and the only channel from the harness to the control plane is §07 frames
over the inherited socketpair to the driver — the one process holding a control-plane
identity. Its only other outbound path is `EgressVia` (§5), which carries none.

Scratch is deliberately non-durable, because checkpoint-and-kill deletes the pod
(ADR-0016:75-80) and *the log and the adapter checkpoint are the only durability*
(ADR-0016:85-87). A harness keeping state only in scratch fails spike 05 gate 4 as one
keeping it in memory does (:124-129).

---

## 7. Suspension, loss, and the ledger

**Preconditions for suspend.** The plane may call `Suspend` only when the run holds no lease
and no `effect_ledger` row for the run is `claimed` — both implied by the state that triggers
suspension, since an effect awaiting a human sits at `awaiting_approval`, not `claimed`,
precisely because "a 5-minute lease cannot span an hour of deliberation"
([`01-schema.md`](01-schema.md) §Effect ledger; the phase split at
[`02-consistency.md`](02-consistency.md) §Claiming and performing an effect). Suspending with a claimed effect would
manufacture indeterminacy the platform then has to carry.

**The `sandboxes` transitions.** These are all of them; no other edge exists.

| From | To | Trigger | Actor |
|---|---|---|---|
| `creating` | `live` | `Create` returns a `Handle` | worker |
| `live` | `suspended` | `Suspend` returns | worker |
| `suspended` | `live` | `Resume` returns a **new** `Handle`: the prior row moves to `destroyed` **first**, then a new row is inserted and runs `creating`→`live` — the index predicate forbids the overlap | worker |
| `creating`, `live`, `suspended` | `destroyed` | `Destroy` returns | worker |
| `creating`, `live`, `suspended` | `lost` | a provider report, or `Health` answering `Gone` | **system only** |

v0.1 never writes `suspended`: its suspend deletes the pod, so the row goes to `destroyed`
(ADR-0016:75-80). The value exists for a provider that keeps something. The five event types
— `sandbox.created`, `.suspended`, `.resumed`, `.destroyed`, `.lost` — are registered at
[`04-events.md`](04-events.md) §Sandbox under its §Naming rule (:36), and every one **folds
to nothing** in run state (§2 consequence 3).

**Losing a sandbox is not a verdict.** A provider reporting loss produces one `sandbox.lost`
event and moves the row to `lost` with `ended_at` set. It changes no run state. The
classification is already specified and does not change here: the stream closes without an
`End` frame — **an unsettled effect ⇒ `indeterminate`; every effect settled ⇒ `failed`,
`adapter_disconnected`** ([`07-adapter-protocol.md`](07-adapter-protocol.md):191-195, tested
at :522).

Two transitions, not one: the **run** is classified as soon as the adapter is gone and a
`claimed` row exists — system only, no waiting
([`05-state-machine.md`](05-state-machine.md):87,:98-109) — while the **effect row** becomes
`indeterminate` when the §02 sweeper finds the claim's lease expired
(`02-consistency.md` §Claiming and performing an effect, and :330-338). Both read the ledger; neither reads the provider's
report. That is ADR-0016:44-45 made concrete: *"a provider reporting 'actor evicted' is
evidence, never a verdict"*.

**Enforcing one non-terminal sandbox.** Before `Create` may run for a run that already has a
row with `ended_at IS NULL`, the plane must drive that row to `lost` or `destroyed`. It does
not wait to be told: it polls `Health` on the colliding row and treats a provider that
cannot answer within a bounded timeout as `Gone`, so an unobserved loss still resolves and
the §1 OQ is about richer vocabulary, not liveness. The partial unique index (§2) enforces
it, so a resume that skips the step fails loudly rather than producing a second sandbox.

**Resume changes nothing about the gates.** A run resumed into a fresh sandbox still walks
`05-state-machine.md` §Ordering guarantee for resume in order — digest, hash, pin,
materialised tree, fenced lease, and only then the adapter. Sandbox replacement must not
become a way to skip a gate (ADR-0016:119-121).

---

## Tests, with negative controls

Binding per [`../spikes/VERIFICATION-RULES.md`](../spikes/VERIFICATION-RULES.md): each row is
tested through the public boundary, and each control must make the suite go red.

| Invariant | Test | Negative control |
|---|---|---|
| The run container is under gVisor | assert the Sentry kernel banner (`4.19.0-gvisor`) from inside | drop `runtimeClassName` ⇒ the host kernel string appears and the assertion must fail |
| No route off the pod skips the guard | from the run container, connect to a public address and to `169.254.169.254` | remove the default-deny egress policy ⇒ both connect |
| The metadata list cannot be configured off | enable every escape hatch, request `168.63.129.16` | make E5 configurable ⇒ the request succeeds, and no private-range check would have caught it |
| Teredo-obfuscated forms are blocked | request the `2001::/32` form of a blocked address | remove the E4 decode ⇒ allowed |
| The guard connects to the address it checked | resolve a hostname to a public address, flip the DNS answer to `169.254.169.254` between check and connect, request it | re-resolve at connect ⇒ the connection lands on the metadata address and E5 never sees a hostname it can block |
| The tool executor has no second egress path | run a platform-executed fetch tool against `169.254.169.254` from the executor | give the executor a direct route ⇒ it connects and no proxy log line exists |
| A model request leaves only through the proxy | run a turn; assert the proxy logged the model host and the run container's environment, mounts and outbound headers carry no provider key (amended 2026-08-30, OQ-075: the proxy injects it, keyed on `run_token`/`run_id`, not an `effect_ledger` row) — **unproven**, since this document's own §Status table marks the provider's gates unrun | give the container a direct route ⇒ the turn still succeeds with no proxy log line |
| Unboundable encodings are rejected | server returns `zstd` despite `Accept-Encoding` | accept it ⇒ a few compressed bytes expand to multi-MiB |
| A run mounts only the knowledge package and one scratch | from inside the run container, read `/proc/self/mountinfo` and assert exactly the two, with the package read-only | permit an extra volume in admission ⇒ a `hostPath` appears in `mountinfo` and the assertion must fail |
| Scratch does not survive suspend | write to scratch, suspend past the warm window, resume, read | back scratch with a PersistentVolume instead of `emptyDir` ⇒ the written bytes are still readable after resume and the assertion must fail |
| No control-plane database path from the run container | attempt a connection to the control database | inject the database credential into the container ⇒ it connects |
| A provider's declared IPC semantics decide the channel | register a provider declaring `abstract_unix`; assert the driver binds an abstract-namespace address and creates no filesystem socket and no socketpair | let the plane hard-code the socketpair ⇒ the abstract address is never bound and the assertion fails |
| A run holding a suspended sandbox cannot acquire a second | leave a row in `suspended`, call `Create` for the same run | give `sandboxes_one_live` the predicate `state IN ('creating','live')` ⇒ the second row inserts cleanly |
| A resume after an unobserved loss is not blocked forever | kill the pod without a provider report; resume | skip the `Health` poll and the `lost` transition ⇒ `Create` violates `sandboxes_one_live` and the run cannot resume |
| A recycled sandbox is not a resumed run | recreate a pod with a prior pod's name and labels; assert no lease and no adapter call | resolve the run by `provider_handle` ⇒ a ghost resume |
| A sandbox event never changes run state | append `sandbox.lost`, fold the log | give it a folding rule to `failed` ⇒ run state now depends on sandbox identity |
| Loss mid-effect is `indeterminate`, decided by the ledger | kill the pod with one `claimed` effect; run the sweeper | classify from the provider's report instead ⇒ a verdict the provider is not entitled to give |
| Idle costs nothing | after the warm window, no pod exists for the run; the run row is `waiting_input` with no lease | warm window zero and skip deletion ⇒ red (ADR-0016:116-117,130) |
| Resume rebuilds from the log alone | delete the adapter checkpoint artefact, resume | keep harness state in process memory ⇒ red (ADR-0016:124-129) |
| Suspend never runs with a claimed effect | force a `claimed` row, request suspend | drop the precondition ⇒ manufactured `indeterminate` |

---

## What this does not guarantee

- **Not a hypervisor boundary.** gVisor was chosen because it needs no KVM and runs on any
  customer's nodes (ADR-0016:75-80), not because it is the strongest isolation available.
- **The provider is decided, not proven.** Spike 05 gates 1-4 have not run. Only T1
  (admission, with its control) and T2 (cross-container socket propagation) are evidence.
- **The egress guard blocks addresses, not intent.** An allowed host is an exfiltration
  channel; content-level egress control is a different boundary, not specified here.
- **The blocklist is a snapshot** read on 2026-08-26. It goes stale silently when a cloud
  provider adds an endpoint.
- **Egress confinement assumes the cluster's CNI enforces the policy** — **unknown — OQ**.
  Spike 05 proved gVisor admission on k3s; it did not test policy enforcement, and if a CNI
  silently ignores the policy the boundary degrades from structural to conventional.
- **No claim about what survives `Destroy`.** Reclaiming the `emptyDir` is the kubelet's.
  This document names no wipe, no encryption-at-rest and no admission rule for remanence, so
  nothing here may be cited for what a later pod on the same node can read.
- **No claim about the checkpoint artefact at rest.** Where it is stored and how it is
  protected belongs to `04-events.md`'s `adapter.checkpointed`, not here.
