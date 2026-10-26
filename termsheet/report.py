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
# ----------------------------------------------------------------------
# Term sheet simple : une page
# ----------------------------------------------------------------------
SCEN_LABELS = {"Hausse rapide": "Le marché monte", "Baisse modérée": "Le marché baisse de 15 %",
               "Krach": "Krach de 55 %"}


def _header(title, subtitle, request, S):
    out = [Paragraph("TERM SHEET INDICATIVE", S["small"]), Spacer(1, 3), Paragraph(esc(title), S["h1"]),
           Paragraph(esc(subtitle), S["sub"]), Spacer(1, 8)]
    return out + request_box(request, S)


def _rows(rows, S, w=38):
    return grid_table([[Paragraph(a, S["cellb"]), Paragraph(esc(b), S["cell"])] for a, b in rows],
                      [w * mm, CONTENT_W - w * mm], header=False)


def termsheet_story(spec, res, S=None, tmpdir=None, request=None) -> list:
    S = S or styles()
    tmpdir = tmpdir or tempfile.mkdtemp()
    if spec.product == "warrant":
        return _warrant_story(spec, res, S, tmpdir, request)

    cpn = res["coupon_used"]
    info = identify(spec, cpn)
    st = _header(info["name"], f"{', '.join(u.name for u in spec.underlyings)} · {spec.maturity:g} ans", request, S)

    label = "Coupon calculé" if res["solved"] is not None else "Coupon"
    margin = 1 - res["fair_value"]
    st.append(kpi_row([(pct(cpn) + " / an", label),
                       (f"{res['expected_life']:.1f} ans".replace(".", ","), "Durée de vie moyenne"),
                       (pct(res["p_loss"], 0), "Risque de perte en capital"),
                       (pct(margin, 1), "Marge de la banque")], S))

    st.append(Paragraph("Le produit", S["h2"]))
    rows = [(a, b) for a, b in info["mechanism"] if a not in ("Observation", "Risque émetteur")]
    rows.insert(0, ("Durée", f"{spec.maturity:g} ans, une date d'observation par "
                             + {1: "an", 2: "semestre", 4: "trimestre", 12: "mois"}[spec.frequency]
                             + (" ; on regarde le sous-jacent le moins performant" if spec.n_assets > 1 else "")))
    st.append(_rows(rows, S))

    st.append(Paragraph("Ce qu'il y a dedans", S["h2"]))
    for sign, brick, _ in info["decomposition"]:
        col = GOOD if sign == "+" else BAD if sign == "−" else MUTED
        st.append(Paragraph(f'<font color="{col.hexval()}"><b>{sign}</b></font>  {esc(brick)}', S["body"]))

    w = CONTENT_W * 0.52
    img = charts.maturity_profile(spec, res, os.path.join(tmpdir, "p.png"))
    rows = [[Paragraph(x, S["cellb"]) for x in ("Si…", "Le client récupère")]]
    for name, sc in res["scenarios"].items():
        key = name.split(" (")[0]
        if key not in SCEN_LABELS:
            continue
        col = GOOD if sc["total"] >= 1 else BAD
        rows.append([Paragraph(SCEN_LABELS[key], S["cell"]),
                     Paragraph(f'<font color="{col.hexval()}"><b>{pct(sc["total"])}</b></font>'
                               f'<br/><font color="{MUTED.hexval()}">{sc["fin"].split(" (")[0]}</font>', S["cell"])])
    scen = grid_table(rows, [36 * mm, CONTENT_W - w - 36 * mm - 6 * mm])
    st.append(Paragraph("À l'échéance et en exemples", S["h2"]))
    t = Table([[Image(img, width=w, height=w * charts.FIG_H / charts.FIG_W), scen]],
              colWidths=[w + 6 * mm, CONTENT_W - w - 6 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    st.append(t)

    st.append(Spacer(1, 10))
    st.append(Paragraph("Document pédagogique, sans valeur contractuelle. Coupon et probabilités calculés sur 20 000 "
                        "scénarios de marché simulés, avec des paramètres de marché illustratifs. Le remboursement "
                        "dépend aussi de la solvabilité de l'émetteur.", S["small"]))
    return st


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
    w = res["warrant"]
    info = identify(spec)
    u = spec.underlyings[0]
    st = _header(f"{info['name']} sur {u.name}", f"{spec.maturity:g} an".replace(".", ",") + f" · parité "
                 f"{spec.warrant.parity:g}", request, S)
    st.append(kpi_row([(_money(w["warrant_price"], spec.currency), "Prix d'un warrant"),
                       (f"× {w['leverage']:.1f}".replace(".", ","), "Effet de levier"),
                       (f"{w['breakeven']:,.0f}".replace(",", " "), "Point mort à l'échéance")], S))
    st.append(Paragraph("Le produit", S["h2"]))
    st.append(_rows(info["mechanism"], S))
    img = charts.warrant_curves(spec, res, os.path.join(tmpdir, "w.png"))
    wd = CONTENT_W * 0.52
    rows = [[Paragraph(x, S["cellb"]) for x in ("Si à l'échéance…", "Gain / perte")]]
    for name, sc in res["scenarios"].items():
        col = GOOD if sc["pnl"] >= 0 else BAD
        rows.append([Paragraph(name.replace(" à maturité", ""), S["cell"]),
                     Paragraph(f'<font color="{col.hexval()}"><b>{100 * sc["pnl"]:+.0f} %</b></font>'
                               .replace("-", "−"), S["cell"])])
    t = Table([[Image(img, width=wd, height=wd * charts.FIG_H / charts.FIG_W),
                grid_table(rows, [40 * mm, CONTENT_W - wd - 46 * mm])]], colWidths=[wd + 6 * mm, CONTENT_W - wd - 6 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    st.append(Paragraph("En exemples", S["h2"]))
    st.append(t)
    st.append(Spacer(1, 10))
    st.append(Paragraph("Document pédagogique, sans valeur contractuelle. Prix de Black-Scholes avec des paramètres "
                        "de marché illustratifs. La perte maximale est le prix payé.", S["small"]))
    return st


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Sans", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 9 * mm, "TermSheet Builder — projet personnel")
    canvas.drawRightString(PAGE_W - MARGIN, 9 * mm, f"{doc.page}")
    canvas.restoreState()


def build_termsheet(spec, res, out_path, request=None):
    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=14 * mm, bottomMargin=16 * mm, title="Fiche produit",
                            author="TermSheet Builder")
    doc.build(termsheet_story(spec, res, request=request), onFirstPage=_footer, onLaterPages=_footer)
    return out_path
