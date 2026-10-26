"""Construit le document de présentation de l'outil (PDF), avec un exemple complet.

    python -m structlab.demo            -> output/StructLab_presentation.pdf
"""
from __future__ import annotations

import glob
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from xml.sax.saxutils import escape as esc

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .analytics import analyze
from .cli import summary
from .identify import identify, pct
from .report import (ACCENT, CONTENT_W, INK, LINE, MARGIN, MUTED, PANEL, _footer, grid_table, styles,
                     termsheet_story)
from .spec import load_spec

AUTHOR = "Alexandre Magnan-Dupont"
DATE = "Octobre 2026"
EXAMPLE = "examples/phoenix_memoire.yaml"


def code_block(text, S, width=104):
    import textwrap
    lines = []
    for line in text.splitlines():
        if len(line) <= width:
            lines.append(line)
            continue
        indent = " " * (len(line) - len(line.lstrip()) + 4)
        lines += textwrap.wrap(line, width, subsequent_indent=indent, break_on_hyphens=False)
    pre = Preformatted("\n".join(lines), S["code"])
    t = Table([[pre]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LINEBEFORE", (0, 0), (0, -1), 1.6, ACCENT)]))
    return t


def steps_table(S):
    steps = [("1", "Décrire", "Le produit est décrit par ses caractéristiques dans un fichier YAML : coupon, "
                              "rappel, remboursement, options de l'émetteur ou de l'investisseur. Jamais par son nom."),
             ("2", "Identifier", "Des règles reconnaissent la famille (Phoenix, Athena, Autocall, Range Accrual, "
                                 "Twin Win, BRC, Warrant...) et les particularités (mémoire, step-down, callable...)."),
             ("3", "Décomposer", "Le payoff est traduit en briques élémentaires : zéro-coupon, digitales, puts à "
                                 "barrière, call spreads, options bermudéennes."),
             ("4", "Pricer", "Monte Carlo multi-actifs corrélé ; Longstaff-Schwartz pour les options callable / "
                             "puttable ; résolution du coupon (ou de la participation) pour un prix cible."),
             ("5", "Restituer", "Mini term sheet PDF : fonctionnement, briques, scénarios, probabilités, "
                                "sensibilités et lecture de la position de risque de la banque.")]
    rows = [[Paragraph(f'<font color="{ACCENT.hexval()}"><b>{n}</b></font>', S["h2"]), Paragraph(f"<b>{a}</b>", S["cell"]),
             Paragraph(b, S["cell"])] for n, a, b in steps]
    t = Table(rows, colWidths=[9 * mm, 26 * mm, CONTENT_W - 35 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


FEATURES = [
    ("Coupon", "aucun · fixe · conditionnel (barrière, effet mémoire) · snowball (Athena) · range accrual (corridor)"),
    ("Rappel automatique", "barrière de rappel, première date, step-down et plancher"),
    ("Remboursement", "barrière européenne ou américaine · capital protégé (participation, cap) · twin win · 100 %"),
    ("Options embarquées", "callable (rappel au gré de l'émetteur) · puttable (revente au gré de l'investisseur)"),
    ("Sous-jacents", "1 à n actifs, worst-of / best-of / panier, matrice de corrélation"),
    ("Warrants", "call / put, strike, parité — formule fermée de Black-Scholes et grecques"),
]


def build(out="output/StructLab_presentation.pdf"):
    S = styles()
    tmp = tempfile.mkdtemp()
    files = sorted(glob.glob("examples/*.yaml"))
    results = {}
    for f in files:
        sp = load_spec(f)
        results[f] = (sp, analyze(sp))
    spec, res = results[EXAMPLE]

    story = []
    # ---- page 1 : présentation ------------------------------------------
    story.append(Paragraph("STRUCTLAB · PROJET PERSONNEL", S["small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("De la description d'un payoff à la fiche produit", S["h1"]))
    story.append(Paragraph(f"{AUTHOR} · {DATE}", S["sub"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "StructLab est un petit outil Python qui reproduit le raisonnement d'un structureur face à une demande : "
        "on lui décrit un payoff, il <b>reconnaît le produit</b>, le <b>décompose en briques élémentaires</b>, "
        "le <b>price</b> (en résolvant le coupon pour une marge cible) et produit une <b>mini term sheet</b> avec "
        "les scénarios, les probabilités et la position de risque de la banque.", S["body"]))
    story.append(Paragraph("Le principe en cinq étapes", S["h2"]))
    story.append(steps_table(S))
    story.append(Paragraph("Ce que l'outil sait traiter", S["h2"]))
    story.append(grid_table([[Paragraph(a, S["cellb"]), Paragraph(b, S["cell"])] for a, b in FEATURES],
                            [38 * mm, CONTENT_W - 38 * mm], header=False))

    story.append(Paragraph("Les produits de la bibliothèque d'exemples", S["h2"]))
    rows = [[Paragraph(x, S["cellb"]) for x in ("Produit identifié", "Résultat clé", "Valeur", "Durée moy.",
                                                 "P(perte)")]]
    for f, (sp, r) in results.items():
        if sp.product == "warrant":
            w = r["warrant"]
            info = identify(sp)
            rows.append([Paragraph(f"{info['name']} sur {esc(sp.underlyings[0].name)}", S["cell"]),
                         Paragraph(f"levier × {w['leverage']:.1f}".replace(".", ","), S["cell"]),
                         Paragraph(f"{w['warrant_price']:.2f} {sp.currency}".replace(".", ","), S["cell"]),
                         Paragraph(f"{sp.maturity:g} an".replace(".", ","), S["cell"]), Paragraph("—", S["cell"])])
            continue
        info = identify(sp, r["coupon_used"], r["participation_used"])
        if r["solved"] is not None:
            key = ("coupon " + pct(r["solved"]) + " / an") if r["solved_which"] == "coupon" else \
                ("participation " + pct(r["solved"]))
        else:
            key = "coupon " + pct(r["coupon_used"]) + " / an (donné)"
        for lab, v in r.get("option_values", {}).items():
            key += f"<br/><font color='{MUTED.hexval()}'>{'option émetteur' if 'émetteur' in lab else 'option investisseur'}"\
                   f" : {pct(v)}</font>"
        rows.append([Paragraph(info["name"], S["cell"]), Paragraph(key, S["cell"]),
                     Paragraph(pct(r["fair_value"]), S["cell"]),
                     Paragraph(f"{r['expected_life']:.1f} ans".replace(".", ","), S["cell"]),
                     Paragraph(pct(r["p_loss"], 1), S["cell"])])
    story.append(grid_table(rows, [64 * mm, 52 * mm, 20 * mm, 20 * mm, CONTENT_W - 156 * mm]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Tous les produits « à prix cible » sont calibrés à 98 % (2 % de marge) : l'outil résout "
                           "le coupon ou la participation correspondante. Paramètres de marché illustratifs.",
                           S["small"]))
    story.append(PageBreak())

    # ---- page 2 : mode d'emploi -------------------------------------------
    story.append(Paragraph("Mode d'emploi", S["h1"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Étape 1 — décrire le produit.</b> On écrit uniquement ce que fait le payoff. "
                           "Exemple : un worst-of sur trois indices, coupon conditionnel avec mémoire, rappel "
                           "automatique dégressif, protection européenne à 60 %.", S["body"]))
    story.append(Spacer(1, 4))
    yaml_txt = open(EXAMPLE, encoding="utf-8").read().split("\n", 2)[2].strip()
    story.append(code_block(yaml_txt, S))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Étape 2 — lancer l'analyse.</b> En ligne de commande (ou depuis Python : "
                           "<font name='Mono'>load_spec → analyze → build_termsheet</font>).", S["body"]))
    story.append(Spacer(1, 4))
    buf = io.StringIO()
    with redirect_stdout(buf):
        print(summary(spec, res))
    story.append(code_block("$ python -m structlab examples/phoenix_memoire.yaml\n\n" + buf.getvalue().strip()
                            + "\n  Fiche produit : output/phoenix_memoire.pdf", S))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Étape 3 — lire la fiche produit</b> (pages suivantes) : elle est générée sans "
                           "aucune intervention manuelle à partir du fichier ci-dessus.", S["body"]))
    story.append(PageBreak())

    # ---- pages 3-4 : la fiche produit générée --------------------------------
    story += termsheet_story(spec, res, S, tmp)
    story.append(PageBreak())

    # ---- dernière page : méthode, limites, suite ------------------------------
    story.append(Paragraph("Méthode et limites", S["h1"]))
    meth = [("Dynamique", "Black-Scholes multi-actifs : lognormal, volatilité et corrélation constantes, "
                          "dividendes en rendement continu ; variables antithétiques."),
            ("Surveillance", "Grille hebdomadaire par défaut (paramétrable) : les barrières américaines et le "
                             "range accrual sont observés sur cette grille, ce qui approxime une observation "
                             "continue ou journalière."),
            ("Actualisation", "Taux sans risque + spread de financement de l'émetteur (le spread finance une partie "
                              "du coupon : le client porte le risque de crédit)."),
            ("Callable / puttable", "Longstaff-Schwartz : régression de la valeur de continuation sur le niveau du "
                                    "panier, les coupons en mémoire et l'état de la barrière ; l'émetteur rappelle "
                                    "quand la note lui coûte plus que le prix de rappel."),
            ("Résolution", "Recherche du coupon ou de la participation par Brent, à nombres aléatoires communs."),
            ("Sensibilités", "Différences finies à nombres aléatoires communs (vol, corrélation, dividendes, taux, "
                             "spot), traduites en position investisseur / banque."),
            ("Contrôles", "Les cas qui ont une formule fermée (zéro-coupon + call, reverse convertible à barrière "
                          "européenne, call spread) sont retrouvés à moins de deux écarts-types Monte Carlo.")]
    story.append(grid_table([[Paragraph(a, S["cellb"]), Paragraph(b, S["cell"])] for a, b in meth],
                            [36 * mm, CONTENT_W - 36 * mm], header=False))
    story.append(Paragraph("Limites connues", S["h2"]))
    lim = ["Skew : le smile est paramétrique (pente et courbure identiques pour toutes les maturités) et non "
           "calibré sur une vraie nappe ; sans skew, l'outil sous-estime nettement le coupon de marché.",
           "Taux déterministes : la valeur d'un callable dépend surtout des mouvements de taux, absents ici ; "
           "seule la composante actions est capturée.",
           "Pas de risque de dividendes stochastiques, ni de corrélation taux / actions.",
           "Identification par règles : un payoff hors catalogue est décrit par ses briques mais reçoit un nom "
           "générique."]
    for l in lim:
        story.append(Paragraph("• " + l, S["body"]))
    story.append(Paragraph("Prochaines étapes", S["h2"]))
    nxt = ["Calibrer la vol locale sur une vraie nappe de vol implicite (structure par terme du skew).",
           "Taux stochastiques (Hull-White) pour les callables et le range accrual sur taux.",
           "Sous-jacents hybrides (actions + taux, actions + FX) et quanto.",
           "Grecques par actif (deltas, vegas, cross-gammas) pour la couverture."]
    for l in nxt:
        story.append(Paragraph("• " + l, S["body"]))

    os.makedirs(os.path.dirname(out), exist_ok=True)
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=14 * mm,
                            bottomMargin=16 * mm, title="StructLab — présentation", author=AUTHOR)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return out


if __name__ == "__main__":
    print(build(*sys.argv[1:]))
