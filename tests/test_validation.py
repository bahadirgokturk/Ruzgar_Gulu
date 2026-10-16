"""Faz 8: elle çözülmüş örnek problemlerle doğrulama.

Ders kitabı örneği sağlanmadığı için, kapalı formda çözülebilen klasik ders kitabı problemleri kullanılmıştır
(Manwell vd., Wind Energy Explained, Bölüm 2 ve 11). Her testte beklenen değer elle (analitik) hesaplanmış,
yazılımın sayısal sonucu bununla karşılaştırılmıştır.
"""
import math

import numpy as np
import pandas as pd
import pytest

from core import economics as ec
from core import energy as en
from core import wind_resource as wr


# ---------------------------------------------------------------- Problem 1: Rayleigh rüzgar rejimi
# Ortalama hızı 7 m/s olan bir sahada dağılım Rayleigh (k = 2) kabul ediliyor, ρ = 1.225 kg/m³.
# a) c = v̄ / Γ(1.5) = 7 / 0.886227 = 7.8987 m/s
# b) Güç yoğunluğu = ½ρ·(6/π)·v̄³ = 0.5·1.225·1.909859·343 = 401.24 W/m²  (enerji örüntü faktörü 6/π)
# c) v > 10 m/s olma olasılığı = exp(−(π/4)(10/7)²) = exp(−1.60285) = 0.20130

V_MEAN = 7.0
C_RAYLEIGH = V_MEAN / math.gamma(1.5)


def test_p1_rayleigh_scale():
    assert C_RAYLEIGH == pytest.approx(7.8987, abs=1e-4)
    assert wr.weibull_mean(2.0, C_RAYLEIGH) == pytest.approx(V_MEAN)


def test_p1_power_density_energy_pattern_factor():
    hand = 0.5 * 1.225 * (6 / math.pi) * V_MEAN**3
    assert hand == pytest.approx(401.24, abs=0.01)
    assert wr.power_density_weibull(2.0, C_RAYLEIGH, 1.225) == pytest.approx(hand, rel=1e-9)


def test_p1_exceedance_probability():
    v = np.linspace(10, 60, 50_001)
    p_num = np.trapezoid(wr.weibull_pdf(v, 2.0, C_RAYLEIGH), v)
    assert p_num == pytest.approx(0.20130, abs=1e-4)


def test_p1_weibull_fit_recovers_rayleigh():
    rng = np.random.default_rng(7)
    ws = pd.Series(C_RAYLEIGH * rng.weibull(2.0, 100_000))
    p = wr.fit_weibull_mle(ws)
    assert p.k == pytest.approx(2.0, rel=0.02) and p.c == pytest.approx(C_RAYLEIGH, rel=0.02)


# ---------------------------------------------------------------- Problem 2: ideal türbin AEP
# Nominal gücü 1500 kW olan ideal bir türbin 12 m/s ile 25 m/s arasında sabit 1500 kW üretiyor, dışında üretmiyor.
# Saha Weibull k = 2, c = 8 m/s. Kapalı form:
#   AEP = 8760·Pₙ·[exp(−(vᵣ/c)^k) − exp(−(v_f/c)^k)]
#       = 8760·1500·[exp(−2.25) − exp(−9.765625)] = 13 140 000·(0.105399 − 0.0000573) kWh
#       ≈ 1 384.2 MWh/yıl,  CF = 1384.2 / (1.5·8760) = %10.53

def test_p2_ideal_turbine_aep():
    v = np.array([0, 11.999, 12, 25, 25.001, 30.0])
    curve = pd.DataFrame({"wind_speed": v, "power_kw": [0, 0, 1500, 1500, 0, 0]})
    hand = 8760 * 1500 * (math.exp(-(12 / 8) ** 2) - math.exp(-(25 / 8) ** 2)) / 1000
    assert hand == pytest.approx(1384.2, abs=0.1)
    assert en.aep_weibull(2.0, 8.0, curve, dv=0.001) == pytest.approx(hand, rel=2e-3)
    assert hand / (1.5 * 8760) == pytest.approx(0.1053, abs=1e-4)


# ---------------------------------------------------------------- Problem 3: yükseklik ekstrapolasyonu
# 10 m'de 5 m/s ölçülmüş. 80 m'deki hız:
#   Power law, α = 1/7:  5·8^(1/7) = 6.73 m/s
#   Log law, z₀ = 0.03 m: 5·ln(80/0.03)/ln(10/0.03) = 5·7.8886/5.8091 = 6.79 m/s

def test_p3_extrapolation():
    assert wr.power_law(5.0, 10, 80, 1 / 7) == pytest.approx(6.73, abs=0.005)
    assert wr.log_law(5.0, 10, 80, 0.03) == pytest.approx(6.79, abs=0.005)


# ---------------------------------------------------------------- Problem 4: LCOE, sermaye geri kazanım faktörü
# 2 MW türbin, CAPEX 1300 $/kW (2.6 M$), OPEX 40 $/kW/yıl (80 000 $/yıl), net AEP 6000 MWh/yıl sabit,
# r = %8, n = 20 yıl. Ders kitabı formülü:
#   CRF = r(1+r)^n / ((1+r)^n − 1) = 0.08·4.660957 / 3.660957 = 0.101852
#   LCOE = (CAPEX·CRF + OPEX) / AEP = (264 815.7 + 80 000) / 6000 = 57.47 $/MWh
# Bu, yazılımdaki Σ maliyet/(1+r)ᵗ ÷ Σ üretim/(1+r)ᵗ tanımıyla matematiksel olarak özdeştir.

def test_p4_lcoe_crf():
    r, n = 0.08, 20
    crf = r * (1 + r) ** n / ((1 + r) ** n - 1)
    assert crf == pytest.approx(0.101852, abs=1e-6)
    hand = (2_600_000 * crf + 80_000) / 6000
    assert hand == pytest.approx(57.47, abs=0.01)
    inp = ec.EconomicInputs.from_defaults(capex_per_kw=1300, opex_per_kw_year=40, opex_escalation=0.0,
                                          discount_rate=r, lifetime=n, degradation=0.0)
    assert ec.lcoe(inp, ec.cash_flow_table(inp, 6000, 2000)) == pytest.approx(hand, rel=1e-9)


# ---------------------------------------------------------------- Problem 5: NPV/IRR, eşit nakit akışı (anüite)
# Yatırım 1000, 10 yıl boyunca yılda 150 net nakit girişi.
#   NPV(%8) = −1000 + 150·(1 − 1.08^−10)/0.08 = −1000 + 150·6.710081 = 6.51
#   IRR: 150·(1 − (1+i)^−10)/i = 1000  →  i ≈ %8.144

def test_p5_npv_irr_annuity():
    cf = [-1000] + [150] * 10
    assert ec.npv(0.08, cf) == pytest.approx(6.512, abs=0.001)
    assert ec.irr(cf) == pytest.approx(0.08144, abs=1e-5)
    assert ec.payback(cf) == pytest.approx(1000 / 150, rel=1e-9)
