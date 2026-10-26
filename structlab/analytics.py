"""Pricing, résolution du coupon, statistiques, sensibilités et scénarios."""
from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

from . import engine
from .engine import AUTOCALL, HOLDER_PUT, ISSUER_CALL, MATURITY
from .market import simulate_basket
from .spec import Spec
from .warrant import bs, price_warrant


def has_bermudan(spec: Spec) -> bool:
    return spec.callable is not None or spec.puttable is not None


def value(spec: Spec, times, B, coupon=None, part=None, rate_bump=0.0):
    """Valeur actuelle (par trajectoire) du produit, exercice optimal inclus."""
    policy = {}
    call_ex = put_ex = None
    if has_bermudan(spec):
        call_ex, put_ex, policy = engine.lsm_exercise(spec, times, B, coupon, part, rate_bump)
    fl = engine.evaluate(spec, times, B, coupon, part, call_ex, put_ex)
    return engine.present_value(spec, fl, rate_bump), fl, policy


def solve_parameter(spec: Spec, times, B):
    """Cherche le coupon (ou la participation) qui ramène la valeur au prix cible."""
    target = spec.pricing.target_price
    if target is None:
        return None, None
    which = spec.pricing.solve or ("coupon" if spec.coupon.type != "none" else "participation")
    if which == "coupon":
        f = lambda x: value(spec, times, B, coupon=x)[0].mean() - target
        lo, hi = 0.0, 1.0
    else:
        f = lambda x: value(spec, times, B, part=x)[0].mean() - target
        lo, hi = 0.0, 5.0
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return which, None
    return which, brentq(f, lo, hi, xtol=1e-5)


def scenario_paths(spec: Spec, times):
    T, t1 = spec.maturity, spec.obs_times[0]
    ramp1 = np.minimum(times / t1, 1.0)
    lin = times / T
    return {
        "Hausse rapide (+10 % dès la 1re date)": 1 + 0.10 * ramp1,
        "Hausse progressive (+40 % à maturité)": 1 + 0.40 * lin,
        "Baisse modérée (−15 %, stable ensuite)": 1 - 0.15 * ramp1,
        "Krach (−55 % à maturité)": 1 - 0.55 * lin,
    }


def describe_flows(spec: Spec, fl, i: int) -> dict:
    k = int(fl.end_k[i])
    t = spec.obs_times[k]
    total = fl.cf[i].sum()
    red = fl.redemption[i]
    coupons = total - red
    reason = engine.REASON_LABEL[int(fl.reason[i])]
    dur = f"{t:g}".replace(".", ",") + (" an" if t < 2 else " ans")
    return {"fin": f"{reason} à {dur} (obs. {k + 1})", "coupons": coupons,
            "remboursement": red, "total": total, "duree": t}


def analyze(spec: Spec, with_sensitivities: bool = True) -> dict:
    if spec.product == "warrant":
        return analyze_warrant(spec)

    times, B = simulate_basket(spec)
    which, solved = solve_parameter(spec, times, B)
    coupon = solved if which == "coupon" else None
    part = solved if which == "participation" else None

    pv, fl, policy = value(spec, times, B, coupon, part)
    n, t = spec.n_obs, np.array(spec.obs_times)
    res = {"spec": spec, "times": times, "B_sample": B[:60], "solved_which": which, "solved": solved,
           "coupon_used": coupon if coupon is not None else spec.coupon.rate,
           "participation_used": part if part is not None else spec.participation()}
    res["fair_value"] = pv.mean()
    res["stderr"] = pv.std(ddof=1) / np.sqrt(len(pv))

    # valeur des options de remboursement anticipé (callable / puttable)
    res["option_values"] = {}
    if has_bermudan(spec):
        for attr, label in (("callable", "Option de rappel (détenue par l'émetteur)"),
                            ("puttable", "Option de revente (détenue par l'investisseur)")):
            if getattr(spec, attr) is None:
                continue
            s2 = spec.copy()
            setattr(s2, attr, None)
            v2 = value(s2, times, B, coupon, part)[0].mean()
            res["option_values"][label] = abs(v2 - res["fair_value"])

    # --- statistiques ---------------------------------------------------
    early = {}
    for code in (AUTOCALL, ISSUER_CALL, HOLDER_PUT):
        mask = fl.reason == code
        if mask.any():
            early[code] = np.bincount(fl.end_k[mask], minlength=n) / len(pv)
    res["early_probs"] = early
    at_mat = fl.reason == MATURITY
    loss = at_mat & (fl.redemption < 1 - 1e-9)
    res["p_maturity"] = at_mat.mean()
    res["p_loss"] = loss.mean()
    res["avg_loss_given_loss"] = (1 - fl.redemption[loss]).mean() if loss.any() else 0.0
    res["p_ki"] = fl.ki.mean()
    res["expected_life"] = t[fl.end_k].mean()
    res["expected_coupons"] = fl.n_coupons.mean()
    total = fl.cf.sum(axis=1)
    res["total_payout"] = total
    life = t[fl.end_k]
    res["ann_return"] = (total - 1) / life
    res["p_gain"] = (total > 1 + 1e-9).mean()
    if spec.coupon.type == "range_accrual":
        res["avg_in_range"] = (fl.n_coupons / (fl.end_k + 1)).mean()

    # --- sensibilités (nombres aléatoires communs) ------------------------
    if with_sensitivities:
        base = res["fair_value"]
        sens = []

        def bumped(label, unit, **kw):
            rb = kw.get("rate_bump", 0.0)
            _, Bb = simulate_basket(spec, **kw)
            v = value(spec, times, Bb, coupon, part, rate_bump=rb)[0].mean()
            sens.append((label, unit, v - base))

        bumped("Volatilité", "+1 pt de vol", vol_bump=0.01)
        if spec.n_assets > 1 and spec.basket != "single":
            bumped("Corrélation", "+10 pts", corr_bump=0.10)
        bumped("Dividendes", "+0,5 % / an", div_bump=0.005)
        bumped("Taux", "+0,5 %", rate_bump=0.005)
        v = value(spec, times, B * 0.95, coupon, part)[0].mean()
        sens.append(("Niveau du sous-jacent", "−5 % sur le spot", v - base))
        res["sensitivities"] = sens

    # --- scénarios déterministes ------------------------------------------
    scen = {}
    for name, path in scenario_paths(spec, times).items():
        Bs = path[None, :]
        call_ex = put_ex = None
        if policy:
            call_ex, put_ex = engine.apply_policy(spec, policy, times, Bs, coupon, part)
        fls = engine.evaluate(spec, times, Bs, coupon, part, call_ex, put_ex)
        scen[name] = {"path": path, **describe_flows(spec, fls, 0)}
    res["scenarios"] = scen

    # --- profil de remboursement à maturité ---------------------------------
    L = np.linspace(0.0, 1.6, 321)
    p = res["participation_used"]
    curves = {}
    no_ki = engine.redemption_value(spec, L, engine.ki_flag(spec, L, L) if spec.redemption.monitoring != "american"
                                    else np.zeros_like(L, bool), p)
    c_last = (res["coupon_used"] or 0.0) / spec.frequency
    extra = np.zeros_like(L)
    if spec.coupon.type == "conditional":
        extra = np.where(L >= spec.coupon.barrier, c_last, 0.0)
    elif spec.coupon.type == "fixed":
        extra = np.full_like(L, c_last)
    elif spec.coupon.type == "snowball":
        bar = spec.coupon.barrier if spec.coupon.barrier is not None else spec.autocall.level(n)
        extra = np.where(L >= bar, c_last * n, 0.0)
    if spec.redemption.monitoring == "american" and spec.redemption.barrier is not None:
        curves["Barrière jamais franchie"] = np.where(L >= spec.redemption.barrier, no_ki + extra, np.nan)
        curves["Barrière franchie pendant la vie"] = engine.redemption_value(spec, L, np.ones_like(L, bool), p) + extra
    else:
        curves["Remboursement à maturité"] = no_ki + extra
    res["maturity_curves"] = (L, curves)
    return res


def analyze_warrant(spec: Spec) -> dict:
    w = price_warrant(spec)
    u = spec.underlyings[0]
    S, K = w["spot"], w["strike"]
    res = {"spec": spec, "warrant": w}
    grid = np.linspace(0.5 * S, 1.5 * S, 201)
    payoff = np.maximum(grid - K, 0) if spec.warrant.type == "call" else np.maximum(K - grid, 0)
    today = np.array([bs(s, K, spec.maturity, spec.rate, u.div, u.vol, spec.warrant.type) for s in grid])
    half = np.array([bs(s, K, spec.maturity / 2, spec.rate, u.div, u.vol, spec.warrant.type) for s in grid])
    res["curves"] = (grid, {"Valeur aujourd'hui": today,
                            f"Valeur à mi-vie ({spec.maturity / 2:.2g} an)": half,
                            "Payoff à maturité": payoff})
    scen = {}
    for mv in (-0.20, -0.10, 0.0, 0.10, 0.20):
        ST = S * (1 + mv)
        pay = max(ST - K, 0) if spec.warrant.type == "call" else max(K - ST, 0)
        scen[f"Sous-jacent {100 * mv:+.0f} % à maturité".replace("-", "−")] = {"payoff": pay, "pnl": pay / w["option_price"] - 1}
    res["scenarios"] = scen
    res["fair_value"] = w["warrant_price"]
    return res
