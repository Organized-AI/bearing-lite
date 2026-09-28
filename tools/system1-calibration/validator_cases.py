"""Edge-case agreement fixtures for the `validator` backend, labeled by the Python side.

    python3 tools/system1-calibration/validator_cases.py

Writes test/fixtures/system1-validators/cases.json. Every expectation comes from
this repository's independent Python implementations, never from the Node
validators under test:

  * gtm: labelers.label_gtm on the parsed push (label and reasons);
  * wrangler: tomllib or s1cal.parse_jsonc, then s1cal.extract_bindings and
    labelers.label_wrangler (label, reasons, and the SHA-256 of the RFC 8785
    canonical bindings state);
  * toml: tomllib's result as RFC 8785 JCS, or "invalid" when tomllib rejects
    the text ("valid" for a case outside the subset). `subset` records whether the case is inside the reader subset
    documented in tools/system1-validators/toml.cjs; a valid-TOML case outside
    it must be ERROR toml_unsupported_construct, never a parsed value.

test/system1-validators.test.mjs requires the Node validators to agree with
every case, in addition to the 360-item calibration datasets.
"""
from __future__ import annotations

import json
import os
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1cal  # noqa: E402
from labelers import label_gtm, label_wrangler  # noqa: E402

OUT = os.path.join(s1cal.ROOT, "test", "fixtures", "system1-validators", "cases.json")

_OK_ITEM = {"item_id": "SKU_1", "item_name": "Hoodie"}


def _push(**ec_over):
    ec = {"transaction_id": "T-1", "value": 10, "currency": "EUR", "items": [_OK_ITEM]}
    for k, v in ec_over.items():
        if v is _DROP:
            ec.pop(k)
        else:
            ec[k] = v
    return {"event": "purchase", "ecommerce": ec}


_DROP = object()

GTM = {
    "valid_minimal": _push(),
    "valid_value_zero": _push(value=0),
    "valid_value_false": _push(value=False),
    "valid_transaction_id_zero": _push(transaction_id=0),
    "valid_item_name_only": _push(items=[{"item_name": "Hoodie"}]),
    "valid_second_item_identified": _push(items=[{"quantity": 1}, {"item_id": "SKU_2"}]),
    "valid_ved": _push(currency="VED"),
    "valid_zwg": _push(currency="ZWG"),
    "valid_xcg": _push(currency="XCG"),
    "valid_extra_top_level_keys": {**_push(), "gtm.uniqueEventId": 7, "user_id": None},
    "event_trailing_space": {**_push(), "event": "purchase "},
    "event_uppercase": {**_push(), "event": "PURCHASE"},
    "event_missing": {"ecommerce": _push()["ecommerce"]},
    "event_null": {**_push(), "event": None},
    "ecommerce_null": {"event": "purchase", "ecommerce": None},
    "ecommerce_array": {"event": "purchase", "ecommerce": [_push()["ecommerce"]]},
    "transaction_id_null": _push(transaction_id=None),
    "transaction_id_empty": _push(transaction_id=""),
    "value_empty_string": _push(value=""),
    "value_missing": _push(value=_DROP),
    "currency_null": _push(currency=None),
    "currency_empty": _push(currency=""),
    "currency_number": _push(currency=978),
    "currency_lowercase": _push(currency="eur"),
    "currency_padded": _push(currency=" EUR"),
    "currency_not_a_code": _push(currency="EURO"),
    "currency_list": _push(currency=["EUR"]),
    "items_missing": _push(items=_DROP),
    "items_null": _push(items=None),
    "items_object": _push(items=_OK_ITEM),
    "items_empty": _push(items=[]),
    "items_only_nulls": _push(items=[None, "SKU_1"]),
    "items_nested_array": _push(items=[[_OK_ITEM]]),
    "items_empty_ids": _push(items=[{"item_id": "", "item_name": None}]),
    "everything_wrong": {"event": "add_to_cart", "ecommerce": {"currency": "usd", "items": []}},
    "push_is_array": [_push()],
    "push_is_string": "purchase",
    "push_is_null": None,
}

WRANGLER_JSONC = {
    "all_bound_with_comments": """{
  // required bindings
  "name": "w",
  "d1_databases": [{ "binding": "DB", "database_name": "d", "database_id": "abc" },],
  /* kv */ "kv_namespaces": [{ "binding": "CACHE", "id": "k" }],
  "r2_buckets": [{ "binding": "ASSETS", "bucket_name": "b" }],
}
""",
    "db_id_number": '{"d1_databases":[{"binding":"DB","database_id":123}],"kv_namespaces":[{"binding":"CACHE","id":"k"}],"r2_buckets":[{"binding":"ASSETS","bucket_name":"b"}]}',
    "second_db_entry_has_id": '{"d1_databases":[{"binding":"DB","database_id":""},{"binding":"DB","database_id":"x"}],"kv_namespaces":[{"binding":"CACHE","id":"k"}],"r2_buckets":[{"binding":"ASSETS","bucket_name":"b"}]}',
    "entries_not_objects": '{"d1_databases":["DB"],"kv_namespaces":[null,{"binding":"CACHE","id":"k"}],"r2_buckets":[{"binding":"ASSETS","bucket_name":"b"}]}',
    "arrays_are_objects": '{"d1_databases":{"binding":"DB","database_id":"x"},"kv_namespaces":[{"binding":"CACHE","id":"k"}],"r2_buckets":[{"binding":"ASSETS","bucket_name":"b"}]}',
    "binding_case": '{"d1_databases":[{"binding":"db","database_id":"x"}],"kv_namespaces":[{"binding":"Cache","id":"k"}],"r2_buckets":[{"binding":"ASSETS","bucket_name":"b"}]}',
    "only_under_env": '{"env":{"production":{"d1_databases":[{"binding":"DB","database_id":"x"}],"kv_namespaces":[{"binding":"CACHE","id":"k"}],"r2_buckets":[{"binding":"ASSETS","bucket_name":"b"}]}}}',
    "empty_object": "{}",
}

WRANGLER_TOML = {
    "inline_tables": """name = "w"
main = "src/index.ts"
compatibility_flags = ["nodejs_compat"]  # flags
d1_databases = [ { binding = "DB", database_name = "d", database_id = "abc" } ]
kv_namespaces = [
  { binding = "CACHE", id = "k" },   # trailing comma follows
]
r2_buckets = [{ binding = 'ASSETS', bucket_name = 'b' }]
""",
    "arrays_of_tables_with_env": """name = "w"
[vars]
API_HOST = "example.com"

[[d1_databases]]
binding = "DB"
database_name = "d"
database_id = "abc"

[[kv_namespaces]]
binding = "CACHE"
id = "k"

[[r2_buckets]]
binding = "ASSETS"
bucket_name = "b"

[env.production]
name = "w-prod"

[[env.production.kv_namespaces]]
binding = "CACHE"
id = "prod"
""",
    "only_under_env_toml": """name = "w"
[[env.staging.d1_databases]]
binding = "DB"
database_id = "abc"
[[env.staging.kv_namespaces]]
binding = "CACHE"
id = "k"
[[env.staging.r2_buckets]]
binding = "ASSETS"
bucket_name = "b"
""",
    "quoted_keys_and_escapes": """"name" = "w\\u00e9"
[["d1_databases"]]
"binding" = "DB"
database_id = "a\\tb"
[[kv_namespaces]]
binding = "CACHE"
id = ""
[[r2_buckets]]
binding = "ASSETS"
bucket_name = "b"
""",
    "numbers_and_booleans": """workers_dev = true
usage_model = "standard"
[limits]
cpu_ms = 50_000
[placement]
mode = "smart"
[[d1_databases]]
binding = "DB"
database_id = "x"
migrations_dir = "migrations"
[[kv_namespaces]]
binding = "CACHE"
id = "k"
[[r2_buckets]]
binding = "ASSETS"
bucket_name = "b"
""",
}

# TOML reader cases: (name, text, subset) where subset is "supported" or "unsupported".
TOML = [
    ("comment_only", "# nothing\n", "supported"),
    ("empty", "", "supported"),
    ("crlf", 'a = "x"\r\n[t]\r\nb = 1\r\n', "supported"),
    ("dotted_keys", 'site.bucket = "./public"\nsite.include = ["*.html"]\n', "supported"),
    ("dotted_header", '[env.staging.vars]\nX = "1"\n', "supported"),
    ("nested_inline", 'a = { b = { c = [1, 2.5, -3, +4, 1e3, 6.02E-2] } }\n', "supported"),
    ("literal_string_backslash", "p = 'C:\\\\path\\\\x'\n", "supported"),
    ("unicode_escapes", 'u = "\\u00e9\\U0001F600"\n', "supported"),
    ("array_multiline_comments", 'a = [\n  "x", # one\n  "y",\n  # gap\n]\n', "supported"),
    ("array_of_tables_then_subtable", '[[a]]\nx = 1\n[a.b]\ny = 2\n[[a]]\nx = 3\n', "supported"),
    ("int_underscore", "n = 1_000_000\n", "supported"),
    ("negative_zero", "n = -0\n", "supported"),
    ("bool_and_float", "t = true\nf = false\nx = 0.5\n", "supported"),
    ("bom", '\ufeffa = "x"\n', "supported"),
    ("empty_inline_table", "t = {}\n", "supported"),
    ("bare_key_digits", '1234 = "n"\n', "supported"),
    ("multiline_basic", 'a = """\nline\n"""\n', "unsupported"),
    ("multiline_literal", "a = '''\nline\n'''\n", "unsupported"),
    ("offset_datetime", "d = 1979-05-27T07:32:00Z\n", "unsupported"),
    ("local_date", "d = 1979-05-27\n", "unsupported"),
    ("local_time", "t = 07:32:00\n", "unsupported"),
    ("hex_int", "h = 0xDEAD\n", "unsupported"),
    ("oct_int", "o = 0o755\n", "unsupported"),
    ("bin_int", "b = 0b1101\n", "unsupported"),
    ("inf", "x = inf\n", "unsupported"),
    ("neg_nan", "x = -nan\n", "unsupported"),
    ("huge_int", "x = 9007199254740993\n", "unsupported"),
    ("duplicate_key", 'a = 1\na = 2\n', "supported"),
    ("duplicate_table", "[t]\n[t]\n", "supported"),
    ("table_over_value", 'a = 1\n[a]\n', "supported"),
    ("missing_value", "a =\n", "supported"),
    ("bad_escape", 'a = "\\q"\n', "supported"),
    ("unterminated_string", 'a = "x\n', "supported"),
    ("leading_zero", "a = 01\n", "supported"),
    ("inline_table_trailing_comma", "a = { b = 1, }\n", "supported"),
    ("inline_table_extended", "a = { b = 1 }\n[a.c]\nd = 2\n", "supported"),
    ("header_reopens_dotted", "[t]\nx.y = 1\n[t.x]\nz = 2\n", "supported"),
    ("value_then_garbage", 'a = "x" b\n', "supported"),
    ("array_of_tables_over_static_array", "a = [1]\n[[a]]\n", "supported"),
    ("header_trailing_comment", "[t] # c\nx = 1\n", "supported"),
]


def _reasons_label(fn, value):
    lab = fn(value)
    return lab["label"], lab["reasons"]


def main():
    cases = {"gtm": [], "wrangler": [], "toml": []}
    for name, push in GTM.items():
        text = json.dumps(push, ensure_ascii=False)
        label, reasons = _reasons_label(label_gtm, json.loads(text))
        cases["gtm"].append({"name": name, "text": text, "label": label, "reasons": reasons})
    for fmt, table in (("jsonc", WRANGLER_JSONC), ("toml", WRANGLER_TOML)):
        for name, source in table.items():
            parsed = tomllib.loads(source) if fmt == "toml" else s1cal.parse_jsonc(source)
            state = s1cal.jcs(s1cal.extract_bindings(parsed))
            label, reasons = _reasons_label(label_wrangler, json.loads(state))
            cases["wrangler"].append({"name": name, "format": fmt, "source": source, "label": label,
                                      "reasons": reasons, "state_digest": s1cal.sha256_text(state)})
    for name, text, subset in TOML:
        try:
            doc = tomllib.loads(text)
            # Unsupported cases may hold values with no JSON form (dates); only their validity is recorded.
            parsed = "valid" if subset == "unsupported" else s1cal.jcs(doc)
        except tomllib.TOMLDecodeError:
            parsed = "invalid"
        assert not (subset == "unsupported" and parsed == "invalid"), name + ": unsupported cases must be valid TOML"
        cases["toml"].append({"name": name, "text": text, "tomllib": parsed, "subset": subset})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(cases, indent=1, ensure_ascii=False) + "\n")
    print("gtm %d, wrangler %d, toml %d -> %s" % (len(cases["gtm"]), len(cases["wrangler"]), len(cases["toml"]),
                                                  os.path.relpath(OUT, s1cal.ROOT)))


if __name__ == "__main__":
    main()
