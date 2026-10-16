"""Faz 3: türbin ve enerji üretimi testleri."""
import numpy as np
import pandas as pd
import pytest

from core import energy as en
from core.plots import loss_waterfall, power_curve_plot

V = np.arange(0, 26, 1.0)
CURVE = pd.DataFrame({"wind_speed": V, "power_kw": np.clip(2000 * ((V - 3) / 9) ** 3, 0, 2000) * (V >= 3)})


def series(value, n=8760):
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.Series(np.full(n, value), index=idx)


def test_aep_constant_above_rated():
    assert en.aep_timeseries(series(15.0), CURVE) == pytest.approx(2000 * 8760 / 1000)


@pytest.mark.parametrize("v", [2.0, 30.0])
def test_zero_outside_operating_range(v):
    assert en.aep_timeseries(series(v), CURVE) == 0.0


def test_losses_multiplicative():
    net, table = en.apply_losses(1000.0, {"a": 0.1, "b": 0.1})
    assert net == pytest.approx(810.0)
    assert table["lost_mwh"].sum() == pytest.approx(190.0)
    assert en.total_loss_factor({"a": 0.1, "b": 0.1}) == pytest.approx(0.19)
    with pytest.raises(ValueError):
        en.apply_losses(1000.0, {"a": 1.2})


def test_density_correction():
    same = en.density_corrected_curve(CURVE, 1.225, "iec")
    pd.testing.assert_frame_equal(same, CURVE)
    low = en.density_corrected_curve(CURVE, 1.10, "iec")
    assert low["wind_speed"].iloc[12] == pytest.approx(12 * (1.225 / 1.10) ** (1 / 3))
    sv = en.density_corrected_curve(CURVE, 1.10, "svenningsen")
    assert en.power_from_curve(8.0, sv) < en.power_from_curve(8.0, CURVE)


def test_timeseries_vs_weibull():
    rng = np.random.default_rng(1)
    ws = pd.Series(7.0 * rng.weibull(2.0, 200_000))
    assert en.aep_weibull(2.0, 7.0, CURVE) == pytest.approx(en.aep_timeseries(ws, CURVE), rel=0.02)


def test_monthly_energy_sums_to_annual():
    m = en.monthly_energy(series(15.0, 8784), CURVE)  # 2024 artık yıl
    assert len(m) == 12
    assert m.sum() == pytest.approx(2000 * 8784 / 1000)


def test_library_turbine_and_summary():
    lib = en.list_turbines()
    assert "E-82/2300" in lib["turbine_type"].values
    t = en.load_library_turbine("E-82/2300", 98)
    assert t.rated_kw == pytest.approx(2300) and t.rotor_d == pytest.approx(82)
    rng = np.random.default_rng(2)
    idx = pd.date_range("2024-01-01", periods=8760, freq="h", tz="UTC")
    s = en.energy_summary(pd.Series(7.0 * rng.weibull(2.0, 8760), index=idx), t, rho=1.2)
    assert s["losses"]["wake"] == 0.0
    assert 0 < s["capacity_factor"] < 1
    assert s["net_aep"] < s["gross_aep_ts"]
    farm = en.energy_summary(pd.Series(7.0 * rng.weibull(2.0, 8760), index=idx), t, rho=1.2, n_turbines=3)
    assert farm["losses"]["wake"] > 0
    power_curve_plot(s["curve_std"], s["curve_site"])
    loss_waterfall(s["gross_aep_ts"], s["loss_table"], s["net_aep"])


def test_custom_curve_csv(tmp_path):
    p = tmp_path / "my.csv"
    CURVE.to_csv(p, index=False)
    t = en.load_custom_curve_csv(p, hub_height=80)
    assert t.rated_kw == 2000 and t.name == "my"
    bad = tmp_path / "bad.csv"
    bad.write_text("v,p\n1,2\n")
    with pytest.raises(ValueError):
        en.load_custom_curve_csv(bad, 80)
