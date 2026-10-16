"""Faz 5: çevresel etki testleri."""
import pytest

from core import environment as env


def test_avoided_co2_hand():
    assert env.avoided_co2(5000, 0.438) == pytest.approx(2190)


def test_lifetime_without_degradation():
    assert env.lifetime_avoided(5000, 25, 0.0, 0.438) == pytest.approx(2190 * 25)
    assert env.lifetime_avoided(5000, 25, 0.01, 0.438) < 2190 * 25


def test_households():
    assert env.household_equivalent(2400, 2400) == pytest.approx(1000)


@pytest.mark.parametrize("call", [lambda: env.avoided_co2(-1), lambda: env.household_equivalent(100, 0),
                                  lambda: env.lifetime_avoided(100, 0)])
def test_invalid(call):
    with pytest.raises(ValueError):
        call()


def test_summary_notes():
    s = env.environment_summary(5000, 25, notes={"noise": " 1.2 km "})
    assert s["qualitative"]["noise"] == ("Gürültü", "1.2 km")
    assert s["qualitative"]["birds"][1] == ""
