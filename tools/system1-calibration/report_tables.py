"""Print the markdown tables used in docs/calibration/system1-calibration-report.md.

    python tools/system1-calibration/report_tables.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1cal  # noqa: E402
from evaluate import RUBRIC_FILE  # noqa: E402


def f3(x):
    return "n/a" if x is None else "%.3f" % x


def main():
    print("| Rubric | Formulation | Held-out acc | ECE raw / shipped / fitted | T | Coverage | Precision | Controls | epsilon | assurance_eligible |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    per = {}
    for rubric, fn in RUBRIC_FILE.items():
        d = os.path.join(s1cal.FIXTURES, rubric)
        res = json.load(open(os.path.join(d, "results.json"), encoding="utf-8"))
        rb = json.load(open(os.path.join(s1cal.RUBRICS_DIR, fn), encoding="utf-8"))
        per[rubric] = res
        name = res["chosen"]["formulation"]
        r = res["formulations"][name]
        tc = r["test_calibrated"]
        ctl = sum(v["pass"] for v in r["controls"].values())
        print("| %s %s | `%s` | %.3f | %.3f / %.3f / %.3f | %.4g | %.3f | %s | %d/%d pass | %g | %s |" % (
            rb["rubric_id"], rb["rubric_version"], name, tc["accuracy"], r["test_raw"]["ece"], r["test_shipped"]["ece"],
            tc["ece"], r["temperature"], tc["coverage"], f3(tc["precision"]), ctl, len(r["controls"]),
            rb["replay"]["probability_epsilon"], str(rb["assurance_eligible"]).lower()))
    for rubric, res in per.items():
        print("\n#### %s (verify %.2f, refute %.2f, max_ece %.2f)\n" % (rubric, res["verify_threshold"], res["refute_threshold"], res["max_ece"]))
        print("| Formulation | Checkpoint | Schema | T | Cal acc | Held-out acc | ECE raw | ECE shipped | ECE fitted | Coverage | Precision | V / R / I | Controls (observed at fitted T) |")
        print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for n, r in res["formulations"].items():
            tc = r["test_calibrated"]
            ctl = ", ".join("%s %s" % (c.replace("CTL-", ""), v["observed"][0]) for c, v in r["controls"].items())
            print("| `%s`%s | %s | %s | %.3g | %.3f | %.3f | %.3f | %.3f | %.3f | %.3f | %s | %d / %d / %d | %s |" % (
                n, " (chosen)" if n == res["chosen"]["formulation"] else "", r["checkpoint"],
                "yes" if r["schema_ok"] else "no (diagnostic)", r["temperature"], r["calibration_calibrated"]["accuracy"],
                tc["accuracy"], r["test_raw"]["ece"], r["test_shipped"]["ece"], tc["ece"], tc["coverage"],
                f3(tc["precision"]), tc["verified"], tc["refuted"], tc["inconclusive"], ctl))


if __name__ == "__main__":
    main()
