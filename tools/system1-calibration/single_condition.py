"""Single-condition Laya rubrics: one question per required consent disclosure,
plus one GTM demonstration question, calibrated with the protocol of
docs/calibration/system1-calibration-report.md.

    python tools/system1-calibration/single_condition.py generate      # datasets + controls (tokenizers only)
    python tools/system1-calibration/single_condition.py run           # score every formulation (model)
    python tools/system1-calibration/single_condition.py evaluate      # fit T, choose, metrics (no model)
    python tools/system1-calibration/single_condition.py replay [N]    # N fresh-process control replays (model)
    python tools/system1-calibration/single_condition.py rubrics       # write the rubric files (no model)
    python tools/system1-calibration/single_condition.py report        # markdown tables for the report

Why: the multi-condition consent rubric (RUB-S1-CONSENT-BANNER-DISCLOSURES)
scored at chance. The rule is a conjunction of three disclosures, so it is
decomposed into three rubrics that each ask one thing, and the claim holds when
all three receipts VERIFY. The GTM question ("is the event exactly purchase")
is a demonstration of where Laya works; the selection guide routes that check to
the `validator` backend, which decides it exactly.

Protocol, fixed before any held-out number was read:
  * consent: 512 banners from the consent generator's segment model, each
    disclosure present independently, so every (purpose, third parties,
    withdrawal) combination appears equally often (8 combinations x 8 languages
    x 4 per split). Each disclosure is balanced 128/128 in each split. The split
    is paraphrase-disjoint: the calibration split uses the generator's original
    three paraphrases per disclosure and language, the held-out split uses two
    new ones (NEW_PARAPHRASES), so held-out wording is unseen during selection
    and temperature fitting;
  * gtm-event: 360 pushes, half `purchase`, half other GA4 events and near-miss
    spellings, split 50/50 stratified by label (seed s1cal.SPLIT_SEED);
  * the formulation is chosen on the calibration split only: highest accuracy,
    then lowest NLL at its fitted temperature. Consent formulations were
    registered in two stages (STAGE2, after stage 1 failed on the calibration
    split); the choice spans both stages and still reads only the calibration
    split;
  * T is fitted on the calibration split (s1cal.fit_temperature);
  * held-out accuracy, ECE (raw, shipped, fitted), and coverage/precision at the
    rubric thresholds (verify/refute 0.85 for consent, the original consent
    rubric's; 0.90 for GTM, the original GTM rubric's) are reported;
  * assurance_eligible iff held-out gated precision >= 0.95 with a Wilson 95%
    lower bound >= 0.90, every control on its expected status at the fitted T
    in every replay run, and measured ECE (worse of calibration and held-out)
    <= max_ece.
"""
from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1cal  # noqa: E402
from generate import CONSENT, SENT_SEP, _valid_purchase  # noqa: E402
from labelers import label_consent  # noqa: E402

FIX = os.path.join(s1cal.FIXTURES, "single-condition")
RUNTIME = {"laya": (512, 192), "laya-multilingual": (1024, 256)}
DISCLOSURES = ("purpose", "third_parties", "withdrawal")
PRECISION_BAR, WILSON_BAR = 0.95, 0.90

# Two new paraphrases per disclosure and language, used only in the held-out split.
NEW_PARAPHRASES = {
    "en": {
        "purpose": ["These cookies record which products you view so that we can improve our shop and tailor offers to you.",
                    "We store small files on your device to count visits, see which content is popular and show you personalised promotions."],
        "third_parties": ["Partner companies, for example Microsoft and TikTok, also receive details of your visit.",
                          "This information is disclosed to external service providers, who also process it for their own purposes."],
        "withdrawal": ["Changed your mind? You can revoke your consent whenever you like under \"Privacy preferences\".",
                       "You are free to say no: choose \"Only necessary cookies\", and you can switch tracking off again at any time."],
    },
    "de": {
        "purpose": ["Diese Cookies speichern, welche Produkte Sie ansehen, damit wir unseren Shop verbessern und Angebote auf Sie zuschneiden können.",
                    "Wir legen kleine Dateien auf Ihrem Gerät ab, um Besuche zu zählen, beliebte Inhalte zu erkennen und Ihnen persönliche Aktionen zu zeigen."],
        "third_parties": ["Partnerunternehmen, zum Beispiel Microsoft und TikTok, erhalten ebenfalls Angaben zu Ihrem Besuch.",
                          "Diese Informationen werden an externe Dienstleister übermittelt, die sie auch für eigene Zwecke verarbeiten."],
        "withdrawal": ["Meinung geändert? Sie können Ihre Einwilligung jederzeit unter „Datenschutzeinstellungen“ zurücknehmen.",
                       "Sie müssen nicht zustimmen: Wählen Sie „Nur notwendige Cookies“, und Sie können das Tracking jederzeit wieder abschalten."],
    },
    "fr": {
        "purpose": ["Ces cookies enregistrent les produits que vous consultez afin que nous puissions améliorer notre boutique et adapter nos offres à vos goûts.",
                    "Nous déposons de petits fichiers sur votre appareil pour compter les visites, repérer les contenus populaires et vous montrer des promotions personnalisées."],
        "third_parties": ["Des sociétés partenaires, par exemple Microsoft et TikTok, reçoivent également des informations sur votre visite.",
                          "Ces informations sont communiquées à des prestataires externes, qui les traitent aussi pour leur propre compte."],
        "withdrawal": ["Vous avez changé d'avis ? Vous pouvez révoquer votre consentement quand vous le souhaitez dans « Préférences de confidentialité ».",
                       "Vous êtes libre de dire non : choisissez « Cookies nécessaires uniquement », et vous pourrez désactiver le suivi à tout moment."],
    },
    "es": {
        "purpose": ["Estas cookies registran los productos que consulta para que podamos mejorar nuestra tienda y adaptar las ofertas a usted.",
                    "Guardamos pequeños archivos en su dispositivo para contar las visitas, saber qué contenidos gustan más y mostrarle promociones personalizadas."],
        "third_parties": ["Empresas asociadas, por ejemplo Microsoft y TikTok, también reciben datos sobre su visita.",
                          "Esta información se comunica a proveedores externos, que también la tratan para sus propios fines."],
        "withdrawal": ["¿Ha cambiado de opinión? Puede revocar su consentimiento cuando quiera en «Preferencias de privacidad».",
                       "Es libre de decir que no: elija «Solo cookies necesarias» y podrá desactivar el seguimiento en cualquier momento."],
    },
    "it": {
        "purpose": ["Questi cookie registrano i prodotti che visualizzi, così possiamo migliorare il nostro negozio e adattare le offerte a te.",
                    "Salviamo piccoli file sul tuo dispositivo per contare le visite, capire quali contenuti piacciono di più e mostrarti promozioni personalizzate."],
        "third_parties": ["Anche aziende partner, ad esempio Microsoft e TikTok, ricevono informazioni sulla tua visita.",
                          "Queste informazioni vengono comunicate a fornitori esterni, che le trattano anche per scopi propri."],
        "withdrawal": ["Hai cambiato idea? Puoi revocare il consenso quando vuoi da «Preferenze privacy».",
                       "Sei libero di dire di no: scegli «Solo cookie necessari» e potrai disattivare il tracciamento in qualsiasi momento."],
    },
    "pt": {
        "purpose": ["Estes cookies registam os produtos que consulta para podermos melhorar a nossa loja e adaptar as ofertas a si.",
                    "Guardamos pequenos ficheiros no seu dispositivo para contar visitas, perceber que conteúdos são mais populares e mostrar-lhe promoções personalizadas."],
        "third_parties": ["Empresas parceiras, por exemplo a Microsoft e o TikTok, também recebem dados sobre a sua visita.",
                          "Estas informações são comunicadas a prestadores de serviços externos, que também as tratam para fins próprios."],
        "withdrawal": ["Mudou de ideias? Pode revogar o seu consentimento quando quiser em «Preferências de privacidade».",
                       "É livre de dizer que não: escolha «Apenas cookies necessários» e poderá desativar o rastreamento a qualquer momento."],
    },
    "nl": {
        "purpose": ["Deze cookies houden bij welke producten u bekijkt, zodat wij onze winkel kunnen verbeteren en aanbiedingen op u kunnen afstemmen.",
                    "Wij plaatsen kleine bestanden op uw apparaat om bezoeken te tellen, te zien welke inhoud populair is en u persoonlijke acties te tonen."],
        "third_parties": ["Ook partnerbedrijven, zoals Microsoft en TikTok, ontvangen gegevens over uw bezoek.",
                          "Deze informatie wordt verstrekt aan externe dienstverleners, die haar ook voor eigen doeleinden verwerken."],
        "withdrawal": ["Van gedachten veranderd? U kunt uw toestemming altijd intrekken via 'Privacyvoorkeuren'.",
                       "U mag nee zeggen: kies 'Alleen noodzakelijke cookies', en u kunt tracking op elk moment weer uitschakelen."],
    },
    "ja": {
        "purpose": ["これらのCookieは閲覧した商品を記録し、ストアの改善やお客様に合わせたご提案に役立てます。",
                    "訪問数の集計や人気コンテンツの把握、パーソナライズされたキャンペーンの表示のため、お客様の端末に小さなファイルを保存します。"],
        "third_parties": ["MicrosoftやTikTokなどのパートナー企業も、お客様の訪問に関する情報を受け取ります。",
                          "この情報は外部のサービス事業者に開示され、各事業者が独自の目的でも利用します。"],
        "withdrawal": ["気が変わった場合は、「プライバシー設定」からいつでも同意を取り消せます。",
                       "同意は任意です。「必要なCookieのみ」を選択でき、トラッキングはいつでも無効にできます。"],
    },
}

PREAMBLE = "The state is the visible text of a website cookie or consent notice, in any language."
DISCLOSURE_TEXT = {
    "purpose": ("Does the text state why data or cookies are used, for example to measure visits, analyse traffic, "
                "personalise content or show advertising?",
                "it states why data or cookies are used (for example measurement, analytics, personalisation or advertising)",
                "it does not state why data or cookies are used"),
    "third_parties": ("Does the text say that the data is shared with, passed to, or received by third parties, "
                      "partners or other companies?",
                      "it says the data is shared with or received by third parties, partners or other companies",
                      "it does not say that anyone else receives the data"),
    "withdrawal": ("Does the text tell the visitor that they can refuse, reject or withdraw consent, or how to do so?",
                   "it tells the visitor they can refuse, reject or withdraw consent",
                   "it does not tell the visitor how to refuse or withdraw consent"),
}

# Stage 2, registered after stage 1 (noul, choice2_neutral) failed on the calibration split for purpose and
# third parties (calibration accuracy 0.50-0.65; their held-out numbers had been computed too, see the report).
# Selection over all four formulations still uses the calibration split only.
STAGE2 = {
    "purpose": ("names a use of the data or cookies (measuring visits, analysing traffic, improving the service, "
                "personalising content or ads)",
                "yes: it names at least one use of the data or cookies",
                "no: it names no use of the data or cookies",
                "Does the text contain a sentence that says what the cookies or data are used for, such as measuring "
                "visits, analytics, personalisation or advertising?"),
    "third_parties": ("says that other companies, partners or third parties receive or are passed the data",
                      "yes: it says other companies, partners or third parties receive the data",
                      "no: it never says that anyone other than the website receives the data",
                      "Does the text contain a sentence that says the data is shared with, passed to or received by "
                      "other companies, partners or third parties?"),
    "withdrawal": ("tells the visitor they can refuse, reject, decline or withdraw consent",
                   "yes: it says the visitor can refuse, reject, decline or withdraw consent",
                   "no: it gives no way to refuse, reject, decline or withdraw consent",
                   "Does the text contain a sentence that tells the visitor they can refuse, reject, decline or "
                   "withdraw consent?"),
}
STAGE2_NOTE = ("Accept buttons, titles, other disclosures and a link to a privacy policy do not count.")

GTM_PRE = "The state is one dataLayer push as JSON."

# ------------------------------------------------------------------ rubrics under calibration

RUBRICS = {
    "consent-purpose": {
        "file": "laya-consent-purpose.rubric.json", "rubric_id": "RUB-S1-CONSENT-STATES-PURPOSE",
        "title": "Localized consent banner states the purpose of data collection",
        "claim_type": "localized_copy_disclosure", "disclosure": "purpose",
        "statement": "The rendered consent banner text for the locale states what data is collected or why it is used.",
        "checkpoint": "laya-multilingual", "thresholds": (0.85, 0.85, 0.12), "key": "states_purpose",
    },
    "consent-third-parties": {
        "file": "laya-consent-third-parties.rubric.json", "rubric_id": "RUB-S1-CONSENT-NAMES-THIRD-PARTIES",
        "title": "Localized consent banner says third parties receive the data",
        "claim_type": "localized_copy_disclosure", "disclosure": "third_parties",
        "statement": "The rendered consent banner text for the locale states that third parties, such as analytics or advertising partners, receive the data.",
        "checkpoint": "laya-multilingual", "thresholds": (0.85, 0.85, 0.12), "key": "names_third_parties",
    },
    "consent-withdrawal": {
        "file": "laya-consent-withdrawal.rubric.json", "rubric_id": "RUB-S1-CONSENT-EXPLAINS-WITHDRAWAL",
        "title": "Localized consent banner tells the visitor how to refuse or withdraw consent",
        "claim_type": "localized_copy_disclosure", "disclosure": "withdrawal",
        "statement": "The rendered consent banner text for the locale tells the visitor how to refuse or withdraw consent.",
        "checkpoint": "laya-multilingual", "thresholds": (0.85, 0.85, 0.12), "key": "explains_withdrawal",
    },
    "gtm-event-is-purchase": {
        "file": "laya-gtm-event-is-purchase.rubric.json", "rubric_id": "RUB-S1-GTM-EVENT-IS-PURCHASE",
        "title": "dataLayer push is a GA4 purchase event (single condition, demonstration)",
        "claim_type": "tracking_event_classification",
        "statement": "The dataLayer push captured for the checkout-complete step is a GA4 `purchase` event (its `event` is exactly \"purchase\").",
        "checkpoint": "laya", "thresholds": (0.90, 0.90, 0.10), "key": "event_is_purchase",
    },
}


def formulations(rubric):
    """Pre-registered formulations per rubric: {name: question}."""
    spec = RUBRICS[rubric]
    if "disclosure" in spec:
        noul_q, a, b = DISCLOSURE_TEXT[spec["disclosure"]]
        x, a2, b2, noul2 = STAGE2[spec["disclosure"]]
        return {
            "noul": {"key": spec["key"], "type": "noul", "instructions": PREAMBLE + " " + noul_q},
            "choice2_neutral": {"key": spec["key"], "type": "choice",
                                "instructions": PREAMBLE + " Which option describes the text?",
                                "criteria": {"A": a, "B": b}},
            # stage 2
            "choice2_contrastive": {"key": spec["key"], "type": "choice",
                                    "instructions": PREAMBLE + " Consider only whether it " + x + ". " + STAGE2_NOTE +
                                    " Which option describes the text?",
                                    "criteria": {"A": a2, "B": b2}},
            "noul_sentence": {"key": spec["key"], "type": "noul",
                              "instructions": PREAMBLE + " " + STAGE2_NOTE + " " + noul2},
        }
    return {
        "noul": {"key": spec["key"], "type": "noul",
                 "instructions": GTM_PRE + ' Is the value of its top-level `event` field exactly "purchase"?'},
        "choice2_neutral": {"key": spec["key"], "type": "choice",
                            "instructions": GTM_PRE + " Which option describes the value of its top-level `event` field?",
                            "criteria": {"A": "exactly purchase", "B": "any other value"}},
        "choice5_events": {"key": spec["key"], "type": "choice",
                           "instructions": GTM_PRE + " Which GA4 event is it?",
                           "criteria": {"A": "purchase", "B": "add_to_cart", "C": "begin_checkout", "D": "view_item",
                                        "E": "another event"}},
    }


def decision_sets(question):
    if question["type"] == "noul":
        return ["yes"], ["no"]
    return ["A"], [k for k in question["criteria"] if k != "A"]


GTM_EVENT_KEY = {"purchase": "A", "add_to_cart": "B", "begin_checkout": "C", "view_item": "D"}


def truth_key(question, row):
    holds = row["label"] == "holds"
    if question["type"] == "noul":
        return "yes" if holds else "no"
    if "E" in question["criteria"]:
        return GTM_EVENT_KEY.get(row["event"], "E")
    return "A" if holds else "B"


# ------------------------------------------------------------------ controls

CONSENT_CONTROLS = {
    # Existing control fixtures (tools/system1-calibration/controls.py) plus two new ones.
    "CTL-CONSENT-DE-COMPLETE": ("test/fixtures/consent/controls/de-complete.txt", None),
    "CTL-CONSENT-ES-NO-WITHDRAW": ("test/fixtures/consent/controls/es-missing-withdrawal.txt", None),
    "CTL-CONSENT-JA-NO-THIRD-PARTY": ("test/fixtures/consent/controls/ja-missing-third-parties.txt", None),
    "CTL-CONSENT-FR-NO-PURPOSE": ("test/fixtures/consent/controls/fr-missing-purpose.txt", {
        "lang": "fr", "is_banner": True, "segments": [
            {"kind": "filler", "text": "Gestion des cookies"},
            {"kind": "third_parties", "text": "Certaines informations sur votre navigation sont transmises à nos partenaires, notamment Google."},
            {"kind": "withdrawal", "text": "Vous pouvez à tout moment refuser ou retirer votre accord depuis la page « Mes choix »."},
            {"kind": "filler", "text": "[J'accepte]"}]}),
    "CTL-CONSENT-EN-SHOP-NOTICE": ("test/fixtures/consent/controls/en-shop-notice.txt", {
        "lang": "en", "is_banner": False, "segments": [
            {"kind": "other", "text": "Our summer sale ends on Sunday. Returns are free within 30 days of delivery."},
            {"kind": "filler", "text": "[Shop now]"}]}),
}
RUBRIC_CONTROLS = {
    "consent-purpose": [("CTL-CONSENT-DE-COMPLETE", "VERIFIED"), ("CTL-CONSENT-FR-NO-PURPOSE", "REFUTED"),
                        ("CTL-CONSENT-EN-SHOP-NOTICE", "REFUTED")],
    "consent-third-parties": [("CTL-CONSENT-DE-COMPLETE", "VERIFIED"), ("CTL-CONSENT-ES-NO-WITHDRAW", "VERIFIED"),
                              ("CTL-CONSENT-JA-NO-THIRD-PARTY", "REFUTED")],
    "consent-withdrawal": [("CTL-CONSENT-DE-COMPLETE", "VERIFIED"), ("CTL-CONSENT-JA-NO-THIRD-PARTY", "VERIFIED"),
                           ("CTL-CONSENT-ES-NO-WITHDRAW", "REFUTED")],
    "gtm-event-is-purchase": [("CTL-GTM-PURCHASE-VALID", "VERIFIED"), ("CTL-GTM-PURCHASE-NO-CURRENCY", "VERIFIED"),
                              ("CTL-GTM-ADD-TO-CART", "REFUTED")],
}
GTM_CONTROLS = {
    "CTL-GTM-PURCHASE-VALID": "test/fixtures/datalayer/controls/purchase-valid.json",
    "CTL-GTM-PURCHASE-NO-CURRENCY": "test/fixtures/datalayer/controls/purchase-missing-currency.json",
    "CTL-GTM-ADD-TO-CART": "test/fixtures/datalayer/controls/add-to-cart.json",
}


def _assemble(lang, segs, is_banner):
    parts = [s["text"] for s in segs]
    if is_banner:
        return s1cal.canonical_text(parts[0] + "\n" + SENT_SEP.get(lang, " ").join(parts[1:-1]) + "\n" + parts[-1])
    return s1cal.canonical_text("\n".join(parts))


def controls(rubric):
    """[{control_id, locator, expected, state, input_digest}]; expected statuses are certified by the labeler."""
    out = []
    for cid, expected in RUBRIC_CONTROLS[rubric]:
        if rubric.startswith("consent"):
            loc, content = CONSENT_CONTROLS[cid]
            path = os.path.join(s1cal.ROOT, loc)
            if content is not None:
                state = _assemble(content["lang"], content["segments"], content["is_banner"])
                truth = label_consent(content)["disclosures"][RUBRICS[rubric]["disclosure"]] and content["is_banner"]
            else:
                state = open(path, encoding="utf-8").read()
                truth = None  # the original controls: truth from controls.py's segment model
                import controls as legacy
                meta = {c[0]: c[3] for c in legacy.CONTROLS["multilingual-consent-banner"]}[cid]
                truth = label_consent(meta)["disclosures"][RUBRICS[rubric]["disclosure"]]
                assert legacy._state("multilingual-consent-banner", meta) == state
        else:
            loc = GTM_CONTROLS[cid]
            state = open(os.path.join(s1cal.ROOT, loc), encoding="utf-8").read()
            truth = json.loads(state).get("event") == "purchase"
        assert ("VERIFIED" if truth else "REFUTED") == expected, (rubric, cid)
        out.append({"control_id": cid, "locator": loc, "expected": expected, "state": state,
                    "input_digest": s1cal.sha256_text(state)})
    return out


# ------------------------------------------------------------------ datasets

def _consent_items(split, r, exclude=frozenset()):
    """8 combinations x 8 languages x 4 items; paraphrases 0-2 (calibration) or the two new ones (test).
    `exclude` holds the calibration states, so no held-out banner repeats a calibration one (the
    no-disclosure and non-banner cells share their filler text across splits)."""
    langs = sorted(CONSENT)
    combos = [(p, t, w) for p in (0, 1) for t in (0, 1) for w in (0, 1)]
    out, seen = [], set(exclude)
    for lang in langs:
        L = CONSENT[lang]
        pool = {d: (list(enumerate(L[d])) if split == "calibration" else
                    [(3 + j, s) for j, s in enumerate(NEW_PARAPHRASES[lang][d])]) for d in DISCLOSURES}
        for combo in combos:
            made = 0
            while made < 4:
                present = [d for d, on in zip(DISCLOSURES, combo) if on]
                non_banner = not present and made >= 2  # half of the no-disclosure cell is ordinary shop text
                if non_banner:
                    segs = [{"kind": "other", "text": r.choice(L["other"])}]
                    if r.random() < 0.5:
                        segs.append({"kind": "filler", "text": r.choice(L["button"])})
                    idx = [None] * len(segs)
                else:
                    picks = [(d, r.choice(pool[d])) for d in present]
                    body = [{"kind": d, "text": s} for d, (_, s) in picks]
                    idx = {d: j for d, (j, _) in picks}
                    order = list(range(len(body)))
                    if r.random() < 0.25:
                        r.shuffle(order)
                    body = [body[k] for k in order]
                    if r.random() < 0.5:
                        body.insert(r.randint(0, len(body)), {"kind": "filler", "text": L["near"][0]})
                    segs = [{"kind": "filler", "text": r.choice(L["title"])}] + body + \
                           [{"kind": "filler", "text": r.choice(L["button"])}]
                state = _assemble(lang, segs, not non_banner)
                if state in seen:
                    continue
                seen.add(state)
                item = {"lang": lang, "is_banner": not non_banner, "segments": segs}
                truth = label_consent(item)["disclosures"]  # also runs the filler leak check
                assert tuple(int(truth[d]) for d in DISCLOSURES) == combo
                out.append({"lang": lang, "variant": "".join(map(str, combo)) + ("_not_banner" if non_banner else ""),
                            "paraphrases": {} if non_banner else idx, "state": state,
                            "truth": {d: bool(truth[d]) for d in DISCLOSURES}})
                made += 1
    return out


GTM_OTHER = ["add_to_cart"] * 5 + ["begin_checkout"] * 3 + ["view_item"] * 3 + \
            ["refund", "add_payment_info", "view_cart", "page_view", "sign_up"]
GTM_NEAR = ["Purchase", "PURCHASE", "purchase_complete", "order_completed", "purchased", "checkout_purchase"]


def _gtm_items(r, n=360):
    out, seen = [], set()
    while len(out) < n:
        p = _valid_purchase(r)
        k = len(out) % 10
        if k < 5:
            ev = "purchase"
        elif k < 9:
            ev = r.choice(GTM_OTHER)
        else:
            ev = r.choice(GTM_NEAR)
        p["event"] = ev
        if ev != "purchase" and ev not in GTM_NEAR:
            p["ecommerce"].pop("transaction_id", None)
            if ev == "page_view":
                del p["ecommerce"]
                p["page_location"] = "https://shop.example/"
        state = s1cal.jcs(p)
        if state in seen:
            continue
        seen.add(state)
        out.append({"event": ev, "variant": "purchase" if ev == "purchase" else ("near_miss" if ev in GTM_NEAR else "other_event"),
                    "state": state, "label": "holds" if ev == "purchase" else "fails"})
    return out


def generate():
    tok_ml, tok_en = s1cal.load_tokenizer("laya-multilingual"), s1cal.load_tokenizer("laya")
    manifest = {"split_seed": s1cal.SPLIT_SEED}
    # consent pool
    pool = {}
    for split, seed in (("calibration", 7101), ("test", 7102)):
        rows = []
        exclude = frozenset(x["state"] for x in pool.get("calibration", []))
        for i, it in enumerate(_consent_items(split, random.Random(seed), exclude)):
            rows.append({"id": "consent-%s-%04d" % (split[:3], i), **it,
                         "state_tokens": s1cal.count_state_tokens(tok_ml, it["state"]),
                         "input_digest": s1cal.sha256_text(it["state"])})
        assert max(x["state_tokens"] for x in rows) <= 768
        pool[split] = rows
        s1cal.write_jsonl(os.path.join(FIX, "consent-pool", split + ".jsonl"), rows)
    manifest["consent-pool"] = {s: {"size": len(v), "sha256": s1cal.file_sha256(os.path.join(FIX, "consent-pool", s + ".jsonl")),
                                    "max_state_tokens": max(x["state_tokens"] for x in v)} for s, v in pool.items()}
    digests = {x["input_digest"] for v in pool.values() for x in v}
    for rubric, spec in RUBRICS.items():
        if "disclosure" not in spec:
            continue
        entry = {"seeds": [7101, 7102]}
        for split, rows in pool.items():
            labels = [{"id": x["id"], "input_digest": x["input_digest"],
                       "label": "holds" if x["truth"][spec["disclosure"]] else "fails"} for x in rows]
            sha = s1cal.write_jsonl(os.path.join(FIX, rubric, split + ".jsonl"), labels)
            entry[split] = {"sha256": sha, "size": len(labels),
                            "labels": {k: sum(1 for x in labels if x["label"] == k) for k in ("holds", "fails")}}
        manifest[rubric] = entry
    # gtm
    items = _gtm_items(random.Random(9173))
    rows = [{"id": "gtmev-%04d" % i, **it, "state_tokens": s1cal.count_state_tokens(tok_en, it["state"]),
             "input_digest": s1cal.sha256_text(it["state"])} for i, it in enumerate(items)]
    assert max(x["state_tokens"] for x in rows) <= 320
    cal, test = s1cal.stratified_split(rows)
    entry = {"seed": 9173}
    for split, part in (("calibration", cal), ("test", test)):
        sha = s1cal.write_jsonl(os.path.join(FIX, "gtm-event-is-purchase", split + ".jsonl"), part)
        entry[split] = {"sha256": sha, "size": len(part),
                        "labels": {k: sum(1 for x in part if x["label"] == k) for k in ("holds", "fails")}}
    manifest["gtm-event-is-purchase"] = entry
    # controls: write the new consent fixtures, check none duplicates a dataset item
    gtm_digests = {x["input_digest"] for x in rows}
    for rubric in RUBRICS:
        for c in controls(rubric):
            path = os.path.join(s1cal.ROOT, c["locator"])
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(c["state"])
            assert s1cal.file_sha256(path) == c["input_digest"], c["control_id"]
            assert c["input_digest"] not in digests | gtm_digests, "control duplicates a dataset item: " + c["control_id"]
    with open(os.path.join(FIX, "manifest.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(manifest, indent=1))


def load(rubric):
    """(calibration rows, test rows) with state and label."""
    if rubric.startswith("consent"):
        out = []
        for split in ("calibration", "test"):
            pool = {x["id"]: x for x in s1cal.read_jsonl(os.path.join(FIX, "consent-pool", split + ".jsonl"))}
            rows = []
            for lab in s1cal.read_jsonl(os.path.join(FIX, rubric, split + ".jsonl")):
                p = pool[lab["id"]]
                assert p["input_digest"] == lab["input_digest"]
                rows.append({**p, "label": lab["label"]})
            out.append(rows)
        return out[0], out[1]
    d = os.path.join(FIX, rubric)
    return s1cal.read_jsonl(os.path.join(d, "calibration.jsonl")), s1cal.read_jsonl(os.path.join(d, "test.jsonl"))


# ------------------------------------------------------------------ model runs

def run(only=None):
    by_ck = {}
    for rubric, spec in RUBRICS.items():
        if not only or rubric in only:
            by_ck.setdefault(spec["checkpoint"], []).append(rubric)
    for ck, rubrics in by_ck.items():
        runner = s1cal.LayaRunner(ck, *RUNTIME[ck])
        for rubric in rubrics:
            d = os.path.join(FIX, rubric)
            cal, test = load(rubric)
            rows = cal + test
            pred_path = os.path.join(d, "predictions.jsonl")
            preds = {r["id"]: r for r in s1cal.read_jsonl(pred_path)} if os.path.exists(pred_path) else {}
            ctl_path = os.path.join(d, "controls-inprocess.json")
            ctl = json.load(open(ctl_path, encoding="utf-8")) if os.path.exists(ctl_path) else {}
            # A prediction is keyed by item id and the item's input digest, so a regenerated item is rescored.
            for r in rows:
                p = preds.get(r["id"])
                if p is not None and p.get("input_digest") not in (None, r["input_digest"]):
                    preds[r["id"]] = {"id": r["id"]}
                preds.setdefault(r["id"], {"id": r["id"]})["input_digest"] = r["input_digest"]
            for name, q in formulations(rubric).items():
                todo = [r for r in rows if name not in preds[r["id"]]]
                if not todo and name in ctl:
                    continue
                used, cut = runner.head_tokens(q)
                assert not cut, (rubric, name, "instructions would be cut by head_max_len")
                logits = runner.logits([r["state"] for r in todo], q, batch_size=1)
                for r, lg in zip(todo, logits):
                    preds[r["id"]][name] = [round(float(x), 6) for x in lg]
                s1cal.write_jsonl(pred_path, [preds[k] for k in sorted(preds)])
                if name not in ctl:
                    ctl[name] = {c["control_id"]: [runner.logits([c["state"]], q)[0].tolist() for _ in range(3)]
                                 for c in controls(rubric)}
                with open(ctl_path, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(ctl, indent=1) + "\n")
                print(rubric, name, "head_tokens", used, "scored", len(todo), "of", len(rows), flush=True)
        del runner


# ------------------------------------------------------------------ evaluation

def wilson_lower(k, n, z=1.96):
    if n == 0:
        return None
    ph = k / n
    return (ph + z * z / (2 * n) - z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def evaluate(rubric):
    import numpy as np
    from evaluate import shipped_temperature
    spec = RUBRICS[rubric]
    vt, rt, max_ece = spec["thresholds"]
    d = os.path.join(FIX, rubric)
    cal, test = load(rubric)
    preds = {r["id"]: r for r in s1cal.read_jsonl(os.path.join(d, "predictions.jsonl"))}
    ctl_runs = json.load(open(os.path.join(d, "controls-inprocess.json"), encoding="utf-8"))
    ctl_meta = {c["control_id"]: c for c in controls(rubric)}
    out = {"rubric": rubric, "verify_threshold": vt, "refute_threshold": rt, "max_ece": max_ece,
           "calibration_size": len(cal), "test_size": len(test), "formulations": {}}
    for name, q in formulations(rubric).items():
        keys = s1cal.option_keys(q)
        holds, fails = decision_sets(q)
        lc = np.array([preds[r["id"]][name] for r in cal])
        lt = np.array([preds[r["id"]][name] for r in test])
        yc = [truth_key(q, r) for r in cal]
        yt = [truth_key(q, r) for r in test]
        t_fit = s1cal.fit_temperature(lc, np.array([keys.index(y) for y in yc]))
        t_ship = shipped_temperature(spec["checkpoint"], q["type"], len(keys))
        res = {"question": q, "temperature": t_fit, "shipped_temperature": t_ship,
               "calibration_calibrated": s1cal.evaluate(lc, yc, keys, holds, fails, vt, rt, t_fit),
               "test_raw": s1cal.evaluate(lt, yt, keys, holds, fails, vt, rt, 1.0),
               "test_shipped": s1cal.evaluate(lt, yt, keys, holds, fails, vt, rt, t_ship),
               "test_calibrated": s1cal.evaluate(lt, yt, keys, holds, fails, vt, rt, t_fit), "controls": {}}
        # gated precision counts a verdict correct when it agrees with the binary label (holds/fails)
        tc = res["test_calibrated"]
        k = tc["verified_correct"] + tc["refuted_correct"]
        g = tc["verified"] + tc["refuted"]
        res["test_gated"] = {"verdicts": g, "correct": k, "wilson_lower": wilson_lower(k, g)}
        for field in ("lang", "variant"):
            vals = sorted({r.get(field) for r in test if r.get(field) is not None})
            if vals:
                res["test_accuracy_by_" + field] = {}
                for v in vals:
                    idx = [i for i, r in enumerate(test) if r.get(field) == v]
                    p = s1cal.softmax(lt[idx], t_fit)
                    res["test_accuracy_by_" + field][v] = float(np.mean([keys[int(j)] == yt[i] for j, i in zip(p.argmax(1), idx)]))
        pt = s1cal.softmax(lt, t_fit)
        res["test_status_by_variant"] = {}
        for i, row in enumerate(test):
            st = s1cal.map_status(pt[i], keys, holds, fails, vt, rt)[0]
            cell = res["test_status_by_variant"].setdefault(row["variant"], {})
            cell[st] = cell.get(st, 0) + 1
        all_ok = True
        for cid, runs in ctl_runs[name].items():
            mapped = [s1cal.map_status(s1cal.softmax(np.array(lg), t_fit), keys, holds, fails, vt, rt) for lg in runs]
            exp = ctl_meta[cid]["expected"]
            ok = all(m[0] == exp for m in mapped)
            all_ok &= ok
            res["controls"][cid] = {"expected": exp, "observed": [m[0] for m in mapped], "answer": mapped[0][1],
                                   "thresholded_probability": round(mapped[0][2], 6), "pass": ok}
        res["controls_pass"] = all_ok
        out["formulations"][name] = res
    # Pre-registered choice on the calibration split only.
    ranked = sorted(out["formulations"].items(),
                    key=lambda nr: (-nr[1]["calibration_calibrated"]["accuracy"], nr[1]["calibration_calibrated"]["nll"]))
    name, r = ranked[0]
    tc, cc = r["test_calibrated"], r["calibration_calibrated"]
    measured_ece = max(tc["ece"], cc["ece"])
    reasons = []
    if tc["precision"] is None:
        reasons.append("no held-out item clears either threshold (coverage 0)")
    else:
        if tc["precision"] < PRECISION_BAR:
            reasons.append("held-out gated precision %.3f is below %.2f" % (tc["precision"], PRECISION_BAR))
        lb = r["test_gated"]["wilson_lower"]
        if lb < WILSON_BAR:
            reasons.append("Wilson 95%% lower bound of held-out gated precision %.3f (%d/%d) is below %.2f"
                           % (lb, r["test_gated"]["correct"], r["test_gated"]["verdicts"], WILSON_BAR))
    if measured_ece > max_ece:
        reasons.append("measured ECE %.3f (worse of calibration %.3f and held-out %.3f) exceeds max_ece %.2f"
                       % (measured_ece, cc["ece"], tc["ece"], max_ece))
    if not r["controls_pass"]:
        reasons.append("controls land on the wrong status: " + ", ".join(c for c, v in r["controls"].items() if not v["pass"]))
    out["chosen"] = {"formulation": name, "measured_ece": measured_ece, "assurance_eligible_before_replay": not reasons,
                     "reasons": reasons}
    with open(os.path.join(d, "results.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def summary(out):
    print("==", out["rubric"], "thresholds", out["verify_threshold"], out["refute_threshold"], "max_ece", out["max_ece"])
    for n, r in out["formulations"].items():
        a, s, c, cc = r["test_raw"], r["test_shipped"], r["test_calibrated"], r["calibration_calibrated"]
        print("  %-16s T=%.3f cal_acc=%.3f cal_nll=%.3f | test acc=%.3f ece raw/ship/cal=%.3f/%.3f/%.3f cov=%.3f prec=%s "
              "lb=%s V/R/I=%d/%d/%d ctl=%s preds=%s" % (
                  n, r["temperature"], cc["accuracy"], cc["nll"], c["accuracy"], a["ece"], s["ece"], c["ece"],
                  c["coverage"], "n/a" if c["precision"] is None else "%.3f" % c["precision"],
                  "n/a" if r["test_gated"]["wilson_lower"] is None else "%.3f" % r["test_gated"]["wilson_lower"],
                  c["verified"], c["refuted"], c["inconclusive"],
                  " ".join("%s:%s" % (k.split("-", 2)[-1], "+".join(sorted(set(v["observed"])))) for k, v in r["controls"].items()),
                  c["pred_counts"]))
    print("  chosen:", out["chosen"])


# ------------------------------------------------------------------ replay

def fresh(rubric, name):
    spec = RUBRICS[rubric]
    runner = s1cal.LayaRunner(spec["checkpoint"], *RUNTIME[spec["checkpoint"]])
    q = formulations(rubric)[name]
    print("RESULT " + json.dumps({"pid": os.getpid(),
                                  "logits": {c["control_id"]: runner.logits([c["state"]], q)[0].tolist() for c in controls(rubric)}}))


def replay(rubric, fresh_runs):
    import numpy as np
    d = os.path.join(FIX, rubric)
    res = json.load(open(os.path.join(d, "results.json"), encoding="utf-8"))
    name = res["chosen"]["formulation"]
    fr = res["formulations"][name]
    q = formulations(rubric)[name]
    keys, (holds, fails) = s1cal.option_keys(q), decision_sets(q)
    vt, rt, t = res["verify_threshold"], res["refute_threshold"], fr["temperature"]
    runs = {cid: [{"fresh_process": False, "logits": lg} for lg in lgs]
            for cid, lgs in json.load(open(os.path.join(d, "controls-inprocess.json"), encoding="utf-8"))[name].items()}
    for _ in range(fresh_runs):
        p = subprocess.run([sys.executable, os.path.abspath(__file__), "--fresh", rubric, name], capture_output=True,
                           text=True, check=True, env={**os.environ, "HF_HUB_OFFLINE": "1"})
        payload = json.loads([ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")][-1][7:])
        for cid, lg in payload["logits"].items():
            runs[cid].append({"fresh_process": True, "logits": lg})
    report = {"rubric": rubric, "formulation": name, "temperature": t, "controls": {}}
    worst_p = worst_l = 0.0
    for cid, rs in runs.items():
        mapped = [s1cal.map_status(s1cal.softmax(np.array(r["logits"]), t), keys, holds, fails, vt, rt) for r in rs]
        probs = [m[2] for m in mapped]
        lg = np.array([r["logits"] for r in rs])
        dp, dl = max(probs) - min(probs), float((lg.max(0) - lg.min(0)).max())
        worst_p, worst_l = max(worst_p, dp), max(worst_l, dl)
        report["controls"][cid] = {"runs": len(rs), "fresh_process_runs": sum(r["fresh_process"] for r in rs),
                                   "statuses": [m[0] for m in mapped], "answers": [m[1] for m in mapped],
                                   "thresholded_probability": probs, "max_probability_delta": dp, "max_logit_delta": dl}
    report.update({"max_probability_delta": worst_p, "max_logit_delta": worst_l})
    with open(os.path.join(d, "replay.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(report, indent=1) + "\n")
    print(rubric, name, "dp=%.3g dl=%.3g" % (worst_p, worst_l),
          {c: sorted(set(v["statuses"])) for c, v in report["controls"].items()})


# ------------------------------------------------------------------ rubric files

GATEWAY = {
    "worker_name": "jev-gateway", "ai_gateway_id_env": "JEV_GATEWAY_AI_GATEWAY_ID", "endpoint_env": "JEV_GATEWAY_ENDPOINT",
    "auth_token_env": "JEV_GATEWAY_TOKEN", "route": "/v1/systemone",
    "cache": {"mode": "enabled_with_bypass_run", "ttl_seconds": 86400,
              "key_binds": ["backend", "model_revision", "checkpoint", "rubric_digest", "question_digest", "input_digest",
                            "calibration"]},
    "logging": True,
}
DENIED = ["generate", "propose", "propose_claims", "propose_options", "suggest_options", "rewrite", "rewrite_claim",
          "rewrite_options", "explain", "complete", "chat", "review"]


def worst_logit_delta():
    vals = []
    for base in (s1cal.FIXTURES, FIX):
        for sub in os.listdir(base):
            p = os.path.join(base, sub, "replay.json")
            if os.path.exists(p):
                vals.append(json.load(open(p, encoding="utf-8"))["max_logit_delta"])
    return max(vals)


def epsilon_from(dp_measured, temperature):
    """10x the larger of the measured probability delta and the delta the worst logit wobble seen on any
    checkpoint would cause at this T (for the mass of any option set, |dp| <= dlogit / (2T)), rounded up to
    one significant figure, floored at 1e-6, capped at the schema's 0.02 (as update_rubrics.py does)."""
    e = max(1e-6, 10 * max(dp_measured, worst_logit_delta() / (2 * temperature)))
    mag = 10 ** math.floor(math.log10(e))
    return min(0.02, round(math.ceil(round(e / mag, 9)) * mag, 12))


def write_rubric(rubric):
    spec = RUBRICS[rubric]
    d = os.path.join(FIX, rubric)
    res = json.load(open(os.path.join(d, "results.json"), encoding="utf-8"))
    rep = json.load(open(os.path.join(d, "replay.json"), encoding="utf-8"))
    name = res["chosen"]["formulation"]
    assert rep["formulation"] == name
    r = res["formulations"][name]
    q = formulations(rubric)[name]
    tc, tr, ts, cc = r["test_calibrated"], r["test_raw"], r["test_shipped"], r["calibration_calibrated"]
    vt, rt, max_ece = spec["thresholds"]
    holds, fails = decision_sets(q)
    reasons = list(res["chosen"]["reasons"])
    replay_bad = [c for c, v in rep["controls"].items() if len(set(v["statuses"])) != 1
                  or v["statuses"][0] != r["controls"][c]["expected"]]
    if replay_bad:
        reasons.append("controls off their expected status in a replay run: " + ", ".join(replay_bad))
    eligible = not reasons
    split_sha = {s: s1cal.file_sha256(os.path.join(d, s + ".jsonl")) for s in ("calibration", "test")}
    is_consent = rubric.startswith("consent")
    runtime_len = RUNTIME[spec["checkpoint"]]
    ctls = controls(rubric)
    per_variant = ", ".join("%s %.2f" % kv for kv in r.get("test_accuracy_by_variant", {}).items())
    per_lang = ", ".join("%s %.2f" % kv for kv in r.get("test_accuracy_by_lang", {}).items())
    tried = "; ".join("%s: calibration accuracy %.3f, NLL %.3f at T %.4g; held-out accuracy %.3f" % (
        n, x["calibration_calibrated"]["accuracy"], x["calibration_calibrated"]["nll"], x["temperature"],
        x["test_calibrated"]["accuracy"]) for n, x in res["formulations"].items())
    lb = r["test_gated"]["wilson_lower"]
    notes = [
        "Measured on the pinned checkpoint, CPU fp32, eval mode, one state per forward pass: formulation `%s` chosen on "
        "the calibration split only (highest accuracy, then lowest NLL at the fitted temperature). Held-out accuracy "
        "%.3f (n=%d); ECE (15 bins) %.3f raw logits, %.3f at the checkpoint's shipped temperature, %.3f at the fitted "
        "temperature %.4g; at verify %.2f / refute %.2f, coverage %.3f (VERIFIED %d, REFUTED %d, INCONCLUSIVE %d) with "
        "gated precision %s (Wilson 95%% lower bound %s). Calibration split: accuracy %.3f, ECE after fitting %.3f "
        "(n=%d). Dataset: test/fixtures/system1-calibration/single-condition/%s/ (report: "
        "docs/calibration/system1-calibration-report.md, Hybrid section)." % (
            name, tc["accuracy"], tc["n"], tr["ece"], ts["ece"], tc["ece"], r["temperature"], vt, rt, tc["coverage"],
            tc["verified"], tc["refuted"], tc["inconclusive"],
            "n/a" if tc["precision"] is None else "%.3f" % tc["precision"], "n/a" if lb is None else "%.3f" % lb,
            cc["accuracy"], cc["ece"], cc["n"], rubric),
        "Formulations tried: %s. Controls at the fitted T: %s. Replay: %d runs per control (%d in fresh processes), "
        "max thresholded-probability delta %.3g, max logit delta %.3g; epsilon is 10x the larger of the measured delta "
        "and the delta the worst logit wobble seen on any checkpoint would cause at this temperature, rounded up." % (
            tried, "; ".join("%s %s->%s (p=%.3f)" % (c, v["expected"], v["observed"][0], v["thresholded_probability"])
                             for c, v in r["controls"].items()),
            max(v["runs"] for v in rep["controls"].values()), max(v["fresh_process_runs"] for v in rep["controls"].values()),
            rep["max_probability_delta"], rep["max_logit_delta"]),
        "Temperature semantics: `calibration.temperature` replaces the checkpoint's own temperature for this "
        "question's (type, option count) bucket, i.e. probabilities are softmax(option logits / T); a runner sets "
        "agent.temperature_by_options[temp_bucket] = T and passes no `lang`. `measured_ece` is the larger of the "
        "calibration-split and held-out ECE at the fitted temperature.",
    ]
    if per_variant:
        notes.append(("Held-out accuracy by variant (presence of purpose, third parties, withdrawal as 0/1): %s." if is_consent
                      else "Held-out accuracy by variant: %s.") % per_variant + (" By language: %s." % per_lang if per_lang else ""))
    if is_consent:
        notes += [
            "Formulations were registered in two stages: noul and choice2_neutral first; choice2_contrastive and "
            "noul_sentence after stage 1 failed on the calibration split (stage-1 held-out numbers had already been "
            "computed for two of the three disclosures). The choice among all four used the calibration split only.",
            "Single condition: this rubric asks about one disclosure only. The consent-banner rule (purpose, third "
            "parties, withdrawal) holds for a locale when all three single-disclosure rubrics VERIFY on its banner; "
            "it replaces the multi-condition rubric RUB-S1-CONSENT-BANNER-DISCLOSURES, which scored at chance.",
            "The held-out split is paraphrase-disjoint: calibration banners use the generator's original three "
            "paraphrases per disclosure and language, held-out banners two new ones, so held-out wording was never "
            "seen while choosing the formulation or fitting T. The paraphrases were written for this exercise; they "
            "are not reviewed native copy.",
            "Checkpoint is pinned to laya-multilingual; Router auto-selection is not used. This checks that the "
            "disclosure is stated, not that the wording satisfies any particular law.",
        ]
    else:
        notes += [
            "Demonstration of a single-condition question where Laya works. The selection guide routes this exact "
            "check to the `validator` backend (RUB-S1-VAL-GTM-PURCHASE-EVENT decides it, and the five other "
            "purchase conditions, exactly); do not bind a new claim to this rubric where the validator applies.",
            "Held-out items include near-miss spellings (Purchase, PURCHASE, purchase_complete, order_completed, "
            "purchased, checkout_purchase) labeled as not purchase, because the condition is `event` exactly equal to "
            "\"purchase\". Held-out statuses by variant: %s. Every wrong gated verdict is a near-miss spelling "
            "VERIFIED as purchase; the model never REFUTES one. The bar is met on this mix (about one item in eight a "
            "near miss) and would not be on a population with more near misses." % "; ".join(
                "%s %s" % (v, ", ".join("%s %d" % kv for kv in sorted(c.items())))
                for v, c in sorted(r["test_status_by_variant"].items())),
        ]
    if eligible:
        notes.append("Assurance-eligible: held-out gated precision %.3f >= %.2f with Wilson lower bound %.3f >= %.2f, "
                     "every control on its expected status in every replay run, measured ECE %.3f <= max_ece %.2f."
                     % (tc["precision"], PRECISION_BAR, lb, WILSON_BAR, res["chosen"]["measured_ece"], max_ece))
    else:
        notes.append("Not assurance-eligible: " + "; ".join(reasons) + ". Thresholds were not lowered to compensate.")
    rb = {
        "kind": "rubric", "schema_family": "system1", "schema_version": "1",
        "rubric_id": spec["rubric_id"], "rubric_version": "1.0.0", "title": spec["title"],
        "claim": {"claim_type": spec["claim_type"], "statement": spec["statement"],
                  "eligibility": "closed_option_conformance",
                  "spec_refs": ["consent spec: banner disclosures"] if is_consent else ["tracking-spec: purchase event"]},
        "assurance_eligible": eligible,
        "backend": "laya",
        "model": {"provider": "huggingface", "repo": s1cal.REPO, "checkpoint": spec["checkpoint"],
                  "revision": s1cal.REVISION, "selection": "pinned",
                  "runtime": {"package": "laya", "package_version": "0.3.21", "precision": "fp32", "device_class": "cpu",
                              "eval_mode": True, "fast_path": False, "max_len": runtime_len[0],
                              "head_max_len": runtime_len[1]}},
        "question": q,
        "question_digest": s1cal.sha256_text(s1cal.bridge_canonical_json(q)),
        "decision": {"claim_holds_options": holds, "claim_fails_options": fails, "verify_threshold": vt,
                     "refute_threshold": rt, "probability_basis": "calibrated_option_set_mass", "tie_rule": "INCONCLUSIVE"},
        "calibration": {"method": "temperature_scaled", "temperature": round(r["temperature"], 6),
                        "calibration_set_digest": split_sha["calibration"],
                        "calibration_set_size": cc["n"], "measured_ece": round(res["chosen"]["measured_ece"], 4),
                        "max_ece": max_ece},
        "input": ({"state_shape": "text", "source": {"kind": "build_artifact", "locator": "dist/locales/*/consent-banner.txt",
                                                     "extractor": "one claim per locale file"},
                   "canonicalization": "utf8_nfc_lf_trim_trailing", "token_limit": 768}
                  if is_consent else
                  {"state_shape": "json_document", "source": {"kind": "captured_fixture",
                                                              "locator": "test/fixtures/datalayer/purchase-push.json"},
                   "canonicalization": "rfc8785_jcs", "token_limit": 320}),
        "controls": [{"control_id": c["control_id"], "locator": c["locator"], "input_digest": c["input_digest"],
                      "expected": c["expected"]} for c in ctls],
        "replay": {"min_runs": 2, "probability_epsilon": epsilon_from(rep["max_probability_delta"], r["temperature"]),
                   "require_identical_answer": True, "require_identical_status": True,
                   "freshness": "uncached_and_fresh_process"},
        "gateway": GATEWAY,
        "operations": {"allowed": ["evaluate"], "denied": DENIED},
        "notes": notes,
    }
    rb["input"].update({"tokenizer": "pinned_checkpoint", "truncation": "never", "over_limit": "ERROR"})
    path = os.path.join(s1cal.RUBRICS_DIR, spec["file"])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(rb, indent=2, ensure_ascii=False) + "\n")
    print(spec["file"], name, "eligible" if eligible else "NOT eligible", reasons)


def report():
    """Markdown tables for the Hybrid section of docs/calibration/system1-calibration-report.md."""
    def f3(x):
        return "n/a" if x is None else "%.3f" % x
    print("| Rubric | Formulation | Held-out acc | ECE raw / shipped / fitted | T | Coverage | Precision (k/n) | "
          "Wilson LB | Controls | epsilon | assurance_eligible |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for rubric, spec in RUBRICS.items():
        res = json.load(open(os.path.join(FIX, rubric, "results.json"), encoding="utf-8"))
        rb = json.load(open(os.path.join(s1cal.RUBRICS_DIR, spec["file"]), encoding="utf-8"))
        name = res["chosen"]["formulation"]
        r = res["formulations"][name]
        tc, g = r["test_calibrated"], r["test_gated"]
        ok = sum(v["pass"] for v in r["controls"].values())
        print("| %s %s | `%s` | %.3f | %.3f / %.3f / %.3f | %.4g | %.3f | %s (%d/%d) | %s | %d/%d pass | %g | %s |" % (
            spec["rubric_id"], rb["rubric_version"], name, tc["accuracy"], r["test_raw"]["ece"],
            r["test_shipped"]["ece"], tc["ece"], r["temperature"], tc["coverage"], f3(tc["precision"]), g["correct"],
            g["verdicts"], f3(g["wilson_lower"]), ok, len(r["controls"]), rb["replay"]["probability_epsilon"],
            str(rb["assurance_eligible"]).lower()))
    print()
    print("| Rubric | Formulation | Cal acc | Cal NLL | T | Held-out acc | ECE fitted | Coverage | Precision | V / R / I | Controls |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for rubric, spec in RUBRICS.items():
        res = json.load(open(os.path.join(FIX, rubric, "results.json"), encoding="utf-8"))
        for name, r in res["formulations"].items():
            tc, cc = r["test_calibrated"], r["calibration_calibrated"]
            print("| %s | `%s`%s | %.3f | %.3f | %.4g | %.3f | %.3f | %.3f | %s | %d / %d / %d | %s |" % (
                rubric, name, " (chosen)" if name == res["chosen"]["formulation"] else "", cc["accuracy"], cc["nll"],
                r["temperature"], tc["accuracy"], tc["ece"], tc["coverage"], f3(tc["precision"]), tc["verified"],
                tc["refuted"], tc["inconclusive"],
                ", ".join("%s %s" % (c.replace("CTL-", ""), "/".join(sorted(set(v["observed"])))) for c, v in r["controls"].items())))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "--fresh":
        fresh(sys.argv[2], sys.argv[3])
    elif cmd == "generate":
        generate()
    elif cmd == "run":
        run(set(sys.argv[2:]))
    elif cmd == "evaluate":
        for rb in (sys.argv[2:] or RUBRICS):
            summary(evaluate(rb))
    elif cmd == "replay":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
        for rb in (sys.argv[3:] or RUBRICS):
            replay(rb, n)
    elif cmd == "rubrics":
        for rb in (sys.argv[2:] or RUBRICS):
            write_rubric(rb)
    elif cmd == "report":
        report()
    else:
        raise SystemExit(__doc__)
