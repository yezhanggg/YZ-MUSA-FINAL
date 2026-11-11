"""Housing growth model and ADUs by 2031.

Part 1. Where did housing grow? (the model)
    Target: log(decennial homes 2020 / decennial homes 2010) per 2020 tract (crosswalked).
    Tracts with under 100 homes in 2010 are left out.
    Features: 2010 values only (homes, density, LODES jobs and workers, NLCD developed share,
    land area, location). Optional: county net migration (IRS) just after 2010.
    Models: state median (baseline), ridge regression, random forest, gradient boosting.
    Validation: spatial cross-validation with whole counties held out, and with 40 km grid
    blocks held out. Random 5-fold CV is shown only to show how much it flatters.

Part 2. Temporal backtest
    Train on 2010-14 -> 2015-19 ACS housing growth (features at 2010-14), predict
    2015-19 -> 2020-24 (features at 2015-19), and score against what happened.
    Baselines: last-period rate (each tract keeps its own earlier growth) and the earlier median.

Part 3. Intervals, importance, partial dependence
    Split-conformal intervals from county-held-out residuals, with coverage checked fold by fold.
    Permutation importance on held-out counties. Partial dependence for the top 4 features.

Part 4. ADUs by 2031
    ADUs = people x permit rate x payoff weight x lots index x demand x town rule x 5 years,
    capped at lots with room. Rules: today (shared/legal_status.csv), HB 2186 (every town),
    SB 1346 (every town except Philadelphia and Pittsburgh, which the MPC does not reach).
    This is scenario arithmetic, not a fitted ADU model: Pennsylvania has no ADU permit series
    to fit or check it against.

Run:  python -m pipeline.tract.forecast
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.inspection import partial_dependence, permutation_importance
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from pipeline.tract import migration
from pipeline.tract.io import LEGAL_STATUS, PROCESSED, RAW5500, lmh, out_dir, table, value, write_json

SEED = 0
FOLDS = 5
GRID_KM = 40
MIN_UNITS = 100
ALPHA = 0.1   # 90 percent intervals
PHILADELPHIA, PITTSBURGH = "4210160000", "4200361000"
RULES = ("current", "hb2186", "sb1346")


# ------------------------------------------------------------------ features
@dataclass(frozen=True)
class Base:
    """Which columns describe a tract at a base year."""

    units: str
    jobs: int
    dev: int
    acs: int


BASES = {
    2010: Base("dec_units_2010", 2010, 2010, 2014),
    2014: Base("housing_units_2014", 2014, 2010, 2014),
    2019: Base("housing_units_2019", 2019, 2019, 2019),
    2020: Base("dec_units_2020", 2019, 2019, 2024),
}
CORE = ["log_units", "units_per_km2", "log_jobs", "log_workers", "jobs_per_unit", "dev_share", "devhi_share",
        "log_area", "x", "y"]
ACS_FEATS = ["renter_share", "sfd_share", "vacancy", "median_rent", "median_value", "median_income"]


def features(d: pd.DataFrame, base: int, acs: bool = False) -> pd.DataFrame:
    """Predictors at a base year. `d` holds the tract panel plus access, area and centroid columns."""
    b = BASES[base]
    units = d[b.units]
    f = pd.DataFrame(index=d.index)
    f["log_units"] = np.log1p(units)
    f["units_per_km2"] = units / d.area_km2
    f["log_jobs"] = np.log1p(d[f"jobs_here_{b.jobs}"])
    f["log_workers"] = np.log1p(d[f"workers_living_here_{b.jobs}"])
    f["jobs_per_unit"] = d[f"jobs_here_{b.jobs}"] / units.clip(lower=1)
    f["dev_share"] = d[f"dev_{b.dev}"]
    f["devhi_share"] = d[f"devhi_{b.dev}"]
    f["log_area"] = np.log(d.area_km2)
    f["x"], f["y"] = d.x, d.y
    if acs:
        a = b.acs
        hu = d[f"housing_units_{a}"].clip(lower=1)
        f["renter_share"] = d[f"renter_units_{a}"] / d[f"occupied_units_{a}"].clip(lower=1)
        f["sfd_share"] = d[f"single_family_detached_{a}"] / hu
        f["vacancy"] = d[f"vacant_units_{a}"] / hu
        f["median_rent"] = d[f"median_rent_{a}"]
        f["median_value"] = d[f"median_value_{a}"]
        f["median_income"] = d[f"median_income_{a}"]
    return f.replace([np.inf, -np.inf], np.nan)


def fill(f: pd.DataFrame, county: pd.Series, ref: pd.DataFrame | None = None) -> pd.DataFrame:
    """Fill blanks with the county median, then the median of `ref` (default: f itself)."""
    g = f.groupby(county.values).transform(lambda s: s.fillna(s.median()))
    g.index = f.index
    return g.fillna((ref if ref is not None else f).median())


def load_frame() -> pd.DataFrame:
    """Tract panel with access shares, area (km2) and centroid (km, EPSG:5070)."""
    panel = pd.read_csv(PROCESSED / "tract_panel.csv", dtype={"GEOID": str, "county": str})
    access = pd.read_csv(PROCESSED / "access_tract.csv", dtype={"GEOID": str})
    tg = gpd.read_file(PROCESSED / "tracts_2020.gpkg").to_crs(5070)
    geo = pd.DataFrame({"GEOID": tg.GEOID, "area_km2": tg.area / 1e6,
                        "x": tg.centroid.x / 1000, "y": tg.centroid.y / 1000})
    acc = access[["GEOID", "dev_2010", "devhi_2010", "dev_2019", "devhi_2019"]]
    return panel.merge(acc, on="GEOID", how="left").merge(geo, on="GEOID")


def grid_blocks(x_km: pd.Series, y_km: pd.Series, size_km: float = GRID_KM) -> pd.Series:
    """Square grid cell id for each point. Used as the group in block cross-validation."""
    return (np.floor(x_km / size_km).astype(int).astype(str) + "_" + np.floor(y_km / size_km).astype(int).astype(str))


# ------------------------------------------------------------------ models
def models() -> dict[str, object]:
    return {
        "ridge": make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-3, 3, 13))),
        "random_forest": RandomForestRegressor(n_estimators=400, min_samples_leaf=5, n_jobs=-1, random_state=SEED),
        # Absolute-error loss: a few crosswalk artifacts have log changes past -2, and squared loss chases them.
        "gradient_boosting": HistGradientBoostingRegressor(loss="absolute_error", max_iter=300, learning_rate=0.05,
                                                           min_samples_leaf=20, random_state=SEED),
    }


def oof_predict(model, X: pd.DataFrame, y: pd.Series, groups: pd.Series | None, folds: int = FOLDS) -> np.ndarray:
    """Out-of-fold predictions. Group folds when groups are given, else shuffled K-fold."""
    pred = np.full(len(y), np.nan)
    split = (GroupKFold(folds).split(X, y, groups) if groups is not None
             else KFold(folds, shuffle=True, random_state=SEED).split(X, y))
    for tr, te in split:
        m = clone(model).fit(X.iloc[tr], y.iloc[tr])
        pred[te] = m.predict(X.iloc[te])
    return pred


def fold_scores(y: pd.Series, pred: np.ndarray, groups: pd.Series | None, folds: int = FOLDS) -> dict[str, float]:
    """Pooled R2 and MAE, plus the mean of per-fold R2."""
    out = {"r2_pooled": float(r2_score(y, pred)), "mae": float(mean_absolute_error(y, pred))}
    if groups is not None:
        r2s = [r2_score(y.iloc[te], pred[te]) for _, te in GroupKFold(folds).split(y, y, groups)]
        out["r2_fold_mean"] = float(np.mean(r2s))
    return out


def compare(X: pd.DataFrame, y: pd.Series, schemes: dict[str, pd.Series | None]) -> tuple[pd.DataFrame, dict]:
    """Every model under every CV scheme. Baseline = training-fold median."""
    rows, preds = [], {}
    for scheme, groups in schemes.items():
        base = np.full(len(y), np.nan)
        split = (GroupKFold(FOLDS).split(X, y, groups) if groups is not None
                 else KFold(FOLDS, shuffle=True, random_state=SEED).split(X, y))
        for tr, te in split:
            base[te] = y.iloc[tr].median()
        rows.append({"scheme": scheme, "model": "median_baseline", **fold_scores(y, base, groups)})
        for name, m in models().items():
            p = oof_predict(m, X, y, groups)
            preds[(scheme, name)] = p
            rows.append({"scheme": scheme, "model": name, **fold_scores(y, p, groups)})
    return pd.DataFrame(rows), preds


# ------------------------------------------------------------------ intervals
def conformal_halfwidth(residuals: np.ndarray, alpha: float = ALPHA) -> float:
    """Split-conformal half-width: the ceil((n+1)(1-alpha))/n quantile of absolute residuals."""
    r = np.sort(np.abs(residuals[~np.isnan(residuals)]))
    n = len(r)
    k = min(n - 1, int(np.ceil((n + 1) * (1 - alpha))) - 1)
    return float(r[k])


def conformal_coverage(y: pd.Series, pred: np.ndarray, groups: pd.Series, alpha: float = ALPHA) -> pd.DataFrame:
    """Honest check: for each held-out county fold, the half-width comes from the other folds only."""
    res = y.values - pred
    rows = []
    for i, (_, te) in enumerate(GroupKFold(FOLDS).split(y, y, groups)):
        mask = np.ones(len(y), bool)
        mask[te] = False
        q = conformal_halfwidth(res[mask], alpha)
        rows.append({"fold": i, "halfwidth": q, "coverage": float(np.mean(np.abs(res[te]) <= q)), "n": len(te)})
    return pd.DataFrame(rows)


def quantile_gb_coverage(X: pd.DataFrame, y: pd.Series, groups: pd.Series, alpha: float = ALPHA) -> dict[str, float]:
    """Quantile gradient boosting (5th and 95th percentile) under county-held-out CV."""
    lo, hi = np.full(len(y), np.nan), np.full(len(y), np.nan)
    for tr, te in GroupKFold(FOLDS).split(X, y, groups):
        for q, out in ((alpha / 2, lo), (1 - alpha / 2, hi)):
            m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=300, learning_rate=0.05,
                                              min_samples_leaf=20, random_state=SEED)
            out[te] = m.fit(X.iloc[tr], y.iloc[tr]).predict(X.iloc[te])
    return {"coverage": float(np.mean((y.values >= lo) & (y.values <= hi))),
            "median_width": float(np.median(hi - lo))}


# ------------------------------------------------------------------ explain
def heldout_importance(model, X: pd.DataFrame, y: pd.Series, groups: pd.Series, repeats: int = 5) -> pd.DataFrame:
    """Permutation importance (drop in R2) on held-out counties, averaged over folds."""
    imps = []
    for tr, te in GroupKFold(FOLDS).split(X, y, groups):
        m = clone(model).fit(X.iloc[tr], y.iloc[tr])
        r = permutation_importance(m, X.iloc[te], y.iloc[te], n_repeats=repeats, random_state=SEED, scoring="r2")
        imps.append(pd.Series(r.importances_mean, index=X.columns))
    df = pd.concat(imps, axis=1)
    return pd.DataFrame({"importance": df.mean(axis=1), "fold_sd": df.std(axis=1)}).sort_values(
        "importance", ascending=False)


def pdp(model, X: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    rows = []
    for f in feats:
        r = partial_dependence(model, X, [f], grid_resolution=30, percentiles=(0.02, 0.98))
        for v, a in zip(r["grid_values"][0], r["average"][0], strict=True):
            rows.append({"feature": f, "value": float(v), "partial_dependence": float(a)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ backtest
def backtest(d: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train on 2010-14 -> 2015-19 ACS growth, predict 2015-19 -> 2020-24."""
    ok = (d.housing_units_2014 >= MIN_UNITS) & (d.housing_units_2019 >= MIN_UNITS) & (d.housing_units_2024 > 0)
    dd = d[ok]
    y1 = np.log(dd.housing_units_2019 / dd.housing_units_2014)
    y2 = np.log(dd.housing_units_2024 / dd.housing_units_2019)
    X1 = fill(features(dd, 2014, acs=True), dd.county)
    X2 = fill(features(dd, 2019, acs=True), dd.county, ref=X1)
    preds = {"median_of_earlier_period": np.full(len(y2), y1.median()), "last_period_rate": y1.values}
    for name, m in models().items():
        preds[name] = clone(m).fit(X1, y1).predict(X2)
    table_ = score_table(y2.values, preds, measurable(dd).values)
    detail = pd.DataFrame({"GEOID": dd.GEOID.values, "actual": y2.values, **{k: v for k, v in preds.items()}})
    return table_, detail


def score_table(actual: np.ndarray, preds: dict[str, np.ndarray], sure: np.ndarray) -> pd.DataFrame:
    """R2, MAE and correlation for each prediction, on all tracts and on tracts with a measurable change."""
    rows = []
    for k, p in preds.items():
        p = np.asarray(p, float)
        rows.append({"model": k, "r2": float(r2_score(actual, p)), "mae": float(mean_absolute_error(actual, p)),
                     "corr": _corr(actual, p), "r2_beyond_moe": float(r2_score(actual[sure], p[sure])),
                     "corr_beyond_moe": _corr(actual[sure], p[sure]), "tracts_beyond_moe": int(sure.sum())})
    return pd.DataFrame(rows)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a, b)[0, 1]) if np.std(b) > 0 and np.std(a) > 0 else float("nan")


def measurable(dd: pd.DataFrame) -> pd.Series:
    """Tracts whose 2015-19 to 2020-24 change in homes is larger than its ACS margin of error."""
    m = np.sqrt(dd.housing_units_moe_2019 ** 2 + dd.housing_units_moe_2024 ** 2)
    return (dd.housing_units_2024 - dd.housing_units_2019).abs() > m


# ------------------------------------------------------------------ ADUs by 2031
def demand_factor(pred_growth: pd.Series) -> pd.Series:
    """0.5 (slowest predicted growth) to 1.5 (fastest), by rank."""
    return 0.5 + pred_growth.rank(pct=True)


def lots_index(d: pd.DataFrame, lots: pd.DataFrame | None, cap: float) -> pd.DataFrame:
    """Share of homes on a lot with room, over the state share, capped. Fallback: single-family share."""
    out = pd.DataFrame({"GEOID": d.GEOID})
    hu = d.housing_units_2024.clip(lower=1)
    ref = d.single_family_detached_2024.sum() / d.housing_units_2024.sum()
    out["lots_index"] = (d.single_family_detached_2024 / hu / ref).clip(upper=cap).values
    out["lots_cap"] = d.single_family_detached_2024.values
    out["lots_source"] = "fallback: single-family detached share"
    if lots is not None:
        m = out.merge(lots[["GEOID", "lots_fit"]], on="GEOID", how="left")
        has = m.lots_fit.notna()
        ref6950 = m.loc[has, "lots_fit"].sum() / hu[has.values].sum()
        m.loc[has, "lots_index"] = (m.loc[has, "lots_fit"] / hu[has.values].values / ref6950).clip(upper=cap)
        m.loc[has, "lots_cap"] = m.loc[has, "lots_fit"]
        m.loc[has, "lots_source"] = "MUSA 6950 lots_tract.csv"
        out = m.drop(columns="lots_fit")
    return out


def town_split() -> pd.DataFrame:
    """Share of each tract in each town, weighted by workers who live in each block (LODES RAC 2024)."""
    xw = pd.read_csv(RAW5500 / "jobs" / "pa_xwalk.csv.gz", dtype=str,
                     usecols=["tabblk2020", "trct", "ctycsub", "blklatdd", "blklondd"])
    rac = pd.read_csv(RAW5500 / "jobs" / "pa_rac_2024.csv.gz", dtype={"h_geocode": str}, usecols=["h_geocode", "C000"])
    xw = xw.merge(rac, left_on="tabblk2020", right_on="h_geocode", how="left")
    xw["wt"] = xw.C000.fillna(0) + 0.01
    towns = gpd.read_file(PROCESSED / "towns_2020.gpkg")
    bad = ~xw.ctycsub.isin(towns.GEOID)
    pts = gpd.GeoDataFrame(xw[bad], geometry=gpd.points_from_xy(xw[bad].blklondd.astype(float),
                                                                 xw[bad].blklatdd.astype(float)), crs=4326)
    fix = gpd.sjoin_nearest(pts.to_crs(5070), towns[["GEOID", "geometry"]].to_crs(5070))[["GEOID"]]
    fix = fix[~fix.index.duplicated()]
    xw.loc[fix.index, "ctycsub"] = fix.GEOID.values
    split = xw.groupby(["trct", "ctycsub"]).wt.sum().reset_index()
    split["share"] = split.wt / split.groupby("trct").wt.transform("sum")
    return split.rename(columns={"trct": "GEOID", "ctycsub": "town_geoid"})[["GEOID", "town_geoid", "share"]]


def town_rules(towns: pd.DataFrame, legal: pd.DataFrame, unlisted: str) -> pd.DataFrame:
    r = towns[["GEOID", "NAMELSAD"]].merge(legal[["GEOID", "adu_rule"]], on="GEOID", how="left")
    r["listed"] = r.adu_rule.notna()
    r["adu_rule"] = r.adu_rule.replace("unknown", np.nan).fillna(unlisted)
    return r.rename(columns={"GEOID": "town_geoid", "NAMELSAD": "name"})


def rule_factor(rule: str, adu_rule: pd.Series, town: pd.Series, level: str, factors: dict) -> pd.Series:
    """Share of the permit rate under a scenario. State bills set 'allowed' where they reach."""
    today = adu_rule.map(lambda a: factors[a][level]).astype(float)
    if rule == "current":
        return today
    if rule == "hb2186":
        return pd.Series(factors["allowed"][level], index=adu_rule.index)
    if rule == "sb1346":   # the MPC does not govern Philadelphia or Pittsburgh
        out = pd.Series(factors["allowed"][level], index=adu_rule.index)
        return out.where(~town.isin([PHILADELPHIA, PITTSBURGH]), today)
    raise ValueError(rule)


def adu_pieces(tract: pd.DataFrame, split: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    """Tract x town pieces with ADUs by 2031 for every scenario and level."""
    rate = lmh("forecast.permits_per_100k")
    years = value("forecast.years")
    factors = table("forecast.rule_factor")
    p = split.merge(tract[["GEOID", "pop_2024", "factor", "lots_cap"]], on="GEOID").merge(rules, on="town_geoid")
    p["pop"] = p.pop_2024 * p.share
    p["cap"] = p.lots_cap.fillna(0) * p.share
    out = []
    for rule in RULES:
        r = p.copy()
        r["rule"] = rule
        for lvl in ("low", "mid", "high"):
            rf = rule_factor(rule, r.adu_rule, r.town_geoid, lvl, factors)
            est = r["pop"] / 1e5 * rate[lvl] * r.factor * rf * years
            r[f"adus_{lvl}"] = np.minimum(est, r.cap)
        out.append(r)
    return pd.concat(out, ignore_index=True)


def town_table(pieces: pd.DataFrame) -> pd.DataFrame:
    f = (pieces.groupby(["town_geoid", "name", "adu_rule", "listed", "rule"])
         .agg(pop=("pop", "sum"), adus_low=("adus_low", "sum"), adus_mid=("adus_mid", "sum"),
              adus_high=("adus_high", "sum"))
         .reset_index().rename(columns={"adu_rule": "rule_today"}))
    for c in ["pop", "adus_low", "adus_mid", "adus_high"]:
        f[c] = f[c].round(1)
    return f


def scenario_totals(pieces: pd.DataFrame, pop_pa: float, years: float) -> pd.DataFrame:
    tot = pieces.groupby("rule")[["adus_low", "adus_mid", "adus_high"]].sum()
    tot.columns = ["low", "mid", "high"]
    per_year = tot / years
    return pd.concat({"by_2031": tot, "per_year": per_year, "per_100k_per_year": per_year / pop_pa * 1e5}, axis=1)


def by_rule_today(pieces: pd.DataFrame) -> pd.DataFrame:
    """Mid ADUs by 2031 split by the town's rule today and whether it is coded in legal_status.csv."""
    k = pieces.assign(coded=np.where(pieces.listed, "coded", "not coded"))
    return k.pivot_table(index=["adu_rule", "coded"], columns="rule", values="adus_mid", aggfunc="sum").round(0)


# ------------------------------------------------------------------ run
def train_set(d: pd.DataFrame, with_migration: bool, mig: pd.DataFrame | None):
    ok = (d.dec_units_2010 >= MIN_UNITS) & (d.dec_units_2020 > 0)
    y = np.log(d.dec_units_2020[ok] / d.dec_units_2010[ok])
    X = features(d, 2010)
    if with_migration and mig is not None:
        X["net_mig_per_1000"] = migration.base_feature(mig, d, 2010).values
    X = fill(X[ok], d.county[ok])
    return X, y, ok


def run(save: bool = True, pays: pd.Series | None = None) -> dict[str, object]:
    # Histogram boosting on 3,400 rows is 10x slower with many OpenMP threads (thread overhead).
    with threadpool_limits(limits=1, user_api="openmp"):
        return _run(save, pays)


def _run(save: bool, pays: pd.Series | None) -> dict[str, object]:
    d = load_frame()
    mig = migration.load()
    lots_file = PROCESSED / "lots_tract.csv"
    lots = pd.read_csv(lots_file, dtype={"GEOID": str}) if lots_file.exists() else None

    # Part 1: model comparison, with and without the IRS migration feature
    X, y, ok = train_set(d, False, mig)
    Xm, _, _ = train_set(d, True, mig)
    county = d.county[ok]
    block = grid_blocks(d.x[ok], d.y[ok])
    cv, preds = compare(X, y, {"random_5fold": None, "county_blocks": county, "grid_40km_blocks": block})
    cv_mig, _ = compare(Xm, y, {"county_blocks": county})
    cv_mig = cv_mig[cv_mig.model != "median_baseline"].assign(scheme="county_blocks + IRS migration")
    spatial = cv[cv.scheme == "county_blocks"].set_index("model")
    # Rule: lowest county-held-out MAE. R2 is reported too, but a few crosswalk artifacts dominate it.
    best = spatial.drop(index="median_baseline").mae.idxmin()
    mig_gain = float(cv_mig.set_index("model").loc[best, "r2_fold_mean"] - spatial.loc[best, "r2_fold_mean"])
    use_mig = mig_gain > 0.02
    Xfit = Xm if use_mig else X
    model = clone(models()[best]).fit(Xfit, y)

    # Part 2: temporal backtest
    bt, bt_detail = backtest(d)

    # Part 3: intervals and explanation (for the chosen model, county-held-out)
    p_sp = preds[("county_blocks", best)] if not use_mig else oof_predict(models()[best], Xfit, y, county)
    cover = conformal_coverage(y, p_sp, county)
    half = conformal_halfwidth(y.values - p_sp)
    qgb = quantile_gb_coverage(Xfit, y, county)
    imp = heldout_importance(models()[best], Xfit, y, county)
    top4 = list(imp.index[:4])
    pd_tab = pdp(model, Xfit, top4)

    # Forecast from 2020: same features at the 2020 base
    X20 = features(d, 2020)
    if use_mig:
        X20["net_mig_per_1000"] = migration.base_feature(mig, d, 2020).values
    X20 = fill(X20, d.county, ref=Xfit)[Xfit.columns]
    logp = model.predict(X20)
    tract = d[["GEOID", "county", "pop_2024", "housing_units_2024", "single_family_detached_2024"]].copy()
    tract["pred_growth"] = np.expm1(logp)
    tract["pred_growth_lo"] = np.expm1(logp - half)
    tract["pred_growth_hi"] = np.expm1(logp + half)
    tract["demand_factor"] = demand_factor(tract.pred_growth)

    # Part 4: ADUs by 2031
    if pays is None:
        pays = pd.read_csv(PROCESSED / "payoff_tract.csv", dtype={"GEOID": str}).set_index("GEOID").pays
    weights = {k: float(v) for k, v in table("forecast.pays_weight").items()}
    tract["pays"] = tract.GEOID.map(pays)
    tract["pays_weight"] = tract.pays.map(weights).fillna(weights["no"])
    li = lots_index(d, lots, value("forecast.lots_index_cap"))
    tract = tract.merge(li, on="GEOID")
    tract["factor"] = tract.pays_weight * tract.lots_index * tract.demand_factor
    legal = pd.read_csv(LEGAL_STATUS, dtype={"GEOID": str}, comment="#")
    towns = gpd.read_file(PROCESSED / "towns_2020.gpkg", ignore_geometry=True)
    rules = town_rules(towns, legal, table("forecast.unlisted_rule")["rule"])
    pieces = adu_pieces(tract, town_split(), rules)
    towns_out = town_table(pieces)
    years = value("forecast.years")
    totals = scenario_totals(pieces, float(d.pop_2024.sum()), years)
    by_rule = by_rule_today(pieces)
    adus_tract = pieces.pivot_table(index="GEOID", columns="rule", values=["adus_low", "adus_mid", "adus_high"],
                                    aggfunc="sum")
    adus_tract.columns = [f"{v}_{r}" for v, r in adus_tract.columns]

    summary = {
        "model": best, "use_migration": bool(use_mig), "migration_gain_r2": mig_gain,
        "training_tracts": int(len(y)), "target_median_growth": float(np.expm1(y.median())),
        "conformal_halfwidth_log": half, "conformal_coverage_mean": float(cover.coverage.mean()),
        "conformal_coverage_min": float(cover.coverage.min()), "quantile_gb": qgb,
        "top4": top4,
        "totals": {r: {f"{a}.{b}": float(v) for (a, b), v in totals.loc[r].items()} for r in totals.index},
        "pa_pop_2024": float(d.pop_2024.sum()),
    }
    out = {"cv": pd.concat([cv, cv_mig], ignore_index=True), "backtest": bt, "backtest_detail": bt_detail,
           "coverage": cover, "importance": imp, "pdp": pd_tab, "tract": tract, "towns": towns_out,
           "totals": totals, "by_rule": by_rule, "adus_tract": adus_tract.reset_index(), "summary": summary,
           "X": Xfit, "y": y, "model_fit": model, "oof": p_sp}
    if save:
        save_outputs(out)
    return out


def save_outputs(r: dict) -> None:
    o = out_dir()
    r["cv"].to_csv(o / "forecast_cv.csv", index=False)
    r["backtest"].to_csv(o / "forecast_backtest.csv", index=False)
    r["coverage"].to_csv(o / "forecast_conformal.csv", index=False)
    r["importance"].to_csv(o / "forecast_importance.csv")
    r["pdp"].to_csv(o / "forecast_pdp.csv", index=False)
    r["totals"].to_csv(o / "forecast_totals.csv")
    r["by_rule"].to_csv(o / "forecast_by_rule_today.csv")
    r["adus_tract"].to_csv(o / "forecast_tract_adus.csv", index=False)
    write_json(r["summary"], o / "forecast_summary.json")
    t = r["tract"]
    r["towns"].to_csv(PROCESSED / "forecast_town.csv", index=False)
    t[["GEOID", "pop_2024", "pays", "pays_weight", "lots_index", "lots_source", "demand_factor", "factor",
       "pred_growth", "pred_growth_lo", "pred_growth_hi"]].to_csv(PROCESSED / "forecast_tract_inputs.csv", index=False)
    pay = pd.read_csv(PROCESSED / "payoff_tract.csv", dtype={"GEOID": str}).drop(columns=["pred_growth"],
                                                                                  errors="ignore")
    pay = pay.merge(t[["GEOID", "pred_growth"]].assign(pred_growth=t.pred_growth.round(4)), on="GEOID", how="left")
    pay.to_csv(PROCESSED / "payoff_tract.csv", index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Housing growth model and ADUs by 2031")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    r = run(save=not a.no_save)
    pd.set_option("display.width", 160)
    print(r["cv"].round(3).to_string(index=False))
    print(r["backtest"].round(3).to_string(index=False))
    print(r["coverage"].round(3).to_string(index=False))
    print(r["importance"].round(4))
    print(r["totals"].round(1))
    print(r["by_rule"])
    s = {k: v for k, v in r["summary"].items() if k != "totals"}
    print(s)


if __name__ == "__main__":
    main()
