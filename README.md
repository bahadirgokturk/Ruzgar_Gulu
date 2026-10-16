# Rüzgar Enerjisi Fizibilite Raporu Yazılımı

Seçilen bir konumda rüzgar santralinin (tek türbin veya küçük çiftlik) teknik ve ekonomik fizibilitesini hesaplayan ve Türkçe fizibilite raporu (Word/PDF) üreten Streamlit uygulaması. EEM son sınıf Rüzgar Enerjisi dersi projesi.

## Kurulum (Windows, Python 3.11)

Sanal ortamı OneDrive dışında tutmak önerilir (senkronizasyon binlerce dosyayla yavaşlar):

```bash
py -3.11 -m venv %USERPROFILE%\venvs\ruzgar-fizibilite
%USERPROFILE%\venvs\ruzgar-fizibilite\Scripts\activate
pip install -r requirements.txt
```

## Çalıştırma

```bash
streamlit run app/streamlit_app.py
pytest
```

## Klasör yapısı

- `core/` hesaplama modülleri (Streamlit'ten bağımsız saf fonksiyonlar)
- `app/` Streamlit arayüzü
- `config/defaults.yaml` tüm teknik ve ekonomik varsayımlar
- `data/cache/` API önbelleği, `data/turbines/` özel güç eğrisi CSV'leri
- `outputs/` üretilen raporlar
- `prototip/` arayüz tasarım prototipi (statik HTML)

## PDF çıktısı

PDF dönüşümü `docx2pdf` ile yapılır ve bilgisayarda Microsoft Word kurulu olmasını gerektirir. Word yoksa rapor yalnızca .docx olarak üretilir.
