"""Trend groups: clipping, k rule, stability on clear blobs, deterministic plain names."""
import numpy as np
import pandas as pd

from pipeline.tract import groups as G


def toy(seed: int = 0, n: int = 60) -> pd.DataFrame:
    """Three made-up growth paths: job boom after 2019, people leaving, flat."""
    rng = np.random.default_rng(seed)
    centers = {
        "boom": [0.00, 0.08, 0.00, 0.01, 0.01, 0.01],
        "leaving": [-0.01, -0.02, -0.02, -0.03, 0.00, -0.02],
        "flat": [0.01, 0.00, 0.00, 0.00, 0.01, 0.00],
    }
    rows = []
    for name, c in centers.items():
        pts = rng.normal(c, 0.002, size=(n, 6))
        for i, p in enumerate(pts):
            rows.append({"GEOID": f"{name}{i:03d}", **dict(zip(G.FEATS, p, strict=True)), "truth": name})
    return pd.DataFrame(rows)


def test_features_drop_blanks_and_clip():
    t = toy()
    t.loc[0, "jobs_growth_after"] = np.nan
    t.loc[1, "pop_growth_after"] = 5.0   # wild tiny-tract rate
    x = G.features(t)
    assert len(x) == len(t) - 1
    assert x.pop_growth_after.max() < 5.0


def test_kmeans_recovers_clear_blobs_and_is_stable():
    x = G.features(toy(), clip=(0.0, 1.0))
    z = G.scale(x)
    m = G.sweep(z, ks=range(2, 6), gap_refs=3)
    assert m.set_index("k").silhouette.idxmax() == 3
    assert G.bootstrap_stability(z, 3, reps=5) > 0.95
    assert G.seed_stability(z, 3, seeds=5) > 0.9


def test_choose_k_rule():
    m = pd.DataFrame({"k": [2, 3, 4], "silhouette": [0.20, 0.30, 0.35], "ari_bootstrap": [0.9, 0.85, 0.5],
                      "smallest_group_share": [0.4, 0.1, 0.1]})
    assert G.choose_k(m) == 3          # k=4 has the best silhouette but is unstable
    m.loc[1, "smallest_group_share"] = 0.01
    assert G.choose_k(m) == 2          # k=3 now has a tiny group


def test_names_are_plain_deterministic_and_follow_the_data():
    x = G.features(toy(), clip=(0.0, 1.0))
    z = G.scale(x)
    lab1 = G.kmeans(z, 3, seed=42).labels_
    lab2 = G.kmeans(z, 3, seed=42).labels_
    n1, n2 = G.name_groups(x, lab1), G.name_groups(x, lab2)
    assert n1 == n2
    named = pd.Series([n1[int(g)] for g in lab1], index=x.index)
    truth = toy().loc[x.index, "truth"]
    by_truth = named.groupby(truth).agg(lambda s: s.mode()[0])
    assert by_truth["boom"] == "Growing: jobs jumped after 2019"
    assert by_truth["leaving"].startswith("Shrinking")
    assert len(set(n1.values())) == 3
    # Relabelling the clusters does not change which tracts get which name
    perm = {0: 2, 1: 0, 2: 1}
    n3 = G.name_groups(x, np.array([perm[g] for g in lab1]))
    renamed = pd.Series([n3[perm[int(g)]] for g in lab1], index=x.index)
    assert (renamed == named).all()


def test_compare_methods_shapes():
    x = G.features(toy(), clip=(0.0, 1.0))
    scores, ari = G.compare_methods(G.scale(x), 3)
    assert set(scores.index) == {"kmeans", "gmm", "ward"}
    assert np.allclose(np.diag(ari.values), 1.0)
    assert (ari.values > 0.9).all()   # clear blobs: all three methods agree
