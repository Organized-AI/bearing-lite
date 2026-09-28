"use strict";

/**
 * Minimal TOML reader for the subset wrangler.toml uses. Dependency-free.
 *
 * Supported (TOML 1.0 semantics): comments; blank lines; bare, quoted and
 * dotted keys; `[table]` and `[[array.of.tables]]` headers (dotted, quoted);
 * basic strings with the TOML 1.0 escapes; literal strings; decimal integers
 * (sign, `_` separators, within the IEEE-754 safe range); decimal floats;
 * booleans; arrays (multi-line, trailing comma, comments); inline tables.
 *
 * Outside the subset, and therefore `toml_unsupported_construct` (never a
 * guess): multi-line strings, offset/local dates and times, hex/octal/binary
 * integers, `inf`/`nan`, and integers outside +/-(2^53 - 1). Text that is not
 * valid TOML (a redefined key or table, a bad escape, a missing `=`) is
 * `input_unparseable`.
 */

const { InputError, isPlainObject, hasOwn, setOwn } = require("./lib.cjs");

const BARE_KEY = /^[A-Za-z0-9_-]+/;
const SUPPORTED_SUBSET =
  "comments, bare/quoted/dotted keys, [table] and [[array-of-tables]] headers, basic and literal strings, " +
  "decimal integers and floats, booleans, arrays, inline tables";

/**
 * @param {string} text
 * @returns {Record<string, unknown>}
 */
function parseToml(text) {
  let i = 0;
  const n = text.length;
  const invalid = (msg) => {
    throw new InputError("input_unparseable", `TOML: ${msg} at offset ${i}`);
  };
  const unsupported = (what) => {
    throw new InputError(
      "toml_unsupported_construct",
      `TOML: ${what} at offset ${i} is outside the supported subset (${SUPPORTED_SUBSET})`
    );
  };

  const root = {};
  const explicitTables = new Set(); // [table] headers already opened, by key path
  const arrayTables = new WeakSet(); // arrays created by [[header]]
  const closed = new WeakSet(); // inline tables and static arrays: never extended
  const dottedMade = new WeakSet(); // tables created by dotted keys; a [header] may not reopen them

  const spaces = () => {
    while (i < n && (text[i] === " " || text[i] === "\t")) i += 1;
  };
  const comment = () => {
    if (text[i] !== "#") return;
    while (i < n && text[i] !== "\n" && !(text[i] === "\r" && text[i + 1] === "\n")) {
      const code = text.charCodeAt(i);
      if ((code < 0x20 && code !== 0x09) || code === 0x7f) invalid("control character in comment");
      i += 1;
    }
  };
  const newline = () => {
    if (text[i] === "\n") {
      i += 1;
      return true;
    }
    if (text[i] === "\r" && text[i + 1] === "\n") {
      i += 2;
      return true;
    }
    return false;
  };
  const endOfLine = () => {
    spaces();
    comment();
    if (i >= n) return;
    if (!newline()) invalid("expected end of line");
  };
  const blankLines = () => {
    for (;;) {
      spaces();
      comment();
      if (!newline()) return;
    }
  };

  function basicString() {
    if (text.startsWith('"""', i)) unsupported("a multi-line basic string");
    i += 1;
    let out = "";
    while (i < n && text[i] !== '"') {
      const c = text[i];
      const code = text.charCodeAt(i);
      if (c === "\n" || c === "\r") invalid("newline in a basic string");
      if ((code < 0x20 && code !== 0x09) || code === 0x7f) invalid("control character in a basic string");
      if (c !== "\\") {
        out += c;
        i += 1;
        continue;
      }
      const e = text[i + 1];
      const simple = { '"': '"', "\\": "\\", b: "\b", t: "\t", n: "\n", f: "\f", r: "\r" }[e];
      if (simple !== undefined) {
        out += simple;
        i += 2;
      } else if (e === "u" || e === "U") {
        const len = e === "u" ? 4 : 8;
        const hex = text.slice(i + 2, i + 2 + len);
        if (hex.length !== len || !/^[0-9A-Fa-f]+$/.test(hex)) invalid("bad unicode escape");
        const cp = parseInt(hex, 16);
        if (cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) invalid("escape is not a Unicode scalar value");
        out += String.fromCodePoint(cp);
        i += 2 + len;
      } else invalid("invalid escape");
    }
    if (i >= n) invalid("unterminated basic string");
    i += 1;
    return out;
  }

  function literalString() {
    if (text.startsWith("'''", i)) unsupported("a multi-line literal string");
    i += 1;
    const start = i;
    while (i < n && text[i] !== "'") {
      const code = text.charCodeAt(i);
      if (text[i] === "\n" || text[i] === "\r") invalid("newline in a literal string");
      if ((code < 0x20 && code !== 0x09) || code === 0x7f) invalid("control character in a literal string");
      i += 1;
    }
    if (i >= n) invalid("unterminated literal string");
    const s = text.slice(start, i);
    i += 1;
    return s;
  }

  function key() {
    const parts = [];
    for (;;) {
      spaces();
      if (text[i] === '"') parts.push(basicString());
      else if (text[i] === "'") parts.push(literalString());
      else {
        const m = BARE_KEY.exec(text.slice(i, i + 256));
        if (!m) invalid("expected a key");
        parts.push(m[0]);
        i += m[0].length;
      }
      spaces();
      if (text[i] !== ".") return parts;
      i += 1;
    }
  }

  function scalar() {
    const rest = text.slice(i, i + 64);
    const word = /^(true|false)(?=$|[\s,\]}#])/.exec(rest);
    if (word) {
      i += word[1].length;
      return word[1] === "true";
    }
    if (/^[0-9]{4}-[0-9]{2}-[0-9]{2}/.test(rest) || /^[0-9]{2}:[0-9]{2}:[0-9]{2}/.test(rest)) {
      unsupported("a date or time value");
    }
    if (/^[+-]?(inf|nan)(?=$|[\s,\]}#])/.test(rest)) unsupported("an inf or nan float");
    if (/^[+-]?0[xob]/.test(rest)) unsupported("a hexadecimal, octal or binary integer");
    const num = /^[+-]?(0|[1-9](?:_?[0-9])*)(\.[0-9](?:_?[0-9])*)?([eE][+-]?[0-9](?:_?[0-9])*)?(?=$|[\s,\]}#])/.exec(rest);
    if (!num) invalid("unrecognised value");
    i += num[0].length;
    const digits = num[0].replace(/_/g, "");
    const isFloat = num[2] !== undefined || num[3] !== undefined;
    const v = Number(digits);
    if (!isFloat && !Number.isSafeInteger(v)) unsupported("an integer outside +/-(2^53 - 1)");
    if (!Number.isFinite(v)) invalid("float out of range");
    return v;
  }

  function value(depth) {
    if (depth > 128) invalid("nesting too deep");
    const c = text[i];
    if (c === '"') return basicString();
    if (c === "'") return literalString();
    if (c === "[") {
      i += 1;
      const arr = [];
      closed.add(arr);
      blankLines();
      while (text[i] !== "]") {
        if (i >= n) invalid("unterminated array");
        arr.push(value(depth + 1));
        blankLines();
        if (text[i] === ",") {
          i += 1;
          blankLines();
        } else if (text[i] !== "]") invalid("expected ',' or ']' in an array");
      }
      i += 1;
      return arr;
    }
    if (c === "{") {
      i += 1;
      const tbl = {};
      spaces();
      if (text[i] === "}") {
        i += 1;
        closed.add(tbl);
        return tbl;
      }
      for (;;) {
        const k = key();
        if (text[i] !== "=") invalid("expected '=' in an inline table");
        i += 1;
        spaces();
        assign(tbl, k, value(depth + 1));
        spaces();
        if (text[i] === ",") {
          i += 1;
          spaces();
          if (text[i] === "}") invalid("trailing comma in an inline table");
        } else if (text[i] === "}") {
          i += 1;
          break;
        } else invalid("expected ',' or '}' in an inline table");
      }
      closed.add(tbl);
      return tbl;
    }
    return scalar();
  }

  /** Set a dotted key under `table`. Redefining any key is invalid TOML. */
  function assign(table, parts, v) {
    let cur = table;
    for (let j = 0; j < parts.length - 1; j += 1) {
      const p = parts[j];
      if (!hasOwn(cur, p)) {
        const made = {};
        dottedMade.add(made);
        setOwn(cur, p, made);
      }
      cur = cur[p];
      if (!isPlainObject(cur) || closed.has(cur) || !dottedMade.has(cur)) invalid("dotted key redefines a value");
    }
    const last = parts[parts.length - 1];
    if (hasOwn(cur, last)) invalid(`duplicate key ${JSON.stringify(parts.join("."))}`);
    setOwn(cur, last, v);
  }

  /** Resolve a [table] or [[array]] header path, creating intermediate tables. */
  function openHeader(parts, isArrayTable) {
    let cur = root;
    for (let j = 0; j < parts.length; j += 1) {
      const p = parts[j];
      const last = j === parts.length - 1;
      if (last && isArrayTable) {
        if (!hasOwn(cur, p)) {
          const arr = [];
          arrayTables.add(arr);
          setOwn(cur, p, arr);
        }
        const arr = cur[p];
        if (!Array.isArray(arr) || !arrayTables.has(arr)) invalid("[[header]] redefines a value");
        const t = {};
        arr.push(t);
        return t;
      }
      if (!hasOwn(cur, p)) setOwn(cur, p, {});
      let next = cur[p];
      if (Array.isArray(next) && arrayTables.has(next)) {
        if (last) invalid("[header] names an array of tables");
        next = next[next.length - 1];
      }
      if (!isPlainObject(next) || closed.has(next)) invalid("[header] redefines a value");
      if (last && dottedMade.has(next)) invalid("[header] reopens a table defined by dotted keys");
      cur = next;
    }
    return cur;
  }

  let current = root;
  for (;;) {
    blankLines();
    if (i >= n) break;
    if (text[i] === "[") {
      const isArrayTable = text[i + 1] === "[";
      i += isArrayTable ? 2 : 1;
      const parts = key();
      if (isArrayTable ? !text.startsWith("]]", i) : text[i] !== "]") invalid("unterminated table header");
      i += isArrayTable ? 2 : 1;
      endOfLine();
      if (!isArrayTable) {
        const tag = JSON.stringify(parts);
        if (explicitTables.has(tag)) invalid("table defined twice");
        explicitTables.add(tag);
      }
      current = openHeader(parts, isArrayTable);
      continue;
    }
    const k = key();
    if (text[i] !== "=") invalid("expected '=' after a key");
    i += 1;
    spaces();
    if (i >= n || text[i] === "\n" || text[i] === "\r" || text[i] === "#") invalid("missing value");
    assign(current, k, value(0));
    endOfLine();
  }
  return root;
}

module.exports = { parseToml, SUPPORTED_SUBSET };
