"""Pipeline sanity probe (diagnostic, not a rubric): shows the capture/calibration
path works on easy single-attribute questions, so chance-level rubric accuracy
is the model's, not the harness's.

    python tools/system1-calibration/sanity_probe.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1cal  # noqa: E402

if __name__ == "__main__":
    rows = s1cal.read_jsonl(os.path.join(s1cal.FIXTURES, "gtm-datalayer-event", "test.jsonl"))
    ok = [r for r in rows if r["variant"] == "valid"][:20]
    we = [r for r in rows if r["variant"] == "wrong_event"][:20]
    run = s1cal.LayaRunner("laya", 512, 192)
    q = {"key": "k", "type": "choice", "instructions": "The state is one dataLayer push as JSON. What is the value of its `event` field?",
         "criteria": {"A": "purchase", "B": "something other than purchase"}}
    lg = run.logits([x["state"] for x in ok + we], q)
    pred = ["A" if l[0] > l[1] else "B" for l in lg]
    truth = ["A"] * len(ok) + ["B"] * len(we)
    print("event-name probe on dataset pushes: accuracy %.3f (n=%d)" % (np.mean([a == b for a, b in zip(pred, truth)]), len(truth)))
    q2 = {"key": "k", "type": "choice", "instructions": "Which kind of event is this dataLayer push?",
          "criteria": {"A": "a purchase", "B": "an add to cart", "C": "a page view"}}
    states = ['{"event":"purchase","ecommerce":{"value":10}}', '{"event":"add_to_cart","ecommerce":{"value":10}}',
              '{"event":"page_view","page":"/home"}']
    for s, l in zip(states, run.logits(states, q2)):
        print(s, np.round(s1cal.softmax(l, 1.0), 3).tolist())
    q3 = {"key": "k", "type": "noul", "instructions": "Is the customer asking for a refund?"}
    for s in ["I want my money back for this broken blender.", "What time do you open on Sunday?"]:
        print(s, "p(yes)=%.3f" % s1cal.softmax(run.logits([s], q3)[0], 1.983399510383606)[1])
