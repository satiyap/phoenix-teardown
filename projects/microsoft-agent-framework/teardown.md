# Teardown — Microsoft Agent Framework

> Target length: 5–10 substantive pages. Cross-product synthesis matters more
> than exhaustive documentation. If a section has nothing decision-relevant,
> write "Nothing notable" and move on. Padding costs later reading time.

| | |
|---|---|
| Repo | |
| Commit read | |
| Version / tag | |
| Docs | |
| License | |
| Read on | |
| Evidence class | A / B / C |
| Depth | deep / targeted |
| Runtime class | worker_queue / durable_actor / attached_harness / in_process / hybrid |

**Evidence rule:** every architectural claim below cites `path/file.py:120 @ sha`
or `URL (read YYYY-MM-DD)`. Unsupported claims get marked `unknown` in
`facts.yaml`, not asserted here.

---

## 1. What problem it solves

Whose problem, and what they did before this existed.

## 2. Core architectural thesis

The single bet this system makes. One paragraph. If you cannot state the bet,
you have not finished reading.

## 3. Resource / object model

ASCII tree of resources that actually exist in the code or API. No aspirational
nodes.

```text
```

Then: what is the root resource, and what surprised you about the shape.

## 4. Runtime model

Who launches, who hosts, what the execution substrate is, who owns the event
loop. Diagram if it helps.

## 5. Execution lifecycle

The real state machine, using their state names.

```text
```

Note states they lack that you expect to need.

## 6. Durability model

What is durable, when it persists, how it recovers. The most important section
for our purposes — do not compress it.

## 7. Agent identity and lifecycle

Identity versus runtime instance. Versioning. Registry. Revocation.

## 8. Multi-agent communication

Messaging, delegation, RPC. Delivery guarantees. Ordering.

## 9. Human interaction model

How a human observes, intervenes, approves. Whether humans are modelled at all.

## 10. Context and memory

Enumerate the distinct concepts separately. Resist collapsing them into
"memory."

## 11. Tools and capabilities

Binding, scoping, credentials, interception.

## 12. Security and IAM

Principals, authN, authZ, secrets, isolation, audit. Include the S1 delegation
answer explicitly.

## 13. Sandboxing

Lifecycle, isolation technology, pluggability.

## 14. Orchestration

Topology, spawning, cancellation propagation. Whether Temporal or Restate could
replace it.

## 15. Observability

Event objects, keying, schema stability, cost accounting.

## 16. Multi-tenancy

Hierarchy, RBAC, quotas, and what is held back for a commercial tier.

## 17. Protocols and APIs

Verbatim endpoint or SDK surface. Standards implemented.

## 18. Storage

Required datastores. What is authoritative versus derived.

## 19. Deployment architecture

How it actually runs in production. Single binary, k8s, managed service.

## 20. OSS / license / commercial model

Answers to Q1–Q6, ending in a verdict: USE / INTEGRATE / REFERENCE_ONLY / AVOID.

## 21. Hard scenarios

Walk S1–S10. Be explicit where behaviour is undefined; undefined behaviour in a
mature system is a finding, not a gap in your reading.

| Scenario | Verdict | Notes |
|---|---|---|
| S1 Delegated authority | | |
| S2 Torn side effect | | |
| S3 Upgrade mid-flight | | |
| S4 Concurrent memory write | | |
| S5 Cancellation tree | | |
| S6 Silent context loss | | |
| S7 Poison message | | |
| S8 Tenant leak | | |
| S9 Runaway spend | | |
| S10 Zombie sandbox | | |

## 22. Strongest ideas

Things worth stealing. Be specific enough to act on.

## 23. Weakest architectural choices

Where this system will hurt its users, and why.

## 24. Reusable components

| Component | Decision | Reasoning |
|---|---|---|
| | REUSE / INTEGRATE / ADOPT_AS_STANDARD / BUILD | |

## 25. Lessons for our platform

Each lesson names an ADR it confirms, amends, or challenges. A teardown that
touches no ADR was either too shallow or covered ground already settled — say
which.

| ADR | Effect | Note |
|---|---|---|
| ADR-0001 | confirms / amends / challenges / neutral | |

## 26. Open questions

Anything unresolved. Mirror these into `open-questions.md` with an owner.
