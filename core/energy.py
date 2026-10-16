"""Türbin güç eğrileri, brüt/net AEP ve kayıplar.

Birimler: hız m/s, güç kW (iç gösterim), enerji MWh, yoğunluk kg/m³.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.config import load_defaults

LOSS_LABELS = {
    "wake": "İz (wake)",
    "availability": "Kullanılabilirlik",
    "electrical": "Elektriksel",
    "turbine_performance": "Türbin performansı",
    "environmental": "Çevresel",
    "curtailment": "Şebeke kısıtı",
}


def _cfg(key: str) -> Any:
    return load_defaults()["energy"][key]["value"]


def default_losses() -> dict[str, float]:
    """defaults.yaml'daki kayıp oranları {anahtar: oran}."""
    return {k: v["value"] for k, v in load_defaults()["losses"].items()}


# ---------------------------------------------------------------- türbin

@dataclass
class Turbine:
    """Türbin tanımı. curve: 'wind_speed' [m/s] ve 'power_kw' [kW] sütunlu DataFrame."""

    name: str
    rated_kw: float
    rotor_d: float | None
    hub_height: float
    curve: pd.DataFrame = field(repr=False)


def _oedb_turbine_data() -> pd.DataFrame:
    import windpowerlib

    path = os.path.join(os.path.dirname(windpowerlib.__file__), "oedb", "turbine_data.csv")
    return pd.read_csv(path)


def list_turbines() -> pd.DataFrame:
    """windpowerlib (oedb) kütüphanesinde güç eğrisi olan türbinleri listeler.

    Sütunlar: manufacturer, turbine_type, rated_kw, rotor_d [m], hub_heights (metin, ';' ayrılmış).
    """
    t = _oedb_turbine_data()
    t = t[t["has_power_curve"] == True]  # noqa: E712
    return (
        t.assign(rated_kw=t["nominal_power"] / 1000.0)
        .rename(columns={"rotor_diameter": "rotor_d", "hub_height": "hub_heights"})
        [["manufacturer", "turbine_type", "rated_kw", "rotor_d", "hub_heights"]]
        .sort_values(["manufacturer", "turbine_type"])
        .reset_index(drop=True)
    )


def load_library_turbine(turbine_type: str, hub_height: float) -> Turbine:
    """windpowerlib.WindTurbine'den güç eğrisini yükler (W -> kW çevrilir)."""
    from windpowerlib import WindTurbine

    wt = WindTurbine(hub_height=hub_height, turbine_type=turbine_type)
    curve = pd.DataFrame({
        "wind_speed": wt.power_curve["wind_speed"].to_numpy(float),
        "power_kw": wt.power_curve["value"].to_numpy(float) / 1000.0,
    })
    return Turbine(turbine_type, wt.nominal_power / 1000.0, wt.rotor_diameter, hub_height, curve)


def load_custom_curve_csv(path: str | Path, hub_height: float, name: str | None = None,
                          rated_kw: float | None = None, rotor_d: float | None = None) -> Turbine:
    """Özel güç eğrisi CSV'si: 'wind_speed' [m/s] ve 'power_kw' [kW] sütunları zorunlu."""
    curve = pd.read_csv(path)
    if not {"wind_speed", "power_kw"} <= set(curve.columns):
        raise ValueError("Güç eğrisi CSV'si 'wind_speed' ve 'power_kw' sütunlarını içermeli.")
    curve = curve[["wind_speed", "power_kw"]].astype(float).sort_values("wind_speed").reset_index(drop=True)
    return Turbine(name or Path(path).stem, rated_kw or float(curve["power_kw"].max()), rotor_d, hub_height, curve)


# ---------------------------------------------------------------- yoğunluk düzeltmesi

def density_corrected_curve(curve: pd.DataFrame, rho: float, method: str | None = None) -> pd.DataFrame:
    """Güç eğrisini saha hava yoğunluğuna göre düzeltir.

    iec (IEC 61400-12-1): v_site = v_std · (ρ₀/ρ_site)^(1/3), güç değerleri aynı kalır.
    svenningsen: windpowerlib.power_output.power_curve_density_correction ile
        değişken üslü düzeltme (1/3 → 2/3), 0.1 m/s ızgarada yeniden örneklenir.
    ρ₀ = 1.225 kg/m³ (defaults.yaml).
    """
    method = method or _cfg("density_correction_method")
    rho0 = _cfg("standard_density")
    if method == "iec":
        out = curve.copy()
        out["wind_speed"] = curve["wind_speed"] * (rho0 / rho) ** (1 / 3)
        return out
    if method == "svenningsen":
        from windpowerlib.power_output import power_curve_density_correction

        grid = np.arange(0, curve["wind_speed"].max() + 0.05, 0.1)
        p = power_curve_density_correction(
            pd.Series(grid), curve["wind_speed"].to_numpy(), curve["power_kw"].to_numpy(), np.full(len(grid), rho))
        return pd.DataFrame({"wind_speed": grid, "power_kw": np.asarray(p, float)})
    raise ValueError(f"Bilinmeyen yoğunluk düzeltme yöntemi: {method}")


def power_from_curve(ws, curve: pd.DataFrame) -> np.ndarray:
    """Güç eğrisini hızlara doğrusal interpolasyonla uygular [kW].

    Eğri aralığı dışında (kesme hızı altı/üstü) P = 0.
    """
    return np.interp(np.asarray(ws, float), curve["wind_speed"], curve["power_kw"], left=0.0, right=0.0)


# ---------------------------------------------------------------- AEP

def aep_timeseries(ws_hub: pd.Series, curve: pd.DataFrame) -> float:
    """Zaman serisi yöntemi: AEP = mean(P(vₜ)) · 8760 / 1000  [MWh/yıl].

    Eksik saatler ortalamaya girmez (toplam yerine ortalama ile yıllığa ölçekleme).
    """
    p = power_from_curve(ws_hub.dropna(), curve)
    return float(p.mean() * _cfg("hours_per_year") / 1000.0)


def aep_weibull(k: float, c: float, curve: pd.DataFrame, dv: float = 0.01) -> float:
    """Weibull yöntemi: AEP = 8760 · ∫ P(v)·f(v) dv / 1000  [MWh/yıl] (sayısal trapez integrali)."""
    from core.wind_resource import weibull_pdf

    v = np.arange(dv, curve["wind_speed"].max() + dv, dv)
    return float(np.trapezoid(power_from_curve(v, curve) * weibull_pdf(v, k, c), v) * _cfg("hours_per_year") / 1000.0)


def monthly_energy(ws_hub: pd.Series, curve: pd.DataFrame) -> pd.Series:
    """Ortalama aylık üretim [MWh/ay]: her (yıl, ay) için Σ P·1h, sonra yıllar üzerinden ortalama.

    Saatlik veri varsayılır.
    """
    p = pd.Series(power_from_curve(ws_hub, curve), index=ws_hub.index).where(ws_hub.notna())
    by_ym = p.groupby([p.index.year, p.index.month]).sum() / 1000.0
    return by_ym.groupby(level=1).mean().rename_axis("month")


# ---------------------------------------------------------------- kayıplar

def apply_losses(gross: float, losses: dict[str, float]) -> tuple[float, pd.DataFrame]:
    """Çarpımsal kayıp: Net = Brüt · Π(1 − kᵢ)  [MWh/yıl].

    Tablo, her kalemin sırayla uygulandığında düşürdüğü enerjiyi verir (şelale grafiği için).
    """
    rows, remaining = [], gross
    for key, k in losses.items():
        if not 0 <= k < 1:
            raise ValueError(f"Kayıp oranı 0 ile 1 arasında olmalı: {key}={k}")
        lost = remaining * k
        rows.append({"key": key, "label": LOSS_LABELS.get(key, key), "rate": k, "lost_mwh": lost})
        remaining -= lost
    table = pd.DataFrame(rows, columns=["key", "label", "rate", "lost_mwh"])
    return remaining, table


def total_loss_factor(losses: dict[str, float]) -> float:
    """Toplam kayıp oranı 1 − Π(1 − kᵢ)."""
    return 1.0 - float(np.prod([1 - k for k in losses.values()]))


# ---------------------------------------------------------------- özet

def energy_summary(
    ws_hub: pd.Series,
    turbine: Turbine,
    rho: float,
    n_turbines: int = 1,
    losses: dict[str, float] | None = None,
    density_method: str | None = None,
) -> dict[str, Any]:
    """Türbin/çiftlik için enerji özeti.

    Brüt AEP = N · AEP_tek; tek türbinde iz kaybı 0 alınır.
    CF = Net / (Pₙ · N · 8760);  tam yük saati = Net / (Pₙ · N)  [h].
    """
    from core.wind_resource import fit_weibull_mle

    if n_turbines < 1:
        raise ValueError("Türbin adedi en az 1 olmalı.")
    losses = dict(default_losses() if losses is None else losses)
    if n_turbines == 1:
        losses["wake"] = 0.0
    curve = density_corrected_curve(turbine.curve, rho, density_method)
    w = fit_weibull_mle(ws_hub)
    gross_ts = aep_timeseries(ws_hub, curve) * n_turbines
    gross_wb = aep_weibull(w.k, w.c, curve) * n_turbines
    net, loss_table = apply_losses(gross_ts, losses)
    capacity_mw = turbine.rated_kw * n_turbines / 1000.0
    hours = _cfg("hours_per_year")
    monthly = monthly_energy(ws_hub, curve) * n_turbines
    return {
        "turbine": turbine.name,
        "n_turbines": n_turbines,
        "capacity_mw": capacity_mw,
        "hub_height": turbine.hub_height,
        "rho": rho,
        "weibull_hub": w,
        "gross_aep_ts": gross_ts,
        "gross_aep_weibull": gross_wb,
        "method_diff_pct": 100 * (gross_wb - gross_ts) / gross_ts if gross_ts else 0.0,
        "losses": losses,
        "loss_table": loss_table,
        "total_loss_pct": 100 * total_loss_factor(losses),
        "net_aep": net,
        "capacity_factor": net / (capacity_mw * hours) if capacity_mw else 0.0,
        "full_load_hours": net / capacity_mw if capacity_mw else 0.0,
        "monthly_gross": monthly,
        "monthly_net": monthly * (net / gross_ts if gross_ts else 0.0),
        "curve_std": turbine.curve,
        "curve_site": curve,
    }
