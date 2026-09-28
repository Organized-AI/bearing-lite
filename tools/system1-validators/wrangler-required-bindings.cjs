"use strict";

/**
 * Validator `wrangler-required-bindings` (backend `validator`).
 *
 * Rule text (the three conditions of RUB-S1-WRANGLER-REQUIRED-BINDINGS,
 * decided exactly instead of asked of a model). Binding names are
 * case-sensitive and must match exactly:
 *   (1) the d1_databases array contains an entry whose binding is exactly "DB"
 *       with a non-empty database_id;
 *   (2) the kv_namespaces array contains an entry whose binding is exactly
 *       "CACHE" with a non-empty id;
 *   (3) the r2_buckets array contains an entry whose binding is exactly
 *       "ASSETS" with a non-empty bucket_name.
 * "Non-empty" means a string other than "". Only the top-level arrays count:
 * `env.<name>` sections are parsed but not read, so a binding that exists only
 * under an environment does not satisfy the rule.
 *
 * Input: a whole wrangler configuration file. `.jsonc` and `.json` are JSONC
 * (comments and trailing commas allowed); `.toml` is the TOML subset in
 * toml.cjs. The format comes from the file extension, never from sniffing.
 * Canonical form: RFC 8785 JCS of the object holding only the top-level
 * d1_databases, kv_namespaces and r2_buckets keys (absent stays absent), the
 * same bytes the Laya rubric's `jsonc_to_rfc8785_jcs` extraction produced.
 * Unparseable input is ERROR `input_unparseable`; a TOML construct outside the
 * subset is ERROR `toml_unsupported_construct`; a JSON document whose top level
 * is not an object is ERROR `input_shape_invalid`.
 */

const { InputError, isPlainObject, hasOwn, jcs, parseJsonc, conditionDecision } = require("./lib.cjs");
const { parseToml } = require("./toml.cjs");

const VALIDATOR_ID = "wrangler-required-bindings";
const VALIDATOR_VERSION = "1.0.0";

const RULE_TEXT =
  "Binding names are case-sensitive and must match exactly. The configuration conforms iff: (1) the top-level " +
  'd1_databases array contains an entry whose binding is exactly "DB" with a non-empty database_id; (2) the ' +
  'top-level kv_namespaces array contains an entry whose binding is exactly "CACHE" with a non-empty id; (3) the ' +
  'top-level r2_buckets array contains an entry whose binding is exactly "ASSETS" with a non-empty bucket_name. ' +
  '"Non-empty" means a string other than "". env.<name> sections are not read.';

const REQUIRED = Object.freeze([
  { array: "d1_databases", binding: "DB", idKey: "database_id" },
  { array: "kv_namespaces", binding: "CACHE", idKey: "id" },
  { array: "r2_buckets", binding: "ASSETS", idKey: "bucket_name" },
]);
const BINDING_KEYS = Object.freeze(REQUIRED.map((r) => r.array));

const CONDITIONS = Object.freeze(
  REQUIRED.flatMap((r, k) => [
    { id: `${r.array}_is_array`, text: `(${k + 1}) top-level ${r.array} is an array.` },
    {
      id: `${r.array}_has_${r.binding}`,
      text: `(${k + 1}) ${r.array} has an object entry whose binding is exactly "${r.binding}" (evaluated when it is an array).`,
    },
    {
      id: `${r.array}_${r.binding}_${r.idKey}_nonempty`,
      text: `(${k + 1}) an entry bound "${r.binding}" has a non-empty string ${r.idKey} (evaluated when such an entry exists).`,
    },
  ])
);

const FORMAT_BY_EXTENSION = Object.freeze({ ".jsonc": "jsonc", ".json": "jsonc", ".toml": "toml" });

/** Keep only the three binding arrays (absent stays absent). */
function extractBindings(config) {
  const out = {};
  for (const k of BINDING_KEYS) if (hasOwn(config, k)) out[k] = config[k];
  return out;
}

/**
 * @param {string} text
 * @param {string} format `jsonc` or `toml` (from the file extension)
 */
function canonicalize(text, format) {
  let config;
  if (format === "jsonc") config = parseJsonc(text);
  else if (format === "toml") config = parseToml(text);
  else throw new InputError("input_unresolvable", `no wrangler format for ${JSON.stringify(format)}`);
  if (!isPlainObject(config)) {
    throw new InputError("input_shape_invalid", "a wrangler configuration's top level must be an object");
  }
  const state = extractBindings(config);
  return { format, canonical: jcs(state), state };
}

/** Decide the rule over the extracted bindings object. */
function evaluateBindings(state) {
  const pairs = [];
  for (const r of REQUIRED) {
    const arr = hasOwn(state, r.array) ? state[r.array] : undefined;
    const isArray = Array.isArray(arr);
    pairs.push([`${r.array}_is_array`, isArray]);
    const entries = isArray ? arr.filter((e) => isPlainObject(e) && e.binding === r.binding) : [];
    const has = isArray ? entries.length > 0 : null;
    pairs.push([`${r.array}_has_${r.binding}`, has]);
    pairs.push([
      `${r.array}_${r.binding}_${r.idKey}_nonempty`,
      has ? entries.some((e) => hasOwn(e, r.idKey) && typeof e[r.idKey] === "string" && e[r.idKey] !== "") : null,
    ]);
  }
  return conditionDecision(pairs);
}

module.exports = {
  VALIDATOR_ID,
  VALIDATOR_VERSION,
  RULE_TEXT,
  CONDITIONS,
  FORMATS: Object.freeze(["jsonc", "toml"]),
  FORMAT_BY_EXTENSION,
  canonicalize,
  evaluate: evaluateBindings,
  extractBindings,
};
