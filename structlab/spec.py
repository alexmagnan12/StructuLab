"""Lecture du fichier YAML qui décrit le produit (ses règles, pas son nom)."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import yaml

FREQ = {"annual": 1, "semiannual": 2, "quarterly": 4, "monthly": 12}
FREQ_LABEL = {1: "annuelle", 2: "semestrielle", 4: "trimestrielle", 12: "mensuelle"}


@dataclass
class Underlying:
    name: str
    vol: float            # vol ATM
    div: float = 0.0
    spot: Optional[float] = None
    skew: float = 0.0     # pente du smile (ex. -0.25)
    smile: float = 0.0    # courbure du smile (ex. 0.10)

    @property
    def has_skew(self):
        return bool(self.skew or self.smile)

    def implied_vol(self, k):
        """vol(k) = vol ATM + skew * k + smile * k^2, avec k = ln(strike / forward)."""
        return np.maximum(self.vol + self.skew * k + self.smile * k * k, 0.03)


@dataclass
class Coupon:
    type: str = "none"            # none | fixed | conditional | snowball
    rate: float = 0.0             # taux annuel
    barrier: Optional[float] = None
    memory: bool = False


@dataclass
class Autocall:
    barrier: float = 1.0
    start: int = 1                # première date où le rappel est possible
    stepdown: float = 0.0         # baisse de la barrière à chaque date
    floor: float = 0.0

    def level(self, k):
        return max(self.barrier - self.stepdown * (k - self.start), self.floor)


@dataclass
class Redemption:
    type: str = "barrier"         # barrier (capital à risque) | full (100 % garanti)
    barrier: Optional[float] = None
    monitoring: str = "european"  # european (à maturité) | american (pendant toute la vie)
    strike: float = 1.0


@dataclass
class Warrant:
    type: str = "call"
    strike: float = 1.0           # en % du spot
    parity: float = 1.0


@dataclass
class Pricing:
    paths: int = 20000
    steps_per_year: int = 52
    seed: int = 42
    target_price: Optional[float] = None   # si donné, on cherche le coupon qui donne ce prix


@dataclass
class Spec:
    underlyings: list
    maturity: float
    product: str = "note"
    notional: float = 1000.0
    currency: str = "EUR"
    issuer: str = "Émetteur (illustratif)"
    frequency: int = 1
    correlation: float = 0.6
    basket: str = "worst_of"
    rate: float = 0.025
    issuer_spread: float = 0.0
    coupon: Coupon = field(default_factory=Coupon)
    autocall: Optional[Autocall] = None
    redemption: Redemption = field(default_factory=Redemption)
    warrant: Optional[Warrant] = None
    pricing: Pricing = field(default_factory=Pricing)

    @property
    def n_obs(self):
        return int(round(self.maturity * self.frequency))

    @property
    def obs_times(self):
        return [k / self.frequency for k in range(1, self.n_obs + 1)]

    @property
    def n_assets(self):
        return len(self.underlyings)

    @property
    def has_skew(self):
        return any(u.has_skew for u in self.underlyings)

    @property
    def basket_label(self):
        if self.n_assets == 1:
            return self.underlyings[0].name
        return "Worst-of (" + ", ".join(u.name for u in self.underlyings) + ")"

    def copy(self):
        return copy.deepcopy(self)


def pct(x):
    """Accepte 0.7, 70 ou '70%'."""
    if x is None:
        return None
    if isinstance(x, str):
        x = x.strip()
        if x.endswith("%"):
            return float(x[:-1]) / 100
    x = float(x)
    return x / 100 if abs(x) > 3 else x


def _make(cls, d, pct_fields=()):
    if d is None:
        return None
    d = dict(d)
    for f in pct_fields:
        if f in d:
            d[f] = pct(d[f])
    return cls(**d)


def load_spec(path):
    with open(path, encoding="utf-8") as fh:
        return spec_from_dict(yaml.safe_load(fh))


def spec_from_dict(d):
    d = copy.deepcopy(d)
    unders = [Underlying(name=u["name"], vol=pct(u["vol"]), div=pct(u.get("div", 0)) or 0.0, spot=u.get("spot"),
                         skew=float(u.get("skew", 0)), smile=float(u.get("smile", 0)))
              for u in d.pop("underlyings")]
    market = d.pop("market", {})
    spec = Spec(
        underlyings=unders,
        maturity=float(d.pop("maturity")),
        product=d.pop("product", "note"),
        notional=float(d.pop("notional", 1000)),
        currency=d.pop("currency", "EUR"),
        frequency=FREQ[d.pop("frequency", "annual")],
        correlation=float(d.pop("correlation", 0.6)),
        rate=pct(market.get("rate", 0.025)),
        issuer_spread=pct(market.get("issuer_spread", 0)) or 0.0,
        coupon=_make(Coupon, d.pop("coupon", None), ("rate", "barrier")) or Coupon(),
        autocall=_make(Autocall, d.pop("autocall", None), ("barrier", "stepdown", "floor")),
        redemption=_make(Redemption, d.pop("redemption", None), ("barrier", "strike")) or Redemption(type="full"),
        warrant=_make(Warrant, d.pop("warrant", None), ("strike",)),
        pricing=_make(Pricing, d.pop("pricing", None), ("target_price",)) or Pricing(),
    )
    if d:
        raise ValueError(f"Champs inconnus : {sorted(d)}")
    if spec.n_assets == 1:
        spec.basket = "single"
    if spec.warrant:
        spec.product = "warrant"
    if spec.coupon.type == "conditional" and spec.coupon.barrier is None:
        raise ValueError("Un coupon conditionnel a besoin d'une barrière (coupon.barrier).")
    if spec.redemption.type == "barrier" and spec.redemption.barrier is None:
        raise ValueError("Un capital à risque a besoin d'une barrière (redemption.barrier).")
    if spec.coupon.type == "snowball" and spec.autocall is None:
        raise ValueError("Un coupon snowball (Athena) a besoin d'un rappel automatique.")
    spy = spec.pricing.steps_per_year
    if spy % spec.frequency:   # la grille doit tomber sur les dates d'observation
        spec.pricing.steps_per_year = spy + spec.frequency - spy % spec.frequency
    return spec
