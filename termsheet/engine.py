"""Applique les règles du produit à chaque trajectoire simulée (nominal = 1).

À chaque date d'observation : 1) le coupon, 2) le rappel automatique.
À maturité : le remboursement du capital (avec ou sans barrière).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MATURITY, AUTOCALL = 0, 1
REASON_LABEL = {MATURITY: "Maturité", AUTOCALL: "Rappel automatique"}


@dataclass
class Flows:
    cf: np.ndarray          # flux payés à chaque date (trajectoires x dates)
    end_k: np.ndarray       # date de fin de vie (index)
    reason: np.ndarray      # maturité ou rappel
    redemption: np.ndarray  # capital rendu
    n_coupons: np.ndarray   # nombre de coupons touchés


def capital_at_maturity(spec, L, running_min):
    """Capital rendu à maturité selon le niveau final L du panier."""
    r = spec.redemption
    if r.type == "full":
        return np.ones_like(L)
    if r.monitoring == "american":
        hit = running_min < r.barrier
    else:
        hit = L < r.barrier
    return np.where(hit & (L < r.strike), L / r.strike, 1.0)


def evaluate(spec, B, coupon_rate=None):
    n_paths, n = B.shape[0], spec.n_obs
    spy = spec.pricing.steps_per_year
    steps = [int(round(k * spy / spec.frequency)) for k in range(1, n + 1)]
    cp = spec.coupon
    c = (cp.rate if coupon_rate is None else coupon_rate) / spec.frequency   # coupon par période
    ac = spec.autocall

    cf = np.zeros((n_paths, n))
    alive = np.ones(n_paths, dtype=bool)
    end_k = np.full(n_paths, n - 1)
    reason = np.full(n_paths, MATURITY)
    redemption = np.ones(n_paths)
    n_coupons = np.zeros(n_paths)
    missed = np.zeros(n_paths)          # coupons manqués (effet mémoire)

    for k in range(n):
        L = B[:, steps[k]]
        date = k + 1

        # 1) coupon
        if cp.type == "fixed":
            cf[alive, k] += c
            n_coupons += alive
        elif cp.type == "conditional":
            ok = L >= cp.barrier
            nb = 1 + (missed if cp.memory else 0)
            cf[:, k] += np.where(alive & ok, c * nb, 0.0)
            n_coupons += np.where(alive & ok, nb, 0.0)
            if cp.memory:
                missed = np.where(ok, 0, missed + 1)

        if k == n - 1:
            break

        # 2) rappel automatique
        if ac is not None and date >= ac.start:
            called = alive & (L >= ac.level(date))
            bonus = c * date if cp.type == "snowball" else 0.0   # Athena : coupons accumulés
            cf[called, k] += 1.0 + bonus
            if cp.type == "snowball":
                n_coupons[called] += date
            end_k[called] = k
            reason[called] = AUTOCALL
            alive &= ~called

    # 3) maturité
    L = B[:, -1]
    capital = capital_at_maturity(spec, L, B.min(axis=1))
    if cp.type == "snowball":
        win = alive & (L >= ac.level(n))
        cf[win, -1] += c * n
        n_coupons[win] += n
    cf[alive, -1] += capital[alive]
    redemption[alive] = capital[alive]
    return Flows(cf, end_k, reason, redemption, n_coupons)


def present_value(spec, flows, rate_bump=0.0):
    t = np.array(spec.obs_times)
    df = np.exp(-(spec.rate + rate_bump + spec.issuer_spread) * t)
    return flows.cf @ df
