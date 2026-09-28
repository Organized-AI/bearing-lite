"""Replay the controls for the chosen formulation, including fresh processes.

    python tools/system1-calibration/replay.py gtm [--fresh-runs 2]

Run 1-3 come from controls-inprocess.json (one process, same model object).
Each fresh run starts a new Python interpreter that loads the pinned checkpoint
from scratch and scores every control once. The max pairwise difference of the
calibrated thresholded probability over all runs is the measured replay delta;
replay.json records it with the raw-logit delta and the per-run statuses.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1cal  # noqa: E402
from controls import controls  # noqa: E402
from formulations import FORMULATIONS, decision_sets  # noqa: E402
from run_formulations import ALIASES, RUNTIME  # noqa: E402


def fresh(rubric, name):
    f = FORMULATIONS[rubric][name]
    run = s1cal.LayaRunner(f["checkpoint"], *RUNTIME[f["checkpoint"]])
    out = {c["control_id"]: run.logits([c["state"]], f["question"])[0].tolist() for c in controls(rubric)}
    print("RESULT " + json.dumps({"pid": os.getpid(), "logits": out}))


def main(rubric, fresh_runs):
    d = os.path.join(s1cal.FIXTURES, rubric)
    res = json.load(open(os.path.join(d, "results.json"), encoding="utf-8"))
    name = res["chosen"]["formulation"]
    fr = res["formulations"][name]
    q = FORMULATIONS[rubric][name]["question"]
    keys = s1cal.option_keys(q)
    holds, fails = decision_sets(q)
    vt, rt, t = res["verify_threshold"], res["refute_threshold"], fr["temperature"]
    runs = {cid: [{"fresh_process": False, "pid": "inprocess", "logits": lg} for lg in lgs]
            for cid, lgs in json.load(open(os.path.join(d, "controls-inprocess.json"), encoding="utf-8"))[name].items()}
    for _ in range(fresh_runs):
        p = subprocess.run([sys.executable, os.path.abspath(__file__), "--fresh", rubric, name],
                           capture_output=True, text=True, check=True, env={**os.environ, "HF_HUB_OFFLINE": "1"})
        payload = json.loads([ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")][-1][7:])
        for cid, lg in payload["logits"].items():
            runs[cid].append({"fresh_process": True, "pid": payload["pid"], "logits": lg})
    report = {"rubric": rubric, "formulation": name, "temperature": t, "controls": {}}
    worst_p = worst_l = worst_r = 0.0
    for cid, rs in runs.items():
        mapped = [s1cal.map_status(s1cal.softmax(np.array(r["logits"]), t), keys, holds, fails, vt, rt) for r in rs]
        probs = [m[2] for m in mapped]
        rounded = [round(p, 4) for p in probs]  # laya returns probabilities rounded to 4 decimals
        lg = np.array([r["logits"] for r in rs])
        dp = max(probs) - min(probs)
        dl = float((lg.max(0) - lg.min(0)).max())
        dr = max(rounded) - min(rounded)
        worst_p, worst_l, worst_r = max(worst_p, dp), max(worst_l, dl), max(worst_r, dr)
        report["controls"][cid] = {
            "runs": len(rs), "fresh_process_runs": sum(r["fresh_process"] for r in rs),
            "statuses": [m[0] for m in mapped], "answers": [m[1] for m in mapped],
            "thresholded_probability": probs, "max_probability_delta": dp, "max_logit_delta": dl,
            "max_rounded_probability_delta": dr,
            "identical_status": len({m[0] for m in mapped}) == 1, "identical_answer": len({m[1] for m in mapped}) == 1}
    report.update({"max_probability_delta": worst_p, "max_logit_delta": worst_l, "max_rounded_probability_delta": worst_r})
    # Sessions accumulate: a later quiet session must not erase a divergence an earlier one observed.
    path = os.path.join(d, "replay.json")
    prior = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    sessions = [s for s in prior.get("sessions", []) if s.get("formulation") == name]
    report["session"] = len(sessions) + 1
    sessions.append(report)
    out = {"rubric": rubric, "formulation": name, "temperature": t, "sessions": sessions,
           "max_probability_delta": max(s["max_probability_delta"] for s in sessions),
           "max_logit_delta": max(s["max_logit_delta"] for s in sessions),
           "max_rounded_probability_delta": max(s["max_rounded_probability_delta"] for s in sessions),
           "controls": {cid: {"runs": 3 + sum(s["controls"][cid]["fresh_process_runs"] for s in sessions),
                              "fresh_process_runs": sum(s["controls"][cid]["fresh_process_runs"] for s in sessions),
                              "statuses": sorted({st for s in sessions for st in s["controls"][cid]["statuses"]})}
                        for cid in report["controls"]}}
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "controls"}))
    for cid, c in report["controls"].items():
        print(" ", cid, c["statuses"], "dp=%.3g dl=%.3g" % (c["max_probability_delta"], c["max_logit_delta"]))


if __name__ == "__main__":
    if sys.argv[1] == "--fresh":
        fresh(sys.argv[2], sys.argv[3])
    else:
        n = int(sys.argv[sys.argv.index("--fresh-runs") + 1]) if "--fresh-runs" in sys.argv else 2
        main(ALIASES.get(sys.argv[1], sys.argv[1]), n)
