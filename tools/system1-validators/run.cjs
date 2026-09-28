#!/usr/bin/env node
"use strict";

/**
 * Backend client for the `validator` backend: runs one frozen validator
 * rubric against one input and prints `backend_output` (schemas/system1.schema.json)
 * for hooks/verification-bridge.cjs sealVerification.
 *
 *   node tools/system1-validators/run.cjs --rubric <rubric.json> [--claim-id <id>] <operation> <target> <claim-json>
 *
 * A rubric's invocation is typically
 *   executable "node", argv_template ["tools/system1-validators/run.cjs", "--rubric", "<rubric path>",
 *   "{operation}", "{target}", "{claim}"].
 * Paths (rubric, pinned validator files, control locators, target) resolve
 * against the working directory, which must be the repository root.
 *
 * Steps, each failure typed (never a guess):
 *   1. parse the claim binding; a claim that does not parse carries the bridge's
 *      `malformed claim` marker (sealVerification rejects it, no receipt);
 *   2. load the rubric and require SHA-256(canonicalJson(rubric)) == claim.rubric_digest;
 *   3. require the operation in the rubric's verdict-only allowlist;
 *   4. require every pinned validator file to hash to its pinned SHA-256 and the
 *      module to report the pinned validator_id and version;
 *   5. resolve the target, check its size and that SHA-256(file bytes) == claim.input_digest;
 *   6. decide every control in-process; any control off its expected verdict
 *      makes the claim INCONCLUSIVE `control_failed`;
 *   7. decide the target in `replay.min_runs` freshly started Node processes;
 *      the SHA-256 of every run's canonical decision record must be identical,
 *      else INCONCLUSIVE `replay_output_divergence`.
 * The verdict is the decision record's: VERIFIED, REFUTED, or ERROR with the
 * record's typed reason. No probability, temperature, or threshold exists.
 *
 * Internal mode (one fresh-process replay run; prints the canonical decision record):
 *   node tools/system1-validators/run.cjs --decide <validator module> <format> <input file>
 */

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const { InputError, decodeUtf8, isPlainObject, jcs, sha256Hex } = require("./lib.cjs");

const SHA256 = /^[0-9a-f]{64}$/;
const SEMVER = /^[0-9]+\.[0-9]+\.[0-9]+$/;
const RUBRIC_ID = /^RUB-S1-[A-Z0-9][A-Z0-9-]*$/;
const CLAIM_KEYS = ["backend", "input_digest", "kind", "rubric_digest", "rubric_id", "rubric_version"];

/**
 * Decide one input with one validator module. Pure: same bytes, same record.
 * @param {object} mod validator module
 * @param {Buffer} bytes
 * @param {string} format
 */
function decide(mod, bytes, format) {
  const record = {
    validator_id: mod.VALIDATOR_ID,
    validator_version: mod.VALIDATOR_VERSION,
    format,
    input_bytes: bytes.length,
    input_digest: sha256Hex(bytes),
    canonical_input_digest: null,
    verdict: "ERROR",
    conditions: [],
    failed_conditions: [],
  };
  let canon;
  try {
    canon = mod.canonicalize(decodeUtf8(bytes), format);
  } catch (err) {
    if (!(err instanceof InputError)) throw err;
    return { ...record, reason: err.reason, detail: err.message };
  }
  const decision = mod.evaluate(canon.state);
  return { ...record, canonical_input_digest: sha256Hex(canon.canonical), ...decision };
}

function loadModule(absPath) {
  delete require.cache[require.resolve(absPath)];
  return require(absPath);
}

/** --decide mode: one replay run in this (fresh) process. */
function decideMain(argv) {
  const [modulePath, format, inputPath] = argv;
  const mod = loadModule(path.resolve(modulePath));
  const record = decide(mod, fs.readFileSync(inputPath), format);
  process.stdout.write(jcs(record));
}

const fileDigest = (abs) => sha256Hex(fs.readFileSync(abs));

/** Deterministic JSON with sorted keys (hooks/verification-bridge.cjs canonicalJson). */
function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value === undefined ? null : value);
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  return (
    "{" +
    Object.keys(value)
      .sort()
      .filter((k) => value[k] !== undefined)
      .map((k) => JSON.stringify(k) + ":" + canonicalJson(value[k]))
      .join(",") +
    "}"
  );
}

function parseClaim(text) {
  let claim;
  try {
    claim = JSON.parse(text);
  } catch {
    return { error: "claim is not JSON" };
  }
  if (!isPlainObject(claim)) return { error: "claim is not an object" };
  const keys = Object.keys(claim).sort();
  if (keys.join(",") !== CLAIM_KEYS.join(",")) return { error: `claim keys must be exactly ${CLAIM_KEYS.join(", ")}` };
  if (claim.kind !== "system1_decision") return { error: "claim.kind must be system1_decision" };
  if (claim.backend !== "validator") return { error: "claim.backend must be validator" };
  if (!RUBRIC_ID.test(String(claim.rubric_id))) return { error: "claim.rubric_id is invalid" };
  if (!SEMVER.test(String(claim.rubric_version))) return { error: "claim.rubric_version is invalid" };
  if (!SHA256.test(String(claim.rubric_digest)) || !SHA256.test(String(claim.input_digest))) {
    return { error: "claim digests must be 64 lowercase hex characters" };
  }
  return { claim };
}

/**
 * Run one claim. Never throws for a typed failure: every outcome is a backend_output.
 * @param {{rubricPath: string, operation: string, target: string, claimText: string, claimId?: string, root?: string, runnerPath?: string}} args
 */
function runClaim(args) {
  const root = path.resolve(args.root || process.cwd());
  const runnerPath = args.runnerPath || __filename;
  const nodeMajor = Number(process.versions.node.split(".")[0]);
  let backendVersion = `validator unresolved node${nodeMajor}`;
  const evidence = { strength: "observed", engine: "validator", engine_version: "unresolved" };
  let claimId = args.claimId || "unbound";

  const output = (verdict, reason, detail) => {
    const result = { claim_id: claimId, kind: "system1_decision", verdict, detail, evidence };
    if (reason) result.reason = reason;
    return { schema_family: "system1", schema_version: "1", backend: "validator", backend_version: backendVersion, results: [result] };
  };

  const parsed = parseClaim(args.claimText);
  if (parsed.error) {
    const out = output("ERROR", "claim_malformed", `malformed claim: ${parsed.error}`);
    delete out.results[0].evidence;
    return out;
  }
  const claim = parsed.claim;
  if (!args.claimId) claimId = claim.rubric_id;

  // 2. rubric
  let rubric;
  try {
    rubric = JSON.parse(fs.readFileSync(path.resolve(root, args.rubricPath), "utf8"));
  } catch (err) {
    return output("ERROR", "rubric_unavailable", `rubric ${args.rubricPath} could not be read: ${err.message}`);
  }
  const rubricDigest = sha256Hex(canonicalJson(rubric));
  if (
    rubricDigest !== claim.rubric_digest ||
    rubric.backend !== "validator" ||
    rubric.rubric_id !== claim.rubric_id ||
    rubric.rubric_version !== claim.rubric_version
  ) {
    return output("ERROR", "rubric_digest_mismatch", `rubric ${args.rubricPath} does not match the claim binding (digest ${rubricDigest})`);
  }
  const v = rubric.validator;
  backendVersion = `validator ${v.validator_id}@${v.validator_version} node${nodeMajor}`;
  evidence.engine_version = `${v.validator_id}@${v.validator_version}`;
  evidence.rubric = { rubric_id: rubric.rubric_id, rubric_version: rubric.rubric_version, rubric_digest: rubricDigest };

  // 3. operation
  if (!rubric.operations.allowed.includes(args.operation)) {
    return output("ERROR", "operation_not_allowed", `operation ${JSON.stringify(args.operation)} is not in the rubric's verdict-only allowlist`);
  }

  // 4. pins
  const pinned = [v.implementation, ...v.support_files];
  const observedPins = [];
  for (const pin of pinned) {
    let digest = null;
    try {
      digest = fileDigest(path.resolve(root, pin.path));
    } catch {
      digest = null;
    }
    observedPins.push({ path: pin.path, sha256: digest });
    if (digest !== pin.sha256) {
      return output("ERROR", "validator_digest_mismatch", `${pin.path} does not hash to its pinned SHA-256`);
    }
  }
  if (nodeMajor < v.runtime.node_major_min) {
    return output("ERROR", "validator_runtime_mismatch", `node ${process.versions.node} is below the pinned minimum major ${v.runtime.node_major_min}`);
  }
  const implAbs = path.resolve(root, v.implementation.path);
  let mod;
  try {
    mod = loadModule(implAbs);
  } catch (err) {
    return output("ERROR", "validator_runtime_error", `validator module failed to load: ${err.message}`);
  }
  if (mod.VALIDATOR_ID !== v.validator_id || mod.VALIDATOR_VERSION !== v.validator_version) {
    return output("ERROR", "validator_digest_mismatch", "validator module reports a different id or version than the rubric pins");
  }
  evidence.validator = {
    validator_id: v.validator_id,
    validator_version: v.validator_version,
    pinned_files: observedPins,
    runner_sha256: fileDigest(runnerPath),
    node_major: nodeMajor,
  };

  // 5. target
  const input = rubric.input;
  const ext = path.extname(args.target).toLowerCase();
  const format = Object.prototype.hasOwnProperty.call(input.format_by_extension, ext) ? input.format_by_extension[ext] : null;
  evidence.input = {
    target: args.target,
    format: format || "unresolved",
    canonicalization: input.canonicalization,
    input_digest_basis: input.input_digest_basis,
    claim_input_digest: claim.input_digest,
    max_input_bytes: input.max_input_bytes,
  };
  const targetAbs = path.resolve(root, args.target);
  let bytes;
  try {
    bytes = fs.readFileSync(targetAbs);
  } catch {
    return output("ERROR", "input_unresolvable", `target ${args.target} could not be read`);
  }
  evidence.input.input_bytes = bytes.length;
  evidence.input.input_digest = sha256Hex(bytes);
  if (!format) return output("ERROR", "input_unresolvable", `no pinned format for extension ${JSON.stringify(ext)}`);
  if (bytes.length > input.max_input_bytes) {
    return output("ERROR", "input_over_size_limit", `target is ${bytes.length} bytes, over max_input_bytes ${input.max_input_bytes}`);
  }
  if (evidence.input.input_digest !== claim.input_digest) {
    return output("ERROR", "input_digest_mismatch", "SHA-256 of the target bytes differs from the claim's input_digest");
  }

  // 6. controls (in-process)
  evidence.controls = [];
  let controlsPass = true;
  for (const c of rubric.controls) {
    let observed = "ERROR";
    let outputDigest = null;
    try {
      const cBytes = fs.readFileSync(path.resolve(root, c.locator));
      const cExt = path.extname(c.locator).toLowerCase();
      if (sha256Hex(cBytes) === c.input_digest && Object.prototype.hasOwnProperty.call(input.format_by_extension, cExt)) {
        const rec = decide(mod, cBytes, input.format_by_extension[cExt]);
        observed = rec.verdict;
        outputDigest = sha256Hex(jcs(rec));
      }
    } catch {
      observed = "ERROR";
    }
    if (observed !== c.expected) controlsPass = false;
    evidence.controls.push({ control_id: c.control_id, expected: c.expected, observed, output_digest: outputDigest });
  }

  // 7. replay in fresh processes
  evidence.runs = [];
  let record = null;
  for (let k = 1; k <= rubric.replay.min_runs; k += 1) {
    let stdout;
    try {
      stdout = execFileSync(process.execPath, [runnerPath, "--decide", implAbs, format, targetAbs], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
        timeout: 60_000,
        maxBuffer: 16 * 1024 * 1024,
      });
      record = JSON.parse(stdout);
    } catch (err) {
      return output("ERROR", "validator_runtime_error", `replay run ${k} failed: ${String(err.message).split("\n")[0]}`);
    }
    evidence.runs.push({ run_index: k, fresh_process: true, verdict: record.verdict, output_digest: sha256Hex(stdout) });
  }
  const digests = new Set(evidence.runs.map((r) => r.output_digest));
  const identical = digests.size === 1;
  evidence.replay = {
    runs: evidence.runs.length,
    min_runs: rubric.replay.min_runs,
    identical_output_digest: identical,
    output_digest: identical ? evidence.runs[0].output_digest : null,
  };
  evidence.input.canonical_input_digest = record.canonical_input_digest;
  evidence.decision = {
    verdict: record.verdict,
    conditions: record.conditions,
    failed_conditions: record.failed_conditions,
  };

  if (!controlsPass) {
    const bad = evidence.controls.filter((c) => c.observed !== c.expected).map((c) => c.control_id);
    return output("INCONCLUSIVE", "control_failed", `control(s) off their expected verdict: ${bad.join(", ")}`);
  }
  if (!identical) {
    return output("INCONCLUSIVE", "replay_output_divergence", "fresh-process runs produced different decision-record digests");
  }
  if (record.verdict === "ERROR") return output("ERROR", record.reason, record.detail);
  const n = record.conditions.length;
  if (record.verdict === "VERIFIED") {
    return output("VERIFIED", null, `all ${n} conditions hold (${v.validator_id}@${v.validator_version})`);
  }
  return output("REFUTED", null, `failed condition(s): ${record.failed_conditions.join(", ")}`);
}

function usage(msg) {
  process.stderr.write(
    `${msg}\nusage: run.cjs --rubric <rubric.json> [--claim-id <id>] <operation> <target> <claim-json>\n` +
      "       run.cjs --decide <validator module> <format> <input file>\n"
  );
  process.exit(2);
}

function main(argv) {
  if (argv[0] === "--decide") {
    if (argv.length !== 4) usage("--decide takes exactly three arguments");
    decideMain(argv.slice(1));
    return;
  }
  const opts = {};
  const positional = [];
  for (let k = 0; k < argv.length; k += 1) {
    if (argv[k] === "--rubric" || argv[k] === "--claim-id") {
      if (k + 1 >= argv.length) usage(`${argv[k]} needs a value`);
      opts[argv[k] === "--rubric" ? "rubricPath" : "claimId"] = argv[k + 1];
      k += 1;
    } else positional.push(argv[k]);
  }
  if (!opts.rubricPath) usage("--rubric is required");
  if (positional.length !== 3) usage("expected <operation> <target> <claim-json>");
  const [operation, target, claimText] = positional;
  const out = runClaim({ ...opts, operation, target, claimText });
  process.stdout.write(canonicalJson(out) + "\n");
}

if (require.main === module) main(process.argv.slice(2));

module.exports = { runClaim, decide, canonicalJson };
