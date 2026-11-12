"""Static figures for the course pages. Each function draws one figure and saves it in
musa5500/docs/figures. The notebooks call these and show the result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from pipeline.tract.io import FIGURES, PROCESSED

DPI = 120
PAYS_COLORS = {"yes": "#1a9850", "maybe": "#e0b000", "no": "#c0392b"}
GROUP_COLORS = [
    "#4c72b0",
    "#dd8452",
    "#55a868",
    "#c44e52",
    "#8172b3",
    "#937860",
    "#da8bc3",
    "#8c8c8c",
    "#ccb974",
    "#64b5cd",
]


def _save(fig: Any, name: str) -> Path:
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / name
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    return path


def tracts_gdf() -> gpd.GeoDataFrame:
    return gpd.read_file(PROCESSED / "tracts_2020.gpkg")[["GEOID", "geometry"]].to_crs(3857)


# ------------------------------------------------------------------ growth
def growth_hist(trends: pd.DataFrame) -> Any:
    fig, axes = plt.subplots(1, 4, figsize=(14, 3.4))
    titles = {"pop": "Population", "units": "Housing units", "jobs": "Jobs", "rent": "Real rent"}
    for ax, m in zip(axes, titles, strict=True):
        b, a = trends[f"{m}_growth_before"] * 100, trends[f"{m}_growth_after"] * 100
        lo, hi = np.nanpercentile(pd.concat([b, a]), [2, 98])
        bins = np.linspace(lo, hi, 40)
        ax.hist(b.dropna(), bins=bins, alpha=0.6, label="before")
        ax.hist(a.dropna(), bins=bins, alpha=0.6, label="after")
        ax.axvline(0, color="k", lw=0.6)
        ax.set_title(titles[m])
        ax.set_xlabel("% per year")
    axes[0].legend(frameon=False)
    fig.suptitle("Yearly growth by tract. ACS: 2010-14 to 2015-19 vs 2015-19 to 2020-24. Jobs: 2010-19 vs 2019-24")
    fig.tight_layout()
    _save(fig, "01_growth_hist.png")
    return fig


def trend_change_map(trends: pd.DataFrame) -> Any:
    g = tracts_gdf().merge(trends, on="GEOID")
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    for ax, m, t in zip(axes, ["jobs", "pop"], ["Jobs", "Population"], strict=True):
        g.plot(
            column=g[f"{m}_change"] * 100,
            ax=ax,
            cmap="RdBu",
            vmin=-4,
            vmax=4,
            legend=True,
            missing_kwds={"color": "#ddd"},
            legend_kwds={"shrink": 0.6, "label": "points per year"},
        )
        ax.set_title(f"{t}: growth after minus growth before")
        ax.set_axis_off()
    fig.tight_layout()
    _save(fig, "01_trend_change_map.png")
    return fig


def moe_bars(moe: pd.DataFrame) -> Any:
    p = moe.pivot(index="measure", columns="part", values="share_within_moe")[["before", "after", "change"]] * 100
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    p.plot.barh(ax=ax, color=["#9ecae1", "#4292c6", "#08519c"])
    ax.set_xlabel("% of tracts where the change is smaller than its margin of error")
    ax.set_xlim(0, 100)
    ax.set_ylabel("")
    ax.legend(frameon=False, loc="lower right")
    ax.set_title("Most tract changes are inside the ACS margin of error")
    fig.tight_layout()
    _save(fig, "01_moe.png")
    return fig


# ------------------------------------------------------------------ groups
def k_metrics(m: pd.DataFrame, k: int) -> Any:
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.2))
    axes[0].plot(m.k, m.inertia, "o-")
    axes[0].set_title("Inertia (elbow)")
    axes[1].plot(m.k, m.silhouette, "o-", label="silhouette (higher better)")
    axes[1].plot(m.k, m.davies_bouldin / 10, "s--", label="Davies-Bouldin / 10 (lower better)")
    axes[1].legend(frameon=False, fontsize=8)
    axes[1].set_title("Separation")
    axes[2].errorbar(m.k, m.gap, yerr=m.gap_s, fmt="o-")
    axes[2].set_title("Gap statistic")
    axes[3].plot(m.k, m.ari_seeds, "o-", label="across seeds")
    axes[3].plot(m.k, m.ari_bootstrap, "s--", label="80% subsamples")
    axes[3].axhline(0.8, color="grey", lw=0.6)
    axes[3].set_ylim(0, 1)
    axes[3].legend(frameon=False, fontsize=8)
    axes[3].set_title("Stability (adjusted Rand)")
    for a in axes:
        a.set_xlabel("k")
        a.axvline(k, color="k", lw=0.5, ls=":")
    fig.tight_layout()
    _save(fig, "02_k_metrics.png")
    return fig


def groups_map(trends: pd.DataFrame, k: int) -> Any:
    g = tracts_gdf().merge(trends[["GEOID", "trend_group"]], on="GEOID")
    order = [n for n in g.trend_group.value_counts().index if n != "Not enough data"] + ["Not enough data"]
    colors = dict(zip(order[:-1], GROUP_COLORS, strict=False)) | {"Not enough data": "#dddddd"}
    fig, ax = plt.subplots(figsize=(10, 6.8))
    for name in order:
        sub = g[g.trend_group == name]
        sub.plot(ax=ax, color=colors[name], linewidth=0, label=f"{name} ({len(sub)})")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 0), ncol=2, frameon=False, fontsize=8.5)
    ax.set_axis_off()
    ax.set_title(f"Trend groups (K-means, k = {k}). A description, not natural clusters")
    fig.tight_layout()
    _save(fig, "02_groups_map.png")
    return fig


# ------------------------------------------------------------------ payoff
def payoff_map(payoff: pd.DataFrame, title: str) -> Any:
    g = tracts_gdf().merge(payoff[["GEOID", "pays"]], on="GEOID")
    fig, ax = plt.subplots(figsize=(10, 6.5))
    for k, c in PAYS_COLORS.items():
        sub = g[g.pays == k]
        sub.plot(ax=ax, color=c, linewidth=0, label=f"{k} ({len(sub)})")
    if g.pays.isna().any():
        g[g.pays.isna()].plot(ax=ax, color="#cccccc", linewidth=0, label=f"no rent data ({g.pays.isna().sum()})")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 0), ncol=4, frameon=False)
    ax.set_axis_off()
    ax.set_title(title)
    fig.tight_layout()
    _save(fig, "04_payoff_map.png")
    return fig


def sensitivity_heat(sens: pd.DataFrame) -> Any:
    p = sens.pivot_table(index=["rent_basis", "rate_name"], columns="cost_level", values="share_yes")
    p = p[["low", "mid", "high"]] * 100
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    im = ax.imshow(p.values, cmap="Greens", vmin=0, vmax=65, aspect="auto")
    ax.set_xticks(range(3), ["$175", "$250", "$300"])
    ax.set_yticks(range(len(p)), [f"{b} @ {r}" for b, r in p.index], fontsize=8)
    for i in range(p.shape[0]):
        for j in range(p.shape[1]):
            ax.text(j, i, f"{p.values[i, j]:.1f}", ha="center", va="center", fontsize=8)
    ax.set_xlabel("Build cost per sq ft")
    ax.set_title("% of tracts where the unit pays (yes)")
    fig.colorbar(im, ax=ax, shrink=0.7)
    fig.tight_layout()
    _save(fig, "04_payoff_sensitivity.png")
    return fig


# ------------------------------------------------------------------ forecast
def model_compare(cv: pd.DataFrame) -> Any:
    keep = cv[cv.scheme.isin(["random_5fold", "county_blocks", "grid_40km_blocks"])]
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.6))
    for ax, col, t in zip(
        axes, ["r2_pooled", "mae"], ["R2 (higher better)", "MAE, log points (lower better)"], strict=True
    ):
        keep.pivot(index="model", columns="scheme", values=col).plot.barh(ax=ax)
        ax.set_title(t)
        ax.set_ylabel("")
        ax.legend(frameon=False, fontsize=8)
    fig.suptitle("Housing growth 2010-20: models under random and spatial block cross-validation")
    fig.tight_layout()
    _save(fig, "04_model_compare.png")
    return fig


def backtest_scatter(detail: pd.DataFrame, model: str) -> Any:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, col, t in zip(
        axes, ["last_period_rate", model], ["Last-period rate", model.replace("_", " ")], strict=True
    ):
        ax.scatter(detail[col] * 100, detail.actual * 100, s=3, alpha=0.3)
        ax.axline((0, 0), slope=1, color="k", lw=0.6, ls="--")
        ax.set_xlim(-30, 30)
        ax.set_ylim(-30, 30)
        ax.set_xlabel("Predicted change in homes, 2015-19 to 2020-24 (log %)")
        ax.set_ylabel("Actual (log %)")
        ax.set_title(t)
    fig.suptitle("Temporal backtest: trained on 2010-14 to 2015-19, scored on the next step")
    fig.tight_layout()
    _save(fig, "04_backtest.png")
    return fig


def importance_pdp(imp: pd.DataFrame, pdp: pd.DataFrame) -> Any:
    feats = list(pdp.feature.unique())
    fig, axes = plt.subplots(1, 1 + len(feats), figsize=(4 + 3 * len(feats), 3.4))
    imp.importance.iloc[::-1].plot.barh(ax=axes[0], xerr=imp.fold_sd.iloc[::-1], color="#4c72b0")
    axes[0].set_title("Permutation importance\n(drop in R2, held-out counties)")
    for ax, f in zip(axes[1:], feats, strict=True):
        s = pdp[pdp.feature == f]
        ax.plot(s.value, np.expm1(s.partial_dependence) * 100)
        ax.set_title(f"Partial dependence: {f}")
        ax.set_ylabel("Predicted 10-year growth, %")
    fig.tight_layout()
    _save(fig, "04_importance_pdp.png")
    return fig


def forecast_map(towns_out: pd.DataFrame, rule: str = "hb2186") -> Any:
    towns = gpd.read_file(PROCESSED / "towns_2020.gpkg")[["GEOID", "geometry"]]
    tw = towns.merge(towns_out[towns_out.rule == rule], left_on="GEOID", right_on="town_geoid").to_crs(3857)
    tw["per_1000"] = tw.adus_mid / tw["pop"].clip(lower=1) * 1000
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    for ax, col, t in zip(axes, ["adus_mid", "per_1000"], ["ADUs by 2031 (mid)", "Per 1,000 residents"], strict=True):
        tw.plot(
            column=col,
            ax=ax,
            cmap="YlGnBu",
            scheme="quantiles",
            k=5,
            legend=True,
            legend_kwds={
                "loc": "upper center",
                "bbox_to_anchor": (0.5, 0.02),
                "ncol": 3,
                "fontsize": 8,
                "frameon": False,
                "fmt": "{:.1f}",
            },
        )
        ax.set_title(f"{t}, {rule.upper()} scenario, by town")
        ax.set_axis_off()
    fig.tight_layout()
    _save(fig, "04_forecast_map.png")
    return fig


def migration_map(periods: pd.DataFrame) -> Any:
    c = gpd.read_file(PROCESSED / "counties_2020.gpkg")[["GEOID", "geometry"]].to_crs(3857)
    g = c.merge(periods, left_on="GEOID", right_on="county")
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    for ax, col, t in zip(axes, ["before", "after"], ["2012-2019", "2020-2023"], strict=True):
        g.plot(
            column=col,
            ax=ax,
            cmap="PuOr",
            vmin=-10,
            vmax=10,
            legend=True,
            edgecolor="white",
            linewidth=0.3,
            legend_kwds={"shrink": 0.6, "label": "net movers per 1,000 a year"},
        )
        ax.set_title(f"IRS county net migration, {t}")
        ax.set_axis_off()
    fig.tight_layout()
    _save(fig, "04_migration_map.png")
    return fig
