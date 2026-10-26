"""Graphiques de la fiche produit (matplotlib -> PNG)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter, PercentFormatter


INK = "#1B2433"
MUTED = "#6B7385"
GRID = "#E3E6EC"
BLUE = "#2F5D9E"
TEAL = "#2A8C82"
AMBER = "#C98A1B"
RED = "#B54A3C"
LIGHT = "#A9B8D1"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlesize": 9.5, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "axes.titlelocation": "left", "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "legend.frameon": False, "legend.fontsize": 7.5,
})
PCT = PercentFormatter(1.0, decimals=0)
FIG_W, FIG_H = 4.2, 2.45


def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def maturity_profile(spec, res, path):
    L, curves = res["maturity_curves"]
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    colors = [BLUE, RED, TEAL]
    for (lab, y), col in zip(curves.items(), colors):
        ax.plot(L, y, color=col, lw=1.8, label=lab)
    ax.plot(L, L, color=MUTED, lw=0.8, ls=":", label="Détention directe du sous-jacent")
    r = spec.redemption
    for lvl, lab, col in ((r.barrier, "Barrière capital", RED),
                          (spec.coupon.barrier if spec.coupon.type == "conditional" else None, "Barrière coupon", AMBER)):
        if lvl is not None:
            ax.axvline(lvl, color=col, lw=0.9, ls="--", label=f"{lab} ({lvl:.0%})")
    ax.set_xlim(0, 1.6)
    ax.set_ylim(0, max(1.7, max(np.nanmax(v) for v in curves.values()) * 1.05))
    ax.xaxis.set_major_formatter(PCT)
    ax.yaxis.set_major_formatter(PCT)
    ax.set_xlabel("Niveau final du sous-jacent (en % du niveau initial)")
    ax.set_ylabel("Montant reçu à maturité")
    ax.set_title("Profil de remboursement à maturité")
    ax.legend(loc="lower right", fontsize=6.8)
    return _save(fig, path)


def sample_paths(spec, res, path, n=14):
    t, B = res["times"], res["B_sample"][:n]
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    for p in B:
        ax.plot(t, p, color=LIGHT, lw=0.7, alpha=0.9)
    obs = np.array(spec.obs_times)
    if spec.autocall:
        lv = [spec.autocall.level(k) if k >= spec.autocall.start else np.nan for k in range(1, spec.n_obs + 1)]
        ax.step(obs, lv, where="post", color=BLUE, lw=1.4, label="Barrière de rappel")
    if spec.coupon.type == "conditional":
        ax.axhline(spec.coupon.barrier, color=AMBER, lw=1.2, label="Barrière coupon")
    if spec.redemption.barrier is not None:
        ax.axhline(spec.redemption.barrier, color=RED, lw=1.2, ls="--", label="Barrière capital")
    for x in obs:
        ax.axvline(x, color=GRID, lw=0.5, zorder=0)
    ax.yaxis.set_major_formatter(PCT)
    ax.set_xlabel("Années")
    if ax.get_legend_handles_labels()[0]:
        ax.legend(loc="upper left", ncol=2)
    kind = "worst-of" if spec.n_assets > 1 else spec.underlyings[0].name
    ax.set_title(f"Trajectoires simulées ({kind})")
    return _save(fig, path)


def lifetime(spec, res, path):
    n = spec.n_obs
    t = np.array(spec.obs_times)
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    bottom = np.zeros(n)
    width = 0.7 / spec.frequency
    if spec.autocall:
        p = res["early_probs"]
        ax.bar(t, p, width, color=BLUE, label="Rappel automatique")
        bottom += p
    p_mat_ok = res["p_maturity"] - res["p_loss"]
    ax.bar(t[-1] + 1.3 * width, p_mat_ok, width, color=LIGHT, label="Maturité sans perte")
    ax.bar(t[-1] + 1.3 * width, res["p_loss"], width, bottom=p_mat_ok, color=RED, label="Maturité avec perte")
    ax.yaxis.set_major_formatter(PCT)
    ax.set_xlabel("Date de fin de vie (années)")
    ax.set_title("Quand le produit se termine-t-il ?")
    ax.set_ylim(0, max(bottom.max(), res["p_maturity"]) * 1.45)
    ax.set_xlim(0, t[-1] + 2.5 * width + 0.2)
    ax.legend(loc="upper center", ncol=2)
    return _save(fig, path)


def payout_hist(spec, res, path):
    tot = res["total_payout"]
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    bins = np.linspace(min(0, tot.min()), max(1.6, tot.max()), 60)
    cnt, edges = np.histogram(tot, bins=bins)
    freq = cnt / cnt.sum()
    centers = 0.5 * (edges[1:] + edges[:-1])
    ax.bar(centers, freq, width=np.diff(edges), color=np.where(centers < 1, RED, BLUE), alpha=0.85)
    ax.axvline(1.0, color=INK, lw=0.8)
    ax.xaxis.set_major_formatter(PCT)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Total reçu sur la vie du produit (coupons + capital, non actualisé)")
    ax.set_title("Distribution du montant total reçu")
    return _save(fig, path)


def warrant_curves(spec, res, path):
    grid, curves = res["curves"]
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    for (lab, y), col, ls in zip(curves.items(), [BLUE, TEAL, INK], ["-", "-", "--"]):
        ax.plot(grid, y / spec.warrant.parity, color=col, lw=1.6, ls=ls, label=lab)
    w = res["warrant"]
    ax.axvline(w["spot"], color=MUTED, lw=0.7, ls=":")
    ax.axvline(w["strike"], color=RED, lw=0.8, ls="--")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}".replace(",", " ")))
    ax.set_xlabel(f"Niveau de {spec.underlyings[0].name}")
    ax.set_ylabel(f"Prix d'un warrant ({spec.currency})")
    ax.set_title("Valeur du warrant selon le niveau du sous-jacent")
    ax.legend(loc="upper left")
    return _save(fig, path)


def scenario_paths(spec, res, path):
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    cols = [BLUE, TEAL, AMBER, RED]
    t = res["times"]
    for (name, sc), col in zip(res["scenarios"].items(), cols):
        ax.plot(t, sc["path"], color=col, lw=1.6, label=name.split(" (")[0])
    if spec.redemption.barrier is not None:
        ax.axhline(spec.redemption.barrier, color=RED, lw=0.8, ls="--")
    ax.yaxis.set_major_formatter(PCT)
    ax.set_xlabel("Années")
    ax.set_title("Scénarios illustratifs")
    ax.legend(loc="lower left")
    return _save(fig, path)
