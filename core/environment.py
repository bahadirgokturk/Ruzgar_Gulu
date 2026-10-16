"""Çevresel etki: önlenen CO2 ve eşdeğerlikler, nitel değerlendirme başlıkları.

Birimler: enerji MWh, emisyon tCO₂, emisyon faktörü tCO₂/MWh, hane tüketimi kWh/yıl.
"""
from __future__ import annotations

from typing import Any

from core.config import load_defaults

# Rapordaki nitel başlıklar: anahtar -> (başlık, kullanıcıya yönlendirici açıklama)
QUALITATIVE_SECTIONS = {
    "noise": ("Gürültü", "En yakın yerleşime uzaklık, beklenen ses seviyesi ve yönetmelik sınırları."),
    "shadow_flicker": ("Gölge titreşimi", "Güneşin alçak olduğu saatlerde yakın konutlara düşen kanat gölgesi."),
    "birds": ("Kuş ve yarasa göçü", "Sahanın göç yolları ve hassas yaşam alanlarına yakınlığı."),
    "visual": ("Görsel etki", "Türbinin yakın yerleşim ve manzara noktalarından görünürlüğü."),
}


def _cfg(key: str) -> Any:
    return load_defaults()["environment"][key]["value"]


def avoided_co2(net_aep_mwh: float, ef: float | None = None) -> float:
    """Yıllık önlenen CO₂ = Net AEP [MWh/yıl] × EF [tCO₂/MWh]  →  [tCO₂/yıl]."""
    ef = _cfg("grid_emission_factor") if ef is None else ef
    if net_aep_mwh < 0 or ef < 0:
        raise ValueError("Net AEP ve emisyon faktörü negatif olamaz.")
    return net_aep_mwh * ef


def lifetime_avoided(net_aep_mwh: float, lifetime: int, degradation: float = 0.0, ef: float | None = None) -> float:
    """Ömür boyu önlenen CO₂ = Σₜ AEP·(1−d)^(t−1)·EF, t = 1..N  [tCO₂]."""
    if lifetime < 1:
        raise ValueError("Proje ömrü en az 1 yıl olmalı.")
    return sum(avoided_co2(net_aep_mwh * (1 - degradation) ** (t - 1), ef) for t in range(1, lifetime + 1))


def household_equivalent(net_aep_mwh: float, kwh_per_household: float | None = None) -> float:
    """Karşılanan hane sayısı = Net AEP·1000 [kWh] / hane tüketimi [kWh/yıl]."""
    kwh = _cfg("household_consumption") if kwh_per_household is None else kwh_per_household
    if kwh <= 0:
        raise ValueError("Hane tüketimi sıfırdan büyük olmalı.")
    return net_aep_mwh * 1000.0 / kwh


def environment_summary(net_aep_mwh: float, lifetime: int, degradation: float = 0.0,
                        ef: float | None = None, kwh_per_household: float | None = None,
                        notes: dict[str, str] | None = None) -> dict[str, Any]:
    """Çevresel etki özeti; notes: nitel başlıklar için kullanıcı metinleri."""
    ef = _cfg("grid_emission_factor") if ef is None else ef
    kwh = _cfg("household_consumption") if kwh_per_household is None else kwh_per_household
    return {
        "emission_factor": ef,
        "annual_co2_t": avoided_co2(net_aep_mwh, ef),
        "lifetime_co2_t": lifetime_avoided(net_aep_mwh, lifetime, degradation, ef),
        "households": household_equivalent(net_aep_mwh, kwh),
        "household_kwh": kwh,
        "qualitative": {k: (title, (notes or {}).get(k, "").strip()) for k, (title, _) in QUALITATIVE_SECTIONS.items()},
    }
