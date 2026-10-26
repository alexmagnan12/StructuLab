"""Reconnaît le produit à partir de ses règles et le décompose en briques."""
from __future__ import annotations

from .spec import FREQ_LABEL


def pct(x, d=2):
    if x is None:
        return "—"
    s = f"{100 * x:.{d}f}".rstrip("0").rstrip(".") if d else f"{100 * x:.0f}"
    return s.replace(".", ",") + " %"


def family(spec):
    if spec.product == "warrant":
        return "warrant", f"Warrant {spec.warrant.type.capitalize()}"
    cp, ac = spec.coupon.type, spec.autocall is not None
    if ac and cp == "snowball":
        return "athena", "Athena"
    if ac and cp == "conditional":
        return "phoenix", "Phoenix Mémoire" if spec.coupon.memory else "Phoenix"
    if ac:
        return "autocall", "Autocall à coupon fixe" if cp == "fixed" else "Autocall"
    if spec.redemption.type == "barrier" and cp == "fixed":
        return "rc", "Reverse Convertible à barrière"
    if cp == "conditional":
        return "phoenix", "Phoenix sans rappel automatique"
    return "note", "Note à coupons" if cp != "none" else "Obligation zéro-coupon"


def identify(spec, coupon=None):
    fam, name = family(spec)
    if spec.n_assets > 1:
        name = "Worst-of " + name
    cpn = spec.coupon.rate if coupon is None else coupon
    tags = []
    if spec.n_assets > 1:
        tags.append(f"{spec.n_assets} sous-jacents (worst-of)")
    if spec.coupon.memory:
        tags.append("effet mémoire")
    if spec.autocall:
        tags.append("rappel automatique" + (" dégressif" if spec.autocall.stepdown else ""))
    if spec.redemption.type == "barrier":
        tags.append("barrière " + ("américaine" if spec.redemption.monitoring == "american" else "européenne"))
    if spec.has_skew:
        tags.append("skew pris en compte")
    return {"family": fam, "name": name, "tags": tags, "mechanism": mechanism(spec, cpn),
            "decomposition": decomposition(spec), **PROFILES[fam]}


def mechanism(spec, cpn):
    if spec.product == "warrant":
        w, u = spec.warrant, spec.underlyings[0]
        K = f"{w.strike * (u.spot or 100):,.0f}".replace(",", " ")
        sens = "au-dessus" if w.type == "call" else "en dessous"
        return [("Droit", f"Option {w.type} européenne sur {u.name}, strike {K} ({pct(w.strike, 0)} du spot)."),
                ("Paiement", f"À maturité, si {u.name} finit {sens} du strike : l'écart divisé par la parité ; "
                             f"sinon rien."),
                ("Parité", f"{w.parity:g} warrants pour 1 sous-jacent."),
                ("Perte maximale", "Le prix payé pour le warrant.")]

    B = "le worst-of" if spec.n_assets > 1 else spec.underlyings[0].name
    per = cpn / spec.frequency
    cp, ac, r = spec.coupon, spec.autocall, spec.redemption
    out = [("Observation", f"Fréquence {FREQ_LABEL[spec.frequency]}, {spec.n_obs} dates sur {spec.maturity:g} ans. "
                           f"Niveaux en % du niveau initial.")]
    if cp.type == "fixed":
        out.append(("Coupon", f"{pct(per)} par période ({pct(cpn)} par an), versé tant que le produit vit."))
    elif cp.type == "conditional":
        out.append(("Coupon", f"À chaque date, si {B} ≥ {pct(cp.barrier, 0)} : coupon de {pct(per)} "
                              f"({pct(cpn)} par an), sinon rien."
                    + (" Les coupons manqués sont rattrapés plus tard (mémoire)." if cp.memory else "")))
    elif cp.type == "snowball":
        out.append(("Coupon", f"{pct(per)} par période écoulée, versé seulement au rappel (ou à maturité si "
                              f"{B} ≥ {pct(ac.level(spec.n_obs), 0)})."))
    if ac:
        out.append(("Rappel automatique", f"À partir de la date {ac.start}, si {B} ≥ {pct(ac.barrier, 0)}"
                    + (f" (−{pct(ac.stepdown)} par date, plancher {pct(ac.floor, 0)})" if ac.stepdown else "")
                    + " : remboursement à 100 % et fin du produit."))
    if r.type == "barrier":
        quand = "pendant toute la vie" if r.monitoring == "american" else "à maturité"
        out.append(("Remboursement final", f"Si {B} n'est pas passé sous {pct(r.barrier, 0)} ({quand}) : 100 % du "
                                           f"capital. Sinon : capital × performance finale (perte en capital)."))
    else:
        out.append(("Remboursement final", "100 % du capital."))
    out.append(("Risque émetteur", "Le remboursement dépend de la solvabilité de l'émetteur."))
    return out


def decomposition(spec):
    if spec.product == "warrant":
        w = spec.warrant
        return [("+", f"{1 / w.parity:g} × {w.type.capitalize()} européen strike {pct(w.strike, 0)}",
                 "Option vanille, pricée avec Black-Scholes.")]
    on = " sur le worst-of" if spec.n_assets > 1 else ""
    cp, r = spec.coupon, spec.redemption
    out = [("+", "Obligation zéro-coupon de l'émetteur", "Finance le remboursement du capital.")]
    if cp.type == "fixed":
        out.append(("+", "Coupons fixes", "Flux certains tant que le produit vit."))
    elif cp.type == "conditional":
        out.append(("+", f"Digitales{on} au strike {pct(cp.barrier, 0)}",
                    "Chaque coupon conditionnel est une digitale" + (" ; la mémoire les rend dépendantes du chemin."
                                                                     if cp.memory else ".")))
    elif cp.type == "snowball":
        out.append(("+", "Digitales de rappel à montant croissant", "Le coupon n'existe qu'à travers le rappel."))
    if spec.autocall:
        out.append(("±", f"Rappel automatique à {pct(spec.autocall.barrier, 0)}",
                    "Les options s'éteignent en cas de rappel : la durée de vie devient aléatoire."))
    if r.type == "barrier":
        kind = "européen" if r.monitoring == "european" else "à barrière américaine"
        out.append(("−", f"Put down-and-in {kind}{on}, strike {pct(r.strike, 0)}, barrière {pct(r.barrier, 0)}",
                    "Vendu par l'investisseur : c'est lui qui finance le coupon."))
    return out


PROFILES = {
    "phoenix": {"profile": "Investisseur cherchant un revenu régulier, prêt à risquer son capital sous la barrière.",
                "view": "Marché stable ou en baisse modérée.",
                "environment": "Plus attractif quand la volatilité et les taux sont élevés."},
    "athena": {"profile": "Investisseur neutre à haussier, prêt à attendre le rappel.",
               "view": "Marché stable ou haussier.", "environment": "Plus attractif quand la volatilité est élevée."},
    "autocall": {"profile": "Investisseur cherchant un rendement fixe.", "view": "Marché stable ou haussier.",
                 "environment": "Plus attractif quand la volatilité est élevée."},
    "rc": {"profile": "Investisseur cherchant un coupon élevé et certain.", "view": "Pas de krach d'ici la maturité.",
           "environment": "Plus attractif quand la volatilité est élevée (le put vendu vaut cher)."},
    "warrant": {"profile": "Investisseur averti cherchant un effet de levier.",
                "view": "Vue directionnelle forte à court terme.",
                "environment": "Moins cher quand la volatilité est basse ; perd de la valeur chaque jour."},
    "note": {"profile": "—", "view": "—", "environment": "—"},
}

SENS_READING = {"Volatilité": ("long volatilité", "court volatilité"),
                "Corrélation": ("long corrélation", "court corrélation"),
                "Dividendes": ("long dividendes", "court dividendes"),
                "Taux": ("gagne si les taux montent", "perd si les taux montent")}


def risk_reading(label, change):
    """Si la valeur du produit monte quand le paramètre monte, l'investisseur est 'long' ce paramètre."""
    pos, neg = SENS_READING[label]
    return (pos, neg) if change > 0 else (neg, pos)
