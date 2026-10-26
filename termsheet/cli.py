"""Ligne de commande.

    python -m termsheet                                   # mode interactif : on tape la description
    python -m termsheet "Phoenix 5 ans sur le CAC 40, coupon si le CAC est au-dessus de 70 %..."
    python -m termsheet examples/textes/phoenix.txt       # description dans un fichier texte
    python -m termsheet examples/phoenix_memoire.yaml     # description détaillée (YAML)
"""
from __future__ import annotations

import argparse
import os
import sys

from .analytics import analyze
from .identify import identify, pct
from .report import build_termsheet
from .parser import ParseError, parse_text
from .spec import load_spec, spec_from_dict


def summary(spec, res) -> str:
    lines = []
    if spec.product == "warrant":
        info = identify(spec)
        w = res["warrant"]
        lines += [f"Produit identifié : {info['name']} sur {spec.underlyings[0].name}",
                  f"  Prix d'un warrant : {w['warrant_price']:.4f} {spec.currency}  |  levier x{w['leverage']:.1f}"
                  f"  |  point mort {w['breakeven']:.0f}"]
        return "\n".join(lines)
    info = identify(spec, res["coupon_used"])
    lines.append(f"Produit identifié : {info['name']}")
    lines.append("  Caractéristiques : " + ", ".join(info["tags"]))
    lines.append("  Décomposition :")
    for s, b, _ in info["decomposition"]:
        lines.append(f"     {s} {b}")
    if res["solved"] is not None:
        lines.append(f"  Coupon résolu : {pct(res['solved'])}  (prix cible {pct(spec.pricing.target_price)})")
    lines.append(f"  Valeur théorique : {pct(res['fair_value'])} ± {pct(res['stderr'])}")
    lines.append(f"  Durée de vie moyenne : {res['expected_life']:.2f} ans".replace(".", ",") + " | P(rappel anticipé) "
                 + f"{pct(1 - res['p_maturity'], 1)} | P(perte) {pct(res['p_loss'], 1)}")
    return "\n".join(lines)


def _slug(name):
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", name)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def run(spec, label, out=None, outdir="output", request=None, pdf=True):
    res = analyze(spec)
    print(summary(spec, res))
    if pdf:
        info = identify(spec, res.get("coupon_used"))
        out = out or os.path.join(outdir, _slug(info["name"] if request else label) + ".pdf")
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        build_termsheet(spec, res, out, request=request)
        print(f"\n  Term sheet : {out}")


def run_text(text, out=None, outdir="output", pdf=True):
    try:
        d, understood, assumed = parse_text(text)
    except ParseError as e:
        print(f"Je n'ai pas compris : {e}")
        return 1
    print("\nCe que j'ai compris :")
    for k, v in understood:
        print(f"  • {k} : {v}")
    if assumed:
        print("Valeurs par défaut (non précisées dans le texte) :")
        for a in assumed:
            print(f"  • {a}")
    print()
    run(spec_from_dict(d), "produit", out, outdir, request=text, pdf=pdf)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="termsheet",
        description="Décrivez un produit structuré en français : l'outil le reconnaît, le décompose, "
                    "calcule le coupon et génère une term sheet.")
    ap.add_argument("entree", nargs="*", help="la description en texte (entre guillemets), un fichier .txt, "
                                              "ou un fichier .yaml ; rien = mode interactif")
    ap.add_argument("-o", "--output", help="chemin du PDF")
    ap.add_argument("--outdir", default="output", help="dossier des PDF (défaut : output/)")
    ap.add_argument("--no-pdf", action="store_true", help="n'affiche que le résumé")
    a = ap.parse_args(argv)

    if not a.entree:
        print("Décrivez le produit (sous-jacents, durée, coupon, rappel, protection...), puis appuyez sur Entrée :")
        return run_text(input("> "), a.output, a.outdir, not a.no_pdf)

    files = [e for e in a.entree if os.path.isfile(e)]
    if not files:                                   # du texte libre
        return run_text(" ".join(a.entree), a.output, a.outdir, not a.no_pdf)
    for f in files:
        print("=" * 72)
        print(os.path.basename(f))
        if f.endswith(".txt"):
            run_text(open(f, encoding="utf-8").read(), a.output if len(files) == 1 else None, a.outdir,
                     not a.no_pdf)
        else:
            run(load_spec(f), os.path.splitext(os.path.basename(f))[0], a.output if len(files) == 1 else None,
                a.outdir, pdf=not a.no_pdf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
