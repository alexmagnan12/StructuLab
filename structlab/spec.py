"""Description d'un produit structuré à partir de ses caractéristiques (fichier YAML).

On ne donne jamais le nom du produit : on décrit le payoff (coupon, rappel,
remboursement, options de l'émetteur / de l'investisseur) et l'outil en déduit
la famille du produit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import yaml

FREQ = {"annual": 1, "annuel": 1, "semiannual": 2, "semestriel": 2,
        "quarterly": 4, "trimestriel": 4, "monthly": 12, "mensuel": 12}
FREQ_LABEL = {1: "annuelle", 2: "semestrielle", 4: "trimestrielle", 12: "mensuelle"}


@dataclass
class Underlying:
    name: str
    vol: float
    div: float = 0.0
    spot: Optional[float] = None
    skew: float = 0.0     # pente de la vol implicite en log-moneyness (ex. -0.25)
    smile: float = 0.0    # courbure du smile (ex. 0.10)

    @property
    def has_skew(self) -> bool:
        return bool(self.skew or self.smile)

    def implied_vol(self, k):
        """Vol implicite paramétrique : vol ATM + skew × k + smile × k², avec k = ln(strike / forward)."""
        import numpy as np
        return np.maximum(self.vol + self.skew * k + self.smile * k * k, 0.03)


@dataclass
class Coupon:
    type: str = "none"            # none | fixed | conditional | snowball | range_accrual
    rate: float = 0.0             # taux annuel
    barrier: Optional[float] = None
    memory: bool = False
    lower: Optional[float] = None  # range accrual
    upper: Optional[float] = None


@dataclass
class Autocall:
    barrier: float = 1.0
    stepdown: float = 0.0         # baisse de la barrière à chaque observation
    start: int = 1                # première date d'observation de rappel (1 = la première)
    floor: float = 0.0            # niveau minimum de la barrière après step-down

    def level(self, k: int) -> float:
        return max(self.barrier - self.stepdown * (k - self.start), self.floor)


@dataclass
class Redemption:
    type: str = "barrier"         # barrier | protected | twin_win | full
    barrier: Optional[float] = None
    monitoring: str = "european"  # european | american
    strike: float = 1.0
    participation: Optional[float] = None
    cap: Optional[float] = None
    protection: float = 1.0
    down_participation: float = 1.0  # twin win : gain sur la baisse


@dataclass
class EarlyOption:
    start: int = 1
    price: float = 1.0


@dataclass
class Warrant:
    type: str = "call"
    strike: float = 1.0           # en % du spot
    parity: float = 1.0           # nombre de warrants pour 1 sous-jacent


@dataclass
class Pricing:
    paths: int = 20000
    steps_per_year: int = 52
    seed: int = 42
    target_price: Optional[float] = None   # prix cible -> on résout le coupon / la participation
    solve: Optional[str] = None            # "coupon" | "participation" (auto si None)


@dataclass
class Spec:
    underlyings: list
    maturity: float
    name: Optional[str] = None
    product: str = "note"         # note | warrant
    notional: float = 1000.0
    currency: str = "EUR"
    issuer: str = "Émetteur (illustratif)"
    frequency: int = 1
    correlation: object = 0.6
    basket: str = "worst_of"
    rate: float = 0.025
    issuer_spread: float = 0.0
    coupon: Coupon = field(default_factory=Coupon)
    autocall: Optional[Autocall] = None
    redemption: Redemption = field(default_factory=Redemption)
    callable: Optional[EarlyOption] = None
    puttable: Optional[EarlyOption] = None
    warrant: Optional[Warrant] = None
    pricing: Pricing = field(default_factory=Pricing)

    # ------------------------------------------------------------------
    @property
    def n_obs(self) -> int:
        return int(round(self.maturity * self.frequency))

    @property
    def obs_times(self):
        return [k / self.frequency for k in range(1, self.n_obs + 1)]

    @property
    def n_assets(self) -> int:
        return len(self.underlyings)

    @property
    def has_skew(self) -> bool:
        return any(u.has_skew for u in self.underlyings)

    @property
    def basket_label(self) -> str:
        if self.n_assets == 1:
            return self.underlyings[0].name
        names = ", ".join(u.name for u in self.underlyings)
        kind = {"worst_of": "Worst-of", "best_of": "Best-of", "average": "Panier équipondéré"}[self.basket]
        return f"{kind} ({names})"

    def participation(self) -> float:
        if self.redemption.participation is not None:
            return self.redemption.participation
        return 0.0 if self.redemption.type in ("barrier", "full") else 1.0

    def copy(self) -> "Spec":
        import copy
        return copy.deepcopy(self)


def _pct(x):
    """Accepte 0.7, 70 ou '70%'."""
    if x is None:
        return None
    if isinstance(x, str):
        x = x.strip()
        if x.endswith("%"):
            return float(x[:-1]) / 100
        x = float(x)
    x = float(x)
    return x / 100 if abs(x) > 3 else x


def _build(cls, d, pct_fields=()):
    if d is None:
        return None
    if d is True:
        d = {}
    d = dict(d)
    for f in pct_fields:
        if f in d:
            d[f] = _pct(d[f])
    return cls(**d)


def load_spec(path_or_dict) -> Spec:
    if isinstance(path_or_dict, dict):
        d = dict(path_or_dict)
    else:
        with open(path_or_dict, encoding="utf-8") as fh:
            d = yaml.safe_load(fh)

    unders = [Underlying(name=u["name"], vol=_pct(u["vol"]), div=_pct(u.get("div", 0.0)) or 0.0,
                         spot=u.get("spot"), skew=float(u.get("skew", 0.0)), smile=float(u.get("smile", 0.0)))
              for u in d.pop("underlyings")]
    market = d.pop("market", {}) or {}
    freq = d.pop("frequency", "annual")
    freq = FREQ[freq] if isinstance(freq, str) else int(freq)

    spec = Spec(
        underlyings=unders,
        maturity=float(d.pop("maturity")),
        name=d.pop("name", None),
        product=d.pop("product", "note"),
        notional=float(d.pop("notional", 1000)),
        currency=d.pop("currency", "EUR"),
        issuer=d.pop("issuer", "Émetteur (illustratif)"),
        frequency=freq,
        correlation=d.pop("correlation", 0.6),
        basket=d.pop("basket", "worst_of"),
        rate=_pct(market.get("rate", 0.025)),
        issuer_spread=_pct(market.get("issuer_spread", 0.0)) or 0.0,
        coupon=_build(Coupon, d.pop("coupon", None), ("rate", "barrier", "lower", "upper")) or Coupon(),
        autocall=_build(Autocall, d.pop("autocall", None), ("barrier", "stepdown", "floor")),
        redemption=_build(Redemption, d.pop("redemption", None),
                          ("barrier", "strike", "participation", "cap", "protection", "down_participation"))
        or Redemption(type="full"),
        callable=_build(EarlyOption, d.pop("callable", None), ("price",)),
        puttable=_build(EarlyOption, d.pop("puttable", None), ("price",)),
        warrant=_build(Warrant, d.pop("warrant", None), ("strike",)),
        pricing=_build(Pricing, d.pop("pricing", None), ("target_price",)) or Pricing(),
    )
    if d:
        raise ValueError(f"Champs inconnus dans la description : {sorted(d)}")
    if spec.n_assets == 1:
        spec.basket = "single"
    if spec.warrant is not None:
        spec.product = "warrant"
    _validate(spec)
    return spec


def _validate(s: Spec):
    if s.coupon.type not in ("none", "fixed", "conditional", "snowball", "range_accrual"):
        raise ValueError(f"coupon.type inconnu : {s.coupon.type}")
    if s.redemption.type not in ("barrier", "protected", "twin_win", "full"):
        raise ValueError(f"redemption.type inconnu : {s.redemption.type}")
    if s.coupon.type == "conditional" and s.coupon.barrier is None:
        raise ValueError("Un coupon conditionnel a besoin d'une barrière (coupon.barrier).")
    if s.coupon.type == "range_accrual" and (s.coupon.lower is None or s.coupon.upper is None):
        raise ValueError("Un range accrual a besoin de coupon.lower et coupon.upper.")
    if s.redemption.type in ("barrier", "twin_win") and s.redemption.barrier is None:
        raise ValueError("Ce remboursement a besoin d'une barrière (redemption.barrier).")
    if s.coupon.type == "snowball" and s.autocall is None:
        raise ValueError("Un coupon 'snowball' (Athena) n'a de sens qu'avec un rappel automatique.")
    # la grille de simulation doit tomber sur les dates d'observation
    spy = s.pricing.steps_per_year
    if spy % s.frequency:
        s.pricing.steps_per_year = int(spy + s.frequency - spy % s.frequency)
