"""Pennsylvania municipalities (2020 Census county subdivisions) and the survey sample.

The list comes from the PL 94-171 geo header that tools/town_targets.py caches.
Places split across counties (Bethlehem, for one) are merged into one row, keyed by
the part with the most people. That gives the 2,560 municipalities.

Survey design:
  - certainty stratum: the 60 most populous municipalities (all in towns_index.json)
  - five size classes for the rest, 30 places each, spread over six regions in
    proportion to their counts, fixed seed
  - every place in towns_index.json is surveyed too. Index places outside the top 60
    are reported but not used for the statewide estimate unless the random draw
    picked them

Run:
    python -m pipeline.corpus.places            # write municipalities.csv and sample.csv
"""

from __future__ import annotations

import csv
import importlib.util
import json
import random
from pathlib import Path
from typing import Any

from pipeline.corpus.paths import REPO, RULES, sub

SEED = 20261111
TOP_N = 60
PER_CLASS = 30
SIZE_CLASSES = [
    (0, 1000, "under 1k"),
    (1000, 2500, "1k-2.5k"),
    (2500, 5000, "2.5k-5k"),
    (5000, 10000, "5k-10k"),
    (10000, 10**9, "10k+"),
]

REGIONS = {
    "Southeast": ["Bucks", "Chester", "Delaware", "Montgomery", "Philadelphia"],
    "Northeast": [
        "Carbon",
        "Lackawanna",
        "Lehigh",
        "Luzerne",
        "Monroe",
        "Northampton",
        "Pike",
        "Schuylkill",
        "Susquehanna",
        "Wayne",
        "Wyoming",
    ],
    "South Central": [
        "Adams",
        "Berks",
        "Cumberland",
        "Dauphin",
        "Franklin",
        "Fulton",
        "Juniata",
        "Lancaster",
        "Lebanon",
        "Mifflin",
        "Perry",
        "York",
    ],
    "North Central": [
        "Bradford",
        "Cameron",
        "Centre",
        "Clearfield",
        "Clinton",
        "Columbia",
        "Elk",
        "Lycoming",
        "McKean",
        "Montour",
        "Northumberland",
        "Potter",
        "Snyder",
        "Sullivan",
        "Tioga",
        "Union",
    ],
    "Northwest": ["Clarion", "Crawford", "Erie", "Forest", "Jefferson", "Lawrence", "Mercer", "Venango", "Warren"],
    "Southwest": [
        "Allegheny",
        "Armstrong",
        "Beaver",
        "Bedford",
        "Blair",
        "Butler",
        "Cambria",
        "Fayette",
        "Greene",
        "Huntingdon",
        "Indiana",
        "Somerset",
        "Washington",
        "Westmoreland",
    ],
}
COUNTY_REGION = {c: r for r, cs in REGIONS.items() for c in cs}


def _town_targets() -> Any:
    spec = importlib.util.spec_from_file_location("town_targets", REPO / "tools" / "town_targets.py")
    if spec is None or spec.loader is None:
        raise ImportError("tools/town_targets.py not found")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def size_class(pop: int) -> str:
    return next(label for lo, hi, label in SIZE_CLASSES if lo <= pop < hi)


def municipalities() -> list[dict[str, Any]]:
    """One row per municipality, split parts merged, with region and size class."""
    tt = _town_targets()
    rows = [r for r in tt.pl_geo_rows() if r["type"] != "other"]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["geoid"][5:], r["name"]), []).append(r)
    out = []
    for parts in groups.values():
        parts.sort(key=lambda r: -r["population"])
        main = dict(parts[0])
        main["geoid_aliases"] = [p["geoid"] for p in parts[1:]]
        main["population"] = sum(p["population"] for p in parts)
        main["housing_units"] = sum(p["housing_units"] for p in parts)
        main["counties"] = [p["county"] for p in parts]
        main["region"] = COUNTY_REGION[main["county"]]
        out.append(main)
    out.sort(key=lambda r: -r["population"])
    for i, r in enumerate(out):
        r["pop_rank"] = i + 1
        r["stratum"] = "top60" if i < TOP_N else size_class(r["population"])
    return out


def index_towns() -> dict[str, dict[str, Any]]:
    data = json.loads((RULES / "towns_index.json").read_text())
    return {t["geoid"]: t for t in data["towns"]}


def draw_sample(rows: list[dict[str, Any]], seed: int = SEED) -> list[dict[str, Any]]:
    """30 per size class outside the top 60, spread over regions by count (largest remainder)."""
    rng = random.Random(seed)
    picked = []
    for _, _, label in SIZE_CLASSES:
        pool = [r for r in rows if r["stratum"] == label]
        by_region: dict[str, list[dict[str, Any]]] = {}
        for r in pool:
            by_region.setdefault(r["region"], []).append(r)
        quotas = {k: PER_CLASS * len(v) / len(pool) for k, v in by_region.items()}
        alloc = {k: int(q) for k, q in quotas.items()}
        for k in sorted(quotas, key=lambda k: -(quotas[k] - alloc[k]))[: PER_CLASS - sum(alloc.values())]:
            alloc[k] += 1
        for region in sorted(by_region):
            cands = sorted(by_region[region], key=lambda r: r["geoid"])
            picked += rng.sample(cands, alloc[region])
    return picked


def survey_rows() -> list[dict[str, Any]]:
    rows = municipalities()
    idx = index_towns()
    sample = {r["geoid"] for r in draw_sample(rows)}
    n_class: dict[Any, int] = {}
    for r in rows:
        n_class[r["stratum"]] = n_class.get(r["stratum"], 0) + 1
    out = []
    for r in rows:
        in_index = r["geoid"] in idx or any(a in idx for a in r["geoid_aliases"])
        if r["stratum"] == "top60":
            role, weight = "certainty", 1.0
        elif r["geoid"] in sample:
            role, weight = "random", n_class[r["stratum"]] / PER_CLASS
        elif in_index:
            role, weight = "index_only", 0.0
        else:
            continue
        t = idx.get(r["geoid"], {})
        out.append(
            {
                "geoid": r["geoid"],
                "name": r["name"],
                "county": r["county"],
                "region": r["region"],
                "population": r["population"],
                "housing_units": r["housing_units"],
                "pop_rank": r["pop_rank"],
                "stratum": r["stratum"],
                "role": role,
                "weight": round(weight, 4),
                "in_index": in_index,
                "index_file": t.get("file", ""),
                "index_status": t.get("status", ""),
                "index_code_host": t.get("code_host", ""),
                "index_code_url": t.get("code_url", ""),
            }
        )
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    rows = municipalities()
    out = sub("")
    write_csv(
        out / "municipalities.csv",
        [
            {
                k: (";".join(v) if isinstance(v, list) else v)
                for k, v in r.items()
                if k not in ("county_fips", "basename")
            }
            for r in rows
        ],
    )
    s = survey_rows()
    write_csv(out / "sample.csv", s)
    print(f"{len(rows)} municipalities, {sum(r['population'] for r in rows):,} people")
    counts: dict[str, int] = {}
    for r in s:
        counts[r["role"]] = counts.get(r["role"], 0) + 1
    print("survey rows", len(s), counts)


if __name__ == "__main__":
    main()
