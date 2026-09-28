# System One rubrics (Jev, Laya, and validator)

Schema: `schemas/system1.schema.json`. Adapter contract: `references/verification.md`.
Examples: `references/system1-rubrics/*.rubric.json`.

A System One decision model scores a fixed set of typed options for a fixed
input in one forward pass and returns a hard answer plus a calibrated
probability. It never generates text. Bearing Lite uses two such backends,
`jev` (TypeSafe Jev, hosted) and `laya` (convaiinnovations/laya, open weights),
**only for deterministic execution**: a claim is judged by running a fixed,
versioned model against fixed inputs and fixed typed options, under thresholds
frozen in the plan. They are never used for open-ended judgment, for generating
or proposing claims or options, or for code review.

A rubric is the unit of freezing. It pins exactly one backend, one immutable
model revision, one typed question and its digest, the decision thresholds,
the calibration, the input canonicalization and context policy, known-answer
controls, the replay protocol, the gateway cache policy, and a verdict-only
operation allowlist. Its SHA-256 over canonical JSON (the bridge's
`canonicalJson`) is bound into every claim and every evidence record.

A third backend identity, `validator`, shares the schema family but is **not a
model**: it is a pinned, dependency-free Node program under
`tools/system1-validators/` that decides a rule expressible as code exactly
(section 2a). Same input bytes, same verdict: it has no probability,
temperature, calibration, threshold, ECE, or epsilon, and the schema forbids
them on a validator rubric. It is unrelated to the retired Validator role.

## 1. Eligibility test

A claim is eligible for a System One backend only when **all** hold:

1. **Closed options.** The answer space is a fixed, written set (yes/no, named
   categories, or ordered levels), authored by the Planning Test Engineer before
   the candidate exists.
2. **Fixed rule text.** The rule the input is judged against is written into the
   question and derives from a requirement, design item, or published clause.
3. **Fixed, bounded input.** The input is a named artifact of the candidate,
   extracted by a deterministic step and canonicalized to bytes that fit the
   pinned context limit without truncation.
4. **Holds/fails partition.** Some options mean the claim holds and some mean it
   fails; any remaining option (for example "not applicable") maps to
   INCONCLUSIVE.
5. **Known answers exist.** At least one input that must VERIFY and one that
   must REFUTE can be written as controls.
6. **No cheaper exact oracle (decision models).** If a parser, schema, type
   checker, or test can decide the claim exactly, that is the method: a
   `validator` rubric when the check must be a frozen, receipted gate claim,
   otherwise an ordinary test. `laya` and `jev` are for what code cannot
   decide: one semantic condition over natural-language text.
7. **One condition per Laya question.** Measured on the pinned checkpoints,
   Laya scores multi-condition rules at chance and every control lands on
   INCONCLUSIVE (`docs/calibration/system1-calibration-report.md`). A rule
   that is a conjunction is split into one rubric per condition, and the claim
   holds only when every one of them VERIFIES.

| Eligible | Not eligible |
| --- | --- |
| A captured dataLayer push meets the six `purchase` conditions of the tracking spec (`validator`). | "Is our tracking good?" (open-ended). |
| A locale's consent banner states the purpose of data collection, one disclosure per rubric (`laya`, multilingual). | "Write a compliant banner" or "suggest missing disclosures" (generative). |
| Wrangler bindings (JSONC or TOML) satisfy the resource table (`validator`). | All three consent disclosures asked of Laya in one question (measured at chance). |
| A diff hunk to wrangler config puts no secret value under `vars`, per an existing Jev project rule (`jev`). | "Review this PR" or "is this code correct?" (code review). |
| A support-macro reply is classified into fixed escalation categories (`laya`, choice). | Choosing which claims to verify, or rewording a claim so it passes. |

## 2. Backend selection by the Planning Test Engineer

This replaces "select Reverify only on an applicable binary-level claim".

> Define applicable deterministic claims. Select a backend (`validator`,
> `laya`, or `jev`) only on a SEIT claim that passes the eligibility test in
> `references/system1-rubrics.md`, in the order of the selection guide, and
> bind it to exactly one frozen rubric (id, version, digest). Availability or
> profile enablement never selects a backend. Plan Integrator copies the
> selection and the rubric binding; it never invents a claim, a rubric, or a
> backend.

Selection guide, in order:

1. **`validator` first** for anything expressible as code: field presence and
   values, exact names, enumerations, structure of JSON, JSONC, or TOML, and
   any conjunction of such conditions. It decides the rule exactly; its bar is
   100% agreement with an independent labeler plus passing controls.
2. **`laya` only** for a single-condition semantic question over text that
   code cannot decide reliably (for example whether a consent banner in any of
   eight languages states a purpose; keyword lists are brittle there). One
   condition per rubric; pin `laya-multilingual` for multilingual input, or a
   fine-tuned checkpoint published as its own pinned revision.
3. **`jev` only** where a calibrated Jev rule already exists for this exact
   check (for example an abide project rule) and re-deriving it would change
   the rule, or where the option set exceeds Laya's option-prompt budget.

Any of the three may be enabled in a profile; each rubric still pins one.
Choosing another backend for an existing claim is a new rubric, a new binding,
and a plan amendment, never a fallback. Which shipped rubric owns which check,
and the measurements behind each `assurance_eligible` flag, are in the Hybrid
section of `docs/calibration/system1-calibration-report.md`.

## 2a. Validator rubrics

A validator rubric (`backend: "validator"`) pins, instead of a model:

- `validator`: `validator_id` and version, the implementation path and the
  SHA-256 of its source, every support file it loads by SHA-256, and the
  runtime (`node`, CommonJS, no runtime dependencies, minimum Node major);
- `rule`: the rule text, the conditions in evaluation order (equal to the
  module's `CONDITIONS`), and the fixed verdict map: every condition holds is
  VERIFIED, any fails is REFUTED, undecidable input is ERROR;
- `input`: the format chosen by file extension (never sniffed), the
  canonicalization the rule is decided on, `input_digest_basis:
  "raw_file_bytes"` (the claim's `input_digest` is SHA-256 of the target
  file), and `max_input_bytes`;
- known-answer `controls` with real input digests (at least one VERIFIED and
  one REFUTED) and `replay`: every run in a fresh process, byte-identical
  SHA-256 of the canonical decision record across at least two runs;
- `operations.allowed: ["check"]`.

The caller runs the backend client like any other; the bridge never runs it:
`node tools/system1-validators/run.cjs --rubric <rubric> check <target>
<claim-json>`, from the repository root (an `invocation` of `executable:
"node"` with that argv template). It checks the claim's rubric digest, every
pinned file digest, the target's size and digest, runs every control, decides
the target in fresh processes, and prints `backend_output` for
`sealVerification`. Failures are typed: ERROR `claim_malformed` (the bridge's
malformed-claim rejection), `rubric_digest_mismatch`,
`validator_digest_mismatch`, `input_unresolvable`, `input_digest_mismatch`,
`input_over_size_limit`, `input_unparseable`, `input_shape_invalid`, or
`toml_unsupported_construct`; INCONCLUSIVE `control_failed` or
`replay_output_divergence`. A rubric is `assurance_eligible` only when the
program agrees with an independent labeler on 100% of the rule's labeled
dataset and every control passes.

Checkpoint pinning (Laya): assurance rubrics set `model.selection: "pinned"`.
The Laya `Router` chooses a checkpoint from the input's language and script, so
two candidates can be judged by different models under one rubric. `router_auto`
is valid only on a rubric with `assurance_eligible: false` (diagnostic use). A
run whose served routing metadata names another checkpoint is ERROR
`checkpoint_mismatch`.

## 3. Thresholds and calibration

Frozen in the rubric, never chosen at run time:

- **Hard answer.** argmax option (choice), argmax level (score), `yes` iff
  p(yes) > 0.5 (noul). An exact top tie is INCONCLUSIVE `answer_tie`.
- **Probability basis.** The calibrated probability mass of the option set that
  contains the hard answer (`claim_holds_options` or `claim_fails_options`).
  Never the raw logit, never an uncalibrated softmax, never Laya's
  `act_probability` head (it carries no usable signal).
- **Thresholds.** `verify_threshold` and `refute_threshold`, each in
  [0.5, 0.999]; assurance-eligible rubrics require at least 0.8. Asymmetric
  thresholds are allowed (for example refute at 0.85, verify at 0.9).
- **Calibration.** Laya checkpoints ship over-confident: a frozen temperature
  per (question type, option count), fitted on the rubric's own calibration set
  (digest and size recorded, at least 50 items), is required. Jev may use
  provider probabilities only if the measured ECE on the calibration set is at or
  below `max_ece` (at most 0.15); otherwise fit a temperature too. A changed
  temperature, calibration set, or threshold is a new `rubric_version`.
- **Controls.** At least one VERIFIED and one REFUTED known-answer control, run
  with the same rubric in the same session. A control that maps to the wrong
  status makes the claim INCONCLUSIVE `control_failed`. Controls catch
  label-following (Laya's `noul` can follow its `false`/`true` labels on the
  English checkpoint) and silent serving drift.
- **noul caution.** Prefer a two-option `choice` with neutral keys (`A`/`B`) and
  the yes/no wording in the descriptions when controls show label-following.

## 4. Replay protocol

An assurance run executes the claim `replay.min_runs` times (at least 2) and
must satisfy `replay.freshness`:

- `one_uncached_run`: at least one run bypasses the AI Gateway cache.
- `one_fresh_process_run`: at least one run on a freshly started model process.
- `uncached_and_fresh_process`: both (recommended for Laya).

Each run maps through the thresholds on its own. The claim status is that
common status only when every run has the identical hard answer, the identical
status, and pairwise probability deltas at or below `probability_epsilon`
(Laya on pinned CPU fp32 weights in eval mode: about 1e-6; GPU or hosted Jev:
up to 0.02). Otherwise INCONCLUSIVE with the replay reason. Every run records
the gateway request id, log id, cache status, fresh-process flag, and served
revision, and the whole output is digested into the receipt.

Diagnostic runs may use `min_runs: 1`. They remain diagnostic receipts and can
never satisfy an assurance gate.

## 5. Status mapping

| Condition (per run, then replay) | Status | Reason |
| --- | --- | --- |
| Answer in holds set AND holds mass >= verify_threshold; all runs agree | VERIFIED | none |
| Answer in fails set AND fails mass >= refute_threshold; all runs agree | REFUTED | none |
| Answer in holds set, mass below verify_threshold | INCONCLUSIVE | `below_verify_threshold` |
| Answer in fails set, mass below refute_threshold | INCONCLUSIVE | `below_refute_threshold` |
| Answer in neither set | INCONCLUSIVE | `answer_not_decisive` |
| Exact tie for the top option | INCONCLUSIVE | `answer_tie` |
| Runs disagree on answer / status / probability beyond epsilon | INCONCLUSIVE | `replay_answer_divergence` / `replay_status_divergence` / `replay_probability_divergence` |
| No uncached or fresh-process run | INCONCLUSIVE | `replay_freshness_unmet` |
| Fewer runs than `min_runs` completed | INCONCLUSIVE | `replay_runs_insufficient` |
| A control mapped to the wrong status | INCONCLUSIVE | `control_failed` |
| Verdict reconstructed (for example from a gateway log after a timeout) | INCONCLUSIVE (sealed, evidence_tier `derived`) | `verdict_recovered_not_read` |
| Input exceeds `token_limit` | ERROR | `input_over_context_limit` |
| Input cannot be located / extracted / canonicalized, or its digest differs from the claim | ERROR | `input_unresolvable` / `input_canonicalization_failed` / `input_digest_mismatch` |
| Served model revision or checkpoint differs from the rubric | ERROR | `model_revision_mismatch` / `checkpoint_mismatch` |
| Served rubric or question digest differs | ERROR | `rubric_digest_mismatch` / `question_digest_mismatch` |
| Calibration artifact missing or its digest differs | ERROR | `calibration_unavailable` |
| Gateway or backend unreachable, timed out, or returned a malformed response | ERROR | `backend_unavailable` / `gateway_error` / `gateway_timeout` / `backend_response_invalid` |

The table is for decision models. A validator run maps as section 2a says:
VERIFIED or REFUTED from the program, INCONCLUSIVE only for `control_failed`
or `replay_output_divergence`, ERROR for anything that stops the pinned program
from deciding the input as frozen.

INCONCLUSIVE and ERROR never become PASS. An over-limit input is ERROR (the
rubric could not execute as frozen), and is never silently truncated. A claim
binding the runner cannot parse is a `claim_malformed` rejection with no receipt,
exactly as `verification.md` defines.

## 6. Operations

Allowed (verdict-only): `evaluate`, `check`, `score`; a validator rubric
allows exactly `check`. Denied, so they are
refused as `generative_backend_operation_denied`: `generate`, `propose`,
`propose_claims`, `propose_options`, `suggest_options`, `rewrite`,
`rewrite_claim`, `rewrite_options`, `explain`, `complete`, `chat`, `review`.
`command_configuration.args` is empty: every parameter is pinned by the rubric
digest, so a command line cannot override a threshold, checkpoint, or cache
policy.

## 7. Identity, authority, and amendment

- Backend identity is `jev`, `laya`, or `validator`, never a generic
  `system1` name. A
  receipt's `backend` equals its rubric's backend. No fallback inside an
  assurance receipt: an unavailable backend is ERROR `backend_unavailable`
  (`halt` when required, `proceed-with-note` when only selected).
- Diagnostic versus assurance authority and fresh-session assurance independence
  are unchanged. Implementer, Light Implementer, and Integration Engineer runs are
  diagnostic. Only an independent Test Engineer assurance session, rerunning the
  frozen rubric on the exact stable candidate, produces assurance receipts.
- Only a rubric with `assurance_eligible: true` may back an assurance request:
  `planVerification` requires the rubric object on a `jev`/`laya`/`validator`
  assurance plan, checks its digest against the claim's `rubric_digest`, and
  refuses a non-eligible rubric as `rubric_not_assurance_eligible` before
  anything runs.
  Diagnostic plans may use it.
- Any change to backend, model revision, checkpoint, question, options,
  thresholds, calibration, validator source, rule, controls, input policy,
  replay, or cache policy is a new rubric version and requires a plan amendment before an assurance packet may
  consume it.
- Credentials never appear in a rubric, profile, request, receipt, or output.
  Gateway identifiers, endpoints, and tokens are referenced by env-var name only.

## 8. Place in the gate chain

The seventh-gate slot is renamed from `reverify` to the backend-neutral
`deterministic_verification`, keeping its position:

`build`, `types_lint`, `red_then_green`, `mutation`, `changed_line_coverage`,
`deterministic_verification`, `reviewer`.

Why rename rather than keep the slot name: the slot is a gate class, not a
backend. The profile key is already `deterministic_verification`; a gate named
`reverify` that holds `jev`, `laya`, or `validator` receipts would let a backend name stand
in for a different binding, which `verification.md` forbids. Keeping position
means deterministic evidence is complete before Reviewer consumes the gate-chain
receipt. The slot passes only when every required claim's receipt is
`gate_eligible` under `hooks/verification.cjs`; with no eligible claim it is
declared `NOT_APPLICABLE` with a reason. `hooks/policy.cjs` and the
`assurance-policy.md` block carry the rename together
(`docs/proposals/system1-backend.md`, applied), and `evaluateGateChain`
fails a declaration that still names `reverify` closed at this slot
(`retired_gate_name_declared`).

## 9. What Reviewer may and may not request

Reviewer **may** request a deterministic rerun of an existing frozen rubric,
through the parent controller, to adjudicate one specific suspected defect on
the current candidate, for example "rerun `RUB-S1-CONSENT-EXPLAINS-WITHDRAWAL`
on the `fr` locale". The result is a receipt like any other and is recorded as
evidence for that finding.

Reviewer **may not**: author, edit, or re-threshold a rubric; ask a backend to
review code, explain a verdict, propose options, or generate text; switch a
rubric's backend or checkpoint; treat a System One verdict as its own finding
without the receipt; or trigger automatic rereview after a repair. A needed new
rubric is a finding routed to the Planning Test Engineer through an owner
amendment.
