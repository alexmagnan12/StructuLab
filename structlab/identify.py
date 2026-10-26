"""Identification du produit, décomposition en briques élémentaires et description.

L'utilisateur ne donne jamais le nom du produit : on le déduit de ses caractéristiques
(type de coupon, rappel automatique, type de remboursement, options de l'émetteur...).
"""
from __future__ import annotations

from .spec import FREQ_LABEL, Spec


def pct(x, d=2):
    if x is None:
        return "—"
    s = f"{100 * x:.{d}f}".rstrip("0").rstrip(".") if d else f"{100 * x:.0f}"
    return s.replace(".", ",") + " %"


def _family(spec: Spec) -> tuple[str, str]:
    if spec.product == "warrant":
        return "warrant", f"Warrant {spec.warrant.type.capitalize()}"
    ct, rt, ac = spec.coupon.type, spec.redemption.type, spec.autocall is not None
    if ct == "range_accrual":
        return "range_accrual", "Range Accrual"
    if ac:
        if ct == "snowball":
            return "athena", "Athena"
        if ct == "conditional":
            return "phoenix", "Phoenix Mémoire" if spec.coupon.memory else "Phoenix"
        if ct == "fixed":
            return "autocall", "Autocall à coupon fixe"
        return "autocall", "Autocall"
    if rt == "twin_win":
        return "twin_win", "Twin Win"
    if rt == "protected":
        return "protected", "Note à capital protégé" + (" avec cap" if spec.redemption.cap is not None else "")
    if rt == "barrier":
        if ct == "fixed":
            return "brc", ("Barrier Reverse Convertible" if spec.redemption.barrier < spec.redemption.strike
                           else "Reverse Convertible")
        if ct == "conditional":
            base = "Phoenix Mémoire" if spec.coupon.memory else "Phoenix"
            return "phoenix", base if spec.callable else base + " sans rappel automatique"
        return "capital_at_risk", "Note à capital à risque"
    if rt == "full" and spec.participation() > 0:
        return "protected", "Note à capital garanti"
    return "note", "Note à coupons" if ct != "none" else "Obligation zéro-coupon"


def identify(spec: Spec, coupon: float | None = None, participation: float | None = None) -> dict:
    fam, base = _family(spec)
    cpn = spec.coupon.rate if coupon is None else coupon
    part = spec.participation() if participation is None else participation

    prefix = ""
    if spec.n_assets > 1:
        prefix = {"worst_of": "Worst-of ", "best_of": "Best-of ", "average": "Panier "}.get(spec.basket, "")
    name = prefix + base
    suffix = []
    if spec.callable:
        suffix.append("Callable")
    if spec.puttable:
        suffix.append("Puttable")
    if suffix:
        name += " " + " & ".join(suffix)

    tags = []
    if spec.n_assets > 1:
        tags.append(f"{spec.n_assets} sous-jacents ({spec.basket.replace('_', '-')})")
    if spec.coupon.memory:
        tags.append("effet mémoire")
    if spec.autocall is not None:
        tags.append("rappel automatique")
        if spec.autocall.stepdown:
            tags.append("barrière dégressive (step-down)")
    if spec.redemption.barrier is not None:
        tags.append("barrière " + ("américaine" if spec.redemption.monitoring == "american" else "européenne"))
    if spec.callable:
        tags.append("rappel au gré de l'émetteur")
    if spec.puttable:
        tags.append("revente au gré de l'investisseur")
    if spec.redemption.type in ("protected", "full"):
        tags.append("capital protégé" if spec.redemption.protection >= 1 else "capital partiellement protégé")

    return {"family": fam, "name": spec.name or name, "auto_name": name, "tags": tags,
            "mechanism": mechanism(spec, cpn, part),
            "decomposition": decomposition(spec, fam, part),
            **PROFILES.get(fam, PROFILES["note"])}


# ----------------------------------------------------------------------
def mechanism(spec: Spec, cpn: float, part: float) -> list[tuple[str, str]]:
    """Description du fonctionnement, rubrique par rubrique (style term sheet)."""
    if spec.product == "warrant":
        w, u = spec.warrant, spec.underlyings[0]
        S = u.spot or 100
        K = w.strike * S
        sens = "au-dessus" if w.type == "call" else "en dessous"
        k_txt = f"{K:,.0f}".replace(",", " ")
        return [("Droit", f"Option {w.type} européenne sur {u.name}, strike {k_txt} ({pct(w.strike, 0)} du spot)."),
                ("Paiement", f"À maturité, si {u.name} termine {sens} du strike : "
                             f"(niveau final − strike)/parité versé par warrant ; sinon 0."
                             if w.type == "call" else
                             f"À maturité, si {u.name} termine {sens} du strike : "
                             f"(strike − niveau final)/parité versé par warrant ; sinon 0."),
                ("Parité", f"{w.parity:g} warrants pour 1 sous-jacent."),
                ("Perte maximale", "Le prix payé pour le warrant (pas de perte au-delà).")]

    f = spec.frequency
    per = cpn / f
    B = spec.basket_label if spec.n_assets == 1 else ("le Worst-of" if spec.basket == "worst_of" else
                                                      "le Best-of" if spec.basket == "best_of" else "le panier")
    if spec.n_assets == 1:
        B = spec.underlyings[0].name
    out = [("Observation", f"Fréquence {FREQ_LABEL.get(f, str(f))}, {spec.n_obs} dates sur {spec.maturity:g} ans. "
                           f"Niveaux exprimés en % du niveau initial.")]
    c = spec.coupon
    if c.type == "fixed":
        out.append(("Coupon", f"Coupon fixe de {pct(per)} par période ({pct(cpn)} par an), versé à chaque date "
                              f"tant que le produit est en vie."))
    elif c.type == "conditional":
        txt = (f"À chaque date, si {B} ≥ {pct(c.barrier, 0)} : coupon de {pct(per)} ({pct(cpn)} par an). "
               f"Sinon : pas de coupon.")
        if c.memory:
            txt += " Effet mémoire : les coupons non versés sont rattrapés dès que la condition est de nouveau remplie."
        out.append(("Coupon", txt))
    elif c.type == "snowball":
        bar = c.barrier if c.barrier is not None else spec.autocall.level(spec.n_obs)
        out.append(("Coupon", f"Coupon de {pct(per)} par période écoulée, versé uniquement en cas de rappel "
                              f"(ou à maturité si {B} ≥ {pct(bar, 0)}) : effet « boule de neige »."))
    elif c.type == "range_accrual":
        out.append(("Coupon", f"Coupon de {pct(cpn)} par an × proportion des jours où {B} reste dans le "
                              f"corridor [{pct(c.lower, 0)} ; {pct(c.upper, 0)}]."))
    ac = spec.autocall
    if ac:
        txt = (f"À partir de l'observation {ac.start}, si {B} ≥ {pct(ac.barrier, 0)}"
               + (f" (barrière abaissée de {pct(ac.stepdown)} à chaque date, plancher {pct(ac.floor, 0)})"
                  if ac.stepdown else "")
               + " : remboursement anticipé automatique à 100 %"
               + (" + coupons accumulés." if c.type == "snowball" else " (+ coupon de la date)."))
        out.append(("Rappel automatique", txt))
    if spec.callable:
        out.append(("Rappel émetteur", f"À partir de l'observation {spec.callable.start}, l'émetteur peut rembourser "
                                       f"le produit à {pct(spec.callable.price, 0)} à sa discrétion "
                                       f"(il le fait quand le produit lui coûte plus cher que ce prix)."))
    if spec.puttable:
        out.append(("Revente investisseur", f"À partir de l'observation {spec.puttable.start}, l'investisseur peut "
                                            f"demander le remboursement à {pct(spec.puttable.price, 0)}."))
    r = spec.redemption
    cap = f", plafonnée à +{pct(r.cap, 0)}" if r.cap is not None else ""
    up = f" + {pct(part)} de la hausse{cap}" if part > 0 else ""
    mon = ("observée en continu pendant toute la vie du produit" if r.monitoring == "american"
           else "observée uniquement à maturité")
    if r.type == "barrier":
        out.append(("Remboursement final",
                    f"Si {B} ≥ {pct(r.barrier, 0)} (barrière {mon}) : 100 % du capital{up}. "
                    f"Sinon : capital × performance finale de {B} (perte en capital, potentiellement totale)."
                    if r.monitoring == "european" else
                    f"Si la barrière de {pct(r.barrier, 0)} n'a jamais été franchie, ou si {B} termine ≥ "
                    f"{pct(r.strike, 0)} : 100 % du capital{up}. Sinon : capital × performance finale "
                    f"de {B} (perte en capital)."))
    elif r.type == "protected":
        out.append(("Remboursement final", f"{pct(r.protection, 0)} du capital garanti{up} "
                                           f"(hausse mesurée par rapport au niveau initial)."))
    elif r.type == "twin_win":
        out.append(("Remboursement final",
                    f"Si la barrière de {pct(r.barrier, 0)} n'a jamais été franchie ({mon}) : 100 % "
                    f"+ {pct(part)} de la hausse{cap}, ou + {pct(r.down_participation, 0)} de la baisse en valeur "
                    f"absolue (on gagne dans les deux sens). Si elle a été franchie : capital × performance finale."))
    else:
        out.append(("Remboursement final", f"100 % du capital{up}."))
    out.append(("Risque émetteur", "Le remboursement dépend de la solvabilité de l'émetteur (risque de crédit)."))
    return out


def decomposition(spec: Spec, fam: str, part: float) -> list[tuple[str, str, str]]:
    """Liste de (signe, brique, explication) du point de vue de l'investisseur."""
    if spec.product == "warrant":
        w = spec.warrant
        return [("+", f"{1 / w.parity:g} × {w.type.capitalize()} européen strike {pct(w.strike, 0)}",
                 "Option vanille ; prix en formule fermée de Black-Scholes.")]
    on = "sur le worst-of" if spec.basket == "worst_of" and spec.n_assets > 1 else (
        "sur le best-of" if spec.basket == "best_of" else "sur le panier" if spec.n_assets > 1 else "")
    ko = " désactivantes en cas de rappel" if spec.autocall else ""
    out = [("+", "Obligation zéro-coupon de l'émetteur",
            "Finance le remboursement du capital ; le spread de crédit de l'émetteur augmente le budget d'options.")]
    c = spec.coupon
    if c.type == "fixed":
        out.append(("+", "Strip de coupons fixes" + (" (versés tant que le produit vit)" if spec.autocall else ""),
                    "Flux certains tant que le produit n'est pas remboursé."))
    elif c.type == "conditional":
        out.append(("+", f"Strip de digitales cash-or-nothing {on} au strike {pct(c.barrier, 0)}{ko}",
                    "Chaque coupon conditionnel est une digitale" + (" ; l'effet mémoire les rend dépendantes du "
                                                                     "chemin (une digitale par date manquée)."
                                                                     if c.memory else ".")))
    elif c.type == "snowball":
        out.append(("+", f"Digitales de rappel à montant croissant {on} (k × coupon à la date k)",
                    "Le coupon n'existe qu'à travers l'événement de rappel."))
    elif c.type == "range_accrual":
        out.append(("+", f"Somme de digitales journalières en corridor {on} : "
                         f"digitale(≥ {pct(c.lower, 0)}) − digitale(> {pct(c.upper, 0)})",
                    "Chaque jour dans le corridor rapporte une fraction du coupon."))
    if spec.autocall:
        out.append(("±", f"Clause de rappel automatique à {pct(spec.autocall.barrier, 0)}",
                    "Toutes les options deviennent knock-out (autocallables) : la durée de vie est aléatoire, "
                    "ce qui réduit le coût du put vendu par l'investisseur."))
    r = spec.redemption
    if r.type == "barrier":
        if r.monitoring == "european":
            out.append(("−", f"Put down-and-in européen {on} strike {pct(r.strike, 0)}, barrière {pct(r.barrier, 0)}",
                        f"= − Put(strike {pct(r.barrier, 0)}) − {pct(r.strike - r.barrier, 0)} × digitale put"
                        f"({pct(r.barrier, 0)}). C'est cette vente d'option qui finance le rendement."))
        else:
            out.append(("−", f"Put down-and-in (DIP) {on} strike {pct(r.strike, 0)}, barrière américaine "
                             f"{pct(r.barrier, 0)}",
                        "Vendu par l'investisseur : c'est cette vente d'option qui finance le rendement."))
        if part > 0:
            out.append(("+", f"{pct(part)} × Call {on} strike {pct(r.strike, 0)}", "Participation à la hausse."))
    elif r.type == "protected":
        if part > 0:
            if r.cap is not None:
                out.append(("+", f"{pct(part)} × Call spread {on} {pct(r.strike, 0)} / {pct(r.strike + r.cap, 0)}",
                            "= Call ATM acheté − Call OTM vendu au niveau du cap (le cap réduit le coût)."))
            else:
                out.append(("+", f"{pct(part)} × Call {on} strike {pct(r.strike, 0)}", "Participation à la hausse."))
        if r.protection < 1:
            out[0] = ("+", f"Obligation zéro-coupon remboursant {pct(r.protection, 0)}",
                      "Protection partielle du capital : libère du budget pour la participation.")
    elif r.type == "twin_win":
        out.append(("+", f"{pct(part)} × Call {on} strike {pct(r.strike, 0)}", "Gain à la hausse."))
        out.append(("+", f"Put down-and-out strike {pct(r.strike, 0)}, barrière {pct(r.barrier, 0)}",
                    "Gain à la baisse tant que la barrière n'est pas touchée."))
        out.append(("−", f"Put down-and-in strike {pct(r.strike, 0)}, barrière {pct(r.barrier, 0)}",
                    "Perte en capital si la barrière est touchée. Au total : ZC + Call + Put − 2 × Put DI."))
    elif r.type == "full" and part > 0:
        out.append(("+", f"{pct(part)} × Call {on}", "Participation à la hausse."))
    if spec.callable:
        out.append(("−", f"Option bermudéenne de remboursement anticipé à {pct(spec.callable.price, 0)}",
                    "Vendue par l'investisseur à l'émetteur : elle augmente le coupon offert."))
    if spec.puttable:
        out.append(("+", f"Option bermudéenne de revente à {pct(spec.puttable.price, 0)}",
                    "Achetée par l'investisseur : liquidité garantie, mais elle réduit le rendement."))
    return out


PROFILES = {
    "phoenix": {"profile": "Investisseur recherchant un revenu régulier, prêt à risquer son capital sous la barrière.",
                "view": "Marché stable, en légère hausse ou en baisse modérée : les coupons tombent tant que le "
                        "sous-jacent reste au-dessus de la barrière coupon.",
                "environment": "Plus attractif quand la volatilité implicite et les taux sont élevés : "
                               "l'investisseur vend de la volatilité."},
    "athena": {"profile": "Investisseur neutre à haussier, prêt à attendre le rappel pour toucher un coupon élevé.",
               "view": "Marché stable ou haussier : le produit est rappelé tôt avec les coupons accumulés.",
               "environment": "Plus attractif quand la volatilité et les taux sont élevés."},
    "autocall": {"profile": "Investisseur cherchant un rendement fixe, avec un risque en capital sous la barrière.",
                 "view": "Marché stable ou haussier.",
                 "environment": "Plus attractif quand la volatilité et les taux sont élevés."},
    "brc": {"profile": "Investisseur cherchant un coupon élevé et certain, prêt à prendre le risque de baisse "
                       "sous la barrière.",
            "view": "Marché neutre : pas de krach attendu d'ici la maturité.",
            "environment": "Plus attractif quand la volatilité est élevée (le put vendu vaut cher)."},
    "range_accrual": {"profile": "Investisseur anticipant un marché sans tendance marquée.",
                      "view": "Marché stable dans un couloir : chaque jour dans le corridor rapporte du coupon.",
                      "environment": "Plus attractif quand la volatilité réalisée attendue est faible "
                                     "par rapport à la volatilité implicite."},
    "twin_win": {"profile": "Investisseur anticipant un mouvement modéré, sans savoir dans quel sens.",
                 "view": "Hausse ou baisse modérée, sans krach (sinon la barrière est touchée).",
                 "environment": "Plus attractif quand les dividendes sont élevés et la volatilité basse."},
    "protected": {"profile": "Investisseur prudent qui ne veut pas perdre son capital.",
                  "view": "Haussier à moyen terme, sans vouloir de risque en capital.",
                  "environment": "Plus attractif quand les taux sont élevés (zéro-coupon bon marché) et la "
                                 "volatilité basse (call bon marché)."},
    "capital_at_risk": {"profile": "Investisseur acceptant un risque en capital.",
                        "view": "Neutre à haussier.", "environment": "—"},
    "warrant": {"profile": "Investisseur averti cherchant un effet de levier (spéculation ou couverture).",
                "view": "Vue directionnelle forte à court terme.",
                "environment": "Moins cher quand la volatilité implicite est basse ; perte de valeur temps "
                               "chaque jour (theta)."},
    "note": {"profile": "—", "view": "—", "environment": "—"},
}

SENS_READING = {
    "Volatilité": ("long volatilité", "court volatilité"),
    "Corrélation": ("long corrélation", "court corrélation"),
    "Dividendes": ("long dividendes", "court dividendes"),
    "Taux": ("gagne si les taux montent", "perd si les taux montent"),
    "Niveau du sous-jacent": ("perd si le marché monte", "long le sous-jacent (delta positif)"),
}


def risk_reading(label: str, change: float) -> tuple[str, str]:
    """Traduit le signe d'une sensibilité en position investisseur / banque."""
    pos, neg = SENS_READING[label]
    inv = pos if change > 0 else neg
    bank = neg if change > 0 else pos
    if label == "Niveau du sous-jacent":
        inv, bank = (neg, pos) if change < 0 else (pos, neg)
        bank = "court le sous-jacent avant couverture (se couvre en achetant du delta)" if change < 0 else bank
    return inv, bank
