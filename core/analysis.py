"""Uçtan uca analiz zinciri: rüzgar kaynağı → enerji → ekonomi → çevre.

Rapor ve örnek rapor üretimi bu modülü kullanır. Streamlit'e bağımlı değildir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core import economics as ec
from core import energy as en
from core import environment as env
from core import wind_resource as wr
from core.config import load_defaults


@dataclass
class AnalysisInputs:
    """Analiz girdileri. df: temizlenmiş saatlik veri (data_sources şeması)."""

    lat: float
    lon: float
    df: pd.DataFrame
    quality: dict[str, Any]
    source_label: str
    turbine: en.Turbine
    econ: ec.EconomicInputs
    is_nasa: bool = True
    h1: float = 50.0
    ws_col: str = "ws50"
    wd_col: str | None = "wd50"
    n_turbines: int = 1
    method: str = "power"            # "power" | "log"
    alpha: float | None = None       # None: sahadan hesapla (yalnız NASA)
    z0: float = 0.03
    z0_name: str = "Nadas tarlası"
    density_method: str = "iec"
    losses: dict[str, float] | None = None
    emission_factor: float | None = None
    household_kwh: float | None = None
    env_notes: dict[str, str] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Tüm hesap sonuçları (rapor için tek nesne)."""

    inputs: AnalysisInputs
    stats: dict[str, float]
    weibull_mle: wr.WeibullParams
    weibull_mom: wr.WeibullParams
    rose: pd.DataFrame | None
    monthly: pd.Series
    yearly: pd.Series
    cov: float
    alpha_used: float | None
    method_compare: dict[str, float] | None
    ws_hub: pd.Series
    rho: float
    rho_is_standard: bool
    pd_ref: float
    pd_hub: float
    wind_class: dict[str, Any]
    energy: dict[str, Any]
    econ: dict[str, Any] | None
    econ_error: str | None
    sensitivity: pd.DataFrame | None
    scenarios: pd.DataFrame | None
    env: dict[str, Any]


def run_analysis(inp: AnalysisInputs) -> AnalysisResult:
    """Tüm hesapları sırayla çalıştırır. Formüller ilgili core modüllerinde belgelenmiştir."""
    df = inp.df
    ref = df[inp.ws_col]
    has_met = {"ps_kpa", "t2m_c"} <= set(df.columns)
    rho_series = wr.air_density(df["ps_kpa"], df["t2m_c"]) if has_met else None
    rho = float(rho_series.mean()) if has_met else float(load_defaults()["energy"]["standard_density"]["value"])
    rho_for = rho_series if has_met else rho

    alpha = inp.alpha
    if inp.method == "power" and alpha is None:
        if not inp.is_nasa:
            raise ValueError("Ölçüm verisinde sahaya özel α hesaplanamaz; sabit α girin.")
        alpha = wr.site_alpha(df["ws10"], df["ws50"])
    ws_hub = wr.extrapolate(df, inp.turbine.hub_height, inp.method, alpha=alpha, z0=inp.z0,
                            source_col=inp.ws_col, h1=inp.h1)
    compare = wr.compare_methods(df, inp.turbine.hub_height, inp.z0, alpha) if inp.is_nasa else None

    energy = en.energy_summary(ws_hub, inp.turbine, rho, inp.n_turbines, inp.losses, inp.density_method)
    cap_kw = inp.turbine.rated_kw * inp.n_turbines
    try:
        econ = ec.evaluate(inp.econ, energy["net_aep"], cap_kw)
        sens = ec.sensitivity(inp.econ, energy["net_aep"], cap_kw)
        scen = ec.scenarios(inp.econ, energy["net_aep"], cap_kw)
        econ_error = None
    except ValueError as e:
        econ, sens, scen, econ_error = None, None, None, str(e)

    pd_ref = wr.power_density_timeseries(ref, rho_for)
    yearly, cov = wr.annual_variability(ref)
    return AnalysisResult(
        inputs=inp,
        stats=wr.basic_stats(ref),
        weibull_mle=wr.fit_weibull_mle(ref),
        weibull_mom=wr.fit_weibull_moments(ref),
        rose=wr.wind_rose(ref, df[inp.wd_col]) if inp.wd_col and inp.wd_col in df else None,
        monthly=wr.monthly_profile(ref),
        yearly=yearly,
        cov=cov,
        alpha_used=alpha if inp.method == "power" else None,
        method_compare=compare,
        ws_hub=ws_hub,
        rho=rho,
        rho_is_standard=not has_met,
        pd_ref=pd_ref,
        pd_hub=wr.power_density_timeseries(ws_hub, rho_for),
        wind_class=wr.wind_class(pd_ref, inp.h1),
        energy=energy,
        econ=econ,
        econ_error=econ_error,
        sensitivity=sens,
        scenarios=scen,
        env=env.environment_summary(energy["net_aep"], inp.econ.lifetime, inp.econ.degradation,
                                    inp.emission_factor, inp.household_kwh, inp.env_notes),
    )
