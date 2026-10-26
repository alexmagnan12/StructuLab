"""Présentation courte (3 pages), sans code : python -m structlab.brochure"""
from __future__ import annotations

import os
import tempfile

import matplotlib.pyplot as plt
import numpy as np
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import charts
from .analytics import analyze
from .identify import identify, pct, risk_reading
from .report import (ACCENT, BAD, CONTENT_W, GOOD, INK, LINE, MARGIN, MUTED, PANEL, _footer, grid_table, kpi_row,
                     styles)
from .spec import load_spec

AUTHOR = "Alexandre Magnan-Dupont"
DATE = "Octobre 2026"
EXAMPLE = "examples/phoenix_memoire.yaml"


def flow_diagram():
    steps = ["Je décris\nle payoff", "L'outil reconnaît\nle produit", "Il le décompose\nen briques",
             "Il calcule le coupon\net fait la fiche"]
    W, H = CONTENT_W, 22 * mm
    d = Drawing(W, H)
    gap = 7 * mm
    bw = (W - 3 * gap) / 4
    for i, txt in enumerate(steps):
        x = i * (bw + gap)
        d.add(Rect(x, 0, bw, H, fillColor=PANEL, strokeColor=None))
        d.add(Rect(x, H - 1.6, bw, 1.6, fillColor=ACCENT, strokeColor=None))
        d.add(String(x + 7, H - 15, str(i + 1), fontName="Sans-Bold", fontSize=13, fillColor=ACCENT))
        for j, line in enumerate(txt.split("\n")):
            d.add(String(x + 7, H - 32 - 11 * j, line, fontName="Sans", fontSize=8.6, fillColor=INK))
        if i < 3:
            ax = x + bw + 1.5
            d.add(Line(ax, H / 2, ax + gap - 4, H / 2, strokeColor=MUTED, strokeWidth=1))
            d.add(Polygon([ax + gap - 3, H / 2, ax + gap - 7, H / 2 + 3, ax + gap - 7, H / 2 - 3],
                          fillColor=MUTED, strokeColor=None))
    return d


def smile_chart(spec, path):
    u = spec.underlyings[0]
    K = np.linspace(0.5, 1.4, 200)
    F = np.exp((spec.rate - u.div) * 1.0)
    fig, ax = plt.subplots(figsize=(charts.FIG_W, charts.FIG_H))
    ax.plot(K, np.full_like(K, u.vol), color=charts.MUTED, lw=1.6, ls="--", label="Sans skew : même vol partout")
    ax.plot(K, u.implied_vol(np.log(K / F)), color=charts.BLUE, lw=2, label="Avec skew (illustratif)")
    ax.axvline(spec.redemption.barrier, color=charts.RED, lw=0.9, ls=":")
    ax.text(spec.redemption.barrier + 0.01, 0.37, "barrière\n60 %", color=charts.RED, fontsize=7, va="top")
    ax.xaxis.set_major_formatter(charts.PCT)
    ax.yaxis.set_major_formatter(charts.PCT)
    ax.set_ylim(0.08, 0.40)
    ax.set_xlabel("Strike (en % du niveau actuel)")
    ax.set_ylabel("Volatilité implicite")
    ax.set_title(f"Volatilité implicite de l'{u.name}" if u.name[0] in "AEIOU" else f"Volatilité implicite du {u.name}")
    ax.legend(loc="upper right")
    charts._save(fig, path)
    return path


def plain_terms(spec, cpn):
    ac, c, r = spec.autocall, spec.coupon, spec.redemption
    from xml.sax.saxutils import escape
    names = ", ".join(escape(u.name) for u in spec.underlyings)
    return [
        ("Sous-jacents", f"{names}. C'est toujours <b>l'indice le moins performant</b> des trois qui compte."),
        ("Durée", f"{spec.maturity:g} ans, avec un rendez-vous chaque trimestre."),
        ("Coupon", f"Versé à chaque rendez-vous si l'indice le plus faible est au-dessus de <b>{pct(c.barrier, 0)}</b> "
                   f"de son niveau de départ. Les coupons manqués sont rattrapés plus tard."),
        ("Sortie anticipée", f"Dès 1 an, si l'indice le plus faible est au-dessus de <b>{pct(ac.barrier, 0)}</b> "
                             f"(seuil qui baisse de {pct(ac.stepdown, 0)} par trimestre), le client récupère son "
                             f"capital et le produit s'arrête."),
        ("À l'échéance", f"Capital rendu si l'indice le plus faible est au-dessus de <b>{pct(r.barrier, 0)}</b>. "
                         f"Sinon, le client perd autant que la baisse de l'indice."),
        ("Marge de la banque", f"{pct(1 - spec.pricing.target_price, 0)} : l'outil cherche le coupon qui rend le "
                               f"produit juste à ce prix."),
    ]


PLAIN_BRICKS = [
    ("+", "Une obligation", "elle finance le remboursement du capital à l'échéance."),
    ("+", "Des « paris » sur chaque trimestre", "chacun paie le coupon si l'indice le plus faible est au-dessus "
                                                "du seuil : ce sont des options digitales."),
    ("±", "Une clause de sortie anticipée", "le produit s'arrête dès que le marché est assez haut."),
    ("−", "Une assurance vendue par le client", "le client vend à la banque une protection contre une forte baisse "
                                                "(un put à barrière). C'est elle qui finance le coupon."),
]

PLAIN_RISK = {
    "Volatilité": "Le client <b>vend de la volatilité</b> : si les marchés deviennent plus agités, son produit perd "
                  "de la valeur. La banque est dans la position inverse.",
    "Corrélation": "Le client <b>gagne quand les indices évoluent ensemble</b> : avec trois indices très différents, "
                   "le risque qu'un seul chute augmente.",
    "Dividendes": "La banque <b>gagne si les dividendes augmentent</b> : ils font baisser les indices, donc le "
                  "produit vaut moins pour le client.",
}


def build(out="output/StructLab_en_3_pages.pdf"):
    S = styles()
    tmp = tempfile.mkdtemp()
    spec = load_spec(EXAMPLE)
    res = analyze(spec)
    flat = load_spec(EXAMPLE)
    for u in flat.underlyings:
        u.skew = u.smile = 0.0
    res_flat = analyze(flat, with_sensitivities=False)
    cpn = res["solved"]
    info = identify(spec, cpn)

    st = []
    # ------------------------------------------------------------- page 1
    st.append(Paragraph("STRUCTLAB · PROJET PERSONNEL", S["small"]))
    st.append(Spacer(1, 4))
    st.append(Paragraph("Un assistant de structuration", S["h1"]))
    st.append(Paragraph(f"{AUTHOR} · {DATE}", S["sub"]))
    st.append(Spacer(1, 10))
    st.append(Paragraph(
        "On décrit simplement ce que fait un produit structuré. L'outil dit <b>ce que c'est</b>, <b>de quoi il est "
        "fait</b>, <b>combien il peut rapporter</b> et <b>ce qui peut mal tourner</b>, puis il prépare une fiche "
        "produit.", ParagraphStyleBig(S)))
    st.append(Spacer(1, 10))
    st.append(flow_diagram())

    st.append(Paragraph("Exemple : ce que je donne à l'outil", S["h2"]))
    st.append(grid_table([[Paragraph(a, S["cellb"]), Paragraph(b, S["cell"])] for a, b in plain_terms(spec, cpn)],
                         [36 * mm, CONTENT_W - 36 * mm], header=False))
    st.append(Spacer(1, 2))
    st.append(Paragraph("Je ne donne jamais le nom du produit : seulement ses règles.", S["small"]))

    st.append(Paragraph("Ce que l'outil répond", S["h2"]))
    answer = Table([[Paragraph("Produit reconnu", S["kpi_l"]), Paragraph("Coupon calculé", S["kpi_l"])],
                    [Paragraph(info["name"], S["kpi_v"]), Paragraph(pct(cpn) + " par an", S["kpi_v"])]],
                   colWidths=[CONTENT_W * 0.62, CONTENT_W * 0.38])
    answer.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
                                ("LINEABOVE", (0, 0), (-1, 0), 1.6, ACCENT)]))
    st.append(answer)
    st.append(Spacer(1, 6))
    st.append(Paragraph("<b>De quoi il est fait</b>, vu par le client :", S["body"]))
    st.append(Spacer(1, 3))
    rows = []
    for sign, title, txt in PLAIN_BRICKS:
        col = GOOD if sign == "+" else BAD if sign == "−" else MUTED
        rows.append([Paragraph(f'<font color="{col.hexval()}"><b>{sign}</b></font>', S["cell"]),
                     Paragraph(f"<b>{title}</b> : {txt}", S["cell"])])
    st.append(grid_table(rows, [7 * mm, CONTENT_W - 7 * mm], header=False))
    st.append(PageBreak())

    # ------------------------------------------------------------- page 2
    st.append(Paragraph("Le résultat en un coup d'œil", S["h1"]))
    st.append(Spacer(1, 6))
    st.append(kpi_row([(pct(cpn) + " / an", "Coupon qui laisse 2 % de marge à la banque"),
                       (f"{res['expected_life']:.1f} ans".replace(".", ","), "Durée de vie moyenne"),
                       (pct(1 - res["p_maturity"], 0), "Chance d'être remboursé avant l'échéance"),
                       (pct(res["p_loss"], 0), "Risque de perdre une partie du capital")], S))
    st.append(Spacer(1, 8))
    w = CONTENT_W / 2 - 2 * mm
    h = w * charts.FIG_H / charts.FIG_W
    i1 = charts.maturity_profile(spec, res, os.path.join(tmp, "p.png"))
    i2 = charts.lifetime(spec, res, os.path.join(tmp, "l.png"))
    g = Table([[Image(i1, width=w, height=h), Image(i2, width=w, height=h)]], colWidths=[CONTENT_W / 2] * 2)
    g.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    st.append(g)
    st.append(Paragraph("À gauche : ce que touche le client à l'échéance selon le niveau final. À droite : la plupart "
                        "des produits s'arrêtent tôt, à la première date de remboursement anticipé.", S["small"]))

    st.append(Paragraph("Quatre scénarios pour l'expliquer à un client", S["h2"]))
    labels = {"Hausse rapide": "Les marchés montent", "Hausse progressive": "Les marchés montent lentement",
              "Baisse modérée": "Les marchés baissent de 15 %", "Krach": "Krach de 55 %"}
    rows = [[Paragraph(x, S["cellb"]) for x in ("Si...", "Que se passe-t-il ?", "Le client récupère")]]
    for name, sc in res["scenarios"].items():
        key = name.split(" (")[0]
        col = GOOD if sc["total"] >= 1 else BAD
        what = sc["fin"].split(" (")[0].replace("Rappel automatique", "Remboursé par anticipation") \
            .replace("Maturité", "Va jusqu'à l'échéance")
        rows.append([Paragraph(labels.get(key, key), S["cell"]),
                     Paragraph(f"{what} ; coupons reçus : {pct(sc['coupons'])}", S["cellm"]),
                     Paragraph(f'<font color="{col.hexval()}"><b>{pct(sc["total"])}</b></font> du capital',
                               S["cell"])])
    st.append(grid_table(rows, [52 * mm, 88 * mm, CONTENT_W - 140 * mm]))

    st.append(Paragraph("Ce que ça veut dire pour la banque", S["h2"]))
    for label, _, ch in res["sensitivities"]:
        if label in PLAIN_RISK:
            st.append(Paragraph("• " + PLAIN_RISK[label], S["body"]))
            st.append(Spacer(1, 2))
    st.append(PageBreak())

    # ------------------------------------------------------------- page 3
    st.append(Paragraph("Pourquoi le skew change tout", S["h1"]))
    st.append(Spacer(1, 4))
    st.append(Paragraph(
        "Sur les marchés actions, une assurance contre une forte baisse coûte plus cher qu'une option sur la hausse : "
        "les investisseurs ont plus peur d'un krach qu'ils n'espèrent un envol. La volatilité implicite est donc "
        "plus élevée pour les strikes bas. C'est le <b>skew</b>.", S["body"]))
    st.append(Spacer(1, 6))
    img = smile_chart(spec, os.path.join(tmp, "s.png"))
    wd = CONTENT_W * 0.6
    st.append(Image(img, width=wd, height=wd * charts.FIG_H / charts.FIG_W))
    st.append(Spacer(1, 4))
    st.append(Paragraph(
        "Dans ce produit, le client vend une protection à 60 %, exactement là où le skew rend la volatilité la plus "
        "chère. Si on ignore le skew, on sous-estime ce que vaut cette protection, donc le coupon qu'on peut "
        "offrir. L'outil peut tourner avec ou sans skew :", S["body"]))
    st.append(Spacer(1, 5))
    hdr = [Paragraph(x, S["cellb"]) for x in ("", "Sans skew", "Avec skew")]
    rows = [hdr,
            [Paragraph("Coupon possible (même marge de 2 %)", S["cell"]), Paragraph(pct(res_flat["solved"]), S["cell"]),
             Paragraph(f"<b>{pct(cpn)}</b>", S["cell"])],
            [Paragraph("Durée de vie moyenne", S["cell"]),
             Paragraph(f"{res_flat['expected_life']:.1f} ans".replace(".", ","), S["cell"]),
             Paragraph(f"{res['expected_life']:.1f} ans".replace(".", ","), S["cell"])],
            [Paragraph("Chance de remboursement anticipé", S["cell"]),
             Paragraph(pct(1 - res_flat["p_maturity"], 0), S["cell"]),
             Paragraph(pct(1 - res["p_maturity"], 0), S["cell"])],
            [Paragraph("Risque de perte en capital", S["cell"]), Paragraph(pct(res_flat["p_loss"], 0), S["cell"]),
             Paragraph(pct(res["p_loss"], 0), S["cell"])]]
    st.append(grid_table(rows, [80 * mm, 40 * mm, CONTENT_W - 120 * mm]))
    st.append(Spacer(1, 5))
    st.append(Paragraph(
        "Deux effets jouent dans le même sens : la protection vendue par le client vaut plus cher, et, parce que la "
        "volatilité baisse quand le marché monte, le produit est plus souvent remboursé tôt.", S["body"]))

    st.append(Paragraph("Les produits que l'outil sait traiter", S["h2"]))
    prods = [("Phoenix", "coupons sous condition, avec ou sans mémoire"),
             ("Athena", "coupons accumulés, versés à la sortie"),
             ("Reverse Convertible", "coupon élevé contre un risque de baisse"),
             ("Warrant", "option cotée avec effet de levier")]
    half = len(prods) // 2
    rows = [[Paragraph(f"<b>{a}</b> — {b}", S["cell"]), Paragraph(f"<b>{c}</b> — {d}", S["cell"])]
            for (a, b), (c, d) in zip(prods[:half], prods[half:])]
    st.append(grid_table(rows, [CONTENT_W / 2] * 2, header=False))
    st.append(Spacer(1, 8))
    st.append(Paragraph("Document pédagogique. Les paramètres de marché (volatilités, skew, taux, dividendes) sont "
                        "illustratifs ; les chiffres viennent d'une simulation de 20 000 scénarios de marché.",
                        S["small"]))

    os.makedirs(os.path.dirname(out), exist_ok=True)
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=14 * mm,
                            bottomMargin=16 * mm, title="StructLab — un assistant de structuration", author=AUTHOR)
    doc.build(st, onFirstPage=_footer, onLaterPages=_footer)
    return out


def ParagraphStyleBig(S):
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle("lead", parent=S["body"], fontSize=10.5, leading=15)


if __name__ == "__main__":
    print(build())
