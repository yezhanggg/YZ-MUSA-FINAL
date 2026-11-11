"""Trend groups: tracts with similar growth paths before and after 2019.

Steps
    1. Six features: yearly growth of jobs, people and real rent, before and after.
       Clip each to its 1st and 99th percentile, then standardize.
    2. Scaling check: spread of each feature before and after scaling.
    3. k from 2 to 10: inertia (elbow), silhouette, Davies-Bouldin, Calinski-Harabasz, gap statistic.
    4. Stability: adjusted Rand index between K-means runs with different seeds,
       and between the full fit and fits on 80 percent subsamples.
    5. Compare K-means with a Gaussian mixture and Ward clustering at the chosen k.
    6. Name groups from their median growth, in plain growing / steady / shrinking words.

Run:  python -m pipeline.tract.groups
Adds trend_group to data/processed/trends_tract.csv and writes groups_* files in
<data root>/processed/5500.
"""
from __future__ import annotations

import argparse
from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import adjusted_rand_score, calinski_harabasz_score, davies_bouldin_score, silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

from pipeline.tract.io import PROCESSED, out_dir, write_json

FEATS = ["jobs_growth_before", "jobs_growth_after", "pop_growth_before", "pop_growth_after",
         "rent_growth_before", "rent_growth_after"]
CLIP = (0.01, 0.99)
K_RANGE = range(2, 11)
SEED = 42
N_SEEDS = 20
N_BOOT = 20
NO_DATA = "Not enough data"
# A group median counts as up or down when it is this far from the all-tract median (share per year).
BAND = 0.005


# ------------------------------------------------------------------ features
def features(trends: pd.DataFrame, feats: list[str] = FEATS, clip: tuple[float, float] = CLIP) -> pd.DataFrame:
    """Rows with all features, clipped to the given quantiles. Index = trends index, plus GEOID."""
    x = trends.dropna(subset=feats)[["GEOID"] + feats].copy()
    for c in feats:
        lo, hi = x[c].quantile(list(clip))
        x[c] = x[c].clip(lo, hi)
    return x


def scale(x: pd.DataFrame, feats: list[str] = FEATS) -> np.ndarray:
    return StandardScaler().fit_transform(x[feats])


def scaling_check(x: pd.DataFrame, feats: list[str] = FEATS) -> pd.DataFrame:
    """Spread of each feature raw (% per year) and after scaling. Unscaled, jobs would dominate."""
    z = scale(x, feats)
    return pd.DataFrame({"raw_std_pct": x[feats].std() * 100, "raw_iqr_pct": (x[feats].quantile(0.75)
                         - x[feats].quantile(0.25)) * 100, "skew": x[feats].skew(),
                         "scaled_std": z.std(axis=0), "share_of_raw_variance": x[feats].var() / x[feats].var().sum()})


# ------------------------------------------------------------------ k sweep
def kmeans(z: np.ndarray, k: int, seed: int = SEED, n_init: int = 10) -> KMeans:
    return KMeans(n_clusters=k, n_init=n_init, random_state=seed).fit(z)


def gap_statistic(z: np.ndarray, k: int, refs: int = 10, seed: int = SEED) -> tuple[float, float]:
    """Tibshirani gap: log inertia of uniform reference data minus log inertia of the data. Returns (gap, s_k)."""
    rng = np.random.default_rng(seed)
    lo, hi = z.min(axis=0), z.max(axis=0)
    ref = [np.log(kmeans(rng.uniform(lo, hi, size=z.shape), k, seed, n_init=3).inertia_) for _ in range(refs)]
    gap = float(np.mean(ref) - np.log(kmeans(z, k, seed).inertia_))
    return gap, float(np.std(ref) * np.sqrt(1 + 1 / refs))


def sweep(z: np.ndarray, ks=K_RANGE, seed: int = SEED, gap_refs: int = 10) -> pd.DataFrame:
    rows = []
    for k in ks:
        km = kmeans(z, k, seed)
        gap, sk = gap_statistic(z, k, gap_refs, seed) if gap_refs else (np.nan, np.nan)
        gmm = GaussianMixture(k, covariance_type="full", n_init=3, random_state=seed).fit(z)
        rows.append({"k": k, "inertia": km.inertia_, "silhouette": silhouette_score(z, km.labels_),
                     "davies_bouldin": davies_bouldin_score(z, km.labels_),
                     "calinski_harabasz": calinski_harabasz_score(z, km.labels_),
                     "gap": gap, "gap_s": sk, "gmm_bic": gmm.bic(z),
                     "smallest_group_share": float(np.bincount(km.labels_).min() / len(z))})
    out = pd.DataFrame(rows)
    # Tibshirani rule: smallest k with gap(k) >= gap(k+1) - s(k+1)
    ok = out.gap.values[:-1] >= (out.gap.values[1:] - out.gap_s.values[1:])
    out["gap_rule_ok"] = list(ok) + [False]
    return out


# ------------------------------------------------------------------ stability
def seed_stability(z: np.ndarray, k: int, seeds: int = N_SEEDS) -> float:
    """Mean adjusted Rand index between K-means fits (one start each) with different seeds."""
    labels = [KMeans(n_clusters=k, n_init=1, random_state=s).fit(z).labels_ for s in range(seeds)]
    return float(np.mean([adjusted_rand_score(a, b) for a, b in combinations(labels, 2)]))


def bootstrap_stability(z: np.ndarray, k: int, reps: int = N_BOOT, frac: float = 0.8, seed: int = SEED) -> float:
    """Mean ARI between the full fit and fits on random 80 percent subsamples (labels predicted for all rows)."""
    rng = np.random.default_rng(seed)
    full = kmeans(z, k, seed).labels_
    scores = []
    for r in range(reps):
        idx = rng.choice(len(z), int(frac * len(z)), replace=False)
        sub = kmeans(z[idx], k, seed + r + 1)
        scores.append(adjusted_rand_score(full, sub.predict(z)))
    return float(np.mean(scores))


def stability(z: np.ndarray, ks=K_RANGE) -> pd.DataFrame:
    return pd.DataFrame([{"k": k, "ari_seeds": seed_stability(z, k), "ari_bootstrap": bootstrap_stability(z, k)}
                         for k in ks])


# ------------------------------------------------------------------ methods
def fit_methods(z: np.ndarray, k: int, seed: int = SEED) -> dict[str, np.ndarray]:
    return {
        "kmeans": kmeans(z, k, seed).labels_,
        "gmm": GaussianMixture(k, covariance_type="full", n_init=5, random_state=seed).fit(z).predict(z),
        "ward": AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(z),
    }


def compare_methods(z: np.ndarray, k: int, seed: int = SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    labels = fit_methods(z, k, seed)
    scores = pd.DataFrame([{"method": m, "silhouette": silhouette_score(z, lab),
                            "davies_bouldin": davies_bouldin_score(z, lab),
                            "smallest_group_share": float(np.bincount(lab).min() / len(z))}
                           for m, lab in labels.items()]).set_index("method")
    ari = pd.DataFrame({a: {b: adjusted_rand_score(labels[a], labels[b]) for b in labels} for a in labels})
    return scores, ari


def choose_k(metrics: pd.DataFrame, min_ari: float = 0.8, min_share: float = 0.02) -> int:
    """Stated rule: among k that are stable (bootstrap ARI >= min_ari) and have no group under
    min_share of tracts, take the best silhouette. Ties go to the smaller k."""
    ok = metrics[(metrics.ari_bootstrap >= min_ari) & (metrics.smallest_group_share >= min_share)]
    pool = ok if len(ok) else metrics
    best = pool.silhouette.max()
    return int(pool[pool.silhouette >= best - 1e-9].k.min())


# ------------------------------------------------------------------ naming
PHRASES = {
    ("jobs_growth_before", 1): "jobs grew fast before 2019", ("jobs_growth_before", -1): "jobs fell before 2019",
    ("jobs_growth_after", 1): "jobs jumped after 2019", ("jobs_growth_after", -1): "jobs fell after 2019",
    ("pop_growth_before", 1): "people grew fast before 2019", ("pop_growth_before", -1): "people left before 2019",
    ("pop_growth_after", 1): "population jump after 2019", ("pop_growth_after", -1): "people left after 2019",
    ("rent_growth_before", 1): "rents rose fast before 2019", ("rent_growth_before", -1): "rents fell before 2019",
    ("rent_growth_after", 1): "rents rose fast after 2019", ("rent_growth_after", -1): "rents fell after 2019",
}
STANDOUT = 0.5   # a feature stands out when the group median is this many standard deviations from the mean


def name_groups(x: pd.DataFrame, labels: np.ndarray, feats: list[str] = FEATS, band: float = BAND) -> dict[int, str]:
    """Plain names backed by the group medians.

    Head word from growth after 2019 (mean of the jobs and people rates, group median):
    Growing above +band a year, Shrinking below -band, else Steady.
    Then the measure that stands out most (largest median z-score, at least STANDOUT),
    for example "jobs jumped after 2019". A second measure is added if two names clash.
    Deterministic: the same data and labels always give the same names.
    """
    z = (x[feats] - x[feats].mean()) / x[feats].std()
    zmed = z.groupby(labels).median()
    med = x[feats].groupby(labels).median()
    names: dict[int, str] = {}
    order: dict[int, list[str]] = {}
    for g in sorted(med.index):
        after = (med.loc[g, "jobs_growth_after"] + med.loc[g, "pop_growth_after"]) / 2
        head = "Growing" if after > band else "Shrinking" if after < -band else "Steady"
        ranked = zmed.loc[g].abs().sort_values(ascending=False, kind="stable")
        phrases = [PHRASES[(f, 1 if zmed.loc[g, f] > 0 else -1)] for f in ranked.index if ranked[f] >= STANDOUT]
        order[int(g)] = phrases
        names[int(g)] = f"{head}: {phrases[0]}" if phrases else f"{head}: close to the state median"
    for _ in range(2):   # resolve clashes with the next phrase, then with a number
        counts = pd.Series(names).value_counts()
        for g, n in list(names.items()):
            if counts[n] > 1 and len(order[g]) > 1 and order[g][1] not in n:
                names[g] = f"{n}, {order[g][1]}"
    seen: dict[str, int] = {}
    for g in sorted(names):
        seen[names[g]] = seen.get(names[g], 0) + 1
        if seen[names[g]] > 1:
            names[g] = f"{names[g]} ({seen[names[g]]})"
    return names


def profile(x: pd.DataFrame, labels: np.ndarray, names: dict[int, str], feats: list[str] = FEATS) -> pd.DataFrame:
    """Median yearly growth (% per year) and tract count per group."""
    p = x[feats].groupby(labels).median() * 100
    p["tracts"] = pd.Series(labels).value_counts()
    p.index = [names[i] for i in p.index]
    p.index.name = "trend_group"
    return p.sort_values("tracts", ascending=False)


def moe_by_group(trends: pd.DataFrame) -> pd.DataFrame:
    """Per group: share of tracts whose 5-year change is larger than its ACS margin of error."""
    cols = {"pop_before": "pop_before_within_moe", "pop_after": "pop_after_within_moe",
            "rent_before": "rent_before_within_moe", "rent_after": "rent_after_within_moe"}
    out = {}
    for name, c in cols.items():
        v = trends[c].map({True: 0.0, False: 1.0, "True": 0.0, "False": 1.0})
        out[f"share_{name}_beyond_moe"] = v.groupby(trends.trend_group).mean()
    return pd.DataFrame(out)


# ------------------------------------------------------------------ run
def run(save: bool = True, k: int | None = None, method: str = "kmeans") -> dict[str, object]:
    trends = pd.read_csv(PROCESSED / "trends_tract.csv", dtype={"GEOID": str})
    trends = trends.drop(columns=["trend_group"], errors="ignore")
    x = features(trends)
    z = scale(x)
    sc = scaling_check(x)
    sw = sweep(z)
    st = stability(z)
    metrics = sw.merge(st, on="k")
    k = k or choose_k(metrics)
    scores, ari = compare_methods(z, k)
    labels = fit_methods(z, k)[method]
    names = name_groups(x, labels)
    prof = profile(x, labels, names)
    x["trend_group"] = [names[int(g)] for g in labels]
    out = trends.merge(x[["GEOID", "trend_group"]], on="GEOID", how="left")
    out["trend_group"] = out.trend_group.fillna(NO_DATA)
    result = {"x": x, "z": z, "scaling": sc, "metrics": metrics, "k": k, "method": method,
              "method_scores": scores, "method_ari": ari, "profile": prof, "trends": out}
    if save:
        out.to_csv(PROCESSED / "trends_tract.csv", index=False)
        o = out_dir()
        metrics.to_csv(o / "groups_k_metrics.csv", index=False)
        prof.to_csv(o / "groups_profile.csv")
        scores.join(ari.add_prefix("ari_vs_")).to_csv(o / "groups_methods.csv")
        sc.to_csv(o / "groups_scaling.csv")
        moe_by_group(out).to_csv(o / "groups_moe.csv")
        write_json({"k": k, "method": method, "tracts": int(len(x)), "no_data": int((out.trend_group == NO_DATA).sum()),
                    "silhouette": float(scores.loc[method, "silhouette"]),
                    "davies_bouldin": float(scores.loc[method, "davies_bouldin"]),
                    "ari_bootstrap": float(metrics.set_index("k").loc[k, "ari_bootstrap"]),
                    "ari_seeds": float(metrics.set_index("k").loc[k, "ari_seeds"]),
                    "counts": out.trend_group.value_counts().to_dict()}, o / "groups_summary.json")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Trend groups for 2020 tracts")
    ap.add_argument("--k", type=int, default=None, help="force k (default: the stated rule)")
    ap.add_argument("--method", default="kmeans", choices=["kmeans", "gmm", "ward"])
    a = ap.parse_args()
    r = run(k=a.k, method=a.method)
    pd.set_option("display.width", 160)
    print(r["scaling"].round(3))
    print(r["metrics"].round(3).to_string(index=False))
    print("k =", r["k"])
    print(r["method_scores"].round(3))
    print(r["method_ari"].round(3))
    print(r["profile"].round(2))


if __name__ == "__main__":
    main()
