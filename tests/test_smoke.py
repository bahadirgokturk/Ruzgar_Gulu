"""Faz 0 duman testleri: modüller yükleniyor, yaml okunuyor."""
import importlib

import pytest

from core.config import load_defaults


@pytest.mark.parametrize("name", ["data_sources", "wind_resource", "energy", "economics", "environment", "report"])
def test_core_modules_import(name):
    importlib.import_module(f"core.{name}")


def test_defaults_yaml_sections():
    cfg = load_defaults()
    for key in ["data", "wind_resource", "energy", "losses", "economics", "environment", "report"]:
        assert key in cfg
