"""Simulation Monte Carlo : sous-jacents lognormaux corrélés (Black-Scholes multi-actifs)."""
from __future__ import annotations

import numpy as np

from .spec import Spec


def correlation_matrix(spec: Spec) -> np.ndarray:
    n = spec.n_assets
    c = spec.correlation
    if isinstance(c, (int, float)):
        m = np.full((n, n), float(c))
        np.fill_diagonal(m, 1.0)
    else:
        m = np.array(c, dtype=float)
    return m


def local_vol(k, t, atm, skew, smile):
    """Volatilité locale de Dupire déduite d'un smile paramétrique
    sigma_imp(k) = atm + skew*k + smile*k^2 (k = ln(S/F), identique pour toutes les maturités).
    Formule de Dupire écrite en variance totale w = sigma_imp^2 * t (Gatheral)."""
    sig = np.maximum(atm + skew * k + smile * k * k, 0.03)
    d1 = skew + 2 * smile * k                     # dsigma/dk
    d2 = 2 * smile                                # d2sigma/dk2
    w = sig * sig * t
    wk = 2 * t * sig * d1
    wkk = 2 * t * (d1 * d1 + sig * d2)
    denom = 1 - k * wk / w + 0.25 * (-0.25 - 1 / w + k * k / (w * w)) * wk * wk + 0.5 * wkk
    lv2 = sig * sig / np.maximum(denom, 0.05)
    return np.sqrt(np.clip(lv2, 0.03 ** 2, 1.5 ** 2))


def simulate_basket(spec: Spec, vol_bump: float = 0.0, corr_bump: float = 0.0,
                    div_bump: float = 0.0, rate_bump: float = 0.0,
                    n_paths: int | None = None, seed: int | None = None):
    """Renvoie (temps, B) où B[p, j] est la performance du panier (worst-of, etc.)
    en base 1 à la date j de la grille de surveillance.

    La même graine donne les mêmes aléas : les sensibilités sont calculées à
    nombres aléatoires communs (bruit Monte Carlo quasi nul sur les écarts)."""
    n_paths = n_paths or spec.pricing.paths
    seed = spec.pricing.seed if seed is None else seed
    spy = spec.pricing.steps_per_year
    n_steps = int(round(spec.maturity * spy))
    dt = 1.0 / spy
    n = spec.n_assets

    vols = np.array([u.vol + vol_bump for u in spec.underlyings])
    divs = np.array([u.div + div_bump for u in spec.underlyings])
    r = spec.rate + rate_bump
    corr = correlation_matrix(spec)
    if n > 1 and corr_bump:
        corr = np.clip(corr + corr_bump, -0.99, 0.99)
        np.fill_diagonal(corr, 1.0)
    chol = np.linalg.cholesky(corr)

    drift = (r - divs - 0.5 * vols ** 2) * dt
    diff = vols * np.sqrt(dt)
    use_lv = spec.has_skew
    skews = np.array([u.skew for u in spec.underlyings])
    smiles = np.array([u.smile for u in spec.underlyings])

    rng = np.random.default_rng(seed)
    logS = np.zeros((n_paths, n))
    B = np.empty((n_paths, n_steps + 1))
    B[:, 0] = 1.0
    half = (n_paths + 1) // 2
    for j in range(1, n_steps + 1):
        z = rng.standard_normal((half, n))
        z = np.vstack([z, -z])[:n_paths]          # variables antithétiques
        if use_lv:
            t = (j - 0.5) * dt
            k = logS - (r - divs) * (j - 1) * dt          # log-moneyness par rapport au forward
            sig = local_vol(k, t, vols, skews, smiles)
            logS += (r - divs - 0.5 * sig ** 2) * dt + (z @ chol.T) * sig * np.sqrt(dt)
        else:
            logS += drift + (z @ chol.T) * diff
        perf = np.exp(logS)
        if spec.basket in ("worst_of", "single"):
            B[:, j] = perf.min(axis=1)
        elif spec.basket == "best_of":
            B[:, j] = perf.max(axis=1)
        else:
            B[:, j] = perf.mean(axis=1)
    times = np.arange(n_steps + 1) * dt
    return times, B
