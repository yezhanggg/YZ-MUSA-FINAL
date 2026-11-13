"""Zoning status and office contacts from DCED Municipal Statistics.

Source: Pennsylvania Department of Community and Economic Development, Municipal Statistics,
report "Municipal/County Planning, Zoning & Building Codes" (CountyMuniBuilding_Excel) and
"County / Municipal Contact Person" (CountyMuniContact), All Counties, exported from
https://apps.dced.pa.gov/Munstats-public/. The fields come from the annual DCED-CLGS-19 report each
municipality files (Land Use Information section). The site says data are refreshed nightly.

zoning_authority from the zoning report:
    municipal  ZONING_ORDINANCE = YES (own or joint ordinance)
    county     no own ordinance, the county files a county zoning ordinance, the municipality says county
               zoning applies, and the county's own list (when it gives one) names the municipality.
               Also any municipality a county web page lists under its county ordinance.
    none       no own ordinance, county zoning NO, and no county list names it
    unknown    the records disagree (county zoning YES but the county files no ordinance or leaves the
               municipality off its list, or the county lists it while it says NO)

A municipality split across counties has a row in each county. A YES in any row counts for all its parts.
Contacts keep only the office phone and website. Street addresses, names and emails are not used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

TYPES = {
    "BORO": "borough",
    "BOROUGH": "borough",
    "TWP": "township",
    "TOWNSHIP": "township",
    "CITY": "city",
    "TOWN": "town",
}
# DCED spelling -> Census spelling, where the two differ by more than spaces and punctuation
NAME_FIX = {("Schuylkill", "UPPERMAHANTANGO"): "UPPERMAHANTONGO"}
REPORT_URL = "https://apps.dced.pa.gov/Munstats-public/ReportInformation2.aspx?report=CountyMuniBuilding_Excel"
CONTACT_URL = "https://apps.dced.pa.gov/Munstats-public/ReportInformation2.aspx?report=CountyMuniContact"


def key(name: str) -> str:
    s = name.upper().replace(".", "").replace("'", "").replace("-", "")
    s = re.sub(r"\bMOUNT\b", "MT", s)
    s = re.sub(r"\bSAINT\b", "ST", s)
    return re.sub(r"\s+", "", s)


def split_name(dced_name: str) -> tuple[str, str | None]:
    m = re.match(r"(.*) (BORO|BOROUGH|TWP|TOWNSHIP|CITY|TOWN)$", dced_name.strip())
    return (key(m.group(1)), TYPES[m.group(2)]) if m else (key(dced_name), None)


def county_title(s: str) -> str:
    return s.strip().title().replace("Mckean", "McKean")


def crosswalk(dced: pd.DataFrame, places: pd.DataFrame, name_col: str, county_col: str) -> pd.Series:
    """GEOID for each DCED municipality row (None when no single match). Match on county and name,
    with the type to break ties (Baldwin borough and Baldwin township)."""
    p = places.assign(k=places.basename.map(key), typ=places.type.where(places.type != "municipality"))
    by_county = {c: g for c, g in p.groupby("county")}
    out: list[str | None] = []
    for name, county in zip(dced[name_col], dced[county_col], strict=True):
        cty = county_title(str(county))
        k, typ = split_name(str(name))
        k = NAME_FIX.get((cty, k), k)
        g = by_county.get(cty)
        if g is None:
            out.append(None)
            continue
        cand = g[(g.k == k) | (g.k == k + "CITY")]
        if len(cand) > 1:
            cand = cand[(cand.typ == typ) | cand.typ.isna()]
        out.append(cand.geoid.iloc[0] if len(cand) == 1 else None)
    return pd.Series(out, index=dced.index, dtype=object)


def _names(cell: object) -> set[str]:
    if not isinstance(cell, str):
        return set()
    return {re.sub(r"\s+", " ", x).strip() for x in cell.split(",") if x.strip()}


@dataclass
class Zoning:
    table: pd.DataFrame  # geoid, zoning_authority, zoning_source, zoning_note, dced flags
    unmatched: list[str]


def read_zoning(path: Path, places: pd.DataFrame, county_lists: pd.DataFrame | None = None) -> Zoning:
    d = pd.read_csv(path, dtype=str).rename(columns={"MUNICIPALITY ID": "MUNICIPALITY_ID"})
    is_county = d.MUNICIPALITY_NAME.str.endswith(" COUNTY")
    cty = d[is_county].set_index("COUNTY_NAME")
    m = d[~is_county].copy()
    m["geoid"] = crosswalk(m, places, "MUNICIPALITY_NAME", "COUNTY_NAME")
    unmatched = sorted(m[m.geoid.isna()].MUNICIPALITY_NAME + " (" + m[m.geoid.isna()].COUNTY_NAME + ")")
    m = m[m.geoid.notna()]
    county_has = {c: r["ZONING_ORDINANCE"] == "YES" for c, r in cty.iterrows()}
    county_list = {c: _names(r["ZONING_MUNICIPALITIES"]) for c, r in cty.iterrows()}

    rows = []
    recs: list[dict[str, Any]] = m.to_dict("records")  # type: ignore[assignment]
    for r in recs:
        own = r["ZONING_ORDINANCE"] == "YES"
        says_county = r["COUNTY_ZONING"] == "YES"
        has_ord = county_has.get(r["COUNTY_NAME"], False)
        lst = county_list.get(r["COUNTY_NAME"], set())
        listed = re.sub(r"\s+", " ", str(r["MUNICIPALITY_NAME"])).strip() in lst
        if own:
            auth, note = "municipal", None
        elif says_county and has_ord and (not lst or listed):
            auth, note = "county", None
        elif says_county and not has_ord:
            auth, note = (
                "unknown",
                "Files no zoning ordinance and says county zoning applies, but the county files no county zoning ordinance",
            )
        elif says_county:
            auth, note = (
                "unknown",
                "Files no zoning ordinance and says county zoning applies, but the county's list leaves it out",
            )
        elif has_ord and listed:
            auth, note = (
                "unknown",
                "Files no zoning ordinance and says no county zoning, but the county lists it under the county ordinance",
            )
        else:
            auth, note = "none", None
        rows.append(
            {
                "geoid": r["geoid"],
                "dced_id": r["MUNICIPALITY_ID"],
                "dced_name": r["MUNICIPALITY_NAME"],
                "dced_zoning_ordinance": r["ZONING_ORDINANCE"],
                "dced_county_zoning": r["COUNTY_ZONING"],
                "dced_joint_with": r["ZONING_MUNICIPALITIES"] if isinstance(r["ZONING_MUNICIPALITIES"], str) else None,
                "zoning_authority": auth,
                "zoning_source": "dced",
                "zoning_note": note,
            }
        )
    z = pd.DataFrame(rows)
    # A split municipality: a YES in any county row counts for every part
    main = places.set_index("geoid").main_geoid
    z["main_geoid"] = z.geoid.map(main)
    rank = {"municipal": 0, "county": 1, "none": 2, "unknown": 3}
    z["_r"] = z.zoning_authority.map(rank)
    best = z.sort_values(["main_geoid", "_r", "geoid"]).drop_duplicates("main_geoid").set_index("main_geoid")
    full = places[["geoid", "main_geoid"]].merge(z.drop(columns=["main_geoid", "_r"]), on="geoid", how="left")
    miss = full.zoning_authority.isna()
    for col in ["zoning_authority", "zoning_source", "zoning_note"]:
        full.loc[miss, col] = full.loc[miss, "main_geoid"].map(best[col])
    disagree = z.groupby("main_geoid").zoning_authority.nunique()
    for mg in disagree[disagree > 1].index:
        sel = full.main_geoid == mg
        full.loc[sel, "zoning_authority"] = best.loc[mg, "zoning_authority"]
        full.loc[sel, "zoning_note"] = (
            "DCED rows for the parts of this split municipality disagree. A municipal ordinance in any part counts for all"
        )
    full["zoning_authority"] = full.zoning_authority.fillna("unknown")
    full.loc[full.zoning_source.isna(), "zoning_note"] = "Not in the DCED report"
    full["zoning_source"] = full.zoning_source.fillna("dced")

    # County web pages that list the places under a county ordinance win over the DCED filing
    if county_lists is not None and len(county_lists):
        cl = county_lists.copy()
        geo = places.assign(k=places.name.str.lower())
        idx = {(c, k): g for c, k, g in zip(geo.county, geo.k, geo.geoid, strict=True)}
        cl_recs: list[dict[str, Any]] = cl.to_dict("records")  # type: ignore[assignment]
        for c in cl_recs:
            gid = idx.get((str(c["county"]), str(c["municipality"]).lower()))
            if gid is None:
                continue
            sel = full.geoid == gid
            before = full.loc[sel, "zoning_authority"].iloc[0]
            full.loc[sel, "zoning_authority"] = "county"
            full.loc[sel, "zoning_source"] = str(c["source_id"])
            if before != "county":
                full.loc[sel, "zoning_note"] = (
                    f"The county page lists it under the county ordinance. DCED filing reads {before}"
                )
            else:
                full.loc[sel, "zoning_note"] = None
    return Zoning(full.drop(columns=["main_geoid"]), unmatched)


def read_contacts(path: Path, places: pd.DataFrame) -> pd.DataFrame:
    """geoid, phone, url from the contact report. Street addresses, names and emails are not used."""
    d = pd.read_csv(path, dtype=str)
    d = d[d["County Name"].notna() & d["Municipality Name"].notna()]
    d = d[~d["Municipality Name"].str.endswith(" COUNTY")].copy()
    d["geoid"] = crosswalk(d, places, "Municipality Name", "County Name")
    d = d[d.geoid.notna()]

    def phone(p: object) -> str | None:
        if not isinstance(p, str) or not re.search(r"\d{3}.*\d{4}", p):
            return None
        return re.sub(r"[^0-9)]+$", "", re.sub(r"\s+", " ", p).strip())

    def url(u: object) -> str | None:
        if not isinstance(u, str) or "." not in u:
            return None
        u = u.strip()
        return u if u.lower().startswith("http") else "http://" + u

    out = pd.DataFrame(
        {
            "geoid": d.geoid,
            "phone": d.Phone.map(phone),
            "url": d.Website.map(url),
        }
    )
    out = out[out[["phone", "url"]].notna().any(axis=1)]
    # split municipalities: the part with an entry lends it to the other parts
    main = places.set_index("geoid").main_geoid
    out["main_geoid"] = out.geoid.map(main)
    first = out.sort_values("geoid").drop_duplicates("main_geoid").set_index("main_geoid")
    full = places[["geoid", "main_geoid"]].merge(out.drop(columns=["main_geoid"]), on="geoid", how="left")
    miss = full.phone.isna() & full.url.isna()
    for col in ["phone", "url"]:
        full.loc[miss, col] = full.loc[miss, "main_geoid"].map(first[col])
    return full.drop(columns=["main_geoid"])
