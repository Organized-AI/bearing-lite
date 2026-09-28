"""Score every pre-registered formulation over a rubric's dataset and controls.

    python tools/system1-calibration/run_formulations.py gtm [formulation ...]

Uses the pinned CPU fp32 eval-mode checkpoint with one state per forward pass
(the serving path; batching changes padding and moves logits by ~1e-5).
Appends raw option logits (6 decimals) per item to
test/fixtures/system1-calibration/<rubric>/predictions.jsonl, and runs each
control 3 times in-process, recording full-precision logits in
controls-inprocess.json. Idempotent: formulations already scored are skipped.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1cal  # noqa: E402
from controls import controls  # noqa: E402
from formulations import FORMULATIONS  # noqa: E402

RUNTIME = {"laya": (512, 192), "laya-typed-decisions": (512, 192), "laya-multilingual": (1024, 256)}
ALIASES = {"gtm": "gtm-datalayer-event", "consent": "multilingual-consent-banner", "wrangler": "wrangler-bindings"}


def main(rubric, only):
    d = os.path.join(s1cal.FIXTURES, rubric)
    rows = s1cal.read_jsonl(os.path.join(d, "calibration.jsonl")) + s1cal.read_jsonl(os.path.join(d, "test.jsonl"))
    pred_path = os.path.join(d, "predictions.jsonl")
    preds = {r["id"]: r for r in s1cal.read_jsonl(pred_path)} if os.path.exists(pred_path) else {}
    ctl_path = os.path.join(d, "controls-inprocess.json")
    ctl = json.load(open(ctl_path, encoding="utf-8")) if os.path.exists(ctl_path) else {}
    runners = {}
    for name, f in FORMULATIONS[rubric].items():
        if only and name not in only:
            continue
        if rows and all(name in preds.get(r["id"], {}) for r in rows) and name in ctl:
            print("skip", name, flush=True)
            continue
        ck = f["checkpoint"]
        if ck not in runners:
            runners.clear()  # one model in memory at a time (7 GB box)
            runners[ck] = s1cal.LayaRunner(ck, *RUNTIME[ck])
        run = runners[ck]
        used, cut = run.head_tokens(f["question"])
        assert not cut, "%s: instructions would be truncated by head_max_len" % name
        t0 = time.time()
        logits = run.logits([r["state"] for r in rows], f["question"], batch_size=1)
        for r, lg in zip(rows, logits):
            preds.setdefault(r["id"], {"id": r["id"]})[name] = [round(float(x), 6) for x in lg]
        s1cal.write_jsonl(pred_path, [preds[k] for k in sorted(preds)])
        ctl[name] = {}
        for c in controls(rubric):
            ctl[name][c["control_id"]] = [run.logits([c["state"]], f["question"])[0].tolist() for _ in range(3)]
        with open(ctl_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(ctl, indent=1) + "\n")
        print("%s %s head_tokens=%d builtin_T=%.6f n=%d %.1fs" % (
            rubric, name, used, run.builtin_temperature(f["question"]["type"], len(logits[0])), len(rows),
            time.time() - t0), flush=True)


if __name__ == "__main__":
    rubric = ALIASES.get(sys.argv[1], sys.argv[1])
    main(rubric, set(sys.argv[2:]))
