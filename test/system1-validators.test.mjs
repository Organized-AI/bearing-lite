/**
 * `validator` backend: deterministic code checks for multi-condition rules
 * (tools/system1-validators/). No model, no probability: same bytes, same verdict.
 *
 * Covers agreement with the independent Python labelers on every labeled item,
 * the TOML subset reader against tomllib, the frozen rubrics' pins and
 * controls, determinism, typed ERROR/INCONCLUSIVE outcomes, and the round trip
 * planVerification -> run -> sealVerification -> evaluateVerification.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const bridge = require(path.join(ROOT, "hooks/verification-bridge.cjs"));
const adapter = require(path.join(ROOT, "hooks/verification.cjs"));
const { runClaim, decide } = require(path.join(ROOT, "tools/system1-validators/run.cjs"));
const { InputError, jcs } = require(path.join(ROOT, "tools/system1-validators/lib.cjs"));
const { parseToml } = require(path.join(ROOT, "tools/system1-validators/toml.cjs"));
const gtm = require(path.join(ROOT, "tools/system1-validators/gtm-purchase-event.cjs"));
const wrangler = require(path.join(ROOT, "tools/system1-validators/wrangler-required-bindings.cjs"));

const RUBRIC_DIR = "skills/bearing-lite/references/system1-rubrics";
const GTM_RUBRIC = `${RUBRIC_DIR}/validator-gtm-purchase-event.rubric.json`;
const WRANGLER_RUBRIC = `${RUBRIC_DIR}/validator-wrangler-required-bindings.rubric.json`;
const CASES = JSON.parse(readFileSync(path.join(ROOT, "test/fixtures/system1-validators/cases.json"), "utf8"));
const TRIP = JSON.parse(readFileSync(path.join(ROOT, "test/fixtures/system1-validator-round-trip.json"), "utf8"));

const sha = (data) => createHash("sha256").update(data).digest("hex");
const readJson = (rel) => JSON.parse(readFileSync(path.join(ROOT, rel), "utf8"));
const readJsonl = (rel) => readFileSync(path.join(ROOT, rel), "utf8").trim().split("\n").map((l) => JSON.parse(l));
const label = (verdict) => (verdict === "VERIFIED" ? "holds" : verdict === "REFUTED" ? "fails" : verdict);

/** Validator condition id -> labelers.py reason string. */
const GTM_REASON = {
  push_is_object: "not_an_object",
  event_is_purchase: "event_not_purchase",
  ecommerce_is_object: "ecommerce_missing",
  transaction_id_present: "missing_transaction_id",
  value_present: "missing_value",
  currency_present: "missing_currency",
  currency_is_iso4217: "currency_not_iso4217",
  items_is_array: "items_not_array",
  items_nonempty: "items_empty",
  items_has_identified_item: "no_item_with_id_or_name",
};
const WRANGLER_REASON = {};
for (const [a, b, k] of [
  ["d1_databases", "DB", "database_id"],
  ["kv_namespaces", "CACHE", "id"],
  ["r2_buckets", "ASSETS", "bucket_name"],
]) {
  WRANGLER_REASON[`${a}_is_array`] = `missing_${a}`;
  WRANGLER_REASON[`${a}_has_${b}`] = `no_${a}_binding_${b}`;
  WRANGLER_REASON[`${a}_${b}_${k}_nonempty`] = `empty_or_missing_${k}_for_${b}`;
}

function claimFor(rubricRel, targetRel) {
  const rubric = readJson(rubricRel);
  return {
    kind: "system1_decision",
    backend: "validator",
    rubric_id: rubric.rubric_id,
    rubric_version: rubric.rubric_version,
    rubric_digest: sha(bridge.canonicalJson(rubric)),
    input_digest: sha(readFileSync(path.join(ROOT, targetRel))),
  };
}

function run(rubricRel, targetRel, extra = {}) {
  return runClaim({
    rubricPath: rubricRel,
    operation: "check",
    target: targetRel,
    claimText: JSON.stringify(claimFor(rubricRel, targetRel)),
    root: ROOT,
    ...extra,
  });
}

describe("validator backend: agreement with the independent Python labelers", () => {
  it("gtm-purchase-event agrees on 100% of the 360 GTM items: verdict, reasons, canonical digest", () => {
    const rows = ["calibration", "test"].flatMap((s) =>
      readJsonl(`test/fixtures/system1-calibration/gtm-datalayer-event/${s}.jsonl`)
    );
    assert.equal(rows.length, 360);
    const bad = [];
    for (const r of rows) {
      const rec = decide(gtm, Buffer.from(r.state, "utf8"), "json");
      const reasons = rec.failed_conditions.map((c) => GTM_REASON[c]);
      if (label(rec.verdict) !== r.label || JSON.stringify(reasons) !== JSON.stringify(r.truth.reasons) ||
          rec.canonical_input_digest !== r.input_digest) bad.push(r.id);
    }
    assert.deepEqual(bad, []);
  });

  it("wrangler-required-bindings agrees on 100% of the 360 items, read from their JSONC or TOML source", () => {
    const rows = ["calibration", "test"].flatMap((s) =>
      readJsonl(`test/fixtures/system1-calibration/wrangler-bindings/${s}.jsonl`)
    );
    assert.equal(rows.length, 360);
    assert.ok(rows.some((r) => r.source_format === "toml") && rows.some((r) => r.source_format === "jsonc"));
    const bad = [];
    for (const r of rows) {
      const rec = decide(wrangler, Buffer.from(r.source, "utf8"), r.source_format);
      const reasons = rec.failed_conditions.map((c) => WRANGLER_REASON[c]);
      if (label(rec.verdict) !== r.label || JSON.stringify(reasons) !== JSON.stringify(r.truth.reasons) ||
          rec.canonical_input_digest !== r.input_digest) bad.push(r.id);
    }
    assert.deepEqual(bad, []);
  });

  it("agrees on every hand-written edge case the Python side labeled", () => {
    for (const c of CASES.gtm) {
      const rec = decide(gtm, Buffer.from(c.text, "utf8"), "json");
      assert.equal(label(rec.verdict), c.label, c.name);
      assert.deepEqual(rec.failed_conditions.map((x) => GTM_REASON[x]), c.reasons, c.name);
    }
    for (const c of CASES.wrangler) {
      const rec = decide(wrangler, Buffer.from(c.source, "utf8"), c.format);
      assert.equal(label(rec.verdict), c.label, c.name);
      assert.deepEqual(rec.failed_conditions.map((x) => WRANGLER_REASON[x]), c.reasons, c.name);
      assert.equal(rec.canonical_input_digest, c.state_digest, c.name);
    }
  });

  it("pins the same ISO 4217 list as labelers.py", () => {
    const py = readFileSync(path.join(ROOT, "tools/system1-calibration/labelers.py"), "utf8");
    const block = /ISO_4217 = frozenset\("""([\s\S]*?)"""/.exec(py)[1];
    assert.deepEqual([...gtm.ISO_4217].sort(), block.split(/\s+/).filter(Boolean).sort());
  });
});

describe("validator backend: TOML subset reader", () => {
  it("matches Python's tomllib inside the subset and refuses everything outside it by type", () => {
    for (const c of CASES.toml) {
      let got;
      try {
        got = jcs(parseToml(c.text));
      } catch (err) {
        assert.ok(err instanceof InputError, c.name);
        got = err.reason;
      }
      const want = c.subset === "unsupported" ? "toml_unsupported_construct" : c.tomllib === "invalid" ? "input_unparseable" : c.tomllib;
      assert.equal(got, want, c.name);
    }
  });

  it("an unsupported TOML construct in a wrangler file is ERROR toml_unsupported_construct, never a guess", () => {
    const rec = decide(wrangler, Buffer.from('name = "w"\ncompatibility_date = 2026-09-01\n'), "toml");
    assert.equal(rec.verdict, "ERROR");
    assert.equal(rec.reason, "toml_unsupported_construct");
    assert.deepEqual(rec.conditions, []);
  });

  it("unparseable or non-object input is ERROR with a typed reason", () => {
    assert.equal(decide(gtm, Buffer.from('{"event":"purchase",'), "json").reason, "input_unparseable");
    assert.equal(decide(gtm, Buffer.from([0xff, 0xfe, 0x00]), "json").reason, "input_unparseable");
    assert.equal(decide(wrangler, Buffer.from("[1, 2]"), "jsonc").reason, "input_shape_invalid");
    assert.equal(decide(wrangler, Buffer.from("a = = 1"), "toml").reason, "input_unparseable");
  });
});

describe("validator backend: frozen rubrics", () => {
  for (const [rel, mod] of [[GTM_RUBRIC, gtm], [WRANGLER_RUBRIC, wrangler]]) {
    it(`${path.basename(rel)} pins the current program and is assurance-eligible`, () => {
      const r = readJson(rel);
      assert.equal(r.backend, "validator");
      assert.equal(r.assurance_eligible, true);
      for (const key of ["model", "question", "decision", "calibration", "gateway"]) assert.equal(key in r, false, key);
      assert.equal(r.validator.validator_id, mod.VALIDATOR_ID);
      assert.equal(r.validator.validator_version, mod.VALIDATOR_VERSION);
      for (const pin of [r.validator.implementation, ...r.validator.support_files]) {
        assert.equal(sha(readFileSync(path.join(ROOT, pin.path))), pin.sha256, pin.path);
      }
      assert.equal(r.rule.text, mod.RULE_TEXT);
      assert.deepEqual(r.rule.conditions, mod.CONDITIONS.map((c) => ({ id: c.id, text: c.text })));
      assert.deepEqual(r.operations.allowed, ["check"]);
      assert.ok(r.replay.min_runs >= 2);
      assert.ok(r.controls.some((c) => c.expected === "VERIFIED") && r.controls.some((c) => c.expected === "REFUTED"));
    });

    it(`${path.basename(rel)}: every control file hashes to its pin and lands on its expected verdict`, () => {
      const r = readJson(rel);
      for (const c of r.controls) {
        const bytes = readFileSync(path.join(ROOT, c.locator));
        assert.equal(sha(bytes), c.input_digest, c.control_id);
        const out = run(rel, c.locator);
        assert.equal(out.results[0].verdict, c.expected, c.control_id);
        assert.ok(out.results[0].evidence.controls.every((x) => x.observed === x.expected));
      }
    });
  }
});

describe("validator backend: determinism", () => {
  it("two CLI runs on the same input print byte-identical output (same digest)", () => {
    const claim = JSON.stringify(claimFor(WRANGLER_RUBRIC, "test/fixtures/wrangler/controls/all-bound.toml"));
    const argv = ["tools/system1-validators/run.cjs", "--rubric", WRANGLER_RUBRIC, "check",
      "test/fixtures/wrangler/controls/all-bound.toml", claim];
    const a = execFileSync(process.execPath, argv, { cwd: ROOT });
    const b = execFileSync(process.execPath, argv, { cwd: ROOT });
    assert.equal(sha(a), sha(b));
    const out = JSON.parse(a.toString("utf8"));
    assert.equal(out.results[0].verdict, "VERIFIED");
    const { runs, replay } = out.results[0].evidence;
    assert.ok(runs.length >= 2 && runs.every((r) => r.fresh_process === true));
    assert.equal(new Set(runs.map((r) => r.output_digest)).size, 1);
    assert.equal(replay.identical_output_digest, true);
  });

  it("a nondeterministic program is INCONCLUSIVE replay_output_divergence, never a verdict", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "validator-replay-"));
    try {
      mkdirSync(path.join(dir, "v"));
      cpSync(path.join(ROOT, "tools/system1-validators"), path.join(dir, "v"), { recursive: true });
      const src = readFileSync(path.join(dir, "v/gtm-purchase-event.cjs"), "utf8").replace(
        "return conditionDecision(pairs);\n}\n\n/**",
        "pairs.push([\"coin\", Math.random() < 2]);\n  return { ...conditionDecision(pairs), nonce: Math.random() };\n}\n\n/**"
      );
      writeFileSync(path.join(dir, "v/gtm-purchase-event.cjs"), src);
      const r = readJson(GTM_RUBRIC);
      r.validator.implementation = { path: "v/gtm-purchase-event.cjs", sha256: sha(src) };
      r.validator.support_files = [{ path: "v/lib.cjs", sha256: sha(readFileSync(path.join(dir, "v/lib.cjs"))) }];
      r.controls = r.controls.map((c) => ({ ...c, locator: path.join(ROOT, c.locator) }));
      writeFileSync(path.join(dir, "r.json"), JSON.stringify(r));
      writeFileSync(path.join(dir, "t.json"), readFileSync(path.join(ROOT, "test/fixtures/datalayer/purchase-push.json")));
      const claim = {
        kind: "system1_decision", backend: "validator", rubric_id: r.rubric_id, rubric_version: r.rubric_version,
        rubric_digest: sha(bridge.canonicalJson(r)), input_digest: sha(readFileSync(path.join(dir, "t.json"))),
      };
      const out = runClaim({ rubricPath: "r.json", operation: "check", target: "t.json", claimText: JSON.stringify(claim), root: dir });
      assert.equal(out.results[0].verdict, "INCONCLUSIVE");
      assert.equal(out.results[0].reason, "replay_output_divergence");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("validator backend: typed refusals", () => {
  const target = "test/fixtures/datalayer/purchase-push.json";

  it("a malformed claim carries the bridge's marker and is rejected with no receipt", () => {
    const out = runClaim({ rubricPath: GTM_RUBRIC, operation: "check", target, claimText: "{not json", root: ROOT });
    assert.equal(out.results[0].reason, "claim_malformed");
    assert.match(out.results[0].detail, /malformed claim/);
    const plan = bridge.planVerification({ ...TRIP.trips.verified.spec, rubric: readJson(GTM_RUBRIC) });
    const seal = bridge.sealVerification({ plan, output: out, produced_by: TRIP.produced_by });
    assert.deepEqual([seal.outcome, seal.reason], ["REJECT", "claim_malformed"]);
  });

  it("a stale rubric digest, a changed input, an unlisted operation, or an oversized input is ERROR", () => {
    const claim = claimFor(GTM_RUBRIC, target);
    const go = (c, extra = {}) => runClaim({ rubricPath: GTM_RUBRIC, operation: "check", target, claimText: JSON.stringify(c), root: ROOT, ...extra }).results[0];
    assert.equal(go({ ...claim, rubric_digest: "0".repeat(64) }).reason, "rubric_digest_mismatch");
    assert.equal(go({ ...claim, input_digest: "0".repeat(64) }).reason, "input_digest_mismatch");
    assert.equal(go(claim, { operation: "evaluate" }).reason, "operation_not_allowed");
    assert.equal(go(claim, { target: "test/fixtures/datalayer/missing.json" }).reason, "input_unresolvable");
    const big = runClaim({
      rubricPath: WRANGLER_RUBRIC, operation: "check", target: "test/fixtures/system1-calibration/wrangler-bindings/test.jsonl",
      claimText: JSON.stringify(claimFor(WRANGLER_RUBRIC, "test/fixtures/wrangler/controls/all-bound.jsonc")), root: ROOT,
    }).results[0];
    assert.equal(big.reason, "input_unresolvable"); // .jsonl has no pinned format
  });

  it("an edited pinned file is ERROR validator_digest_mismatch; a failing control is INCONCLUSIVE control_failed", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "validator-pins-"));
    try {
      cpSync(path.join(ROOT, "tools"), path.join(dir, "tools"), { recursive: true });
      cpSync(path.join(ROOT, "test/fixtures/datalayer"), path.join(dir, "test/fixtures/datalayer"), { recursive: true });
      mkdirSync(path.join(dir, RUBRIC_DIR), { recursive: true });
      cpSync(path.join(ROOT, GTM_RUBRIC), path.join(dir, GTM_RUBRIC));
      const claimText = JSON.stringify(claimFor(GTM_RUBRIC, target));
      const go = () => runClaim({ rubricPath: GTM_RUBRIC, operation: "check", target, claimText, root: dir }).results[0];
      assert.equal(go().verdict, "VERIFIED");
      writeFileSync(path.join(dir, "test/fixtures/datalayer/controls/add-to-cart.json"), '{"event":"purchase"}');
      const ctl = go();
      assert.deepEqual([ctl.verdict, ctl.reason], ["INCONCLUSIVE", "control_failed"]);
      writeFileSync(path.join(dir, "tools/system1-validators/lib.cjs"), readFileSync(path.join(ROOT, "tools/system1-validators/lib.cjs"), "utf8") + "\n");
      assert.equal(go().reason, "validator_digest_mismatch");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("validator backend: bridge round trip", () => {
  const rubric = readJson(TRIP.rubric_path);
  const backend = { name: "validator", enabled: true, available: true };
  const author = { role: "implementer", identity: "author-1", session: "sess-impl" };

  it("reproduces the fixture requests and receipts exactly", () => {
    for (const [key, t] of Object.entries(TRIP.trips)) {
      const plan = bridge.planVerification({ ...t.spec, rubric });
      assert.equal(plan.outcome, "READY", key);
      assert.deepEqual(plan.request, t.request, key);
      const seal = bridge.sealVerification({ plan, output: t.output, produced_by: TRIP.produced_by });
      assert.deepEqual(seal.receipt, t.receipt, key);
    }
  });

  it("planVerification -> run -> sealVerification -> evaluateVerification: a VERIFIED run on an eligible rubric is an assurance PASS", () => {
    const t = TRIP.trips.verified;
    const plan = bridge.planVerification({ ...t.spec, rubric });
    assert.equal(plan.outcome, "READY", JSON.stringify(plan));
    assert.equal(plan.argv[0], "node");
    const stdout = execFileSync(process.execPath, plan.argv.slice(1), { cwd: ROOT, encoding: "utf8" });
    const output = JSON.parse(stdout);
    assert.equal(output.results[0].verdict, "VERIFIED");
    const seal = bridge.sealVerification({ plan, output, produced_by: TRIP.produced_by });
    assert.equal(seal.outcome, "READY");
    assert.equal(seal.receipt.backend, "validator");
    assert.equal(seal.receipt.evidence_tier, "observed");
    const verdict = adapter.evaluateVerification({
      request: plan.request, receipt: seal.receipt, candidate: t.spec.candidate, backend, author, gate: "assurance",
    });
    assert.equal(verdict.outcome, "PASS", JSON.stringify(verdict));
    assert.equal(verdict.reason, "independent_assurance_verified");
    assert.equal(verdict.gate_eligible, true);
  });

  it("REFUTED and ERROR runs never pass the assurance gate", () => {
    const refuted = TRIP.trips.refuted;
    const v1 = adapter.evaluateVerification({
      request: refuted.request, receipt: refuted.receipt, candidate: refuted.spec.candidate, backend, author, gate: "assurance",
    });
    assert.deepEqual([v1.outcome, v1.reason, v1.gate_eligible], ["REJECT", "expected_result_mismatch", false]);
    const err = TRIP.trips.error_unparseable;
    assert.equal(err.receipt.status, "ERROR");
    const v2 = adapter.evaluateVerification({
      request: err.request, receipt: err.receipt, candidate: err.spec.candidate, backend, author, gate: "assurance",
    });
    assert.deepEqual([v2.outcome, v2.gate_eligible], ["ERROR", false]);
  });

  it("an assurance plan on a validator rubric that is not eligible, or not the claimed rubric, is refused", () => {
    const t = TRIP.trips.verified;
    const off = { ...rubric, assurance_eligible: false };
    const refused = bridge.planVerification({
      ...t.spec, rubric: off, claim: { ...t.spec.claim, rubric_digest: sha(bridge.canonicalJson(off)) },
    });
    assert.deepEqual([refused.outcome, refused.reason], ["REJECT", "rubric_not_assurance_eligible"]);
    const missing = bridge.planVerification({ ...t.spec });
    assert.deepEqual([missing.outcome, missing.reason], ["REJECT", "rubric_missing"]);
    const denied = bridge.planVerification({ ...t.spec, rubric, backend_operation: "propose_claims" });
    assert.deepEqual([denied.outcome, denied.reason], ["REJECT", "generative_backend_operation_denied"]);
    const laya = bridge.planVerification({ ...t.spec, rubric, backend: "laya" });
    assert.deepEqual([laya.outcome, laya.reason], ["REJECT", "rubric_backend_mismatch"]);
  });
});
