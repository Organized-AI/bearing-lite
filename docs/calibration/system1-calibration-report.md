# System One Laya rubric calibration report

Date: 2026-09-27. Branch `system1-backend`, baseline commit `2f8a83d`.
Rubrics: `skills/bearing-lite/references/system1-rubrics/`.
Data, predictions and results: `test/fixtures/system1-calibration/<rubric>/`.
Scripts: `tools/system1-calibration/`.

## Summary

None of the three Laya rubrics meets its bar. All three are now
`assurance_eligible: false`, and every one of their known-answer controls maps
to INCONCLUSIVE. The thresholds were not lowered.

On these multi-condition conformance rules the pinned checkpoints score at or
near chance. Temperature scaling works as intended: it pushes the probabilities
toward 0.5, so the 0.85 and 0.90 thresholds almost never fire and the rubrics
return INCONCLUSIVE instead of wrong verdicts. Without calibration, the same
thresholds would issue verdicts on 20 to 95 percent of held-out items at 38 to
74 percent precision. The calibration is doing its job. The model does not
have the capability these rules need.

| Rubric | Formulation | Held-out acc | ECE raw / shipped / fitted | T | Coverage | Precision | Controls | epsilon | assurance_eligible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RUB-S1-GTM-DATALAYER-PURCHASE 2.0.0 | `noul_tight` | 0.533 | 0.383 / 0.298 / 0.039 | 20 | 0.000 | n/a | 0/3 pass | 8e-05 | false |
| RUB-S1-CONSENT-BANNER-DISCLOSURES 2.0.0 | `choice2_neutral` | 0.514 | 0.167 / 0.167 / 0.005 | 20 | 0.000 | n/a | 0/3 pass | 8e-05 | false |
| RUB-S1-WRANGLER-REQUIRED-BINDINGS 2.0.0 | `noul_tight` | 0.606 | 0.347 / 0.232 / 0.089 | 5.342 | 0.017 | 1.000 (3/3) | 0/3 pass | 0.0003 | false |
| RUB-S1-ABIDE-NO-SECRETS-IN-WRANGLER 1.0.1 (Jev) | unchanged | not measured | not measured | not fitted | n/a | n/a | no fixtures | 0.01 (unchanged) | false |

Notes on the table:

- "Held-out" means the test split (n = 180, 181 for consent).
- ECE is `laya.ece_score` with 15 bins, computed on top-1 confidence against
  correctness. It is reported at three temperatures:
  - "raw" is T = 1 on the option logits;
  - "shipped" is the checkpoint's own temperature, which is what `laya.predict`
    returns by default;
  - "fitted" is the temperature fitted on the calibration split.
- Coverage and precision are measured at the fitted T and the rubric's own
  thresholds.
- The rubric's `measured_ece` records the worse of the calibration-split and
  held-out figures (GTM 0.096, consent 0.079, wrangler 0.089). All three are
  under their `max_ece`. ECE is therefore not what fails.
- Wilson 95% intervals on held-out accuracy:
  - GTM: 0.461 to 0.605.
  - Wrangler: 0.533 to 0.674. The majority-class rate is 0.506.
  - Consent: 0.441 to 0.586. The majority-class rate for the two-option form
    is 0.564, so consent is below that baseline.
- Wrangler's 3/3 gated precision has a Wilson lower bound of 0.44. It is not
  evidence of 0.95 precision.

Why each rubric fails its bar:

- **GTM:** all 3 controls are INCONCLUSIVE, and held-out coverage is 0.
- **Consent:** all 3 controls are INCONCLUSIVE, and held-out coverage is 0.
- **Wrangler:** all 3 controls are INCONCLUSIVE. Held-out coverage is 3/180,
  all correct REFUTEDs, a sample far too small to establish precision.

## Formulations tried

The formulation list in `tools/system1-calibration/formulations.py` was fixed
before any held-out number was seen. The selection rule in `evaluate.py` was
also fixed in advance:

1. Only schema-expressible formulations are eligible.
2. Prefer a formulation whose controls all pass.
3. Then prefer the higher held-out accuracy.
4. Then prefer the lower fitted ECE.

No formulation passed its controls, so the choice fell to held-out accuracy.
Every difference in that column is within noise.

The formulations are:

- `noul_verbatim`: the original question.
- `noul_tight`: noul with a numbered condition checklist.
- `noul_neutral_labels`: noul with `labels: {false: "B", true: "A"}`, against
  laya issue #156. The rubric schema cannot express it. A rubric `question`
  admits only key, type, instructions and criteria, and a noul question may
  not carry criteria. It was measured as a diagnostic and could not be chosen.
- `choice2_neutral` and `choice2_tight`: two options with neutral A/B keys and
  the verdict in the descriptions.
- `typed_choice2_neutral`: `choice2_neutral` on `laya-typed-decisions`, which
  is in the schema's checkpoint enum.
- Consent only:
  - `choice3_verbatim`: the original question.
  - `choice3_tight`: the three disclosures spelled out.
  - `noul_tight`.

#### gtm-datalayer-event (verify 0.90, refute 0.90, max_ece 0.10)

| Formulation | Checkpoint | Schema | T | Cal acc | Held-out acc | ECE raw | ECE shipped | ECE fitted | Coverage | Precision | V / R / I | Controls (observed at fitted T) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `noul_verbatim` | laya | yes | 20 | 0.428 | 0.500 | 0.395 | 0.273 | 0.039 | 0.000 | n/a | 0 / 0 / 180 | all 3 INCONCLUSIVE |
| `noul_tight` (chosen) | laya | yes | 20 | 0.467 | 0.533 | 0.383 | 0.298 | 0.039 | 0.000 | n/a | 0 / 0 / 180 | all 3 INCONCLUSIVE |
| `noul_neutral_labels` | laya | no (diagnostic) | 20 | 0.467 | 0.489 | 0.363 | 0.257 | 0.064 | 0.000 | n/a | 0 / 0 / 180 | all 3 INCONCLUSIVE |
| `choice2_neutral` | laya | yes | 20 | 0.467 | 0.472 | 0.463 | 0.372 | 0.073 | 0.000 | n/a | 0 / 0 / 180 | all 3 INCONCLUSIVE |
| `choice2_tight` | laya | yes | 20 | 0.511 | 0.500 | 0.396 | 0.277 | 0.044 | 0.000 | n/a | 0 / 0 / 180 | all 3 INCONCLUSIVE |
| `typed_choice2_neutral` | laya-typed-decisions | yes | 20 | 0.450 | 0.406 | 0.312 | 0.222 | 0.107 | 0.000 | n/a | 0 / 0 / 180 | all 3 INCONCLUSIVE |

Held-out accuracy of `noul_tight` by near-miss type:

| Near-miss type | Accuracy | Near-miss type | Accuracy |
| --- | --- | --- | --- |
| missing_transaction_id | 1.00 | empty_items | 0.89 |
| wrong_event | 0.80 | items_without_id_or_name | 0.77 |
| ecommerce_missing | 0.71 | items_not_array | 0.64 |
| bad_currency | 0.59 | empty_transaction_id | 0.50 |
| missing_value | 0.29 | missing_currency | 0.00 |
| valid | 0.38 | | |

Missing-currency pushes, the exact case of the original smoke test, are never
caught. Valid pushes are rejected more often than accepted.

Label-following shows up in the prediction counts:

- `noul_verbatim` answers yes on 139 of 180 items.
- `noul_neutral_labels` answers yes on 165 of 180 items.
- Both choice forms answer A on 173 or more of 180 items.

#### multilingual-consent-banner (verify 0.85, refute 0.85, max_ece 0.12)

| Formulation | Checkpoint | Schema | T | Cal acc | Held-out acc | ECE raw | ECE shipped | ECE fitted | Coverage | Precision | V / R / I | Controls (observed at fitted T) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `choice3_verbatim` | laya-multilingual | yes | 20 | 0.313 | 0.381 | 0.077 | 0.077 | 0.042 | 0.000 | n/a | 0 / 0 / 181 | all 3 INCONCLUSIVE |
| `choice3_tight` | laya-multilingual | yes | 1.08 | 0.480 | 0.508 | 0.096 | 0.096 | 0.109 | 0.000 | n/a | 0 / 0 / 181 | all 3 INCONCLUSIVE |
| `choice2_neutral` (chosen) | laya-multilingual | yes | 20 | 0.430 | 0.514 | 0.167 | 0.167 | 0.005 | 0.000 | n/a | 0 / 0 / 181 | all 3 INCONCLUSIVE |
| `noul_tight` | laya-multilingual | yes | 20 | 0.441 | 0.442 | 0.521 | 0.521 | 0.107 | 0.000 | n/a | 0 / 0 / 181 | all 3 INCONCLUSIVE |

The shipped temperature of `laya-multilingual` is 1.0, so the raw and shipped
columns are identical.

Held-out accuracy of `choice2_neutral`:

| By variant | Accuracy | By language | Accuracy |
| --- | --- | --- | --- |
| complete | 0.27 | de | 0.60 |
| missing one | 0.70 | en | 0.53 |
| missing two | 0.78 | es | 0.48 |
| none | 1.00 | fr | 0.32 |
| not a banner | 0.47 | it | 0.50 |
| | | ja | 0.67 |
| | | nl | 0.52 |
| | | pt | 0.48 |

The noul form answers yes on 180 of 181 items. At the shipped temperature it
would issue verdicts on 95% of items at 45% precision.

The chosen two-option form has no "not a banner" option, so non-banner text
now maps to B and can REFUTE. The rubric notes say this.

`laya-typed-decisions` was not tried for consent because it is an English
ModernBERT fine-tune and the rubric's input is multilingual.

#### wrangler-bindings (verify 0.90, refute 0.90, max_ece 0.10)

| Formulation | Checkpoint | Schema | T | Cal acc | Held-out acc | ECE raw | ECE shipped | ECE fitted | Coverage | Precision | V / R / I | Controls (observed at fitted T) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `noul_verbatim` | laya | yes | 12.7 | 0.517 | 0.517 | 0.441 | 0.350 | 0.090 | 0.000 | n/a | 0 / 0 / 180 | all 3 INCONCLUSIVE |
| `noul_tight` (chosen) | laya | yes | 5.34 | 0.606 | 0.606 | 0.347 | 0.232 | 0.089 | 0.017 | 1.000 | 0 / 3 / 177 | all 3 INCONCLUSIVE |
| `noul_neutral_labels` | laya | no (diagnostic) | 10.5 | 0.511 | 0.511 | 0.426 | 0.316 | 0.066 | 0.000 | n/a | 0 / 0 / 180 | all 3 INCONCLUSIVE |
| `choice2_neutral` | laya | yes | 20 | 0.511 | 0.506 | 0.452 | 0.354 | 0.040 | 0.000 | n/a | 0 / 0 / 180 | all 3 INCONCLUSIVE |
| `choice2_tight` | laya | yes | 18.8 | 0.511 | 0.506 | 0.435 | 0.322 | 0.036 | 0.000 | n/a | 0 / 0 / 180 | all 3 INCONCLUSIVE |
| `typed_choice2_neutral` | laya-typed-decisions | yes | 20 | 0.494 | 0.522 | 0.247 | 0.152 | 0.008 | 0.000 | n/a | 0 / 0 / 180 | all 3 INCONCLUSIVE |

Held-out accuracy of `noul_tight` by near-miss type:

| Near-miss type | Accuracy | Near-miss type | Accuracy |
| --- | --- | --- | --- |
| valid | 0.86 | missing_array | 0.75 |
| wrong_array | 0.75 | missing_id_key | 0.42 |
| empty_id | 0.31 | renamed_binding | 0.13 |
| lowercase_binding | 0.00 | | |

The misnamed bindings, which are the case this rubric exists for, are almost
never caught. Both choice forms answer A on every item.

### Uncalibrated gating would be unsafe

Coverage and precision at the rubric thresholds, measured without the fitted
temperature on the held-out split:

| Rubric | Formulation | Raw T=1: coverage | Raw T=1: precision | Shipped T: coverage | Shipped T: precision |
| --- | --- | --- | --- | --- | --- |
| GTM | `noul_verbatim` | 0.589 | 0.509 | 0.150 | 0.556 |
| GTM | `noul_tight` | 0.678 | 0.541 | 0.478 | 0.523 |
| GTM | `choice2_neutral` | 0.833 | 0.467 | 0.378 | 0.382 |
| Wrangler | `noul_verbatim` | 0.867 | 0.571 | 0.483 | 0.621 |
| Wrangler | `noul_tight` | 0.756 | 0.625 | 0.211 | 0.737 |
| Consent | `noul_tight` | 0.950 | 0.453 | 0.950 | 0.453 |

Two things follow from this table:

- The per-rubric fitted temperature is load-bearing. Without it the thresholds
  would issue a verdict on a large share of the inputs, and a large share of
  those verdicts would be wrong.
- The controls catch the failure regardless of temperature. At the fitted T
  they all land on INCONCLUSIVE, so any claim run under these rubrics seals
  INCONCLUSIVE `control_failed`.

### The harness works on easy questions

`tools/system1-calibration/sanity_probe.py` is a diagnostic, not a rubric. It
runs the same capture path on easy single-attribute questions:

- "Which kind of event is this push?" over purchase, add_to_cart and
  page_view: p = 0.999, 0.998 and 1.000 on the correct option.
- "Is the customer asking for a refund?": p(yes) = 0.883 on a refund request
  and 0.000 on an opening-hours question.
- The `event` field of the dataset's own pushes: 0.686 (n = 35).

So the chance-level results come from the multi-condition rule. The harness
is reading the model correctly.

## Methods

### Datasets

`generate.py` builds the datasets with fixed seeds (GTM 4217, consent 1156,
wrangler 8785). Each rubric has 360 items. `labelers.py` labels every item
deterministically; no model is involved. Each labeler implements its rubric's
rule text literally:

- **GTM:** exact `event == "purchase"`, then a present and non-empty
  transaction_id, value and currency. The currency must be an exact uppercase
  code in the ISO 4217 list, and the items must be an array containing an
  object with item_id or item_name.
- **Consent:** each banner is assembled from typed segments (purpose,
  third_parties, withdrawal, filler, other), and the label comes from the
  segment kinds. A per-language cue-word check asserts that no filler segment
  leaks a disclosure.
- **Wrangler:** exact case-sensitive binding names, with a non-empty string id.

The generator's own intent tag (`variant`) is cross-checked against the
labeler. It is never used as the label.

What each dataset contains:

- **GTM:** about half the items are valid purchases. Valid items vary the
  number of items, whether an item has an id, a name or both, the optional
  ecommerce fields, and noise top-level keys such as `gtm.uniqueEventId`,
  `user_id` and `debug_mode`. The near-misses are:
  - a wrong or case-changed event name;
  - a missing or empty transaction_id;
  - a missing value;
  - a missing currency;
  - a bad currency: `usd`, `US$`, `€`, `EURO`, `ABC`, a numeric 840, and
    similar;
  - an empty items array;
  - items that are an object or a string;
  - items with no item_id or item_name;
  - the ecommerce fields flattened to the top level.
- **Consent:** 8 languages (en, de, fr, es, it, pt, nl, ja), with 3
  paraphrases per disclosure per language. The item mix is:
  - banners that are complete (label A);
  - banners missing one, two or all three disclosures (label B);
  - non-banner shop text (label C, 8%);
  - an optional "see our privacy policy" line, as a near-miss that discloses
    nothing.

  Every item stores its segments and a `truth.disclosures` object with a
  boolean for purpose, third_parties and withdrawal.
- **Wrangler:** the source configs are JSONC (with comments and trailing
  commas) or TOML. Their `d1_databases`, `kv_namespaces` and `r2_buckets`
  sections are extracted and canonicalized to RFC 8785. The near-misses are:
  - a missing array;
  - a renamed binding (KV, CACHE_KV, DATABASE, BUCKET, and similar);
  - a lowercase or capitalized binding;
  - an empty id;
  - a missing id key;
  - the required binding placed in the wrong array.

  Extra non-required bindings appear on both positive and negative items. The
  rubric pins `jsonc_to_rfc8785_jcs`. TOML sources are included for input
  diversity, and after extraction the model sees the same JCS form either way.

Every item carries:

- the exact `state` string sent to the model;
- `input_digest`, the SHA-256 of that state;
- `state_tokens`, counted with the pinned tokenizer.

No item exceeded its `token_limit`: the largest are 157, 109 and 233 tokens
against limits of 320, 768 and 320.

The split is stratified by label, 50/50, with seed 20260927
(`s1cal.stratified_split`). Each split is written as canonical JSONL, one RFC
8785 object per line with LF endings. `calibration_set_digest` is the SHA-256
of `calibration.jsonl`; neither the schema nor the rubric doc defines it more
precisely. `manifest.json` records both digests and the label counts:

| Rubric | Calibration items | Test items |
| --- | --- | --- |
| GTM | 180 (85 holds / 95 fails) | 180 |
| Consent | 179 (79 A / 86 B / 14 C) | 181 |
| Wrangler | 180 (92 holds / 88 fails) | 180 |

The whole `test/fixtures/system1-calibration/` tree is 1.4 MB.

### Model execution

The runs used:

- `laya` 0.3.21 on CPU fp32, eval mode, fast path off;
- the pinned revision `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`, loaded as
  the root checkpoint or the `multilingual` or `typed-decisions` subfolder;
- the rubric's `max_len` and `head_max_len`: 512/192 for the English
  checkpoints, and 1024/256 for `laya-multilingual`;
- one state per forward pass.

Batching changed logits by up to 1.1e-5 because of padding, so it was not used.

For JSON rubrics the state sent is the canonical JCS text itself.
`serialize_state` passes strings through verbatim, so the bytes sent are the
bytes digested.

Raw option logits are captured at full precision by wrapping
`Agent._decode_answers`. The noul option order is [false, true]. They are
stored to 6 decimals in `predictions.jsonl`, and every metric is recomputed
from that file.

`run_formulations.py` asserts that no instruction text is cut by
`head_max_len`.

### Temperature

The rubric temperature T replaces the checkpoint's temperature for the
question's (type, option count) bucket, so p = softmax(logits / T). A runner
applies it as follows:

- set `agent.temperature_by_options[temp_bucket(qtype, k)] = T`;
- pass no `lang`, so `lang_temperatures` cannot override it.

The shipped temperatures are:

| Checkpoint | Bucket | Shipped T |
| --- | --- | --- |
| `laya` and `laya-typed-decisions` | noul:2 | 1.9834 |
| `laya` and `laya-typed-decisions` | choice:2 | 1.9064 |
| `laya-multilingual` | all | 1.0 |

T is fitted on the calibration split only, by minimizing NLL:

1. Search a 400-point log grid on [0.05, 20], where 20 is the schema maximum.
2. Refine with golden-section search.

T lands on the bound of 20 in most cases. There the NLL is still falling:
the logits carry no usable signal, and the best calibration is a flat 0.5.

### Status mapping and gated metrics

`s1cal.map_status` applies the rules of `system1-rubrics.md` §3 and §5:

- The hard answer is the argmax.
- The thresholded mass is the calibrated probability of the answer's option
  set.
- A result is VERIFIED or REFUTED only when it is at or above the rubric's
  threshold. Anything else, and any exact tie, is INCONCLUSIVE.

Coverage is (VERIFIED + REFUTED) / n. Precision is the fraction of those
verdicts that agree with the labeler. A consent C item is never a correct
verdict.

### Controls

`controls.py` writes each control file at its rubric `locator`. The file
content is the canonical state bytes with no trailing newline:

- RFC 8785 JCS for the GTM and wrangler controls. A JCS document is also valid
  JSONC, and re-extracting and re-canonicalizing it is the identity.
- `utf8_nfc_lf_trim_trailing` for consent, meaning NFC, LF line endings,
  trailing whitespace trimmed per line and at the end.

`input_digest` is the SHA-256 of the file bytes, which equals the SHA-256 of
the canonical state. The expected status is certified by the labeler. A check
confirms that no control duplicates a dataset item.

For the GTM rubric the input extractor is `json_pointer:/0`, so a control file
holds the push after extraction.

Controls at the fitted T of the chosen formulation (p is the thresholded
mass):

| Control | Expected | Observed |
| --- | --- | --- |
| CTL-GTM-PURCHASE-VALID | VERIFIED | INCONCLUSIVE, p = 0.533 |
| CTL-GTM-PURCHASE-NO-CURRENCY | REFUTED | INCONCLUSIVE, p = 0.578 |
| CTL-GTM-ADD-TO-CART | REFUTED | INCONCLUSIVE, p = 0.571 |
| CTL-CONSENT-DE-COMPLETE | VERIFIED | INCONCLUSIVE |
| CTL-CONSENT-ES-NO-WITHDRAW | REFUTED | INCONCLUSIVE |
| CTL-CONSENT-JA-NO-THIRD-PARTY | REFUTED | INCONCLUSIVE |
| CTL-WRANGLER-ALL-BOUND | VERIFIED | INCONCLUSIVE |
| CTL-WRANGLER-NO-R2 | REFUTED | INCONCLUSIVE |
| CTL-WRANGLER-WRONG-KV-NAME | REFUTED | INCONCLUSIVE |

The per-formulation observations are in each `results.json`. No formulation
put any control on its expected status.

### Replay and epsilon

`replay.py` replays each control of the chosen formulation 9 times:

- 3 runs in the process that scored the dataset;
- 6 runs in freshly started Python processes, spread over two sessions (2
  fresh processes, then 4).

Results:

- **GTM and wrangler:** every run is bit-identical. The max probability delta
  and the max logit delta are both 0.
- **Consent:** in session 1, the second fresh process ran while `generate.py`
  was also using the machine's 2 CPUs. It moved one control's logits by
  2.99e-4, which is a 4.2e-6 probability delta at T = 20. The quiet session 2
  was bit-identical. `replay.json` keeps both sessions. Session 1 is
  reconstructed from its log, because its per-run logits were not retained.

The hard answer and the status were identical on every run.

`probability_epsilon` is 10 times the larger of two deltas, rounded up to one
significant figure:

- the rubric's own measured probability delta;
- the delta that the worst logit wobble seen on any checkpoint (2.99e-4) would
  cause through that rubric's T. For two options, |dp| <= dlogit / (2T).

The resulting values are all inside the schema bound of at most 0.02:

| Rubric | epsilon |
| --- | --- |
| GTM | 8e-5 |
| Consent | 8e-5 |
| Wrangler | 3e-4 |

These are wider than the 1e-6 the rubric doc suggests, because CPU contention
does move fp32 logits on this stack.

## What didn't work, and limitations

- **No formulation fixes the model.** The neutral keys, neutral noul labels,
  checklist wording and the typed-decisions checkpoint all score within noise
  of chance. The formulation change on each rubric (hence 2.0.0) follows the
  pre-registered rule. None of them is demonstrably better than the verbatim
  question.
- **Neutral noul labels cannot be expressed in the schema.** `labels` is not a
  rubric `question` field. They would also not have helped: 0.489 on GTM and
  0.511 on wrangler.
- **The datasets are synthetic.** They are generator-built rather than
  captured production traffic. The consent paraphrases were written for this
  exercise and are not reviewed native copy. The ground truth is exact with
  respect to the rubric rule text, but the realism of the input distribution
  is limited.
- **Selecting on held-out accuracy spends the test split.** The candidate list
  was fixed beforehand and nothing was iterated, but the chosen formulation's
  held-out figure is still mildly optimistic.
- **The round-trip fixture is synthetic.**
  `test/fixtures/system1-laya-round-trip.json` still carries a synthetic
  VERIFIED run at p = 0.9731. It is now a diagnostic run: `planVerification`
  refuses an assurance plan on a rubric that is not `assurance_eligible`
  (`rubric_not_assurance_eligible`), so the assurance-gate tests use an in-test
  synthetic copy of the GTM rubric with the flag flipped and a recomputed
  digest.
- **Jev is unmeasured.** No TypeSafe Jev credentials were available. The Jev
  rubric keeps its placeholder calibration and has no control fixtures. It is
  now marked `UNMEASURED` and `assurance_eligible: false` at version 1.0.1.

## Reproduce

```sh
# Python 3.12 venv with laya==0.3.21 and CPU torch; HF weights for the pinned revision cached
export HF_HUB_OFFLINE=1
python tools/system1-calibration/generate.py            # datasets + manifest (tokenizers only)
python tools/system1-calibration/controls.py            # control fixtures at the rubric locators
python tools/system1-calibration/run_formulations.py gtm        # ~35 min on 2 CPUs
python tools/system1-calibration/run_formulations.py wrangler   # ~40 min
python tools/system1-calibration/run_formulations.py consent    # ~6 min
python tools/system1-calibration/evaluate.py            # fit T, metrics, controls -> results.json (no model)
python tools/system1-calibration/replay.py gtm --fresh-runs 4   # likewise wrangler, consent
python tools/system1-calibration/update_rubrics.py      # rewrites the 3 Laya rubrics from the baseline 2f8a83d
python tools/system1-calibration/report_tables.py       # tables above
node tools/system1-calibration/build-round-trip.mjs     # rebinds the round-trip fixture to the GTM rubric
python tools/system1-calibration/sanity_probe.py        # optional harness check
node --test test/*.test.mjs && python3.12 test/schema-validation.py
```

`generate.py` is deterministic: rerunning it reproduces both JSONL splits
byte-for-byte. `evaluate.py`, `update_rubrics.py` and `report_tables.py` need
only the committed fixtures.
