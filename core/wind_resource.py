"""Rüzgar kaynağı analizi: istatistik, Weibull, yükseklik ekstrapolasyonu, yoğunluk.

Birimler: hız m/s, yükseklik m, basınç kPa (girdi) / Pa (hesap), sıcaklık °C (girdi) / K (hesap),
yoğunluk kg/m³, güç yoğunluğu W/m².
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import gamma

from core.config import load_defaults

SECTOR_NAMES_16 = ["K", "KKD", "KD", "DKD", "D", "DGD", "GD", "GGD",
                   "G", "GGB", "GB", "BGB", "B", "BKB", "KB", "KKB"]
CLASS_NAMES = ["Zayıf", "Sınırda", "Orta", "İyi", "Mükemmel", "Üstün", "Olağanüstü"]


def _cfg(key: str) -> Any:
    return load_defaults()["wind_resource"][key]["value"]


# ---------------------------------------------------------------- istatistik

def basic_stats(ws: pd.Series) -> dict[str, float]:
    """Ortalama, medyan, std, min, max [m/s] ve sakin saat oranı [%] (v < calm_threshold)."""
    v = ws.dropna()
    return {
        "mean": float(v.mean()),
        "median": float(v.median()),
        "std": float(v.std()),
        "min": float(v.min()),
        "max": float(v.max()),
        "calm_pct": float(100 * (v < _cfg("calm_threshold")).mean()),
        "n": int(len(v)),
    }


def monthly_profile(ws: pd.Series) -> pd.Series:
    """Ay bazında ortalama hız [m/s]; index 1-12."""
    return ws.groupby(ws.index.month).mean().rename_axis("month")


def diurnal_profile(ws: pd.Series, utc_offset: int | None = None) -> pd.Series:
    """Günün saatine göre ortalama hız [m/s]; index yerel saat 0-23."""
    off = _cfg("local_utc_offset") if utc_offset is None else utc_offset
    hours = (ws.index.hour + off) % 24
    return ws.groupby(hours).mean().rename_axis("hour")


def annual_variability(ws: pd.Series) -> tuple[pd.Series, float]:
    """Yıllık ortalama hızlar [m/s] ve yıllar arası değişim katsayısı CoV = σ/μ [%]."""
    yearly = ws.groupby(ws.index.year).mean().rename_axis("year")
    cov = float(100 * yearly.std() / yearly.mean()) if len(yearly) > 1 else 0.0
    return yearly, cov


# ---------------------------------------------------------------- Weibull

@dataclass(frozen=True)
class WeibullParams:
    """Weibull parametreleri: k şekil [-], c ölçek [m/s]."""

    k: float
    c: float
    method: str


def fit_weibull_mle(ws: pd.Series) -> WeibullParams:
    """Maximum Likelihood ile Weibull uydurma (scipy.stats.weibull_min, konum = 0).

    f(v) = (k/c)(v/c)^(k-1) exp(-(v/c)^k). v = 0 değerleri log(0) nedeniyle dışlanır;
    sakin oranı basic_stats ile ayrıca raporlanır.
    """
    v = ws.dropna().to_numpy()
    v = v[v > 0]
    k, _, c = stats.weibull_min.fit(v, floc=0)
    return WeibullParams(float(k), float(c), "MLE")


def fit_weibull_moments(ws: pd.Series) -> WeibullParams:
    """Ampirik (momentler) yöntem, Justus yaklaşımı.

    k = (σ / v̄)^(-1.086),  c = v̄ / Γ(1 + 1/k)
    """
    v = ws.dropna()
    k = (v.std() / v.mean()) ** -1.086
    c = v.mean() / gamma(1 + 1 / k)
    return WeibullParams(float(k), float(c), "Momentler")


def weibull_pdf(v: np.ndarray, k: float, c: float) -> np.ndarray:
    """Weibull olasılık yoğunluğu f(v) [1/(m/s)]."""
    v = np.asarray(v, dtype=float)
    return (k / c) * (v / c) ** (k - 1) * np.exp(-((v / c) ** k))


def weibull_mean(k: float, c: float) -> float:
    """Weibull ortalaması v̄ = c·Γ(1 + 1/k) [m/s]."""
    return float(c * gamma(1 + 1 / k))


def histogram_with_fit(ws: pd.Series, bin_width: float = 1.0) -> dict[str, Any]:
    """Grafik verisi: normalize histogram ve iki yöntemin Weibull eğrileri."""
    v = ws.dropna().to_numpy()
    edges = np.arange(0, np.ceil(v.max()) + bin_width, bin_width)
    density, edges = np.histogram(v, bins=edges, density=True)
    x = np.linspace(0, edges[-1], 300)
    mle, mom = fit_weibull_mle(ws), fit_weibull_moments(ws)
    return {
        "edges": edges, "density": density, "x": x,
        "fits": {p.method: (p, weibull_pdf(x, p.k, p.c)) for p in (mle, mom)},
    }


# ---------------------------------------------------------------- rüzgar gülü

def wind_rose(ws: pd.Series, wd: pd.Series, n_sectors: int | None = None) -> pd.DataFrame:
    """Sektör bazında frekans [%] ve ortalama hız [m/s].

    Sektörler K'ye ortalanır: genişlik w = 360/n, i. sektör [i·w - w/2, i·w + w/2).
    """
    n = n_sectors or _cfg("wind_rose_sectors")
    w = 360 / n
    d = pd.concat([ws, wd], axis=1, keys=["ws", "wd"]).dropna()
    idx = (((d["wd"] % 360) + w / 2) // w).astype(int) % n
    g = d["ws"].groupby(idx)
    out = pd.DataFrame({"freq_pct": 100 * g.size() / len(d), "mean_ws": g.mean()}).reindex(range(n), fill_value=0.0)
    out["center_deg"] = out.index * w
    out["sector"] = SECTOR_NAMES_16 if n == 16 else [f"{c:.0f}°" for c in out["center_deg"]]
    return out


# ---------------------------------------------------------------- yükseklik

def site_alpha(ws_low: pd.Series, ws_high: pd.Series, h_low: float = 10, h_high: float = 50) -> float:
    """Sahaya özel power law üssü: α = ln(v̄_high / v̄_low) / ln(h_high / h_low)."""
    return float(np.log(ws_high.mean() / ws_low.mean()) / np.log(h_high / h_low))


def power_law(v1, h1: float, h2: float, alpha: float):
    """Power law: v₂ = v₁·(h₂/h₁)^α  [m/s]."""
    return v1 * (h2 / h1) ** alpha


def log_law(v1, h1: float, h2: float, z0: float):
    """Log law: v₂ = v₁·ln(h₂/z₀) / ln(h₁/z₀)  [m/s], z₀ pürüzlülük uzunluğu [m]."""
    if z0 <= 0 or h1 <= z0 or h2 <= z0:
        raise ValueError("z₀ pozitif ve her iki yükseklikten küçük olmalı.")
    return v1 * np.log(h2 / z0) / np.log(h1 / z0)


def extrapolate(
    df: pd.DataFrame,
    h2: float,
    method: Literal["power", "log"] = "power",
    alpha: float | None = None,
    z0: float | None = None,
    source_col: str = "ws50",
    h1: float = 50,
) -> pd.Series:
    """Saatlik hız serisini h2 yüksekliğine taşır.

    power: alpha verilmezse 10 m ve 50 m verisinden site_alpha ile hesaplanır.
    log: z0 zorunludur.
    """
    v1 = df[source_col]
    if method == "power":
        if alpha is None:
            alpha = site_alpha(df["ws10"], df["ws50"])
        return power_law(v1, h1, h2, alpha).rename(f"ws{h2:g}")
    if z0 is None:
        raise ValueError("Log law için z₀ seçilmeli.")
    return log_law(v1, h1, h2, z0).rename(f"ws{h2:g}")


def compare_methods(df: pd.DataFrame, h2: float, z0: float, alpha: float | None = None) -> dict[str, float]:
    """Power law ve log law ortalama hızlarını ve farkı [%] (log'a göre power) döndürür."""
    a = alpha if alpha is not None else site_alpha(df["ws10"], df["ws50"])
    vp = float(extrapolate(df, h2, "power", alpha=a).mean())
    vl = float(extrapolate(df, h2, "log", z0=z0).mean())
    return {"alpha": a, "z0": z0, "power_mean": vp, "log_mean": vl, "diff_pct": 100 * (vp - vl) / vl}


# ---------------------------------------------------------------- yoğunluk ve güç

def air_density(ps_kpa, t2m_c, r: float | None = None):
    """Hava yoğunluğu ρ = P / (R·T) [kg/m³].

    P [Pa] = PS [kPa] × 1000, T [K] = T2M [°C] + 273.15, R = 287.05 J/(kg·K).
    """
    r = _cfg("gas_constant_dry_air") if r is None else r
    return (ps_kpa * 1000.0) / (r * (t2m_c + 273.15))


def power_density_timeseries(ws, rho) -> float:
    """Ortalama rüzgar güç yoğunluğu P/A = mean(½·ρ·v³) [W/m²] (ortalama hızın küpü değil)."""
    return float(np.nanmean(0.5 * np.asarray(rho) * np.asarray(ws) ** 3))


def power_density_weibull(k: float, c: float, rho: float) -> float:
    """Weibull'dan analitik güç yoğunluğu P/A = ½·ρ·c³·Γ(1 + 3/k) [W/m²]."""
    return float(0.5 * rho * c**3 * gamma(1 + 3 / k))


def wind_class(power_density: float, height: float = 50) -> dict[str, Any]:
    """NREL/PNL rüzgar güç sınıfı (1-7). 10 m ve 50 m tablolarından yüksekliğe en yakını kullanılır."""
    tables = {int(h): v for h, v in _cfg("wind_power_classes").items()}
    ref = min(tables, key=lambda h: abs(h - height))
    cls = int(np.searchsorted(tables[ref], power_density, side="right"))
    return {"class": cls, "name": CLASS_NAMES[cls - 1], "table_height": ref}
