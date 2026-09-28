// Rebuild test/fixtures/system1-laya-round-trip.json after its bound rubric changes.
//
//   node tools/system1-calibration/build-round-trip.mjs
//
// The fixture is built the way 2f8a83d built it: a planVerification spec bound
// to the GTM rubric by id, version and digest; three schema-shaped backend
// outputs (verified, replay_divergence, derived); and the request and receipts
// that hooks/verification-bridge.cjs emits for them. This script re-derives every
// rubric-bound field (rubric version and digest, question digest and type,
// option keys, calibration temperature, thresholds, replay epsilon) from the
// rubric file and re-runs planVerification and sealVerification. Run
// probabilities, gateway ids, and control observations stay synthetic: the
// fixture exercises the bridge, it is not a measurement.
//
// The shipped rubric is not assurance_eligible, and planVerification refuses an
// assurance plan on it (rubric_not_assurance_eligible). The fixture is therefore
// a diagnostic run by an implementer. The assurance cases in
// test/verification-bridge.test.mjs use an in-test synthetic eligible copy.
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const require = createRequire(import.meta.url);
const bridge = require(path.join(ROOT, "hooks/verification-bridge.cjs"));
const FIXTURE = path.join(ROOT, "test/fixtures/system1-laya-round-trip.json");
const sha = (s) => createHash("sha256").update(s, "utf8").digest("hex");

const S1 = JSON.parse(readFileSync(FIXTURE, "utf8"));
const rubric = JSON.parse(readFileSync(path.join(ROOT, S1.rubric_path), "utf8"));
const rubricDigest = sha(bridge.canonicalJson(rubric));
const questionDigest = sha(bridge.canonicalJson(rubric.question));
if (questionDigest !== rubric.question_digest) throw new Error("rubric question_digest is stale");

const holds = rubric.decision.claim_holds_options[0];
const fails = rubric.decision.claim_fails_options[0];

S1.description =
  "Laya System One round trip (diagnostic authority): spec planned from a frozen example rubric that is not assurance-eligible, backend outputs as schemas/system1.schema.json backend_output, and the receipts sealVerification emits for them. test/verification-bridge.test.mjs reseals the outputs and must reproduce these receipts; test/schema-validation.py validates outputs and receipts against their schemas. " +
  "Rebuilt by tools/system1-calibration/build-round-trip.mjs. Run probabilities, gateway ids, and control observations are synthetic bridge inputs, not measurements: the bound rubric's measured calibration (it is not assurance-eligible) is in docs/calibration/system1-calibration-report.md.";
S1.spec.claim = { ...S1.spec.claim, rubric_id: rubric.rubric_id, rubric_version: rubric.rubric_version, rubric_digest: rubricDigest };
S1.spec.backend_operations = rubric.operations;
S1.spec.stage = "implementation";
S1.spec.authority = "diagnostic";
S1.produced_by = { role: "implementer", identity: "impl-s1", session: "sess-impl-s1" };

for (const output of Object.values(S1.outputs)) {
  for (const result of output.results) {
    const ev = result.evidence;
    ev.rubric = { rubric_id: rubric.rubric_id, rubric_version: rubric.rubric_version, rubric_digest: rubricDigest, question_digest: questionDigest };
    ev.model = { ...ev.model, checkpoint: rubric.model.checkpoint, selection: rubric.model.selection, calibration_temperature: rubric.calibration.temperature };
    ev.question_type = rubric.question.type;
    ev.input = { ...ev.input, canonicalization: rubric.input.canonicalization, token_limit: rubric.input.token_limit };
    for (const run of ev.runs) {
      const p = run.thresholded_probability;
      run.answer = holds;
      run.option_probabilities = { [holds]: p, [fails]: Number((1 - p).toFixed(4)) };
      run.served_checkpoint = rubric.model.checkpoint;
    }
    ev.replay.probability_epsilon = rubric.replay.probability_epsilon;
    ev.decision = { ...ev.decision, answer: holds, verify_threshold: rubric.decision.verify_threshold, refute_threshold: rubric.decision.refute_threshold };
  }
}

const plan = bridge.planVerification({ ...S1.spec, rubric });
if (plan.outcome !== "READY") throw new Error("plan: " + JSON.stringify(plan));
S1.request = plan.request;
for (const key of Object.keys(S1.outputs)) {
  const seal = bridge.sealVerification({ plan, output: S1.outputs[key], produced_by: S1.produced_by });
  if (seal.outcome !== "READY") throw new Error(key + ": " + JSON.stringify(seal));
  S1.receipts[key] = seal.receipt;
}
writeFileSync(FIXTURE, JSON.stringify(S1, null, 2) + "\n");
console.log("rubric", rubric.rubric_id, rubric.rubric_version, rubricDigest);
