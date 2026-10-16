"""Faz 2: rüzgar kaynağı analizi testleri."""
import numpy as np
import pandas as pd
import pytest

from core import wind_resource as wr
from core.plots import weibull_histogram, wind_rose_plot


@pytest.fixture(scope="module")
def synthetic():
    rng = np.random.default_rng(42)
    v = 7.0 * rng.weibull(2.0, 50_000)
    idx = pd.date_range("2021-01-01", periods=len(v), freq="h", tz="UTC")
    return pd.Series(v, index=idx)


@pytest.mark.parametrize("fit", [wr.fit_weibull_mle, wr.fit_weibull_moments])
def test_weibull_recovery(synthetic, fit):
    p = fit(synthetic)
    assert p.k == pytest.approx(2.0, rel=0.03)
    assert p.c == pytest.approx(7.0, rel=0.03)


def test_weibull_pdf_integrates_to_one():
    x = np.linspace(0, 60, 20_001)
    assert np.trapezoid(wr.weibull_pdf(x, 2.0, 7.0), x) == pytest.approx(1.0, abs=1e-4)


def test_power_law():
    assert wr.power_law(5.0, 10, 80, 0.0) == pytest.approx(5.0)
    assert wr.power_law(5.0, 10, 20, 0.143) == pytest.approx(5.0 * 2**0.143)


def test_log_law():
    expected = 5.0 * np.log(100 / 0.03) / np.log(10 / 0.03)
    assert wr.log_law(5.0, 10, 100, 0.03) == pytest.approx(expected)
    with pytest.raises(ValueError):
        wr.log_law(5.0, 10, 100, 0)


def test_site_alpha():
    a = wr.site_alpha(pd.Series([4.0]), pd.Series([4.0 * 5**0.2]))
    assert a == pytest.approx(0.2)


def test_air_density_standard():
    assert wr.air_density(101.325, 15.0) == pytest.approx(1.225, abs=0.001)


def test_power_density():
    assert wr.power_density_timeseries(np.full(10, 10.0), 1.225) == pytest.approx(612.5)


def test_power_density_weibull_matches_series(synthetic):
    ts = wr.power_density_timeseries(synthetic, 1.225)
    an = wr.power_density_weibull(2.0, 7.0, 1.225)
    assert ts == pytest.approx(an, rel=0.03)


def test_wind_rose_sectors():
    ws = pd.Series([5.0, 6.0, 7.0, 8.0])
    wd = pd.Series([355.0, 10.0, 90.0, 180.0])
    rose = wr.wind_rose(ws, wd)
    assert rose["freq_pct"].sum() == pytest.approx(100)
    assert rose.loc[0, "freq_pct"] == pytest.approx(50)     # 355° ve 10° -> K
    assert rose.loc[0, "mean_ws"] == pytest.approx(5.5)
    assert rose.loc[4, "sector"] == "D"


@pytest.mark.parametrize("pd_, h, cls", [(150, 50, 1), (200, 50, 2), (850, 50, 7), (120, 10, 2), (50, 100, 1)])
def test_wind_class(pd_, h, cls):
    assert wr.wind_class(pd_, h)["class"] == cls


def test_extrapolate_and_compare():
    idx = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
    df = pd.DataFrame({"ws10": [4.0, 4.0, 4.0], "ws50": [5.0, 5.0, 5.0]}, index=idx)
    v = wr.extrapolate(df, 100)
    alpha = np.log(5 / 4) / np.log(5)
    assert v.iloc[0] == pytest.approx(5.0 * 2**alpha)
    cmp_ = wr.compare_methods(df, 100, z0=0.03)
    assert cmp_["alpha"] == pytest.approx(alpha)


def test_stats_and_profiles(synthetic):
    s = wr.basic_stats(synthetic)
    assert s["mean"] == pytest.approx(wr.weibull_mean(2.0, 7.0), rel=0.02)
    assert len(wr.monthly_profile(synthetic)) == 12
    assert len(wr.diurnal_profile(synthetic)) == 24
    yearly, cov = wr.annual_variability(synthetic)
    assert cov >= 0


def test_plots_render(synthetic):
    weibull_histogram(synthetic)
    wind_rose_plot(wr.wind_rose(synthetic, pd.Series(np.linspace(0, 359, len(synthetic)), index=synthetic.index)))
