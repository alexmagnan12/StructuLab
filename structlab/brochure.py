"""Présentation courte (3 pages), sans code : python -m structlab.brochure"""
from __future__ import annotations

import os
import tempfile

import matplotlib.pyplot as plt
import numpy as np
from xml.sax.saxutils import escape as esc
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import charts
from .analytics import analyze
from .identify import identify, pct, risk_reading
from .report import (ACCENT, BAD, CONTENT_W, GOOD, INK, LINE, MARGIN, MUTED, PANEL, _footer, grid_table, kpi_row,
                     styles)
from .parser import parse_text
from .report import request_box, termsheet_story
from .spec import spec_from_dict

AUTHOR = "Alexandre Magnan-Dupont"
DATE = "Octobre 2026"
EXAMPLE = "examples/textes/phoenix.txt"


def flow_diagram():
    steps = ["J'écris le produit\nen français", "L'outil reconnaît\nle produit", "Il le décompose\nen briques",
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
    ("+", "Une obligation zéro-coupon", "pour rembourser le capital à l'échéance."),
    ("+", "Une digitale par trimestre", "qui paie le coupon si l'indice le plus faible est au-dessus de 65 %."),
    ("±", "Le rappel automatique", "qui arrête le produit dès que le marché est assez haut."),
    ("−", "Un put à barrière vendu par le client", "si j'ai bien compris, c'est ce qui finance le coupon."),
]

PLAIN_RISK = {
    "Volatilité": "Le client <b>vend de la volatilité</b> : si les marchés deviennent plus agités, son produit perd "
                  "de la valeur. La banque est dans la position inverse.",
    "Corrélation": "Le client <b>gagne quand les indices évoluent ensemble</b> : avec trois indices très différents, "
                   "le risque qu'un seul chute augmente.",
    "Dividendes": "La banque <b>gagne si les dividendes augmentent</b> : ils font baisser les indices, donc le "
                  "produit vaut moins pour le client.",
}


def build(out="output/StructuLab_en_3_pages.pdf"):
    S = styles()
    tmp = tempfile.mkdtemp()
    text = open(EXAMPLE, encoding="utf-8").read().strip()
    d, understood, _ = parse_text(text)
    spec = spec_from_dict(d)
    res = analyze(spec)
    flat = spec_from_dict(d)
    for u in flat.underlyings:
        u.skew = u.smile = 0.0
    res_flat = analyze(flat, with_sensitivities=False)
    cpn = res["solved"]
    info = identify(spec, cpn)

    st = []
    # ------------------------------------------------------------- page 1
    st.append(Paragraph("STRUCTULAB · PROJET PERSONNEL", S["small"]))
    st.append(Spacer(1, 4))
    st.append(Paragraph("Un petit outil pour m'entraîner sur les produits structurés", S["h1"]))
    st.append(Paragraph(f"{AUTHOR} · {DATE}", S["sub"]))
    st.append(Spacer(1, 10))
    st.append(Paragraph(
        "J'apprends la structuration en ce moment, et pour m'entraîner j'ai essayé de construire un petit outil : "
        "à partir d'une description en français, il tente de retrouver le produit, de le décomposer et d'estimer le "
        "coupon. C'est un projet d'apprentissage, avec sûrement des simplifications et des erreurs. J'ai été aidé "
        "par un assistant IA pour le code ; j'ai surtout cherché à comprendre chaque étape.", ParagraphStyleBig(S)))
    st.append(Spacer(1, 10))
    st.append(flow_diagram())

    st.append(Paragraph("Un exemple : la phrase que j'ai tapée", S["h2"]))
    st += request_box(text.replace("\n", " "), S)[:1]
    st.append(Spacer(1, 2))
    st.append(Paragraph("Je ne précise pas le nom du produit, seulement ses règles : c'est à l'outil de le retrouver.",
                        S["small"]))
    st.append(Paragraph("Ce que l'outil a compris", S["h2"]))
    st.append(grid_table([[Paragraph(a, S["cellb"]), Paragraph(esc(b), S["cell"])] for a, b in understood],
                         [36 * mm, CONTENT_W - 36 * mm], header=False))

    st.append(Paragraph("Le résultat", S["h2"]))
    answer = Table([[Paragraph("Produit reconnu", S["kpi_l"]), Paragraph("Coupon calculé", S["kpi_l"])],
                    [Paragraph(info["name"], S["kpi_v"]), Paragraph(pct(cpn) + " par an", S["kpi_v"])]],
                   colWidths=[CONTENT_W * 0.62, CONTENT_W * 0.38])
    answer.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
                                ("LINEABOVE", (0, 0), (-1, 0), 1.6, ACCENT)]))
    st.append(answer)
    st.append(Spacer(1, 6))
    st.append(Paragraph("<b>Comment je comprends sa décomposition</b>, côté client :", S["body"]))
    st.append(Spacer(1, 3))
    rows = []
    for sign, title, txt in PLAIN_BRICKS:
        col = GOOD if sign == "+" else BAD if sign == "−" else MUTED
        rows.append([Paragraph(f'<font color="{col.hexval()}"><b>{sign}</b></font>', S["cell"]),
                     Paragraph(f"<b>{title}</b> : {txt}", S["cell"])])
    st.append(grid_table(rows, [7 * mm, CONTENT_W - 7 * mm], header=False))
    st.append(PageBreak())

    # ------------------------------------------------------------- page 2 : la term sheet générée
    st.append(Paragraph("La term sheet que l'outil génère à partir de cette phrase, sans retouche :", S["small"]))
    st.append(Spacer(1, 6))
    st += termsheet_story(spec, res, S, tmp)
    st.append(PageBreak())

    # ------------------------------------------------------------- page 3
    st.append(Paragraph("Ce qui m'a surpris : l'effet du skew", S["h1"]))
    st.append(Spacer(1, 4))
    st.append(Paragraph(
        "Ma première version utilisait la même volatilité pour tous les strikes. J'ai ensuite ajouté un skew, "
        "de façon très simplifiée (ci-dessous, celui que j'ai utilisé pour l'Euro Stoxx 50).", S["body"]))
    st.append(Spacer(1, 6))
    img = smile_chart(spec, os.path.join(tmp, "s.png"))
    wd = CONTENT_W * 0.6
    st.append(Image(img, width=wd, height=wd * charts.FIG_H / charts.FIG_W))
    st.append(Spacer(1, 4))
    st.append(Paragraph(
        "Je m'attendais à un effet sur le coupon, mais pas à un écart aussi grand :", S["body"]))
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
        "Mon interprétation : le client vend une protection à 60 %, là où la volatilité est la plus élevée, donc "
        "cette protection vaut plus cher et laisse plus de budget pour le coupon ; et le produit serait plus souvent "
        "rappelé tôt. Mais mon smile garde la même pente pour toutes les maturités, donc je pense que l'écart est "
        "exagéré, et je ne sais pas bien en mesurer l'ampleur réelle.", S["body"]))

    st.append(Paragraph("Les questions que je me pose encore", S["h2"]))
    for q in ["L'ordre de grandeur de l'effet du skew sur le coupon est-il réaliste pour ce type de Phoenix ?",
              "Comment le skew est-il pris en compte en pratique : vol locale, vol stochastique, autre chose ?",
              "Parmi mes simplifications (smile, taux et dividendes fixes, corrélation constante), "
              "laquelle fausse le plus le résultat ?"]:
        st.append(Paragraph("• " + q, S["body"]))
        st.append(Spacer(1, 2))
    st.append(Spacer(1, 6))
    st.append(Paragraph("Pour l'instant, l'outil gère les Phoenix, les Athena, les reverse convertibles à barrière et "
                        "les warrants. Les paramètres de marché sont illustratifs et les chiffres viennent de 20 000 "
                        "scénarios simulés.", S["small"]))

    os.makedirs(os.path.dirname(out), exist_ok=True)
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=14 * mm,
                            bottomMargin=16 * mm, title="StructuLab — un assistant de structuration", author=AUTHOR)
    doc.build(st, onFirstPage=_footer, onLaterPages=_footer)
    return out


def ParagraphStyleBig(S):
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle("lead", parent=S["body"], fontSize=10.5, leading=15)


if __name__ == "__main__":
    print(build())
