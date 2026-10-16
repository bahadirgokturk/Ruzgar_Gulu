"""Rüzgar enerjisi fizibilite uygulaması (Streamlit arayüzü)."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

st.set_page_config(page_title="Rüzgar Fizibilite", layout="wide")

with st.sidebar:
    st.subheader("Rüzgar Enerjisi Fizibilite")
    st.caption("EEM Rüzgar Enerjisi dersi projesi")

st.header("Proje")
tabs = st.tabs(["Saha & Veri", "Rüzgar Kaynağı", "Türbin & Enerji", "Ekonomi", "Çevre", "Rapor"])
for tab in tabs:
    with tab:
        st.info("Bu bölüm sonraki fazlarda eklenecek.")
