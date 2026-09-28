"""Seeded generator for the three Laya calibration datasets.

    python tools/system1-calibration/generate.py            # all rubrics
    python tools/system1-calibration/generate.py gtm        # one rubric

Writes test/fixtures/system1-calibration/<rubric>/{calibration,test}.jsonl as
canonical JSONL (one RFC 8785 object per line) and manifest.json with the
counts and SHA-256 of each split. Every item carries the exact `state` string
the model is sent (its SHA-256 is `input_digest`) and a `truth` block computed by
labelers.py; the generator's own `variant` tag is only a design note and is
cross-checked against the labeler, never used as the label.
"""
from __future__ import annotations

import json
import os
import random
import string
import sys
import tomllib
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1cal  # noqa: E402
from labelers import label_consent, label_gtm, label_wrangler  # noqa: E402

SEED = {"gtm-datalayer-event": 4217, "multilingual-consent-banner": 1156, "wrangler-bindings": 8785}
TOKEN_LIMIT = {"gtm-datalayer-event": 320, "multilingual-consent-banner": 768, "wrangler-bindings": 320}
CHECKPOINT = {"gtm-datalayer-event": "laya", "multilingual-consent-banner": "laya-multilingual", "wrangler-bindings": "laya"}

# ------------------------------------------------------------------ GTM

PRODUCTS = [
    ("SKU_1042", "Trail Running Shoes"), ("SKU_2210", "Merino Wool Socks"), ("SKU_3307", "Waterproof Jacket"),
    ("SKU_4471", "Insulated Bottle"), ("SKU_5093", "Canvas Tote"), ("SKU_6120", "Espresso Beans 1kg"),
    ("SKU_7718", "Wireless Earbuds"), ("SKU_8052", "Yoga Mat"), ("SKU_9186", "Desk Lamp"), ("P-00931", "Linen Shirt"),
    ("P-01877", "Ceramic Mug"), ("P-02264", "Phone Case"),
]
VALID_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "SEK", "BRL", "INR", "MXN", "PLN"]
BAD_CURRENCIES = ["usd", "eur", "US$", "€", "DOLLAR", "EURO", "EU", "USDT", "US", "ABC", "QQQ", 840, 978]
WRONG_EVENTS = ["add_to_cart", "begin_checkout", "view_item", "refund", "add_payment_info", "Purchase",
                "purchase_complete", "checkout", "order_completed"]
NOISE = [("gtm.uniqueEventId", lambda r: r.randint(3, 400)), ("user_id", lambda r: "u_%06d" % r.randint(1, 999999)),
         ("page_type", lambda r: r.choice(["checkout", "confirmation", "thank_you"])),
         ("customer_type", lambda r: r.choice(["new", "returning"])), ("debug_mode", lambda r: r.choice([True, False]))]


def _item(r: random.Random, mode: str = "both"):
    pid, name = r.choice(PRODUCTS)
    it = {}
    if mode in ("both", "id"):
        it["item_id"] = pid
    if mode in ("both", "name"):
        it["item_name"] = name
    if r.random() < 0.7:
        it["price"] = round(r.uniform(4, 180), 2)
    if r.random() < 0.7:
        it["quantity"] = r.randint(1, 4)
    if r.random() < 0.3:
        it["item_category"] = r.choice(["Apparel", "Outdoor", "Kitchen", "Electronics"])
    if r.random() < 0.2:
        it["item_brand"] = r.choice(["Northway", "Alpen", "Kofi", "Lumen"])
    return it


def _valid_purchase(r: random.Random):
    n = r.choice([1, 1, 1, 2, 2, 3])
    items = [_item(r, r.choice(["both", "both", "id", "name"])) for _ in range(n)]
    ec = {
        "transaction_id": r.choice(["T-%05d" % r.randint(1, 99999), "ORD%08d" % r.randint(1, 99999999),
                                    str(uuid.UUID(int=r.getrandbits(128)))[:13]]),
        "value": r.choice([round(r.uniform(5, 900), 2), r.randint(5, 900)]),
        "currency": r.choice(VALID_CURRENCIES),
        "items": items,
    }
    for k, f in (("tax", lambda: round(r.uniform(0, 60), 2)), ("shipping", lambda: r.choice([0, 4.99, 9.5])),
                 ("coupon", lambda: r.choice(["SUMMER10", "WELCOME", "FREESHIP"])),
                 ("affiliation", lambda: r.choice(["Online Store", "App"]))):
        if r.random() < 0.35:
            ec[k] = f()
    push = {"event": "purchase", "ecommerce": ec}
    for k, f in NOISE:
        if r.random() < 0.3:
            push[k] = f(r)
    return push


def gen_gtm(r: random.Random, n: int):
    variants = ["valid"] * 10 + ["valid_noise"] * 2 + ["wrong_event"] * 2 + ["missing_transaction_id",
                "missing_value", "missing_currency", "bad_currency", "bad_currency", "empty_items",
                "items_not_array", "items_without_id_or_name", "ecommerce_missing", "empty_transaction_id"]
    out = []
    while len(out) < n:
        v = r.choice(variants)
        p = _valid_purchase(r)
        ec = p["ecommerce"]
        if v == "valid_noise":
            p[r.choice(["gtm.start", "consent_state", "experiment"])] = r.choice([r.randint(1, 10 ** 9), "granted", "B"])
        elif v == "wrong_event":
            p["event"] = r.choice(WRONG_EVENTS)
        elif v.startswith("missing_"):
            ec.pop(v[len("missing_"):])
        elif v == "empty_transaction_id":
            ec["transaction_id"] = ""
        elif v == "bad_currency":
            ec["currency"] = r.choice(BAD_CURRENCIES)
        elif v == "empty_items":
            ec["items"] = []
        elif v == "items_not_array":
            ec["items"] = r.choice([ec["items"][0], ec["items"][0].get("item_id", "SKU_1042")])
        elif v == "items_without_id_or_name":
            ec["items"] = [{k: val for k, val in it.items() if k not in ("item_id", "item_name")} or {"quantity": 1}
                           for it in ec["items"]]
        elif v == "ecommerce_missing":
            del p["ecommerce"]
            p.update(ec)
        state = s1cal.jcs(p)
        truth = label_gtm(json.loads(state))
        expect = "holds" if v.startswith("valid") else "fails"
        assert truth["label"] == expect, (v, state, truth)
        out.append({"variant": v, "state": state, "truth": truth})
    return out


# ------------------------------------------------------------------ consent

CONSENT = {
    "en": {
        "purpose": ["We use cookies and similar technologies to measure how our website is used and to personalise the ads you see.",
                    "We collect information about your device and browsing, such as pages visited and clicks, to analyse traffic and improve our services.",
                    "Cookies help us understand how visitors use this site and let us show you more relevant advertising."],
        "third_parties": ["Some of this data is shared with third parties, such as Google and Meta.",
                          "Our partners, including Google and other companies, receive this information and may combine it with other data they hold.",
                          "We pass this information on to selected third-party providers."],
        "withdrawal": ["You can refuse non-essential cookies or withdraw your consent at any time via \"Cookie settings\" in the footer.",
                       "If you do not agree, click \"Reject all\". You can change your mind later in the privacy settings.",
                       "You may decline, and you can withdraw your consent at any time from the link at the bottom of every page."],
        "title": ["Your privacy matters to us.", "Welcome!", "Cookies on this site"],
        "button": ["[Accept all]", "[OK]", "[Accept]"],
        "near": ["More information is available in our privacy policy."],
        "other": ["Free shipping on all orders over 50 euros. Orders placed before 2 pm ship the same day.",
                  "Sign up for our newsletter and be the first to hear about new arrivals and seasonal sales."],
    },
    "de": {
        "purpose": ["Wir verwenden Cookies und ähnliche Technologien, um die Nutzung unserer Website zu messen und Ihnen personalisierte Werbung anzuzeigen.",
                    "Wir erfassen Informationen über Ihr Gerät und Ihr Surfverhalten, etwa besuchte Seiten und Klicks, um den Datenverkehr zu analysieren und unsere Dienste zu verbessern.",
                    "Cookies helfen uns zu verstehen, wie Besucher diese Seite nutzen, und ermöglichen relevantere Werbung."],
        "third_parties": ["Ein Teil dieser Daten wird an Dritte weitergegeben, zum Beispiel an Google und Meta.",
                          "Unsere Partner, darunter Google und weitere Unternehmen, erhalten diese Informationen und können sie mit anderen Daten zusammenführen.",
                          "Wir geben diese Informationen an ausgewählte Drittanbieter weiter."],
        "withdrawal": ["Sie können nicht notwendige Cookies ablehnen oder Ihre Einwilligung jederzeit über „Cookie-Einstellungen“ im Seitenfuß widerrufen.",
                       "Wenn Sie nicht einverstanden sind, klicken Sie auf „Alle ablehnen“. Sie können Ihre Entscheidung später in den Datenschutzeinstellungen ändern.",
                       "Sie können ablehnen und Ihre Einwilligung jederzeit über den Link am Ende jeder Seite widerrufen."],
        "title": ["Ihre Privatsphäre ist uns wichtig.", "Willkommen!", "Cookies auf dieser Website"],
        "button": ["[Alle akzeptieren]", "[OK]", "[Akzeptieren]"],
        "near": ["Weitere Informationen finden Sie in unserer Datenschutzerklärung."],
        "other": ["Kostenloser Versand für alle Bestellungen ab 50 Euro. Bestellungen vor 14 Uhr werden noch am selben Tag verschickt.",
                  "Melden Sie sich für unseren Newsletter an und erfahren Sie als Erste von neuen Produkten und Sonderangeboten."],
    },
    "fr": {
        "purpose": ["Nous utilisons des cookies et des technologies similaires pour mesurer l'utilisation de notre site et vous proposer des publicités personnalisées.",
                    "Nous collectons des informations sur votre appareil et votre navigation, comme les pages consultées et les clics, afin d'analyser le trafic et d'améliorer nos services.",
                    "Les cookies nous aident à comprendre comment les visiteurs utilisent ce site et à vous montrer des publicités plus pertinentes."],
        "third_parties": ["Une partie de ces données est partagée avec des tiers, tels que Google et Meta.",
                          "Nos partenaires, dont Google et d'autres sociétés, reçoivent ces informations et peuvent les combiner avec d'autres données.",
                          "Nous transmettons ces informations à des prestataires tiers sélectionnés."],
        "withdrawal": ["Vous pouvez refuser les cookies non essentiels ou retirer votre consentement à tout moment via « Paramètres des cookies » en bas de page.",
                       "Si vous n'êtes pas d'accord, cliquez sur « Tout refuser ». Vous pourrez changer d'avis plus tard dans les paramètres de confidentialité.",
                       "Vous pouvez refuser et retirer votre consentement à tout moment grâce au lien présent en bas de chaque page."],
        "title": ["Votre vie privée compte pour nous.", "Bienvenue !", "Cookies sur ce site"],
        "button": ["[Tout accepter]", "[OK]", "[Accepter]"],
        "near": ["Plus d'informations dans notre politique de confidentialité."],
        "other": ["Livraison gratuite pour toute commande de plus de 50 euros. Les commandes passées avant 14 h sont expédiées le jour même.",
                  "Inscrivez-vous à notre newsletter pour découvrir en avant-première nos nouveautés et nos soldes."],
    },
    "es": {
        "purpose": ["Utilizamos cookies y tecnologías similares para medir el uso de nuestro sitio web y mostrarle publicidad personalizada.",
                    "Recopilamos información sobre su dispositivo y su navegación, como las páginas visitadas y los clics, para analizar el tráfico y mejorar nuestros servicios.",
                    "Las cookies nos ayudan a entender cómo usan los visitantes este sitio y a mostrarle anuncios más relevantes."],
        "third_parties": ["Parte de estos datos se comparte con terceros, como Google y Meta.",
                          "Nuestros socios, entre ellos Google y otras empresas, reciben esta información y pueden combinarla con otros datos.",
                          "Transmitimos esta información a proveedores terceros seleccionados."],
        "withdrawal": ["Puede rechazar las cookies no esenciales o retirar su consentimiento en cualquier momento desde «Configuración de cookies» en el pie de página.",
                       "Si no está de acuerdo, haga clic en «Rechazar todo». Podrá cambiar de opinión más tarde en la configuración de privacidad.",
                       "Puede negarse y retirar su consentimiento en cualquier momento mediante el enlace al final de cada página."],
        "title": ["Su privacidad es importante para nosotros.", "¡Bienvenido!", "Cookies en este sitio"],
        "button": ["[Aceptar todo]", "[OK]", "[Aceptar]"],
        "near": ["Encontrará más información en nuestra política de privacidad."],
        "other": ["Envío gratuito en todos los pedidos superiores a 50 euros. Los pedidos realizados antes de las 14:00 se envían el mismo día.",
                  "Suscríbase a nuestro boletín y sea el primero en conocer las novedades y las rebajas de temporada."],
    },
    "it": {
        "purpose": ["Utilizziamo cookie e tecnologie simili per misurare l'utilizzo del nostro sito e mostrarti pubblicità personalizzata.",
                    "Raccogliamo informazioni sul tuo dispositivo e sulla tua navigazione, come le pagine visitate e i clic, per analizzare il traffico e migliorare i nostri servizi.",
                    "I cookie ci aiutano a capire come i visitatori usano questo sito e a mostrarti annunci più pertinenti."],
        "third_parties": ["Alcuni di questi dati vengono condivisi con terze parti, come Google e Meta.",
                          "I nostri partner, tra cui Google e altre società, ricevono queste informazioni e possono combinarle con altri dati.",
                          "Trasmettiamo queste informazioni a fornitori terzi selezionati."],
        "withdrawal": ["Puoi rifiutare i cookie non essenziali o revocare il consenso in qualsiasi momento tramite «Impostazioni cookie» nel piè di pagina.",
                       "Se non sei d'accordo, fai clic su «Rifiuta tutto». Potrai cambiare idea in seguito nelle impostazioni sulla privacy.",
                       "Puoi rifiutare e revocare il tuo consenso in qualsiasi momento tramite il link in fondo a ogni pagina."],
        "title": ["La tua privacy è importante per noi.", "Benvenuto!", "Cookie su questo sito"],
        "button": ["[Accetta tutto]", "[OK]", "[Accetta]"],
        "near": ["Maggiori informazioni sono disponibili nella nostra informativa sulla privacy."],
        "other": ["Spedizione gratuita per tutti gli ordini superiori a 50 euro. Gli ordini effettuati entro le 14 vengono spediti in giornata.",
                  "Iscriviti alla nostra newsletter per scoprire in anteprima le novità e i saldi di stagione."],
    },
    "pt": {
        "purpose": ["Utilizamos cookies e tecnologias semelhantes para medir a utilização do nosso site e mostrar-lhe publicidade personalizada.",
                    "Recolhemos informações sobre o seu dispositivo e a sua navegação, como páginas visitadas e cliques, para analisar o tráfego e melhorar os nossos serviços.",
                    "Os cookies ajudam-nos a perceber como os visitantes usam este site e a mostrar-lhe anúncios mais relevantes."],
        "third_parties": ["Parte destes dados é partilhada com terceiros, como a Google e a Meta.",
                          "Os nossos parceiros, incluindo a Google e outras empresas, recebem estas informações e podem combiná-las com outros dados.",
                          "Transmitimos estas informações a fornecedores terceiros selecionados."],
        "withdrawal": ["Pode recusar os cookies não essenciais ou retirar o seu consentimento a qualquer momento em «Definições de cookies», no rodapé.",
                       "Se não concordar, clique em «Rejeitar tudo». Pode mudar de ideias mais tarde nas definições de privacidade.",
                       "Pode recusar e retirar o seu consentimento a qualquer momento através da ligação no fundo de cada página."],
        "title": ["A sua privacidade é importante para nós.", "Bem-vindo!", "Cookies neste site"],
        "button": ["[Aceitar tudo]", "[OK]", "[Aceitar]"],
        "near": ["Mais informações na nossa política de privacidade."],
        "other": ["Envio gratuito em todas as encomendas acima de 50 euros. As encomendas feitas antes das 14h são enviadas no mesmo dia.",
                  "Subscreva a nossa newsletter e seja o primeiro a saber das novidades e dos saldos."],
    },
    "nl": {
        "purpose": ["Wij gebruiken cookies en vergelijkbare technieken om het gebruik van onze website te meten en u gepersonaliseerde advertenties te tonen.",
                    "Wij verzamelen informatie over uw apparaat en surfgedrag, zoals bezochte pagina's en klikken, om het verkeer te analyseren en onze diensten te verbeteren.",
                    "Cookies helpen ons te begrijpen hoe bezoekers deze site gebruiken en u relevantere advertenties te laten zien."],
        "third_parties": ["Een deel van deze gegevens wordt gedeeld met derden, zoals Google en Meta.",
                          "Onze partners, waaronder Google en andere bedrijven, ontvangen deze informatie en kunnen die combineren met andere gegevens.",
                          "Wij geven deze informatie door aan geselecteerde externe aanbieders."],
        "withdrawal": ["U kunt niet-noodzakelijke cookies weigeren of uw toestemming op elk moment intrekken via 'Cookie-instellingen' onderaan de pagina.",
                       "Gaat u niet akkoord, klik dan op 'Alles weigeren'. U kunt uw keuze later wijzigen in de privacy-instellingen.",
                       "U kunt weigeren en uw toestemming op elk moment intrekken via de link onderaan elke pagina."],
        "title": ["Uw privacy is belangrijk voor ons.", "Welkom!", "Cookies op deze site"],
        "button": ["[Alles accepteren]", "[OK]", "[Accepteren]"],
        "near": ["Meer informatie vindt u in ons privacybeleid."],
        "other": ["Gratis verzending voor alle bestellingen boven 50 euro. Bestellingen die vóór 14.00 uur worden geplaatst, worden dezelfde dag verzonden.",
                  "Schrijf u in voor onze nieuwsbrief en hoor als eerste over nieuwe producten en seizoensuitverkoop."],
    },
    "ja": {
        "purpose": ["当サイトでは、サイトの利用状況を測定し、お客様に合わせた広告を表示するために、Cookieおよび類似の技術を使用しています。",
                    "閲覧したページやクリックなど、お客様の端末と閲覧に関する情報を収集し、トラフィックの分析とサービスの改善に利用します。",
                    "Cookieは、訪問者が当サイトをどのように利用しているかを把握し、より関連性の高い広告を表示するのに役立ちます。"],
        "third_parties": ["これらのデータの一部は、GoogleやMetaなどの第三者と共有されます。",
                          "Googleをはじめとする当社のパートナー企業がこの情報を受け取り、他のデータと組み合わせる場合があります。",
                          "当社は、選定した外部の事業者にこの情報を提供します。"],
        "withdrawal": ["必須ではないCookieは拒否でき、フッターの「Cookie設定」からいつでも同意を撤回できます。",
                       "同意しない場合は「すべて拒否」をクリックしてください。後からプライバシー設定で変更することもできます。",
                       "同意しないこともでき、各ページ下部のリンクからいつでも同意を撤回できます。"],
        "title": ["お客様のプライバシーを大切にしています。", "ようこそ！", "このサイトのCookieについて"],
        "button": ["[すべて同意する]", "[OK]", "[同意する]"],
        "near": ["詳しくはプライバシーポリシーをご覧ください。"],
        "other": ["5,000円以上のご注文で送料無料。午後2時までのご注文は当日発送いたします。",
                  "ニュースレターに登録して、新商品やセール情報をいち早く受け取りましょう。"],
    },
}
SENT_SEP = {"ja": ""}


def gen_consent(r: random.Random, n: int):
    langs = sorted(CONSENT)
    kinds = ["complete"] * 9 + ["missing_one"] * 7 + ["missing_two"] * 2 + ["none"] * 1 + ["not_banner"] * 2
    out, seen = [], set()
    while len(out) < n:
        lang = langs[len(out) % len(langs)]
        L = CONSENT[lang]
        v = r.choice(kinds)
        if v == "not_banner":
            segs = [{"kind": "other", "text": r.choice(L["other"])}]
            if r.random() < 0.5:
                segs.append({"kind": "filler", "text": r.choice(L["button"])})
            is_banner = False
        else:
            present = ["purpose", "third_parties", "withdrawal"]
            if v == "missing_one":
                present.remove(r.choice(present))
            elif v == "missing_two":
                present = [r.choice(present)]
            elif v == "none":
                present = []
            body = [{"kind": k, "text": r.choice(L[k])} for k in present]
            if r.random() < 0.25:
                r.shuffle(body)
            if r.random() < 0.5:
                body.insert(r.randint(0, len(body)), {"kind": "filler", "text": L["near"][0]})
            segs = [{"kind": "filler", "text": r.choice(L["title"])}] + body + [{"kind": "filler", "text": r.choice(L["button"])}]
            is_banner = True
        sep = SENT_SEP.get(lang, " ")
        parts = [s["text"] for s in segs]
        if is_banner:
            text = parts[0] + "\n" + sep.join(parts[1:-1]) + "\n" + parts[-1]
        else:
            text = "\n".join(parts)
        state = s1cal.canonical_text(text)
        if state in seen:
            continue
        seen.add(state)
        item = {"lang": lang, "is_banner": is_banner, "segments": segs}
        truth = label_consent(item)
        exp = {"complete": "A", "not_banner": "C"}.get(v, "B")
        assert truth["label"] == exp, (v, truth)
        out.append({"variant": v, "lang": lang, "segments": segs, "state": state, "truth": truth})
    return out


# ------------------------------------------------------------------ wrangler

def _hex(r, n):
    return "".join(r.choice("0123456789abcdef") for _ in range(n))


def _uuid(r):
    return str(uuid.UUID(int=r.getrandbits(128)))


def _slug(r):
    return r.choice(["assets", "static", "media", "uploads", "site"]) + "-" + r.choice(["prod", "staging", "eu", "v2"])


def gen_wrangler(r: random.Random, n: int):
    variants = ["valid"] * 11 + ["missing_array"] * 2 + ["renamed_binding"] * 4 + ["empty_id"] * 2 + \
               ["missing_id_key"] * 2 + ["wrong_array"] * 1 + ["lowercase_binding"] * 1
    names = {"d1_databases": "DB", "kv_namespaces": "CACHE", "r2_buckets": "ASSETS"}
    idkey = {"d1_databases": "database_id", "kv_namespaces": "id", "r2_buckets": "bucket_name"}
    wrong = {"DB": ["DATABASE", "D1", "DB_MAIN", "MAIN_DB"], "CACHE": ["KV", "CACHE_KV", "SESSIONS", "STORE"],
             "ASSETS": ["BUCKET", "ASSET", "R2", "STATIC_ASSETS"]}
    extra = {"d1_databases": ["ANALYTICS_DB", "AUDIT_DB"], "kv_namespaces": ["SESSIONS", "FLAGS"],
             "r2_buckets": ["UPLOADS", "BACKUPS"]}
    out, seen = [], set()
    while len(out) < n:
        v = r.choice(variants)
        cfg = {"name": r.choice(["shop-api", "edge-router", "docs-site", "tracking-gw"]),
               "main": "src/index.ts", "compatibility_date": "2026-0%d-1%d" % (r.randint(1, 9), r.randint(0, 9))}

        def entry(arr, binding):
            if arr == "d1_databases":
                e = {"binding": binding, "database_name": binding.lower().replace("_", "-") + "-" + r.choice(["prod", "main"]),
                     "database_id": _uuid(r)}
            elif arr == "kv_namespaces":
                e = {"binding": binding, "id": _hex(r, 32)}
                if r.random() < 0.3:
                    e["preview_id"] = _hex(r, 32)
            else:
                e = {"binding": binding, "bucket_name": _slug(r)}
                if r.random() < 0.2:
                    e["jurisdiction"] = "eu"
            return e

        for arr, b in names.items():
            lst = [entry(arr, b)]
            if r.random() < 0.3:
                lst.append(entry(arr, r.choice(extra[arr])))
            r.shuffle(lst)
            cfg[arr] = lst
        target = r.choice(list(names))
        req = [e for e in cfg[target] if e["binding"] == names[target]][0]
        if v == "missing_array":
            del cfg[target]
        elif v == "renamed_binding":
            req["binding"] = r.choice(wrong[names[target]])
        elif v == "lowercase_binding":
            req["binding"] = names[target].lower() if r.random() < 0.5 else names[target].capitalize()
        elif v == "empty_id":
            req[idkey[target]] = ""
        elif v == "missing_id_key":
            del req[idkey[target]]
            if target == "kv_namespaces":
                req["preview_id"] = _hex(r, 32)
        elif v == "wrong_array":
            other = r.choice([a for a in names if a != target])
            cfg[target].remove(req)
            if not cfg[target]:
                del cfg[target]
            cfg[other].append(req)
        fmt = r.choice(["jsonc", "jsonc", "toml"])
        source = _to_jsonc(cfg, r) if fmt == "jsonc" else _to_toml(cfg)
        parsed = s1cal.parse_jsonc(source) if fmt == "jsonc" else tomllib.loads(source)
        assert parsed == cfg
        state = s1cal.jcs(s1cal.extract_bindings(parsed))
        if state in seen:
            continue
        seen.add(state)
        truth = label_wrangler(json.loads(state))
        assert truth["label"] == ("holds" if v == "valid" else "fails"), (v, state, truth)
        out.append({"variant": v, "source_format": fmt, "source": source, "state": state, "truth": truth})
    return out


def _to_jsonc(cfg, r):
    lines = ["{", '  // generated fixture'] if r.random() < 0.6 else ["{"]
    keys = list(cfg)
    for i, k in enumerate(keys):
        comma = "," if (i < len(keys) - 1 or r.random() < 0.4) else ""
        val = json.dumps(cfg[k], indent=2).replace("\n", "\n  ")
        if k in s1cal.BINDING_KEYS and r.random() < 0.4:
            lines.append("  /* %s */" % k.replace("_", " "))
        lines.append('  "%s": %s%s' % (k, val, comma))
    lines.append("}")
    return "\n".join(lines) + "\n"


def _toml_val(v):
    return json.dumps(v)


def _to_toml(cfg):
    lines = []
    for k, v in cfg.items():
        if not isinstance(v, list):
            lines.append("%s = %s" % (k, _toml_val(v)))
    for k, v in cfg.items():
        if isinstance(v, list):
            for e in v:
                lines.append("")
                lines.append("[[%s]]" % k)
                for ek, ev in e.items():
                    lines.append("%s = %s" % (ek, _toml_val(ev)))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ driver

GENERATORS = {"gtm-datalayer-event": (gen_gtm, 360), "multilingual-consent-banner": (gen_consent, 360),
              "wrangler-bindings": (gen_wrangler, 360)}
ALIASES = {"gtm": "gtm-datalayer-event", "consent": "multilingual-consent-banner", "wrangler": "wrangler-bindings"}


def build(rubric: str):
    fn, n = GENERATORS[rubric]
    r = random.Random(SEED[rubric])
    tok = s1cal.load_tokenizer(CHECKPOINT[rubric])
    raw = fn(r, n)
    items, dropped = [], 0
    for i, it in enumerate(raw):
        tokens = s1cal.count_state_tokens(tok, it["state"])
        if tokens > TOKEN_LIMIT[rubric]:
            dropped += 1  # would be ERROR input_over_context_limit, never scored
            continue
        row = {"id": "%s-%04d" % (rubric.split("-")[0], i), **it, "state_tokens": tokens,
               "input_digest": s1cal.sha256_text(it["state"]), "label": it["truth"]["label"]}
        items.append(row)
    cal, test = s1cal.stratified_split(items)
    d = os.path.join(s1cal.FIXTURES, rubric)
    cal_sha = s1cal.write_jsonl(os.path.join(d, "calibration.jsonl"), cal)
    test_sha = s1cal.write_jsonl(os.path.join(d, "test.jsonl"), test)
    counts = lambda rows: {k: sum(1 for x in rows if x["label"] == k) for k in sorted({x["label"] for x in rows})}
    manifest = {
        "rubric": rubric, "generator_seed": SEED[rubric], "split_seed": s1cal.SPLIT_SEED,
        "split": "stratified by label, %.0f%% calibration" % (100 * s1cal.CAL_FRACTION),
        "checkpoint_tokenizer": CHECKPOINT[rubric], "token_limit": TOKEN_LIMIT[rubric], "dropped_over_limit": dropped,
        "calibration": {"file": "calibration.jsonl", "sha256": cal_sha, "size": len(cal), "labels": counts(cal)},
        "test": {"file": "test.jsonl", "sha256": test_sha, "size": len(test), "labels": counts(test)},
        "max_state_tokens": max(x["state_tokens"] for x in items),
    }
    with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    targets = [ALIASES.get(a, a) for a in sys.argv[1:]] or list(GENERATORS)
    for t in targets:
        build(t)
