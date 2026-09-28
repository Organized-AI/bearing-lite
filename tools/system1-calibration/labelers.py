"""Deterministic ground-truth labelers. No model is ever consulted.

Each labeler implements the rule text of its rubric literally:

gtm-datalayer-event  (RUB-S1-GTM-DATALAYER-PURCHASE)
  holds iff `event` == "purchase" AND `ecommerce` is an object that contains
  transaction_id, value, currency AND currency is a 3-letter ISO 4217 code
  (exact uppercase code from the active ISO 4217 list below) AND items is an
  array with at least one object item that has item_id or item_name.
  "contains" means the key is present with a non-null, non-empty-string value.

multilingual-consent-banner  (RUB-S1-CONSENT-BANNER-DISCLOSURES)
  Banners are assembled from typed segments; the labeler reads the segment
  kinds. A (holds) iff the text is a banner AND it has a purpose segment AND a
  third-parties segment AND a withdrawal segment; B (fails) iff it is a banner
  missing at least one; C iff it is not banner text. A lexical leak check
  confirms that filler segments carry no disclosure cue words.

wrangler-bindings  (RUB-S1-WRANGLER-REQUIRED-BINDINGS)
  holds iff d1_databases has an entry with binding "DB" and a non-empty string
  database_id, AND kv_namespaces has an entry with binding "CACHE" and a
  non-empty string id, AND r2_buckets has an entry with binding "ASSETS" and a
  non-empty string bucket_name. Binding names are case-sensitive.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Active ISO 4217 alphabetic codes (subset large enough to cover every code the
# generator can emit as a valid currency, plus the common ones).
ISO_4217 = frozenset("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD
CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD
GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT
LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR
NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP
STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF
XPF YER ZAR ZMW ZWL
""".split())


def _present(obj: Dict[str, Any], key: str) -> bool:
    if key not in obj:
        return False
    v = obj[key]
    return v is not None and v != ""


def label_gtm(push: Any) -> Dict[str, Any]:
    reasons: List[str] = []
    if not isinstance(push, dict):
        return {"label": "fails", "reasons": ["not_an_object"]}
    if push.get("event") != "purchase":
        reasons.append("event_not_purchase")
    ec = push.get("ecommerce")
    if not isinstance(ec, dict):
        reasons.append("ecommerce_missing")
    else:
        for k in ("transaction_id", "value", "currency"):
            if not _present(ec, k):
                reasons.append("missing_" + k)
        cur = ec.get("currency")
        if _present(ec, "currency") and not (isinstance(cur, str) and cur in ISO_4217):
            reasons.append("currency_not_iso4217")
        items = ec.get("items")
        if not isinstance(items, list):
            reasons.append("items_not_array")
        elif not any(isinstance(it, dict) and (_present(it, "item_id") or _present(it, "item_name")) for it in items):
            reasons.append("items_empty" if len(items) == 0 else "no_item_with_id_or_name")
    return {"label": "holds" if not reasons else "fails", "reasons": reasons}


# Cue words per language that must NOT appear in filler segments (leak check).
CONSENT_CUES = {
    "en": ["partner", "third", "withdraw", "refuse", "reject", "decline", "measure", "analy", "personal", "advert"],
    "de": ["partner", "dritt", "widerruf", "ablehn", "analys", "personalis", "werb", "messen"],
    "fr": ["partenaire", "tiers", "retir", "refus", "mesur", "analy", "personnalis", "publicit"],
    "es": ["socio", "terceros", "retirar", "rechaz", "medir", "anali", "personaliz", "publicid"],
    "it": ["partner", "terze", "terzi", "revoc", "rifiut", "misur", "anali", "personalizz", "pubblicit"],
    "pt": ["parceir", "terceir", "retirar", "recus", "medir", "anális", "personaliz", "publicid"],
    "nl": ["partner", "derde", "intrekken", "weiger", "meten", "analy", "personalis", "advertent"],
    "ja": ["パートナー", "第三者", "撤回", "拒否", "分析", "測定", "広告", "パーソナライズ"],
}

DISCLOSURES = ("purpose", "third_parties", "withdrawal")


def label_consent(item: Dict[str, Any]) -> Dict[str, Any]:
    """item: {"lang", "is_banner", "segments": [{"kind", "text"}]}"""
    kinds = {s["kind"] for s in item["segments"]}
    disclosures = {d: (d in kinds) for d in DISCLOSURES}
    cues = CONSENT_CUES.get(item["lang"], [])
    for s in item["segments"]:
        if s["kind"] == "filler":
            low = s["text"].lower()
            for c in cues:
                if c in low:
                    raise AssertionError("filler segment leaks disclosure cue %r: %r" % (c, s["text"]))
    if not item["is_banner"]:
        return {"label": "C", "disclosures": disclosures, "missing": []}
    missing = [d for d in DISCLOSURES if not disclosures[d]]
    return {"label": "A" if not missing else "B", "disclosures": disclosures, "missing": missing}


def _has_binding(state: Dict[str, Any], array: str, name: str, id_key: str) -> str:
    arr = state.get(array)
    if not isinstance(arr, list):
        return "missing_" + array
    entries = [e for e in arr if isinstance(e, dict) and e.get("binding") == name]
    if not entries:
        return "no_%s_binding_%s" % (array, name)
    if not any(isinstance(e.get(id_key), str) and e.get(id_key) != "" for e in entries):
        return "empty_or_missing_%s_for_%s" % (id_key, name)
    return ""


def label_wrangler(state: Dict[str, Any]) -> Dict[str, Any]:
    reasons = [r for r in (
        _has_binding(state, "d1_databases", "DB", "database_id"),
        _has_binding(state, "kv_namespaces", "CACHE", "id"),
        _has_binding(state, "r2_buckets", "ASSETS", "bucket_name"),
    ) if r]
    return {"label": "holds" if not reasons else "fails", "reasons": reasons}
