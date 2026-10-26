"""Moteur de flux : applique les règles du produit à chaque trajectoire simulée.

Toutes les règles sont exprimées en % du nominal (nominal = 1). À chaque date
d'observation on traite, dans l'ordre :
  1. le coupon (fixe, conditionnel avec mémoire, snowball, range accrual) ;
  2. le rappel automatique (autocall, avec step-down éventuel) ;
  3. le rappel de l'émetteur (callable) ou la revente par l'investisseur (puttable) ;
  4. à maturité : le remboursement (barrière, capital protégé, twin win).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .spec import Spec

MATURITY, AUTOCALL, ISSUER_CALL, HOLDER_PUT = 0, 1, 2, 3
REASON_LABEL = {MATURITY: "Maturité", AUTOCALL: "Rappel automatique",
                ISSUER_CALL: "Rappel émetteur", HOLDER_PUT: "Revente investisseur"}


@dataclass
class Flows:
    cf: np.ndarray          # (paths, n_obs) flux versés à chaque date (non actualisés)
    end_k: np.ndarray       # index (0-based) de la date de fin de vie
    reason: np.ndarray      # motif de fin de vie
    ki: np.ndarray          # barrière de protection franchie (à maturité)
    final_level: np.ndarray # niveau du panier à la dernière date de vie
    n_coupons: np.ndarray   # nombre de coupons (ou fraction pour range accrual) payés
    redemption: np.ndarray  # montant de remboursement du capital
    features: dict          # variables d'état à chaque date (pour la régression LSM)


def ki_flag(spec: Spec, path_min: np.ndarray, final: np.ndarray) -> np.ndarray:
    red = spec.redemption
    if red.barrier is None:
        return np.zeros_like(final, dtype=bool)
    if red.monitoring == "american":
        return path_min < red.barrier
    return final < red.barrier


def redemption_value(spec: Spec, L: np.ndarray, ki: np.ndarray, participation: float) -> np.ndarray:
    """Remboursement du capital à maturité (hors coupon) en fonction du niveau final L."""
    red = spec.redemption
    K = red.strike
    up = np.maximum(L - K, 0.0)
    if red.cap is not None:
        up = np.minimum(up, red.cap)
    if red.type == "full":
        return 1.0 + participation * up
    if red.type == "protected":
        return red.protection + participation * up
    if red.type == "barrier":
        loss = ki & (L < K)
        return np.where(loss, L / K, 1.0 + participation * up)
    if red.type == "twin_win":
        down_gain = red.down_participation * np.maximum(K - L, 0.0)
        return np.where(ki, np.where(L < K, L / K, 1.0 + participation * up),
                        1.0 + participation * up + down_gain)
    raise ValueError(red.type)


def evaluate(spec: Spec, times: np.ndarray, B: np.ndarray, coupon_rate: float | None = None,
             participation: float | None = None, call_ex: np.ndarray | None = None,
             put_ex: np.ndarray | None = None) -> Flows:
    n_paths = B.shape[0]
    n = spec.n_obs
    spy = spec.pricing.steps_per_year
    step_of = [int(round(k * spy / spec.frequency)) for k in range(1, n + 1)]

    cpn = spec.coupon
    c = (spec.coupon.rate if coupon_rate is None else coupon_rate) / spec.frequency
    part = spec.participation() if participation is None else participation
    ac = spec.autocall

    cf = np.zeros((n_paths, n))
    alive = np.ones(n_paths, dtype=bool)
    end_k = np.full(n_paths, n - 1)
    reason = np.full(n_paths, MATURITY)
    memory = np.zeros(n_paths)
    n_coupons = np.zeros(n_paths)
    final_level = B[:, -1].copy()
    redemption = np.zeros(n_paths)
    running_min = np.minimum.accumulate(B, axis=1)

    feat = {"level": np.zeros((n_paths, n)), "memory": np.zeros((n_paths, n)),
            "ki": np.zeros((n_paths, n))}

    for k in range(n):
        j = step_of[k]
        L = B[:, j]
        kk = k + 1  # numéro de l'observation (1-based)

        # --- 1. coupon -------------------------------------------------
        pay = np.zeros(n_paths)
        if cpn.type == "fixed":
            pay = np.full(n_paths, c)
            n_coupons += alive
        elif cpn.type == "conditional":
            hit = L >= cpn.barrier
            mult = 1.0 + (memory if cpn.memory else 0.0)
            pay = np.where(hit, c * mult, 0.0)
            n_coupons += np.where(hit & alive, mult, 0.0)
            if cpn.memory:
                memory = np.where(hit, 0.0, memory + 1.0)
        elif cpn.type == "range_accrual":
            j0 = step_of[k - 1] if k > 0 else 0
            window = B[:, j0 + 1:j + 1]
            frac = ((window >= cpn.lower) & (window <= cpn.upper)).mean(axis=1)
            pay = c * frac
            n_coupons += np.where(alive, frac, 0.0)
        cf[:, k] += np.where(alive, pay, 0.0)

        feat["level"][:, k] = L
        feat["memory"][:, k] = memory
        feat["ki"][:, k] = running_min[:, j] < (spec.redemption.barrier or -1.0)

        if k == n - 1:
            break

        # --- 2. rappel automatique -------------------------------------
        if ac is not None and kk >= ac.start:
            called = alive & (L >= ac.level(kk))
            amount = 1.0 + (c * kk if cpn.type == "snowball" else 0.0)
            cf[:, k] += np.where(called, amount, 0.0)
            if cpn.type == "snowball":
                n_coupons += np.where(called, kk, 0.0)
            end_k[called] = k
            reason[called] = AUTOCALL
            final_level[called] = L[called]
            redemption[called] = 1.0
            alive &= ~called

        # --- 3. options de remboursement anticipé ----------------------
        if call_ex is not None:
            ex = alive & call_ex[:, k]
            cf[:, k] += np.where(ex, spec.callable.price, 0.0)
            end_k[ex], reason[ex], final_level[ex], redemption[ex] = k, ISSUER_CALL, L[ex], spec.callable.price
            alive &= ~ex
        if put_ex is not None:
            ex = alive & put_ex[:, k]
            cf[:, k] += np.where(ex, spec.puttable.price, 0.0)
            end_k[ex], reason[ex], final_level[ex], redemption[ex] = k, HOLDER_PUT, L[ex], spec.puttable.price
            alive &= ~ex

    # --- 4. maturité ----------------------------------------------------
    L = B[:, -1]
    ki = ki_flag(spec, running_min[:, -1], L)
    red = redemption_value(spec, L, ki, part)
    if cpn.type == "snowball":
        bar = cpn.barrier if cpn.barrier is not None else ac.level(n)
        win = L >= bar
        cf[:, -1] += np.where(alive & win, c * n, 0.0)
        n_coupons += np.where(alive & win, n, 0.0)
    cf[:, -1] += np.where(alive, red, 0.0)
    redemption[alive] = red[alive]

    return Flows(cf=cf, end_k=end_k, reason=reason, ki=ki & alive, final_level=final_level,
                 n_coupons=n_coupons, redemption=redemption, features=feat)


def discount_factors(spec: Spec, rate_bump: float = 0.0) -> np.ndarray:
    t = np.array(spec.obs_times)
    return np.exp(-(spec.rate + rate_bump + spec.issuer_spread) * t)


def present_value(spec: Spec, flows: Flows, rate_bump: float = 0.0) -> np.ndarray:
    return flows.cf @ discount_factors(spec, rate_bump)


# ----------------------------------------------------------------------
# Options bermudéennes (callable / puttable) : Longstaff-Schwartz
# ----------------------------------------------------------------------
def _basis(spec: Spec, feat: dict, k: int, idx: np.ndarray) -> np.ndarray:
    L = feat["level"][idx, k]
    cols = [np.ones_like(L), L, L ** 2, L ** 3]
    if spec.coupon.memory:
        m = feat["memory"][idx, k]
        cols += [m, m * L]
    if spec.redemption.monitoring == "american" and spec.redemption.barrier is not None:
        ki = feat["ki"][idx, k]
        cols += [ki, ki * L]
    return np.column_stack(cols)


def lsm_exercise(spec: Spec, times, B, coupon_rate=None, participation=None, rate_bump=0.0):
    """Détermine la politique d'exercice optimale :
    - l'émetteur rappelle si la valeur de continuation (ce qu'il doit encore payer)
      dépasse le prix de rappel ;
    - l'investisseur revend si la valeur de continuation est inférieure au prix de revente.
    Renvoie (call_ex, put_ex, policy) ; policy permet d'appliquer la règle à d'autres trajectoires."""
    n_paths, n = B.shape[0], spec.n_obs
    call_ex = np.zeros((n_paths, n), dtype=bool) if spec.callable else None
    put_ex = np.zeros((n_paths, n), dtype=bool) if spec.puttable else None
    policy = {}
    t = np.array(spec.obs_times)
    r = spec.rate + rate_bump + spec.issuer_spread

    for k in range(n - 2, -1, -1):
        kk = k + 1
        can_call = spec.callable is not None and kk >= spec.callable.start
        can_put = spec.puttable is not None and kk >= spec.puttable.start
        if not (can_call or can_put):
            continue
        fl = evaluate(spec, times, B, coupon_rate, participation, call_ex, put_ex)
        # vivant après le coupon et le rappel automatique de la date k
        alive = fl.end_k >= k
        alive &= ~((fl.end_k == k) & (fl.reason == AUTOCALL))
        if call_ex is not None:
            alive &= ~((fl.end_k == k) & (fl.reason == ISSUER_CALL))
        if put_ex is not None:
            alive &= ~((fl.end_k == k) & (fl.reason == HOLDER_PUT))
        idx = np.where(alive)[0]
        if len(idx) < 50:
            continue
        disc = np.exp(-r * (t[k + 1:] - t[k]))
        cont = fl.cf[idx, k + 1:] @ disc
        X = _basis(spec, fl.features, k, idx)
        beta, *_ = np.linalg.lstsq(X, cont, rcond=None)
        est = X @ beta
        policy[k] = beta
        if can_call:
            call_ex[idx, k] = est > spec.callable.price
        if can_put:
            put_ex[idx, k] = est < spec.puttable.price
            if can_call:
                put_ex[idx, k] &= ~call_ex[idx, k]
    return call_ex, put_ex, policy


def apply_policy(spec: Spec, policy: dict, times, B, coupon_rate=None, participation=None):
    """Applique une politique d'exercice estimée à de nouvelles trajectoires (scénarios)."""
    fl = evaluate(spec, times, B, coupon_rate, participation)
    n_paths, n = B.shape[0], spec.n_obs
    call_ex = np.zeros((n_paths, n), dtype=bool) if spec.callable else None
    put_ex = np.zeros((n_paths, n), dtype=bool) if spec.puttable else None
    idx = np.arange(n_paths)
    for k, beta in policy.items():
        est = _basis(spec, fl.features, k, idx) @ beta
        kk = k + 1
        if spec.callable and kk >= spec.callable.start:
            call_ex[:, k] = est > spec.callable.price
        if spec.puttable and kk >= spec.puttable.start:
            put_ex[:, k] = est < spec.puttable.price
    return call_ex, put_ex
