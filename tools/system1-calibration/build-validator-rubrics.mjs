// Build the two `validator` backend rubrics from the pinned programs.
//
//   node tools/system1-calibration/build-validator-rubrics.mjs
//
// For each validator this script:
//   * hashes the pinned files (module plus support files) into `validator`;
//   * copies RULE_TEXT and CONDITIONS from the module into `rule`;
//   * hashes each control fixture and decides it, requiring its expected verdict;
//   * measures agreement with the independent Python labelers over the whole
//     360-item calibration dataset (both splits) and the edge cases in
//     test/fixtures/system1-validators/cases.json: same verdict, same failing
//     conditions (mapped to the labeler's reason vocabulary), and the same
//     SHA-256 of the canonical state;
//   * sets assurance_eligible true if and only if agreement is 100% and every
//     control passes, and records the numbers in `notes`.
// test/system1-validators.test.mjs repeats the agreement check independently.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const require = createRequire(import.meta.url);
const { decide } = require(path.join(ROOT, "tools/system1-validators/run.cjs"));
const { sha256Hex } = require(path.join(ROOT, "tools/system1-validators/lib.cjs"));
const RUBRICS = path.join(ROOT, "skills/bearing-lite/references/system1-rubrics");
const CASES = JSON.parse(readFileSync(path.join(ROOT, "test/fixtures/system1-validators/cases.json"), "utf8"));

const DENIED = ["generate", "propose", "propose_claims", "propose_options", "suggest_options", "rewrite",
  "rewrite_claim", "rewrite_options", "explain", "complete", "chat", "review"];
const SUPPORT = ["tools/system1-validators/lib.cjs"];

/** Validator condition id -> the Python labeler's reason string. */
const GTM_REASONS = {
  push_is_object: "not_an_object", event_is_purchase: "event_not_purchase", ecommerce_is_object: "ecommerce_missing",
  transaction_id_present: "missing_transaction_id", value_present: "missing_value", currency_present: "missing_currency",
  currency_is_iso4217: "currency_not_iso4217", items_is_array: "items_not_array", items_nonempty: "items_empty",
  items_has_identified_item: "no_item_with_id_or_name",
};
const WRANGLER_REASONS = {};
for (const [a, b, k] of [["d1_databases", "DB", "database_id"], ["kv_namespaces", "CACHE", "id"], ["r2_buckets", "ASSETS", "bucket_name"]]) {
  WRANGLER_REASONS[`${a}_is_array`] = `missing_${a}`;
  WRANGLER_REASONS[`${a}_has_${b}`] = `no_${a}_binding_${b}`;
  WRANGLER_REASONS[`${a}_${b}_${k}_nonempty`] = `empty_or_missing_${k}_for_${b}`;
}

const readJsonl = (rel) => readFileSync(path.join(ROOT, rel), "utf8").trim().split("\n").map((l) => JSON.parse(l));
const fileSha = (rel) => sha256Hex(readFileSync(path.join(ROOT, rel)));
const labelOf = (verdict) => (verdict === "VERIFIED" ? "holds" : verdict === "REFUTED" ? "fails" : `ERROR`);

function agreement(mod, items, reasonMap) {
  let agree = 0;
  const disagreements = [];
  for (const it of items) {
    const rec = decide(mod, Buffer.from(it.bytes, "utf8"), it.format);
    const reasons = rec.failed_conditions.map((c) => reasonMap[c]);
    const ok = labelOf(rec.verdict) === it.label &&
      JSON.stringify(reasons) === JSON.stringify(it.reasons) &&
      (it.state_digest === undefined || rec.canonical_input_digest === it.state_digest);
    if (ok) agree += 1;
    else disagreements.push(it.id);
  }
  return { n: items.length, agree, disagreements };
}

const SPECS = [
  {
    file: "validator-gtm-purchase-event.rubric.json",
    module: "tools/system1-validators/gtm-purchase-event.cjs",
    support: SUPPORT,
    reasonMap: GTM_REASONS,
    rubric: {
      rubric_id: "RUB-S1-VAL-GTM-PURCHASE-EVENT",
      title: "GTM dataLayer purchase event conforms to the tracking spec (validator)",
      claim: {
        claim_type: "tracking_event_conformance",
        statement: "The dataLayer push captured for the checkout-complete step is a GA4 `purchase` event that carries transaction_id, value, currency, and a non-empty items array, as the tracking spec requires.",
        eligibility: "deterministic_rule_conformance",
        spec_refs: ["tracking-spec: purchase event"],
      },
      input: {
        state_shape: "json_document",
        source: { kind: "captured_fixture", locator: "test/fixtures/datalayer/purchase-push.json" },
        format_by_extension: { ".json": "json" },
        canonicalization: "rfc8785_jcs",
        input_digest_basis: "raw_file_bytes",
        max_input_bytes: 65536,
        over_limit: "ERROR",
      },
      controls: [
        ["CTL-GTM-PURCHASE-VALID", "test/fixtures/datalayer/controls/purchase-valid.json", "VERIFIED"],
        ["CTL-GTM-PURCHASE-NO-CURRENCY", "test/fixtures/datalayer/controls/purchase-missing-currency.json", "REFUTED"],
        ["CTL-GTM-ADD-TO-CART", "test/fixtures/datalayer/controls/add-to-cart.json", "REFUTED"],
      ],
    },
    dataset: () =>
      ["calibration", "test"].flatMap((s) => readJsonl(`test/fixtures/system1-calibration/gtm-datalayer-event/${s}.jsonl`))
        .map((r) => ({ id: r.id, bytes: r.state, format: "json", label: r.label, reasons: r.truth.reasons, state_digest: r.input_digest })),
    edge: () => CASES.gtm.map((c) => ({ id: c.name, bytes: c.text, format: "json", label: c.label, reasons: c.reasons })),
    datasetDir: "test/fixtures/system1-calibration/gtm-datalayer-event/",
    notes: [
      "Supersedes the Laya rubric RUB-S1-GTM-DATALAYER-PURCHASE for this check: the same six conditions, decided by a pinned program instead of asked of a model (which scored them at chance).",
      "The target file holds exactly one push as JSON (no extractor). `claim.input_digest` is SHA-256 of the file bytes; the evidence also records the SHA-256 of its RFC 8785 form, which equals the Laya datasets' `input_digest` for the same push.",
      "The accepted currency set is the ISO 4217 list pinned in the module source (the Python labeler carries an independent copy). Adding or retiring a code is a new validator version and a new rubric version.",
    ],
  },
  {
    file: "validator-wrangler-required-bindings.rubric.json",
    module: "tools/system1-validators/wrangler-required-bindings.cjs",
    support: [...SUPPORT, "tools/system1-validators/toml.cjs"],
    reasonMap: WRANGLER_REASONS,
    rubric: {
      rubric_id: "RUB-S1-VAL-WRANGLER-REQUIRED-BINDINGS",
      title: "Worker bindings satisfy the resource table (validator)",
      claim: {
        claim_type: "deployment_config_conformance",
        statement: "The Worker's wrangler configuration binds a D1 database as DB, a KV namespace as CACHE, and an R2 bucket as ASSETS, each with a non-empty resource identifier, as the design's resource table requires.",
        eligibility: "deterministic_rule_conformance",
        spec_refs: ["design: Worker resource bindings"],
      },
      input: {
        state_shape: "json_document",
        source: { kind: "repo_file", locator: "wrangler.jsonc", extractor: "keys:d1_databases,kv_namespaces,r2_buckets" },
        format_by_extension: { ".json": "jsonc", ".jsonc": "jsonc", ".toml": "toml" },
        canonicalization: "jsonc_or_toml_to_rfc8785_jcs",
        input_digest_basis: "raw_file_bytes",
        max_input_bytes: 262144,
        over_limit: "ERROR",
      },
      controls: [
        ["CTL-WRANGLER-ALL-BOUND", "test/fixtures/wrangler/controls/all-bound.jsonc", "VERIFIED"],
        ["CTL-WRANGLER-NO-R2", "test/fixtures/wrangler/controls/missing-r2.jsonc", "REFUTED"],
        ["CTL-WRANGLER-WRONG-KV-NAME", "test/fixtures/wrangler/controls/kv-bound-as-kv.jsonc", "REFUTED"],
        ["CTL-WRANGLER-TOML-ALL-BOUND", "test/fixtures/wrangler/controls/all-bound.toml", "VERIFIED"],
        ["CTL-WRANGLER-TOML-LOWERCASE-DB", "test/fixtures/wrangler/controls/lowercase-db.toml", "REFUTED"],
      ],
    },
    dataset: () =>
      ["calibration", "test"].flatMap((s) => readJsonl(`test/fixtures/system1-calibration/wrangler-bindings/${s}.jsonl`))
        .map((r) => ({ id: r.id, bytes: r.source, format: r.source_format, label: r.label, reasons: r.truth.reasons, state_digest: r.input_digest })),
    edge: () => CASES.wrangler.map((c) => ({ id: c.name, bytes: c.source, format: c.format, label: c.label, reasons: c.reasons, state_digest: c.state_digest })),
    datasetDir: "test/fixtures/system1-calibration/wrangler-bindings/",
    notes: [
      "Supersedes the Laya rubric RUB-S1-WRANGLER-REQUIRED-BINDINGS for this check: the same three conditions, decided by a pinned program instead of asked of a model (which scored them near chance and never caught a misnamed binding).",
      "The target is the whole wrangler configuration file; the format comes from its extension (.jsonc/.json as JSONC, .toml as TOML), never from sniffing. The dataset items are scored from their original JSONC or TOML source, not from the extracted state. TOML is read by the subset reader tools/system1-validators/toml.cjs; a construct outside the subset (multi-line strings, dates, hex/octal/binary integers, inf/nan, integers beyond 2^53) is ERROR toml_unsupported_construct, never a guess. The reader agrees with Python's tomllib on every case in test/fixtures/system1-validators/cases.json.",
      "Only top-level d1_databases, kv_namespaces and r2_buckets count; env.<name> sections are parsed but not read, so a binding that exists only under an environment REFUTES.",
    ],
  },
];

for (const spec of SPECS) {
  const mod = require(path.join(ROOT, spec.module));
  const controls = spec.rubric.controls.map(([control_id, locator, expected]) => {
    const bytes = readFileSync(path.join(ROOT, locator));
    const ext = path.extname(locator);
    const rec = decide(mod, bytes, spec.rubric.input.format_by_extension[ext]);
    return { control: { control_id, locator, input_digest: sha256Hex(bytes), expected }, observed: rec.verdict };
  });
  const controlsPass = controls.every((c) => c.observed === c.control.expected);
  const ds = agreement(mod, spec.dataset(), spec.reasonMap);
  const edge = agreement(mod, spec.edge(), spec.reasonMap);
  const eligible = controlsPass && ds.agree === ds.n && edge.agree === edge.n;

  const rubric = {
    kind: "rubric",
    schema_family: "system1",
    schema_version: "1",
    rubric_id: spec.rubric.rubric_id,
    rubric_version: "1.0.0",
    title: spec.rubric.title,
    claim: spec.rubric.claim,
    assurance_eligible: eligible,
    backend: "validator",
    validator: {
      validator_id: mod.VALIDATOR_ID,
      validator_version: mod.VALIDATOR_VERSION,
      implementation: { path: spec.module, sha256: fileSha(spec.module) },
      support_files: spec.support.map((p) => ({ path: p, sha256: fileSha(p) })),
      runtime: { executable: "node", module_system: "commonjs", runtime_dependencies: "none", node_major_min: 18 },
    },
    rule: {
      text: mod.RULE_TEXT,
      conditions: mod.CONDITIONS.map((c) => ({ id: c.id, text: c.text })),
      verdict_map: { all_conditions_hold: "VERIFIED", any_condition_fails: "REFUTED", input_not_decidable: "ERROR" },
    },
    input: spec.rubric.input,
    controls: controls.map((c) => c.control),
    replay: { min_runs: 2, fresh_process: "every_run", require_identical_output_digest: true, output_digest_basis: "sha256_rfc8785_decision_record" },
    operations: { allowed: ["check"], denied: DENIED },
    notes: [
      `Measured agreement with the independent Python labeler (tools/system1-calibration/labelers.py): ${ds.agree}/${ds.n} items of ${spec.datasetDir} (both splits) and ${edge.agree}/${edge.n} edge cases of test/fixtures/system1-validators/cases.json, on the verdict, the failing conditions (mapped to the labeler's reason strings), and the SHA-256 of the canonical state. Controls: ${controls.filter((c) => c.observed === c.control.expected).length}/${controls.length} on their expected verdict. assurance_eligible is true if and only if agreement is 100% and every control passes.` +
        (ds.disagreements.length || edge.disagreements.length ? ` Disagreements: ${[...ds.disagreements, ...edge.disagreements].join(", ")}.` : ""),
      "No model, probability, temperature, threshold, ECE, or epsilon exists for this backend. Replay decides the input in `min_runs` freshly started Node processes and requires byte-identical SHA-256 digests of the RFC 8785 decision record; any difference is INCONCLUSIVE replay_output_divergence.",
      "Run with: node tools/system1-validators/run.cjs --rubric <this file> check <target> <claim-json>, from the repository root. The runner checks the claim's rubric and input digests and every pinned file digest before deciding, and prints backend_output for sealVerification.",
      ...spec.notes,
    ],
  };
  writeFileSync(path.join(RUBRICS, spec.file), JSON.stringify(rubric, null, 2) + "\n");
  console.log(spec.file, `dataset ${ds.agree}/${ds.n}`, `edge ${edge.agree}/${edge.n}`,
    `controls ${controlsPass ? "pass" : "FAIL"}`, eligible ? "eligible" : "NOT eligible");
}

// ---------------------------------------------------------------- round-trip fixture
// test/fixtures/system1-validator-round-trip.json: assurance plans against the
// GTM validator rubric, the backend_output the runner printed for each, and the
// receipt sealVerification emitted. test/system1-validators.test.mjs reseals
// each output and must reproduce the receipt; test/schema-validation.py
// validates outputs, requests and receipts.
{
  const { execFileSync } = await import("node:child_process");
  const bridge = require(path.join(ROOT, "hooks/verification-bridge.cjs"));
  const rubricPath = "skills/bearing-lite/references/system1-rubrics/validator-gtm-purchase-event.rubric.json";
  const rubric = JSON.parse(readFileSync(path.join(ROOT, rubricPath), "utf8"));
  const rubricDigest = sha256Hex(bridge.canonicalJson(rubric));
  const producedBy = { role: "test_engineer.assurance", identity: "ate-val", session: "sess-ate-val" };
  const trips = {};
  for (const [key, target] of [
    ["verified", "test/fixtures/datalayer/purchase-push.json"],
    ["refuted", "test/fixtures/datalayer/controls/add-to-cart.json"],
    ["error_unparseable", "test/fixtures/datalayer/purchase-push-truncated.json"],
  ]) {
    const spec = {
      backend: "validator",
      backend_operation: "check",
      backend_operations: rubric.operations,
      invocation: {
        executable: "node",
        argv_template: ["tools/system1-validators/run.cjs", "--rubric", rubricPath, "--claim-id", "SEIT-VAL-GTM-001", "{operation}", "{target}", "{claim}"],
      },
      claim_id: "SEIT-VAL-GTM-001",
      claim_type: rubric.claim.claim_type,
      claim: {
        kind: "system1_decision",
        backend: "validator",
        rubric_id: rubric.rubric_id,
        rubric_version: rubric.rubric_version,
        rubric_digest: rubricDigest,
        input_digest: fileSha(target),
      },
      target,
      candidate: { candidate_ref: "cand-val-1", candidate_revision: "5f1e0c3a9b7d2e4f6a8c0b1d3e5f7a9c1b3d5e7f" },
      stage: "assurance",
      authority: "assurance",
      expected_result: "VERIFIED",
      selected: true,
      required: true,
    };
    const plan = bridge.planVerification({ ...spec, rubric });
    if (plan.outcome !== "READY") throw new Error(key + ": " + JSON.stringify(plan));
    const stdout = execFileSync(plan.argv[0], plan.argv.slice(1), { cwd: ROOT, encoding: "utf8" });
    const output = JSON.parse(stdout);
    const seal = bridge.sealVerification({ plan, output, produced_by: producedBy });
    if (seal.outcome !== "READY") throw new Error(key + ": " + JSON.stringify(seal));
    trips[key] = { spec, request: plan.request, output, receipt: seal.receipt };
  }
  const fixture = {
    description:
      "Validator backend round trip (assurance authority): specs planned against the frozen, assurance-eligible GTM validator rubric, the backend_output tools/system1-validators/run.cjs printed for each, and the receipt sealVerification emitted. Rebuilt by tools/system1-calibration/build-validator-rubrics.mjs. test/system1-validators.test.mjs reseals every output and must reproduce the receipt; test/schema-validation.py validates outputs, requests and receipts.",
    rubric_path: rubricPath,
    produced_by: producedBy,
    trips,
  };
  writeFileSync(path.join(ROOT, "test/fixtures/system1-validator-round-trip.json"), JSON.stringify(fixture, null, 2) + "\n");
  console.log("round trip:", Object.entries(trips).map(([k, t]) => `${k}=${t.receipt.status}`).join(" "));
}
