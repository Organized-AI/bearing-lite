"use strict";

/**
 * Shared, dependency-free helpers for the `validator` backend.
 *
 * A validator is a deterministic program, not a model: the same input bytes
 * always give the same decision record, with no probability. Nothing here
 * reads the clock, the environment, the network, or randomness. Validator
 * rubrics pin this file by SHA-256, so any edit is a new rubric version.
 */

const crypto = require("node:crypto");

const isPlainObject = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);

const hasOwn = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

function sha256Hex(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

/**
 * RFC 8785 JSON Canonicalization Scheme. Object keys sort by UTF-16 code
 * units (what Array#sort compares); strings and numbers serialize as
 * ECMAScript JSON.stringify does, which is what RFC 8785 specifies. For JSON
 * values this equals hooks/verification-bridge.cjs canonicalJson.
 * @param {unknown} value
 * @returns {string}
 */
function jcs(value) {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("RFC 8785 forbids NaN and Infinity");
    return JSON.stringify(value);
  }
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(jcs).join(",") + "]";
  if (isPlainObject(value)) {
    return "{" + Object.keys(value).sort().map((k) => JSON.stringify(k) + ":" + jcs(value[k])).join(",") + "}";
  }
  throw new TypeError("not a JSON value: " + typeof value);
}

/**
 * A typed input failure. `reason` is one of the validator ERROR reasons in
 * schemas/system1.schema.json (`input_unparseable`, `input_shape_invalid`,
 * `toml_unsupported_construct`).
 */
class InputError extends Error {
  constructor(reason, detail) {
    super(detail);
    this.reason = reason;
  }
}

/**
 * Decode strict UTF-8. Invalid bytes are unparseable, never replaced. A byte
 * order mark is kept, so the parsers reject it as JSON.parse and Python's
 * tomllib do.
 */
function decodeUtf8(bytes) {
  try {
    return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new InputError("input_unparseable", "input is not valid UTF-8");
  }
}

const setOwn = (obj, key, value) =>
  Object.defineProperty(obj, key, { value, enumerable: true, writable: true, configurable: true });

/**
 * Parse JSONC: strict JSON (RFC 8259) plus `//` and block comments and
 * trailing commas, the dialect wrangler.jsonc uses. With `strict`, comments
 * and trailing commas are refused too (plain JSON). A duplicate key keeps its
 * last value, as JSON.parse does. Anything else is `input_unparseable`, with a
 * message this module writes, so an ERROR decision record is the same on
 * every Node version.
 * @param {string} text
 * @param {{strict?: boolean}} [options]
 */
function parseJsonc(text, options = {}) {
  const strict = options.strict === true;
  const dialect = strict ? "JSON" : "JSONC";
  let i = 0;
  const n = text.length;
  const fail = (msg) => {
    throw new InputError("input_unparseable", `${dialect}: ${msg} at offset ${i}`);
  };
  function ws() {
    for (;;) {
      while (i < n && (text[i] === " " || text[i] === "\t" || text[i] === "\r" || text[i] === "\n")) i += 1;
      if (strict) return;
      if (text.startsWith("//", i)) {
        while (i < n && text[i] !== "\n") i += 1;
      } else if (text.startsWith("/*", i)) {
        const end = text.indexOf("*/", i + 2);
        if (end < 0) fail("unterminated block comment");
        i = end + 2;
      } else return;
    }
  }
  function string() {
    const start = i;
    i += 1;
    while (i < n && text[i] !== '"') {
      if (text.charCodeAt(i) < 0x20) fail("control character in string");
      i += text[i] === "\\" ? 2 : 1;
    }
    if (i >= n) fail("unterminated string");
    i += 1;
    try {
      return JSON.parse(text.slice(start, i));
    } catch {
      return fail("invalid string escape");
    }
  }
  function value(depth) {
    if (depth > 256) fail("nesting too deep");
    ws();
    const c = text[i];
    if (c === "{") {
      i += 1;
      const obj = {};
      ws();
      while (text[i] !== "}") {
        if (text[i] !== '"') fail("expected a string key");
        const key = string();
        ws();
        if (text[i] !== ":") fail("expected ':'");
        i += 1;
        setOwn(obj, key, value(depth + 1));
        ws();
        if (text[i] === ",") {
          i += 1;
          ws();
          if (strict && text[i] === "}") fail("trailing comma");
        } else if (text[i] !== "}") fail("expected ',' or '}'");
      }
      i += 1;
      return obj;
    }
    if (c === "[") {
      i += 1;
      const arr = [];
      ws();
      while (text[i] !== "]") {
        arr.push(value(depth + 1));
        ws();
        if (text[i] === ",") {
          i += 1;
          ws();
          if (strict && text[i] === "]") fail("trailing comma");
        } else if (text[i] !== "]") fail("expected ',' or ']'");
      }
      i += 1;
      return arr;
    }
    if (c === '"') return string();
    const m = /^(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)/.exec(text.slice(i, i + 400));
    if (!m) fail("unexpected token");
    i += m[0].length;
    const v = JSON.parse(m[0]);
    if (typeof v === "number" && !Number.isFinite(v)) fail("number out of range");
    return v;
  }
  const out = value(0);
  ws();
  if (i !== n) fail("trailing content");
  return out;
}

/** Strict JSON (RFC 8259): no comments, no trailing commas. */
function parseJson(text) {
  return parseJsonc(text, { strict: true });
}

/**
 * Condition-list decision. Each pair is [condition_id, true | false | null];
 * null means "not evaluated because a prerequisite failed". VERIFIED iff no
 * condition is false.
 */
function conditionDecision(pairs) {
  const conditions = pairs.map(([id, holds]) => ({ id, holds }));
  const failed = conditions.filter((c) => c.holds === false).map((c) => c.id);
  return { verdict: failed.length === 0 ? "VERIFIED" : "REFUTED", conditions, failed_conditions: failed };
}

module.exports = {
  isPlainObject,
  hasOwn,
  setOwn,
  sha256Hex,
  jcs,
  InputError,
  decodeUtf8,
  parseJsonc,
  parseJson,
  conditionDecision,
};
