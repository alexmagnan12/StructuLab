"""Ligne de commande.

    python -m structlab examples/phoenix_memoire.yaml            # analyse + fiche PDF
    python -m structlab examples/phoenix_memoire.yaml -o out.pdf
    python -m structlab examples/*.yaml --no-pdf                 # résumé console uniquement
"""
from __future__ import annotations

import argparse
import os
import sys

from .analytics import analyze
from .identify import identify, pct
from .report import build_termsheet
from .spec import load_spec


def summary(spec, res) -> str:
    lines = []
    if spec.product == "warrant":
        info = identify(spec)
        w = res["warrant"]
        lines += [f"Produit identifié : {info['name']} sur {spec.underlyings[0].name}",
                  f"  Prix d'un warrant : {w['warrant_price']:.4f} {spec.currency}  |  levier x{w['leverage']:.1f}"
                  f"  |  point mort {w['breakeven']:.0f}"]
        return "\n".join(lines)
    info = identify(spec, res["coupon_used"], res["participation_used"])
    lines.append(f"Produit identifié : {info['name']}")
    lines.append("  Caractéristiques : " + ", ".join(info["tags"]))
    lines.append("  Décomposition :")
    for s, b, _ in info["decomposition"]:
        lines.append(f"     {s} {b}")
    if res["solved"] is not None:
        lab = "Coupon résolu" if res["solved_which"] == "coupon" else "Participation résolue"
        lines.append(f"  {lab} : {pct(res['solved'])}  (prix cible {pct(spec.pricing.target_price)})")
    lines.append(f"  Valeur théorique : {pct(res['fair_value'])} ± {pct(res['stderr'])}")
    lines.append(f"  Durée de vie moyenne : {res['expected_life']:.2f} ans".replace(".", ",") + " | P(rappel anticipé) "
                 + f"{pct(1 - res['p_maturity'], 1)} | P(perte) {pct(res['p_loss'], 1)}")
    for k, v in res.get("option_values", {}).items():
        lines.append(f"  {k} : {pct(v)}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="structlab", description="Identifie, décompose et price un produit structuré "
                                                                "décrit par ses caractéristiques (YAML).")
    ap.add_argument("files", nargs="+", help="fichier(s) YAML décrivant le payoff")
    ap.add_argument("-o", "--output", help="chemin du PDF (un seul fichier en entrée)")
    ap.add_argument("--outdir", default="output", help="dossier des PDF (défaut : output/)")
    ap.add_argument("--no-pdf", action="store_true", help="n'affiche que le résumé")
    ap.add_argument("--paths", type=int, help="nombre de trajectoires Monte Carlo")
    a = ap.parse_args(argv)

    for f in a.files:
        spec = load_spec(f)
        if a.paths:
            spec.pricing.paths = a.paths
        res = analyze(spec)
        print("=" * 72)
        print(f"{os.path.basename(f)}")
        print(summary(spec, res))
        if not a.no_pdf:
            out = a.output if (a.output and len(a.files) == 1) else os.path.join(
                a.outdir, os.path.splitext(os.path.basename(f))[0] + ".pdf")
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            build_termsheet(spec, res, out)
            print(f"  Fiche produit : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
