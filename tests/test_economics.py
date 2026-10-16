"""Faz 4: ekonomik analiz testleri."""
from dataclasses import replace

import numpy as np
import pytest

from core import economics as ec
from core.plots import cash_flow_plot, tornado_plot


@pytest.fixture
def inp():
    return ec.EconomicInputs.from_defaults()


def test_npv_irr_hand_calculated():
    cf = [-1000, 300, 400, 500]
    # Elle: -1000 + 300/1.1 + 400/1.21 + 500/1.331 = -1000 + 272.727 + 330.579 + 375.657
    assert ec.npv(0.10, cf) == pytest.approx(-21.037, abs=0.01)
    r = ec.irr(cf)
    assert r == pytest.approx(0.0889633947, abs=1e-6)
    assert ec.npv(r, cf) == pytest.approx(0, abs=1e-6)


def test_payback():
    assert ec.payback([-100, 40, 40, 40]) == pytest.approx(2.5)
    assert ec.payback([-100, 10, 10]) is None
    # iskontolu: kümülatif -100, -63.64, -30.58, -0.53, ... -> 4. yılda geçer
    assert ec.payback([-100, 40, 40, 40, 40], 0.10) > 3


def test_lcoe_zero_discount(inp):
    i0 = replace(inp, discount_rate=0.0, degradation=0.0, opex_escalation=0.0, lifetime=20)
    t = ec.cash_flow_table(i0, 5000, 2300)
    total_cost = 1300 * 2300 + 40 * 2300 * 20
    assert ec.lcoe(i0, t) == pytest.approx(total_cost / (5000 * 20))


def test_incentive_and_escalation(inp):
    i2 = replace(inp, incentive_years=10, incentive_price=73, market_price=60, price_escalation=0.01)
    assert ec.price_for_year(i2, 10) == 73
    assert ec.price_for_year(i2, 11) == 60
    assert ec.price_for_year(i2, 12) == pytest.approx(60.6)


def test_degradation_and_table(inp):
    t = ec.cash_flow_table(inp, 5000, 2300)
    assert len(t) == inp.lifetime + 1
    assert t.loc[2, "energy_mwh"] == pytest.approx(5000 * (1 - inp.degradation))
    assert t.loc[0, "net_cf"] == pytest.approx(-1300 * 2300)


def test_loan_repaid(inp):
    il = replace(inp, loan_enabled=True)
    t = ec.cash_flow_table(il, 5000, 2300)
    assert t["principal"].sum() == pytest.approx(1300 * 2300 * 0.7)
    assert t.loc[il.loan_term + 1, "interest"] == 0


@pytest.mark.parametrize("bad", [dict(capex_per_kw=0), dict(lifetime=0), dict(incentive_years=40)])
def test_invalid_inputs(inp, bad):
    with pytest.raises(ValueError):
        ec.cash_flow_table(replace(inp, **bad), 5000, 2300)


def test_sensitivity_directions(inp):
    s = ec.sensitivity(inp, 5000, 2300)
    get = lambda p, d: s[(s.param == p) & np.isclose(s.delta, d)].iloc[0]
    assert get("aep", 0.1).d_npv > 0
    assert get("capex", 0.1).d_npv < 0
    assert get("capex", 0.1).d_lcoe > 0
    assert get("price", 0.1).d_lcoe == pytest.approx(0)
    cash_flow_plot(ec.evaluate(inp, 5000, 2300)["table"])
    tornado_plot(s)


def test_scenarios_order(inp):
    sc = ec.scenarios(inp, 5000, 2300)
    assert sc.loc["Kötümser", "npv"] < sc.loc["Baz", "npv"] < sc.loc["İyimser", "npv"]
    assert sc.loc["Kötümser", "net_aep"] == pytest.approx(5000 * (1 - 1.282 * inp.aep_sigma))
