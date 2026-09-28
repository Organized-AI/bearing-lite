"""Pre-registered question formulations tried per rubric.

The list is fixed before any held-out number is looked at; nothing here is
edited in response to test-split results. `schema_ok` is False for a
formulation schemas/system1.schema.json cannot express (the rubric `question`
object admits only key/type/instructions/criteria, and a noul question may not
carry criteria), so such a formulation is measured as a diagnostic only and is
never eligible to be chosen.
"""
from __future__ import annotations

GTM_RULE = ('The state is one dataLayer push as JSON. Rule: it is a GA4 purchase event only if `event` equals '
            '"purchase" and `ecommerce` contains transaction_id, value, currency (a 3-letter ISO 4217 code), and an '
            'items array with at least one item that has item_id or item_name.')
GTM_TIGHT = ('The state is one dataLayer push as JSON. Check every condition: (1) the top-level `event` value is '
             'exactly "purchase"; (2) there is an `ecommerce` object; (3) ecommerce.transaction_id is present and '
             'not empty; (4) ecommerce.value is present; (5) ecommerce.currency is an uppercase 3-letter ISO 4217 '
             'currency code such as USD or EUR; (6) ecommerce.items is an array containing at least one item with '
             'item_id or item_name.')

WR_RULE = ('The state is the bindings section of a Cloudflare wrangler configuration as JSON. Rule: d1_databases has '
           'an entry with binding "DB" and a non-empty database_id; kv_namespaces has an entry with binding "CACHE" '
           'and a non-empty id; r2_buckets has an entry with binding "ASSETS" and a non-empty bucket_name.')
WR_TIGHT = ('The state is the bindings section of a Cloudflare wrangler configuration as JSON. Binding names are '
            'case-sensitive and must match exactly. Check every condition: (1) the d1_databases array contains an '
            'entry whose binding is exactly "DB" with a non-empty database_id; (2) the kv_namespaces array contains '
            'an entry whose binding is exactly "CACHE" with a non-empty id; (3) the r2_buckets array contains an '
            'entry whose binding is exactly "ASSETS" with a non-empty bucket_name.')

CONSENT_TIGHT = ('The state is the visible text of a website consent banner in any language. Look for three '
                 'disclosures: (1) purpose: why data or cookies are used, such as measurement, analytics or ads; '
                 '(2) third parties: that partners or other companies receive the data; (3) withdrawal: how the '
                 'visitor can refuse, reject or withdraw consent. Which option describes the text?')

FORMULATIONS = {
    "gtm-datalayer-event": {
        "noul_verbatim": {"checkpoint": "laya", "schema_ok": True, "question": {
            "key": "purchase_event_conforms", "type": "noul",
            "instructions": GTM_RULE + " Does this push satisfy every part of the rule?"}},
        "noul_tight": {"checkpoint": "laya", "schema_ok": True, "question": {
            "key": "purchase_event_conforms", "type": "noul",
            "instructions": GTM_TIGHT + " Do all six conditions hold?"}},
        "noul_neutral_labels": {"checkpoint": "laya", "schema_ok": False, "question": {
            "key": "purchase_event_conforms", "type": "noul",
            "instructions": GTM_RULE + " Does this push satisfy every part of the rule?",
            "labels": {"false": "B", "true": "A"}}},
        "choice2_neutral": {"checkpoint": "laya", "schema_ok": True, "question": {
            "key": "purchase_event_conforms", "type": "choice",
            "instructions": GTM_RULE + " Which option describes this push?",
            "criteria": {"A": "the push satisfies every part of the rule",
                         "B": "the push violates at least one part of the rule"}}},
        "choice2_tight": {"checkpoint": "laya", "schema_ok": True, "question": {
            "key": "purchase_event_conforms", "type": "choice",
            "instructions": GTM_TIGHT + " Which option describes this push?",
            "criteria": {"A": "all six conditions hold", "B": "at least one condition fails"}}},
        "typed_choice2_neutral": {"checkpoint": "laya-typed-decisions", "schema_ok": True, "question": {
            "key": "purchase_event_conforms", "type": "choice",
            "instructions": GTM_RULE + " Which option describes this push?",
            "criteria": {"A": "the push satisfies every part of the rule",
                         "B": "the push violates at least one part of the rule"}}},
    },
    "wrangler-bindings": {
        "noul_verbatim": {"checkpoint": "laya", "schema_ok": True, "question": {
            "key": "required_bindings_present", "type": "noul",
            "instructions": WR_RULE + " Does the configuration satisfy all three parts of the rule?"}},
        "noul_tight": {"checkpoint": "laya", "schema_ok": True, "question": {
            "key": "required_bindings_present", "type": "noul",
            "instructions": WR_TIGHT + " Do all three conditions hold?"}},
        "noul_neutral_labels": {"checkpoint": "laya", "schema_ok": False, "question": {
            "key": "required_bindings_present", "type": "noul",
            "instructions": WR_RULE + " Does the configuration satisfy all three parts of the rule?",
            "labels": {"false": "B", "true": "A"}}},
        "choice2_neutral": {"checkpoint": "laya", "schema_ok": True, "question": {
            "key": "required_bindings_present", "type": "choice",
            "instructions": WR_RULE + " Which option describes the configuration?",
            "criteria": {"A": "the configuration satisfies all three parts of the rule",
                         "B": "the configuration violates at least one part of the rule"}}},
        "choice2_tight": {"checkpoint": "laya", "schema_ok": True, "question": {
            "key": "required_bindings_present", "type": "choice",
            "instructions": WR_TIGHT + " Which option describes the configuration?",
            "criteria": {"A": "all three conditions hold", "B": "at least one condition fails"}}},
        "typed_choice2_neutral": {"checkpoint": "laya-typed-decisions", "schema_ok": True, "question": {
            "key": "required_bindings_present", "type": "choice",
            "instructions": WR_RULE + " Which option describes the configuration?",
            "criteria": {"A": "the configuration satisfies all three parts of the rule",
                         "B": "the configuration violates at least one part of the rule"}}},
    },
    "multilingual-consent-banner": {
        "choice3_verbatim": {"checkpoint": "laya-multilingual", "schema_ok": True, "question": {
            "key": "banner_disclosures", "type": "choice",
            "instructions": "The state is the visible text of a website consent banner in any language. Which option describes it?",
            "criteria": {
                "A": "it states the purpose of data collection, AND names third parties or partners who receive data, AND tells the visitor how to refuse or withdraw consent",
                "B": "it is a consent banner but at least one of those three disclosures is missing",
                "C": "it is not consent banner text"}}},
        "choice3_tight": {"checkpoint": "laya-multilingual", "schema_ok": True, "question": {
            "key": "banner_disclosures", "type": "choice",
            "instructions": CONSENT_TIGHT,
            "criteria": {
                "A": "a consent banner with all three disclosures: purpose, third parties, and how to refuse or withdraw",
                "B": "a consent banner missing at least one of the three disclosures",
                "C": "not a consent banner"}}},
        "choice2_neutral": {"checkpoint": "laya-multilingual", "schema_ok": True, "question": {
            "key": "banner_disclosures", "type": "choice",
            "instructions": "The state is the visible text of a website consent banner in any language. Which option describes it?",
            "criteria": {
                "A": "it states the purpose of data collection, AND names third parties or partners who receive data, AND tells the visitor how to refuse or withdraw consent",
                "B": "at least one of those three disclosures is missing"}}},
        "noul_tight": {"checkpoint": "laya-multilingual", "schema_ok": True, "question": {
            "key": "banner_disclosures", "type": "noul",
            "instructions": CONSENT_TIGHT.replace(" Which option describes the text?", " Does the text contain all three disclosures?")}},
    },
}

# Decision mapping per formulation type (the rubric's option sets).
def decision_sets(question):
    if question["type"] == "noul":
        return ["yes"], ["no"]
    return ["A"], ["B"]


def truth_key(rubric, question, label):
    """Map a labeler label to the option key that is correct for this question."""
    if rubric == "multilingual-consent-banner":
        if question["type"] == "noul":
            return "yes" if label == "A" else "no"
        if "C" not in question["criteria"]:
            return "A" if label == "A" else "B"
        return label
    holds = label == "holds"
    if question["type"] == "noul":
        return "yes" if holds else "no"
    return "A" if holds else "B"
