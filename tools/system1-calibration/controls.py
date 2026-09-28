"""Known-answer control fixtures for the three Laya rubrics.

    python tools/system1-calibration/controls.py     # (re)write fixtures, print digests

Each control file holds exactly the canonicalized state bytes the model is sent
(no trailing newline): RFC 8785 JCS for the JSON rubrics (a JCS document is
also valid JSONC, and re-extracting and re-canonicalizing it is the identity),
and `utf8_nfc_lf_trim_trailing` text for the consent banner. So
input_digest = SHA-256(file bytes) = SHA-256(canonical state). Expected
statuses are certified by labelers.py, not by a model.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1cal  # noqa: E402
from labelers import label_consent, label_gtm, label_wrangler  # noqa: E402

_ITEM = {"item_id": "SKU_CTRL_01", "item_name": "Control Hoodie", "price": 80, "quantity": 1}

CONTROLS = {
    "gtm-datalayer-event": [
        ("CTL-GTM-PURCHASE-VALID", "test/fixtures/datalayer/controls/purchase-valid.json", "VERIFIED",
         {"event": "purchase", "ecommerce": {"transaction_id": "T-20260927-0042", "value": 84.9, "currency": "EUR",
                                              "shipping": 4.9, "items": [_ITEM]}}),
        ("CTL-GTM-PURCHASE-NO-CURRENCY", "test/fixtures/datalayer/controls/purchase-missing-currency.json", "REFUTED",
         {"event": "purchase", "ecommerce": {"transaction_id": "T-20260927-0042", "value": 84.9, "shipping": 4.9,
                                              "items": [_ITEM]}}),
        ("CTL-GTM-ADD-TO-CART", "test/fixtures/datalayer/controls/add-to-cart.json", "REFUTED",
         {"event": "add_to_cart", "ecommerce": {"currency": "EUR", "value": 80, "items": [_ITEM]}}),
    ],
    "wrangler-bindings": [
        ("CTL-WRANGLER-ALL-BOUND", "test/fixtures/wrangler/controls/all-bound.jsonc", "VERIFIED",
         {"d1_databases": [{"binding": "DB", "database_name": "control-db", "database_id": "0f6d2c4e-8a1b-4c3d-9e5f-7a6b5c4d3e2f"}],
          "kv_namespaces": [{"binding": "CACHE", "id": "5d41402abc4b2a76b9719d911017c592"}],
          "r2_buckets": [{"binding": "ASSETS", "bucket_name": "control-assets"}]}),
        ("CTL-WRANGLER-NO-R2", "test/fixtures/wrangler/controls/missing-r2.jsonc", "REFUTED",
         {"d1_databases": [{"binding": "DB", "database_name": "control-db", "database_id": "0f6d2c4e-8a1b-4c3d-9e5f-7a6b5c4d3e2f"}],
          "kv_namespaces": [{"binding": "CACHE", "id": "5d41402abc4b2a76b9719d911017c592"}]}),
        ("CTL-WRANGLER-WRONG-KV-NAME", "test/fixtures/wrangler/controls/kv-bound-as-kv.jsonc", "REFUTED",
         {"d1_databases": [{"binding": "DB", "database_name": "control-db", "database_id": "0f6d2c4e-8a1b-4c3d-9e5f-7a6b5c4d3e2f"}],
          "kv_namespaces": [{"binding": "KV", "id": "5d41402abc4b2a76b9719d911017c592"}],
          "r2_buckets": [{"binding": "ASSETS", "bucket_name": "control-assets"}]}),
    ],
    "multilingual-consent-banner": [
        ("CTL-CONSENT-DE-COMPLETE", "test/fixtures/consent/controls/de-complete.txt", "VERIFIED",
         {"lang": "de", "is_banner": True, "segments": [
             {"kind": "filler", "text": "Datenschutz-Hinweis"},
             {"kind": "purpose", "text": "Mit Cookies werten wir aus, wie unser Onlineshop genutzt wird, und blenden passende Angebote ein."},
             {"kind": "third_parties", "text": "Diese Daten erhalten auch unsere Werbe- und Analysepartner, etwa Google."},
             {"kind": "withdrawal", "text": "Sie können Ihre Zustimmung verweigern oder später jederzeit unter „Datenschutz-Einstellungen“ zurückziehen."},
             {"kind": "filler", "text": "[Einverstanden]"}]}),
        ("CTL-CONSENT-ES-NO-WITHDRAW", "test/fixtures/consent/controls/es-missing-withdrawal.txt", "REFUTED",
         {"lang": "es", "is_banner": True, "segments": [
             {"kind": "filler", "text": "Aviso de cookies"},
             {"kind": "purpose", "text": "Usamos cookies para conocer cómo navega por nuestra tienda y ofrecerle promociones adaptadas a sus intereses."},
             {"kind": "third_parties", "text": "Compartimos estos datos con empresas colaboradoras, como Google y Meta."},
             {"kind": "filler", "text": "[Aceptar]"}]}),
        ("CTL-CONSENT-JA-NO-THIRD-PARTY", "test/fixtures/consent/controls/ja-missing-third-parties.txt", "REFUTED",
         {"lang": "ja", "is_banner": True, "segments": [
             {"kind": "filler", "text": "Cookieの使用について"},
             {"kind": "purpose", "text": "当ストアでは、ご利用状況の把握とおすすめ商品の表示のためにCookieを使用します。"},
             {"kind": "withdrawal", "text": "同意しない場合は「拒否する」を選択でき、設定画面からいつでも同意を取り消せます。"},
             {"kind": "filler", "text": "[同意する]"}]}),
    ],
}


def _state(rubric, content):
    if rubric == "multilingual-consent-banner":
        segs = [s["text"] for s in content["segments"]]
        sep = "" if content["lang"] == "ja" else " "
        return s1cal.canonical_text(segs[0] + "\n" + sep.join(segs[1:-1]) + "\n" + segs[-1])
    if rubric == "wrangler-bindings":
        return s1cal.jcs(s1cal.extract_bindings(content))
    return s1cal.jcs(content)


def _expected_from_labeler(rubric, content):
    if rubric == "gtm-datalayer-event":
        return "VERIFIED" if label_gtm(content)["label"] == "holds" else "REFUTED"
    if rubric == "wrangler-bindings":
        return "VERIFIED" if label_wrangler(content)["label"] == "holds" else "REFUTED"
    lab = label_consent(content)["label"]
    return {"A": "VERIFIED", "B": "REFUTED"}[lab]


def controls(rubric):
    """[(control_id, locator, expected, state, input_digest)] - reads nothing, derives everything."""
    out = []
    for cid, loc, expected, content in CONTROLS[rubric]:
        assert _expected_from_labeler(rubric, content) == expected, cid
        state = _state(rubric, content)
        out.append({"control_id": cid, "locator": loc, "expected": expected, "state": state,
                    "input_digest": s1cal.sha256_text(state)})
    return out


def write_all():
    for rubric in CONTROLS:
        data = {r["id"]: r for split in ("calibration", "test")
                for r in s1cal.read_jsonl(os.path.join(s1cal.FIXTURES, rubric, split + ".jsonl"))}
        digests = {r["input_digest"] for r in data.values()}
        for c in controls(rubric):
            assert c["input_digest"] not in digests, "control duplicates a dataset item: " + c["control_id"]
            path = os.path.join(s1cal.ROOT, c["locator"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(c["state"])
            assert s1cal.file_sha256(path) == c["input_digest"]
            if rubric == "wrangler-bindings":  # the pinned canonicalization is the identity on the file
                assert s1cal.jcs(s1cal.extract_bindings(s1cal.parse_jsonc(c["state"]))) == c["state"]
            elif rubric == "gtm-datalayer-event":
                assert s1cal.jcs(json.loads(c["state"])) == c["state"]
            else:
                assert s1cal.canonical_text(c["state"]) == c["state"]
            print(rubric, c["control_id"], c["expected"], c["input_digest"])


if __name__ == "__main__":
    write_all()
