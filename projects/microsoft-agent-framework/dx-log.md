# DX log — Microsoft Agent Framework

Targeted pass, 2026-08-26. Installed the Python core and reproduced the
signature-hash mechanism; did not run the test suites.

- `pip install agent-framework-core` to inspecting the checkpoint type: **~70 seconds**
- Reproducing `graph_signature_hash` independently: ~5 minutes

## Timeline

| Elapsed | What I did | What happened |
|---|---|---|
| 0:00 | Cloned; found `declarative-agents/`, three language trees, 35 Python packages | Wide surface; needed the targeted scope to stay useful |
| 0:04 | Listed `_workflows/` | `_checkpoint.py`, `_edge.py`, `_request_info_mixin.py` — the pass's targets |
| 0:08 | Read `_checkpoint.py` | **`graph_signature_hash` — "to validate checkpoint compatibility during restore."** The thing thirteen projects lacked |
| 0:13 | Grepped for enforcement | `_functional.py:987` raises on mismatch. Not just recorded — checked |
| 0:18 | Read `_compute_signature_hash` | It hashes **bytecode**, with a comment explaining why name discovery is insufficient |
| 0:24 | `pip install`, inspected `WorkflowCheckpoint` | 11 fields confirmed live, including `previous_checkpoint_id` and `version` |
| 0:31 | Wrote a script to reproduce the hash | Identical body → same hash; changed body → different. **Verified** |
| 0:38 | Read `_edge.py` | Typed edge groups: single, fan-out, fan-in, switch-case with `Default` |
| 0:44 | Found `_validation.py` and `_viz.py` | A graph you can check and draw — because topology is data |
| 0:50 | Read `purview/README.md` | Ingress **and** egress content policy, centrally managed |
| 0:56 | Looked at a declarative agent YAML | `approvalMode` and `allowedTools` in the manifest |
| 1:02 | Searched for agent revocation | Nothing. Thirteen projects |

## Friction points

1. **Scale demands a scope decision up front.** 75MB, three language SDKs, 35 Python
   packages, plus `lab/` and `monty/` shipped alongside stable code. Without the
   pre-committed targeted scope (F, L, D9, D10) this pass would have sprawled and
   produced less. The cost is honest: 52 probes stay `unknown`.
2. **Stability is not visible from the package list.** `_feature_stage.py` exists and
   is a good idea, but `lab/`, `monty/`, and preview packages sit beside production
   ones in the same directory. ADK's approach — putting stability in the *import
   path* — makes the same information legible without opening files.
3. **The best governance story needs a subscription.** `agent-framework-purview` is
   the only bidirectional content-policy implementation in the study and it requires
   Azure Purview, so I could read its contract but not exercise it.
4. **I could not find an escape hatch for the signature hash.** A comment-only edit
   changes bytecode and therefore invalidates checkpoints. That is the safe
   direction, but a deliberate compatible change appears to have no supported path
   (OQ-037).

## What was genuinely good

1. **A docstring that states what a checkpoint is *not* tied to.** "Note that a
   checkpoint is not tied to a specific workflow instance, but rather to a workflow
   definition… This allows checkpoints to be shared and restored across different
   workflow instances." That sentence taught me a property I had not thought to want,
   and it is in the type's docstring rather than a design doc.
2. **A comment that justifies the mechanism.** "The code digest catches body changes
   that step-name discovery misses (e.g. attribute-access step references)." It
   explains why the obvious implementation (hash the discovered node names) is
   insufficient. That is the single most useful comment I read in this study.
3. **Documenting a field's non-uniqueness with the case that breaks it.**
   `iteration_count` "is not guaranteed to be unique… For example, a run that pauses
   at `IDLE_WITH_PENDING_REQUESTS` records a checkpoint after superstep…". Someone
   anticipated the wrong assumption and pre-empted it.
4. **An error message that names the likely cause**, not just the failure: "The
   workflow's step structure may have changed since this checkpoint was saved."
5. **Topology as data.** Because edges are declared objects, `_validation.py` can
   check the graph before it runs and `_viz.py` can draw it. Both are consequences of
   one design choice.
6. **Canonical JSON for the digest** (`sort_keys=True`, tight separators), so the
   hash is reproducible — which is what let me verify the claim independently.
7. **`approvalMode` and `allowedTools` in the manifest.** Tool scope and approval
   policy travel with the declared agent rather than living in runtime config.

## Answers to R1–R7

- **R1 install to running:** ~70s for `agent-framework-core`.
- **R2 concepts before hello world:** an agent is small; the workflow model adds
  executors, edge groups, supersteps and checkpoints, and the package surface is
  large.
- **R3 local dev loop:** good — `devui` for a local UI, `_viz.py` to see the graph
  before running it.
- **R4 debugging:** strong. Graph validation up front, visualisation, typed superstep
  events, and a checkpoint chain that supports time-travel.
- **R5 unit testing:** extensive per-package tests exist; I ran none, but the
  signature hash was verifiable in isolation, which is itself a sign of good
  factoring.
- **R6 deployment:** many targets — `foundry_hosting`, `foundry_local`, `hosting-*`,
  three language SDKs, `hyperlight`.
- **R7 CLI ergonomics:** `devui` is the developer surface; no agent-management CLI
  examined.

## Lessons for our own DX

**Comment the mechanism, not the behaviour.** The bytecode-digest comment explains
why the naive approach fails. That is the comment that changed my design — not the
docstring describing what the function returns. Where we make a non-obvious
implementation choice, the comment should say what the obvious choice would have
missed.

**Make the pin reproducible on purpose.** MAF's canonical JSON digest let me
independently recompute the hash and verify the guarantee in five minutes. A pin
computed with unstable serialisation would have been unverifiable, and I would have
had to trust the comment. Guarantees that outsiders can check are worth more than
guarantees they must believe.

**Anticipate the wrong assumption in the docstring.** Two fields here document what
they are *not*: a checkpoint is not instance-bound, and `iteration_count` is not
unique. Both are exactly the assumptions a reader would otherwise make. Our
`Run`/`Approval`/pin fields should do the same.
