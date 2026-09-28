# Proposal: Jev and Laya as the deterministic-verification backends

Status: **Applied.** Sections 1 to 12 are implemented on branch
`system1-backend`; section 13 (hosting) remains documentation. The sections
below keep the original proposal text; "Applied with changes" lists where the
implementation departs from it and why.

## Applied with changes

- **Section 1, gate shape and typed reasons.** The proposal said
  `evaluateGateChain` needs no code change. It needed some: without it a frozen
  plan declaring `reverify` failed at the new slot with no typed reason, and a
  `DECLARED` slot would accept any `tool` (including `reverify`) and any
  threshold. `ASSURANCE_BUDGET_POLICY` therefore gains
  `deterministic_verification_gate`
  (`tools: ["jev", "laya", "jev+laya"]`,
  `threshold: "all_required_claims_gate_eligible"`,
  `retired_gate_names: ["reverify"]`), mirrored in the `assurance-policy.md`
  block. At the `deterministic_verification` slot the evaluator returns
  `NEEDS_MORE_EVIDENCE` with a typed `reason`:
  `retired_gate_name_declared` (any `reverify` key in the declaration, even
  beside the new slot; no alias), `backend_identity_undeclared`,
  `threshold_not_policy`, `required_claim_missing`,
  `claim_backend_undeclared`, or `required_claim_not_gate_eligible`. The slot
  result carries `claims: [{ claim_id, backend, required, gate_eligible }]`,
  one entry per claim's `evaluateVerification` judgement.
- **Section 2.** The added sentence is followed by a short paragraph stating
  the slot semantics and the retired-name failure.
- **Section 3.** The opening sentence is wrapped so "never downloads" stays on
  one line (`test/verification.test.mjs` matches it).
- **Sections 4 and 7, line budget.** `skills-conformance` caps a skill at 60
  lines, so the new test-engineer and onboard-bearing text is reflowed onto
  wider lines instead of adding lines.
- **Section 7, Reverify exclusivity.** onboard-bearing asks `jev` then `laya`
  as separate questions with no preselection. Enabling either records
  `reverify.enabled: false`; an existing `reverify.enabled: true` needs an
  explicit answer to disable it first, otherwise `OWNER_DECISION_REQUIRED` and
  neither is enabled. The onboarding guide says the same.
- **`system1-rubrics.md` section 8.** "This rename is a proposal until ..."
  now states that the rename is applied and names the typed failure.
- **Section 12, where the cases live.** The laya round trip
  (`planVerification` -> `sealVerification` -> `evaluateVerification`) is one
  suite in `test/verification-bridge.test.mjs`, driven by
  `test/fixtures/system1-laya-round-trip.json` (spec bound to the example
  `laya-gtm-datalayer-event` rubric by digest, three backend outputs, and the
  exact receipts). It covers assurance PASS on VERIFIED, INCONCLUSIVE
  `replay_probability_divergence` not gate-eligible, DERIVED sealing
  INCONCLUSIVE, generative operations refused, and a `jev` receipt against a
  `laya` request rejected. After calibration left every shipped rubric
  `assurance_eligible: false`, `planVerification` refuses a `jev`/`laya`
  assurance plan without its rubric (`rubric_missing`), whose rubric does not
  hash to `rubric_digest` (`rubric_digest_mismatch`), whose rubric pins another
  backend (`rubric_backend_mismatch`), or whose rubric is not eligible
  (`rubric_not_assurance_eligible`). The fixture is therefore a diagnostic run,
  and the assurance cases use an in-test synthetic eligible copy of the GTM
  rubric. `test/verification.test.mjs` renames the download
  case and runs it for `reverify`, `jev`, and `laya`;
  `test/required-semantics.test.mjs` adds the `jev`/`laya` selected-versus-
  required split. `test/gate-chain.test.mjs` adds the slot, legacy-slot, and
  eligibility cases. `test/schema-validation.py` validates the example
  rubrics, the fixture backend outputs and command configurations against
  `system1.schema.json`, the fixture receipts against
  `verification.schema.json` (they fail against the pre-section-11 schema),
  and the profile exclusivity positives and negatives.

Already on this branch:

- `schemas/system1.schema.json`: rubric (discriminated on `backend`),
  `command_configuration`, and `backend_output` for the `system1` family.
- `schemas/profiles.schema.json`: `deterministic_verification.jev` and
  `.laya` (`enabled`, optional `required`, optional `gateway` of env-var
  names), `laya.default_checkpoint`, and the rule that `reverify.enabled: true`
  is invalid while `jev.enabled` or `laya.enabled` is true.
- `skills/bearing-lite/references/system1-rubrics.md` and four example rubrics
  in `skills/bearing-lite/references/system1-rubrics/`.

Decision recorded here: the seventh gate is renamed `reverify` to
`deterministic_verification` in the same position (rationale in
`system1-rubrics.md` section 8).

## 1. `hooks/policy.cjs`

Replace the `gate_order` array:

```js
  gate_order: [
    "build",
    "types_lint",
    "red_then_green",
    "mutation",
    "changed_line_coverage",
    "deterministic_verification",
    "reviewer",
  ],
```

No other policy field changes. `hooks/assurance-budget.cjs` iterates
`POLICY.gate_order`, so `evaluateGateChain` picks the rename up without code
changes. Consequence: a frozen plan whose `gate_declarations` still names
`reverify` fails closed at that slot (`NEEDS_MORE_EVIDENCE`,
`failed_gate: "deterministic_verification"`). That is intended. No alias is
added, because an alias would let an old gate name stand in for a new binding.
In-flight Lifecycles re-declare the slot through an owner amendment. Frozen
historical plans under `docs/plans/` are not rewritten.

Slot semantics to state in the gate-chain declaration: `DECLARED` with
`tool` set to the backend identity (`"laya"` or `"jev"`, or `"jev+laya"` when
claims use both) and `threshold: "all_required_claims_gate_eligible"`. The
result is `PASS` only when every required claim's `evaluateVerification`
returned `gate_eligible: true`. When there is no eligible claim, declare
`NOT_APPLICABLE` with a reason, for example
`"no claim passes the System One eligibility test"`.

## 2. `skills/bearing-lite/references/assurance-policy.md`

`test/policy-drift.test.mjs` deep-compares this JSON block to `policy.cjs`, so
it changes in the same commit as section 1. Replace the `gate_order` line:

```json
  "gate_order": ["build", "types_lint", "red_then_green", "mutation", "changed_line_coverage", "deterministic_verification", "reviewer"],
```

Add one sentence after the opening paragraph:

> The `deterministic_verification` gate passes only when every required
> System One claim (`jev` or `laya`) has an independent assurance receipt that
> `hooks/verification.cjs` marks `gate_eligible`; see
> `references/system1-rubrics.md`.

## 3. `skills/bearing-lite/references/verification.md`

In "Backend activation", replace:

> Reverify identity stays `reverify`; a generic backend name must not stand in
> for an absent binding. Profile `reverify.enabled` records user configuration;
> availability does not select Reverify for every task. Planning Test Engineer
> selects it on an applicable binary-level SEIT claim; Plan Integrator copies
> that selection and must not invent V&V.

with:

> Backend identity is `jev` or `laya` and stays that name in every request,
> receipt, and gate declaration. A generic name such as `system1` must not stand
> in for an absent binding, and one backend never substitutes for the other
> inside an assurance receipt: switching backend is a new rubric, a new binding,
> and a plan amendment. Profile `jev.enabled` and `laya.enabled` record user
> configuration; availability does not select a backend for any task. The
> Planning Test Engineer selects one only on a SEIT claim that passes the
> eligibility test in `references/system1-rubrics.md` and binds it to one frozen
> rubric (id, version, digest). Plan Integrator copies that selection and must
> not invent V&V. `reverify` is a legacy identity: it may not be enabled
> together with `jev` or `laya`.

In the opening paragraph, replace "Reverify is optional profile configuration;
this adapter never downloads or installs it." with "System One backends are
optional profile configuration; this adapter never downloads, installs, or
calls them."

Add under "Receipt bridge", after the three refusals:

> For `jev` and `laya`, the backend output follows `schemas/system1.schema.json`
> `backend_output`: one result whose `verdict` is mechanically derived from the
> frozen rubric (thresholds, calibration, replay), and whose evidence records
> rubric digest, model revision, checkpoint, gateway request and log ids, and
> every replay run. A verdict reconstructed rather than read (for example from a
> gateway log after a timeout) is marked `DERIVED` and seals INCONCLUSIVE.

## 4. `skills/test-engineer/SKILL.md`

Algorithm step 1, replace "Define applicable deterministic claims; select
Reverify only on an applicable binary-level claim." with:

> Define applicable deterministic claims. Select a System One backend (`jev`
> or `laya`, Laya preferred for assurance) only on a claim that passes the
> eligibility test in `bearing-lite/references/system1-rubrics.md`, and bind
> it to one frozen rubric by id, version, and digest. Never let a backend
> propose, generate, or reword a claim or its options.

Algorithm step 2, append:

> For System One claims, rerun each frozen rubric with its replay protocol (at
> least two runs, including an uncached or fresh-process run) and attach the
> `assurance` receipts; a replay divergence or failed control is INCONCLUSIVE,
> never PASS.

## 5. `skills/planning-and-design/SKILL.md`

Step 2, replace "select Reverify only on applicable binary-level SEIT claims"
with "select a System One backend (`jev` or `laya`) only on SEIT claims that
pass the eligibility test in `bearing-lite/references/system1-rubrics.md`,
each bound to one frozen rubric".

## 6. `skills/plan-integrator/SKILL.md`

Step 5, replace "never invent claims, methods, or Reverify selection." with
"never invent claims, methods, rubrics, or System One backend selection
(`jev` / `laya`)."

## 7. `skills/onboard-bearing/SKILL.md`

Step 3, replace "optional Reverify." with "optional System One backends
(`jev`, `laya`: enabled, required, and the jev-gateway env-var names), plus
`laya.default_checkpoint` when Laya is enabled."

Replace "Declining Reverify or its download persists `reverify.enabled: false`
for that named profile." with:

> Declining a System One backend persists `jev.enabled: false` or
> `laya.enabled: false` for that named profile. A profile that already holds
> `reverify.enabled: false` keeps it (`reverify.enabled: false` stays valid).
> A profile holding `reverify.enabled: true` cannot also enable `jev` or
> `laya`: return `OWNER_DECISION_REQUIRED` and ask whether to disable Reverify
> first. Record gateway ids, endpoints, and tokens only as env-var names; store
> no credentials.

Keeping the literal `reverify.enabled: false` keeps `test/s1-contracts.test.mjs`
("onboard-bearing asks one setting at a time") green.

## 8. `README.md`

Step 3, replace "and optional Reverify." with "and optional System One
verification backends (Jev, Laya)."

Step 4, replace the Reverify paragraph with:

> 4. If you decline Jev or Laya, onboard-bearing persists `jev.enabled: false`
>    or `laya.enabled: false` for that named profile and does not ask again
>    during ordinary Lifecycles. Jev is a hosted third-party decision model;
>    Laya is an open-weights model you host yourself. Bearing Lite does not
>    bundle, download, or call either one; the adapter only judges receipts a
>    caller produces from a frozen rubric
>    (`skills/bearing-lite/references/system1-rubrics.md`). Legacy
>    `reverify.enabled: false` stays valid; `reverify.enabled: true` cannot be
>    combined with Jev or Laya.

`test/public-boundary.test.mjs` accepts any `enabled: false` wording, so it
stays green.

## 9. `docs/guides/onboarding.md` and `docs/architecture/bearing-delivery-lifecycle.md`

Onboarding guide: rename the `## Reverify` section to
`## Deterministic verification (Jev, Laya)` with the same content as README
step 4, plus the gateway env-var names. Architecture doc: replace "Declining
Reverify persists `reverify.enabled: false`." with "Declining Jev or Laya
persists `jev.enabled: false` or `laya.enabled: false`." Line 17 of the guide:
"Reverify" becomes "the System One backends (Jev, Laya)".

## 10. `hooks/verification.cjs` (comments only)

Line 6: "Reverify is one optional backend; availability never selects it for a
task." becomes "Backends (`jev`, `laya`) are optional; availability never
selects one for a task." Line 171 comment: "Reverify/download" becomes
"Backend download or invocation". No logic change. The adapter is
backend-agnostic, which is why `jev` and `laya` need no code there.

## 11. `schemas/verification.schema.json` (pre-existing gap, found while validating)

`sealVerification` emits `evidence_tier`, `backend_verdict`, and optionally
`evidence_engine` on every receipt, but the receipt definition sets
`additionalProperties: false` and lists none of them. So any sealed receipt,
Reverify or System One, fails this schema today. Add to `$defs.receipt.properties`:

```json
"evidence_tier": { "type": "string", "enum": ["observed", "derived"] },
"backend_verdict": { "$ref": "#/$defs/status" },
"evidence_engine": { "$ref": "#/$defs/nonempty" }
```

## 12. Tests

- `test/gate-chain.test.mjs` line 15: `ORDER` replaces `"reverify"` with
  `"deterministic_verification"`. The AC-143.01 title comment "seven-gate" is
  unchanged.
- `test/policy-drift.test.mjs`: no edit. It stays green only if sections 1 and
  2 land together.
- `test/verification.test.mjs`, `test/verification-bridge.test.mjs`,
  `test/required-semantics.test.mjs`: keep the existing `reverify` fixtures
  (they test the backend-agnostic adapter) and add parallel cases:
  1. A `laya` plan from a rubric's `operations` refuses `propose_claims` with
     `generative_backend_operation_denied`.
  2. A `laya` output with `strength: "DERIVED ..."` seals INCONCLUSIVE
     (`evidence_tier: derived`).
  3. A receipt with `backend: "jev"` against a `backend: "laya"` request is
     `claim_or_backend_mismatch`, which confirms there is no silent fallback.
  4. An INCONCLUSIVE `replay_probability_divergence` receipt is not
     `gate_eligible`.
  Rename "never downloads Reverify even when asked" to "never downloads a
  backend even when asked".
- `test/profile-capability-freeze.test.mjs`: add one case freezing
  `{ laya: { enabled: true, default_checkpoint: "laya" }, jev: { enabled: false } }`
  and asserting deep-copy isolation. The existing `reverify` cases stay.
- `test/schema-validation.py`: add a SEIT row block that validates every
  `skills/bearing-lite/references/system1-rubrics/*.rubric.json` against
  `schemas/system1.schema.json`, and profile negatives for `reverify` plus
  `laya`/`jev` enabled together. Equivalent checks were run by hand for this
  branch but are not committed as a test.
- `test/s1-contracts.test.mjs`, `test/public-boundary.test.mjs`: no edit
  needed if sections 7 and 8 keep the quoted literals.

## 13. Hosting note: Laya behind jev-gateway and AI Gateway

- **Serve.** Run `laya-serve` (`pip install "laya[serve]"`, pinned
  `laya==0.3.21`) in a Cloudflare Container or on any CPU or GPU host. Pin weights
  with `revision=<commit sha>`, preload only the pinned checkpoints
  (`LAYA_PRELOAD=1`), and set `LAYA_API_KEY`. Without that key the server binds
  `0.0.0.0` with no auth. For assurance, prefer CPU fp32 with the TileLang fast
  path off. That configuration is the most reproducible, and it lets
  `probability_epsilon` sit near 1e-6.
- **Route.** `laya-serve` exposes the Jev-compatible `POST /v1/systemone`. In
  Cloudflare AI Gateway, register it as a custom provider next to TypeSafe Jev.
  The `jev-gateway` Worker picks the upstream by the request's pinned backend,
  never by availability. An unreachable upstream returns ERROR
  `backend_unavailable` and never reroutes to the other backend.
- **Cache.** Keep AI Gateway caching on. Set `cf-aig-cache-key` to a hash
  of backend, model revision, checkpoint, rubric digest, question digest, input
  digest, and calibration, so a cached answer can never cross a pin. The replay
  freshness run sends `cf-aig-skip-cache: true`, and the runner records `cache`
  as `HIT`, `MISS`, or `BYPASS` per run.
- **Log.** Keep AI Gateway logging on. The runner copies each run's gateway
  request id and log id into the evidence, which the receipt digest binds.
- **Secrets.** Worker secrets or bindings hold the gateway id, endpoint,
  `LAYA_API_KEY`, and the Jev key. Profiles and rubrics carry only env-var names
  (`JEV_GATEWAY_AI_GATEWAY_ID`, `JEV_GATEWAY_ENDPOINT`, `JEV_GATEWAY_TOKEN`).
- **Routing metadata.** The Worker forwards Laya's `routing` block unchanged.
  The runner compares `routing.model` with the rubric checkpoint and seals ERROR
  `checkpoint_mismatch` when they differ.
