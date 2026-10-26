"""Génération de la mini term sheet en PDF (reportlab)."""
from __future__ import annotations

import os
import tempfile
from xml.sax.saxutils import escape as esc

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from . import charts
from .identify import identify, pct, risk_reading
from .spec import FREQ_LABEL

def _font(name):
    """Cherche la police DejaVu (Linux, ou celle fournie par matplotlib sur Mac / Windows)."""
    import matplotlib
    for d in ("/usr/share/fonts/truetype/dejavu", os.path.join(matplotlib.get_data_path(), "fonts", "ttf")):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(name)


pdfmetrics.registerFont(TTFont("Sans", _font("DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Bold", _font("DejaVuSans-Bold.ttf")))
pdfmetrics.registerFont(TTFont("Mono", _font("DejaVuSansMono.ttf")))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")

INK = colors.HexColor("#1B2433")
MUTED = colors.HexColor("#6B7385")
LINE = colors.HexColor("#DDE1E8")
PANEL = colors.HexColor("#F3F5F8")
ACCENT = colors.HexColor("#2F5D9E")
GOOD = colors.HexColor("#2A8C82")
BAD = colors.HexColor("#B54A3C")

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def styles():
    s = {}
    s["h1"] = ParagraphStyle("h1", fontName="Sans-Bold", fontSize=17, leading=21, textColor=INK, spaceAfter=2)
    s["h2"] = ParagraphStyle("h2", fontName="Sans-Bold", fontSize=10.5, leading=14, textColor=INK,
                             spaceBefore=9, spaceAfter=4)
    s["sub"] = ParagraphStyle("sub", fontName="Sans", fontSize=9, leading=12, textColor=MUTED)
    s["body"] = ParagraphStyle("body", fontName="Sans", fontSize=8.3, leading=11.2, textColor=INK, alignment=TA_LEFT)
    s["small"] = ParagraphStyle("small", fontName="Sans", fontSize=7.2, leading=9.4, textColor=MUTED)
    s["cell"] = ParagraphStyle("cell", fontName="Sans", fontSize=7.8, leading=10.2, textColor=INK)
    s["cellb"] = ParagraphStyle("cellb", parent=s["cell"], fontName="Sans-Bold")
    s["cellm"] = ParagraphStyle("cellm", parent=s["cell"], textColor=MUTED)
    s["kpi_v"] = ParagraphStyle("kpi_v", fontName="Sans-Bold", fontSize=14, leading=17, textColor=INK)
    s["kpi_l"] = ParagraphStyle("kpi_l", fontName="Sans", fontSize=7, leading=9, textColor=MUTED)
    s["tag"] = ParagraphStyle("tag", fontName="Sans", fontSize=7.4, leading=9.5, textColor=ACCENT)
    s["code"] = ParagraphStyle("code", fontName="Mono", fontSize=7.3, leading=9.4, textColor=INK)
    return s


def grid_table(rows, widths, header=True, zebra=False):
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3.5),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5), ("LEFTPADDING", (0, 0), (-1, -1), 5),
          ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), PANEL), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
    t.setStyle(TableStyle(st))
    return t


def kpi_row(items, S):
    cells = [[Paragraph(v, S["kpi_v"]), Paragraph(l, S["kpi_l"])] for v, l in items]
    w = CONTENT_W / len(items)
    inner = [Table([[c[0]], [c[1]]], colWidths=[w - 8]) for c in cells]
    for t in inner:
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    t = Table([inner], colWidths=[w] * len(items))
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("LINEBEFORE", (1, 0), (-1, 0), 0.6, colors.white),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LINEABOVE", (0, 0), (-1, 0), 1.6, ACCENT)]))
    return t


def _money(x, cur):
    return f"{x:,.2f}".replace(",", " ").replace(".", ",") + f" {cur}"


# ----------------------------------------------------------------------
def termsheet_story(spec, res, S=None, tmpdir=None, request=None) -> list:
    S = S or styles()
    tmpdir = tmpdir or tempfile.mkdtemp()
    if spec.product == "warrant":
        return _warrant_story(spec, res, S, tmpdir, request)

    cpn = res["coupon_used"]
    info = identify(spec, cpn)
    story = []
    story.append(Paragraph("FICHE PRODUIT INDICATIVE · générée automatiquement", S["small"]))
    story.append(Spacer(1, 3))
    story.append(Paragraph(info["name"], S["h1"]))
    story.append(Paragraph(esc(f"{spec.basket_label} · {spec.maturity:g} ans · {spec.currency}"), S["sub"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("  ·  ".join(info["tags"]), S["tag"]))
    story.append(Spacer(1, 8))
    story += request_box(request, S)

    # chiffres clés
    if res["solved"] is not None:
        main = (pct(cpn) + " / an", f"Coupon résolu pour un prix de {pct(spec.pricing.target_price)}")
    else:
        main = (pct(cpn) + " / an", "Coupon (donné)")
    margin = 1 - res["fair_value"]
    story.append(kpi_row([
        main,
        (pct(res["fair_value"]), f"Valeur théorique (marge implicite {pct(margin)})"),
        (f"{res['expected_life']:.1f} ans".replace(".", ","), "Durée de vie moyenne"),
        (pct(res["p_loss"], 1), "Probabilité de perte en capital"),
    ], S))

    # caractéristiques
    story.append(Paragraph("Caractéristiques", S["h2"]))
    und = "<br/>".join(f"{esc(u.name)} — vol {pct(u.vol, 0)}, div. {pct(u.div, 1)}" for u in spec.underlyings)
    rows = [["Émetteur", spec.issuer], ["Nominal", _money(spec.notional, spec.currency)],
            ["Sous-jacent(s)", und],
            ["Maturité / observations", f"{spec.maturity:g} ans · {FREQ_LABEL.get(spec.frequency)} "
                                        f"({spec.n_obs} dates)"],
            ["Marché (hypothèses)", f"taux {pct(spec.rate)}, spread émetteur {pct(spec.issuer_spread)}"
             + (f", corrélation {pct(spec.correlation, 0)}" if spec.n_assets > 1 and
                isinstance(spec.correlation, (int, float)) else "")]]
    if spec.pricing.target_price is not None:
        rows.append(["Prix d'émission cible", pct(spec.pricing.target_price)])
    story.append(grid_table([[Paragraph(a, S["cellm"]), Paragraph(b, S["cell"])] for a, b in rows],
                            [42 * mm, CONTENT_W - 42 * mm], header=False))

    story.append(Paragraph("Fonctionnement", S["h2"]))
    story.append(grid_table([[Paragraph(a, S["cellb"]), Paragraph(esc(b), S["cell"])] for a, b in info["mechanism"]],
                            [36 * mm, CONTENT_W - 36 * mm], header=False))

    story.append(Paragraph("Décomposition en briques élémentaires (vue investisseur)", S["h2"]))
    rows = [[Paragraph("", S["cellb"]), Paragraph("Brique", S["cellb"]), Paragraph("Rôle", S["cellb"])]]
    for sign, brick, expl in info["decomposition"]:
        col = GOOD if sign == "+" else BAD if sign == "−" else MUTED
        rows.append([Paragraph(f'<font color="{col.hexval()}"><b>{sign}</b></font>', S["cell"]),
                     Paragraph(esc(brick), S["cell"]), Paragraph(esc(expl), S["cellm"])])
    story.append(grid_table(rows, [7 * mm, 72 * mm, CONTENT_W - 79 * mm]))

    story.append(Paragraph("Profil et vue de marché", S["h2"]))
    rows = [["Investisseur cible", info["profile"]], ["Vue de marché", info["view"]],
            ["Environnement favorable", info["environment"]]]
    story.append(grid_table([[Paragraph(a, S["cellm"]), Paragraph(b, S["cell"])] for a, b in rows],
                            [42 * mm, CONTENT_W - 42 * mm], header=False))

    story.append(PageBreak())

    # graphiques
    w = CONTENT_W / 2 - 2 * mm
    h = w * charts.FIG_H / charts.FIG_W
    imgs = [charts.maturity_profile(spec, res, os.path.join(tmpdir, "c1.png")),
            charts.sample_paths(spec, res, os.path.join(tmpdir, "c2.png")),
            charts.lifetime(spec, res, os.path.join(tmpdir, "c3.png")),
            charts.payout_hist(spec, res, os.path.join(tmpdir, "c4.png"))]
    im = [Image(p, width=w, height=h) for p in imgs]
    gt = Table([[im[0], im[1]], [im[2], im[3]]], colWidths=[CONTENT_W / 2] * 2)
    gt.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(Paragraph("Analyse Monte Carlo", S["h2"]))
    story.append(gt)

    # scénarios
    story.append(Paragraph("Scénarios illustratifs (trajectoires déterministes du sous-jacent)", S["h2"]))
    rows = [[Paragraph(x, S["cellb"]) for x in ("Scénario", "Fin de vie", "Coupons", "Capital", "Total")]]
    for name, sc in res["scenarios"].items():
        col = GOOD.hexval() if sc["total"] >= 1 else BAD.hexval()
        rows.append([Paragraph(name, S["cell"]), Paragraph(sc["fin"], S["cellm"]),
                     Paragraph(pct(sc["coupons"]), S["cell"]), Paragraph(pct(sc["remboursement"]), S["cell"]),
                     Paragraph(f'<font color="{col}"><b>{pct(sc["total"])}</b></font>', S["cell"])])
    story.append(grid_table(rows, [58 * mm, 52 * mm, 22 * mm, 22 * mm, CONTENT_W - 154 * mm]))

    # sensibilités
    story.append(Paragraph("Sensibilités et position de risque", S["h2"]))
    rows = [[Paragraph(x, S["cellb"]) for x in ("Paramètre", "Choc", "Impact valeur", "Investisseur",
                                                 "Banque (avant couverture)")]]
    for label, unit, ch in res["sensitivities"]:
        inv, bank = risk_reading(label, ch)
        rows.append([Paragraph(label, S["cell"]), Paragraph(unit, S["cellm"]),
                     Paragraph(f"{100 * ch:+.2f} pts".replace(".", ","), S["cell"]),
                     Paragraph(inv, S["cell"]), Paragraph(bank, S["cell"])])
    story.append(grid_table(rows, [32 * mm, 26 * mm, 24 * mm, 46 * mm, CONTENT_W - 128 * mm]))

    # statistiques
    stats = [("Probabilité de rappel anticipé", pct(1 - res["p_maturity"], 1)),
             ("Probabilité d'aller à maturité", pct(res["p_maturity"], 1)),
             ("Perte moyenne si perte", pct(res["avg_loss_given_loss"], 1)),
             ("Nombre moyen de coupons", f"{res['expected_coupons']:.1f}".replace(".", ",")),
             ("Probabilité de gain (total > 100 %)", pct(res["p_gain"], 1))]
    stats.append(("Erreur Monte Carlo (1 écart-type)", f"± {pct(res['stderr'])}"))
    story.append(Paragraph("Statistiques", S["h2"]))
    half = (len(stats) + 1) // 2
    left, right = stats[:half], stats[half:] + [("", "")] * (2 * half - len(stats))
    rows = [[Paragraph(a, S["cellm"]), Paragraph(b, S["cellb"]), Paragraph(c, S["cellm"]), Paragraph(d, S["cellb"])]
            for (a, b), (c, d) in zip(left, right)]
    story.append(grid_table(rows, [52 * mm, 30 * mm, 60 * mm, CONTENT_W - 142 * mm], header=False))
    story.append(Spacer(1, 6))
    story.append(Paragraph(_disclaimer(spec), S["small"]))
    return story


def _disclaimer(spec):
    n_paths = f"{spec.pricing.paths:,}".replace(",", " ")
    return (f"Document pédagogique, sans valeur contractuelle. Valorisation Monte Carlo ({n_paths} "
            f"trajectoires, pas de {spec.pricing.steps_per_year} par an) "
            + ("en volatilité locale de Dupire déduite d'un smile paramétrique (skew pris en compte), "
               if spec.has_skew else "dans un modèle de Black-Scholes à volatilité constante (sans skew), ")
            + f"corrélation constante, taux et dividendes déterministes. "
            f"Actualisation au taux sans risque + spread émetteur. "
            f"Les paramètres de marché sont illustratifs.")


def request_box(request, S):
    """Encadré qui rappelle la demande écrite en français."""
    if not request:
        return []
    t = Table([[Paragraph("Demande", S["kpi_l"])], [Paragraph(esc(request.strip()), S["body"])]],
              colWidths=[CONTENT_W])
    t.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, -1), 1.6, ACCENT), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, -1), (-1, -1), 4)]))
    return [t, Spacer(1, 8)]


def _warrant_story(spec, res, S, tmpdir, request=None):
    from .identify import identify
    w = res["warrant"]
    info = identify(spec)
    u = spec.underlyings[0]
    story = [Paragraph("FICHE PRODUIT INDICATIVE · générée automatiquement", S["small"]), Spacer(1, 3),
             Paragraph(info["name"] + f" sur {u.name}", S["h1"]),
             Paragraph(f"Strike {w['strike']:,.0f}".replace(",", " ")
                       + f" · maturité {spec.maturity:g} an · parité {spec.warrant.parity:g}".replace(".", ","),
                       S["sub"]), Spacer(1, 8)] + request_box(request, S)
    story.append(kpi_row([(_money(w["warrant_price"], spec.currency), "Prix théorique d'un warrant"),
                          (f"× {w['leverage']:.1f}".replace(".", ","), "Effet de levier (élasticité)"),
                          (f"{w['breakeven']:,.0f}".replace(",", " "), "Point mort à maturité"),
                          (pct(w["prob_itm"], 1), "Probabilité (risque-neutre) de finir dans la monnaie")], S))
    story.append(Paragraph("Fonctionnement", S["h2"]))
    story.append(grid_table([[Paragraph(a, S["cellb"]), Paragraph(b, S["cell"])] for a, b in info["mechanism"]],
                            [36 * mm, CONTENT_W - 36 * mm], header=False))
    story.append(Paragraph("Décomposition", S["h2"]))
    story.append(grid_table([[Paragraph(s_, S["cellb"]), Paragraph(b, S["cell"]), Paragraph(e, S["cellm"])]
                             for s_, b, e in info["decomposition"]], [7 * mm, 72 * mm, CONTENT_W - 79 * mm],
                            header=False))
    img = charts.warrant_curves(spec, res, os.path.join(tmpdir, "w1.png"))
    wd = CONTENT_W * 0.62
    story.append(Spacer(1, 6))
    story.append(Image(img, width=wd, height=wd * charts.FIG_H / charts.FIG_W))
    story.append(Paragraph("Grecques (pour une option, avant parité)", S["h2"]))
    rows = [[Paragraph(x, S["cellb"]) for x in ("Delta", "Gamma", "Vega (+1 pt)", "Theta (par jour)",
                                                 "Valeur temps")],
            [Paragraph(f"{w['delta']:.3f}", S["cell"]), Paragraph(f"{w['gamma']:.5f}", S["cell"]),
             Paragraph(f"{w['vega']:.2f}", S["cell"]), Paragraph(f"{w['theta']:.2f}", S["cell"]),
             Paragraph(f"{w['time_value']:.2f}", S["cell"])]]
    story.append(grid_table(rows, [CONTENT_W / 5] * 5))
    story.append(Paragraph("Scénarios à maturité", S["h2"]))
    rows = [[Paragraph(x, S["cellb"]) for x in ("Scénario", "Payoff par option", "Rendement sur la prime")]]
    for name, sc in res["scenarios"].items():
        col = GOOD.hexval() if sc["pnl"] >= 0 else BAD.hexval()
        rows.append([Paragraph(name, S["cell"]), Paragraph(f"{sc['payoff']:,.1f}".replace(",", " "), S["cell"]),
                     Paragraph(f'<font color="{col}"><b>{100 * sc["pnl"]:+.0f} %</b></font>'.replace("-", "−"), S["cell"])])
    story.append(grid_table(rows, [70 * mm, 50 * mm, CONTENT_W - 120 * mm]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(info["profile"] + " " + info["environment"], S["body"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Document pédagogique, sans valeur contractuelle. Prix de Black-Scholes à volatilité "
                           "constante ; paramètres de marché illustratifs.", S["small"]))
    return story


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Sans", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 9 * mm, "StructLab — analyse de produits structurés")
    canvas.drawRightString(PAGE_W - MARGIN, 9 * mm, f"{doc.page}")
    canvas.restoreState()


def build_termsheet(spec, res, out_path, request=None):
    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=14 * mm, bottomMargin=16 * mm, title="Fiche produit",
                            author="StructLab")
    doc.build(termsheet_story(spec, res, request=request), onFirstPage=_footer, onLaterPages=_footer)
    return out_path
