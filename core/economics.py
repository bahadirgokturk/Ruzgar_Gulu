"""Ekonomik analiz: nakit akışı, LCOE, NPV, IRR, geri ödeme, duyarlılık ve senaryolar.

Birimler: para birimi kullanıcı seçimi (varsayılan USD), enerji MWh, güç kW, oranlar ondalık (0.08 = %8).
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from typing import Any

import numpy as np
import numpy_financial as npf
import pandas as pd

from core.config import load_defaults

Z_90 = 1.282  # standart normal dağılımda %90 tek yönlü z değeri


@dataclass(frozen=True)
class EconomicInputs:
    """Ekonomik varsayımlar. from_defaults() ile defaults.yaml'dan oluşturulur."""

    capex_per_kw: float
    capex_split: dict[str, float] = field(hash=False)
    opex_per_kw_year: float
    opex_per_mwh: float
    opex_escalation: float
    incentive_price: float
    incentive_years: int
    market_price: float
    price_escalation: float
    discount_rate: float
    lifetime: int
    degradation: float
    tax_rate: float
    depreciation_years: int
    loan_enabled: bool
    loan_share: float
    loan_rate: float
    loan_term: int
    aep_sigma: float
    currency: str = "USD"

    @classmethod
    def from_defaults(cls, **overrides: Any) -> "EconomicInputs":
        cfg = load_defaults()["economics"]
        vals = {f.name: cfg[f.name]["value"] for f in fields(cls) if f.name in cfg}
        vals.update(overrides)
        return cls(**vals)

    def validate(self) -> None:
        """Geçersiz girdilerde Türkçe hata mesajı verir."""
        if self.capex_per_kw <= 0:
            raise ValueError("CAPEX sıfırdan büyük olmalı.")
        if self.lifetime < 1:
            raise ValueError("Proje ömrü en az 1 yıl olmalı.")
        if self.discount_rate <= -1:
            raise ValueError("İskonto oranı -%100'den büyük olmalı.")
        if not 0 <= self.incentive_years <= self.lifetime:
            raise ValueError("Teşvik süresi 0 ile proje ömrü arasında olmalı.")
        if abs(sum(self.capex_split.values()) - 1) > 1e-6:
            raise ValueError("CAPEX alt kalem paylarının toplamı 1 olmalı.")
        if self.loan_enabled and not (0 < self.loan_share <= 1 and self.loan_term >= 1):
            raise ValueError("Kredi payı 0-1 arasında, vade en az 1 yıl olmalı.")


def capex_breakdown(inp: EconomicInputs, capacity_kw: float) -> dict[str, float]:
    """CAPEX alt kalemleri [para birimi]: toplam = capex_per_kw · kurulu güç [kW]."""
    total = inp.capex_per_kw * capacity_kw
    return {k: total * share for k, share in inp.capex_split.items()}


def price_for_year(inp: EconomicInputs, t: int) -> float:
    """t. yıl satış fiyatı: t ≤ N_teşvik ise teşvik fiyatı, sonra piyasa · (1+e)^(t − N_teşvik − 1)."""
    if t <= inp.incentive_years:
        return inp.incentive_price
    return inp.market_price * (1 + inp.price_escalation) ** (t - inp.incentive_years - 1)


def cash_flow_table(inp: EconomicInputs, net_aep: float, capacity_kw: float) -> pd.DataFrame:
    """Yıllık nakit akış tablosu (0..N).

    Eₜ = AEP·(1−d)^(t−1);  Gelirₜ = Eₜ·fiyatₜ;
    OPEXₜ = (OPEX_kW·P + OPEX_MWh·Eₜ)·(1+g)^(t−1);
    Vergiₜ = max(0, Gelir − OPEX − Amortisman − Faiz)·vergi oranı;
    Net NAₜ = Gelir − OPEX − Vergi − Borç servisi;  NA₀ = −(CAPEX − Kredi).
    Kredi: eşit taksitli anüite A = L·i / (1 − (1+i)^−n).
    """
    inp.validate()
    if net_aep < 0:
        raise ValueError("Net AEP negatif olamaz.")
    capex = inp.capex_per_kw * capacity_kw
    loan = capex * inp.loan_share if inp.loan_enabled else 0.0
    annuity = 0.0
    if loan:
        i, n = inp.loan_rate, inp.loan_term
        annuity = loan * i / (1 - (1 + i) ** -n) if i else loan / n
    rows = [{"year": 0, "energy_mwh": 0.0, "price": 0.0, "revenue": 0.0, "opex": 0.0, "depreciation": 0.0,
             "interest": 0.0, "principal": 0.0, "tax": 0.0, "capex": capex, "net_cf": -(capex - loan)}]
    balance = loan
    for t in range(1, inp.lifetime + 1):
        e = net_aep * (1 - inp.degradation) ** (t - 1)
        price = price_for_year(inp, t)
        revenue = e * price
        opex = (inp.opex_per_kw_year * capacity_kw + inp.opex_per_mwh * e) * (1 + inp.opex_escalation) ** (t - 1)
        dep = capex / inp.depreciation_years if t <= inp.depreciation_years else 0.0
        interest = balance * inp.loan_rate if balance > 0 else 0.0
        if balance > 0:
            # son taksitte kalan bakiyenin tamamı ödenir (kayan nokta artığı kalmasın)
            principal = balance if t >= inp.loan_term else min(annuity - interest, balance)
        else:
            principal = 0.0
        balance -= principal
        tax = max(0.0, revenue - opex - dep - interest) * inp.tax_rate
        rows.append({"year": t, "energy_mwh": e, "price": price, "revenue": revenue, "opex": opex,
                     "depreciation": dep, "interest": interest, "principal": principal, "tax": tax,
                     "capex": 0.0, "net_cf": revenue - opex - tax - interest - principal})
    df = pd.DataFrame(rows).set_index("year")
    df["cum_cf"] = df["net_cf"].cumsum()
    return df


def lcoe(inp: EconomicInputs, table: pd.DataFrame) -> float:
    """LCOE = Σ (CAPEXₜ + OPEXₜ)/(1+r)ᵗ ÷ Σ Eₜ/(1+r)ᵗ  [para birimi/MWh] (vergi ve finansman öncesi)."""
    disc = (1 + inp.discount_rate) ** -table.index.to_numpy(float)
    energy = (table["energy_mwh"] * disc).sum()
    if energy <= 0:
        raise ValueError("Toplam iskontolu üretim sıfır; LCOE hesaplanamaz.")
    return float(((table["capex"] + table["opex"]) * disc).sum() / energy)


def npv(rate: float, cash_flows) -> float:
    """NPV = Σ NAₜ/(1+r)ᵗ, t = 0..N (numpy_financial.npv)."""
    return float(npf.npv(rate, np.asarray(cash_flows, float)))


def irr(cash_flows) -> float | None:
    """IRR: NPV(IRR) = 0 (numpy_financial.irr). Çözüm yoksa None."""
    r = npf.irr(np.asarray(cash_flows, float))
    return None if r is None or np.isnan(r) else float(r)


def payback(cash_flows, rate: float = 0.0) -> float | None:
    """Geri ödeme süresi [yıl]; rate > 0 ise iskontolu.

    Kümülatif (iskontolu) nakit akışının sıfırı geçtiği yıl, yıl içinde doğrusal interpolasyonla.
    Ömür içinde geri ödenmezse None.
    """
    cf = np.asarray(cash_flows, float) / (1 + rate) ** np.arange(len(cash_flows))
    cum = np.cumsum(cf)
    for t in range(1, len(cum)):
        if cum[t - 1] < 0 <= cum[t]:
            return float(t - 1 + (-cum[t - 1]) / cf[t])
    return 0.0 if cum[0] >= 0 else None


def evaluate(inp: EconomicInputs, net_aep: float, capacity_kw: float) -> dict[str, Any]:
    """Tüm ekonomik göstergeleri hesaplar."""
    table = cash_flow_table(inp, net_aep, capacity_kw)
    cf = table["net_cf"].to_numpy()
    return {
        "table": table,
        "capex": float(table.loc[0, "capex"]),
        "capex_breakdown": capex_breakdown(inp, capacity_kw),
        "lcoe": lcoe(inp, table),
        "npv": npv(inp.discount_rate, cf),
        "irr": irr(cf),
        "payback": payback(cf),
        "discounted_payback": payback(cf, inp.discount_rate),
    }


def verdict(result: dict[str, Any], discount_rate: float) -> tuple[bool, str]:
    """Fizibilite yorumu: NPV > 0 ise fizibil. Otomatik Türkçe cümle döndürür."""
    npv_, irr_ = result["npv"], result["irr"]
    irr_txt = "hesaplanamadı" if irr_ is None else f"%{100 * irr_:.1f}"
    if npv_ > 0:
        return True, (f"Proje bu varsayımlarla fizibil görünüyor. NPV pozitif ve IRR ({irr_txt}), "
                      f"%{100 * discount_rate:.0f} iskonto oranının üzerinde.")
    return False, (f"Proje bu varsayımlarla fizibil görünmüyor. NPV negatif ve IRR ({irr_txt}), "
                   f"%{100 * discount_rate:.0f} iskonto oranının altında kalıyor.")


SENSITIVITY_PARAMS = {
    "capex": "CAPEX",
    "price": "Satış fiyatı",
    "aep": "AEP",
    "discount_rate": "İskonto oranı",
    "opex": "OPEX",
}


def _perturb(inp: EconomicInputs, aep: float, param: str, delta: float) -> tuple[EconomicInputs, float]:
    f = 1 + delta
    if param == "capex":
        return replace(inp, capex_per_kw=inp.capex_per_kw * f), aep
    if param == "price":
        return replace(inp, incentive_price=inp.incentive_price * f, market_price=inp.market_price * f), aep
    if param == "aep":
        return inp, aep * f
    if param == "discount_rate":
        return replace(inp, discount_rate=inp.discount_rate * f), aep
    if param == "opex":
        return replace(inp, opex_per_kw_year=inp.opex_per_kw_year * f, opex_per_mwh=inp.opex_per_mwh * f), aep
    raise ValueError(param)


def sensitivity(inp: EconomicInputs, net_aep: float, capacity_kw: float,
                steps: list[float] | None = None) -> pd.DataFrame:
    """Tek parametreli duyarlılık: her parametre ve oransal değişim için NPV ve LCOE.

    Sütunlar: param, label, delta, npv, lcoe, d_npv (baza göre fark), d_lcoe.
    """
    steps = steps or load_defaults()["economics"]["sensitivity_steps"]["value"]
    base = evaluate(inp, net_aep, capacity_kw)
    rows = []
    for p, label in SENSITIVITY_PARAMS.items():
        for d in steps:
            i2, a2 = _perturb(inp, net_aep, p, d)
            r = evaluate(i2, a2, capacity_kw)
            rows.append({"param": p, "label": label, "delta": d, "npv": r["npv"], "lcoe": r["lcoe"],
                         "d_npv": r["npv"] - base["npv"], "d_lcoe": r["lcoe"] - base["lcoe"]})
    return pd.DataFrame(rows)


def scenarios(inp: EconomicInputs, net_aep: float, capacity_kw: float) -> pd.DataFrame:
    """Kötümser (P90), baz (P50), iyimser (P10) AEP senaryoları.

    P90 = P50·(1 − 1.282σ), P10 = P50·(1 + 1.282σ); σ = aep_sigma.
    """
    rows = []
    for name, p, f in [("Kötümser", "P90", 1 - Z_90 * inp.aep_sigma), ("Baz", "P50", 1.0),
                       ("İyimser", "P10", 1 + Z_90 * inp.aep_sigma)]:
        r = evaluate(inp, net_aep * f, capacity_kw)
        rows.append({"scenario": name, "p_level": p, "net_aep": net_aep * f,
                     "npv": r["npv"], "irr": r["irr"], "lcoe": r["lcoe"], "payback": r["payback"]})
    return pd.DataFrame(rows).set_index("scenario")
