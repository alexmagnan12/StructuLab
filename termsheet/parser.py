"""Lecture d'une description en français : « Phoenix 5 ans sur le CAC 40, coupon de 8 % par an si... »

Le texte est découpé en morceaux de phrase. Chaque morceau est rangé dans un thème
(coupon, rappel, capital) selon ses mots-clés, puis on y lit les pourcentages en
regardant les mots qui les entourent (« au-dessus de 65 % » = barrière, « 8 % par an » = taux).
Tout ce qui n'est pas précisé reçoit une valeur par défaut, affichée à l'utilisateur.
"""
from __future__ import annotations

import re
import unicodedata

# Sous-jacents connus et paramètres de marché ILLUSTRATIFS (vol ATM, dividende, skew, smile, spot)
MARKET = [
    ("Euro Stoxx Banks", ["euro stoxx banks", "eurostoxx banks", "sx7e"], (0.26, 0.060, -0.20, 0.08, 150)),
    ("Euro Stoxx 50", ["euro stoxx 50", "eurostoxx 50", "euro stoxx", "eurostoxx", "sx5e"], (0.18, 0.032, -0.25, 0.10, 5200)),
    ("S&P 500", ["s&p 500", "s&p500", "s&p", "sp500", "spx"], (0.17, 0.014, -0.28, 0.10, 6000)),
    ("Nasdaq 100", ["nasdaq 100", "nasdaq", "ndx"], (0.21, 0.008, -0.25, 0.10, 21000)),
    ("Nikkei 225", ["nikkei 225", "nikkei"], (0.20, 0.019, -0.22, 0.08, 38000)),
    ("CAC 40", ["cac 40", "cac40", "cac"], (0.17, 0.030, -0.25, 0.10, 7500)),
    ("DAX", ["dax"], (0.18, 0.028, -0.25, 0.10, 19000)),
    ("FTSE 100", ["ftse 100", "ftse"], (0.15, 0.037, -0.25, 0.10, 8200)),
    ("SMI", ["smi"], (0.14, 0.030, -0.25, 0.10, 12000)),
    ("MSCI World", ["msci world"], (0.15, 0.018, -0.25, 0.10, 3700)),
    ("LVMH", ["lvmh"], (0.28, 0.020, -0.20, 0.08, 600)),
    ("TotalEnergies", ["totalenergies", "total energies", "total"], (0.24, 0.050, -0.20, 0.08, 60)),
    ("BNP Paribas", ["bnp paribas", "bnp"], (0.28, 0.060, -0.20, 0.08, 65)),
    ("Sanofi", ["sanofi"], (0.22, 0.040, -0.18, 0.08, 95)),
    ("Airbus", ["airbus"], (0.27, 0.015, -0.20, 0.08, 160)),
    ("Schneider Electric", ["schneider electric", "schneider"], (0.26, 0.015, -0.20, 0.08, 240)),
    ("Apple", ["apple"], (0.27, 0.005, -0.20, 0.08, 230)),
    ("Microsoft", ["microsoft"], (0.24, 0.008, -0.20, 0.08, 420)),
    ("Nvidia", ["nvidia"], (0.45, 0.000, -0.15, 0.06, 130)),
    ("Tesla", ["tesla"], (0.55, 0.000, -0.12, 0.06, 250)),
]

NUM_WORDS = {"un": 1, "une": 1, "premier": 1, "premiere": 1, "1re": 1, "1er": 1, "deux": 2, "deuxieme": 2,
             "second": 2, "seconde": 2, "2e": 2, "trois": 3, "troisieme": 3, "3e": 3, "quatre": 4, "cinq": 5,
             "six": 6, "huit": 8, "dix": 10, "douze": 12}

PCT = re.compile(r"(?<![\w.,])(-?\d+(?:[.,]\d+)?)\s*(?:%|pour\s?cent)")


def fp(x, d=0):
    """Pourcentage au format français : 0.65 -> '65 %'."""
    return f"{100 * x:.{d}f}".replace(".", ",") + " %"


class ParseError(ValueError):
    pass


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    for a, b in (("’", "'"), ("≥", " >= "), ("–", "-"), ("−", "-"), (" ", " "), (" ", " ")):
        t = t.replace(a, b)
    t = re.sub(r"\bau dessus\b", "au-dessus", t)
    t = re.sub(r"\ben dessous\b", "en-dessous", t)
    return re.sub(r"[ \t]+", " ", t)


def _num(s):
    return float(s.replace(",", "."))


def _pcts(seg):
    return [(_num(m.group(1)) / 100, m.start(), m.end()) for m in PCT.finditer(seg)]


def _before(seg, pos, pattern, window=40):
    return re.search(pattern + r"[^%]{0," + str(window) + "}$", seg[max(0, pos - window - 30):pos]) is not None


def _after(seg, end, pattern, window=25):
    return re.match(r"\s*(?:" + pattern + ")", seg[end:end + window]) is not None


def _segments(t):
    out = []
    for sentence in re.split(r"\.(?!\d)|;|\n|!|\?", t):
        out += [s.strip() for s in re.split(r",(?!\d)| puis | et (?=(?:un |une |le |la |les |l'|si |a |avec |en )?"
                                            r"(?:coupon|rappel|capital|barriere|protection|remboursement))",
                                            sentence) if s.strip()]
    return out


def _topic(seg):
    if re.search(r"coupon|coupo\b|rendement|interet", seg):
        return "coupon"
    if re.search(r"rappel|autocall|anticip|rappelable|degressi|step.?down", seg):
        return "autocall"
    if re.search(r"capital|protection|protege|perte|echeance|maturite|remboursement|rembourse|barriere", seg):
        return "capital"
    return None


# ----------------------------------------------------------------------------------------------
def parse_text(text: str):
    """Renvoie (description du produit, ce qui a été compris, hypothèses par défaut)."""
    t = normalize(text)
    understood, assumed = [], []

    # --- sous-jacents ------------------------------------------------------------------------
    found, rest = [], t
    for name, aliases, params in MARKET:
        for a in sorted(aliases, key=len, reverse=True):
            m = re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", rest)
            if m:
                found.append((m.start(), name, params))
                rest = rest[:m.start()] + " " * len(a) + rest[m.end():]
                break
    if not found:
        known = ", ".join(n for n, _, _ in MARKET)
        raise ParseError(f"Je n'ai reconnu aucun sous-jacent. Sous-jacents connus : {known}.")
    found.sort()
    unders = [{"name": n, "vol": p[0], "div": p[1], "skew": p[2], "smile": p[3], "spot": p[4]} for _, n, p in found]
    understood.append(("Sous-jacent(s)", ", ".join(u["name"] for u in unders)
                       + (" — on regarde le moins performant (worst-of)" if len(unders) > 1 else "")))
    assumed.append("Volatilités, dividendes et skew : valeurs de marché illustratives intégrées à l'outil")

    # --- warrant -------------------------------------------------------------------------------
    if re.search(r"\bwarrants?\b", t):
        return _parse_warrant(t, unders[0], understood, assumed)

    # --- maturité et fréquence -------------------------------------------------------------------
    maturity = None
    for m in re.finditer(r"(\d+(?:[.,]\d+)?|un|une|deux|trois|quatre|cinq|six|huit|dix)\s*(ans|an|annees|annee|mois)\b", t):
        if re.search(r"(partir|des|apres|bout|chaque|tous les|par|fin d[eu']?\s*(la|le)?)\s*(la |le |l')?$",
                     t[max(0, m.start() - 25):m.start()]):
            continue
        v = NUM_WORDS.get(m.group(1)) or _num(m.group(1))
        maturity = v / 12 if m.group(2) == "mois" else v
        break
    if maturity is None:
        maturity = 5.0
        assumed.append("Maturité : 5 ans (non précisée)")
    understood.append(("Maturité", f"{maturity:g} ans".replace(".", ",")))

    if re.search(r"mensuel|chaque mois|tous les mois|par mois", t):
        freq = 12
    elif re.search(r"trimestri|trimestre", t):
        freq = 4
    elif re.search(r"semestri|semestre", t):
        freq = 2
    else:
        freq = 1
        if not re.search(r"annuel|chaque annee|tous les ans|par an", t):
            assumed.append("Observations : annuelles (non précisé)")
    freq_name = {1: "annual", 2: "semiannual", 4: "quarterly", 12: "monthly"}[freq]
    understood.append(("Observations", {1: "chaque année", 2: "chaque semestre", 4: "chaque trimestre",
                                        12: "chaque mois"}[freq]))

    # --- lecture des morceaux de phrase -----------------------------------------------------------
    coupon = {"type": None, "rate": None, "barrier": None, "memory": False}
    ac = {"present": False, "barrier": None, "start": None, "stepdown": 0.0, "floor": None}
    cap = {"full": False, "barrier": None, "monitoring": None}
    topic = None
    for seg in _segments(t):
        topic = _topic(seg) or topic
        if topic is None:
            continue
        pcts = _pcts(seg)

        if topic == "coupon":
            if re.search(r"accumul|cumul|boule de neige|snowball|athena|(verse|paye)\w*\s+(uniquement |seulement )?"
                         r"(au|lors du|en cas de|a la date du) (rappel|remboursement)", seg):
                coupon["type"] = "snowball"
            elif coupon["type"] != "snowball" and re.search(r"fixe|garanti|inconditionnel|quoi qu", seg):
                coupon["type"] = "fixed"
            elif coupon["type"] is None and re.search(r"\bsi\b|condition|au-dessus|superieur|barriere|seuil", seg):
                coupon["type"] = "conditional"
            if re.search(r"rappel|anticip|autocall", seg) or (
                    re.search(r"rembours", seg) and not re.search(r"echeance|maturite|a la fin", seg)):
                ac["present"] = True       # « remboursé avec un coupon » = rappel
            if re.search(r"sans (effet )?memoire", seg):
                coupon["memory"] = False
            elif re.search(r"memoire|rattrap|recupere", seg):
                coupon["memory"] = True
            for v, s, e in pcts:
                # un pourcentage lié à la protection ou au rappel, écrit dans la même phrase que le coupon
                if _before(seg, s, r"(protection|protege|capital|perte|baisse|chute)", 20):
                    cap["barrier"] = 1 - abs(v) if (v < 0 or _before(seg, s, r"(baisse|chute|perte)", 15)) else v
                    continue
                if _before(seg, s, r"(rappel|anticip|autocall)", 25):
                    ac["present"] = True
                    ac["barrier"] = v
                    continue
                per = {"par trimestre": 4, "/ ?trimestre": 4, "par semestre": 2, "par mois": 12, "mensuel": 12}
                mult = next((k for p, k in per.items() if _after(seg, e, p)), None)
                if mult:
                    coupon["rate"] = v * mult
                elif _after(seg, e, r"par an|/ ?an|annuel|p\.? ?a|l'an|par annee"):
                    coupon["rate"] = v
                elif _before(seg, s, r"(au-dessus|superieur|>=|>|barriere|seuil|niveau|au moins|plus de)"):
                    coupon["barrier"] = v
                elif coupon["rate"] is None:
                    coupon["rate"] = v
                else:
                    coupon["barrier"] = v
            if re.search(r"\bsi\b|condition", seg) and coupon["type"] == "fixed":
                coupon["type"] = "conditional"

        elif topic == "autocall":
            ac["present"] = True
            m = re.search(r"(?:partir|des|apres|bout)\D{0,20}?(\d+|un|une|premiere?|1re|1er|deux|deuxieme|2e|trois|"
                          r"troisieme|3e|quatre|cinq|six|huit|douze)\s*(?:e|er|re|eme)?\s*"
                          r"(ans?|annees?|trimestres?|semestres?|mois|dates?|observations?)", seg)
            if m:
                n = NUM_WORDS.get(m.group(1)) or int(m.group(1))
                unit = m.group(2)
                per_year = {"an": freq, "ann": freq, "tri": freq / 4, "sem": freq / 2, "moi": freq / 12}
                k = next((v for p, v in per_year.items() if unit.startswith(p)), None)
                ac["start"] = max(1, int(round(n * k))) if k else n
            for v, s, e in pcts:
                if _before(seg, s, r"(baisse|diminu|degressi|step.?down|recul|abaiss)\w*", 20):
                    step = v / freq if _after(seg, e, r"par an|/ ?an|chaque annee") and freq > 1 else v
                    ac["stepdown"] = step
                elif _before(seg, s, r"(plancher|minimum|descendre (sous|en dessous de)|jusqu'a)", 25):
                    ac["floor"] = v
                elif ac["barrier"] is None:
                    ac["barrier"] = v

        elif topic == "capital":
            if re.search(r"capital\s+(est\s+)?(integralement\s+)?(garanti|protege)\s*(a\s*100|integralement|$|,)"
                         r"|capital garanti|garanti a 100|100 ?% (du capital )?garanti", seg):
                cap["full"] = True
            if re.search(r"americ|en continu|a tout moment|pendant toute la (vie|duree)|chaque jour|quotidien", seg):
                cap["monitoring"] = "american"
            elif re.search(r"europe|a l'echeance|a maturite|seulement a|uniquement a", seg):
                cap["monitoring"] = cap["monitoring"] or "european"
            for v, s, e in pcts:
                if v < 0 or _before(seg, s, r"(baisse|chute|perte)\s*(de|jusqu'a)?", 15):
                    cap["barrier"] = 1 - abs(v)
                elif _before(seg, s, r"(au-dessus|superieur|>=|barriere|seuil|jusqu'a|protection|protege|sous|"
                                     r"niveau|au moins)"):
                    cap["barrier"] = v

    # capital garanti écrit n'importe où dans le texte
    if re.search(r"capital\s+(est\s+)?(integralement\s+)?garanti|garantie?\s+(du|en|de)\s+capital|"
                 r"capital\s+(protege|garanti)\s+a\s+100|protection\s+(du\s+|en\s+)?capital\s+(garanti|totale|"
                 r"integrale|a\s+100)|100\s*%\s*(du\s+capital\s+)?garanti", t) and cap["barrier"] is None:
        cap["full"] = True

    # --- mise en forme ------------------------------------------------------------------------------
    spec = {"maturity": maturity, "frequency": freq_name, "underlyings": unders}
    if len(unders) > 1:
        m = re.search(r"correlation\D{0,15}(\d+(?:[.,]\d+)?)\s*(%)?", t)
        if m:
            rho = _num(m.group(1))
            spec["correlation"] = rho / 100 if (m.group(2) or rho > 1) else rho
        else:
            spec["correlation"] = 0.6
            assumed.append("Corrélation entre sous-jacents : 60 %")

    market = {"rate": 0.025, "issuer_spread": 0.008}
    m = re.search(r"taux\D{0,25}?(\d+(?:[.,]\d+)?)\s*%", t)
    if m:
        market["rate"] = _num(m.group(1)) / 100
    else:
        assumed.append("Taux sans risque : 2,5 %")
    m = re.search(r"spread\D{0,25}?(\d+(?:[.,]\d+)?)\s*%", t)
    if m:
        market["issuer_spread"] = _num(m.group(1)) / 100
    else:
        assumed.append("Spread de crédit de l'émetteur : 0,8 %")
    spec["market"] = market

    # coupon
    if coupon["type"] is None and coupon["rate"] is not None:
        coupon["type"] = "conditional" if coupon["barrier"] is not None else "fixed"
    if coupon["type"] is None and coupon["barrier"] is None and not ac["present"]:
        coupon["type"] = "none"
    if coupon["type"] is None:
        coupon["type"] = "conditional" if coupon["barrier"] is not None else "snowball" if ac["present"] else "none"
    if coupon["type"] == "conditional" and coupon["barrier"] is None:
        coupon["barrier"] = cap["barrier"] or 0.7
        assumed.append(f"Barrière coupon : {fp(coupon['barrier'])} (non précisée)")
    c = {"type": coupon["type"], "rate": coupon["rate"] or 0.05}
    if coupon["type"] == "conditional":
        c["barrier"] = coupon["barrier"]
        c["memory"] = coupon["memory"]
    spec["coupon"] = c
    if coupon["type"] == "conditional":
        desc = (f"conditionnel, versé si ≥ {fp(coupon['barrier'])}"
                + (", avec mémoire" if coupon["memory"] else ", sans mémoire"))
    else:
        desc = {"fixed": "fixe, versé à chaque date", "snowball": "accumulé, versé au rappel (snowball)",
                "none": "aucun"}[coupon["type"]]
    understood.append(("Coupon", desc))

    # rappel
    if ac["present"]:
        a = {"barrier": ac["barrier"] or 1.0, "start": ac["start"] or freq, "stepdown": ac["stepdown"]}
        if ac["barrier"] is None and not re.search(r"niveau (initial|de depart|d'origine)", t):
            assumed.append("Barrière de rappel : 100 %")
        if ac["start"] is None:
            assumed.append("Premier rappel possible : au bout d'un an")
        if ac["stepdown"]:
            a["floor"] = ac["floor"] if ac["floor"] is not None else max(a["barrier"] - 0.2, 0.5)
            if ac["floor"] is None:
                assumed.append(f"Plancher de la barrière dégressive : {fp(a['floor'])}")
        spec["autocall"] = a
        understood.append(("Rappel automatique", f"si ≥ {fp(a['barrier'])}, possible à partir de "
                                                 f"l'observation {a['start']}"
                           + (f", barrière baissant de {fp(a['stepdown'], 1)} par date" if a["stepdown"] else "")))
    elif coupon["type"] == "snowball":
        # un coupon accumulé n'a de sens qu'avec un rappel : on en ajoute un, à 100 % chaque année
        spec["autocall"] = {"barrier": 1.0, "start": freq, "stepdown": 0.0}
        assumed.append("Rappel automatique ajouté : coupon accumulé versé si le sous-jacent est au-dessus de 100 % "
                       "(à partir d'un an)")
        understood.append(("Rappel automatique", "si ≥ 100 %, chaque année (implicite pour un coupon accumulé)"))

    # capital
    if cap["full"]:
        spec["redemption"] = {"type": "full"}
        understood.append(("Capital", "garanti à 100 % à l'échéance"))
    else:
        if cap["barrier"] is None:
            cap["barrier"] = 0.6
            assumed.append("Barrière de protection du capital : 60 % (non précisée)")
        mon = cap["monitoring"] or "european"
        if cap["monitoring"] is None:
            assumed.append("Barrière de capital observée à l'échéance seulement (européenne)")
        spec["redemption"] = {"type": "barrier", "barrier": cap["barrier"], "monitoring": mon}
        understood.append(("Capital", f"à risque sous {fp(cap['barrier'])} "
                                      f"({'pendant toute la vie' if mon == 'american' else 'à l échéance'})"
                           .replace("l échéance", "l'échéance")))

    # prix cible : si un coupon est donné sans marge, on calcule la valeur ; sinon on cherche le coupon
    m = re.search(r"marge\D{0,15}?(\d+(?:[.,]\d+)?)\s*%", t)
    m2 = re.search(r"(prix|emis|emission)\D{0,20}?(\d+(?:[.,]\d+)?)\s*%", t)
    rate_given = coupon["rate"] is not None
    if m or m2 or not rate_given:
        if m:
            target = 1 - _num(m.group(1)) / 100
        elif m2:
            target = _num(m2.group(2)) / 100
        else:
            target = 0.98
            assumed.append("Marge de la banque : 2 % (prix cible 98 %)")
        if coupon["type"] != "none":
            spec["pricing"] = {"target_price": target}
            understood.append(("Prix cible", f"{fp(target)} → l'outil calcule le coupon"
                               + (f" (le coupon indiqué, {fp(coupon['rate'], 1)}, sert de point de départ)"
                                  if rate_given else "")))
    else:
        understood.append(("Coupon donné", f"{fp(coupon['rate'], 1)} par an → l'outil calcule la valeur du produit "
                                           f"et la marge de la banque"))
    return spec, understood, assumed


def _parse_warrant(t, u, understood, assumed):
    kind = "put" if re.search(r"\bput\b|baissier|de vente", t) else "call"
    m = re.search(r"(\d+(?:[.,]\d+)?|un|une|deux|trois|six|douze)\s*(mois|ans?|annees?)\b", t)
    if m:
        v = NUM_WORDS.get(m.group(1)) or _num(m.group(1))
        T = v / 12 if m.group(2) == "mois" else v
    else:
        T = 1.0
        assumed.append("Maturité : 1 an")
    strike = 1.0
    m = re.search(r"strike\D{0,10}?(\d[\d ]*(?:[.,]\d+)?)\s*(%|points|pts)?", t)
    if m:
        v = _num(m.group(1).replace(" ", ""))
        strike = v / 100 if (m.group(2) == "%" or v <= 300 and u["spot"] > 1000) else v / u["spot"]
    elif not re.search(r"a la monnaie|atm", t):
        assumed.append("Strike : à la monnaie (100 %)")
    m = re.search(r"parite\D{0,10}?(\d+)", t)
    parity = int(m.group(1)) if m else (100 if u["spot"] > 1000 else 1)
    if not m:
        assumed.append(f"Parité : {parity}")
    understood += [("Produit", f"warrant {kind}"), ("Maturité", f"{T:g} an(s)".replace(".", ",")),
                   ("Strike", f"{fp(strike)} du spot ({strike * u['spot']:,.0f})".replace(",", " ")),
                   ("Parité", str(parity))]
    spec = {"maturity": T, "underlyings": [u], "market": {"rate": 0.025},
            "warrant": {"type": kind, "strike": strike, "parity": parity}}
    return spec, understood, assumed
