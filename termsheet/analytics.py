"""Prix, coupon résolu, statistiques, sensibilités et scénarios."""
from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

from .engine import AUTOCALL, MATURITY, REASON_LABEL, capital_at_maturity, evaluate, present_value
from .market import simulate_basket
from .warrant import bs, price_warrant


def price(spec, B, coupon=None, rate_bump=0.0):
    return present_value(spec, evaluate(spec, B, coupon), rate_bump).mean()


def solve_coupon(spec, B):
    """Cherche le coupon qui donne exactement le prix cible."""
    target = spec.pricing.target_price
    if target is None:
        return None
    return brentq(lambda c: price(spec, B, c) - target, 0.0, 1.0, xtol=1e-5)


def scenario_paths(spec, times):
    first = np.minimum(times / spec.obs_times[0], 1.0)
    lin = times / spec.maturity
    return {
        "Hausse rapide (+10 % dès la 1re date)": 1 + 0.10 * first,
        "Hausse progressive (+40 % à maturité)": 1 + 0.40 * lin,
        "Baisse modérée (−15 %, stable ensuite)": 1 - 0.15 * first,
        "Krach (−55 % à maturité)": 1 - 0.55 * lin,
    }


def analyze(spec, with_sensitivities=True):
    if spec.product == "warrant":
        return analyze_warrant(spec)

    times, B = simulate_basket(spec)
    solved = solve_coupon(spec, B)
    coupon = solved if solved is not None else spec.coupon.rate

    fl = evaluate(spec, B, coupon)
    pv = present_value(spec, fl)
    n, t = spec.n_obs, np.array(spec.obs_times)
    at_mat = fl.reason == MATURITY
    loss = at_mat & (fl.redemption < 1 - 1e-9)
    total = fl.cf.sum(axis=1)

    res = {
        "spec": spec, "times": times, "B_sample": B[:60], "solved": solved, "coupon_used": coupon,
        "fair_value": pv.mean(), "stderr": pv.std(ddof=1) / np.sqrt(len(pv)),
        "early_probs": np.bincount(fl.end_k[fl.reason == AUTOCALL], minlength=n) / len(pv),
        "p_maturity": at_mat.mean(), "p_loss": loss.mean(),
        "avg_loss_given_loss": (1 - fl.redemption[loss]).mean() if loss.any() else 0.0,
        "expected_life": t[fl.end_k].mean(), "expected_coupons": fl.n_coupons.mean(),
        "total_payout": total, "p_gain": (total > 1 + 1e-9).mean(),
    }

    # sensibilités : on refait le calcul avec un paramètre décalé (mêmes nombres aléatoires)
    if with_sensitivities:
        base = res["fair_value"]
        sens = []
        bumps = [("Volatilité", "+1 pt de vol", {"vol_bump": 0.01}),
                 ("Corrélation", "+10 pts", {"corr_bump": 0.10}),
                 ("Dividendes", "+0,5 % / an", {"div_bump": 0.005}),
                 ("Taux", "+0,5 %", {"rate_bump": 0.005})]
        for label, unit, kw in bumps:
            if label == "Corrélation" and spec.n_assets == 1:
                continue
            _, Bb = simulate_basket(spec, **kw)
            sens.append((label, unit, price(spec, Bb, coupon, kw.get("rate_bump", 0.0)) - base))
        res["sensitivities"] = sens

    # scénarios : une trajectoire choisie à la main
    scen = {}
    for name, path in scenario_paths(spec, times).items():
        f = evaluate(spec, path[None, :], coupon)
        k = int(f.end_k[0])
        tk = spec.obs_times[k]
        dur = f"{tk:g}".replace(".", ",") + (" an" if tk < 2 else " ans")
        scen[name] = {"path": path, "fin": f"{REASON_LABEL[int(f.reason[0])]} à {dur} (obs. {k + 1})",
                      "coupons": f.cf[0].sum() - f.redemption[0], "remboursement": f.redemption[0],
                      "total": f.cf[0].sum()}
    res["scenarios"] = scen

    # profil de remboursement à maturité
    L = np.linspace(0.0, 1.6, 321)
    c_last = coupon / spec.frequency
    cp = spec.coupon
    extra = {"conditional": np.where(L >= (cp.barrier or 0), c_last, 0.0),
             "fixed": np.full_like(L, c_last),
             "snowball": np.where(L >= (spec.autocall.level(n) if spec.autocall else 9), c_last * n, 0.0)
             }.get(cp.type, np.zeros_like(L))
    curves = {}
    if spec.redemption.monitoring == "american" and spec.redemption.type == "barrier":
        curves["Barrière jamais franchie"] = np.where(L >= spec.redemption.barrier, 1.0 + extra, np.nan)
        curves["Barrière franchie pendant la vie"] = capital_at_maturity(spec, L, np.zeros_like(L)) + extra
    else:
        curves["Remboursement à maturité"] = capital_at_maturity(spec, L, L) + extra
    res["maturity_curves"] = (L, curves)
    return res


def analyze_warrant(spec):
    w = price_warrant(spec)
    u = spec.underlyings[0]
    S, K, typ = w["spot"], w["strike"], spec.warrant.type
    grid = np.linspace(0.5 * S, 1.5 * S, 201)
    payoff = np.maximum(grid - K, 0) if typ == "call" else np.maximum(K - grid, 0)
    today = np.array([bs(s, K, spec.maturity, spec.rate, u.div, u.vol, typ) for s in grid])
    half = np.array([bs(s, K, spec.maturity / 2, spec.rate, u.div, u.vol, typ) for s in grid])
    scen = {}
    for mv in (-0.20, -0.10, 0.0, 0.10, 0.20):
        ST = S * (1 + mv)
        pay = max(ST - K, 0) if typ == "call" else max(K - ST, 0)
        scen[f"Sous-jacent {100 * mv:+.0f} % à maturité".replace(" -", " −")] = {
            "payoff": pay, "pnl": pay / w["option_price"] - 1}
    return {"spec": spec, "warrant": w, "fair_value": w["warrant_price"], "scenarios": scen,
            "curves": (grid, {"Valeur aujourd'hui": today, "Valeur à mi-vie": half, "Payoff à maturité": payoff})}
