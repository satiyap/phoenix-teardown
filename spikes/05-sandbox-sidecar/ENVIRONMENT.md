# Spike 05 environment — proven, not assumed

Every line below was verified before any gate was written. The previous attempt's
central error was building on an unverified substrate: `--runtime=runsc` under
Podman **silently ran runc**, so isolation gates would have passed against a
container with no gVisor in it.

## Stack

| Component | Value | How it was proven |
|---|---|---|
| Cluster | k3d v5.9.0 / k3s v1.35.5+k3s1, cluster `phoenix-spike05` | `kubectl get nodes` ⇒ Ready |
| Node arch | linux/arm64 | `docker info` |
| gVisor | `release-20260817.0`, aarch64 | `runsc --version` inside the node |
| Binaries | `runsc`, `containerd-shim-runsc-v1` | upstream `.sha512` **and** `PINNED.json` sha256, enforced by `fetch-runsc.sh` |
| Platform | **systrap** (no KVM, no ptrace) | `/etc/containerd/runsc.toml` |
| containerd handler | registered | **`crictl info | grep runsc`** ⇒ handler present with `ConfigPath` |
| RuntimeClass | `gvisor` → handler `runsc` | `kubectl get runtimeclass` |

## Handler registration — a drop-in, not a template override

k3s generates containerd **config version 3** with
`imports = [".../config-v3.toml.d/*.toml"]`. The handler is therefore a drop-in at
`/var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.d/runsc.toml`, so k3s keeps
ownership of everything else it generates. The `config.toml.tmpl` override the hand-off
mentioned is unnecessary on this k3s version.

`runsc` is auto-detected on `PATH` only if the binary is there at containerd start, so
`/usr/local/bin/runsc` is symlinked to the mounted copy and the node is restarted.

## T1 — the Sentry sentinel, with its negative control

```
$ kubectl logs t1-gvisor            # runtimeClassName: gvisor
[   0.000000] Starting gVisor...
[   0.175621] Granting licence to kill(2)...
Linux version 4.19.0-gvisor #1 SMP Sun Jan 10 15:06:54 PST 2016

$ kubectl logs t1-no-rc             # NO runtimeClassName
Linux version 6.19.7-200.fc43.aarch64 ... #1 SMP PREEMPT_DYNAMIC
```

The control is the point: the same pod spec without `runtimeClassName` reports the
**host** kernel. Any gate asserting isolation must be able to tell those apart, and the
previous attempt could not.

## Known-bad reproduced (rule 2)

Under Podman, `--runtime=runsc` with no `runsc` binary installed **ran runc and reported
success** — `/proc/version` showed the host Fedora kernel with no error. That is the
failure T1 exists to catch, and it is why `crictl info` is checked before any gate.
