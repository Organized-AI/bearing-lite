"""Shared helpers for System One (Laya) rubric calibration.

Everything here is deterministic except the model forward pass itself:
canonicalization, digests, splitting, temperature fitting, and the status
mapping. Ground-truth labels never come from this module or from a model; they
come from the per-rubric labelers in labelers.py.

Temperature semantics (frozen in each rubric's `calibration.temperature`):
the rubric temperature T REPLACES the checkpoint's built-in temperature for the
question's (type, option-count) bucket, so the calibrated probabilities are
softmax(logits / T) over the question's option logits. A runner applies it by
setting `agent.temperature_by_options[temp_bucket(qtype, k)] = T` and passing
no `lang` (so `lang_temperatures` cannot override it).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

REPO = "convaiinnovations/laya"
REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
SUBFOLDER = {"laya": None, "laya-multilingual": "multilingual", "laya-typed-decisions": "typed-decisions"}

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FIXTURES = os.path.join(ROOT, "test", "fixtures", "system1-calibration")
RUBRICS_DIR = os.path.join(ROOT, "skills", "bearing-lite", "references", "system1-rubrics")

SPLIT_SEED = 20260927
CAL_FRACTION = 0.5


# ---------------------------------------------------------------- canonical JSON

def _jcs_number(x: Any) -> str:
    if isinstance(x, bool):
        raise TypeError("bool is not a number")
    if isinstance(x, int):
        return str(x)
    if not math.isfinite(x):
        raise ValueError("RFC 8785 forbids NaN/Infinity")
    if x == 0:
        return "0"
    if float(x).is_integer() and abs(x) < 1e21:
        return str(int(x))
    r = repr(float(x))  # shortest round-trip, same digits as ECMAScript Number#toString
    if "e" in r:
        mant, exp = r.split("e")
        exp_i = int(exp)
        if -7 < exp_i < 21:
            # ECMAScript prints this range without an exponent
            return format(float(x), "f").rstrip("0").rstrip(".") if "." in format(float(x), "f") else format(float(x), "f")
        return "%se%s%d" % (mant, "+" if exp_i > 0 else "-", abs(exp_i))
    return r


def jcs(value: Any) -> str:
    """RFC 8785 JSON Canonicalization Scheme (sufficient for the values used here:
    strings, ints, finite floats, bools, null, arrays, objects with string keys).
    Keys sort by UTF-16 code units, strings are escaped as ECMAScript JSON.stringify."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _jcs_number(value)
    if isinstance(value, str):
        return _jcs_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(jcs(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value.keys(), key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(_jcs_string(k) + ":" + jcs(value[k]) for k in keys) + "}"
    raise TypeError("unsupported type %s" % type(value).__name__)


_ESC = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _jcs_string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _ESC:
            out.append(_ESC[ch])
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def canonical_text(s: str) -> str:
    """`utf8_nfc_lf_trim_trailing`: NFC, CRLF/CR -> LF, trailing whitespace removed
    from every line and from the end of the document (no final newline)."""
    s = unicodedata.normalize("NFC", s).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in s.split("\n")).rstrip()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def bridge_canonical_json(value: Any) -> str:
    """hooks/verification-bridge.cjs canonicalJson: sorted keys, no whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------- JSONC / TOML

def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas outside strings."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\":
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith("/*", i):
            i = text.index("*/", i) + 2; continue
        out.append(c); i += 1
    s = "".join(out)
    # trailing commas
    res, in_str, i = [], False, 0
    while i < len(s):
        c = s[i]
        if in_str:
            res.append(c)
            if c == "\\":
                res.append(s[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; res.append(c); i += 1; continue
        if c == ",":
            j = i + 1
            while j < len(s) and s[j] in " \t\r\n":
                j += 1
            if j < len(s) and s[j] in "]}":
                i += 1; continue
        res.append(c); i += 1
    return "".join(res)


def parse_jsonc(text: str) -> Any:
    return json.loads(strip_jsonc(text))


BINDING_KEYS = ("d1_databases", "kv_namespaces", "r2_buckets")


def extract_bindings(config: Dict[str, Any]) -> Dict[str, Any]:
    """Extractor `keys:d1_databases,kv_namespaces,r2_buckets`: keep only those keys (absent stays absent)."""
    return {k: config[k] for k in BINDING_KEYS if k in config}


# ---------------------------------------------------------------- dataset io

def write_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> str:
    """Canonical JSONL: one RFC 8785 line per row, LF-terminated. Returns the file's SHA-256."""
    text = "".join(jcs(r) + "\n" for r in rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return sha256_text(text)


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def file_sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def stratified_split(items: List[Dict[str, Any]], label_key: str = "label",
                     seed: int = SPLIT_SEED, cal_fraction: float = CAL_FRACTION):
    """Deterministic stratified split by label: returns (calibration, test)."""
    rng = random.Random(seed)
    by: Dict[str, List[Dict[str, Any]]] = {}
    for it in sorted(items, key=lambda r: r["id"]):
        by.setdefault(str(it[label_key]), []).append(it)
    cal, test = [], []
    for lab in sorted(by):
        grp = by[lab][:]
        rng.shuffle(grp)
        m = int(round(len(grp) * cal_fraction))
        cal.extend(grp[:m]); test.extend(grp[m:])
    return sorted(cal, key=lambda r: r["id"]), sorted(test, key=lambda r: r["id"])


# ---------------------------------------------------------------- model

class LayaRunner:
    """Pinned CPU fp32 eval-mode Laya with full-precision logit capture."""

    def __init__(self, checkpoint: str, max_len: int, head_max_len: int):
        import torch
        import laya
        torch.set_grad_enabled(False)
        kw = {"device": "cpu", "revision": REVISION}
        if SUBFOLDER[checkpoint]:
            kw["subfolder"] = SUBFOLDER[checkpoint]
        self.checkpoint = checkpoint
        self.agent = laya.load(REPO, **kw)
        self.max_len, self.head_max_len = max_len, head_max_len
        self._captured: List[np.ndarray] = []
        orig = self.agent._decode_answers

        def wrapped(logits, act, items, ids, internal, offset, **kw2):
            for j, _qid in enumerate(ids):
                k = len(items[j]["markers"])
                self._captured.append(np.array(logits[offset + j, :k], dtype=np.float64))
            return orig(logits, act, items, ids, internal, offset, **kw2)

        self.agent._decode_answers = wrapped
        from laya.common import encode_text
        self._encode_text = encode_text
        self.model_eval = not self.agent.model.training

    def builtin_temperature(self, qtype: str, k: int) -> float:
        from laya.common import QTYPES, temp_bucket
        qt = QTYPES[qtype]
        return float(self.agent.temperature_by_options.get(temp_bucket(qt, k), self.agent.temperature[qt]))

    def state_tokens(self, state: str) -> int:
        tok = self.agent.tok
        return len(self._encode_text(tok, state.replace(tok.mask_token, " "), add_special_tokens=False)["input_ids"])

    def head_tokens(self, question: Dict[str, Any]) -> Tuple[int, bool]:
        """Tokens used by the question head and whether the instructions would be cut."""
        from laya.common import render_options
        tok = self.agent.tok
        q = self.agent._to_internal(question)
        opts = render_options(q)
        head = len(self._encode_text(tok, "%s question: %s" % (q["t"], q["ins"]), add_special_tokens=False)["input_ids"])
        opt = sum(1 + min(48, len(self._encode_text(tok, " " + o, add_special_tokens=False)["input_ids"])) for o in opts)
        budget = self.head_max_len - opt
        return head + opt, head > max(8, budget)

    def logits(self, states: Sequence[str], question: Dict[str, Any], batch_size: int = 1) -> List[np.ndarray]:
        """Raw option logits per state (option order = criteria order; noul = [false, true])."""
        qd = {k: v for k, v in question.items() if k != "key"}
        qs = {question["key"]: qd}
        out: List[np.ndarray] = []
        for s in range(0, len(states), batch_size):
            chunk = list(states[s:s + batch_size])
            self._captured.clear()
            if len(chunk) == 1:
                self.agent.predict(chunk[0], qs, max_len=self.max_len, head_max_len=self.head_max_len)
            else:
                self.agent.predict_batch(chunk, qs, batch_size=len(chunk), max_len=self.max_len,
                                         head_max_len=self.head_max_len)
            assert len(self._captured) == len(chunk)
            out.extend(self._captured)
        return out

    def predict_raw(self, state: str, question: Dict[str, Any]) -> Dict[str, Any]:
        qd = {k: v for k, v in question.items() if k != "key"}
        self._captured.clear()
        r = self.agent.predict(state, {question["key"]: qd}, max_len=self.max_len, head_max_len=self.head_max_len)
        return {"answer": r["answers"][question["key"]], "logits": self._captured[0].tolist(), "usage": r["usage"]}


def option_keys(question: Dict[str, Any]) -> List[str]:
    if question["type"] == "noul":
        return ["no", "yes"]  # laya noul option order is [false, true]
    return list(question["criteria"].keys())


# ---------------------------------------------------------------- calibration math

def softmax(z: np.ndarray, t: float) -> np.ndarray:
    z = np.asarray(z, dtype=np.float64) / t
    e = np.exp(z - z.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def nll(logits: np.ndarray, y: np.ndarray, t: float) -> float:
    p = softmax(logits, t)
    return float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-300, 1.0))))


def fit_temperature(logits: np.ndarray, y: np.ndarray, lo: float = 0.05, hi: float = 20.0) -> float:
    """Minimize NLL over T in [lo, hi]: log-spaced grid, then golden-section refinement."""
    grid = np.exp(np.linspace(math.log(lo), math.log(hi), 400))
    vals = [nll(logits, y, t) for t in grid]
    i = int(np.argmin(vals))
    a, b = grid[max(0, i - 1)], grid[min(len(grid) - 1, i + 1)]
    g = (math.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    for _ in range(80):
        if nll(logits, y, c) < nll(logits, y, d):
            b = d
        else:
            a = c
        c, d = b - g * (b - a), a + g * (b - a)
    return float((a + b) / 2)


def ece(conf: np.ndarray, correct: np.ndarray) -> float:
    import laya
    return float(laya.ece_score(np.asarray(conf, dtype=np.float64), np.asarray(correct, dtype=np.float64), bins=15))


def map_status(p: np.ndarray, keys: List[str], holds: List[str], fails: List[str],
               vt: float, rt: float) -> Tuple[str, str, float]:
    """Rubric decision mapping for one run. Returns (status, hard_answer, thresholded_mass)."""
    top = float(p.max())
    if int((p == top).sum()) > 1:
        return "INCONCLUSIVE", "", top
    ans = keys[int(p.argmax())]
    hm = float(sum(p[keys.index(k)] for k in holds))
    fm = float(sum(p[keys.index(k)] for k in fails))
    if ans in holds:
        return ("VERIFIED" if hm >= vt else "INCONCLUSIVE"), ans, hm
    if ans in fails:
        return ("REFUTED" if fm >= rt else "INCONCLUSIVE"), ans, fm
    return "INCONCLUSIVE", ans, top


def evaluate(logits: np.ndarray, truth: List[str], keys: List[str], holds: List[str], fails: List[str],
             vt: float, rt: float, t: float) -> Dict[str, Any]:
    """Accuracy, ECE (top-1 confidence vs correctness), and threshold-gated coverage/precision."""
    p = softmax(logits, t)
    pred = [keys[int(i)] for i in p.argmax(axis=1)]
    correct = np.array([a == b for a, b in zip(pred, truth)], dtype=np.float64)
    conf = p.max(axis=1)
    statuses = [map_status(p[i], keys, holds, fails, vt, rt)[0] for i in range(len(truth))]
    gated = [(s, tr) for s, tr in zip(statuses, truth) if s != "INCONCLUSIVE"]
    ok = [(s == "VERIFIED" and tr in holds) or (s == "REFUTED" and tr in fails) for s, tr in gated]
    n_v = sum(1 for s, _ in gated if s == "VERIFIED")
    n_r = sum(1 for s, _ in gated if s == "REFUTED")
    v_ok = sum(1 for (s, tr), o in zip(gated, ok) if s == "VERIFIED" and o)
    r_ok = sum(1 for (s, tr), o in zip(gated, ok) if s == "REFUTED" and o)
    return {
        "n": len(truth),
        "accuracy": float(correct.mean()),
        "ece": ece(conf, correct),
        "nll": float(-np.mean(np.log(np.clip(p[np.arange(len(truth)), [keys.index(x) for x in truth]], 1e-300, 1)))),
        "coverage": len(gated) / len(truth),
        "precision": (sum(ok) / len(gated)) if gated else None,
        "verified": n_v, "verified_correct": v_ok,
        "refuted": n_r, "refuted_correct": r_ok,
        "inconclusive": len(truth) - len(gated),
        "pred_counts": {k: pred.count(k) for k in keys},
    }


def load_tokenizer(checkpoint: str):
    """The pinned checkpoint's tokenizer only (no weights), loaded the way laya loads it."""
    from huggingface_hub import snapshot_download
    from laya import agent as _ag
    sub = SUBFOLDER[checkpoint]
    prefix = (sub + "/") if sub else ""
    d = snapshot_download(REPO, revision=REVISION, allow_patterns=[prefix + "rl_agent_config.json", prefix + "tokenizer/*"])
    if sub:
        d = os.path.join(d, sub)
    _ag._fix_tokenizer_config(d)
    with open(os.path.join(d, "rl_agent_config.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    return _ag._load_tokenizer(os.path.join(d, "tokenizer"), cfg)


def count_state_tokens(tok, state: str) -> int:
    from laya.common import encode_text
    return len(encode_text(tok, state.replace(tok.mask_token, " "), add_special_tokens=False)["input_ids"])
