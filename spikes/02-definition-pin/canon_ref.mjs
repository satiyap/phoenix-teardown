// INDEPENDENT reference implementation of nfc+intjson/v1, written from the
// normative text in spec/03-canonicalisation.md — NOT a port of pin.py.
//
// This is the oracle the fixture actually needs. Comparing the vectors against
// the Python that generated them proves only that Python is deterministic; the
// CLAIM is that a second language reproduces the digests. Review was right that
// the earlier check was circular.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const INT_SAFE = 9007199254740991n; // 2^53 - 1

class NonCanonical extends Error {}

function nfc(s) { return s.normalize("NFC"); }

// step 1: validate + normalise
function canon(v, path = "$") {
  if (v === null || typeof v === "boolean") return v;
  if (typeof v === "number") {
    if (!Number.isFinite(v)) throw new NonCanonical(`${path}: non-finite`);
    if (!Number.isInteger(v)) throw new NonCanonical(`${path}: non-integral ${v}`);
    if (BigInt(Math.abs(v)) > INT_SAFE) throw new NonCanonical(`${path}: too large`);
    return v === 0 ? 0 : v;               // -0 -> 0
  }
  if (typeof v === "string") return nfc(v);
  if (Array.isArray(v)) return v.map((x, i) => canon(x, `${path}[${i}]`));
  if (typeof v === "object") {
    const out = new Map();
    for (const k of Object.keys(v)) {
      const nk = nfc(k);
      if (out.has(nk)) throw new NonCanonical(`${path}: NFC key collision on ${nk}`);
      out.set(nk, canon(v[k], `${path}.${nk}`));
    }
    return out;
  }
  throw new NonCanonical(`${path}: unsupported ${typeof v}`);
}

// step 2: emit with UTF-8 BYTE order for keys
const enc = new TextEncoder();
function cmpUtf8(a, b) {
  const x = enc.encode(a), y = enc.encode(b);
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i++) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
}
function emit(v) {
  if (v instanceof Map) {
    const keys = [...v.keys()].sort(cmpUtf8);
    return "{" + keys.map(k => JSON.stringify(k) + ":" + emit(v.get(k))).join(",") + "}";
  }
  if (Array.isArray(v)) return "[" + v.map(emit).join(",") + "]";
  if (typeof v === "string") return JSON.stringify(v);
  if (typeof v === "boolean") return v ? "true" : "false";
  if (v === null) return "null";
  if (typeof v === "number") return String(v);
  throw new NonCanonical("emit: unexpected");
}

export function canonicalDigest(obj, kind = "generic") {
  const envelope = new Map([
    ["kind", kind],
    ["canonicalization", "nfc+intjson/v1"],
    ["payload", canon(obj)],
  ]);
  return createHash("sha256").update(emit(envelope), "utf8").digest("hex");
}

// --- run the fixture ---
const fx = JSON.parse(readFileSync(process.argv[2], "utf8"));
let fail = 0, ok = 0;
for (const row of fx.accept) {
  let got;
  try { got = canonicalDigest(row.payload, row.kind); }
  catch (e) { console.log(`  x #${row.n} threw in JS: ${e.message}`); fail++; continue; }
  if (got !== row.digest) {
    console.log(`  x #${row.n} MISMATCH\n      py: ${row.digest}\n      js: ${got}`);
    fail++;
  } else ok++;
}
// A reject case {"__nonfinite__": "nan"|"inf"} denotes a value strict JSON cannot
// express. Substitute this language's equivalent before asserting rejection.
function subst(v) {
  if (v !== null && typeof v === "object" && !Array.isArray(v)) {
    const ks = Object.keys(v);
    if (ks.length === 1 && ks[0] === "__nonfinite__") {
      return v.__nonfinite__ === "nan" ? NaN : Infinity;
    }
    const out = {};
    for (const k of ks) out[k] = subst(v[k]);
    return out;
  }
  return v;
}

for (const row of fx.reject) {
  try {
    canonicalDigest(subst(row.case), row.kind);
    console.log(`  x reject case ACCEPTED by JS: ${JSON.stringify(row.case)}`);
    fail++;
  } catch { ok++; }
}
console.log(`\nJS independent oracle: ${ok} agree, ${fail} disagree`);
process.exit(fail ? 1 : 0);
