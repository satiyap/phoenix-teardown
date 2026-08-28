#!/usr/bin/env bash
# Fetch the pinned gVisor binaries and verify them against BOTH upstream's
# .sha512 files and our own PINNED.json sha256 digests.
#
# The binaries are 140MB of vendored upstream, so they are gitignored; the
# DIGESTS are tracked. A verification step that only checked the version string
# would accept a different binary under the same name -- the same defect spike 06
# was pulled up on ("a pin that is not asserted is a comment").
set -euo pipefail

VERSION="release-20260817.0"
DATE_PATH="20260817.0"
cd "$(dirname "$0")"

case "$(uname -m)" in
  arm64|aarch64) ARCH=aarch64 ;;
  x86_64|amd64)  ARCH=x86_64 ;;
  *) echo "unsupported arch $(uname -m)" >&2; exit 1 ;;
esac

URL="https://storage.googleapis.com/gvisor/releases/release/${DATE_PATH}/${ARCH}"
mkdir -p runsc-bin
cd runsc-bin

for f in runsc containerd-shim-runsc-v1; do
  [ -f "$f" ] || curl -fsSL -o "$f" "$URL/$f"
  curl -fsSL -o "$f.sha512" "$URL/$f.sha512"
  shasum -a 512 -c "$f.sha512" >/dev/null || { echo "UPSTREAM CHECKSUM FAILED: $f" >&2; exit 1; }
  chmod 755 "$f"
done

python3 - <<'PY'
import hashlib, json, pathlib, sys
spec = json.loads(pathlib.Path("PINNED.json").read_text())
if spec["_arch"] != {"arm64":"aarch64","aarch64":"aarch64"}.get(__import__("platform").machine(), "x86_64"):
    print(f"NOTE: PINNED.json pins {spec['_arch']}; digests apply to that arch only")
bad = []
for name, want in spec["files"].items():
    got = hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest()
    if got != want:
        bad.append(f"{name}: expected {want[:16]}... got {got[:16]}...")
if bad:
    print("PIN MISMATCH"); [print(" ", b) for b in bad]; sys.exit(1)
print(f"pin holds: {len(spec['files'])} gVisor binaries, {spec['_version']}")
PY
