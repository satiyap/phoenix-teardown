# Deliverable 4 — Reference Architecture (v0)

> Status: **strawman**. Frozen only at Phase 5, once the ADRs are Accepted.

## Strawman

```text
                      Web / CLI / API
                            │
                            ▼
                   ┌────────────────┐
                   │  Workspace API │   northbound
                   └───────┬────────┘
                           │
             ┌─────────────▼─────────────┐
             │       Control Plane       │
             │                           │
             │  registry    IAM          │
             │  scheduler   policy       │
             │  task svc    messaging    │
             └─────────────┬─────────────┘
                           │
                      Event Bus
                           │
             ┌─────────────▼─────────────┐
             │       Runtime Plane       │   southbound
             │                           │
             │  adapter manager          │
             │  workers                  │
             │  checkpoint               │
             └─────────────┬─────────────┘
                           │
           ┌───────────────┼────────────────┐
           ▼               ▼                ▼
     Claude adapter   Codex adapter    A2A adapter
           │               │                │
           ▼               ▼                ▼
        Sandbox         Sandbox          Remote
```

## Plane responsibilities

| Plane | Owns | Explicitly does not own |
|---|---|---|
| Workspace API | Auth, request validation, northbound contract | Business logic |
| Control Plane | Identity, registry, task lifecycle, policy decisions, messaging, budget | Agent execution |
| Runtime Plane | Adapter lifecycle, worker pool, checkpointing, sandbox brokerage | Policy decisions |
| Adapters | Harness-specific translation | Durability guarantees |
| Sandbox providers | Isolation, filesystem, network controls | Agent semantics |

## Questions the teardown must settle

1. Is the split between control plane and runtime plane a process boundary, or
   only a module boundary in v0.1? Two deployables cost operational complexity
   early.
2. Does the event bus carry authoritative state, or is it purely derived? (ADR-0003,
   ADR-0010 interact here.)
3. Where is policy enforced: control plane, runtime, or capability gateway? All
   three answers appear in the field. (`J10`, `I8`)
4. Who owns checkpointing when the adapted harness cannot checkpoint itself?
   (`E8`, ADR-0004)
5. Does the capability gateway sit inside or outside the sandbox boundary? (`I10`)
6. How is a lost worker detected, and by which component? (`S10`, Run state `LOST`)

## Security boundaries

Mark trust boundaries explicitly before implementation; retrofitting them is
how tenant leaks (`S8`) happen.

```text
[ untrusted: agent-generated content, tool output, model output ]
[ semi-trusted: adapter process ]
[ trusted: control plane, IAM, policy ]
```

Any network-exposed component in this diagram needs its authentication story
written down before it is built, not after.
