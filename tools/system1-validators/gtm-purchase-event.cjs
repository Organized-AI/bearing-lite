"use strict";

/**
 * Validator `gtm-purchase-event` (backend `validator`).
 *
 * Rule text (the six conditions of RUB-S1-GTM-DATALAYER-PURCHASE, decided
 * exactly instead of asked of a model):
 *   (1) the top-level `event` value is exactly "purchase";
 *   (2) there is an `ecommerce` object;
 *   (3) ecommerce.transaction_id is present and not empty;
 *   (4) ecommerce.value is present;
 *   (5) ecommerce.currency is an uppercase 3-letter ISO 4217 currency code;
 *   (6) ecommerce.items is an array containing at least one item with item_id
 *       or item_name.
 * "Present" means the key exists and its value is neither null nor "". The
 * currency must be a string equal to a code in ISO_4217 below (no trimming,
 * no case folding). A push that is not a JSON object fails (1)-(6).
 *
 * Input: one dataLayer push as a UTF-8 JSON document (the target file holds
 * exactly the push). Canonical form: RFC 8785 JCS of the parsed document.
 * Unparseable JSON is ERROR `input_unparseable`; every parsed JSON value is
 * inside the rule's domain, so this validator never returns INCONCLUSIVE.
 */

const { isPlainObject, hasOwn, jcs, parseJson, conditionDecision } = require("./lib.cjs");

const VALIDATOR_ID = "gtm-purchase-event";
const VALIDATOR_VERSION = "1.0.0";

const RULE_TEXT =
  'One dataLayer push conforms iff: (1) the top-level `event` value is exactly "purchase"; (2) there is an ' +
  "`ecommerce` object; (3) ecommerce.transaction_id is present and not empty; (4) ecommerce.value is present; " +
  "(5) ecommerce.currency is an uppercase 3-letter ISO 4217 currency code; (6) ecommerce.items is an array " +
  'containing at least one item (an object) with item_id or item_name. "Present" means the key exists and its ' +
  'value is neither null nor the empty string. The currency must be a string exactly equal to a code in the ' +
  "validator's pinned ISO 4217 list.";

/** Pinned ISO 4217 alphabetic codes (active national currencies; same list as labelers.py). */
const ISO_4217 = new Set(
  `AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD
   CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD
   GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT
   LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR
   NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP
   STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VED VES VND VUV WST XAF XCD
   XCG XOF XPF YER ZAR ZMW ZWG ZWL`.split(/\s+/)
);

/** Conditions in evaluation order; `holds: null` = not evaluated because a prerequisite failed. */
const CONDITIONS = Object.freeze([
  { id: "push_is_object", text: "The push is a JSON object." },
  { id: "event_is_purchase", text: '(1) The top-level `event` value is exactly "purchase".' },
  { id: "ecommerce_is_object", text: "(2) `ecommerce` is a JSON object." },
  { id: "transaction_id_present", text: "(3) ecommerce.transaction_id is present (not null, not \"\")." },
  { id: "value_present", text: "(4) ecommerce.value is present (not null, not \"\")." },
  { id: "currency_present", text: "(5) ecommerce.currency is present (not null, not \"\")." },
  { id: "currency_is_iso4217", text: "(5) ecommerce.currency is a string in the pinned ISO 4217 list (evaluated when present)." },
  { id: "items_is_array", text: "(6) ecommerce.items is an array." },
  { id: "items_nonempty", text: "(6) ecommerce.items has at least one element (evaluated when it is an array)." },
  {
    id: "items_has_identified_item",
    text: "(6) some element of ecommerce.items is an object with item_id or item_name present (evaluated when non-empty).",
  },
]);

const present = (obj, key) => hasOwn(obj, key) && obj[key] !== null && obj[key] !== "";

/** Decide the rule for one parsed push. */
function evaluatePush(push) {
  if (!isPlainObject(push)) {
    return conditionDecision(CONDITIONS.map((c) => [c.id, c.id === "push_is_object" ? false : null]));
  }
  const pairs = [
    ["push_is_object", true],
    ["event_is_purchase", push.event === "purchase"],
  ];
  const ec = hasOwn(push, "ecommerce") ? push.ecommerce : undefined;
  if (!isPlainObject(ec)) {
    pairs.push(["ecommerce_is_object", false]);
    for (const c of CONDITIONS.slice(3)) pairs.push([c.id, null]);
    return conditionDecision(pairs);
  }
  pairs.push(["ecommerce_is_object", true]);
  pairs.push(["transaction_id_present", present(ec, "transaction_id")]);
  pairs.push(["value_present", present(ec, "value")]);
  const hasCurrency = present(ec, "currency");
  pairs.push(["currency_present", hasCurrency]);
  pairs.push(["currency_is_iso4217", hasCurrency ? typeof ec.currency === "string" && ISO_4217.has(ec.currency) : null]);
  const items = hasOwn(ec, "items") ? ec.items : undefined;
  const isArray = Array.isArray(items);
  pairs.push(["items_is_array", isArray]);
  const nonempty = isArray ? items.length > 0 : null;
  pairs.push(["items_nonempty", nonempty]);
  pairs.push([
    "items_has_identified_item",
    nonempty ? items.some((it) => isPlainObject(it) && (present(it, "item_id") || present(it, "item_name"))) : null,
  ]);
  return conditionDecision(pairs);
}

/**
 * Parse and canonicalize the input text. Throws InputError on unparseable input.
 * @param {string} text
 * @returns {{ format: string, canonical: string, state: unknown }}
 */
function canonicalize(text) {
  const state = parseJson(text);
  return { format: "json", canonical: jcs(state), state };
}

module.exports = {
  VALIDATOR_ID,
  VALIDATOR_VERSION,
  RULE_TEXT,
  CONDITIONS,
  ISO_4217,
  FORMATS: Object.freeze(["json"]),
  canonicalize,
  evaluate: evaluatePush,
};
