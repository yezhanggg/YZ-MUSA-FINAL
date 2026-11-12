"""Merge the availability survey and estimate coverage.

Reads corpus/survey/assign_<n>.csv and result_<n>.csv. A row counts for the worker whose
assignment holds its GEOID (one worker wrote some rows into another worker's file). Rows
marked "NOT SEARCHED", and sample places with no row, are "not surveyed".

Writes:
  corpus/availability.csv     one row per surveyed place, with the fetch check from the manifest
  corpus/sources/pilot.csv    fetch list for every place with a public own-site or county copy
  corpus/availability.json    estimates

Estimates use the stratified design in places.py. The certainty stratum (top 60) counts as
itself. Each size class is weighted by its count over the number surveyed in that class.
Ranges are 95 percent intervals (Wilson for each class, combined by a normal approximation
of the stratified estimate), plus a bound that puts every unsurveyed place in the worst or
best category.

Run:
    python -m pipeline.corpus.survey
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from typing import Any

from pipeline.corpus.fetch import load_manifest
from pipeline.corpus.paths import sub

CATS = ["own_site", "county", "state", "code_host_only", "no_zoning", "not_found"]
PUBLIC = {"own_site", "county", "state"}


def merged() -> dict[str, dict[str, Any]]:
    d = sub("survey")
    owner: dict[str, int] = {}
    for p in sorted(d.glob("assign_*.csv")):
        n = int(p.stem.split("_")[1])
        for r in csv.DictReader(p.open()):
            owner[r["geoid"]] = n
    rows: dict[str, dict[str, Any]] = {}
    for p in sorted(d.glob("result_*.csv")):
        for r in csv.DictReader(p.open()):
            g = (r.get("geoid") or "").strip()
            if not g or g not in owner:
                continue
            if "NOT SEARCHED" in (r.get("notes") or "").upper():
                continue
            if g in rows and rows[g].get("_file") == f"result_{owner[g]}.csv" and p.name != rows[g]["_file"]:
                continue  # keep the row from the owner's own file
            rows[g] = {**r, "_file": p.name}
    over = d / "overrides.csv"  # rows checked by hand during the pilot, they win
    if over.exists():
        for r in csv.DictReader(over.open()):
            rows[r["geoid"]] = {**rows.get(r["geoid"], {}), **{k: v for k, v in r.items() if v}, "_file": over.name}
    return rows


def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def estimate(
    sample: list[dict[str, Any]], surveyed: dict[str, dict[str, Any]], muni: list[dict[str, Any]], group: dict[str, str]
) -> dict[str, Any]:
    """Share of municipalities and of people per group of categories."""
    n_by: defaultdict[Any, int] = defaultdict(int)
    pop_by: defaultdict[Any, int] = defaultdict(int)
    for m in muni:
        n_by[m["stratum"]] += 1
        pop_by[m["stratum"]] += int(m["population"])
    total_n, total_pop = len(muni), sum(int(m["population"]) for m in muni)
    strata = defaultdict(list)
    for s in sample:
        if s["role"] in ("certainty", "random"):
            strata[s["stratum"]].append(s)
    out: dict[str, Any] = {"surveyed": {}, "groups": {}}
    groups = sorted(set(group.values()))
    for gname in groups:
        est_n = var_n = est_p = var_p = 0.0
        lo_n = hi_n = 0.0
        for st, members in strata.items():
            done = [m for m in members if m["geoid"] in surveyed]
            k = sum(1 for m in done if group.get(surveyed[m["geoid"]]["source_type"]) == gname)
            n = len(done)
            out["surveyed"][st] = {"surveyed": n, "in_sample": len(members), "stratum_size": n_by[st]}
            if st == "top60":  # every place in the stratum is in the sample
                kn = sum(int(m["population"]) for m in done if group.get(surveyed[m["geoid"]]["source_type"]) == gname)
                miss_pop = sum(int(m["population"]) for m in members if m["geoid"] not in surveyed)
                est_n += k + (len(members) - n) * (k / n if n else 0)
                est_p += kn + miss_pop * (k / n if n else 0)
                lo_n += k
                hi_n += k + (len(members) - n)
                continue
            share = k / n if n else 0.0
            w = n_by[st]
            est_n += w * share
            var_n += (w**2) * share * (1 - share) / max(n, 1) * (1 - n / w)
            mean_pop = pop_by[st] / n_by[st]
            pk = sum(int(m["population"]) for m in done if group.get(surveyed[m["geoid"]]["source_type"]) == gname)
            pn = sum(int(m["population"]) for m in done)
            pshare = pk / pn if pn else 0.0
            est_p += pop_by[st] * pshare
            var_p += (pop_by[st] ** 2) * share * (1 - share) / max(n, 1)
            lo, hi = wilson(k, n)
            lo_n += w * lo
            hi_n += w * hi
            del mean_pop
        se_n, se_p = math.sqrt(var_n), math.sqrt(var_p)
        out["groups"][gname] = {
            "municipalities_est": round(est_n),
            "share_municipalities": round(est_n / total_n, 3),
            "share_municipalities_95": [
                round(max(0, est_n - 1.96 * se_n) / total_n, 3),
                round(min(total_n, est_n + 1.96 * se_n) / total_n, 3),
            ],
            "share_municipalities_wilson_sum": [round(lo_n / total_n, 3), round(hi_n / total_n, 3)],
            "share_population": round(est_p / total_pop, 3),
            "share_population_95": [
                round(max(0, est_p - 1.96 * se_p) / total_pop, 3),
                round(min(total_pop, est_p + 1.96 * se_p) / total_pop, 3),
            ],
        }
    return out


def run() -> dict[str, Any]:
    root = sub("")
    sample = list(csv.DictReader((root / "sample.csv").open()))
    muni = list(csv.DictReader((root / "municipalities.csv").open()))
    rows = merged()
    man = load_manifest()
    by_url = {r["url"]: r for r in man.values()}
    out_rows = []
    for s in sample:
        r = rows.get(s["geoid"])
        rec = by_url.get(r["url"]) if r and r.get("url") else None
        out_rows.append(
            {
                "geoid": s["geoid"],
                "name": s["name"],
                "county": s["county"],
                "region": s["region"],
                "population": s["population"],
                "stratum": s["stratum"],
                "role": s["role"],
                "surveyed": bool(r),
                "source_type": r["source_type"] if r else "not_surveyed",
                "zoning_authority": r.get("zoning_authority", "") if r else "",
                "url": r.get("url", "") if r else "",
                "landing_url": r.get("landing_url", "") if r else "",
                "format": r.get("format", "") if r else "",
                "doc_date": r.get("doc_date", "") if r else "",
                "code_host": r.get("code_host", "") if r else "",
                "code_host_url": r.get("code_host_url", "") if r else "",
                "fetch_status": rec.get("status") if rec else "",
                "robots": rec.get("robots") if rec else "",
                "bytes": rec.get("bytes") if rec else "",
                "content_type": rec.get("content_type") if rec else "",
                "notes": r.get("notes", "") if r else "",
                "confidence": r.get("confidence", "") if r else "",
            }
        )
    with (root / "availability.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    # pilot fetch list
    src = sub("sources") / "pilot.csv"
    with src.open("w", newline="") as f:
        pw = csv.writer(f)
        pw.writerow(["geoid", "url", "kind", "pattern"])
        for r in out_rows:
            if r["source_type"] in PUBLIC and r["url"]:
                if r["format"] == "multi_pdf" and r["landing_url"]:
                    pw.writerow([r["geoid"], r["landing_url"], "index", ""])
                else:
                    pw.writerow([r["geoid"], r["url"], "doc", ""])
    surveyed = {g: v for g, v in rows.items()}
    groups = {
        "by_category": {c: c for c in CATS},
        "by_access": {
            "own_site": "public",
            "county": "public",
            "state": "public",
            "code_host_only": "code_host_only",
            "no_zoning": "no_zoning",
            "not_found": "not_found",
        },
    }
    est = {k: estimate(sample, surveyed, muni, g) for k, g in groups.items()}
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in out_rows:
        counts[r["role"]][r["source_type"]] += 1
    res = {"counts_by_role": {k: dict(v) for k, v in counts.items()}, "estimates": est}
    (root / "availability.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))
