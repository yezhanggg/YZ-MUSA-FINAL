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
    for g, src in EXTRAS.items():  # noqa: F821 (defined below)
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
HOSTS: dict[str, dict[str, Any]] = {
    '4210160000': {"code_host": "amlegal", "code_url": "https://codelibrary.amlegal.com/codes/philadelphia/latest/philadelphia_pa/0-0-0-292755", "plain_fetch": False, "current_through": None, "note": "Title 14 Zoning. Rule file philadelphia.json, outside the MPC."},
    '4200361000': {"code_host": "ecode360", "code_url": "https://ecode360.com/45474194", "plain_fetch": False, "current_through": None, "note": "Title 9 Zoning. Rule file pittsburgh.json, outside the MPC. Ord. 31-2026 (ADUs) not yet folded into eCode360 on 2026-11-10."},
    '4207702000': {"code_host": "ecode360", "code_url": "https://ecode360.com/49783893", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 660 Zoning. New zoning code (Zone Allentown) adopted 10-15-2025 by Ord. No. 16166, now Ch. 660 on ecode360 (code AL4161). Old 2010 ordinance PDF (Nov 2015 ed.) on allentownpa.gov is superseded. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened."},
    '4201163624': {"code_host": "amlegal", "code_url": "https://codelibrary.amlegal.com/codes/readingpa/latest/reading_pa/0-0-0-23864", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 600 Zoning (Zoning Ordinance of 2010). Code on American Legal (readingpa), not ecode360. Node 0-0-0-23864 appeared in search for 'Chapter 600 Zoning' but exact chapter-root node not confirmed (amlegal blocks curl/WebFetch with Cloudflare 403). Search snippets show amendments through 8-24-2026 (Ord. 69-2026), so code is very current. TOD overlay added 6-22-2026."},
    '4204924000': {"code_host": "ecode360", "code_url": "https://ecode360.com/ER3969", "plain_fetch": False, "current_through": None, "note": "Zoning: Part 13 Zoning Code, Article 1303 Zoning Ordinance. Zoning Ordinance (Ord. 80-2005) codified as Art. 1303 within Part 13 on ecode360 (code ER3969). article pages e.g. https://ecode360.com/44156815 note 'as amended through Ord. No. 15-2023', another page 'through Ord. No. 54-2025, passed 7-16-2025'. Chapter id not confirmed, root URL given. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened."},
    '4204579000': {"code_host": "ecode360", "code_url": "https://ecode360.com/33161971", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 550 Zoning (Upper Darby Township Zoning Ordinance of 2010). Code UP3641. 33161971 appears to be the chapter page (33161972 is the short-title section). chapter number 550 from search summary, unverified. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened."},
    '4206969000': {"code_host": "ecode360", "code_url": "https://ecode360.com/SC1588/laws/LF2072635.pdf", "plain_fetch": True, "current_through": None, "note": "Zoning: Chapter 445 Zoning (2023 Zoning Ordinance, File of Council #54 2023). New 2023 Zoning Ordinance effective 12-20-2023 is available as a PDF in ecode360 laws (plain curl returns 200 PDF, 5.3MB, text extractable). Codified ecode360 chapter (code SC1588) pages like https://ecode360.com/45088568 appear to be the new code. chapter root id not confirmed. No 'accessory dwelling' text match in the PDF. Date shown: 2023-12-20 (effective date of PDF)."},
    '4209144976': {"code_host": "ecode360", "code_url": "https://ecode360.com/LO0641", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 155 Zoning. Zoning Code Ch. 155 amended in its entirety 2-26-2020 by Ord. 4181. Code root LO0641 given. chapter id not confirmed. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened."},
    '4201705616': {"code_host": "municode", "code_url": None, "plain_fetch": False, "current_through": None, "note": "URL slug on Municode not confirmed, so no link is given. Zoning: Chapter 232 Zoning. Bensalem code is on Municode per APA knowledgebase and township 'Township Code of Ordinances' link. exact municode slug NOT confirmed (library.municode.com returns Cloudflare 403 to curl). Zoneomics mirror: https://www.zoneomics.com/code/bensalem-township-PA/chapter_1. UNSURE of URL."},
    '4209100156': {"code_host": "ecode360", "code_url": "https://ecode360.com/AB0569", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 162 Zoning. Code AB0569. 2017 comprehensive rezoning Ord. 2136 replaced Ch. 162. amendments through Ord. 2234 (8-14-2025) as ecode360 laws PDFs (e.g. https://ecode360.com/AB0569/laws/LF2693983.pdf). Chapter id not confirmed. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened."},
    '4207141216': {"code_host": "ecode360", "code_url": "https://ecode360.com/LA1674", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 300 Zoning. Code LA1674 (City). Do not confuse with Lancaster Township. Chapter id not confirmed (section pages ~ecode360.com/81228xx). ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened."},
    '4209506088': {"code_host": "own site", "code_url": "https://www.bethlehem-pa.gov/CityOfBethlehem/media/COBfiles/pdf/ordinances/Zoning-Ordinance.pdf", "plain_fetch": True, "current_through": None, "note": "Zoning: Part 13 Zoning Ordinance (Articles 1301-1360). City hosts own PDF (not ecode360). This PDF says 'Last Revised July 17, 2018'. The Zoning Office page links a newer 'Zoning-Ordinance-August-2023.pdf' (https://www.bethlehem-pa.gov/getattachment/Community-Economic-Development/Planning-Zoning/Zoning-Office/Zoning-Ordinance-August-2023.pdf.aspx?lang=en-US) but it returns 404 to curl. Per-article PDFs also at bethlehem-pa.gov/CityOfBethlehem/media/Ordinance-PDFs/ARTICLE-13xx.pdf. No ADU term in 2018 PDF. Date shown: 2018-07-17 (Last Revised, per PDF cover)."},
    '4201708768': {"code_host": "ecode360", "code_url": "https://ecode360.com/9499447", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 205 Zoning. 9499447 is a zoning-chapter page citing 'Bristol Township Zoning Ordinance' (may be section, not chapter root). Do not confuse with Bristol Borough (Ch. 27 Zoning). ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened."},
    '4204949548': {"code_host": "ecode360", "code_url": "https://ecode360.com/MI3114", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 145 Zoning. Code MI3114. Ch. 145 amended and restated 4-28-2022 by Ord. 2022-4. amended by Ord. 2024-6 (https://ecode360.com/MI3114/laws/LF2146675.pdf). Chapter id not confirmed. ecode360 root/chapter pages return Cloudflare 'Just a moment' 403 to curl and WebFetch. chapter id taken from search-result page titles, not opened."},
    '4204345056': {"code_host": "ecode360", "code_url": "https://ecode360.com/LO1649", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 203 Zoning. Code LO1649. Ch. 203 adopted 7-11-2006 by Ord. 2006-05. Index page showed date 2023-12-05 (possibly last update). Chapter id not confirmed. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4204533144': {"code_host": "ecode360", "code_url": "https://ecode360.com/HA0527", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 182 Zoning. Code HA0527. Chapter id not confirmed (section pages ~ecode360.com/12187xxx, 12435xxx). ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4204332800': {"code_host": "ecode360", "code_url": "https://ecode360.com/32584380", "plain_fetch": False, "current_through": None, "note": "Zoning: Title 7 Planning and Zoning Code, Part 3 Zoning Code (Ch. 7-301 to 7-333). ADU text seen: accessory dwelling (defined in Ch. 7-333 Definitions, ecode360.com/32586534). Zoning Code adopted 7-8-2014 by Ord. 5-2014. 32584380 = Ch. 7-301 Title/Purpose (closest to Part 3 root). TOC at https://ecode360.com/26959081. Chapter pages: 7-303=32584259, 7-305=32584223, 7-307=32584129, 7-321=32585393, 7-323=32586321, 7-327=32586102, 7-333=32586534 (ids from earlier saved pages in scratchpad). ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4201749120': {"code_host": "ecode360", "code_url": "https://ecode360.com/MI2390", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 500 Zoning. Code MI2390 (index page showed sections 500-2903, 500-3211. date stamp 2023-11-13). One search summary claimed a renumbered Ch. 275 and code MI1283 - likely a different Middletown. UNSURE which code id is Bucks County. Zoneomics mirror: https://www.zoneomics.com/code/middletown-township-bucks-PA/chapter_1. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4213387048': {"code_host": "amlegal", "code_url": "https://codelibrary.amlegal.com/codes/yorkpa/latest/york_pa", "plain_fetch": False, "current_through": "2024-01-01", "note": "Zoning: Part 13 Planning and Zoning Code (Arts. 1301-1379). Code root on American Legal (yorkpa). amlegal returns Cloudflare 403 to curl. City also links zoning sections 1301-1379 from https://www.yorkcity.org/york-city-codified-ordinances/ (per-article PDFs on yorkcity.org). Zoning chapter node not confirmed."},
    '4207985152': {"code_host": "zoneomics", "code_url": "https://www.zoneomics.com/code/wilkes-barre-PA/chapter_1", "plain_fetch": True, "current_through": None, "note": "Zoning: City of Wilkes-Barre Zoning Ordinance (File of Council No. 18 of 2012). No official online code confirmed. City page 'Zoning Ordinances & Zoning Map' (https://www.wilkes-barre.city/node/156) appears in search but returns 404 to curl. ecode360 hits for 'Wilkes-Barre' were other Luzerne municipalities (Kingston KI0963 etc). Zoneomics plain fetch 200 with zoning text. UNSURE - official source missing."},
    '4207146896': {"code_host": "own site", "code_url": "https://manheimtownship.org/DocumentCenter/View/8076/2-Ordinance-Updates", "plain_fetch": True, "current_through": None, "note": "Zoning: Zoning Ordinance of Manheim Township 2014 (ecode360 Ch. 500 Zoning). Township says codified code excludes the zoning ordinance. current amended text lives in township Document Center as per-article PDFs (e.g. https://manheimtownship.org/DocumentCenter/View/3110/4ARTICLE-1-Title-Purpose). View/8076 is only the revision list (57KB PDF). ecode360 Ch. 500 page https://ecode360.com/14976733 (code MA2385) is stale - amended only through Ord. 2014-21 (11-10-2014). Date shown: 2024-01-22 (latest revision listed: Ord. 2024-01, per search summary)."},
    '4201302184': {"code_host": "ecode360", "code_url": "https://ecode360.com/32046318", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 800 Zoning. 32046318 appeared in search for 'Chapter 800 Zoning' Altoona but may be a section, not chapter root. ecode360 code id not seen. A section references permits filed before 9-8-2025 so chapter recently amended. Zoneomics mirror https://www.zoneomics.com/code/altoona-PA/chapter_1. UNSURE of chapter id. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4212933792': {"code_host": "ecode360", "code_url": "https://ecode360.com/HE0496", "plain_fetch": False, "current_through": None, "note": "Zoning: Hempfield Township Zoning Ordinance of 2014 (chapter number unconfirmed. 1978 ord. was Ch. 87). Code HE0496. 2014 ordinance repealed 1978 ordinance. chapter number for 2014 code not confirmed. Zoning map amendments 2023 as laws PDFs (e.g. https://www.ecode360.com/HE0496/laws/LF2044516.pdf). Do not confuse with Hempfield Twp, Lancaster Co. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4200359032': {"code_host": "ecode360", "code_url": "https://ecode360.com/37763696", "plain_fetch": False, "current_through": None, "note": "Zoning: Part 12 Planning and Zoning Code, Title 6 Zoning (Chapters 1260-1288). Penn Hills codified ordinances are on ecode360 (code id not seen). 37763696 is a Penn Hills ecode360 page from search, not confirmed as zoning root. Zoning amended 10-21-2024 (Ord. 2024-2705) and 11-18-2024 (Ord. 2024-2707) per Zoneomics mirror https://www.zoneomics.com/code/penn-hills-township-PA. UNSURE of URL. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4202773808': {"code_host": "ecode360", "code_url": "https://ecode360.com/ST2624", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter XIX Zoning. Code ST2624. Sections numbered 19-xxx / XIX-xxx. Chapter id not confirmed. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4201754688': {"code_host": "ecode360", "code_url": "https://ecode360.com/NO0896", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 27 Zoning. Code NO0896 (Pennsylvania-style numbering, Ch. 27). Page showed date 2024-04-17. Chapter id not confirmed. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4209112968': {"code_host": "ecode360", "code_url": "https://ecode360.com/33235830", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 295 Zoning (Cheltenham Township Zoning Ordinance of 2017). Code CH1316. 33235830 precedes 33235831 (title section 'Cheltenham Township Zoning Ordinance'), likely chapter/article root but not confirmed. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4209154656': {"code_host": "ecode360", "code_url": "https://ecode360.com/NO0820", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 320 Zoning. Code NO0820 (Municipality of Norristown). Mixed-Use Overlay added 5-21-2025 by Ord. 25-03 (https://ecode360.com/49334564). Chapter id not confirmed. ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4201725112': {"code_host": "ecode360", "code_url": "https://ecode360.com/FA0549", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 209 Zoning. Code FA0549. Chapter id not confirmed (sections ~ecode360.com/71050xx-71270xx). ecode360 pages return Cloudflare 403 to curl and WebFetch. id from search-result titles, not opened."},
    '4200351696': {"code_host": "ecode360", "code_url": "https://ecode360.com/42261300", "plain_fetch": False, "current_through": "2026-02-10", "note": "Zoning: Chapter 20 Zoning. ecode360 code MO6716. Search for \"accessory dwelling\" in this code returned 0 results. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4209179136': {"code_host": "ecode360", "code_url": "https://ecode360.com/11658450", "plain_fetch": False, "current_through": "2026-03-12", "note": "Zoning: Chapter 165 Zoning. ecode360 code UP0975. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4201780952': {"code_host": "ecode360", "code_url": "https://ecode360.com/14238962", "plain_fetch": False, "current_through": "2026-04-09", "note": "Zoning: Chapter 27 Zoning. ecode360 code WA2486. Zoning rewritten by Ord. 762 (5/7/2020). Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4200306064': {"code_host": "ecode360", "code_url": "https://ecode360.com/29463304", "plain_fetch": False, "current_through": "2025-09-08", "note": "Zoning: Chapter 69 Zoning. ecode360 code BE0278. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4200366264': {"code_host": "ecode360", "code_url": "https://ecode360.com/30842452", "plain_fetch": False, "current_through": "2026-04-20", "note": "Zoning: Chapter 27 Zoning (Planning and Zoning Code). ecode360 code RO2521. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4204563264': {"code_host": "ecode360", "code_url": "https://ecode360.com/11078356", "plain_fetch": False, "current_through": "2026-09-28", "note": "Zoning: Chapter 280 Zoning. ecode360 code RA0484. Chapter id taken from the page breadcrumb. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4201744968': {"code_host": "ecode360", "code_url": "https://ecode360.com/11226088", "plain_fetch": False, "current_through": "2025-12-17", "note": "Zoning: Chapter 200 Zoning. ecode360 code LO1561. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4201916920': {"code_host": "ecode360", "code_url": "https://ecode360.com/34273101", "plain_fetch": False, "current_through": "2025-06-05", "note": "Zoning: Chapter 27 Zoning. ecode360 code CR0448. Later amendments (e.g. Ord. 2025-520) are posted on agenda.cranberrytownship.org and may not be codified yet. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4204132296': {"code_host": "municode", "code_url": "https://library.municode.com/pa/hampden_township/codes/code_of_ordinances?nodeId=CH27ZO", "plain_fetch": False, "current_through": "2026-07-02", "note": "Zoning: Chapter 27 Zoning. The township site (hampdentownship.us) links to the Municode library. Plain curl gets a 403 Cloudflare challenge, so the data was read in a browser. Zoneomics has a mirror."},
    '4204513208': {"code_host": "ecode360", "code_url": "https://ecode360.com/45941765", "plain_fetch": False, "current_through": "2026-08-12", "note": "Zoning: Chapter 550 Zoning. ecode360 code CH6779. Adopted 9-9-2015 by Ord. 5-2015. Chester code is CH6779, not CH2012. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4207744952': {"code_host": "ecode360", "code_url": "https://ecode360.com/30829060", "plain_fetch": False, "current_through": "2026-05-21", "note": "Zoning: Chapter 27 Zoning. ecode360 code LO1244. Zoning Ordinance of 2019 (Ord. 2019-10). Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4202977344': {"code_host": "ecode360", "code_url": "https://ecode360.com/7115532", "plain_fetch": False, "current_through": "2026-09-21", "note": "Zoning: Chapter 208 Zoning. ecode360 code TR1485. Chapter id taken from the page breadcrumb. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4212955128': {"code_host": "ecode360", "code_url": "https://ecode360.com/16043696", "plain_fetch": False, "current_through": "2026-01-21", "note": "Zoning: Chapter 555 Zoning. ecode360 code NO0456. Code recodified 2024 (Ord. 2296). Chapter 156 is Airport Zoning, a separate chapter. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4204564800': {"code_host": "ecode360", "code_url": "https://ecode360.com/8799872", "plain_fetch": False, "current_through": "2026-02-25", "note": "Zoning: Chapter 325 Zoning. ecode360 code RI0534. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4207933408': {"code_host": "ecode360", "code_url": "https://ecode360.com/37222224", "plain_fetch": False, "current_through": "2026-08-25", "note": "Zoning: Chapter 575 Zoning. ecode360 code HA1359. Hazleton City Zoning Ordinance of 2021 (Ord. 2021-9). An old 1995 scanned PDF at hazletoncity.org/images/Hazleton-Zoning-Ordinance.pdf is superseded. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4213387056': {"code_host": "own site", "code_url": "https://yorktownshippa.gov/wp-content/uploads/Zoning-Ordinance-last-amendment-3-14-23.pdf", "plain_fetch": True, "current_through": None, "note": "Zoning: Zoning Ordinance (Ord. 2012-13), sections numbered 265-xxx. ADU text seen: No ADU term found. Related: Conversion Apartments 265-624. Accessory Farm Dwelling 265-603. Apartment/residence with commercial use 265-608. Not on ecode360. The PDF is 193 pages, text-extractable, and lists on the Ordinances & Studies page (yorktownshippa.gov/?p=20017). Not the City of York. Date shown: Amendments through Ord. 2023-01 (3/14/2023). zoning map amended 8/13/2024."},
    '4200345900': {"code_host": "ecode360", "code_url": "https://ecode360.com/37748731", "plain_fetch": False, "current_through": "2025-09-08", "note": "Zoning: Part 13 Zoning (Zoning Code, Ord. 1540, 6-26-2023). ecode360 code MC4162. Now styled 'Town of McCandless'. Codified ordinances use Part/section numbering (e.g. 1301.260). Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4207784528': {"code_host": "ecode360", "code_url": "https://ecode360.com/13159599", "plain_fetch": False, "current_through": "2026-02-26", "note": "Zoning: Chapter 27 Zoning. ecode360 code WH2503. Not South Whitehall or North Whitehall. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4200350528': {"code_host": "ecode360", "code_url": "https://ecode360.com/11510889", "plain_fetch": False, "current_through": "2026-06-09", "note": "Zoning: Chapter 359 Zoning. ecode360 code MO1197. UNSURE IF CURRENT: older ecode360 snippets show the 1984 ordinance (Ord. 1443). Zoneomics mirrors a new ordinance effective 11-14-2023. Confirm the ecode360 Ch 359 reflects the 2023 rewrite. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4201172824': {"code_host": "ecode360", "code_url": "https://ecode360.com/45165330", "plain_fetch": False, "current_through": "2026-03-23", "note": "Zoning: Chapter 450 Zoning. ecode360 code SP6788. Zoning Ordinance of 2015 (Ord. 415). Chapter 453 is Airport Zoning. Zoneomics carries an older 2007 Ch 27 version (ignore). Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4200369584': {"code_host": "ecode360", "code_url": "https://ecode360.com/9196870", "plain_fetch": False, "current_through": "2025-06-10", "note": "Zoning: Chapter 225 Zoning. ecode360 code SH1304. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4209521648': {"code_host": "ecode360", "code_url": "https://ecode360.com/9647638", "plain_fetch": False, "current_through": "2026-09-23", "note": "Zoning: Chapter 595 Zoning (Easton Zoning Code). ecode360 code EA2741. Zoning map is on easton-pa.zoninghub.com. Proposed amendments (1-23-2025) are on easton-pa.com. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4204375672': {"code_host": "ecode360", "code_url": "https://ecode360.com/11636509", "plain_fetch": False, "current_through": "2026-08-12", "note": "Zoning: Chapter 295 Zoning (Zoning Ordinance of 2010). ecode360 code SW2044. Use code SW2044 (Dauphin). SW2746 is Swatara Twp, Lebanon County: do not confuse. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4208185312': {"code_host": "amlegal", "code_url": "https://codelibrary.amlegal.com/codes/williamsport/latest/williamsport_pa/0-0-0-5800", "plain_fetch": False, "current_through": "2026-05-28", "note": "Zoning: Part Thirteen: Planning and Zoning Code (zoning chapters 13xx, e.g. 1311.63). Plain curl gets HTTP 403 from amlegal. Art. 355 Residential was re-enacted by Ord. 6510 (city document center). An ecode360 WI3701 code also exists but may be another Williamsport (not verified). amlegal is the city's current host."},
    '4200350784': {"code_host": "ecode360", "code_url": "https://ecode360.com/30859895", "plain_fetch": False, "current_through": "2024-05-29", "note": "Zoning: Chapter 27 Zoning. ecode360 code MO1356. ecode360 has not been updated since 2024. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4200361536': {"code_host": "own site", "code_url": "https://www.plumboro.com/sites/g/files/vyhlif3686/f/pages/zoning_ordinance_w-_amendments_2023_0.pdf", "plain_fetch": True, "current_through": None, "note": "Zoning: Plum Borough Zoning Ordinance (with amendments, 2023). ADU text seen: Accessory Dwelling Unit (attached. also 'Mother-in-law Suites'), Section 406. No ecode360, municode or amlegal code found. Linked from plumboro.com/community-development/pages/planning-and-zoning-ordinances. The PDF is 253 pages and text-extractable. Date shown: PDF titled 'with amendments 2023'."},
    '4213372992': {"code_host": "ecode360", "code_url": "https://ecode360.com/5176819", "plain_fetch": False, "current_through": "2026-06-25", "note": "Zoning: Chapter 325 Zoning. ecode360 code SP2128. Cloudflare 'Just a moment' challenge (HTTP 403/429) on plain curl. data read via a real browser session."},
    '4207542168': {"code_host": "ecode360", "code_url": "https://ecode360.com/LE3707", "plain_fetch": False, "current_through": None, "note": "Zoning: Part Thirteen (Planning and Zoning Code), Zoning Ordinance of 2020 (Ord. 1-2020, passed 6-22-2020). conditional uses ref 1314.17. Code root LE3707 seen in ecode360 index URL (ecode360.com/index/LE3707/M). Zoning sections seen at https://ecode360.com/36369818 and https://ecode360.com/36363477 (Ord. 1-2020). Plain curl returns 403 (ecode360 bot block). WebFetch also 403."},
    '4204375528': {"code_host": "ecode360", "code_url": "https://ecode360.com/SU2468", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 27 Zoning (Zoning Map 27-301). Code root from ecode360.com/index/SU2468/C. Search tool described https://ecode360.com/28271833 as zoning ordinance opening sections (not independently verified as chapter id). Zoneomics mirror at zoneomics.com/code/susquehanna-township-PA. ecode360 returns 403 to plain curl."},
    '4209179008': {"code_host": "amlegal", "code_url": "https://codelibrary.amlegal.com/codes/upperdublin/latest/upperdublintwp_pa", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 255 Zoning (Upper Dublin Township Zoning Ordinance of 1956). Township site points to American Legal Publishing. URL is code root (zoning chapter node id not seen). amlegal returns 403 to plain curl. Zoneomics mirror (zoneomics.com/code/upper-dublin-township-PA) shows amendment dated 12-9-2025. A snippet suggested 'supplements through 1-8-2008' but that is probably an old header. currency unconfirmed."},
    '4209135808': {"code_host": "ecode360", "code_url": "https://ecode360.com/HO1764", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 230 Zoning (Horsham Township Zoning Ordinance of 1995). Code id HO1764 seen in index URLs (ecode360.com/index/HO1764/G). Zoning short-title section at https://ecode360.com/9953287. 230-17 allows conversion of single-family dwelling to more families by special exception (not an ADU per se). ecode360 403 to plain curl."},
    '4202984160': {"code_host": "ecode360", "code_url": "https://ecode360.com/WE3779", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 390 Zoning (TDR article 390-196). 2021 codification Ch 1-390. ADU text seen: Search snippet indicated zoning chapter covers accessory dwelling units (section not seen) - unverified. Code id WE3779 from ecode360 help/about URL. ecode360 403 to plain curl."},
    '4202984104': {"code_host": "ecode360", "code_url": "https://ecode360.com/WE1870", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 170 Zoning (170-100 to 170-2504). ecode360 New Laws lists Ord. 2026-02 amending Ch 170 (dated 2026-06-01), so code is recently maintained. ecode360 403 to plain curl."},
    '4202946792': {"code_host": "ecode360", "code_url": "https://ecode360.com/MA0856", "plain_fetch": False, "current_through": "2023-12-19", "note": "Zoning: Zoning Ordinance of 2003 (chapter number unclear: older 220 numbering vs. later 27 citations). Zoning short title pages at https://ecode360.com/31445090. Chapter number ambiguous. verify in TOC. ecode360 403 to plain curl."},
    '4202920864': {"code_host": "ecode360", "code_url": "https://ecode360.com/EA1968", "plain_fetch": False, "current_through": "2023-02-16", "note": "Zoning: Chapter 399 Zoning (Zoning Ordinance of 1989). Code id from ecode360.com/index/EA1968. Short-title section https://ecode360.com/11881522. ecode360 403 to plain curl."},
    '4202982704': {"code_host": "ecode360", "code_url": "https://ecode360.com/WE0442", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 112 Zoning (Borough of West Chester Zoning Ordinance of 2021). Code id from ecode360.com/index/WE0442/D. Zoning intro/short title at https://ecode360.com/6471984 and https://ecode360.com/6471994. ecode360 403 to plain curl."},
    '4202715136': {"code_host": "ecode360", "code_url": "https://ecode360.com/CO1052", "plain_fetch": False, "current_through": "2023-10-19", "note": "Zoning: Chapter 200 Zoning (College Township Zoning Ordinance). Code id from ecode360.com/CO1052/index. Zoning short-title section https://ecode360.com/10705478. ecode360 403 to plain curl."},
    '4207158840': {"code_host": "ecode360", "code_url": "https://ecode360.com/30832287", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 27 Zoning (Ord. 2022-01, 1/10/2022 per Zoneomics). Penn Twp (Manheim, penntwplanco.org) links to eCode. code root PE3692 cited in township's proposed-changes PDF. search identified 30832287 as Chapter 27 page (moderate confidence). ecode360 403 to plain curl."},
    '4201719784': {"code_host": "ecode360", "code_url": "https://ecode360.com/DO1641", "plain_fetch": False, "current_through": "2026-04-20", "note": "Zoning: Chapter 27 Zoning (Doylestown Borough Zoning Ordinance of 1985). use table 27-406. Ord. 2024-5 amended 27-406/27-906. ecode360 403 to plain curl."},
    '4202935536': {"code_host": "ecode360", "code_url": "https://ecode360.com/HO3693", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 27 Zoning (Ord. 196-2018, 9/12/2018). ADU text seen: accessory dwelling unit (freestanding or attached) - 27-1002 Accessory Dwelling Units [Ord. 196-2018. Ord. 211-2025, 7/9/2025] in Part 10 specific use criteria: min 2-acre gross lot, max 1 ADU per property, min 400 sf, Health Dept sewer/water approval, 2 parking spaces/unit, STR must meet 27-1065. Approval: permitted where the district allows the use, via zoning/building permit (district-level path not confirmed). Text read at https://www.zoneomics.com/code/honey-brook-township-PA/chapter_10 (mirror of ecode360 text). CONFIRMED ADU text. Lead said 27-207 - actual standards are 27-1002 (27-207 may be a district use list. not"},
    '4207143816': {"code_host": "ecode360", "code_url": "https://ecode360.com/LI0684", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 122 Zoning. not confirmed. Only evidence: cpo.soar.com summary (12/31/2025) of Ordinance C622 saying staff stated ADUs will be allowed by right in all districts subject to former special-exception standards - a news summary, not code text. Could not retrieve Chapter 122 ADU text (ecode360 403. Zoneomics Lititz pages are empty shells). Ord. 1498-25 (12/8/2025) ADU hits on ecode360 are GETTYSBURG, not Lititz. Likely real but needs manual check of ecode360 Ch 122."},
    '4209152664': {"code_host": "ecode360", "code_url": "https://ecode360.com/NA0447", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 500 Zoning (form-based. TOC page https://ecode360.com/34400015). ADU text seen: accessory dwelling unit - definition 500-1201 (added 4-21-2022 by Ord. 1043: self-contained unit within a detached accessory structure) and standards in 500-602 Accessory buildings [Amended 4-21-2022 by Ord. 1043]: A(2) 'A residence or dwelling shall be permitted as an accessory dwelling unit', C 'Specific to accessory dwelling units' (only on lot with detached house or twin, max 1 per lot, max 2 units combined, may share building with garage, no extra lot area). Approval: appears permitted (by right) as accessory use. conditional use referenced only for historic contributing-resource case. Seen a"},
    '4204548480': {"code_host": "ecode360", "code_url": "https://ecode360.com/ME1269", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 311 Zoning, Article B Hybrid Form-Based Code (applies to R-1..R-4, Office). ADU text seen: accessory dwelling unit (ADU) - definition in 311.A-13 and Article B-XV Accessory Dwelling Units starting 311.B-107 (Purpose and intent). TOC also lists 'Building Form - ADU External'. Approval path not seen. Seen in Zoneomics mirror TOC/definitions https://www.zoneomics.com/code/media-PA/chapter_1 and ecode360 TOC via search. CONFIRMED ADU article exists (definition + Article B-XV heading read). standards text of B-107+ not read. An older ecode360 page with 'supplemental dwelling unit/accessory apartment' (35% / 400 sf) may be pre-form-based text. ecode360 403 to plain curl."},
    '4202960120': {"code_host": "ecode360", "code_url": "https://ecode360.com/47635361", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 27 Zoning (Ord. 2227, 12-10-2013, as amended). ADU text seen: accessory dwelling unit (ADU) - definition added by Ord. 2025-2410 (8/12/2025) (within, attached to, or in accessory building on lot of single-family dwelling). special exception use in RI, TC, MI, NC, CD districts per special-exception use table, with standards '(d) Accessory Dwelling Unit (ADU)': one ADU accessory to single-family detached, twin or townhouse. owner occupancy in perpetuity. parking 1 space. Approval: SPECIAL EXCEPTION. Seen at https://ecode360.com/47635361 (definition, search) and https://www.zoneomics.com/code/phoenixville-PA/chapter_3. CONFIRMED ADU text. code_url is the definitions section page"},
    '4202725624': {"code_host": "ecode360", "code_url": "https://ecode360.com/FE3697", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 27 Zoning (Ord. 1049, 11/18/2019. amended incl. Ord. 1097, 4/16/2024). ADU text seen: accessory dwelling unit - definition in Part 11 (occupied by relatives of owner or caregivers/household staff) plus 'Elder cottage/in-law quarters/carriage house (accessory dwelling unit)' definition (min 600 sf, not counted toward density). ecode360 TOC lists 27-1503 Accessory Dwelling (Part 15 Accessory Uses). Approval path not seen. Definitions read at https://www.zoneomics.com/code/ferguson-township-centre-county-PA/chapter_10. 27-1503 from ecode360 TOC via search (https://www.ecode360.com/32480896). CONFIRMED ADU text (definitions read. 27-1503 heading via search only, body not read). C"},
    '4202758440': {"code_host": "ecode360", "code_url": "https://ecode360.com/42483863", "plain_fetch": False, "current_through": None, "note": "Zoning: Zoning ordinance (Chapter number unclear. one search summary said Chapter 425 - unverified). not confirmed. Searches and a grep of Zoneomics mirror chapters 1-30 (zoneomics.com/code/patton-township-PA) found no accessory dwelling/apartment/in-law/elder cottage text. 42483863 described by search as Patton zoning ordinance page. code root id ambiguous (PA1294 index appeared in Patton results). ecode360 403 to plain curl."},
    '4204575648': {"code_host": "amlegal", "code_url": "https://codelibrary.amlegal.com/codes/swarthmore/latest/swarthm_pa/0-0-0-23482", "plain_fetch": False, "current_through": None, "note": "Zoning: Part Twelve Planning and Zoning Code - Zoning Code (sections 12xx. family/caregiver suite 1264.18). ADU text seen: family/caregiver suite (in-law suite type, internal only) - 1264.18 per Zoneomics cross-ref. allowed by SPECIAL EXCEPTION in all zoning districts. 1 per dwelling. max 35% of combined floor area. may not be in an accessory structure. annual filing of occupant name/relationship. Adopted 2018. Seen at https://codelibrary.amlegal.com/codes/swarthmore/latest/swarthm_pa/0-0-0-23482 (search snippet). CONFIRMED in-law-suite text (not a general ADU. detached units prohibited). Section number 1264.18 from Zoneomics cross-reference, unverified on amlegal. code_url is the section pa"},
    '4202939352': {"code_host": "zoneomics", "code_url": "https://www.zoneomics.com/code/kennett-square-PA/chapter_3", "plain_fetch": True, "current_through": None, "note": "Zoning: Chapter 23 Zoning (Zoning Ordinance of the Borough of Kennett Square. Ord. 761). ADU text seen: accessory dwelling unit (detached, in accessory building) and accessory apartment (within principal dwelling) - definitions in Ch 23 Art. II. 23-30 Accessory uses: '(A) Accessory Habitation: (i) an accessory apartment as an accessory use. (ii) an accessory dwelling unit (limited to one per property)' allowed as accessory uses to residential uses. detached ADU max 25 ft height, 6 ft side/rear setbacks, max 1,000 sf living space and 2 bedrooms, not subdividable. parking 1 space/bedroom (max 2). Approval: allowed accessory use (by right as listed). Seen at https://www.zoneomics.com/code/kenne"},
    '4209138000': {"code_host": "ecode360", "code_url": "https://ecode360.com/JE0687", "plain_fetch": False, "current_through": None, "note": "Zoning: Zoning chapter (Jenkintown Zoning Ordinance of 1941 as revised. amended code adopted 9-13-2010). short-title page https://ecode360.com/11184146. not confirmed. Searches found no Jenkintown ADU section. grep of Zoneomics mirror chapters 1-30 found no accessory dwelling/apartment/in-law text. Unattributed ecode360 ADU snippets ('one ADU per lot, rear yard only') are from another municipality. Borough site also has jenkintownboro.com/zoning-code. ecode360 403 to plain curl."},
    '4209102264': {"code_host": "own site", "code_url": "https://boroughofambler.com/download/code_of_ordinances/code-of-ordinances-by-chapter/Chapter27.pdf", "plain_fetch": True, "current_through": None, "note": "Zoning: Chapter 27 Zoning. ADU text seen: accessory dwelling units (ADUs), detached and attached - definition in 27-202 and 27-407 Accessory Uses: A(8) ADUs listed as use accessory to a dwelling. C 'Additional Requirements for Accessory Dwelling Units': max 1 per property, occupied only when owner's family lives in principal dwelling and by specified relatives, no rental. not a mobile home. Approval: permitted accessory use (zoning permit), family-occupancy restricted. Read in PDF at https://boroughofambler.com/download/code_of_ordinances/code-of-ordinances-by-chapter/Chapter27.pdf. CONFIRMED ADU text (family-only ADU). PDF 269 pages, 858 KB, plain curl 200 with text. Borough also on ecode36"},
    '4200134424': {"code_host": "own site", "code_url": "https://highland.adamscountypa.gov/getmedia/f6af9e19-a9a2-4645-9034-a9cde6880d9e/Highland-Township-Zoning-Ordinance-of-2025-Final-Compiled-v3.pdf", "plain_fetch": True, "current_through": None, "note": "Zoning: Highland Township Zoning Ordinance of 2025 (standalone). ADU text seen: Accessory Dwelling Unit - definition (Art. 2). permitted accessory use in every district (e.g. 505.A 'Accessory Dwelling Unit, in accordance with Section 1502.H.1'. use table shows P in all districts). standards 1502.H.1 (p.177): max 2 occupants who are relatives of principal residents, at least one needing care for illness/age/disability. must be reconvertible. recorded legal mechanism. attached unless detached specifically approved, detached removed within 90 days. Approval: PERMITTED (by right) accessory use, family/care-restricted (ECHO-style). Read in PDF. CONFIRMED ADU text. PDF labelled 'Final Draft - Octo"},
    '4201719792': {"code_host": "ecode360", "code_url": "https://ecode360.com/DO1312", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 175 Zoning (adopted 10-11-1988). chapter page likely https://ecode360.com/10729898. ADU text seen: accessory dwelling unit (formerly 'accessory family apartment') - use H(12) in 175-16 (added 5-4-1993 Ord. 224. amended 2-16-2021 Ord. 401. renamed/amended apparently 2026): 1 per single-family detached, max 25% of floor area, within principal residence or existing accessory structure (e.g. garage), +1 parking space, max 2 occupants, registration with Zoning Officer, deed restriction, Bucks County Board of Health sewage certification. Approval: SPECIAL EXCEPTION in R-1 per 175-37 (cited in 2024 ZHB decision). Text read at https://www.zoneomics.com/code/doylestown-township-PA/cha"},
    '4207115384': {"code_host": "ecode360", "code_url": "https://ecode360.com/CO0213", "plain_fetch": False, "current_through": None, "note": "Zoning: Chapter 220 Zoning (220-31 Additional requirements for accessory uses). not confirmed. Code appears to prohibit apartments/living quarters in accessory structures (snippet, Amended 4-14-2025 by Ord. No. 603 - but Ord. 603 attribution to Columbia is uncertain). April 2026 council approved DCED technical assistance to evaluate ADUs (cpo.soar.com summary) - proposal only. Zoneomics mirror chapters 1-30 grep found no ADU/accessory apartment text."},
}

# Smaller towns whose zoning code has ADU text (confirmed in the code text on 2026-11-11). Up to 15.
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
}

if __name__ == "__main__":
    sys.exit(main())
