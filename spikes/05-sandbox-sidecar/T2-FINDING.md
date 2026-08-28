# T2 — a Unix socket on a shared `emptyDir` is invisible to the sibling container under gVisor

**Status: FINDING, not a config slip.** Recorded rather than worked around, per instruction.
**Date:** 2026-08-28 · gVisor `release-20260817.0`, systrap, k3s v1.35.5+k3s1, single node, arm64.

## Invariant under test

> In one gVisor pod, the Go driver and the Python sidecar exchange `spec/07` frames over a
> **pod-local** Unix socket on a shared `emptyDir`. The socket never crosses the sandbox
> boundary, so no `host-uds` flag is involved.

The expectation going in — one Sentry per pod, both containers and the volume inside the same
sandbox — was explicit. **It does not hold.**

## What happens

Container A binds `/run/phoenix/a.sock`, chmods it `0600`, listens, and **holds it open**.
Container B mounts the same `emptyDir` at the same path.

| Observation | Container A | Container B |
|---|---|---|
| `ls -la /run/phoenix/` | `srw------- a.sock` **and** `from-a.txt` | **`from-a.txt` only** |
| `os.listdir` | `['a.sock', 'from-a.txt']` | `['from-a.txt']` |
| `os.lstat('a.sock')` | ok | `FileNotFoundError` |
| `connect()` | — | `FileNotFoundError` |

A **regular file** written by A propagates to B on the same volume. The **socket inode does
not appear at all** — this is not a permission or connect failure, the path does not exist
from B's view.

## The negative control that makes it a gVisor finding

The identical pod with **only `runtimeClassName: gvisor` removed**:

```
kernel:   Linux version 6.19.7-200.fc43.aarch64      <- runc, host kernel
listdir:  ['a.sock', 'from-a.txt']                   <- the socket IS there
connect:  CONNECT_OK b'PONG'                         <- and it works
```

Same manifest, same image, same volume, same code. runc propagates the socket; gVisor does not.

## Bisection — what it is not

| Hypothesis | Test | Result |
|---|---|---|
| busybox `nc` lacks `-U` | reran with Python `AF_UNIX` | still fails; the first `DIAL_FAIL` **was** a tooling artefact and was discarded |
| container start race | 60s retry loop polling existence | still fails — "socket never appeared within 60s" |
| A exited and cleaned up its socket | A holds the socket open in `accept()` for the pod's life | still invisible to B |
| gVisor's overlay upper layer | `overlay2 = "none"` | **no change** |
| mount coherence validation | `file-access-mounts = "shared"` | **no change** |
| propagation broken generally | regular file `from-a.txt` written by A | **visible in B** — so only the socket inode is affected |

Two documented `runsc` options that could plausibly govern this were tried and neither changed
the behaviour. No undocumented flag was hunted for, and no workaround was adopted.

## Consequence for the specified topology

`ADR-0016:63`, `ADR-0004:133` and `spec/01`'s `sdk_sidecar` specify the Go driver and the Python
sidecar in **one pod** exchanging §07 frames over a **pod-local Unix socket**. On this gVisor
version that transport **does not work between two containers of the same pod**.

This is a genuine conflict between the decided design and the decided provider. It is not
something this spike can resolve by choosing differently, because both halves were decided
elsewhere. It is filed as an OQ with the options named and no decision taken:

- **single container, two processes — TESTED, WORKS.** With both roles in one container the UDS
  works under gVisor at `0600`, on the `emptyDir` mount *and* on `/tmp`:

  ```
  kernel: Linux version 4.19.0-gvisor #1
  /run/phoenix: CONNECT_OK mode=0o600 reply=b'PONG:HI'
  /tmp:         CONNECT_OK mode=0o600 reply=b'PONG:HI'
  ```

  So the defect is **specifically cross-container inode propagation**, not gVisor's UDS support
  and not the volume. This is the option that keeps the pod-local-UDS decision intact, at the
  cost of one container running two processes — which changes the *packaging* (one image, two
  entrypoints, or a supervisor) but not the §07 boundary, the auth model, or the ledger. It is
  the recommended resolution;
- **pod-local TCP on loopback** — containers in a pod share a network namespace, so this is
  still pod-local and never leaves the sandbox, but it discards `0600` ownership as auth and
  needs `run_token` to carry the whole burden;
- **a newer gVisor**, if this is fixed upstream;
- **a different RuntimeClass for the sidecar pod**, which the RuntimeClass-per-pod rule forbids
  in the two-container form.

## What this does NOT invalidate

- **T1 passes**: RuntimeClass admission by a real kubelet, and the Sentry banner in a real pod,
  each with a negative control. The substrate is sound.
- The **finding itself** is only reachable because the substrate was proven first. Under the
  previous Podman attempt this would have been invisible: that build put the driver on the host
  and used `host-uds=all`, which is precisely the flag that makes a host socket reachable and
  the reason the earlier gates "passed".
