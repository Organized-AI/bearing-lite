"""Fit temperatures, score formulations, check controls, choose a formulation.

    python tools/system1-calibration/evaluate.py      # all rubrics with predictions

Reads predictions.jsonl and controls-inprocess.json (from run_formulations.py)
and writes results.json per rubric. No model is loaded: everything here is
reproducible from the committed fixtures.

Per formulation:
  * T is fitted on the calibration split only (NLL, log grid + golden section).
  * Accuracy, ECE (laya.ece_score, 15 bins, top-1 confidence vs correctness),
    NLL, and threshold-gated coverage/precision are reported on the held-out
    test split, at T=1 (raw logits), at the checkpoint's shipped temperature
    (what laya.predict returns by default), and at the fitted T.
  * Each control is mapped through the rubric thresholds at the fitted T on
    each of its 3 in-process runs.
Selection (pre-registered): among schema-expressible formulations, prefer ones
whose controls all land on their expected status, then higher held-out
accuracy, then lower held-out calibrated ECE. Thresholds are the rubric's,
unchanged.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1cal  # noqa: E402
from controls import controls  # noqa: E402
from formulations import FORMULATIONS, decision_sets, truth_key  # noqa: E402

RUBRIC_FILE = {"gtm-datalayer-event": "laya-gtm-datalayer-event.rubric.json",
               "multilingual-consent-banner": "laya-multilingual-consent-banner.rubric.json",
               "wrangler-bindings": "laya-wrangler-bindings.rubric.json"}
PRECISION_BAR = 0.95


def shipped_temperature(checkpoint, qtype, k):
    """The checkpoint's own temperature for this (type, option count), as laya applies it (clamped to [0.5, 5])."""
    from huggingface_hub import snapshot_download
    from laya.common import QTYPES, temp_bucket
    sub = s1cal.SUBFOLDER[checkpoint]
    d = snapshot_download(s1cal.REPO, revision=s1cal.REVISION,
                          allow_patterns=[((sub + "/") if sub else "") + "rl_agent_config.json"])
    cfg = json.load(open(os.path.join(d, sub or "", "rl_agent_config.json"), encoding="utf-8"))
    qt = QTYPES[qtype]
    t = cfg.get("temperature_by_options", {}).get(temp_bucket(qt, k), cfg["temperature"][qt])
    return float(min(5.0, max(0.5, t)))


def rubric_thresholds(rubric):
    r = json.load(open(os.path.join(s1cal.RUBRICS_DIR, RUBRIC_FILE[rubric]), encoding="utf-8"))
    return r["decision"]["verify_threshold"], r["decision"]["refute_threshold"], r["calibration"]["max_ece"]


def evaluate_rubric(rubric):
    d = os.path.join(s1cal.FIXTURES, rubric)
    cal = s1cal.read_jsonl(os.path.join(d, "calibration.jsonl"))
    test = s1cal.read_jsonl(os.path.join(d, "test.jsonl"))
    preds = {r["id"]: r for r in s1cal.read_jsonl(os.path.join(d, "predictions.jsonl"))}
    ctl_runs = json.load(open(os.path.join(d, "controls-inprocess.json"), encoding="utf-8"))
    vt, rt, max_ece = rubric_thresholds(rubric)
    ctl_meta = {c["control_id"]: c for c in controls(rubric)}
    out = {"rubric": rubric, "verify_threshold": vt, "refute_threshold": rt, "max_ece": max_ece,
           "calibration_size": len(cal), "test_size": len(test), "formulations": {}}
    for name, f in FORMULATIONS[rubric].items():
        if not all(name in preds.get(r["id"], {}) for r in cal + test) or name not in ctl_runs:
            continue
        q = f["question"]
        keys = s1cal.option_keys(q)
        holds, fails = decision_sets(q)
        lc = np.array([preds[r["id"]][name] for r in cal])
        lt = np.array([preds[r["id"]][name] for r in test])
        yc = [truth_key(rubric, q, r["label"]) for r in cal]
        yt = [truth_key(rubric, q, r["label"]) for r in test]
        t_fit = s1cal.fit_temperature(lc, np.array([keys.index(y) for y in yc]))
        t_ship = shipped_temperature(f["checkpoint"], q["type"], len(keys))
        res = {"checkpoint": f["checkpoint"], "schema_ok": f["schema_ok"], "question_type": q["type"],
               "temperature": t_fit, "shipped_temperature": t_ship,
               "test_raw": s1cal.evaluate(lt, yt, keys, holds, fails, vt, rt, 1.0),
               "test_shipped": s1cal.evaluate(lt, yt, keys, holds, fails, vt, rt, t_ship),
               "test_calibrated": s1cal.evaluate(lt, yt, keys, holds, fails, vt, rt, t_fit),
               "calibration_calibrated": s1cal.evaluate(lc, yc, keys, holds, fails, vt, rt, t_fit),
               "controls": {}}
        by_lang = {}
        if rubric == "multilingual-consent-banner":
            for lang in sorted({r["lang"] for r in test}):
                idx = [i for i, r in enumerate(test) if r["lang"] == lang]
                by_lang[lang] = s1cal.evaluate(lt[idx], [yt[i] for i in idx], keys, holds, fails, vt, rt, t_fit)["accuracy"]
            res["test_accuracy_by_lang"] = by_lang
        variants = sorted({r["variant"] for r in test})
        res["test_accuracy_by_variant"] = {}
        for v in variants:
            idx = [i for i, r in enumerate(test) if r["variant"] == v]
            p = s1cal.softmax(lt[idx], t_fit)
            res["test_accuracy_by_variant"][v] = float(np.mean([keys[int(j)] == yt[i] for j, i in zip(p.argmax(1), idx)]))
        all_ok = True
        for cid, runs in ctl_runs[name].items():
            mapped = [s1cal.map_status(s1cal.softmax(np.array(lg), t_fit), keys, holds, fails, vt, rt) for lg in runs]
            exp = ctl_meta[cid]["expected"]
            ok = all(m[0] == exp for m in mapped)
            all_ok &= ok
            res["controls"][cid] = {"expected": exp, "observed": [m[0] for m in mapped], "answer": mapped[0][1],
                                   "thresholded_probability": round(mapped[0][2], 6), "pass": ok}
        res["controls_pass"] = all_ok
        out["formulations"][name] = res
    eligible = [(n, r) for n, r in out["formulations"].items() if r["schema_ok"]]
    eligible.sort(key=lambda nr: (not nr[1]["controls_pass"], -nr[1]["test_calibrated"]["accuracy"],
                                  nr[1]["test_calibrated"]["ece"]))
    if eligible:
        name, r = eligible[0]
        tc = r["test_calibrated"]
        reasons = []
        if tc["ece"] > max_ece:
            reasons.append("held-out calibrated ECE %.3f exceeds max_ece %.2f" % (tc["ece"], max_ece))
        if not r["controls_pass"]:
            bad = [c for c, v in r["controls"].items() if not v["pass"]]
            reasons.append("controls land on the wrong status: " + ", ".join(bad))
        if tc["precision"] is None:
            reasons.append("no held-out item clears either threshold (coverage 0)")
        elif tc["precision"] < PRECISION_BAR:
            reasons.append("held-out precision of gated verdicts %.3f is below %.2f" % (tc["precision"], PRECISION_BAR))
        out["chosen"] = {"formulation": name, "assurance_eligible": not reasons, "reasons": reasons}
    with open(os.path.join(d, "results.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def summary(out):
    print("==", out["rubric"], "thresholds", out["verify_threshold"], out["refute_threshold"], "max_ece", out["max_ece"])
    for n, r in out["formulations"].items():
        a, s, c = r["test_raw"], r["test_shipped"], r["test_calibrated"]
        print("  %-22s ok=%d T=%.3f acc=%.3f ece raw/ship/cal=%.3f/%.3f/%.3f cov=%.3f prec=%s ctl=%s preds=%s" % (
            n, r["schema_ok"], r["temperature"], c["accuracy"], a["ece"], s["ece"], c["ece"], c["coverage"],
            "n/a" if c["precision"] is None else "%.3f" % c["precision"],
            "/".join("%s:%s" % (k.split("-")[-1], "+".join(sorted(set(v["observed"])))) for k, v in r["controls"].items()),
            c["pred_counts"]))
    print("  chosen:", out.get("chosen"))


if __name__ == "__main__":
    for rubric in (sys.argv[1:] or list(RUBRIC_FILE)):
        rubric = {"gtm": "gtm-datalayer-event", "consent": "multilingual-consent-banner", "wrangler": "wrangler-bindings"}.get(rubric, rubric)
        if os.path.exists(os.path.join(s1cal.FIXTURES, rubric, "predictions.jsonl")):
            summary(evaluate_rubric(rubric))
