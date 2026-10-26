"""Warrants : options vanilles cotées, pricées en formule fermée de Black-Scholes."""
from __future__ import annotations

import math

from scipy.stats import norm

from .spec import Spec


def bs(S, K, T, r, q, vol, kind="call"):
    if T <= 0:
        return max(S - K, 0.0) if kind == "call" else max(K - S, 0.0)
    sq = vol * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * vol ** 2) * T) / sq
    d2 = d1 - sq
    if kind == "call":
        return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)


def greeks(S, K, T, r, q, vol, kind="call"):
    sq = vol * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * vol ** 2) * T) / sq
    d2 = d1 - sq
    pdf = norm.pdf(d1)
    if kind == "call":
        delta = math.exp(-q * T) * norm.cdf(d1)
        theta = (-S * math.exp(-q * T) * pdf * vol / (2 * math.sqrt(T))
                 - r * K * math.exp(-r * T) * norm.cdf(d2) + q * S * math.exp(-q * T) * norm.cdf(d1))
        prob = norm.cdf(d2)
    else:
        delta = -math.exp(-q * T) * norm.cdf(-d1)
        theta = (-S * math.exp(-q * T) * pdf * vol / (2 * math.sqrt(T))
                 + r * K * math.exp(-r * T) * norm.cdf(-d2) - q * S * math.exp(-q * T) * norm.cdf(-d1))
        prob = norm.cdf(-d2)
    gamma = math.exp(-q * T) * pdf / (S * sq)
    vega = S * math.exp(-q * T) * pdf * math.sqrt(T) / 100      # pour +1 point de vol
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta / 365, "prob_itm": prob}


def price_warrant(spec: Spec) -> dict:
    u = spec.underlyings[0]
    w = spec.warrant
    S = u.spot or 100.0
    K = w.strike * S
    T = spec.maturity
    opt = bs(S, K, T, spec.rate, u.div, u.vol, w.type)
    g = greeks(S, K, T, spec.rate, u.div, u.vol, w.type)
    price = opt / w.parity
    leverage = g["delta"] * S / opt if opt > 0 else float("nan")
    breakeven = K + opt if w.type == "call" else K - opt
    return {"spot": S, "strike": K, "option_price": opt, "warrant_price": price,
            "price_pct_spot": opt / S, "leverage": leverage, "breakeven": breakeven,
            "time_value": opt - max((S - K) if w.type == "call" else (K - S), 0.0), **g}
