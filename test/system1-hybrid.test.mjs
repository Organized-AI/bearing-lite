/**
 * Hybrid deterministic verification: which backend owns which check, and
 * whether every rubric's assurance_eligible flag follows from its committed
 * measurements (docs/calibration/system1-calibration-report.md, Hybrid section).
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const { canonicalJson } = require(path.join(ROOT, "hooks/verification-bridge.cjs"));
const DIR = path.join(ROOT, "skills/bearing-lite/references/system1-rubrics");
const FIX = path.join(ROOT, "test/fixtures/system1-calibration/single-condition");
const sha = (data) => createHash("sha256").update(data).digest("hex");
const rubric = (file) => JSON.parse(readFileSync(path.join(DIR, file), "utf8"));
const fixture = (dir, file) => JSON.parse(readFileSync(path.join(FIX, dir, file), "utf8"));

const SINGLE = {
  "consent-purpose": "laya-consent-purpose.rubric.json",
  "consent-third-parties": "laya-consent-third-parties.rubric.json",
  "consent-withdrawal": "laya-consent-withdrawal.rubric.json",
  "gtm-event-is-purchase": "laya-gtm-event-is-purchase.rubric.json",
};

/** Wilson 95% lower bound, as tools/system1-calibration/single_condition.py computes it. */
function wilsonLower(k, n, z = 1.96) {
  const p = k / n;
  return (p + (z * z) / (2 * n) - z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / (1 + (z * z) / n);
}

describe("hybrid ownership", () => {
  it("the three multi-condition Laya rubrics are superseded, measured, and not assurance-eligible", () => {
    for (const [file, successor] of [
      ["laya-gtm-datalayer-event.rubric.json", "RUB-S1-VAL-GTM-PURCHASE-EVENT"],
      ["laya-wrangler-bindings.rubric.json", "RUB-S1-VAL-WRANGLER-REQUIRED-BINDINGS"],
      ["laya-multilingual-consent-banner.rubric.json", "RUB-S1-CONSENT-STATES-PURPOSE"],
    ]) {
      const r = rubric(file);
      assert.equal(r.assurance_eligible, false, file);
      assert.match(r.notes[0], /^SUPERSEDED/, file);
      assert.ok(r.notes[0].includes(successor), file);
    }
  });

  it("multi-condition rules are owned by validator rubrics; consent is one Laya rubric per disclosure", () => {
    assert.equal(rubric("validator-gtm-purchase-event.rubric.json").backend, "validator");
    assert.equal(rubric("validator-wrangler-required-bindings.rubric.json").backend, "validator");
    for (const key of ["consent-purpose", "consent-third-parties", "consent-withdrawal"]) {
      const r = rubric(SINGLE[key]);
      assert.equal(r.backend, "laya");
      assert.equal(r.model.checkpoint, "laya-multilingual");
      assert.equal(r.model.selection, "pinned");
      assert.equal(r.model.revision, "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851");
      assert.ok(r.decision.verify_threshold >= 0.85 && r.decision.refute_threshold >= 0.85, key);
      // One condition per question: no numbered checklist, no conjunction of disclosures.
      const text = JSON.stringify(r.question);
      assert.doesNotMatch(text, /\(1\)|\(2\)|AND /, key);
    }
  });
});

describe("single-condition Laya rubrics follow their committed measurements", () => {
  for (const [key, file] of Object.entries(SINGLE)) {
    it(`${file}: digests, temperature, and assurance_eligible match results.json and replay.json`, () => {
      const r = rubric(file);
      const res = fixture(key, "results.json");
      const rep = fixture(key, "replay.json");
      const name = res.chosen.formulation;
      const f = res.formulations[name];
      assert.equal(rep.formulation, name);
      assert.deepEqual(r.question, f.question);
      assert.equal(r.question_digest, sha(canonicalJson(r.question)));
      assert.equal(r.calibration.calibration_set_digest, sha(readFileSync(path.join(FIX, key, "calibration.jsonl"))));
      assert.equal(r.calibration.temperature, Math.round(f.temperature * 1e6) / 1e6);
      assert.ok(r.calibration.calibration_set_size >= 50);
      const tc = f.test_calibrated;
      const n = tc.verified + tc.refuted;
      const k = tc.verified_correct + tc.refuted_correct;
      const measuredEce = Math.max(tc.ece, f.calibration_calibrated.ece);
      const controlsPass = Object.values(f.controls).every((c) => c.pass) &&
        Object.entries(rep.controls).every(([cid, c]) => c.statuses.every((s) => s === f.controls[cid].expected));
      const eligible = n > 0 && k / n >= 0.95 && wilsonLower(k, n) >= 0.9 && controlsPass &&
        measuredEce <= r.calibration.max_ece;
      assert.equal(r.assurance_eligible, eligible);
      for (const c of r.controls) {
        assert.equal(sha(readFileSync(path.join(ROOT, c.locator))), c.input_digest, c.control_id);
      }
    });
  }

  it("the consent label sets are balanced, at least 300 items per disclosure, and paraphrase-disjoint across splits", () => {
    const pool = (split) => readFileSync(path.join(FIX, "consent-pool", `${split}.jsonl`), "utf8").trim().split("\n").map((l) => JSON.parse(l));
    const cal = pool("calibration");
    const test = pool("test");
    assert.ok(cal.length + test.length >= 300);
    for (const d of ["purpose", "third_parties", "withdrawal"]) {
      for (const rows of [cal, test]) {
        assert.equal(rows.filter((x) => x.truth[d]).length * 2, rows.length, d);
      }
    }
    const used = (rows) => new Set(rows.flatMap((x) => Object.entries(x.paraphrases).map(([d, i]) => `${d}:${i}`)));
    const overlap = [...used(cal)].filter((p) => used(test).has(p));
    assert.deepEqual(overlap, []);
    const digests = new Set(cal.map((x) => x.input_digest));
    assert.equal(test.filter((x) => digests.has(x.input_digest)).length, 0);
    assert.ok(readdirSync(FIX).includes("manifest.json"));
  });
});
