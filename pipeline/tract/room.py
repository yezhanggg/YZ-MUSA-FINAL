"""Physical room for a backyard unit in every Pennsylvania tract.

Measured in two cities, modelled everywhere else.

Target (measured, Philadelphia and Pittsburgh): share of 1 to 4 unit lots where a 600 sq ft
detached unit fits under the state-reform setbacks (4 ft side and rear, the loosest any
scenario allows). That is physical room, not legality. Source: lots_tract_v2.csv.

Features that exist for every tract:
    log housing units per km2 of land (ACS 2020-24, TIGER area)
    shares of homes in 1-unit detached, 1-unit attached and 2 to 4 unit buildings (ACS B25024)
    developed share of land (NLCD 2019)
    developed m2 per small-building lot (a rough lot size proxy)

Models: lot-weighted mean (baseline), the retired pilot rate by area type, ridge regression,
and small gradient boosting. Validation: hold out one city and predict the other, and 2 km
block cross-validation within the two cities. The cross-city error is the honest error for
the rest of the state, and it sets the low to high range.

Small-building lots outside the cities = 1-detached + 1-attached + 2-unit / 2 + 3-4 unit / 3.5
(ACS B25024 buildings, not parcels). Checked against the real lot counts in the two cities.

Run:  python -m pipeline.tract.room
Saves data/processed/room_tract.csv and <data root>/processed/5500/room_*.{csv,json}.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from pipeline.tract.acs_moe import BASE, FOLDER, _get
from pipeline.tract.forecast import grid_blocks
from pipeline.tract.io import PROCESSED, out_dir, write_json

if TYPE_CHECKING:
    from matplotlib.figure import Figure

TARGET = "share_fit600_state_reform"
FEATURES = ["log_density", "share_1det", "share_1att", "share_2to4", "dev_share", "log_dev_m2_per_lot"]
MIN_LOTS = 30
BLOCK_KM = 2
ALPHA = 0.1
OUTSIDE_FACTOR = 2.0
CITY_COUNTY = {"philadelphia": "42101", "pittsburgh": "42003"}
OLD_RATE = {"urban": 0.719, "suburban": 0.966, "rural": 0.800}  # retired pilot rates (lots_tract.csv)


def b25024() -> pd.DataFrame:
    """Units in structure, ACS 2020-24, from the Census table file (no key needed)."""
    path = _get(f"{BASE}/2024/table-based-SF/data/5YRData/acsdt5y2024-b25024.dat", FOLDER / "acsdt5y2024-b25024.dat")
    cols = {
        f"B25024_E{i:03d}": n for i, n in [(1, "units_all"), (2, "u_1det"), (3, "u_1att"), (4, "u_2"), (5, "u_3to4")]
    }
    df = pd.read_csv(path, sep="|", dtype=str, usecols=["GEO_ID", *cols])
    df = df[df.GEO_ID.str.startswith("1400000US42")]
    out = pd.DataFrame({"GEOID": df.GEO_ID.str[9:].values})
    for c, n in cols.items():
        out[n] = pd.to_numeric(df[c], errors="coerce").values
    return out


def lots_proxy(u: pd.DataFrame) -> pd.Series:
    """Small-building lots from ACS units: 1 per 1-unit home, 1 per 2 units, 1 per 3.5 units in 3-4 unit buildings."""
    return u.u_1det + u.u_1att + u.u_2 / 2 + u.u_3to4 / 3.5


def tract_features(units: pd.DataFrame, access: pd.DataFrame, area_km2: pd.Series) -> pd.DataFrame:
    f = units[["GEOID"]].copy()
    tot = units.units_all.where(units.units_all > 0)
    area = units.GEOID.map(area_km2)
    f["lots_proxy"] = lots_proxy(units)
    f["log_density"] = np.log1p(units.units_all / area)
    f["share_1det"] = units.u_1det / tot
    f["share_1att"] = units.u_1att / tot
    f["share_2to4"] = (units.u_2 + units.u_3to4) / tot
    dev = units.GEOID.map(access.set_index("GEOID").dev_2019)
    f["dev_share"] = dev
    f["log_dev_m2_per_lot"] = np.log1p(dev * area * 1e6 / f.lots_proxy.where(f.lots_proxy > 0))
    return f


def models() -> dict[str, object]:
    return {
        "ridge": make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-3, 3, 13))),
        "gradient_boosting": HistGradientBoostingRegressor(
            max_iter=200, learning_rate=0.05, max_depth=3, min_samples_leaf=15, random_state=0
        ),
    }


def _score(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> dict[str, float]:
    p = np.clip(p, 0, 1)
    return {
        "r2": float(r2_score(y, p)),
        "mae": float(mean_absolute_error(y, p)),
        "mae_lot_weighted": float(np.average(np.abs(y - p), weights=w)),
        "bias": float(np.mean(p - y)),
        "pooled_share_true": float(np.average(y, weights=w)),
        "pooled_share_pred": float(np.average(p, weights=w)),
    }


def baseline_predictions(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, np.ndarray]:
    mean = np.average(train[TARGET], weights=train.lots)
    return {"lot_weighted_mean": np.full(len(test), mean), "old_pilot_rate": test.old_rate.to_numpy()}


def cross_city(d: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train on one city, predict the other. Returns scores and the out-of-city predictions."""
    rows, preds = [], []
    for test_city in CITY_COUNTY:
        tr, te = d[d.city != test_city], d[d.city == test_city]
        p = baseline_predictions(tr, te)
        for name, m in models().items():
            p[name] = clone(m).fit(tr[FEATURES], tr[TARGET], **_w(m, tr)).predict(te[FEATURES])
        for name, v in p.items():
            rows.append({"test_city": test_city, "model": name, **_score(te[TARGET].to_numpy(), v, te.lots.to_numpy())})
        preds.append(pd.DataFrame({"GEOID": te.GEOID.values, "city": test_city, "actual": te[TARGET].values} | p))
    return pd.DataFrame(rows), pd.concat(preds, ignore_index=True)


def block_cv(d: pd.DataFrame, folds: int = 5) -> pd.DataFrame:
    """2 km block cross-validation on both cities pooled. Blocks never straddle train and test."""
    groups = grid_blocks(d.x, d.y, BLOCK_KM)
    out = {k: np.full(len(d), np.nan) for k in ["lot_weighted_mean", "old_pilot_rate", *models()]}
    for tr, te in GroupKFold(folds).split(d, d[TARGET], groups):
        a, b = d.iloc[tr], d.iloc[te]
        for name, v in baseline_predictions(a, b).items():
            out[name][te] = v
        for name, m in models().items():
            out[name][te] = clone(m).fit(a[FEATURES], a[TARGET], **_w(m, a)).predict(b[FEATURES])
    return pd.DataFrame([{"model": k, **_score(d[TARGET].to_numpy(), v, d.lots.to_numpy())} for k, v in out.items()])


def _w(model: Any, frame: pd.DataFrame) -> dict[str, object]:
    """Weight tracts by the square root of their lot count (big tracts count more, but not all)."""
    w = np.sqrt(frame.lots.values)
    if hasattr(model, "steps"):
        return {f"{model.steps[-1][0]}__sample_weight": w}
    return {"sample_weight": w}


def halfwidth(resid: np.ndarray, alpha: float = ALPHA) -> float:
    r = np.sort(np.abs(resid[~np.isnan(resid)]))
    k = min(len(r) - 1, int(np.ceil((len(r) + 1) * (1 - alpha))) - 1)
    return float(r[k])


def outside_range(f: pd.DataFrame, train: pd.DataFrame) -> pd.Series:
    """True when any feature is outside the 1st to 99th percentile of the training tracts."""
    lo, hi = train[FEATURES].quantile(0.01), train[FEATURES].quantile(0.99)
    return ((f[FEATURES] < lo) | (f[FEATURES] > hi)).any(axis=1)


def load_frame() -> pd.DataFrame:
    tracts = gpd.read_file(PROCESSED / "tracts_2020.gpkg").to_crs(5070)
    area = pd.Series(tracts.area.values / 1e6, index=tracts.GEOID)
    access = pd.read_csv(PROCESSED / "access_tract.csv", dtype={"GEOID": str})
    f = tract_features(b25024(), access, area)
    f = f.merge(
        pd.DataFrame({"GEOID": tracts.GEOID, "x": tracts.centroid.x / 1000, "y": tracts.centroid.y / 1000}), on="GEOID"
    )
    old = pd.read_csv(PROCESSED / "lots_tract.csv", dtype={"GEOID": str})
    f = f.merge(old[["GEOID", "lots_total", "lots_fit", "stratum"]], on="GEOID", how="left")
    f["old_rate"] = f.stratum.map(OLD_RATE)
    lots = pd.read_csv(PROCESSED / "lots_tract_v2.csv", dtype={"tract": str}).rename(columns={"tract": "GEOID"})
    f = f.merge(lots[["GEOID", "lots", "n_fit600_state_reform", TARGET]], on="GEOID", how="left")
    f["city"] = np.where(
        f.lots.notna() & f.GEOID.str.startswith("42101"),
        "philadelphia",
        np.where(f.lots.notna() & f.GEOID.str.startswith("42003"), "pittsburgh", np.array(None, dtype=object)),
    )
    return f


def run(save: bool = True) -> dict[str, Any]:
    f = load_frame()
    train = f[f.city.notna() & (f.lots >= MIN_LOTS)].dropna(subset=FEATURES).reset_index(drop=True)
    cc, cc_pred = cross_city(train)
    bcv = block_cv(train)
    model_name = "ridge"
    model = clone(models()[model_name]).fit(train[FEATURES], train[TARGET], **_w(models()[model_name], train))
    resid = (cc_pred.actual - np.clip(cc_pred[model_name], 0, 1)).values
    q = halfwidth(resid)

    ok = f.dropna(subset=FEATURES)
    f["share_mid"] = np.nan
    f.loc[ok.index, "share_mid"] = np.clip(model.predict(ok[FEATURES]), 0, 1)
    f["outside_training_range"] = outside_range(f, train) | f[FEATURES].isna().any(axis=1)
    # Outside the training range the cross-city error says too little, so the band is doubled (a judgment call)
    width = np.where(f.outside_training_range, OUTSIDE_FACTOR * q, q)
    f["share_low"] = (f.share_mid - width).clip(0, 1)
    f["share_high"] = (f.share_mid + width).clip(0, 1)
    measured = f.city.notna()
    f["source"] = np.where(measured, "measured", "modelled")
    f["lots_est"] = np.where(measured, f.lots, f.lots_proxy).round(0)
    for k in ("mid", "low", "high"):
        f[f"lots_room_{k}"] = np.where(measured, f.n_fit600_state_reform, f[f"share_{k}"] * f.lots_proxy).round(0)
        f[f"share_room_{k}"] = np.where(measured, f[TARGET], f[f"share_{k}"]).round(4)
    f["lots_room_old_pilot"] = f.lots_fit

    cal = train.assign(ratio=train.lots_proxy / train.lots)
    calib = {
        c: {
            "tracts": int((cal.city == c).sum()),
            "proxy_sum": float(cal[cal.city == c].lots_proxy.sum()),
            "lots_sum": float(cal[cal.city == c].lots.sum()),
            "corr": float(cal[cal.city == c][["lots_proxy", "lots"]].corr().to_numpy()[0, 1]),
            "median_ratio": float(cal[cal.city == c].ratio.median()),
        }
        for c in CITY_COUNTY
    }
    mod = f[f.source == "modelled"]
    summary = {
        "target": "share of 1 to 4 unit lots where a 600 sq ft detached unit fits (state-reform setbacks)",
        "training_tracts": {c: int((train.city == c).sum()) for c in CITY_COUNTY},
        "model": model_name,
        "coefficients_standardized": dict(zip(FEATURES, [float(v) for v in model.steps[-1][1].coef_], strict=True)),
        "halfwidth_90": q,
        "halfwidth_outside_training_range": OUTSIDE_FACTOR * q,
        "lots_proxy_check": calib,
        "statewide": {
            "tracts": int(len(f)),
            "measured_tracts": int(measured.sum()),
            "modelled_tracts": int(len(mod)),
            "modelled_outside_training_range": int(mod.outside_training_range.sum()),
            "lots_est": float(f.lots_est.sum()),
            "lots_room_low": float(f.lots_room_low.sum()),
            "lots_room_mid": float(f.lots_room_mid.sum()),
            "lots_room_high": float(f.lots_room_high.sum()),
            "lots_room_measured": float(f.loc[measured, "lots_room_mid"].sum()),
            "lots_room_old_pilot": float(f.lots_room_old_pilot.sum()),
            "share_room_mid_modelled": float(mod.lots_room_mid.sum() / mod.lots_proxy.sum()),
            "modelled_clipped_at_1": int((mod.share_mid >= 0.999).sum()),
            "by_old_stratum": {
                k: {
                    "tracts": int(len(g)),
                    "share_low": float(g.lots_room_low.sum() / g.lots_proxy.sum()),
                    "share_mid": float(g.lots_room_mid.sum() / g.lots_proxy.sum()),
                    "share_high": float(g.lots_room_high.sum() / g.lots_proxy.sum()),
                    "outside_training_range": int(g.outside_training_range.sum()),
                }
                for k, g in mod.groupby("stratum")
            },
        },
    }
    keep = [
        "GEOID",
        "source",
        "outside_training_range",
        "lots_est",
        "share_room_low",
        "share_room_mid",
        "share_room_high",
        "lots_room_low",
        "lots_room_mid",
        "lots_room_high",
        "lots_room_old_pilot",
        "stratum",
        *FEATURES,
    ]
    out = {
        "tracts": f[keep],
        "cross_city": cc,
        "cross_city_pred": cc_pred,
        "block_cv": bcv,
        "summary": summary,
        "train": train,
    }
    if save:
        f[keep].round(4).to_csv(PROCESSED / "room_tract.csv", index=False)
        cc.to_csv(out_dir() / "room_cross_city.csv", index=False)
        bcv.to_csv(out_dir() / "room_block_cv.csv", index=False)
        write_json(summary, out_dir() / "room_summary.json")
    return out


def figure(cc_pred: pd.DataFrame, tracts: pd.DataFrame) -> Figure:
    """Cross-city predictions vs measured shares, and the statewide modelled shares by area type."""
    import matplotlib.pyplot as plt

    from pipeline.tract.plots import _save

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for city, g in cc_pred.groupby("city"):
        axes[0].scatter(g.actual, np.clip(g.ridge, 0, 1), s=8, alpha=0.5, label=f"{city} (trained on the other city)")
    axes[0].plot([0, 1], [0, 1], "k--", lw=0.6)
    axes[0].set_xlabel("Measured share of lots with room for 600 sq ft")
    axes[0].set_ylabel("Predicted (ridge)")
    axes[0].legend(frameon=False, fontsize=8)
    axes[0].set_title("Hold out one city, predict it")
    mod = tracts[tracts.source == "modelled"]
    for flag, g in mod.groupby("outside_training_range"):
        lbl = "outside the two cities' range" if flag else "inside the range"
        axes[1].hist(g.share_room_mid, bins=30, alpha=0.6, label=f"{lbl} ({len(g)})")
    axes[1].set_xlabel("Modelled share of lots with room (mid)")
    axes[1].set_ylabel("Tracts")
    axes[1].legend(frameon=False, fontsize=8)
    axes[1].set_title("Tracts outside the two cities")
    fig.tight_layout()
    _save(fig, "05_room_model.png")
    return fig


def main() -> None:
    argparse.ArgumentParser(description="Physical room model for every PA tract").parse_args()
    r = run()
    figure(r["cross_city_pred"], r["tracts"])
    pd.set_option("display.width", 200)
    print(r["cross_city"].round(3).to_string(index=False))
    print(r["block_cv"].round(3).to_string(index=False))
    import json

    print(json.dumps(r["summary"], indent=1))


if __name__ == "__main__":
    main()
