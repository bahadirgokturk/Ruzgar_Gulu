"""Örnek saha (İzmir, 38.42 K / 27.14 D) için tam raporu outputs/ornek_rapor.docx olarak üretir.

Çalıştırma:  python scripts/ornek_rapor.py
Varsayılan değerler config/defaults.yaml dosyasından okunur.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import economics as ec  # noqa: E402
from core import energy as en  # noqa: E402
from core.analysis import AnalysisInputs, run_analysis  # noqa: E402
from core.config import load_defaults  # noqa: E402
from core.data_sources import clean_wind_data, fetch_nasa_power  # noqa: E402
from core.report import ReportMeta, build_report, to_pdf  # noqa: E402

LAT, LON, Y1, Y2 = 38.42, 27.14, 2021, 2025


def main() -> None:
    cfg = load_defaults()
    df, q = clean_wind_data(fetch_nasa_power(LAT, LON, Y1, Y2))
    turbine = en.load_library_turbine(cfg["energy"]["default_turbine"]["value"],
                                      cfg["energy"]["default_hub_height"]["value"])
    inp = AnalysisInputs(
        lat=LAT, lon=LON, df=df, quality=q.as_dict(), source_label=f"NASA POWER ({Y1}-{Y2})",
        turbine=turbine, econ=ec.EconomicInputs.from_defaults(), z0=0.03, z0_name="Nadas tarlası",
        env_notes={
            "noise": "Örnek nokta İzmir kent merkezine yakındır; gerçek bir projede yerleşimlerden en az "
                     "500 m uzaklık ve gece 45 dB(A) sınırı kontrol edilmelidir.",
            "visual": "Kıyı şeridine yakın konumda türbin uzak mesafelerden görülebilir.",
        })
    result = run_analysis(inp)
    meta = ReportMeta.from_defaults("Örnek Saha: İzmir", author="Rüzgar Fizibilite Yazılımı")
    path = build_report(result, meta)
    final = path.with_name("ornek_rapor.docx")
    path.replace(final)
    pdf = to_pdf(final)
    print(f"Rapor: {final}")
    print(f"PDF:   {pdf if pdf else 'oluşturulamadı (Word veya LibreOffice gerekir)'}")


if __name__ == "__main__":
    main()
