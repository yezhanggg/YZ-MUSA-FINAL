"""Planning-agency ADU inventories: what a county or regional agency reported, municipality by municipality.

Input: raw/places/inventories/inventory_rows.csv, one row per municipality per inventory, columns
    source_id, publisher, title, doc_url, locator, inventory_date, county, municipality, muni_type,
    reported_text, status, status_detail, unit_types, approval, notes
Rows are transcribed from the inventory, never inferred. A row with no status is kept as evidence
but does not set a status. Everything here is "reported", never "verified".
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.places_index.dced import county_title, key
from pipeline.places_index.ladder import APPROVALS, UNIT_TYPES

REPORTED_STATUSES = ("by_right", "limited", "not_addressed", "prohibited")
COLUMNS = [
    "source_id",
    "publisher",
    "title",
    "doc_url",
    "locator",
    "inventory_date",
    "county",
    "municipality",
    "muni_type",
    "reported_text",
    "status",
    "status_detail",
    "unit_types",
    "approval",
    "notes",
]
SUFFIX = re.compile(r"^(.*?)\s+(city|borough|boro\.?|township|twp\.?|town|municipality)$", re.I)
TYPE_WORD = {"boro": "borough", "boro.": "borough", "twp": "township", "twp.": "township"}


def _split(name: str, muni_type: str | None) -> tuple[str, str | None]:
    """Name key and type. "Abington Township" -> (ABINGTON, township). The type column wins when given."""
    n = name.strip()
    m = SUFFIX.match(n)
    typ = None
    if m:
        n, word = m.group(1), m.group(2).lower()
        typ = TYPE_WORD.get(word, word)
    if isinstance(muni_type, str) and muni_type.strip():
        typ = muni_type.strip().lower()
    return key(n), typ


def match(rows: pd.DataFrame, places: pd.DataFrame) -> pd.Series:
    """GEOID for each inventory row: county and name, type when given. None when not one match."""
    p = places.assign(k=places.basename.map(key))
    by_county = {c: g for c, g in p.groupby("county")}
    out: list[str | None] = []
    for county, name, typ in zip(rows.county, rows.municipality, rows.muni_type, strict=True):
        g = by_county.get(county_title(str(county)))
        if g is None or not isinstance(name, str):
            out.append(None)
            continue
        k, t = _split(name, typ)
        cand = g[(g.k == k) | (g.k == k + "CITY")]
        if t and len(cand) > 1:
            cand = cand[(cand.type == t) | (cand.type == "municipality")]
        out.append(cand.geoid.iloc[0] if len(cand) == 1 else None)
    return pd.Series(out, index=rows.index, dtype=object)


def read_inventories(path: Path | None, places: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(matched rows with geoid, unmatched rows). Missing file: two empty frames."""
    if path is None or not Path(path).exists():
        empty = pd.DataFrame(columns=[*COLUMNS, "geoid"])
        return empty, empty
    d = pd.read_csv(path, dtype=str).reindex(columns=COLUMNS)
    d["status"] = d.status.where(d.status.isin(REPORTED_STATUSES))
    d["approval"] = d.approval.where(d.approval.isin(APPROVALS))
    d["geoid"] = match(d, places)
    return d[d.geoid.notna()].copy(), d[d.geoid.isna()].copy()


def parse_types(cell: Any) -> list[str] | None:
    if not isinstance(cell, str) or not cell.strip():
        return None
    out = {x.strip() for x in cell.split(";")}
    return [u for u in UNIT_TYPES if u in out]


def _text(row: Any) -> str:
    parts = [getattr(row, c, None) for c in ("reported_text", "status_detail", "notes")]
    return " ".join(p for p in parts if isinstance(p, str)).lower()


def says_no_zoning(row: Any) -> bool:
    """The inventory itself says the place had no zoning code. Its "permitted" then means no zoning
    rule applied at the time, not an ADU rule."""
    return "no local zoning" in _text(row) or "no zoning" in _text(row)


def _date(cell: Any) -> str | None:
    return cell.strip() if isinstance(cell, str) and cell.strip() else None


def pick(rows: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Best inventory row per place: the newest dated inventory with a status. Others stay as evidence.
    A row without a date cannot set a status (every status needs a dated source)."""
    out: dict[str, dict[str, Any]] = {}
    if rows.empty:
        return out
    r = rows[rows.status.notna() & rows.inventory_date.map(_date).notna()].copy()
    r = r.sort_values(["geoid", "inventory_date", "source_id"], ascending=[True, False, True])
    for gid, g in r.groupby("geoid", sort=True):
        top = g.iloc[0]
        detail = top.status_detail if isinstance(top.status_detail, str) and top.status_detail else None
        out[str(gid)] = {
            "status": top.status,
            "status_detail": f"{detail} (inventory dated {top.inventory_date})" if detail else None,
            "unit_types": parse_types(top.unit_types),
            "approval": top.approval if isinstance(top.approval, str) else None,
            "source": {
                "name": f"{top.publisher}: {top.title}",
                "url": top.doc_url,
                "date": top.inventory_date,
            },
            "source_id": top.source_id,
            "says_no_zoning": says_no_zoning(top),
            "use_check": "placed this use in the adu column" in _text(top),
            "others": [
                {"source_id": o.source_id, "status": o.status, "date": o.inventory_date}
                for o in g.iloc[1:].itertuples()
            ],
        }
    return out


def notes(rows: pd.DataFrame) -> dict[str, str]:
    """A short note per place from inventory rows that set no status (no status given, or no date).
    Used only as words beside an unknown status, never as a status."""
    out: dict[str, str] = {}
    if rows.empty:
        return out
    used = rows.status.notna() & rows.inventory_date.map(_date).notna()
    r = rows[~used].copy()
    r["_d"] = r.inventory_date.fillna("")
    r = r.sort_values(["geoid", "_d", "source_id"], ascending=[True, False, True])
    for gid, g in r.groupby("geoid", sort=True):
        top = g.iloc[0]
        text = top.status_detail if isinstance(top.status_detail, str) and top.status_detail else top.reported_text
        if not isinstance(text, str) or not text:
            continue
        when = top.inventory_date if _date(top.inventory_date) else "undated"
        out[str(gid)] = f"Inventory note, no status claimed ({top.publisher}, {when}): {text}"
    return out


def no_zoning(rows: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Dated inventory rows with no ADU status that say the place has no zoning: a county list of
    unzoned places. geoid -> {source_id, source}."""
    out: dict[str, dict[str, Any]] = {}
    if rows.empty:
        return out
    r = rows[rows.status.isna() & rows.inventory_date.map(_date).notna()]
    for row in r.sort_values(["geoid", "inventory_date"], ascending=[True, False]).itertuples():
        if str(row.geoid) in out or not says_no_zoning(row):
            continue
        out[str(row.geoid)] = {
            "source_id": row.source_id,
            "source": {"name": f"{row.publisher}: {row.title}", "url": row.doc_url, "date": row.inventory_date},
        }
    return out
