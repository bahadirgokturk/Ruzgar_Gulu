"""README ekran görüntülerini üretir (Playwright + sistemdeki Microsoft Edge).

Önce uygulamayı çalıştırın: streamlit run app/streamlit_app.py
Sonra: python scripts/ekran_goruntusu.py   (geliştirme aracı; requirements.txt'te yok, pip install playwright)
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs"
TABS = {"Saha & Veri": "ekran_saha", "Rüzgar Kaynağı": "ekran_ruzgar", "Türbin & Enerji": "ekran_enerji",
        "Ekonomi": "ekran_ekonomi"}

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge")
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto("http://localhost:8501/?ornek=1")
    page.get_by_text("Kapasite faktörü").first.wait_for(timeout=60_000)
    for tab, name in TABS.items():
        page.get_by_role("tab", name=tab).click()
        page.wait_for_timeout(2500)
        page.screenshot(path=OUT / f"{name}.png")
        print(name)
    browser.close()
