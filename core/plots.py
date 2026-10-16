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


def power_curve_plot(curve_std: pd.DataFrame, curve_site: pd.DataFrame | None = None, title: str | None = None) -> plt.Figure:
    """Standart (ρ₀) ve saha yoğunluğuna düzeltilmiş güç eğrisi."""
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=150)
    ax.plot(curve_std["wind_speed"], curve_std["power_kw"], color=MUTED, lw=1.5, ls="--", label="Standart (ρ₀ = 1.225)")
    if curve_site is not None:
        ax.plot(curve_site["wind_speed"], curve_site["power_kw"], color=ACCENT, lw=2, label="Saha yoğunluğu")
    ax.set_xlabel("Rüzgar hızı (m/s)")
    ax.set_ylabel("Güç (kW)")
    if title:
        ax.set_title(title, fontsize=10)
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    return fig


def loss_waterfall(gross: float, loss_table: pd.DataFrame, net: float) -> plt.Figure:
    """Brüt AEP'den net AEP'ye kayıp şelalesi [MWh/yıl]."""
    labels = ["Brüt"] + loss_table["label"].tolist() + ["Net"]
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=150)
    ax.bar(0, gross, color=ACCENT)
    level = gross
    for i, lost in enumerate(loss_table["lost_mwh"], start=1):
        ax.bar(i, -lost, bottom=level, color="#a2412c")
        level -= lost
    ax.bar(len(labels) - 1, net, color=ACCENT)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("MWh/yıl")
    ax.set_ylim(net * 0.85, gross * 1.02)
    _style(ax)
    fig.tight_layout()
    return fig


def cash_flow_plot(table: pd.DataFrame, currency: str = "USD") -> plt.Figure:
    """Yıllık net nakit akışı (çubuk) ve kümülatif nakit akışı (çizgi), milyon birim."""
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=150)
    cf = table["net_cf"] / 1e6
    ax.bar(table.index, cf, color=["#a2412c" if v < 0 else BAR for v in cf])
    ax.plot(table.index, table["cum_cf"] / 1e6, color=ACCENT, lw=2, label="Kümülatif")
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_xlabel("Yıl")
    ax.set_ylabel(f"Milyon {currency}")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    return fig


def tornado_plot(sens: pd.DataFrame, metric: str = "d_npv", currency: str = "USD") -> plt.Figure:
    """En büyük ± değişimdeki NPV (veya LCOE) farkının tornado grafiği."""
    dmax = sens["delta"].abs().max()
    s = sens[sens["delta"].abs() == dmax]
    lo = s[s["delta"] < 0].set_index("label")[metric]
    hi = s[s["delta"] > 0].set_index("label")[metric]
    order = (hi - lo).abs().sort_values().index
    scale = 1e6 if metric == "d_npv" else 1.0
    fig, ax = plt.subplots(figsize=(6.4, 3.4), dpi=150)
    y = np.arange(len(order))
    ax.barh(y, lo[order] / scale, color="#a2412c", label=f"-%{dmax * 100:.0f}")
    ax.barh(y, hi[order] / scale, color=ACCENT, label=f"+%{dmax * 100:.0f}")
    ax.set_yticks(y)
    ax.set_yticklabels(order, fontsize=8)
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.set_xlabel(f"NPV değişimi (milyon {currency})" if metric == "d_npv" else f"LCOE değişimi ({currency}/MWh)")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    return fig
