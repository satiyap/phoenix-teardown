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

// Unpaired UTF-16 surrogates are not characters; they exist only as pairs. Python
// raises UnicodeEncodeError on them while JSON.stringify happily emits an escape,
// so a lone surrogate would digest in one language and fail in the other. The
// profile rejects them explicitly rather than leaving the divergence latent.
function rejectLoneSurrogates(s, path) {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {                 // high
      const n = s.charCodeAt(i + 1);
      if (!(n >= 0xdc00 && n <= 0xdfff)) {
        throw new NonCanonical(`${path}: unpaired high surrogate at ${i}`);
      }
      i++;                                            // skip the valid pair
    } else if (c >= 0xdc00 && c <= 0xdfff) {          // lone low
      throw new NonCanonical(`${path}: unpaired low surrogate at ${i}`);
    }
  }
}

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
  if (typeof v === "string") { rejectLoneSurrogates(v, path); return nfc(v); }
  if (Array.isArray(v)) return v.map((x, i) => canon(x, `${path}[${i}]`));
  if (typeof v === "object") {
    const out = new Map();
    for (const k of Object.keys(v)) {
      rejectLoneSurrogates(k, `${path} (key)`);
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

// --- run the fixture, only when invoked directly ---
if (process.argv[2]) {
const fx = JSON.parse(readFileSync(process.argv[2], "utf8"));
let fail = 0, ok = 0;
const digests = {};
for (const row of fx.accept) {
  let got;
  try { got = canonicalDigest(row.payload, row.kind); }
  catch (e) { console.log(`  x #${row.n} threw in JS: ${e.message}`); fail++; continue; }
  digests[String(row.n)] = got;
  if (got !== row.digest) {
    console.log(`  x #${row.n} MISMATCH\n      py: ${row.digest}\n      js: ${got}`);
    fail++;
  } else ok++;
}
// Expand the symbolic placeholders strict JSON cannot express. The fixture
// documents these in its `symbolic_encoding` field.
const SURR_HI = String.fromCharCode(0xd800);
const SURR_LO = String.fromCharCode(0xdcff);

function subst(v) {
  if (v !== null && typeof v === "object" && !Array.isArray(v)) {
    const ks = Object.keys(v);
    if (ks.length === 1 && ks[0] === "__nonfinite__") {
      return v.__nonfinite__ === "nan" ? NaN : Infinity;
    }
    if (ks.length === 1 && ks[0] === "__surrogate__") {
      return v.__surrogate__ === "high" ? SURR_HI : SURR_LO;
    }
    if (ks.length === 1 && ks[0] === "__surrogate_key__") {
      const k = v.__surrogate_key__ === "high" ? SURR_HI : SURR_LO;
      return { [k]: 1 };
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
if (process.argv.includes("--json")) {
  // machine-readable, so `make spec` can compare Python and JS digests directly
  console.log(JSON.stringify({ digests }));
} else {
  console.log(`\nJS independent oracle: ${ok} agree, ${fail} disagree`);
}
process.exit(fail ? 1 : 0);
}
