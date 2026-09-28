"""Write measured calibration into the three Laya rubric files.

    python tools/system1-calibration/update_rubrics.py

Reads results.json and replay.json per rubric. Never edits thresholds or
max_ece. Sets assurance_eligible from the measured bar (held-out calibrated
ECE <= max_ece, every control on its expected status, held-out precision of
gated verdicts >= 0.95, at least one gated verdict).
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1cal  # noqa: E402
from controls import controls  # noqa: E402
from evaluate import PRECISION_BAR, RUBRIC_FILE  # noqa: E402
from formulations import FORMULATIONS, decision_sets  # noqa: E402
from run_formulations import RUNTIME  # noqa: E402

BASELINE = "2f8a83d"  # commit holding the placeholder rubrics
PLACEHOLDER_PREFIXES = ("Placeholder digests", "measured_ece ", "noul on the English checkpoint",
                        "noul label-following risk", "Measured on ", "Temperature semantics", "Not assurance-eligible",
                        "Option C is deliberately")


def worst_logit_delta():
    """Largest per-logit replay delta measured for any Laya rubric on this machine."""
    return max(json.load(open(os.path.join(s1cal.FIXTURES, r, "replay.json"), encoding="utf-8"))["max_logit_delta"]
               for r in RUBRIC_FILE)


def epsilon_from(dp_measured, temperature):
    """10x the larger of (a) this rubric's measured max thresholded-probability delta and (b) the probability
    delta implied by the worst per-logit delta seen on any checkpoint (two options: |dp| <= dlogit / (2T)),
    rounded up to one significant figure, floored at 1e-6, capped at the schema's 0.02."""
    e = max(1e-6, 10 * max(dp_measured, worst_logit_delta() / (2 * temperature)))
    mag = 10 ** math.floor(math.log10(e))
    return min(0.02, round(math.ceil(round(e / mag, 9)) * mag, 12))


def fmt(x):
    return "n/a" if x is None else "%.3f" % x


def update(rubric):
    d = os.path.join(s1cal.FIXTURES, rubric)
    res = json.load(open(os.path.join(d, "results.json"), encoding="utf-8"))
    rep = json.load(open(os.path.join(d, "replay.json"), encoding="utf-8"))
    man = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
    path = os.path.join(s1cal.RUBRICS_DIR, RUBRIC_FILE[rubric])
    # Always derive from the pre-calibration rubric so reruns are idempotent.
    rel = os.path.relpath(path, s1cal.ROOT)
    rb = json.loads(subprocess.run(["git", "show", BASELINE + ":" + rel], cwd=s1cal.ROOT, check=True,
                                   capture_output=True, text=True).stdout)
    name = res["chosen"]["formulation"]
    assert rep["formulation"] == name
    f = FORMULATIONS[rubric][name]
    r = res["formulations"][name]
    tc, tr, ts = r["test_calibrated"], r["test_raw"], r["test_shipped"]

    old_q = rb["question"]
    question = {k: v for k, v in f["question"].items() if k in ("key", "type", "instructions", "criteria")}
    assert question == f["question"], "formulation is not schema-expressible"
    changed_q = question != old_q or f["checkpoint"] != rb["model"]["checkpoint"]
    major, minor, _ = (int(x) for x in rb["rubric_version"].split("."))
    rb["rubric_version"] = "%d.0.0" % (major + 1) if changed_q else "%d.%d.0" % (major, minor + 1)
    rb["question"] = question
    rb["question_digest"] = s1cal.sha256_text(s1cal.bridge_canonical_json(question))
    rb["model"]["checkpoint"] = f["checkpoint"]
    rb["model"]["runtime"]["max_len"], rb["model"]["runtime"]["head_max_len"] = RUNTIME[f["checkpoint"]]
    holds, fails = decision_sets(question)
    rb["decision"]["claim_holds_options"], rb["decision"]["claim_fails_options"] = holds, fails
    # Conservative: the schema ties measured_ece to the calibration set, the brief to held-out data; record the worse.
    ece_measured = round(max(tc["ece"], r["calibration_calibrated"]["ece"]), 4)
    rb["calibration"].update({
        "temperature": round(r["temperature"], 6),
        "calibration_set_digest": man["calibration"]["sha256"],
        "calibration_set_size": man["calibration"]["size"],
        "measured_ece": ece_measured,
    })
    ctl = {c["control_id"]: c for c in controls(rubric)}
    for c in rb["controls"]:
        m = ctl[c["control_id"]]
        assert m["locator"] == c["locator"] and m["expected"] == c["expected"]
        c["input_digest"] = m["input_digest"]
    eps = epsilon_from(rep["max_probability_delta"], r["temperature"])
    rb["replay"]["probability_epsilon"] = eps

    reasons = list(res["chosen"]["reasons"])
    eligible = not reasons
    rb["assurance_eligible"] = eligible
    ctl_obs = "; ".join("%s %s->%s (p=%.3f)" % (cid, v["expected"], v["observed"][0], v["thresholded_probability"])
                        for cid, v in r["controls"].items())
    kept = [n for n in rb.get("notes", []) if not n.startswith(PLACEHOLDER_PREFIXES)]
    if "C" not in question.get("criteria", {}):
        kept = [n for n in kept if "Option C" not in n]
        if rubric == "multilingual-consent-banner":
            kept.append("Two-option form: there is no 'not a banner' option, so text that is not a consent banner "
                        "(it states none of the disclosures) maps to B and can REFUTE; the extractor and locator, not "
                        "the model, are what establish that the input is the banner.")
    tried = ", ".join("%s %.3f" % (n, x["test_calibrated"]["accuracy"]) for n, x in res["formulations"].items())
    notes = [
        "Measured on the pinned checkpoint, CPU fp32, eval mode, one state per forward pass: formulation `%s`, "
        "held-out accuracy %.3f (n=%d); ECE (15 bins) %.3f raw logits, %.3f at the checkpoint's shipped temperature, "
        "%.3f at the fitted temperature %.4g; at verify %.2f / refute %.2f, coverage %.3f (VERIFIED %d, REFUTED %d, "
        "INCONCLUSIVE %d) with precision %s. Calibration split ECE after fitting %.3f (n=%d). Dataset: "
        "test/fixtures/system1-calibration/%s/ (report: docs/calibration/system1-calibration-report.md)." % (
            name, tc["accuracy"], tc["n"], tr["ece"], ts["ece"], tc["ece"], r["temperature"],
            res["verify_threshold"], res["refute_threshold"], tc["coverage"], tc["verified"], tc["refuted"],
            tc["inconclusive"], fmt(tc["precision"]), r["calibration_calibrated"]["ece"],
            r["calibration_calibrated"]["n"], rubric),
        "Formulations tried (held-out accuracy at fitted T): %s. Controls at the fitted T: %s. Replay: %d runs per "
        "control (%d in fresh processes), max thresholded-probability delta %.3g, max logit delta %.3g; epsilon is "
        "10x the larger of the measured delta and the delta implied by the worst logit wobble seen on any checkpoint "
        "(2.99e-4, laya-multilingual under concurrent CPU load), rounded up." % (
            tried, ctl_obs, max(v["runs"] for v in rep["controls"].values()),
            max(v["fresh_process_runs"] for v in rep["controls"].values()), rep["max_probability_delta"],
            rep["max_logit_delta"]),
        "Temperature semantics: `calibration.temperature` replaces the checkpoint's own temperature for this "
        "question's (type, option count) bucket, i.e. probabilities are softmax(option logits / T); a runner sets "
        "agent.temperature_by_options[temp_bucket] = T and passes no `lang`, so lang_temperatures cannot override it. "
        "`measured_ece` is the larger of the calibration-split (in-sample) and held-out test-split ECE at the fitted "
        "temperature.",
    ]
    if r["temperature"] > 19.99:
        notes.append("The fitted temperature sits at the schema's upper bound (20): NLL keeps falling as T grows, i.e. "
                     "the logits carry no usable signal for this rule and the best calibration is a flat 0.5.")
    gated = tc["verified"] + tc["refuted"]
    if gated:
        k, z = tc["verified_correct"] + tc["refuted_correct"], 1.96
        ph = k / gated
        lo = (ph + z * z / (2 * gated) - z * math.sqrt(ph * (1 - ph) / gated + z * z / (4 * gated * gated))) / (1 + z * z / gated)
        reasons.append("held-out precision rests on only %d gated verdicts (%d correct; Wilson 95%% lower bound %.2f)"
                       % (gated, k, lo)) if lo < PRECISION_BAR else None
    if not eligible:
        notes.append("Not assurance-eligible: " + "; ".join(reasons) + ". Thresholds were not lowered to compensate; "
                     "this rubric may back diagnostic runs only until a re-authored version measures inside the bar.")
    rb["notes"] = notes + kept
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(rb, indent=2, ensure_ascii=False) + "\n")
    print(rubric, rb["rubric_version"], name, "eligible" if eligible else "NOT eligible", reasons)


if __name__ == "__main__":
    for rubric in (sys.argv[1:] or list(RUBRIC_FILE)):
        update(rubric)
