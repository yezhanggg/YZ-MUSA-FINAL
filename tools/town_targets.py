"""Rank Pennsylvania towns for ADU rule files and write shared/rules/towns_index.json.

Population and housing units come from the 2020 Census redistricting file (PL 94-171)
for Pennsylvania, county subdivision level (summary level 060). The Census API needs a
key, so this reads the published file from www2.census.gov instead. The zip is about
57 MB and is cached outside the repo.

The list is:
  - Philadelphia and Pittsburgh (rule files already written, batch 0)
  - the top 60 county subdivisions by 2020 population (the two cities included)
  - every town in shared/legal_status.csv
  - smaller towns known for ADU ordinances (EXTRAS, each with the source that names it)

Batches of 6. Batches 1 and 2 are fixed (already assigned). The rest follow population
order, then legal_status.csv towns, then the extras.

Statuses (todo, in_progress, drafted, verified) already in the index are kept. A town
whose rule file exists moves from todo or in_progress to drafted. checked_on is the
file's provenance.verified_on.

Run:
    /opt/anaconda3/envs/geospatial/bin/python tools/town_targets.py          # write the index
    /opt/anaconda3/envs/geospatial/bin/python tools/town_targets.py --print  # also print the table
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "shared" / "rules"
INDEX = RULES / "towns_index.json"
LEGAL = ROOT / "shared" / "legal_status.csv"
PL_URL = ("https://www2.census.gov/programs-surveys/decennial/2020/data/"
          "01-Redistricting_File--PL_94-171/Pennsylvania/pa2020.pl.zip")
CACHE = Path(os.environ.get("TOWN_TARGETS_CACHE", Path.home() / "musa-drive" / "cache" / "census"))
PA_POP_2020 = 13_002_700  # state total, checked against the file below
TOP_N = 60
BATCH_SIZE = 6

# Geo header fields (2020 PL 94-171 technical documentation, pipe delimited).
F_SUMLEV, F_GEOCODE, F_COUNTY, F_BASENAME, F_NAME, F_FUNCSTAT, F_POP100, F_HU100 = 2, 9, 14, 86, 87, 88, 90, 91

CITY_FILES = {"4210160000": "philadelphia", "4200361000": "pittsburgh"}
ASSIGNED = {  # batch -> GEOIDs, in the order the workers were given them
    1: ["4207702000", "4201163624", "4204924000", "4206969000", "4209506088", "4207141216"],
    2: ["4204332800", "4213387048", "4202773808", "4204579000", "4209144976", "4201705616"],
}
# Smaller towns known for ADU ordinances, with the source that names them. Up to 15.
EXTRAS: dict[str, str] = {}  # filled below the HOSTS table

TYPE_WORDS = ("city", "borough", "township", "town", "municipality")


def pl_geo_rows(cache: Path = CACHE) -> list[dict[str, Any]]:
    """County subdivisions of Pennsylvania with 2020 population and housing units."""
    cache.mkdir(parents=True, exist_ok=True)
    zpath = cache / "pa2020.pl.zip"
    if not zpath.exists():
        print(f"downloading {PL_URL}", file=sys.stderr)
        urllib.request.urlretrieve(PL_URL, zpath)
    counties: dict[str, str] = {}
    rows = []
    with zipfile.ZipFile(zpath) as z:
        with z.open("pageo2020.pl") as raw:
            for line in io.TextIOWrapper(raw, encoding="latin-1"):
                p = line.rstrip("\r\n").split("|")
                if p[F_SUMLEV] == "050":
                    counties[p[F_COUNTY]] = p[F_BASENAME]
                elif p[F_SUMLEV] == "060":
                    rows.append({"geoid": p[F_GEOCODE], "name": p[F_NAME], "basename": p[F_BASENAME],
                                 "county_fips": p[F_COUNTY], "population": int(p[F_POP100]),
                                 "housing_units": int(p[F_HU100])})
    total = sum(r["population"] for r in rows)
    if total != PA_POP_2020:
        raise SystemExit(f"county subdivisions sum to {total:,}, expected {PA_POP_2020:,}. Check field positions")
    for r in rows:
        r["county"] = counties[r["county_fips"]]
        r["type"] = next((t for t in TYPE_WORDS if r["name"].endswith(" " + t)), "other")
    return rows


def snake(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower().replace("'", "")).strip("_")


def file_names(rows: list[dict[str, Any]]) -> dict[str, str]:
    """pa_<county>_<town>. When two places in one county share a name, the larger keeps it."""
    out: dict[str, str] = {}
    taken: dict[str, int] = {}
    for r in sorted(rows, key=lambda r: -r["population"]):
        base = f"pa_{snake(r['county'])}_{snake(r['basename'])}"
        name = base if base not in taken else f"{base}_{r['type']}"
        taken[base] = taken.get(base, 0) + 1
        out[r["geoid"]] = CITY_FILES.get(r["geoid"], name)
    return out


def legal_geoids() -> list[str]:
    lines = [ln for ln in LEGAL.read_text().splitlines() if ln and not ln.startswith("#")]
    return [row["GEOID"] for row in csv.DictReader(lines)]


def checked_on(file: str) -> str | None:
    path = RULES / f"{file}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())["provenance"].get("verified_on")
    except (ValueError, KeyError):
        return None  # a file mid-edit


def build(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by = {r["geoid"]: r for r in rows}
    ranked = sorted(rows, key=lambda r: -r["population"])
    rank = {r["geoid"]: i + 1 for i, r in enumerate(ranked)}
    files = file_names(rows)
    top = [r["geoid"] for r in ranked[:TOP_N]]
    legal = [g for g in legal_geoids() if g in by]
    order: list[str] = []
    why: dict[str, list[str]] = {}
    for g in top:
        why.setdefault(g, []).append(f"top {TOP_N} by 2020 population")
    for g in legal:
        why.setdefault(g, []).append("in shared/legal_status.csv")
    for g, src in EXTRAS.items():
        why.setdefault(g, []).append(f"known ADU ordinance ({src})")
    batch: dict[str, int] = {g: 0 for g in CITY_FILES}
    for b, gs in ASSIGNED.items():
        batch.update({g: b for g in gs})
    rest = [g for g in top + legal + list(EXTRAS) if g not in batch]
    rest = list(dict.fromkeys(rest))
    for i, g in enumerate(rest):
        batch[g] = 3 + i // BATCH_SIZE
    order = list(CITY_FILES) + [g for b in sorted(ASSIGNED) for g in ASSIGNED[b]] + rest

    old = {t["geoid"]: t for t in (json.loads(INDEX.read_text())["towns"] if INDEX.exists() else [])}
    towns = []
    for g in order:
        r, prev, host = by[g], old.get(g, {}), HOSTS.get(g, {})
        file = files[g]
        status = prev.get("status") or ("verified" if g in CITY_FILES else
                                        "in_progress" if batch[g] in ASSIGNED else "todo")
        if (RULES / f"{file}.json").exists() and status in ("todo", "in_progress"):
            status = "drafted"
        towns.append({
            "geoid": g, "name": r["name"], "county": r["county"], "type": r["type"],
            "population": r["population"], "housing_units": r["housing_units"], "pop_rank": rank[g],
            "file": file, "batch": batch[g], "status": status, "checked_on": checked_on(file),
            "code_host": host.get("code_host", "unknown"), "code_url": host.get("code_url"),
            "plain_fetch": host.get("plain_fetch"), "code_current_through": host.get("current_through"),
            "code_note": host.get("note"), "why": why.get(g, ["already has a rule file"]),
        })
    return {
        "about": "Pennsylvania towns targeted for ADU rule files, ranked. Made by tools/town_targets.py. "
                 "Town workers update only 'status'. See TOWNS.md.",
        "generated_on": date.today().isoformat(),
        "population_source": {"title": "2020 Census Redistricting Data (PL 94-171), Pennsylvania, county subdivisions",
                              "url": PL_URL, "fields": "POP100 (total population), HU100 (housing units)",
                              "pa_population_2020": PA_POP_2020},
        "coverage": coverage(towns),
        "towns": towns,
    }


def coverage(towns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Share of the 2020 PA population in Philadelphia, Pittsburgh and the first n batch towns."""
    cities = [t for t in towns if t["batch"] == 0]
    rest = [t for t in towns if t["batch"] > 0]
    base = sum(t["population"] for t in cities)
    out = []
    for n in (0, 12, 24, 36, 48, 60, len(rest)):
        pop = base + sum(t["population"] for t in rest[:n])
        out.append({"towns_beyond_the_two_cities": n, "population": pop, "share_of_pa": round(pop / PA_POP_2020, 4)})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--print", action="store_true", help="print the ranked table")
    a = ap.parse_args(argv)
    index = build(pl_geo_rows())
    INDEX.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    if a.print:
        for t in index["towns"]:
            print(f"{t['batch']:>2} {t['status']:<11} {t['pop_rank']:>4} {t['name']:<34} {t['county']:<13} "
                  f"{t['population']:>9,} {t['code_host']:<10} {t['code_url'] or ''}")
        for c in index["coverage"]:
            print(f"{c['towns_beyond_the_two_cities']:>3} towns + the two cities: {c['share_of_pa']:.1%}")
    print(f"wrote {INDEX.relative_to(ROOT)} with {len(index['towns'])} towns")
    return 0


# ------------------------------------------------------------------ code hosts
# Where each town's zoning code is published, found by web search on 2026-11-11.
# plain_fetch: a plain HTTP GET returns the code text. ecode360, municode and amlegal answer
# plain fetches with a bot challenge (403), so their pages are false. A town worker opens them
# in a browser. current_through: the date the publisher shows, when it could be read.
HOSTS: dict[str, dict[str, Any]] = {}

if __name__ == "__main__":
    sys.exit(main())
