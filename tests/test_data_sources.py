"""Faz 1: veri çekme, CSV yükleme ve temizleme testleri."""
import datetime as dt
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core import data_sources as ds

FIXTURE = Path(__file__).parent / "fixtures" / "power_sample.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_power_json(payload):
    df = ds.parse_power_json(payload)
    assert list(df.columns) == ["ws10", "ws50", "wd10", "wd50", "t2m_c", "ps_kpa"]
    assert str(df.index.tz) == "UTC"
    assert df.index[0] == pd.Timestamp("2024-01-01 00:00", tz="UTC")
    assert np.isnan(df.loc["2024-01-01 02:00", "ws10"])
    assert df["ps_kpa"].iloc[0] == pytest.approx(100.42)


def test_build_power_url():
    url = ds.build_power_url(38.42, 27.14, "20240101", "20241231")
    assert "community=RE" in url and "time-standard=UTC" in url
    assert "parameters=WS10M,WS50M,WD10M,WD50M,T2M,PS" in url


def test_default_year_range():
    assert ds.default_year_range(dt.date(2026, 10, 16)) == (2021, 2025)


def test_fetch_uses_cache(payload, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ds, "_request_json", lambda url: calls.append(url) or payload)
    a = ds.fetch_nasa_power(38.42, 27.14, 2024, 2024, cache_dir=tmp_path)
    b = ds.fetch_nasa_power(38.42, 27.14, 2024, 2024, cache_dir=tmp_path)
    assert len(calls) == 1
    pd.testing.assert_frame_equal(a, b)


def test_fetch_invalid_years(tmp_path):
    with pytest.raises(ValueError):
        ds.fetch_nasa_power(38.42, 27.14, 2025, 2021, cache_dir=tmp_path)


def test_csv_guess_turkish_semicolon():
    csv = "Zaman;Rüzgar Hızı;Yön\n2024-01-01 00:00;5,2;180\n2024-01-01 01:00;6,1;190\n"
    df = ds.load_measurement_csv(io.StringIO(csv), height_m=30)
    assert list(df.columns) == ["ws", "wd"]
    assert df["ws"].tolist() == [5.2, 6.1]
    assert df.attrs["height_m"] == 30


def test_csv_explicit_map_and_missing_column():
    csv = "a,b\n2024-01-01 00:00,4.0\n"
    df = ds.load_measurement_csv(io.StringIO(csv), column_map={"time": "a", "ws": "b"})
    assert df["ws"].iloc[0] == 4.0
    with pytest.raises(ValueError):
        ds.load_measurement_csv(io.StringIO("foo,bar\n1,2\n"))


def test_clean_wind_data():
    idx = pd.to_datetime(
        ["2024-01-01 00:00", "2024-01-01 01:00", "2024-01-01 01:00", "2024-01-01 02:00",
         "2024-01-01 03:00", "2024-01-01 05:00"], utc=True)
    df = pd.DataFrame({"ws": [5.0, -1.0, 9.0, 60.0, np.nan, 7.0], "wd": [10, 20, 30, 400, 50, 60]}, index=idx)
    out, rep = ds.clean_wind_data(df)
    assert rep.total_records == 6
    assert rep.duplicates_removed == 1
    assert rep.out_of_range_removed == 3          # -1 m/s, 60 m/s, 400 derece
    assert rep.expected_records == 6              # 00:00-05:00 saatlik
    assert rep.missing_pct == pytest.approx(100 * (1 - 2 / 6), abs=0.01)
    assert out["ws"].notna().sum() == 2


@pytest.mark.network
def test_fetch_izmir_5_years(tmp_path):
    df = ds.fetch_nasa_power(38.42, 27.14, 2021, 2025, cache_dir=tmp_path)
    assert len(df) > 43000
