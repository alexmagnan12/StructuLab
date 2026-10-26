"""Simulation Monte Carlo des indices (corrélés), avec ou sans skew."""
from __future__ import annotations

import numpy as np


def local_vol(k, t, atm, skew, smile):
    """Vol locale de Dupire déduite du smile vol(k) = atm + skew*k + smile*k^2
    (formule de Dupire écrite en variance totale w = vol^2 * t)."""
    sig = np.maximum(atm + skew * k + smile * k * k, 0.03)
    d1 = skew + 2 * smile * k            # dérivée du smile
    d2 = 2 * smile                       # dérivée seconde
    w = sig * sig * t
    wk = 2 * t * sig * d1
    wkk = 2 * t * (d1 * d1 + sig * d2)
    denom = 1 - k * wk / w + 0.25 * (-0.25 - 1 / w + k * k / (w * w)) * wk * wk + 0.5 * wkk
    return np.sqrt(np.clip(sig * sig / np.maximum(denom, 0.05), 0.03 ** 2, 1.5 ** 2))


def simulate_basket(spec, vol_bump=0.0, corr_bump=0.0, div_bump=0.0, rate_bump=0.0):
    """Renvoie (temps, B) : B[p, j] = niveau du worst-of (base 1) sur la trajectoire p au pas j."""
    n_paths, spy = spec.pricing.paths, spec.pricing.steps_per_year
    n_steps = int(round(spec.maturity * spy))
    dt = 1.0 / spy
    n = spec.n_assets

    vols = np.array([u.vol for u in spec.underlyings]) + vol_bump
    divs = np.array([u.div for u in spec.underlyings]) + div_bump
    skews = np.array([u.skew for u in spec.underlyings])
    smiles = np.array([u.smile for u in spec.underlyings])
    r = spec.rate + rate_bump

    rho = min(spec.correlation + corr_bump, 0.99)
    corr = np.full((n, n), rho)
    np.fill_diagonal(corr, 1.0)
    chol = np.linalg.cholesky(corr)

    rng = np.random.default_rng(spec.pricing.seed)   # même graine = mêmes scénarios
    logS = np.zeros((n_paths, n))
    B = np.ones((n_paths, n_steps + 1))
    half = (n_paths + 1) // 2
    for j in range(1, n_steps + 1):
        z = rng.standard_normal((half, n))
        z = np.vstack([z, -z])[:n_paths] @ chol.T     # antithétiques + corrélation
        if spec.has_skew:
            k = logS - (r - divs) * (j - 1) * dt      # distance au forward
            sig = local_vol(k, (j - 0.5) * dt, vols, skews, smiles)
        else:
            sig = vols
        logS += (r - divs - 0.5 * sig ** 2) * dt + sig * np.sqrt(dt) * z
        B[:, j] = np.exp(logS).min(axis=1)            # worst-of (ou l'indice seul)
    return np.arange(n_steps + 1) * dt, B
