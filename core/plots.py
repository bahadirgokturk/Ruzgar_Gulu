"""Rapora gömülecek matplotlib grafikleri. Her fonksiyon Figure döndürür."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from core.wind_resource import histogram_with_fit

ACCENT = "#0e6b5a"
MUTED = "#9aa5a1"
BAR = "#c9d3cf"


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e4e7e5", linewidth=0.8)
    ax.set_axisbelow(True)


def weibull_histogram(ws: pd.Series, title: str | None = None) -> plt.Figure:
    """Hız histogramı ve MLE / momentler Weibull eğrileri."""
    h = histogram_with_fit(ws)
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=150)
    ax.bar(h["edges"][:-1], h["density"], width=np.diff(h["edges"]), align="edge", color=BAR, edgecolor="white")
    styles = {"MLE": dict(color=ACCENT, lw=2), "Momentler": dict(color=MUTED, lw=1.5, ls="--")}
    for name, (p, y) in h["fits"].items():
        ax.plot(h["x"], y, label=f"{name}: k={p.k:.2f}, c={p.c:.2f} m/s", **styles[name])
    ax.set_xlabel("Rüzgar hızı (m/s)")
    ax.set_ylabel("Olasılık yoğunluğu")
    if title:
        ax.set_title(title, fontsize=10)
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    return fig


def wind_rose_plot(rose: pd.DataFrame) -> plt.Figure:
    """Sektör frekanslarının polar çubuk grafiği (K yukarıda, saat yönünde)."""
    n = len(rose)
    fig = plt.figure(figsize=(4.4, 4.4), dpi=150)
    ax = fig.add_subplot(projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.bar(np.deg2rad(rose["center_deg"]), rose["freq_pct"], width=2 * np.pi / n * 0.9, color=ACCENT, alpha=0.85)
    ax.set_xticks(np.deg2rad(rose["center_deg"]))
    ax.set_xticklabels(rose["sector"], fontsize=7)
    ax.yaxis.set_major_formatter(lambda v, _: f"%{v:.0f}")
    ax.tick_params(axis="y", labelsize=7)
    fig.tight_layout()
    return fig
