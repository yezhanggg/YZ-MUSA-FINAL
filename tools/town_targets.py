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
file's provenance.verified_on. plain_fetch for a file whose code_url is not in the host
table keeps the value the index holds (a rebuild fetches nothing). On the same index and
files a rebuild reproduces the committed index except generated_on.

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
PL_URL = (
    "https://www2.census.gov/programs-surveys/decennial/2020/data/"
    "01-Redistricting_File--PL_94-171/Pennsylvania/pa2020.pl.zip"
)
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
    with zipfile.ZipFile(zpath) as z, z.open("pageo2020.pl") as raw:
        for line in io.TextIOWrapper(raw, encoding="latin-1"):
            p = line.rstrip("\r\n").split("|")
            if p[F_SUMLEV] == "050":
                counties[p[F_COUNTY]] = p[F_BASENAME]
            elif p[F_SUMLEV] == "060":
                rows.append(
                    {
                        "geoid": p[F_GEOCODE],
                        "name": p[F_NAME],
                        "basename": p[F_BASENAME],
                        "county_fips": p[F_COUNTY],
                        "population": int(p[F_POP100]),
                        "housing_units": int(p[F_HU100]),
                    }
                )
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


def provenance(file: str) -> dict[str, Any]:
    """The town file's provenance, or {} when there is no file or it is mid-edit."""
    path = RULES / f"{file}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())["provenance"]
    except (ValueError, KeyError):
        return {}


def adu_status(file: str) -> str | None:
    """The town file's adu.status value, or None when there is no file."""
    path = RULES / f"{file}.json"
    if not path.exists():
        return None
    try:
        return ((json.loads(path.read_text()).get("adu") or {}).get("status") or {}).get("value")
    except ValueError:
        return None


def checked_on(file: str) -> str | None:
    return provenance(file).get("verified_on")


def split_parts(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Places split across counties: same name and county subdivision code in another county
    (Bethlehem city has a Northampton and a Lehigh part). Keyed by each part's GEOID."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["geoid"][5:], r["name"]), []).append(r)
    return {r["geoid"]: [o for o in g if o is not r] for g in groups.values() if len(g) > 1 for r in g}


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
    for g, src in EXTRAS.items():  # noqa: F821 (defined below)
        # A town picked as a known ADU ordinance whose code, once read, has no ADU rule says so.
        st = adu_status(files[g])
        lead = f"added as {src}" if src.startswith("batch ") else f"named as a town with an ADU ordinance ({src})"
        why.setdefault(g, []).append(
            lead
            + (
                f". Its code as read has no ADU rule ({st.replace('_', ' ')})"
                if st in ("not_addressed", "prohibited") and "no ADU text" not in src
                else ""
            )
        )
    batch: dict[str, int] = {g: 0 for g in CITY_FILES}
    for b, gs in ASSIGNED.items():
        batch.update({g: b for g in gs})
    rest = [g for g in top + legal + list(EXTRAS) if g not in batch]
    rest = list(dict.fromkeys(rest))
    for i, g in enumerate(rest):
        batch[g] = FIXED_BATCH.get(g, 3 + i // BATCH_SIZE)  # noqa: F821 (defined below)
    order = list(CITY_FILES) + [g for b in sorted(ASSIGNED) for g in ASSIGNED[b]] + rest

    old = {t["geoid"]: t for t in (json.loads(INDEX.read_text())["towns"] if INDEX.exists() else [])}
    parts = split_parts(rows)
    towns = []
    for g in order:
        r, prev, host = by[g], old.get(g, {}), HOSTS.get(g, {})
        file = files[g]
        status = prev.get("status") or (
            "verified" if g in CITY_FILES else "in_progress" if batch[g] in ASSIGNED else "todo"
        )
        if (RULES / f"{file}.json").exists() and status in ("todo", "in_progress"):
            status = "drafted"
        prov = provenance(file)
        aliases = sorted({o["geoid"] for o in parts.get(g, [])} | set(prov.get("geoid_aliases") or []))
        alias_pop = sum(by[a]["population"] for a in aliases if a in by)
        # The town file is checked more recently than the host table, so its provenance wins.
        towns.append(
            {
                "geoid": g,
                "geoid_aliases": aliases,
                "name": r["name"],
                "county": r["county"],
                "type": r["type"],
                "population": r["population"],
                "population_with_aliases": r["population"] + alias_pop,
                "housing_units": r["housing_units"],
                "pop_rank": rank[g],
                "file": file,
                "batch": batch[g],
                "status": status,
                "checked_on": prov.get("verified_on"),
                "code_host": prov.get("code_host") or host.get("code_host", "unknown"),
                "code_url": prov.get("code_url") or host.get("code_url"),
                # Measured once per host. A file whose code_url is not in the host table keeps the value the
                # index already holds, since a rebuild does not fetch anything.
                "plain_fetch": host.get("plain_fetch")
                if not prov.get("code_url") or prov.get("code_url") == host.get("code_url")
                else prev.get("plain_fetch"),
                "code_current_through": prov.get("code_current_through") or host.get("current_through"),
                "code_note": host.get("note"),
                "why": why.get(g, ["already has a rule file"]),
                # Written by town workers, kept across rebuilds (for example the one open point on a drafted file).
                "status_note": prev.get("status_note"),
            }
        )
    return {
        "about": "Pennsylvania towns targeted for ADU rule files, ranked. Made by tools/town_targets.py. "
        "Town workers update only 'status' and 'status_note'. See TOWNS.md.",
        "generated_on": date.today().isoformat(),
        "population_source": {
            "title": "2020 Census Redistricting Data (PL 94-171), Pennsylvania, county subdivisions",
            "url": PL_URL,
            "fields": "POP100 (total population), HU100 (housing units)",
            "pa_population_2020": PA_POP_2020,
        },
        "coverage": coverage(towns),
        "towns": towns,
    }


def coverage(towns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Share of the 2020 PA population in Philadelphia, Pittsburgh and the first n batch towns."""
    cities = [t for t in towns if t["batch"] == 0]
    rest = [t for t in towns if t["batch"] > 0]
    base = sum(t["population_with_aliases"] for t in cities)
    out = []
    for n in (0, 12, 24, 36, 48, 60, len(rest)):
        pop = base + sum(t["population_with_aliases"] for t in rest[:n])
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
            print(
                f"{t['batch']:>2} {t['status']:<11} {t['pop_rank']:>4} {t['name']:<34} {t['county']:<13} "
                f"{t['population']:>9,} {t['code_host']:<10} {t['code_url'] or ''}"
            )
        for c in index["coverage"]:
            print(f"{c['towns_beyond_the_two_cities']:>3} towns + the two cities: {c['share_of_pa']:.1%}")
    print(f"wrote {INDEX.relative_to(ROOT)} with {len(index['towns'])} towns")
    return 0


# ------------------------------------------------------------------ code hosts
# Where each town's zoning code is published, found by web search on 2026-11-11.
# plain_fetch: a plain HTTP GET returns the code text. ecode360, municode and amlegal answer
# plain fetches with a bot challenge (403), so their pages are false. A town worker opens them
# in a browser. current_through: the date the publisher shows, when it could be read.
HOSTS: dict[str, dict[str, Any]] = {
    "4210160000": {
        "code_host": "amlegal",
        "code_url": "https://codelibrary.amlegal.com/codes/philadelphia/latest/philadelphia_pa/0-0-0-292755",
        "plain_fetch": False,
        "current_through": None,
        "note": "Title 14 Zoning. Rule file philadelphia.json, outside the MPC.",
    },
    "4200361000": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/45474194",
        "plain_fetch": False,
        "current_through": None,
        "note": "Title 9 Zoning. Rule file pittsburgh.json, outside the MPC. Ord. 31-2026 (ADUs) not yet folded into eCode360 on 2026-11-10.",
    },
    "4207702000": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/49783893",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 660 Zoning. New zoning code (Zone Allentown) adopted 10-15-2025 by Ord. No. 16166, now Ch. 660 on ecode360 (code AL4161). Old 2010 ordinance PDF (Nov 2015 ed.) on allentownpa.gov is superseded. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened.",
    },
    "4201163624": {
        "code_host": "amlegal",
        "code_url": "https://codelibrary.amlegal.com/codes/readingpa/latest/reading_pa/0-0-0-23864",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 600 Zoning (Zoning Ordinance of 2010). Code on American Legal (readingpa), not ecode360. Node 0-0-0-23864 appeared in search for 'Chapter 600 Zoning' but exact chapter-root node not confirmed (amlegal blocks curl/WebFetch with Cloudflare 403). Search snippets show amendments through 8-24-2026 (Ord. 69-2026), so code is very current. TOD overlay added 6-22-2026.",
    },
    "4204924000": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/ER3969",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Part 13 Zoning Code, Article 1303 Zoning Ordinance. Zoning Ordinance (Ord. 80-2005) codified as Art. 1303 within Part 13 on ecode360 (code ER3969). article pages e.g. https://ecode360.com/44156815 note 'as amended through Ord. No. 15-2023', another page 'through Ord. No. 54-2025, passed 7-16-2025'. Chapter id not confirmed, root URL given. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened.",
    },
    "4204579000": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/33161971",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 550 Zoning (Upper Darby Township Zoning Ordinance of 2010). Code UP3641. 33161971 appears to be the chapter page (33161972 is the short-title section). chapter number 550 from search summary, unverified. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened.",
    },
    "4206969000": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/SC1588/laws/LF2072635.pdf",
        "plain_fetch": True,
        "current_through": None,
        "note": "Zoning: Chapter 445 Zoning (2023 Zoning Ordinance, File of Council #54 2023). New 2023 Zoning Ordinance effective 12-20-2023 is available as a PDF in ecode360 laws (plain curl returns 200 PDF, 5.3MB, text extractable). Codified ecode360 chapter (code SC1588) pages like https://ecode360.com/45088568 appear to be the new code. chapter root id not confirmed. No 'accessory dwelling' text match in the PDF. Date shown: 2023-12-20 (effective date of PDF).",
    },
    "4209144976": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/LO0641",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 155 Zoning. Zoning Code Ch. 155 amended in its entirety 2-26-2020 by Ord. 4181. Code root LO0641 given. chapter id not confirmed. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened.",
    },
    "4201705616": {
        "code_host": "municode",
        "code_url": None,
        "plain_fetch": False,
        "current_through": None,
        "note": "URL slug on Municode not confirmed, so no link is given. Zoning: Chapter 232 Zoning. Bensalem code is on Municode per APA knowledgebase and township 'Township Code of Ordinances' link. exact municode slug NOT confirmed (library.municode.com returns Cloudflare 403 to curl). Zoneomics mirror: https://www.zoneomics.com/code/bensalem-township-PA/chapter_1. UNSURE of URL.",
    },
    "4209100156": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/AB0569",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 162 Zoning. Code AB0569. 2017 comprehensive rezoning Ord. 2136 replaced Ch. 162. amendments through Ord. 2234 (8-14-2025) as ecode360 laws PDFs (e.g. https://ecode360.com/AB0569/laws/LF2693983.pdf). Chapter id not confirmed. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened.",
    },
    "4207141216": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/LA1674",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 300 Zoning. Code LA1674 (City). Do not confuse with Lancaster Township. Chapter id not confirmed (section pages ~ecode360.com/81228xx). ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened.",
    },
    "4209506088": {
        "code_host": "own site",
        "code_url": "https://www.bethlehem-pa.gov/CityOfBethlehem/media/COBfiles/pdf/ordinances/Zoning-Ordinance.pdf",
        "plain_fetch": True,
        "current_through": None,
        "note": "Zoning: Part 13 Zoning Ordinance (Articles 1301-1360). City hosts own PDF (not ecode360). This PDF says 'Last Revised July 17, 2018'. The Zoning Office page links a newer 'Zoning-Ordinance-August-2023.pdf' (https://www.bethlehem-pa.gov/getattachment/Community-Economic-Development/Planning-Zoning/Zoning-Office/Zoning-Ordinance-August-2023.pdf.aspx?lang=en-US) but it returns 404 to curl. Per-article PDFs also at bethlehem-pa.gov/CityOfBethlehem/media/Ordinance-PDFs/ARTICLE-13xx.pdf. No ADU term in 2018 PDF. Date shown: 2018-07-17 (Last Revised, per PDF cover).",
    },
    "4201708768": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/9499447",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 205 Zoning. 9499447 is a zoning-chapter page citing 'Bristol Township Zoning Ordinance' (may be section, not chapter root). Do not confuse with Bristol Borough (Ch. 27 Zoning). ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened.",
    },
    "4204949548": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/MI3114",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 145 Zoning. Code MI3114. Ch. 145 amended and restated 4-28-2022 by Ord. 2022-4. amended by Ord. 2024-6 (https://ecode360.com/MI3114/laws/LF2146675.pdf). Chapter id not confirmed. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened.",
    },
    "4204345056": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/LO1649",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 203 Zoning. Code LO1649. Ch. 203 adopted 7-11-2006 by Ord. 2006-05. Index page showed date 2023-12-05 (possibly last update). Chapter id not confirmed. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4204533144": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/HA0527",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 182 Zoning. Code HA0527. Chapter id not confirmed (section pages ~ecode360.com/12187xxx, 12435xxx). ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4204332800": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/32584380",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Title 7 Planning and Zoning Code, Part 3 Zoning Code (Ch. 7-301 to 7-333). ADU text seen: accessory dwelling (defined in Ch. 7-333 Definitions, ecode360.com/32586534). Zoning Code adopted 7-8-2014 by Ord. 5-2014. 32584380 = Ch. 7-301 Title/Purpose (closest to Part 3 root). TOC at https://ecode360.com/26959081. Chapter pages: 7-303=32584259, 7-305=32584223, 7-307=32584129, 7-321=32585393, 7-323=32586321, 7-327=32586102, 7-333=32586534 (ids from earlier saved pages in scratchpad). ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4201749120": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/MI2390",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 500 Zoning. Code MI2390 (index page showed sections 500-2903, 500-3211. date stamp 2023-11-13). One search summary claimed a renumbered Ch. 275 and code MI1283 - likely a different Middletown. UNSURE which code id is Bucks County. Zoneomics mirror: https://www.zoneomics.com/code/middletown-township-bucks-PA/chapter_1. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4213387048": {
        "code_host": "amlegal",
        "code_url": "https://codelibrary.amlegal.com/codes/yorkpa/latest/york_pa",
        "plain_fetch": False,
        "current_through": "2024-01-01",
        "note": "Zoning: Part 13 Planning and Zoning Code (Arts. 1301-1379). Code root on American Legal (yorkpa). amlegal returns Cloudflare 403 to curl. City also links zoning sections 1301-1379 from https://www.yorkcity.org/york-city-codified-ordinances/ (per-article PDFs on yorkcity.org). Zoning chapter node not confirmed.",
    },
    "4207985152": {
        "code_host": "zoneomics",
        "code_url": "https://www.zoneomics.com/code/wilkes-barre-PA/chapter_1",
        "plain_fetch": True,
        "current_through": None,
        "note": "Zoning: City of Wilkes-Barre Zoning Ordinance (File of Council No. 18 of 2012). No official online code confirmed. City page 'Zoning Ordinances & Zoning Map' (https://www.wilkes-barre.city/node/156) appears in search but returns 404 to curl. ecode360 hits for 'Wilkes-Barre' were other Luzerne municipalities (Kingston KI0963 etc). Zoneomics plain fetch 200 with zoning text. UNSURE - official source missing.",
    },
    "4207146896": {
        "code_host": "own site",
        "code_url": "https://manheimtownship.org/DocumentCenter/View/8076/2-Ordinance-Updates",
        "plain_fetch": True,
        "current_through": None,
        "note": "Zoning: Zoning Ordinance of Manheim Township 2014 (ecode360 Ch. 500 Zoning). Township says codified code excludes the zoning ordinance. current amended text lives in township Document Center as per-article PDFs (e.g. https://manheimtownship.org/DocumentCenter/View/3110/4ARTICLE-1-Title-Purpose). View/8076 is only the revision list (57KB PDF). ecode360 Ch. 500 page https://ecode360.com/14976733 (code MA2385) is stale - amended only through Ord. 2014-21 (11-10-2014). Date shown: 2024-01-22 (latest revision listed: Ord. 2024-01, per search summary).",
    },
    "4201302184": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/32046318",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 800 Zoning. 32046318 appeared in search for 'Chapter 800 Zoning' Altoona but may be a section, not chapter root. ecode360 code id not seen. A section references permits filed before 9-8-2025 so chapter recently amended. Zoneomics mirror https://www.zoneomics.com/code/altoona-PA/chapter_1. UNSURE of chapter id. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4212933792": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/HE0496",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Hempfield Township Zoning Ordinance of 2014 (chapter number unconfirmed. 1978 ord. was Ch. 87). Code HE0496. 2014 ordinance repealed 1978 ordinance. chapter number for 2014 code not confirmed. Zoning map amendments 2023 as laws PDFs (e.g. https://www.ecode360.com/HE0496/laws/LF2044516.pdf). Do not confuse with Hempfield Twp, Lancaster Co. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4200359032": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/37763696",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Part 12 Planning and Zoning Code, Title 6 Zoning (Chapters 1260-1288). Penn Hills codified ordinances are on ecode360 (code id not seen). 37763696 is a Penn Hills ecode360 page from search, not confirmed as zoning root. Zoning amended 10-21-2024 (Ord. 2024-2705) and 11-18-2024 (Ord. 2024-2707) per Zoneomics mirror https://www.zoneomics.com/code/penn-hills-township-PA. UNSURE of URL. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4202773808": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/ST2624",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter XIX Zoning. Code ST2624. Sections numbered 19-xxx / XIX-xxx. Chapter id not confirmed. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4201754688": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/NO0896",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 27 Zoning. Code NO0896 (Pennsylvania-style numbering, Ch. 27). Page showed date 2024-04-17. Chapter id not confirmed. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4209112968": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/33235830",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 295 Zoning (Cheltenham Township Zoning Ordinance of 2017). Code CH1316. 33235830 precedes 33235831 (title section 'Cheltenham Township Zoning Ordinance'), likely chapter/article root but not confirmed. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4209154656": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/NO0820",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 320 Zoning. Code NO0820 (Municipality of Norristown). Mixed-Use Overlay added 5-21-2025 by Ord. 25-03 (https://ecode360.com/49334564). Chapter id not confirmed. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4201725112": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/FA0549",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 209 Zoning. Code FA0549. Chapter id not confirmed (sections ~ecode360.com/71050xx-71270xx). ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened.",
    },
    "4200351696": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/42261300",
        "plain_fetch": False,
        "current_through": "2026-02-10",
        "note": "Zoning: Chapter 20 Zoning. ecode360 code MO6716. Search for \"accessory dwelling\" in this code returned 0 results. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4209179136": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11658450",
        "plain_fetch": False,
        "current_through": "2026-03-12",
        "note": "Zoning: Chapter 165 Zoning. ecode360 code UP0975. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4201780952": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/14238962",
        "plain_fetch": False,
        "current_through": "2026-04-09",
        "note": "Zoning: Chapter 27 Zoning. ecode360 code WA2486. Zoning rewritten by Ord. 762 (5/7/2020). Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4200306064": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/29463304",
        "plain_fetch": False,
        "current_through": "2025-09-08",
        "note": "Zoning: Chapter 69 Zoning. ecode360 code BE0278. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4200366264": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/30842452",
        "plain_fetch": False,
        "current_through": "2026-04-20",
        "note": "Zoning: Chapter 27 Zoning (Planning and Zoning Code). ecode360 code RO2521. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4204563264": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11078356",
        "plain_fetch": False,
        "current_through": "2026-09-28",
        "note": "Zoning: Chapter 280 Zoning. ecode360 code RA0484. Chapter id taken from the page breadcrumb. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4201744968": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11226088",
        "plain_fetch": False,
        "current_through": "2025-12-17",
        "note": "Zoning: Chapter 200 Zoning. ecode360 code LO1561. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4201916920": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/34273101",
        "plain_fetch": False,
        "current_through": "2025-06-05",
        "note": "Zoning: Chapter 27 Zoning. ecode360 code CR0448. Later amendments (e.g. Ord. 2025-520) are posted on agenda.cranberrytownship.org and may not be codified yet. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4204132296": {
        "code_host": "municode",
        "code_url": "https://library.municode.com/pa/hampden_township/codes/code_of_ordinances?nodeId=CH27ZO",
        "plain_fetch": False,
        "current_through": "2026-07-02",
        "note": "Zoning: Chapter 27 Zoning. The township site (hampdentownship.us) links to the Municode library. Plain curl gets a 403 Cloudflare challenge, so the data was read in a browser. Zoneomics has a mirror.",
    },
    "4204513208": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/45941765",
        "plain_fetch": False,
        "current_through": "2026-08-12",
        "note": "Zoning: Chapter 550 Zoning. ecode360 code CH6779. Adopted 9-9-2015 by Ord. 5-2015. Chester code is CH6779, not CH2012. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4207744952": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/30829060",
        "plain_fetch": False,
        "current_through": "2026-05-21",
        "note": "Zoning: Chapter 27 Zoning. ecode360 code LO1244. Zoning Ordinance of 2019 (Ord. 2019-10). Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4202977344": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/7115532",
        "plain_fetch": False,
        "current_through": "2026-09-21",
        "note": "Zoning: Chapter 208 Zoning. ecode360 code TR1485. Chapter id taken from the page breadcrumb. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4212955128": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/16043696",
        "plain_fetch": False,
        "current_through": "2026-01-21",
        "note": "Zoning: Chapter 555 Zoning. ecode360 code NO0456. Code recodified 2024 (Ord. 2296). Chapter 156 is Airport Zoning, a separate chapter. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4204564800": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/8799872",
        "plain_fetch": False,
        "current_through": "2026-02-25",
        "note": "Zoning: Chapter 325 Zoning. ecode360 code RI0534. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4207933408": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/37222224",
        "plain_fetch": False,
        "current_through": "2026-08-25",
        "note": "Zoning: Chapter 575 Zoning. ecode360 code HA1359. Hazleton City Zoning Ordinance of 2021 (Ord. 2021-9). An old 1995 scanned PDF at hazletoncity.org/images/Hazleton-Zoning-Ordinance.pdf is superseded. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4213387056": {
        "code_host": "own site",
        "code_url": "https://yorktownshippa.gov/wp-content/uploads/Zoning-Ordinance-last-amendment-3-14-23.pdf",
        "plain_fetch": True,
        "current_through": None,
        "note": "Zoning: Zoning Ordinance (Ord. 2012-13), sections numbered 265-xxx. ADU text seen: No ADU term found. Related: Conversion Apartments 265-624. Accessory Farm Dwelling 265-603. Apartment/residence with commercial use 265-608. Not on ecode360. The PDF is 193 pages, text-extractable, and lists on the Ordinances & Studies page (yorktownshippa.gov/?p=20017). Not the City of York. Date shown: Amendments through Ord. 2023-01 (3/14/2023). zoning map amended 8/13/2024.",
    },
    "4200345900": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/37748731",
        "plain_fetch": False,
        "current_through": "2025-09-08",
        "note": "Zoning: Part 13 Zoning (Zoning Code, Ord. 1540, 6-26-2023). ecode360 code MC4162. Now styled 'Town of McCandless'. Codified ordinances use Part/section numbering (e.g. 1301.260). Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4207784528": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/13159599",
        "plain_fetch": False,
        "current_through": "2026-02-26",
        "note": "Zoning: Chapter 27 Zoning. ecode360 code WH2503. Not South Whitehall or North Whitehall. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4200350528": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11510889",
        "plain_fetch": False,
        "current_through": "2026-06-09",
        "note": "Zoning: Chapter 359 Zoning. ecode360 code MO1197. UNSURE IF CURRENT: older ecode360 snippets show the 1984 ordinance (Ord. 1443). Zoneomics mirrors a new ordinance effective 11-14-2023. Confirm the ecode360 Ch 359 reflects the 2023 rewrite. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4201172824": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/45165330",
        "plain_fetch": False,
        "current_through": "2026-03-23",
        "note": "Zoning: Chapter 450 Zoning. ecode360 code SP6788. Zoning Ordinance of 2015 (Ord. 415). Chapter 453 is Airport Zoning. Zoneomics carries an older 2007 Ch 27 version (ignore). Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4200369584": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/9196870",
        "plain_fetch": False,
        "current_through": "2025-06-10",
        "note": "Zoning: Chapter 225 Zoning. ecode360 code SH1304. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4209521648": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/9647638",
        "plain_fetch": False,
        "current_through": "2026-09-23",
        "note": "Zoning: Chapter 595 Zoning (Easton Zoning Code). ecode360 code EA2741. Zoning map is on easton-pa.zoninghub.com. Proposed amendments (1-23-2025) are on easton-pa.com. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4204375672": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11636509",
        "plain_fetch": False,
        "current_through": "2026-08-12",
        "note": "Zoning: Chapter 295 Zoning (Zoning Ordinance of 2010). ecode360 code SW2044. Use code SW2044 (Dauphin). SW2746 is Swatara Twp, Lebanon County: do not confuse. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4208185312": {
        "code_host": "amlegal",
        "code_url": "https://codelibrary.amlegal.com/codes/williamsport/latest/williamsport_pa/0-0-0-5800",
        "plain_fetch": False,
        "current_through": "2026-05-28",
        "note": "Zoning: Part Thirteen: Planning and Zoning Code (zoning chapters 13xx, e.g. 1311.63). Plain curl gets HTTP 403 from amlegal. Art. 355 Residential was re-enacted by Ord. 6510 (city document center). An ecode360 WI3701 code also exists but may be another Williamsport (not verified). amlegal is the city's current host.",
    },
    "4200350784": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/30859895",
        "plain_fetch": False,
        "current_through": "2024-05-29",
        "note": "Zoning: Chapter 27 Zoning. ecode360 code MO1356. ecode360 has not been updated since 2024. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4200361536": {
        "code_host": "own site",
        "code_url": "https://www.plumboro.com/sites/g/files/vyhlif3686/f/pages/zoning_ordinance_w-_amendments_2023_0.pdf",
        "plain_fetch": True,
        "current_through": None,
        "note": "Zoning: Plum Borough Zoning Ordinance (with amendments, 2023). ADU text seen: Accessory Dwelling Unit (attached. also 'Mother-in-law Suites'), Section 406. No ecode360, municode or amlegal code found. Linked from plumboro.com/community-development/pages/planning-and-zoning-ordinances. The PDF is 253 pages and text-extractable. Date shown: PDF titled 'with amendments 2023'.",
    },
    "4213372992": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/5176819",
        "plain_fetch": False,
        "current_through": "2026-06-25",
        "note": "Zoning: Chapter 325 Zoning. ecode360 code SP2128. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session.",
    },
    "4207542168": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/LE3707",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Part Thirteen (Planning and Zoning Code), Zoning Ordinance of 2020 (Ord. 1-2020, passed 6-22-2020). conditional uses ref 1314.17. Code root LE3707 seen in ecode360 index URL (ecode360.com/index/LE3707/M). Zoning sections seen at https://ecode360.com/36369818 and https://ecode360.com/36363477 (Ord. 1-2020). Plain curl returns 403 (ecode360 bot block). WebFetch also 403.",
    },
    "4204375528": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/SU2468",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 27 Zoning (Zoning Map 27-301). Code root from ecode360.com/index/SU2468/C. Search tool described https://ecode360.com/28271833 as zoning ordinance opening sections (not independently verified as chapter id). Zoneomics mirror at zoneomics.com/code/susquehanna-township-PA. ecode360 returns 403 to plain curl.",
    },
    "4209179008": {
        "code_host": "amlegal",
        "code_url": "https://codelibrary.amlegal.com/codes/upperdublin/latest/upperdublintwp_pa",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 255 Zoning (Upper Dublin Township Zoning Ordinance of 1956). Township site points to American Legal Publishing. URL is code root (zoning chapter node id not seen). amlegal returns 403 to plain curl. Zoneomics mirror (zoneomics.com/code/upper-dublin-township-PA) shows amendment dated 12-9-2025. A snippet suggested 'supplements through 1-8-2008' but that is probably an old header. currency unconfirmed.",
    },
    "4209135808": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/HO1764",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 230 Zoning (Horsham Township Zoning Ordinance of 1995). Code id HO1764 seen in index URLs (ecode360.com/index/HO1764/G). Zoning short-title section at https://ecode360.com/9953287. 230-17 allows conversion of single-family dwelling to more families by special exception (not an ADU per se). ecode360 403 to plain curl.",
    },
    "4202984160": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/WE3779",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 390 Zoning (TDR article 390-196). 2021 codification Ch 1-390. ADU text seen: Search snippet indicated zoning chapter covers accessory dwelling units (section not seen) - unverified. Code id WE3779 from ecode360 help/about URL. ecode360 403 to plain curl.",
    },
    "4202984104": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/WE1870",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 170 Zoning (170-100 to 170-2504). ecode360 New Laws lists Ord. 2026-02 amending Ch 170 (dated 2026-06-01), so code is recently maintained. ecode360 403 to plain curl.",
    },
    "4202946792": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/MA0856",
        "plain_fetch": False,
        "current_through": "2023-12-19",
        "note": "Zoning: Zoning Ordinance of 2003 (chapter number unclear: older 220 numbering vs. later 27 citations). Zoning short title pages at https://ecode360.com/31445090. Chapter number ambiguous. verify in TOC. ecode360 403 to plain curl.",
    },
    "4202920864": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/EA1968",
        "plain_fetch": False,
        "current_through": "2023-02-16",
        "note": "Zoning: Chapter 399 Zoning (Zoning Ordinance of 1989). Code id from ecode360.com/index/EA1968. Short-title section https://ecode360.com/11881522. ecode360 403 to plain curl.",
    },
    "4202982704": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/WE0442",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 112 Zoning (Borough of West Chester Zoning Ordinance of 2021). Code id from ecode360.com/index/WE0442/D. Zoning intro/short title at https://ecode360.com/6471984 and https://ecode360.com/6471994. ecode360 403 to plain curl.",
    },
    "4202715136": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/CO1052",
        "plain_fetch": False,
        "current_through": "2023-10-19",
        "note": "Zoning: Chapter 200 Zoning (College Township Zoning Ordinance). Code id from ecode360.com/CO1052/index. Zoning short-title section https://ecode360.com/10705478. ecode360 403 to plain curl.",
    },
    "4207158840": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/30832287",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 27 Zoning (Ord. 2022-01, 1/10/2022 per Zoneomics). Penn Twp (Manheim, penntwplanco.org) links to eCode. code root PE3692 cited in township's proposed-changes PDF. search identified 30832287 as Chapter 27 page (moderate confidence). ecode360 403 to plain curl.",
    },
    "4201719784": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/DO1641",
        "plain_fetch": False,
        "current_through": "2026-04-20",
        "note": "Zoning: Chapter 27 Zoning (Doylestown Borough Zoning Ordinance of 1985). use table 27-406. Ord. 2024-5 amended 27-406/27-906. ecode360 403 to plain curl.",
    },
    "4202935536": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/HO3693",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 27 Zoning (Ord. 196-2018, 9/12/2018). ADU text seen: accessory dwelling unit (freestanding or attached) - 27-1002 Accessory Dwelling Units [Ord. 196-2018. Ord. 211-2025, 7/9/2025] in Part 10 specific use criteria: min 2-acre gross lot, max 1 ADU per property, min 400 sf, Health Dept sewer/water approval, 2 parking spaces/unit, STR must meet 27-1065. Approval: permitted where the district allows the use, via zoning/building permit (district-level path not confirmed). Text read at https://www.zoneomics.com/code/honey-brook-township-PA/chapter_10 (mirror of ecode360 text). CONFIRMED ADU text. Lead said 27-207 - actual standards are 27-1002 (27-207 may be a district use list. not",
    },
    "4207143816": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/LI0684",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 122 Zoning. not confirmed. Only evidence: cpo.soar.com summary (12/31/2025) of Ordinance C622 saying staff stated ADUs will be allowed by right in all districts subject to former special-exception standards - a news summary, not code text. Could not retrieve Chapter 122 ADU text (ecode360 403. Zoneomics Lititz pages are empty shells). Ord. 1498-25 (12/8/2025) ADU hits on ecode360 are GETTYSBURG, not Lititz. Likely real but needs manual check of ecode360 Ch 122.",
    },
    "4209152664": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/NA0447",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 500 Zoning (form-based. TOC page https://ecode360.com/34400015). ADU text seen: accessory dwelling unit - definition 500-1201 (added 4-21-2022 by Ord. 1043: self-contained unit within a detached accessory structure) and standards in 500-602 Accessory buildings [Amended 4-21-2022 by Ord. 1043]: A(2) 'A residence or dwelling shall be permitted as an accessory dwelling unit', C 'Specific to accessory dwelling units' (only on lot with detached house or twin, max 1 per lot, max 2 units combined, may share building with garage, no extra lot area). Approval: appears permitted (by right) as accessory use. conditional use referenced only for historic contributing-resource case. Seen a",
    },
    "4204548480": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/ME1269",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 311 Zoning, Article B Hybrid Form-Based Code (applies to R-1..R-4, Office). ADU text seen: accessory dwelling unit (ADU) - definition in 311.A-13 and Article B-XV Accessory Dwelling Units starting 311.B-107 (Purpose and intent). TOC also lists 'Building Form - ADU External'. Approval path not seen. Seen in Zoneomics mirror TOC/definitions https://www.zoneomics.com/code/media-PA/chapter_1 and ecode360 TOC via search. CONFIRMED ADU article exists (definition + Article B-XV heading read). standards text of B-107+ not read. An older ecode360 page with 'supplemental dwelling unit/accessory apartment' (35% / 400 sf) may be pre-form-based text. ecode360 403 to plain curl.",
    },
    "4202960120": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/47635361",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 27 Zoning (Ord. 2227, 12-10-2013, as amended). ADU text seen: accessory dwelling unit (ADU) - definition added by Ord. 2025-2410 (8/12/2025) (within, attached to, or in accessory building on lot of single-family dwelling). special exception use in RI, TC, MI, NC, CD districts per special-exception use table, with standards '(d) Accessory Dwelling Unit (ADU)': one ADU accessory to single-family detached, twin or townhouse. owner occupancy in perpetuity. parking 1 space. Approval: SPECIAL EXCEPTION. Seen at https://ecode360.com/47635361 (definition, search) and https://www.zoneomics.com/code/phoenixville-PA/chapter_3. CONFIRMED ADU text. code_url is the definitions section page",
    },
    "4202725624": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/FE3697",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 27 Zoning (Ord. 1049, 11/18/2019. amended incl. Ord. 1097, 4/16/2024). ADU text seen: accessory dwelling unit - definition in Part 11 (occupied by relatives of owner or caregivers/household staff) plus 'Elder cottage/in-law quarters/carriage house (accessory dwelling unit)' definition (min 600 sf, not counted toward density). ecode360 TOC lists 27-1503 Accessory Dwelling (Part 15 Accessory Uses). Approval path not seen. Definitions read at https://www.zoneomics.com/code/ferguson-township-centre-county-PA/chapter_10. 27-1503 from ecode360 TOC via search (https://www.ecode360.com/32480896). CONFIRMED ADU text (definitions read. 27-1503 heading via search only, body not read). C",
    },
    "4202758440": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/42483863",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Zoning ordinance (Chapter number unclear. one search summary said Chapter 425 - unverified). not confirmed. Searches and a grep of Zoneomics mirror chapters 1-30 (zoneomics.com/code/patton-township-PA) found no accessory dwelling/apartment/in-law/elder cottage text. 42483863 described by search as Patton zoning ordinance page. code root id ambiguous (PA1294 index appeared in Patton results). ecode360 403 to plain curl.",
    },
    "4204575648": {
        "code_host": "amlegal",
        "code_url": "https://codelibrary.amlegal.com/codes/swarthmore/latest/swarthm_pa/0-0-0-23482",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Part Twelve Planning and Zoning Code - Zoning Code (sections 12xx. family/caregiver suite 1264.18). ADU text seen: family/caregiver suite (in-law suite type, internal only) - 1264.18 per Zoneomics cross-ref. allowed by SPECIAL EXCEPTION in all zoning districts. 1 per dwelling. max 35% of combined floor area. may not be in an accessory structure. annual filing of occupant name/relationship. Adopted 2018. Seen at https://codelibrary.amlegal.com/codes/swarthmore/latest/swarthm_pa/0-0-0-23482 (search snippet). CONFIRMED in-law-suite text (not a general ADU. detached units prohibited). Section number 1264.18 from Zoneomics cross-reference, unverified on amlegal. code_url is the section pa",
    },
    "4202939352": {
        "code_host": "zoneomics",
        "code_url": "https://www.zoneomics.com/code/kennett-square-PA/chapter_3",
        "plain_fetch": True,
        "current_through": None,
        "note": "Zoning: Chapter 23 Zoning (Zoning Ordinance of the Borough of Kennett Square. Ord. 761). ADU text seen: accessory dwelling unit (detached, in accessory building) and accessory apartment (within principal dwelling) - definitions in Ch 23 Art. II. 23-30 Accessory uses: '(A) Accessory Habitation: (i) an accessory apartment as an accessory use. (ii) an accessory dwelling unit (limited to one per property)' allowed as accessory uses to residential uses. detached ADU max 25 ft height, 6 ft side/rear setbacks, max 1,000 sf living space and 2 bedrooms, not subdividable. parking 1 space/bedroom (max 2). Approval: allowed accessory use (by right as listed). Seen at https://www.zoneomics.com/code/kenne",
    },
    "4209138000": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/JE0687",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Zoning chapter (Jenkintown Zoning Ordinance of 1941 as revised. amended code adopted 9-13-2010). short-title page https://ecode360.com/11184146. not confirmed. Searches found no Jenkintown ADU section. grep of Zoneomics mirror chapters 1-30 found no accessory dwelling/apartment/in-law text. Unattributed ecode360 ADU snippets ('one ADU per lot, rear yard only') are from another municipality. Borough site also has jenkintownboro.com/zoning-code. ecode360 403 to plain curl.",
    },
    "4209102264": {
        "code_host": "own site",
        "code_url": "https://boroughofambler.com/download/code_of_ordinances/code-of-ordinances-by-chapter/Chapter27.pdf",
        "plain_fetch": True,
        "current_through": None,
        "note": "Zoning: Chapter 27 Zoning. ADU text seen: accessory dwelling units (ADUs), detached and attached - definition in 27-202 and 27-407 Accessory Uses: A(8) ADUs listed as use accessory to a dwelling. C 'Additional Requirements for Accessory Dwelling Units': max 1 per property, occupied only when owner's family lives in principal dwelling and by specified relatives, no rental. not a mobile home. Approval: permitted accessory use (zoning permit), family-occupancy restricted. Read in PDF at https://boroughofambler.com/download/code_of_ordinances/code-of-ordinances-by-chapter/Chapter27.pdf. CONFIRMED ADU text (family-only ADU). PDF 269 pages, 858 KB, plain curl 200 with text. Borough also on ecode36",
    },
    "4200134424": {
        "code_host": "own site",
        "code_url": "https://highland.adamscountypa.gov/getmedia/f6af9e19-a9a2-4645-9034-a9cde6880d9e/Highland-Township-Zoning-Ordinance-of-2025-Final-Compiled-v3.pdf",
        "plain_fetch": True,
        "current_through": None,
        "note": "Zoning: Highland Township Zoning Ordinance of 2025 (standalone). ADU text seen: Accessory Dwelling Unit - definition (Art. 2). permitted accessory use in every district (e.g. 505.A 'Accessory Dwelling Unit, in accordance with Section 1502.H.1'. use table shows P in all districts). standards 1502.H.1 (p.177): max 2 occupants who are relatives of principal residents, at least one needing care for illness/age/disability. must be reconvertible. recorded legal mechanism. attached unless detached specifically approved, detached removed within 90 days. Approval: PERMITTED (by right) accessory use, family/care-restricted (ECHO-style). Read in PDF. CONFIRMED ADU text. PDF labelled 'Final Draft - Octo",
    },
    "4201719792": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/DO1312",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 175 Zoning (adopted 10-11-1988). chapter page likely https://ecode360.com/10729898. ADU text seen: accessory dwelling unit (formerly 'accessory family apartment') - use H(12) in 175-16 (added 5-4-1993 Ord. 224. amended 2-16-2021 Ord. 401. renamed/amended apparently 2026): 1 per single-family detached, max 25% of floor area, within principal residence or existing accessory structure (e.g. garage), +1 parking space, max 2 occupants, registration with Zoning Officer, deed restriction, Bucks County Board of Health sewage certification. Approval: SPECIAL EXCEPTION in R-1 per 175-37 (cited in 2024 ZHB decision). Text read at https://www.zoneomics.com/code/doylestown-township-PA/cha",
    },
    "4207115384": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/CO0213",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 220 Zoning (220-31 Additional requirements for accessory uses). not confirmed. Code appears to prohibit apartments/living quarters in accessory structures (snippet, Amended 4-14-2025 by Ord. No. 603 - but Ord. 603 attribution to Columbia is uncertain). April 2026 council approved DCED technical assistance to evaluate ADUs (cpo.soar.com summary) - proposal only. Zoneomics mirror chapters 1-30 grep found no ADU/accessory apartment text.",
    },
    "4207779104": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/14515564",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 27 Zoning (Ord. 9-94). ADU text: 'Accessory apartment, one' within an existing single-family detached house or twin half (27-306, 27-403.4A), special exception in R3, R4, R5 and by right in NC, HC, LI, LI(L), GI. Separate 'apartment for care of relative' by special exception in all residential districts (27-403.4C). Read in the browser on eCode360 (UP2477).",
    },
    "4207121232": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/14043769",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 270 Zoning (East Hempfield Township Zoning Ordinance of 2014). ADU text: 'accessory dwelling' (270-2.2) and 270-5.2A, permitted accessory use in A, RB, RL, RM, VR, VC, CBC, AH, RCC since Ord. No. 2022-02; immediate family only, 40% of the house, owner residency, +1 parking. Read in the browser on eCode360 (EA2319).",
    },
    "4209506096": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/13370636",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 275 Zoning (Ord. No. 8-97). ADU text: 'Accessory apartment within an existing single-family detached dwelling' (275-190D(1)), accessory use by right in MDR (275-46B(6)) and MHDR (275-54B(6)); conversion rules 275-189A(24). Read in the browser on eCode360 (BE2269), legislation through 06-15-2026.",
    },
    "4201781048": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/32025905",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 370 Zoning (Ord. No. 2021-O-04). ADU text: 'H1, Multigenerational apartment' (370-305H(1)), special exception in RA, R1, R2, R2-I, R3, MR, EV (Table 300): relatives of the owner, no rent, inside the house, lesser of 25% or 800 sq ft, public water and sewer. 370-820 limits secondary kitchens (Ord. No. 2026-O-01). Read in the browser on eCode360 (WA0807), legislation through 08-11-2026.",
    },
    "4209145080": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/6205724",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 143 Zoning (Ord. No. 432). ADU text: 'In-law suite' (143-6.2, Ord. No. 662, 2020; amended Ord. No. 687, 2025), residential accessory use by right in R-1 to R-5: inside the house or a detached household garage, two family members, 800 sq ft cap. Read in the browser on eCode360 (LO0679).",
    },
    "4209150640": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11516266",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 230 Zoning (readopted 2007 by Ord. No. 06-211Z). ADU text: 'Accessory family dwelling' (230-149C): one unit with a single-family detached house for family members or a family caregiver, part of the house with an internal connection, 25% of floor area, no rental, registration, +1 parking. Read in the browser on eCode360 (MO1293).",
    },
    "4201124384": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/8337502",
        "plain_fetch": False,
        "current_through": "2026-04-13",
        "note": "Zoning: Chapter 390 Zoning (Exeter Township Zoning Ordinance of 2010, Ord. No. 700). No ADU text: searches for accessory dwelling, accessory apartment, in-law and ECHO find nothing. Two-family detached by right in SR3 and UR. Ord. No. 881 (2026-06-22, zoning) not yet codified. Read in the browser on eCode360 (EX2329).",
    },
    "4204573032": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/30536824",
        "plain_fetch": False,
        "current_through": "2026-06-09",
        "note": "Zoning: Chapter 143 Zoning (Ord. No. 1504, 2010). No ADU text and no two-family listing in any district. Ord. No. 1651 (2025) and Ord. No. 1660 (2026) zoning amendments listed as new laws. Read in the browser on eCode360 (SP0159).",
    },
    "4209179256": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/42975244",
        "plain_fetch": False,
        "current_through": "2025-10-28",
        "note": "Zoning: Chapter 300 Zoning (Ord. No. 180, recodified 2024). ADU text: 'Temporary unit for relative (in-law suite)' (300-15B(4), Ord. No. 517, 2011): accessory use to a single-family dwelling, inside the house, owner-occupied, immediate family, recorded covenant. Ord. No. 619 and 623 (2026, zoning) not yet codified. Read in the browser on eCode360 (UP1236).",
    },
    "4204178736": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/8577949",
        "plain_fetch": False,
        "current_through": "2025-12-17",
        "note": "Zoning: Chapter 245 Zoning (Ord. No. 771, 2017). ADU text: 'Accessory apartment' (245-2.1, 245-14.3, Ord. No. 844, 2025): by right in R-3, special exception in A, R-1, R-2, C-1, INS; detached or attached; 300 sq ft to 45% of the house; owner-occupied; 3 parking spaces. Read in the browser on eCode360 (UP1380).",
    },
    "4213319704": {
        "code_host": "amlegal",
        "code_url": "https://codelibrary.amlegal.com/codes/dovertwp/latest/dovertwp_pa/0-0-0-24543",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Chapter 27 Zoning (Ord. No. 2024-01, 5-13-2024). ADU text: 'Accessory apartment' (27-202, 27-602) by right in R-1, R-3, R-4, CV, CRV, A, V, part of the principal structure; 'Accessory family dwelling unit' (27-603) for relatives with a medical hardship, detached portable unit up to 900 sq ft. Read in the browser on American Legal (2026 S-10).",
    },
    "4202983080": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/10796167",
        "plain_fetch": False,
        "current_through": "2026-09-01",
        "note": "Zoning: Chapter 84 Zoning (adopted 1972, as amended). ADU text: 'In-law suite' (84-8, 84-57.25, Ord. No. 5-2016): accessory use by right in R-2, R-3 and R-4 only, for a relative of the residents, at most two occupants, inside the house or an existing accessory structure, 35% of the house plus suite, recorded no-rent agreement. Read in the browser on eCode360 (WE0457).",
    },
    "4205512536": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/10696328",
        "plain_fetch": False,
        "current_through": "2026-09-28",
        "note": "Zoning: Chapter 300 Zoning (Ord. No. 82-7, 1982). No ADU text. Two-family dwellings by right in LDR and MDR (and DCN, DCH, Central Core, Professional Office); conversion apartments by special exception (300-135). Read in the browser on eCode360 (CH1151).",
    },
    "4212559608": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/32749579",
        "plain_fetch": False,
        "current_through": "2026-01-05",
        "note": "Zoning: Chapter 440 Zoning (Ord. No. 820, 2017). No ADU text. Duplexes count as single-family attached dwellings (440-301), permitted in MD, VR and mixed-use districts. Ord. No. 925, 928 and 929 (2026, zoning) not yet codified. Read in the browser on eCode360 (PE3557).",
    },
    "4204111272": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/10683915",
        "plain_fetch": False,
        "current_through": "2026-06-03",
        "note": "Zoning: Chapter 255 Zoning (Ord. No. 1993, 2003). No ADU text; 'No dwelling units shall be permitted within a detached garage' (255-200D(12)(b)[7]). Two-family detached by right in R-3, R-4 and UM. Read in the browser on eCode360 (CA1126).",
    },
    "4209143312": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11206587",
        "plain_fetch": False,
        "current_through": "2026-03-03",
        "note": "Zoning: Chapter 184 Zoning (Ord. No. 146, 1992, readopted 2006). ADU text: 'Temporary unit for relative' (184-10, 184-71B(6)): accessory to a single-family dwelling, inside the house, owner-occupied, immediate family, recorded covenant, annual permit, detached units prohibited. Ord. No. 438 (2026, zoning) not yet codified. Read in the browser on eCode360 (LI1176).",
    },
    "4204144832": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11213000",
        "plain_fetch": False,
        "current_through": "2025-01-27",
        "note": "Zoning: Chapter 220 Zoning (Ord. No. 2009-2). ADU text: 'Accessory dwelling' (220-149): permitted use in R-1, R-2 and MUN (and TND and NR overlays), in an owner-occupied single-family detached dwelling, at most 30% of the floor area, at least 360 sq ft, additions limited to 10%. Read in the browser on eCode360 (LO1571).",
    },
    "4209173088": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11823514",
        "plain_fetch": False,
        "current_through": "2026-05-13",
        "note": "Zoning: Chapter 114 Zoning (Ord. No. 487, 1962). No general ADU text. 'Accessory apartment' only for a historic resource in the Historic Resource Overlay District (114-12D4B(10), Ord. No. 962, 2019): special exception, in a contributing accessory structure, owner on the premises. Two-family dwellings by right in C and D; conversion by special exception in AA, A and B (114-133A). Read in the browser on eCode360 (SP0463).",
    },
    "4209133120": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/10506475",
        "plain_fetch": False,
        "current_through": "2025-12-17",
        "note": "Zoning: Chapter 282 Zoning (Ord. No. 420, 1994, readopted 2008). No ADU section. The family definition (282-6, D) allows relatives as two housekeeping units in a detached single-family dwelling, connected internally, one unit with the owner, the other at most two members with one aged 60 or more, one unit at most 600 sq ft, recorded agreement. Read in the browser on eCode360 (HA2083).",
    },
    "4202984192": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11701933",
        "plain_fetch": False,
        "current_through": "2026-08-26",
        "note": "Zoning: Chapter 325 Zoning. No ADU text. Two-family (duplex, twin) by right in R-3 and R-4; conversion of a single-family dwelling by conditional use in R-3 (325-25). Ord. No. 492 (2026, zoning) not yet codified. Read in the browser on eCode360 (WE2141).",
    },
    "4212958880": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/9968279",
        "plain_fetch": False,
        "current_through": "2025-05-21",
        "note": "Zoning: Chapter 190 Zoning (Ord. No. 912-2016). ADU-like text: 'Conversion apartment' (a dwelling unit created within an existing single-family dwelling, 190-202) permitted in CC and IC only (190-405, 190-406); the multifamily definition also names conversion apartments. Duplex by right in MDR. Ord. No. 973-2025 (zoning) not yet codified. Read in the browser on eCode360 (PE1662).",
    },
    "4212952432": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11539206",
        "plain_fetch": False,
        "current_through": "2026-05-20",
        "note": "Zoning: Chapter 220 Zoning (Ord. No. 680-05, 2005). No ADU text. Two-family dwellings permitted in R-2, R-3 and MU (220-13, 220-16). Read in the browser on eCode360 (MU1309).",
    },
    "4201745112": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/29169162",
        "plain_fetch": False,
        "current_through": "2026-07-08",
        "note": "Zoning: Chapter 27 Zoning (Ord. No. 558, 2012). ADU text: 'Accessory in-law dwelling' (Use 78, 27-1403H(11)): by right in R-1 to R-4, part of a single-family detached house with a connecting door, at most 600 sq ft, one per lot, permit and annual inspection, owner affidavit on the tenant's relationship. Read in the browser on eCode360 (LO0148).",
    },
    "4209184624": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11708888",
        "plain_fetch": False,
        "current_through": "2025-04-10",
        "note": "Zoning: Chapter 116 Zoning (Ord. No. 409, 1981). ADU text: 'Accessory dwelling unit' (116-11, 116-272E, Ord. No. 812, 2006): only in Option One conservation design subdivisions in AAAA and AAA (Conservation Design Overlay), at most 900 sq ft, 25 ft, conservation easement. Conversion of a single-family dwelling by special exception anywhere (116-26). Ord. No. 1049 (2026, zoning) not yet codified. Read in the browser on eCode360 (WH0819).",
    },
    "4201754192": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/37786375",
        "plain_fetch": False,
        "current_through": None,
        "note": "Zoning: Joint Municipal Zoning Ordinance (Newtown, Upper Makefield, Wrightstown), readopted 2007. ADU text: 'residential accessory apartment' within use H-3 (803 H-3.4): by right in the residential districts, for family members, domestic servants, caretakers or occasional guests, County Health sewage permit, 2 parking spaces per unit. Residential conversion (B-16) by conditional use or special exception. Read in the browser on eCode360 (NE3758, Newtown Area Zoning Jointure).",
    },
    "4202979480": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/8009217",
        "plain_fetch": False,
        "current_through": "2025-10-13",
        "note": "Zoning: Chapter 265 Zoning (Ord. No. 94-11, 1994). No ADU text for a household. 'Guesthouse, as an accessory dwelling' (612.7f) is short-term rental lodging in a second historic resource (301.4, 90-day stays), conditional use. Historic residential conversions by conditional use (612.7e). Ord. No. 2021-05 and 2026-08 (zoning) not yet codified. Read in the browser on eCode360 (UW2708).",
    },
    "4207181168": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11671452",
        "plain_fetch": False,
        "current_through": "2025-02-19",
        "note": "Zoning: Chapter 340 Zoning (Ord. No. 159, 1993). ADU text: 'ECHO housing' (340-67): special exception in the A Zone only, portable elder cottage up to 900 sq ft for a relative 50 or older or disabled, utilities shared, removed when no longer needed. Accessory building apartment in Village Overlay developments (340-23E(9)). Conversion apartments (340-65), two-family conversions (340-103), temporary farm employee housing (340-101). Ord. No. 306 and 307 (2026, zoning) not yet codified. Read in the browser on eCode360 (WA2488; WA1313 is Warwick, Bucks County).",
    },
    "4213383432": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/15443121",
        "plain_fetch": False,
        "current_through": "2025-11-13",
        "note": "Zoning: Chapter 150 Zoning (Ord. No. 87-2, 1987). No ADU text. Two-family conversions by special exception in LC only (150-354), duplexes in R-4, R-6, MU and the PRD overlay. A second unit in a single-family zone reads as a duplex (use variance), by right in R-6. Ord. No. 26-01, 26-02 and 26-03 (2026) amend Chapters 29, 139 and 121, not Chapter 150. Read in the browser on eCode360 (WE1311).",
    },
    "4209141432": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11763313",
        "plain_fetch": False,
        "current_through": "2026-05-20",
        "note": "Zoning: Chapter 405 Zoning (Ord. No. 1393, 1988). ADU text: 'Accessory dwelling unit' (405-1913, Ord. No. 2018-1907): by right, attached to or inside a single-family detached home, parents or grandparents of the household only, at most two people, owner-occupied, no rent, deed restriction, annual license, one more parking space. 2026 zoning amendments (Residential B and C, TOD) not yet codified. Read in the browser on eCode360 (LA0393).",
    },
    "4207121344": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/48621783",
        "plain_fetch": False,
        "current_through": "2025-12-15",
        "note": "Zoning: Chapter 375 Zoning (East Lampeter Zoning Ordinance of 2016, Ord. No. 323). ADU text: 'Apartment as an accessory use' (375-2020, 375-23070): by right with a single-family detached dwelling in R-1, R-2, R-3, MU, BH, VG, VC and VR, one per lot, for rent or lease, no size cap. Inside, attached or in a separate building. ECHO housing for a relative (375-23240) by right also in AG, up to 2,000 sq ft, the only accessory unit there. Read in the browser on eCode360 (EA2320).",
    },
    "4205530944": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11174931",
        "plain_fetch": False,
        "current_through": "2026-09-08",
        "note": "Zoning: Chapter 105 Zoning (Ord. No. 3-1998). No ADU text. Conversion of an existing single-family detached dwelling to a two-family dwelling by right in AR, R-1, R-2 and CC (105-6A(7), 105-7A(10), 105-8A(7), 105-9A(5)). Read in the browser on eCode360 (GR1759).",
    },
    "4200372160": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11615243",
        "plain_fetch": False,
        "current_through": "2026-01-14",
        "note": "Zoning: Chapter 240 Zoning. No ADU text. Unlisted uses barred in R-1 to R-4, one principal dwelling per lot (240-13). Two-family dwellings by right in R-4 (240-36) and in ND developments. Ord. No. 4-2026 (zoning, R-1 lot width) not yet codified. Read in the browser on eCode360 (SO0208).",
    },
    "4207141224": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/13005392",
        "plain_fetch": False,
        "current_through": "2022-11-14",
        "note": "Zoning: Chapter 280 Zoning (Ord. No. 2012-04). ADU text: 'Accessory dwelling unit' (280-201, 280-402A, 280-1502): by right in R-1 only, at most 40% of the house, one per lot, owner lives in either unit, lot meets the single-family requirements, one more parking space. Ord. No. 2026-05 (zoning, Industrial District campgrounds) not yet codified. Read in the browser on eCode360 (LA1280; LA3847 is Lancaster Township, Butler County).",
    },
    "4209161664": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/26906730",
        "plain_fetch": False,
        "current_through": "2026-07-13",
        "note": "Zoning: Appendix B Zoning (Ord. No. 342, 1960, as amended). ADU text: 'Additional living quarters (not a dwelling unit)' (1910B(8)): accessory to a single-family dwelling, immediate family only, inside or added to the house, owner-occupied, no rent, one-year renewable permit, recorded deed restriction, detached units prohibited. Conversion to more families by special exception (1912). Duplexes in D only as an attached dwelling development on a tract of one acre or more with a land development plan (803). D-1 bars additional dwelling units (1910B(8)(h)). Read in the browser on eCode360 (PL1880).",
    },
    "4213358888": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/27440640",
        "plain_fetch": False,
        "current_through": "2026-04-20",
        "note": "Zoning: Chapter 325 Zoning (Ord. No. 880, 11-17-2025). ADU text: 'Dwelling, conversion' (325-630): special exception in R-10, R-15, R-22, R-40, RC and MU, one added unit for a family member inside or added to the house, at most 450 sq ft and two people, owner-occupied, annual affidavit, one more parking space. ECHO elder cottage by special exception in the same zones (325-637, portable, 300 to 900 sq ft, relative 60 or older or disabled). MU allows four dwelling units per gross acre (325-207D). Read in the browser on eCode360 (PE0541).",
    },
    "4204515488": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/10946616",
        "plain_fetch": False,
        "current_through": "2025-05-13",
        "note": "Zoning: Chapter 210 Zoning (Ord. No. 132, 12-7-1982, as amended). No general ADU rule: residence districts allow listed uses 'and for no other'. 'Single-family residence with an accessory apartment' (210-4, 210-72A(1)(f), 210-74C(17)) by right only inside an R-PRD-1 planned residential development (50 acres, public water and sewer) on a lot the approved plan designates for it (attached, 600 to 1,000 sq ft, two bedrooms, at most 30% of the units). Added dwelling unit in a Class I or II historic resource by conditional use (210-183.7B) on a property large enough for two units under the district rules, else a Zoning Hearing Board variance (210-183.8A). Read in the browser on eCode360 (CO1622).",
    },
    "4202921192": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/7252554",
        "plain_fetch": False,
        "current_through": "2025-07-15",
        "note": "Zoning: Chapter 240 Zoning (Ord. No. 119, 6-9-1997, as amended). ADU text: 'Apartment for care of a relative' (240-6, 240-32C): accessory use by right in R-1 to R-5, for a relative of a resident who needs care, at most two persons, reconverted or removed when no longer needed, recorded agreement against renting to a nonrelative. Outside R-1 to R-5 a use variance (240-4D does not reach a listed use). Historic resource conversion to dwelling units by conditional use (240-38.5A(2)(c), 240-38.7). Read in the browser on eCode360 (EA1698).",
    },
    "4209177152": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/14342706",
        "plain_fetch": False,
        "current_through": "2025-07-23",
        "note": "Zoning: Chapter 153 Zoning (Zoning Ordinance of 1956, as amended by Ord. No. 95-10 and later). ADU text: 'A-1 Accessory Apartments for Family Members' (153-502H(1)): special exception in R-200, R-180, R-175 and R-125 ('For family member only') and in the RBP Overlay on 80,000 sq ft lots with public water and sewer (153-418, whether the base district's listing still holds in the overlay is not said). Part of the house, not in a basement or accessory building, at most 800 sq ft, related family members only, one more parking space, registered with the Zoning Officer. Residential conversion (153-502F(10)) by special exception. New Laws: Ord. No. 25-08 and 26-04 (zoning) not codified. Read in the browser on eCode360 (TO0773).",
    },
    "4202138288": {
        "code_host": "amlegal",
        "code_url": "https://codelibrary.amlegal.com/codes/johnstownpa/latest/johnstown_pa/0-0-0-49965",
        "plain_fetch": False,
        "current_through": "2026-01-14",
        "note": "Zoning: Chapter 1260 Zoning Ordinance (Ord. 5139, 11-27-2013, as amended), code version 2026 S-20. No ADU text. Two-family dwellings permitted in R2, R3, TND, C1, C2 and C3, 'two-single family units on one lot' in TND and the HOD-CC overlay (1260.064, 1260.066 to 1260.068, 1260.074), and a conversion apartment is defined as a multi-family building (permitted in R3). Elsewhere a use variance (1260.221). Current through 2026-01-14. Read in the browser on American Legal (johnstownpa).",
    },
    "4207183256": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11694778",
        "plain_fetch": False,
        "current_through": "2025-11-10",
        "note": "Zoning: Chapter 285 Zoning (Ord. No. 270, 6-5-2024). ADU text: 'Accessory dwelling unit' (285-49D(1)): special exception in A, C, RR, R-1, R-2 and R-3, one per single-family detached dwelling for use by a relative, owner-occupied, in or attached to the house, at most 40% of the house or 800 sq ft (whichever is less) and two bedrooms, one more parking space, annual certification and recorded agreement. In A a larger ADU (60% or 1,200 sq ft) by conditional use. Conversion of an existing building into dwellings by right in MS (285-43B(1)(e)). Read in the browser on eCode360 (WE2002).",
    },
    "4209179056": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/10790758",
        "plain_fetch": False,
        "current_through": "2025-12-08",
        "note": "Zoning: Chapter 195 Zoning (Ord. No. 87-11, 11-23-1987, as amended). ADU text: an accessory use (195-9F(1)(g)): 'When accessory to a single-family detached dwelling only, one separate living area, including cooking facilities' for no more than two persons related to the principal occupant, with no enlargement of the building's footprint (an existing accessory building is not excluded, 195-3A, B), registered with the Zoning Officer and a recorded agreement to remove the cooking facilities. R-1 names 195-9F. Whether it reaches R-2, R-3, R-4, AP and BP (narrow or no accessory lists) is not settled. C and GA permit no single-family detached dwelling. IN only age-restricted houses by conditional use. VPR conversion by special exception (195-17B(6)(c)) and two-family dwellings in VPR and VC. New Laws: Ord. No. 2026-01 and 2026-03 (zoning) not codified. Read in the browser on eCode360 (UP0929).",
    },
    "4207183152": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/13152773",
        "plain_fetch": False,
        "current_through": "2025-11-06",
        "note": "Zoning: Chapter 145 Zoning (Zoning Ordinance of 1988, as amended). ADU text: ECHO housing (elder cottage, 201.2, 702.9): special exception in R, RR, R-1 and R-2, an addition to or conversion of the house or a mobile home on the lot, at most 1,000 sq ft, for an elderly, handicapped or disabled relative, at most two people, removed within 120 days after use ends, one more parking space. Residential conversion of a house existing on March 14, 1978 by special exception (702.1), two-family dwellings by right in R-2, R-3 and TV, and a farm-employee mobile home by special exception in R (702.4). New Laws: Ord. No. 6-26 (zoning) not codified. Read in the browser on eCode360 (WE1403).",
    },
    "4204578776": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/15685575",
        "plain_fetch": False,
        "current_through": "2026-01-15",
        "note": "Zoning: Chapter 600 Zoning (Ord. No. 678, 12-13-2012, as amended). No ADU text. R-1, R-2 and R-3 permit only single-family detached dwellings among dwellings. Two-family detached dwellings (duplexes) by right only in APT on a one-acre tract (600-40, 600-43C), watchman or caretaker quarters in I (600-81E). Elsewhere a use variance (600-209C). New Laws: Ord. No. 767 (zoning) not codified. Read in the browser on eCode360 (UP1263).",
    },
    "4209526728": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/8571248",
        "plain_fetch": False,
        "current_through": "2025-09-04",
        "note": "Zoning: Chapter 200 Zoning (Ord. No. 331, 8-21-2014, as amended). The code defines an accessory apartment and a unit for care of relative (200-7) but no district lists either use (H-9, H-11, H-12 reserved). A use permitted in no district may be a conditional use (200-79F). Residential conversion by special exception in TC and TC-1 (200-28B(14)), a facility for domestic servants, caretakers or guests on lots over one acre (200-28H(3)(c)[3]), a second dwelling under a county agricultural easement in FP (200-13D), duplexes in age-restricted housing (CR by right, SR and SR-1 conditional use). RC yards follow lot size (200-22C). New Laws: Ord. 414, 415, 416 (zoning) not codified. Ord. 415 rewrites the FP district table. Read in the browser on eCode360 (FO1696).",
    },
    "4204503336": {
        "code_host": "amlegal",
        "code_url": "https://codelibrary.amlegal.com/codes/astontwppa/latest/astontownship_pa/0-0-0-6217",
        "plain_fetch": False,
        "current_through": "2024-02-21",
        "note": "Zoning: Part Twelve, Title Six Zoning (Chapters 1250 to 1298, Ord. 896, 12-21-2011, as amended). ADU text: 'Accessory dwelling units' (1290.14): special exception in R-1, R-2 and R-3 (R-3's own list 1262.03 omits it, so R-3 is in doubt), part of or an addition to the house, owner-occupied, for a member of the owner's immediate family, at most 25% of the house, two bedrooms and four occupants, lot 10,000 sq ft, two more parking spaces. Two-family dwellings by right in APT (3-acre tract). Current through Ord. 1035 (2-21-2024). Read in the browser on American Legal Publishing (astontwppa).",
    },
    "4213332448": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/15699677",
        "plain_fetch": False,
        "current_through": "2026-05-27",
        "note": "Zoning: Chapter 370 Zoning (Ord. No. 2385, adopted 1-28-2026). ADU text: 'Accessory dwelling units' (370-400): special exception in R-1, R-3, R-5, D and MU, accessory to an owner-occupied single-family dwelling, within or attached to the house or in an accessory building (two stories or 25 ft), 500 sq ft to 50% of the house, at most two people. No use variance for a use not permissible in a district (370-907E), so none in CB, PD, M and HI. Conversion of a large existing house (3,000 sq ft) by special exception (370-446). Read in the browser on eCode360 (HA0246).",
    },
    "4204932520": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/38846017",
        "plain_fetch": False,
        "current_through": "2026-08-19",
        "note": "Zoning: Chapter 490 Zoning (Ord. No. 2025-243, adopted 1-8-2025, as amended). No ADU text. A separate building used for living is barred (490-88A, 490-94A), and an accessory building includes a portion of the main building (490-16), so the bar may reach an attached garage or an internal unit. Two-family dwellings by right in R-2 (not abutting another), R-3 and R-4 on duplex lots, a planned residential development with duplexes by conditional use in R-1, R-2 and LF (20 acres, R-2 also multi-story at one unit per 4,000 sq ft), a caretaker unit with an industrial establishment. Unlisted uses are a special exception only in I (490-14B). Read in the browser on eCode360 (HA4252).",
    },
    "4209145096": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/9509651",
        "plain_fetch": False,
        "current_through": "2026-05-06",
        "note": "Zoning: Chapter 164 Zoning (Ord. No. 62-6 of 1962, as amended). No ADU text. Alteration of a single-family dwelling into a two-family dwelling by conditional use in R-1 (164-30B(3)), and by reference perhaps in R-2 and C. Two-family dwellings by right in VC (six units per gross acre, 80% impervious cover), in R-4 and R-5 tract developments and in an OLC development on 10 acres. In RO an existing home may become an office and one apartment, and offices with one apartment are a Class Two use (80,000 sq ft), both by conditional use. OLC houses: the R-3 standards (164-62.9A) conflict with the OLC table (164-62.12). New Laws: Ord. No. 2026-06 (age-qualified residential in LPOD) and 2026-07 (data center overlay) not codified. Read in the browser on eCode360 (LO0727).",
    },
    "4213353224": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/36783754",
        "plain_fetch": False,
        "current_through": "2026-07-28",
        "note": "Zoning: Chapter 380 Zoning (Ord. No. 329, adopted 7-25-2006, as amended). ADU text: ECHO housing (380-14, 380-59A(19)): a portable elder cottage by special exception in RH, A, RR and R, at most 900 sq ft and two people, for a related person 55 or older, handicapped or disabled, on the house's utilities, removed within three months after use ends. Two-family conversion of a large existing house (3,000 sq ft) by special exception in V (380-59A(61)), two-family dwellings by right in RG and V, more than one principal use on a V lot with land development approval (380-43). Lot coverage is impervious cover (380-14). New Laws: Ord. No. 442 (data centers) not codified. Read in the browser on eCode360 (NE2598).",
    },
    "4209183696": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/15475025",
        "plain_fetch": False,
        "current_through": "2026-04-14",
        "note": "Zoning: Chapter 27 Zoning (Ord. No. 524 of 1991 restating the 1952 ordinance, as amended). ADU text: 'One separate living area, including cooking facilities' in a single-family detached dwelling for no more than two persons related to the principal occupant, registered with the Zoning Officer, with a recorded agreement to remove the cooking facilities later (27-301 subsections 6B and 9). Written in R-A and carried by reference to R-1, R-2, R-3, B-P, C, L-C and I. Detached garages may not be used as a dwelling (27-301 subsection 6A). Conversion of dwellings by special exception was repealed (27-1404). Two-family buildings by right only in R-3 tract developments (10 acres), watchman and caretaker quarters in LC&I, where a unified development by conditional use may take any Commercial District use (27-1001Q(2)). State Institution Overlay on part of R-A (27-304 to 27-308, Ord. No. 2024-769), a superseding district with no dwelling use. Read in the browser on eCode360 (WE2500).",
    },
    "4207755576": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/35645899",
        "plain_fetch": False,
        "current_through": "2026-08-10",
        "note": "Zoning: Chapter 440 Zoning (Ord. No. 2025-3, adopted 12-1-2025, repealing the 2002 ordinance). ADU text: 'Accessory family dwelling unit' (440-37 use H5, 440-40H(5)): by right in CR, AR and V, not permitted elsewhere, for family members or a family caregiver, part of the house or in an existing accessory structure such as a garage, at most 25% of the house, one more parking space. Two-family detached dwellings by right in CR, AR, AR-I, AR-L, SR and V. A second single-family detached dwelling for farm workers or the landowner's immediate family is part of an agricultural operation in every district (440-40A(1)(c)). No district height for houses found in the web text. Read in the browser on eCode360 (NO3503).",
    },
    "4200355016": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/30832639",
        "plain_fetch": False,
        "current_through": "2024-10-08",
        "note": "Zoning: Chapter 27 Zoning (Ord. No. 477, 5-11-2021, as amended). ADU text: 'Accessory dwelling unit' (27-305 Table 2, 27-604): conditional use in R-1, R-2 and MU, lot 20,000 sq ft, owner-occupied, one per lot, at most 25% of the house, 8 ft from the house, an apartment above a detached garage, a manufactured home or a tiny house. Table 2 also rates the unit P in B-2 and I-1, where no dwelling is listed. R-1 density 1.1 units per acre with public sewer, 0.5 without. Conversion dwellings by conditional use (27-643(3)), duplexes by right in R-1 and MU. New Laws: Ord. No. 535 and 551 (zoning) not codified. Ord. No. 551 restates the accessory use table. Read in the browser on eCode360 (NO3691).",
    },
    "4201900300": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/12752118",
        "plain_fetch": False,
        "current_through": "2026-02-23",
        "note": "Zoning: Chapter 192 Zoning (Ord. No. 92, adopted 9-25-2000, as amended). ADU text: 'Temporary second dwelling' (192-6, 192-15B(10), 192-16B(9), 192-17B(12), 192-54E, 167-21.1): listed as a principal permitted use in RC, RAL and RAM, for immediate family, on a Board of Supervisors finding of family hardship (no hearing named), permission for 12 months at a time and renewable, so read as a conditional use, a mobile, modular or manufactured home not on a permanent foundation (192-54E(1) also names an apartment in the house or a carriage house), lot of two acres with on-lot sewage or one acre with public sewer, at least 500 sq ft, counts as one-half dwelling unit for density, one per lot. No use variance for a use not permissible in a district (192-76C). Double dwellings by right in RC, RAL, RAM and R-2 where the lot holds two units at the district density, conversion structures (three units) in R-2. Use, dimensional and density schedules only in PDF attachments. Ord. No. 194 (6-22-2026) adopts a merger agreement with Mars Borough. Read in the browser on eCode360 (AD1937).",
    },
    "4200365352": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/14125507",
        "plain_fetch": False,
        "current_through": "2024-04-01",
        "note": "Zoning: Chapter 300 Zoning (Ord. No. 3-1993, amended in its entirety 6-5-2017 by Res. No. 8-2017). No ADU text. 'No accessory structure shall be used for dwelling purposes' (300-73D(2)). Two-family dwellings by right in R-3 and R-5 and in the Mobility Overlay Districts MOD-A, MOD-B and MOD-C, conversion of an existing single-family dwelling to three or more units by special exception in R-3 and by right in R-4 (300-103A(4)). New Laws: Ord. No. 2-2025 (R-4), 3-2025 (low-rise apartment overlay in C-3), 4-2025 (R-3 side yard) and 2-2026 (R-1 lot 17,500 sq ft, front 35 ft) not codified, read in search excerpts. Read in the browser on eCode360 (RO0250).",
    },
    "4205581240": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/6216322",
        "plain_fetch": False,
        "current_through": "2025-12-15",
        "note": "Zoning: Chapter 360 Zoning (Ord. No. 153, adopted 4-2-2001, as amended). No ADU text. One dwelling per lot (360-24). Conversion of an existing single-family detached dwelling to a two-family dwelling (conversion apartment) by right in R-2, R-3 and C-N (360-70F, 360-74F, 360-88G, H), two-family detached dwellings by right in A, R-2 and R-3 on a lot 25% larger than the single-family lot, two-family dwellings in historic residences in H (360-152A), a caretaker residence accessory to any H permitted use, a historic home included, against one dwelling per lot (360-152M(1), 360-24). Read in the browser on eCode360 (WA2765).",
    },
    "4200360272": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/9187197",
        "plain_fetch": False,
        "current_through": "2026-08-03",
        "note": "Zoning: Chapter 84 Zoning (Ord. No. 404, adopted 2-5-2024, repealing the 2005 chapter). ADU text: 'Accessory dwelling unit' (84-9, 84-26 Table 4, 84-34B): by right in E-1, S-1, R-1, R-2 and R-3, not permitted in B-1, C-1 and C-2, for persons related by blood, marriage or adoption to those in the house, owner-occupied, not rented, at most 50% of the house or 1,000 sq ft, 10 ft from the house. The definition says the unit is detached, while 84-34B(1)(c) places it in a detached structure whose first floor is or was a garage or barn, or in the principal dwelling. No two-family dwelling use. Lot coverage is impervious cover (84-9). Traditional Village Overlay front yard at least the greater of 15 ft and the smaller adjacent front yard, at most 25 ft (84-29F(5)(a)). Read in the browser on eCode360 (PI1032).",
    },
    "4204554224": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/15082328",
        "plain_fetch": False,
        "current_through": "2026-02-09",
        "note": "Zoning: Chapter 172 Zoning (1974, amended 6-8-2009 by Ord. No. 2009-03, as amended). ADU text: on estates (R-1 property of 3 to 5 acres, any residential property of 5 acres or more) 'an in-law suite or servants quarters may be located above a garage or in a separate suite in the residence', no rental, a separate building by special exception (172-103G(3)(a)). The code's 'accessory dwelling unit' is a unit within a commercial use in C-1 by special exception for an owner or employee (172-2, 172-70O, Ord. No. 2024-03). Conversion of a house to a two-family dwelling: listed by special exception for R-1, R-2, R-3, SU-1 and SU-2 in 172-14, but 172-111 allows it only where two-family dwellings are permitted. Whether the estate rule reaches R-4 and R-4A (closed accessory list, 172-37C, 172-44A) and R-5 is in doubt. Garage heights by district: 17 ft R-1, 15 ft R-1A and R-2, 14 ft R-3 (172-103B). New Laws: Ord. No. 2026-03 (historic resources map), 2026-04 (data centers in I) and 2026-05 (official map) not codified. Read in the browser on eCode360 (NE1450).",
    },
    "4212511800": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/30998148",
        "plain_fetch": False,
        "current_through": "2026-06-01",
        "note": "Zoning: Chapter 240 Zoning (Ord. No. 5-00, adopted 5-17-2000, amended in its entirety at Code adoption, as amended to Ord. No. 3-2026). No ADU text. One principal residential building per property (240-46). Two-family dwellings by right in R-2, R-3 and C-3 (R-2 6,000 sq ft and R-3 5,000 sq ft per unit with public sewer), and in the SD residential category and the IHPD overlay. Accessory structure size and height by lot size (240-48A). Uses of the same general character as a listed use by special exception in C-1, C-2 and C-3 (240-28D, 240-29D, 240-30C(1)). Lot coverage is building coverage (240-8). Development standards and schedule of uses attachments are PDFs, but the district sections give uses and figures in text. Read in the browser on eCode360 (CE2516).",
    },
    "4201781144": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/11665361",
        "plain_fetch": False,
        "current_through": "2025-11-17",
        "note": "Zoning: Chapter 195 Zoning (Ord. No. 2010-8, 12-20-2010, as amended to Ord. No. 2025-01). ADU text: 'Accessory family apartment or dwelling unit' (Use B8, 195-16B(8)) by special exception in RA, R1, R1A, R2, RR and RG for relatives of the family in the house, at most 50% of the primary living area or 800 sq ft, in the house or in an accessory building that existed on April 1, 2011, no new building, two parking spaces, deed restriction. The O District lists B8 among uses by right against the special exception in 195-16B(8)(f). Also living quarters for household employees (B12), a farm unit for family and farm workers (A2), an accessory dwelling unit with a nonresidential use (G29 dwelling in combination) in VC, VC 2, C1, C2, C3, residential conversion (B7) in the commercial districts and duplexes in MF-1, MF-2, C3 and O. New Laws: Ord. No. 2026-03 (accessory structure placement, data centers) not codified. Not Warwick Township, Lancaster County. Read in the browser on eCode360 (WA1313).",
    },
    "4202982544": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/16247593",
        "plain_fetch": False,
        "current_through": "2026-02-10",
        "note": "Zoning: Chapter 450 Zoning (Ord. No. 1977-1, as amended). ADU text: 'Accessory suite' (450-8, 450-64H, Ord. No. 19-07 of 12-10-2019) by conditional use in R-1 and R-1C, attached to or inside the single-family detached house, for employees of the owner or relatives, one extra parking space, no size cap. R-1 density is one dwelling per net acre 'for each dwelling unit', and the definition calls the suite a dwelling unit. More than one principal building on a lot if each meets the lot and yard rules (450-61H), and added units in historic structures by conditional use (450-62O). Lot coverage is impervious cover (450-8). New Laws: Ord. No. 2026-04 (data centers) not codified. Read in the browser on eCode360 (WE3104).",
    },
    "4209171016": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/9228557",
        "plain_fetch": False,
        "current_through": "2024-04-10",
        "note": "Zoning: Chapter 200 Zoning (Ord. No. 314, 5-14-2008, as amended). No ADU text. Residential districts permit 'any one' listed use 'and no other', among them one single-family detached dwelling, and accessory uses only as listed in 200-47. Two-family detached dwellings by right in R4 (8,000 sq ft per unit) and VR, one dwelling unit or apartment in a building with a commercial use in VC and GC, similar uses by conditional use in VC and GC, and uses not permitted elsewhere by conditional use in LI. Table VR-1 and Table 200-21 are PDF attachments. New Laws: Ord. No. 366, 374 and 375 of 2026 (smoke shops, data centers) not codified. Read in the browser on eCode360 (SK1672).",
    },
    "4209121600": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/8114101",
        "plain_fetch": False,
        "current_through": "2021-06-29",
        "note": "Zoning: Chapter 205 Zoning (Ord. No. 96 of 1973, readopted 2005 and 2008, as amended). ADU text: 'Relative quarters' (205-16B(4)), a use accessory to a dwelling, in the existing house or attached to it with a connecting doorway, not in a separate freestanding building, occupied only by the property owner and immediate family, not leased, deed restriction, one-year renewable Zoning Officer permit. Listed through 205-16 in AR, BR, BR-1, MR, CR, RP and RO. Barred in the ECII residential section (205-63.12A). An accessory building may not be a dwelling unit (205-5). Two-family detached dwellings by right in RO. RP allows one dwelling unit at or above the second story as an accessory use (205-46I), which conflicts with the family rule. The eCode360 search did not find 205-16B(4). CR lot dimensions are in a PDF attachment (205a). New Laws: no zoning ordinance listed. Read in the browser on eCode360 (EA1154).",
    },
    "4200372400": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/33554885",
        "plain_fetch": False,
        "current_through": "2026-08-10",
        "note": "Zoning: Chapter 137 Zoning (Ord. No. 556, 9-16-1996, as amended). No ADU text. Unlisted uses not permitted in R-1 to R-5, RP, BP and CR (137-13A), comparable uses by special exception in C-1 to C-4, I-1 and I-2 (137-131A(12)). Single-family and two-family dwellings are the only principal structure on a lot (137-13C). Two-family dwellings are listed only inside an R-3 planned residential development of 10 acres (137-121B(2)) and a transit-oriented overlay development approved by conditional use (137-196, 137-200A(3)). Apartment above office or retail by special exception in C-1 and C-3 (137-131A(2)). Use Tables A and B are PDF attachments, but each district article lists its uses in text. New Laws: none. Read in the browser on eCode360 (SO0738).",
    },
    "4213373168": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/14755449",
        "plain_fetch": False,
        "current_through": "2025-12-10",
        "note": "Zoning: Chapter 310 Zoning (Ord. No. 2009-09, 11-11-2009, as amended). No ADU text. Multifamily or two-family conversion of an existing house by special exception in R-1 and R-2 (8,000 sq ft of lot per unit, public sewer and water, no change to the original style, 310-66) and by right in A-O, where 310-66 does not apply. Two-family dwelling by right in R-2. Single-family residence with another permitted use in A-O and C, caretaker or watchman dwelling in IP. Unlisted uses by special exception where similar uses are allowed (310-5B). Lot coverage is impervious cover (310-3C). New Laws: none. Read in the browser on eCode360 (SP2461).",
    },
    "4201910464": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/12072159",
        "plain_fetch": False,
        "current_through": "2026-05-28",
        "note": "Zoning: Chapter 260 Zoning (adopted 2-19-1987 as Part 13 of the 1987 Codified Ordinances, as amended). No ADU text. Each district permits its listed uses only. The Zoning Hearing Board may not grant a use variance (260-132C(4)). R-1 allows one dwelling unit per lot (260-16A). Conversion of a house that existed before the chapter to two units is a permitted use in R-2 and R-3 with no Board review (450 sq ft per unit, 3,000 sq ft lot with no addition, 260-20C, 260-29D, 260-132D(4)). Two-family dwellings by right in R-2, R-3 and R-O. Units in an accessory building count toward the district's unit cap (260-10L, N). The use table and the bulk and lot-area-per-unit tables are PDF attachments, but each district article sets its uses and figures in text. New Laws: none on zoning. Read in the browser on eCode360 (BU1538).",
    },
    "4201102328": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/34014197",
        "plain_fetch": False,
        "current_through": "2026-03-18",
        "note": "Zoning: Chapter 32 Zoning (Ord. No. 130, 12-9-1991, as amended). ADU text: 'Family member suites' (32-957, Ord. No. 311 of 2-6-2019), by right in RC, LDR, MDR and RV, by conditional use in PBOI only in a dwelling that existed in 2019. For a father, mother, parent-in-law, step-parent or grandparent of the resident, at most two people, inside or attached to a single-family dwelling, never in an accessory structure, at most 800 sq ft and one bedroom, shared utilities, one extra parking space, zoning permit renewed every two years. Conversion of a large house to two units by special exception in RC, LDR, MDR and RV (32-904). Unlisted dwelling types by conditional use (32-949). The only attachment is the zoning map. New Laws: none on zoning. Read in the browser on eCode360 (AM1620).",
    },
    "4209127280": {
        "code_host": "ecode360",
        "code_url": "https://ecode360.com/8789917",
        "plain_fetch": False,
        "current_through": "2026-07-20",
        "note": "Zoning: Chapter 145 Zoning (Ord. No. 33, 5-2-1966, 'Zoning Ordinance of 1953, Revised', as amended through Ord. No. 434 of 7-20-2026). ADU text: 'In-law suite' (second housekeeping unit), a special exception in R-175, R-130, R-100 and RR under 145-157B: in an owner-occupied single-family detached dwelling, for relatives of the owners, at most two occupants under the Fair Housing Act older persons rules, at most 40% of the main unit and 1,000 sq ft, attached with an interior connection and no separate entrance, recorded removal agreement, one extra parking space. R-130 special exception uses need 40,000 sq ft (145-35.1). VC permits one two-family dwelling or apartments in an existing structure by right (145-192). No PDF use or dimension tables. New Laws: Ord. No. 435 (9-21-2026), zoning map only. Read in the browser on eCode360 (FR0973).",
    },
}

# Smaller towns whose zoning code has ADU text (confirmed in the code text on 2026-11-11), and towns
# added later by population (batch 14). Up to 16.
# Towns whose batch was set when they were assigned, not by position in the list.
FIXED_BATCH = {g: 14 for g in ("4207779104", "4207121232", "4209506096", "4201781048", "4209145080", "4209150640")}
FIXED_BATCH.update({g: 15 for g in ("4201124384", "4204573032", "4209179256", "4204178736", "4213319704")})
FIXED_BATCH.update(
    {g: 16 for g in ("4202983080", "4205512536", "4212559608", "4204111272", "4209143312", "4204144832")}
)
FIXED_BATCH.update(
    {g: 17 for g in ("4209173088", "4209133120", "4202984192", "4212958880", "4212952432", "4201745112")}
)
FIXED_BATCH.update(
    {g: 18 for g in ("4209184624", "4201754192", "4202979480", "4207181168", "4213383432", "4209141432")}
)
FIXED_BATCH.update({g: 19 for g in ("4207121344", "4205530944", "4200372160", "4207141224")})
FIXED_BATCH.update({g: 20 for g in ("4209161664", "4213358888", "4204515488", "4202921192")})
FIXED_BATCH.update({g: 21 for g in ("4209177152", "4202138288", "4207183256")})
FIXED_BATCH.update({g: 22 for g in ("4209179056", "4207183152", "4204578776")})
FIXED_BATCH.update({g: 23 for g in ("4209526728", "4204503336", "4213332448")})
FIXED_BATCH.update({g: 24 for g in ("4204932520", "4209145096", "4213353224")})
FIXED_BATCH.update({g: 25 for g in ("4209183696", "4207755576", "4200355016")})
FIXED_BATCH.update({g: 26 for g in ("4201900300", "4200365352", "4205581240")})
FIXED_BATCH.update({g: 27 for g in ("4200360272", "4204554224", "4212511800")})
FIXED_BATCH.update({g: 28 for g in ("4201781144", "4202982544", "4209171016")})
FIXED_BATCH.update({g: 29 for g in ("4212931200", "4204553104", "4201761616")})
FIXED_BATCH.update({g: 30 for g in ("4209121600", "4200372400", "4213373168")})
FIXED_BATCH.update({g: 31 for g in ("4201910464", "4201102328", "4209127280")})

EXTRAS = {
    "4202935536": "Chester County Planning Commission ADU eTool. Code 27-1002 Accessory Dwelling Units",
    "4209152664": "Ord. 1043 (2022). Code 500-602 and 500-1201",
    "4204548480": "Code 311.A-13 definition and Article B-XV",
    "4202960120": "Ord. 2025-2410 (2025). ADU by special exception",
    "4202725624": "Code Chapter 27 Part 11 definition and 27-1503 Accessory Dwelling",
    "4204575648": "Family or caregiver suite by special exception, 1264.18",
    "4202939352": "Code 23-30 accessory apartment and accessory dwelling unit",
    "4209102264": "Code 27-407.A(8) family occupied ADUs",
    "4200134424": "2025 zoning ordinance 1502.H.1 (final draft, adoption not confirmed)",
    "4201719792": "Code 175-16.H(12) accessory dwelling unit by special exception",
    # Batch 14 (2026-11-14): the next six towns by population without a rule file.
    "4207779104": "Code 27-306 and 27-403.4A accessory apartment by special exception",
    "4207121232": "Code 270-5.2A accessory dwelling units by right, family only",
    "4209506096": "Code 275-190D(1) accessory apartment by right in AG, MDR, MHDR",
    "4201781048": "Code 370-305H(1) multigenerational apartment by special exception",
    "4209145080": "Code 143-6.2 in-law suite by right in R-1 to R-5",
    "4209150640": "Code 230-149C accessory family dwelling",
    # Batch 15 (2026-11-14): the next towns by population without a rule file. Upper Moreland and Derry were
    # skipped (district table or whole ordinance only in a PDF).
    "4201124384": "batch 15 by population. Code Chapter 390 has no ADU text",
    "4204573032": "batch 15 by population. Code Chapter 143 has no ADU text",
    "4209179256": "Code 300-15B(4) temporary unit for relative (in-law suite)",
    "4204178736": "Code 245-14.3 accessory apartment",
    "4213319704": "Code 27-602 accessory apartment and 27-603 accessory family dwelling unit",
    # Batch 16 (2026-11-14): the next towns by population without a rule file. Marple, Pottstown, Palmer,
    # Muhlenberg, Manor (Lancaster), Silver Spring, East Pennsboro and South Whitehall were skipped (district
    # tables only in PDFs, or no code readable as web pages).
    "4202983080": "Code 84-57.25 in-law suites",
    "4205512536": "batch 16 by population. Code Chapter 300 has no ADU text",
    "4212559608": "batch 16 by population. Code Chapter 440 has no ADU text",
    "4204111272": "batch 16 by population. Code Chapter 255 has no ADU text",
    "4209143312": "Code 184-71B(6) temporary unit for relative",
    "4204144832": "Code 220-149 accessory dwellings",
    # Batch 17 (2026-11-14): the next towns by population without a rule file. Unity, New Castle, Buckingham,
    # Coolbaugh, Baldwin and Upper St. Clair were skipped (use tables or the whole ordinance only in PDFs), and
    # Whitpain (new ADU ordinance Ord. No. 4-269 of 2026 not yet codified).
    "4209173088": "Code 114-12D4B(10) accessory apartment (historic resource overlay)",
    "4209133120": "Code 282-6 family definition, two housekeeping units",
    "4202984192": "batch 17 by population. Code Chapter 325 has no ADU text",
    "4212958880": "Code 190-202 and 190-405 conversion apartment",
    "4212952432": "batch 17 by population. Code Chapter 220 has no ADU text",
    "4201745112": "Code 27-1403H(11) accessory in-law dwelling",
    # Batch 18 (2026-11-14): the next towns by population without a rule file. Manchester (York) and Stroud were
    # skipped (district use tables only in PDF attachments).
    "4209184624": "Code 116-272E accessory dwelling units (Conservation Design Overlay, Option One)",
    "4201754192": "JMZO 803 H-3.4 residential accessory apartment",
    "4202979480": "batch 18 by population. Code Chapter 265 has no ADU text for a household (612.7f short-term guesthouse)",
    "4207181168": "Code 340-67 ECHO housing",
    "4213383432": "batch 18 by population. Code Chapter 150 has no ADU text",
    "4209141432": "Code 405-1913 accessory dwelling units, family only",
    # Batch 19 (2026-11-14): the next towns by population without a rule file. West Mifflin was skipped (Table of
    # Uses and dimension tables only in PDF attachments).
    "4207121344": "Code 375-23070 apartment as an accessory use and 375-23240 ECHO housing",
    "4205530944": "batch 19 by population. Code Chapter 105 has no ADU text",
    "4200372160": "batch 19 by population. Code Chapter 240 has no ADU text",
    "4207141224": "Code 280-1502 accessory dwelling unit (R-1)",
    # Batch 20 (2026-11-14): the next towns by population without a rule file.
    "4209161664": "Code Appendix B 1910B(8) additional living quarters, family only",
    "4213358888": "Code 325-630 conversion dwelling for a family member and 325-637 ECHO",
    # Batch 20b (2026-11-14): Upper Saucon, Windsor (York) and Fairview (York) were skipped (zoning only in PDFs, or
    # the online code is not the adopted ordinance).
    "4204515488": "Code 210-72A(1)(f) accessory apartment (R-PRD-1) and 210-183.7B historic added unit",
    "4202921192": "Code 240-32C apartment for care of a relative",
    # Batch 21 (2026-11-14): the next towns by population without a rule file. Hampton (Allegheny) was skipped (lot
    # area and setback table only in a PDF attachment), South Middleton (no code readable as web pages), North Strabane
    # (eCode360 code search closed to the public) and Middletown (Delaware) (code not found; zoning rewrite under way).
    "4209177152": "Code 153-502H(1) accessory apartments for family members",
    "4202138288": "batch 21 by population. Code Chapter 1260 has no ADU text",
    "4207183256": "Code 285-49D(1) accessory dwelling unit for a relative",
    # Batch 22 (2026-11-14): the next towns by population without a rule file. McKeesport was skipped (zoning
    # ordinance only as a PDF on the city website) and Butler (Butler) (bulk table and use table only in PDF attachments).
    "4209179056": "Code 195-9F(1)(g) separate living area for relatives",
    "4207183152": "Code 702.9 ECHO housing",
    "4204578776": "batch 22 by population. Code Chapter 600 has no ADU text",
    # Batch 23 (2026-11-15): the next towns by population without a rule file. Hilltown was skipped (use and bulk tables
    # only in PDF attachments) and Scott (Allegheny) (zoning ordinance only on the township website; eCode360 SC1463 is
    # Scott Township, Columbia County).
    "4209526728": "batch 23 by population. Code 200-7 accessory apartment and unit for care of relative (defined, not listed)",
    "4204503336": "Code 1290.14 accessory dwelling units, immediate family",
    "4213332448": "Code 370-400 accessory dwelling units",
    # Batch 24 (2026-11-15): the next towns by population without a rule file. Chestnuthill was skipped (use and
    # dimensional tables only in PDF attachments) and Antrim (Franklin) (eCode360 AN1579 is behind a login).
    "4204932520": "batch 24 by population. Code Chapter 490 has no ADU text",
    "4209145096": "batch 24 by population. Code Chapter 164 has no ADU text",
    "4213353224": "Code 380-59A(19) ECHO housing",
    # Batch 25 (2026-11-15): the next towns by population without a rule file. Hermitage (Mercer) was skipped (zoning
    # ordinance only as PDFs on the city website).
    "4209183696": "Code 27-301 subsections 6B and 9 separate living area for relatives",
    "4207755576": "Code 440-40H(5) accessory family dwelling unit",
    "4200355016": "Code 27-604 accessory dwelling unit",
    # Batch 26 (2026-11-15): the next towns by population without a rule file. Middle Smithfield was skipped (use and
    # dimensional tables only in PDF attachments), Cumru (zoning ordinance only as PDFs on the township website) and
    # Patton (new ADU ordinance Ord. No. 2026-658 of 10-28-2026 not yet codified).
    "4201900300": "Code 192-54E and 167-21.1 temporary second dwelling, family hardship",
    "4200365352": "batch 26 by population. Code Chapter 300 has no ADU text",
    "4205581240": "batch 26 by population. Code Chapter 360 has no ADU text (conversion apartments in R-2, R-3, C-N)",
    # Batch 27 (2026-11-15): the next towns by population without a rule file. Guilford (Franklin) was skipped (zoning
    # ordinance only as PDFs on the township website) and Caln (new 2026 zoning chapter with use table and district
    # dimension charts only in PDF attachments).
    "4200360272": "Code 84-34B accessory dwelling unit, family only",
    "4204554224": "Code 172-103G(3)(a) in-law suite or servants quarters on estates",
    "4212511800": "batch 27 by population. Code Chapter 240 has no ADU text",
    # Batch 28 (2026-11-15): the next towns by population without a rule file. Upper Southampton (Bucks) was skipped
    # (dimensional and performance tables only in PDF attachments), East Whiteland (use and development standards tables
    # only in PDF attachments), Franklin Park (use and area and bulk tables only in PDF attachments), White (Indiana) (no
    # municipal zoning), Indiana borough (zoning ordinance rewrite adopted in 2026, online code from 2023) and Whitehall
    # (Allegheny) (zoning only as PDFs on the borough website).
    "4201781144": "Code 195-16B(8) accessory family apartment by special exception",
    "4202982544": "Code 450-64H accessory suite by conditional use",
    "4209171016": "batch 28 by population. Code Chapter 200 has no ADU text",
    # Batch 29 (2026-11-15): the next towns by population without a rule file. Wilkinsburg was skipped (Table of
    # Authorized Principal Uses and Table of Authorized Accessory Uses only in PDF attachments) and Dunmore (zoning
    # ordinance of 12-20-2023 only as a PDF on the borough website).
    "4212931200": "batch 29 by population. Code Chapter 265 has no ADU text",
    "4204553104": "batch 29 by population. Code Chapter 300 has no ADU text (300-130 bars living quarters in accessory buildings)",
    "4201761616": "Code 27-304.19 B11 accessory dwelling for relatives or caretakers",
    # Batch 30 (2026-11-15): the next towns by population without a rule file. Lower Moreland (Montgomery) was skipped
    # (eCode360 holds only Article I of the zoning chapter, the full ordinance is a set of files on the township
    # website), Richland (Bucks) (area and bulk tables only in PDF attachments) and Ephrata borough (Lancaster) (use and
    # dimensional tables only in PDF attachments, and Ord. No. 1603 of 7-13-2026 amending zoning not yet codified).
    "4209121600": "Code 205-16B(4) relative quarters, family only",
    "4200372400": "batch 30 by population. Code Chapter 137 has no ADU text",
    "4213373168": "batch 30 by population. Code Chapter 310 has no ADU text (two-family conversion by special exception, 310-66)",
    # Batch 31 (2026-11-15): the next towns by population without a rule file. Derry (Westmoreland) was skipped (no
    # municipal zoning, only a 2024 solar ordinance), Salisbury (Lehigh) (tables of permitted uses and of lot and setback
    # requirements only in PDF attachments, and Ord. No. 08-2026-686 amending zoning not yet codified), Hopewell (Beaver)
    # (no zoning code found as web text; eCode360 HO3808 is Hopewell, Washington County, and HO3815 Hopewell, York
    # County), Coatesville (residential use table and every district's lot, bulk and coverage table only in PDF
    # attachments), Kingston (Luzerne) (Ord. No. 2023-4, a comprehensive zoning revision, and a later Chapter 181
    # amendment not yet codified) and Pottsville (use and lot schedules only in PDF attachments, and Ord. No. 954 of
    # 9-14-2026 amending zoning not yet codified).
    "4201910464": "batch 31 by population. Code Chapter 260 has no ADU text (use variance barred, 260-132C(4))",
    "4201102328": "Code 32-957 family member suites",
    "4209127280": "Code 145-157B in-law suite by special exception",
}

if __name__ == "__main__":
    sys.exit(main())
