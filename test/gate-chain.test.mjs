/** S1 / SEIT-143.01–07: red tests for the deterministic assurance gate chain. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const { ASSURANCE_BUDGET_POLICY } = require(path.join(root, "hooks/policy.cjs"));
const assurance = require(path.join(root, "hooks/assurance-budget.cjs"));
const { evaluateVerification } = require(path.join(root, "hooks/verification.cjs"));
const read = (file) => readFileSync(path.join(root, file), "utf8");
const ORDER = ["build", "types_lint", "red_then_green", "mutation", "changed_line_coverage", "deterministic_verification", "reviewer"];

// The evaluator is deliberately absent at baseline. Each case fails at this
// assertion instead of crashing the file, and will exercise the real export in S5.
function evaluate(gate_declarations, results = {}) {
  assert.equal(typeof assurance.evaluateGateChain, "function", "gate-chain evaluator export is missing");
  return assurance.evaluateGateChain({ gate_declarations, results });
}

const skipped = { status: "NOT_APPLICABLE", reason: "fixture gate is outside this case" };
const declarations = (overrides = {}) => Object.fromEntries(
  ORDER.map((gate) => [gate, overrides[gate] ?? skipped]),
);
const declared = { status: "DECLARED", tool: "fixture-tool", threshold: 80 };
const passing = { tool_available: true, outcome: "PASS", score: 80 };

test("AC-143.01 / SEIT-143.01 fixed seven-gate policy order", () => {
  const block = read("skills/bearing-lite/references/assurance-policy.md").match(/```json\n([\s\S]*?)\n```/);
  assert.ok(block, "assurance policy JSON block is missing");
  assert.deepStrictEqual(ASSURANCE_BUDGET_POLICY.gate_order, ORDER);
  assert.deepStrictEqual(assurance.POLICY.gate_order, ORDER);
  assert.deepStrictEqual(JSON.parse(block[1]).gate_order, ORDER);
});

test("AC-143.02 / SEIT-143.02 claim types and typed-gap rules in both references", () => {
  for (const file of ["skills/test-engineer/SKILL.md", "skills/bearing-lite/references/verification.md"]) {
    const text = read(file);
    for (const term of ["mutation", "changed-line coverage", "red-then-green", "missing tool", "not_run"]) {
      assert.ok(text.includes(term), `${file}: missing ${term} claim/gap rule`);
    }
    assert.match(text, /typed[- ]gap/i, `${file}: missing typed-gap rule`);
  }
});

test("AC-143.03 / SEIT-143.03 declared missing tool and not_run are typed gaps", () => {
  const gates = declarations({ mutation: declared });
  for (const observed of [{ tool_available: false }, { tool_available: true, outcome: "not_run" }]) {
    const got = evaluate(gates, { mutation: observed });
    assert.equal(got.outcome, "NEEDS_MORE_EVIDENCE");
    assert.equal(got.failed_gate, "mutation");
  }
});

test("AC-143.04 / SEIT-143.04 independent boundary rerun and diagnostic-only prose", () => {
  for (const file of ["skills/test-engineer/SKILL.md", "skills/bearing-lite/references/verification.md"]) {
    const text = read(file);
    assert.ok(/Assurance Test Engineer[\s\S]{0,180}independently reruns? the gate[- ]chain[\s\S]{0,100}boundary/i.test(text), `${file}: independent gate-chain boundary rerun rule missing`);
    assert.ok(/author gate[- ]chain receipts?[\s\S]{0,100}diagnostic/i.test(text), `${file}: author gate-chain diagnostic-only rule missing`);
  }
});

test("AC-143.04 / SEIT-143.04 diagnostic receipt cannot satisfy assurance gate (regression guard)", () => {
  const candidate = { candidate_ref: "candidate", candidate_revision: "a".repeat(40) };
  const author = { role: "implementer", identity: "author", session: "author-session" };
  const request = {
    schema_version: "1", kind: "request", ...candidate, claim_id: "gate-chain", claim_type: "gate_chain",
    backend: "node:test", stage: "implementation", authority: "diagnostic", expected_result: "VERIFIED",
    command_configuration: { command: "node --test" }, selected: true, required: true,
  };
  const receipt = {
    schema_version: "1", kind: "receipt", ...candidate, claim_id: "gate-chain", backend: "node:test",
    backend_version: "fixture", command_configuration: request.command_configuration,
    evidence_digest: "b".repeat(64), status: "VERIFIED", authority: "diagnostic",
    stage: "implementation", produced_by: author,
  };
  const got = evaluateVerification({
    request, receipt, candidate, author, gate: "assurance",
    backend: { name: "node:test", enabled: true, available: true },
  });
  assert.equal(got.outcome, "REJECT");
  assert.equal(got.reason, "diagnostic_cannot_satisfy_assurance_gate");
  assert.equal(got.gate_eligible, false);
});

test("AC-143.05 missing-tool / SEIT-143.05 declared gate yields a typed gap", () => {
  const got = evaluate(declarations({ mutation: declared }), { mutation: { tool_available: false } });
  assert.equal(got.outcome, "NEEDS_MORE_EVIDENCE");
  assert.equal(got.failed_gate, "mutation");
});

test("AC-143.05 threshold / SEIT-143.05 score below the declared threshold fails", () => {
  const got = evaluate(declarations({ mutation: declared }), {
    mutation: { tool_available: true, outcome: "PASS", score: 79 },
  });
  assert.equal(got.outcome, "FAIL");
  assert.equal(got.failed_gate, "mutation");
});

test("AC-143.05 fail-fast / SEIT-143.05 later gates cannot pass after first failure", () => {
  const got = evaluate(declarations({ mutation: declared, changed_line_coverage: declared }), {
    mutation: { tool_available: true, outcome: "FAIL", score: 20 },
    changed_line_coverage: passing,
  });
  assert.equal(got.outcome, "FAIL");
  assert.equal(got.failed_gate, "mutation");
  assert.ok(Array.isArray(got.gates), "ordered gate results are missing");
  assert.deepStrictEqual(got.gates.map(({ gate }) => gate), ORDER.slice(0, ORDER.indexOf("mutation") + 1));
  assert.equal(got.gates.some(({ gate, outcome }) => gate === "changed_line_coverage" && outcome === "PASS"), false);
});

test("AC-143.06 / SEIT-143.06 undeclared or reasonless mutation fails closed", () => {
  for (const mutation of [undefined, { status: "NOT_APPLICABLE", reason: "" }]) {
    const gates = declarations();
    if (mutation === undefined) delete gates.mutation;
    else gates.mutation = mutation;
    const got = evaluate(gates);
    assert.equal(got.outcome, "NEEDS_MORE_EVIDENCE");
    assert.equal(got.failed_gate, "mutation");
  }
});

test("AC-143.06 / SEIT-143.06 reasoned non-gate and declared hard gate", () => {
  const nonGate = evaluate(declarations());
  assert.equal(nonGate.outcome, "PASS");
  const hardGate = evaluate(declarations({ mutation: declared }), { mutation: passing });
  assert.equal(hardGate.outcome, "PASS");
  assert.ok(hardGate.gates.some(({ gate, outcome }) => gate === "mutation" && outcome === "PASS"));
});

test("AC-143.07 / SEIT-143.07 red-then-green needs both runs with matching test ids", () => {
  const baseline = { revision: "baseline", outcome: "FAIL", test_ids: ["T-1"] };
  const candidate = { revision: "candidate", outcome: "PASS", test_ids: ["T-1"] };
  const gates = declarations({ red_then_green: { status: "DECLARED", tool: "node:test", threshold: "same test ids" } });
  const run = (receipt) => evaluate(gates, {
    red_then_green: { tool_available: true, outcome: "PASS", receipt },
  });
  for (const receipt of [
    { candidate },
    { baseline },
    { baseline, candidate: { ...candidate, test_ids: ["T-2"] } },
  ]) {
    const got = run(receipt);
    assert.equal(got.outcome, "NEEDS_MORE_EVIDENCE");
    assert.equal(got.failed_gate, "red_then_green");
  }
  assert.equal(run({ baseline, candidate }).outcome, "PASS");
});

test("AC-143.07 / SEIT-143.07 receipt prose binds baseline failure to candidate pass", () => {
  for (const file of ["skills/test-engineer/SKILL.md", "skills/implementer/SKILL.md"]) {
    const text = read(file);
    assert.ok(/red[- ]then[- ]green receipt[\s\S]{0,180}baseline failing run[\s\S]{0,100}candidate passing run/i.test(text), `${file}: baseline-failure/candidate-pass receipt rule missing`);
  }
});

test("W2-F1 reviewer consumes only the latest PASS gate-chain receipt for its unit", (t) => {
  const fs = require("node:fs");
  const os = require("node:os");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "w2-gate-chain-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const declaration_path = path.join(dir, "declaration.json");
  const task_record_path = path.join(dir, "task.json");
  fs.writeFileSync(declaration_path, JSON.stringify({ phases: [{ phaseId: "P1" }] }));
  fs.writeFileSync(task_record_path, JSON.stringify({ journey: "L1", units: [] }));
  const request = {
    journey: "L1", unit_kind: "phase", request_scope: "phase", assurance_unit: "P1",
    cadence: "phase", role: "reviewer", declaration_path, task_record_path,
  };
  for (const later of ["FAIL", "VERIFIED"]) {
    const receipts = ["PASS", later].map((verdict) => ({ kind: "gate_chain", unit_id: "P1", verdict }));
    assert.deepEqual(assurance.evaluateAssuranceBudget({ ...request, receipts }), {
      outcome: "NEEDS_MORE_EVIDENCE", reason: "reviewer_gate_chain_receipt_missing",
    }, `later ${later} must supersede the earlier PASS`);
  }
});

test("W2-F2 declared gate with omitted tool_available is a typed gap", () => {
  const got = evaluate(declarations({ mutation: declared }), { mutation: { outcome: "PASS", score: 100 } });
  assert.equal(got.outcome, "NEEDS_MORE_EVIDENCE");
  assert.equal(got.failed_gate, "mutation");
});

test("W2-F3 red-then-green rejects duplicate candidate ids replacing a baseline id", () => {
  const gates = declarations({ red_then_green: { status: "DECLARED", tool: "node:test", threshold: "same test ids" } });
  const got = evaluate(gates, { red_then_green: {
    tool_available: true, outcome: "PASS",
    receipt: {
      baseline: { outcome: "FAIL", test_ids: ["T-1", "T-2"] },
      candidate: { outcome: "PASS", test_ids: ["T-1", "T-1"] },
    },
  } });
  assert.equal(got.outcome, "NEEDS_MORE_EVIDENCE");
  assert.equal(got.failed_gate, "red_then_green");
});

const systemOne = { status: "DECLARED", tool: "laya", threshold: "all_required_claims_gate_eligible" };
const claim = (extra = {}) => ({ claim_id: "SEIT-S1-001", backend: "laya", required: true, gate_eligible: true, ...extra });
const dvResult = (claims) => ({ tool_available: true, outcome: "PASS", claims });

test("System One: gate_order holds deterministic_verification in the seventh slot", () => {
  assert.equal(ASSURANCE_BUDGET_POLICY.gate_order[5], "deterministic_verification");
  assert.equal(ASSURANCE_BUDGET_POLICY.gate_order.includes("reverify"), false);
  assert.deepStrictEqual(ASSURANCE_BUDGET_POLICY.deterministic_verification_gate, {
    tools: ["jev", "laya", "validator", "jev+laya", "jev+validator", "laya+validator", "jev+laya+validator"],
    threshold: "all_required_claims_gate_eligible",
    retired_gate_names: ["reverify"],
  });
  const got = evaluate(declarations({ deterministic_verification: systemOne }), {
    deterministic_verification: dvResult([claim(), claim({ claim_id: "SEIT-S1-002", required: false, gate_eligible: false })]),
  });
  assert.equal(got.outcome, "PASS");
  assert.deepStrictEqual(got.gates.map(({ gate }) => gate), ORDER);
  const both = evaluate(declarations({ deterministic_verification: { ...systemOne, tool: "jev+laya" } }), {
    deterministic_verification: dvResult([claim(), claim({ claim_id: "SEIT-S1-003", backend: "jev" })]),
  });
  assert.equal(both.outcome, "PASS");
});

test("System One: validator is a declared tool identity and must be named for its claims", () => {
  const alone = evaluate(declarations({ deterministic_verification: { ...systemOne, tool: "validator" } }), {
    deterministic_verification: dvResult([claim({ backend: "validator" })]),
  });
  assert.equal(alone.outcome, "PASS");
  const hybrid = evaluate(declarations({ deterministic_verification: { ...systemOne, tool: "laya+validator" } }), {
    deterministic_verification: dvResult([claim({ backend: "validator" }), claim({ claim_id: "SEIT-S1-004" })]),
  });
  assert.equal(hybrid.outcome, "PASS");
  // A laya-only declaration does not cover a required validator claim: no backend covers another.
  const undeclared = evaluate(declarations({ deterministic_verification: systemOne }), {
    deterministic_verification: dvResult([claim({ backend: "validator" })]),
  });
  assert.equal(undeclared.failed_gate, "deterministic_verification");
  assert.equal(undeclared.reason, "claim_backend_undeclared");
  // Only the listed, ordered combinations are identities.
  const reordered = evaluate(declarations({ deterministic_verification: { ...systemOne, tool: "validator+laya" } }), {
    deterministic_verification: dvResult([claim({ backend: "validator" })]),
  });
  assert.equal(reordered.reason, "backend_identity_undeclared");
});

test("System One: a frozen plan still declaring reverify fails closed at the slot, no alias", () => {
  const legacy = declarations();
  delete legacy.deterministic_verification;
  legacy.reverify = { status: "DECLARED", tool: "reverify", threshold: 1 };
  const got = evaluate(legacy, { reverify: passing, deterministic_verification: passing });
  assert.equal(got.outcome, "NEEDS_MORE_EVIDENCE");
  assert.equal(got.failed_gate, "deterministic_verification");
  assert.equal(got.reason, "retired_gate_name_declared");
  // A leftover reverify key beside the new slot is still ambiguous: fail closed.
  const mixed = evaluate({ ...declarations(), reverify: skipped });
  assert.equal(mixed.outcome, "NEEDS_MORE_EVIDENCE");
  assert.equal(mixed.reason, "retired_gate_name_declared");
  // reverify is not a System One tool identity inside the new slot either.
  const renamed = evaluate(declarations({ deterministic_verification: { ...systemOne, tool: "reverify" } }), {
    deterministic_verification: dvResult([claim({ backend: "reverify" })]),
  });
  assert.equal(renamed.failed_gate, "deterministic_verification");
  assert.equal(renamed.reason, "backend_identity_undeclared");
});

test("System One: slot passes only when every required claim is gate_eligible", () => {
  const run = (claims, declaration = systemOne) => evaluate(
    declarations({ deterministic_verification: declaration }),
    { deterministic_verification: dvResult(claims) },
  );
  const cases = [
    [[claim({ gate_eligible: false })], "required_claim_not_gate_eligible"],
    [[claim(), claim({ claim_id: "SEIT-S1-002", gate_eligible: false })], "required_claim_not_gate_eligible"],
    [[], "required_claim_missing"],
    [[claim({ required: false })], "required_claim_missing"],
    [[claim({ backend: "jev" })], "claim_backend_undeclared"],
  ];
  for (const [claims, reason] of cases) {
    const got = run(claims);
    assert.equal(got.outcome, "NEEDS_MORE_EVIDENCE", reason);
    assert.equal(got.failed_gate, "deterministic_verification");
    assert.equal(got.reason, reason);
  }
  const loose = run([claim()], { ...systemOne, threshold: 0.9 });
  assert.equal(loose.reason, "threshold_not_policy");
  const na = evaluate(declarations({
    deterministic_verification: { status: "NOT_APPLICABLE", reason: "no claim passes the System One eligibility test" },
  }));
  assert.equal(na.outcome, "PASS");
});
