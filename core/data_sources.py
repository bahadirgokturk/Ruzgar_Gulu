"""Veri çekme (NASA POWER) ve CSV yükleme, veri temizleme.

Ortak veri şeması (datetime index, UTC):
    ws10, ws50 : rüzgar hızı [m/s] (CSV için tek yükseklikte ``ws``)
    wd10, wd50 : rüzgar yönü [derece] (CSV için ``wd``)
    t2m_c      : 2 m sıcaklık [°C]
    ps_kpa     : yüzey basıncı [kPa]
"""
from __future__ import annotations

import datetime as dt
import io
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from core.config import load_defaults

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"

# NASA POWER parametre adı -> iç sütun adı
POWER_COLUMNS = {
    "WS10M": "ws10",
    "WS50M": "ws50",
    "WD10M": "wd10",
    "WD50M": "wd50",
    "T2M": "t2m_c",
    "PS": "ps_kpa",
}

# CSV sütun adı tahmini için anahtar kelimeler (küçük harf, Türkçe karakter sadeleştirilmiş)
CSV_ALIASES = {
    "time": ["time", "timestamp", "datetime", "date", "zaman", "tarih"],
    "ws": ["ws", "speed", "wind_speed", "windspeed", "hiz", "ruzgar_hizi", "v"],
    "wd": ["wd", "dir", "direction", "wind_dir", "yon", "ruzgar_yonu"],
    "t2m_c": ["t", "temp", "temperature", "sicaklik", "t2m"],
    "ps_kpa": ["p", "pressure", "basinc", "ps"],
}


def _cfg(key: str) -> Any:
    return load_defaults()["data"][key]["value"]


def default_year_range(today: dt.date | None = None) -> tuple[int, int]:
    """Son tam N yılı (başlangıç, bitiş) olarak döndürür. N defaults.yaml'dan gelir."""
    today = today or dt.date.today()
    end = today.year - 1
    return end - _cfg("default_years") + 1, end


def build_power_url(lat: float, lon: float, start: str, end: str) -> str:
    """NASA POWER saatlik nokta sorgusu adresini kurar.

    start, end: 'YYYYMMDD' biçiminde tarih.
    """
    params = ",".join(_cfg("power_parameters"))
    return (
        f"{_cfg('power_base_url')}?parameters={params}&community={_cfg('power_community')}"
        f"&longitude={lon}&latitude={lat}&start={start}&end={end}"
        f"&format=JSON&time-standard={_cfg('power_time_standard')}"
    )


def parse_power_json(payload: dict) -> pd.DataFrame:
    """NASA POWER JSON yanıtını DataFrame'e çevirir.

    Zaman anahtarları 'YYYYMMDDHH' (UTC). Eksik veri değeri (-999) NaN yapılır.
    Birimler değiştirilmez: hız m/s, yön derece, T2M °C, PS kPa.
    """
    raw = payload["properties"]["parameter"]
    fill = payload.get("header", {}).get("fill_value", _cfg("power_fill_value"))
    df = pd.DataFrame({POWER_COLUMNS.get(k, k): pd.Series(v) for k, v in raw.items()})
    df.index = pd.to_datetime(df.index, format="%Y%m%d%H", utc=True)
    df.index.name = "time"
    df = df.sort_index().astype(float).replace(fill, np.nan)
    df.attrs["source"] = "NASA POWER"
    return df


def _cache_path(cache_dir: Path, lat: float, lon: float, year: int) -> Path:
    return cache_dir / f"power_{lat:.4f}_{lon:.4f}_{year}.parquet"


def _request_json(url: str) -> dict:
    """URL'yi tekrar denemeli olarak çeker."""
    retries, timeout = _cfg("request_retries"), _cfg("request_timeout")
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == retries:
                raise
            time.sleep(2 * attempt)
    raise RuntimeError("unreachable")


def fetch_nasa_power(
    lat: float,
    lon: float,
    start_year: int | None = None,
    end_year: int | None = None,
    cache_dir: Path = CACHE_DIR,
) -> pd.DataFrame:
    """NASA POWER saatlik verisini yıl yıl çeker ve önbellekler.

    Her yıl ayrı bir parquet dosyasına yazılır; dosya varsa API'ye gidilmez.
    Yıl verilmezse son tam yıllar kullanılır (default_year_range).
    """
    if start_year is None or end_year is None:
        start_year, end_year = default_year_range()
    if start_year > end_year:
        raise ValueError("Başlangıç yılı bitiş yılından büyük olamaz.")
    cache_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for year in range(start_year, end_year + 1):
        path = _cache_path(cache_dir, lat, lon, year)
        if path.exists():
            frames.append(pd.read_parquet(path))
            continue
        df = parse_power_json(_request_json(build_power_url(lat, lon, f"{year}0101", f"{year}1231")))
        df.to_parquet(path)
        frames.append(df)
    out = pd.concat(frames).sort_index()
    out.attrs.update(source="NASA POWER", lat=lat, lon=lon, heights_m=[10, 50])
    return out


def _normalize(name: str) -> str:
    table = str.maketrans("çğıöşüÇĞİÖŞÜ ", "cgiosuCGIOSU_")
    return name.strip().translate(table).lower()


def guess_column_map(columns: list[str]) -> dict[str, str]:
    """CSV sütun adlarından şema eşleştirmesini tahmin eder: {iç_ad: csv_sütunu}."""
    found: dict[str, str] = {}
    norm = {_normalize(c): c for c in columns}
    for target, aliases in CSV_ALIASES.items():
        for alias in aliases:
            hit = next((orig for n, orig in norm.items() if n == alias or n.startswith(alias + "_")), None)
            if hit and hit not in found.values():
                found[target] = hit
                break
    return found


def load_measurement_csv(
    file: str | Path | io.IOBase,
    column_map: dict[str, str] | None = None,
    height_m: float | None = None,
) -> pd.DataFrame:
    """Kullanıcı ölçüm CSV'sini ortak şemaya çevirir.

    Ayraç (',' ';' tab) otomatik algılanır; ondalık virgül desteklenir.
    column_map: {iç_ad: csv_sütunu}; verilmezse guess_column_map ile tahmin edilir.
    Zorunlu: time, ws. Opsiyonel: wd, t2m_c, ps_kpa. Ölçüm yüksekliği df.attrs['height_m'].
    """
    df = pd.read_csv(file, sep=None, engine="python")
    cmap = column_map or guess_column_map(list(df.columns))
    missing = {"time", "ws"} - cmap.keys()
    if missing:
        raise ValueError(f"CSV'de zorunlu sütun bulunamadı: {', '.join(sorted(missing))}")
    out = pd.DataFrame(index=pd.DatetimeIndex(pd.to_datetime(df[cmap["time"]], utc=True), name="time"))
    for key in ("ws", "wd", "t2m_c", "ps_kpa"):
        if key in cmap:
            col = df[cmap[key]]
            if not pd.api.types.is_numeric_dtype(col):
                col = col.astype(str).str.replace(",", ".", regex=False)
            out[key] = pd.to_numeric(col, errors="coerce").to_numpy()
    out = out.sort_index()
    out.attrs.update(source="Ölçüm CSV", height_m=height_m)
    return out


@dataclass
class QualityReport:
    """Veri kalite özeti."""

    total_records: int
    expected_records: int
    missing_pct: float          # beklenen kayda göre geçerli hızı olmayan oran [%]
    duplicates_removed: int
    out_of_range_removed: int   # fiziksel olmayan hız/yön sayısı
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    coverage_days: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def clean_wind_data(
    df: pd.DataFrame,
    max_speed: float | None = None,
    min_speed: float | None = None,
) -> tuple[pd.DataFrame, QualityReport]:
    """Tekrar eden zaman damgalarını, fiziksel olmayan hız ve yönleri temizler.

    - Tekrar eden zaman damgalarında ilk kayıt tutulur.
    - Hız < min_speed veya > max_speed [m/s] olan değerler NaN yapılır.
    - Yön 0-360 derece dışındaysa NaN yapılır.
    Eksik veri oranı = 1 - (geçerli hızlı kayıt / tam zaman aralığındaki beklenen kayıt).
    """
    max_speed = _cfg("max_wind_speed") if max_speed is None else max_speed
    min_speed = _cfg("min_wind_speed") if min_speed is None else min_speed
    total = len(df)
    dup = df.index.duplicated(keep="first")
    out = df[~dup].sort_index().copy()
    out.attrs = dict(df.attrs)

    bad = 0
    ws_cols = [c for c in out.columns if c.startswith("ws")]
    for c in ws_cols:
        mask = (out[c] < min_speed) | (out[c] > max_speed)
        bad += int(mask.sum())
        out.loc[mask, c] = np.nan
    for c in (c for c in out.columns if c.startswith("wd")):
        mask = (out[c] < 0) | (out[c] > 360)
        bad += int(mask.sum())
        out.loc[mask, c] = np.nan

    if len(out) >= 2:
        step = out.index.to_series().diff().median()
        expected = int((out.index[-1] - out.index[0]) / step) + 1
    else:
        expected = len(out)
    valid = int(out[ws_cols].notna().all(axis=1).sum()) if ws_cols else 0
    missing_pct = 100.0 * (1 - valid / expected) if expected else 100.0

    report = QualityReport(
        total_records=total,
        expected_records=expected,
        missing_pct=round(missing_pct, 2),
        duplicates_removed=int(dup.sum()),
        out_of_range_removed=bad,
        start=out.index[0] if len(out) else None,
        end=out.index[-1] if len(out) else None,
        coverage_days=round((out.index[-1] - out.index[0]).total_seconds() / 86400, 2) if len(out) >= 2 else 0.0,
    )
    return out, report
