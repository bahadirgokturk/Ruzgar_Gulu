"""Faz 8: uç durum testleri (düşük rüzgar, eksik veri, geçersiz girdiler)."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from core import economics as ec
from core import energy as en
from core.analysis import AnalysisInputs, run_analysis
from core.data_sources import clean_wind_data
from core.report import ReportMeta, build_report

TURBINE = en.load_library_turbine("E-82/2300", 98)


def make_df(scale: float, n: int = 8760, seed: int = 0, nan_frac: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    ws50 = scale * rng.weibull(2.0, n)
    df = pd.DataFrame({"ws10": ws50 * 0.8, "ws50": ws50, "wd50": rng.uniform(0, 360, n),
                       "t2m_c": np.full(n, 15.0), "ps_kpa": np.full(n, 101.325)}, index=idx)
    if nan_frac:
        df.loc[df.sample(frac=nan_frac, random_state=seed).index, ["ws10", "ws50"]] = np.nan
    return df


def analyse(df: pd.DataFrame, **kw) -> object:
    df, q = clean_wind_data(df)
    return run_analysis(AnalysisInputs(lat=0, lon=0, df=df, quality=q.as_dict(), source_label="test",
                                       turbine=TURBINE, econ=ec.EconomicInputs.from_defaults(), **kw))


def test_very_low_wind_site(tmp_path):
    r = analyse(make_df(1.5))
    assert r.energy["capacity_factor"] < 0.01
    assert r.wind_class["class"] == 1
    assert r.econ is not None and r.econ["npv"] < 0 and r.econ["payback"] is None
    path = build_report(r, ReportMeta("Düşük rüzgar", include_map=False), out_dir=tmp_path)
    assert path.exists()


def test_zero_production_gives_clear_error():
    inp = ec.EconomicInputs.from_defaults()
    with pytest.raises(ValueError, match="LCOE"):
        ec.lcoe(inp, ec.cash_flow_table(inp, 0.0, 2300))


def test_missing_data_is_reported_and_tolerated():
    r = analyse(make_df(7.0, nan_frac=0.3))
    assert r.inputs.quality["missing_pct"] == pytest.approx(30, abs=0.5)
    full = analyse(make_df(7.0))
    # eksik saatler ortalamaya girmediği için yıllık üretim kaba ölçüde korunur
    assert r.energy["gross_aep_ts"] == pytest.approx(full.energy["gross_aep_ts"], rel=0.05)


@pytest.mark.parametrize("bad", [dict(capex_per_kw=0), dict(capex_per_kw=-100), dict(lifetime=0),
                                 dict(discount_rate=-1.5), dict(capex_split={"Türbin": 0.5})])
def test_invalid_economic_inputs(bad):
    with pytest.raises(ValueError):
        replace(ec.EconomicInputs.from_defaults(), **bad).validate()


def test_economic_error_does_not_break_analysis(tmp_path):
    df, q = clean_wind_data(make_df(7.0))
    r = run_analysis(AnalysisInputs(lat=0, lon=0, df=df, quality=q.as_dict(), source_label="test", turbine=TURBINE,
                                    econ=ec.EconomicInputs.from_defaults(capex_per_kw=0)))
    assert r.econ is None and "CAPEX" in r.econ_error
    text = build_report(r, ReportMeta("Hatalı ekonomi", include_map=False), out_dir=tmp_path)
    assert text.exists()


def test_negative_aep_and_turbine_count():
    with pytest.raises(ValueError):
        ec.cash_flow_table(ec.EconomicInputs.from_defaults(), -1, 2300)
    with pytest.raises(ValueError):
        en.energy_summary(make_df(7.0)["ws50"], TURBINE, 1.2, n_turbines=0)


def test_measurement_without_met_uses_standard_density():
    df = make_df(7.0)[["ws50", "wd50"]].rename(columns={"ws50": "ws", "wd50": "wd"})
    r = analyse(df, is_nasa=False, h1=50, ws_col="ws", wd_col="wd", alpha=0.143)
    assert r.rho_is_standard and r.rho == pytest.approx(1.225)
    with pytest.raises(ValueError, match="sabit α"):
        analyse(df, is_nasa=False, h1=50, ws_col="ws", wd_col="wd")


def test_irr_none_when_never_positive():
    assert ec.irr([-100, -10, -10]) is None
