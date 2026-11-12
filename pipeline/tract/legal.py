"""Legal class of every town for the ADU forecast, from the town rule files.

Source: shared/rules/towns_index.json and the rule file each entry points to. Town files hold
`adu.status`. Philadelphia and Pittsburgh have full rule files instead, and their class is read
from the lot results (pipeline/build_lots.py), which apply those files to every lot.

    adu.status          legal class       what it means for a new ADU
    allowed_by_right    by_right          a zoning permit, no hearing
    special_exception   discretionary     a hearing (zoning board or governing body)
    conditional_use     discretionary
    family_only         family_only       allowed only for relatives, so not a rental
    conversion_only     conversion_only   only inside the house or an existing building
    not_addressed       none              the code has no ADU use, so a variance at best
    prohibited          none
    (no rule file)      unknown           statewide baseline: zoning is local and not yet read

Index entries marked `todo` have no reviewed file and count as unknown. `drafted` files are used
but flagged. The factor for each class is in shared/assumptions.json (tract.forecast.legal_class_factor).

Run:  python -m pipeline.tract.legal
Saves data/processed/town_legal_class.csv (one row per 2020 county subdivision).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from pipeline.paths import data_root
from pipeline.rules import RULES_DIR
from pipeline.tract.io import PROCESSED

STATUS_CLASS = {
    "allowed_by_right": "by_right",
    "special_exception": "discretionary",
    "conditional_use": "discretionary",
    "family_only": "family_only",
    "conversion_only": "conversion_only",
    "not_addressed": "none",
    "prohibited": "none",
}
CLASSES = ("by_right", "discretionary", "family_only", "conversion_only", "none", "unknown")
# Old forecast vocabulary (shared/legal_status.csv), kept as rule_today in forecast_town.csv
OLD_VOCAB = {
    "by_right": "allowed",
    "discretionary": "limited",
    "family_only": "limited",
    "conversion_only": "limited",
    "unknown": "limited",
    "none": "not_allowed",
}
CITY_FILES = {"philadelphia": "4210160000", "pittsburgh": "4200361000"}


def _value(x: Any) -> Any:
    return x.get("value") if isinstance(x, dict) else x


def town_status(entry: dict[str, Any]) -> dict[str, Any]:
    """adu.status of one index entry, read from its rule file."""
    out: dict[str, Any] = {"status": None, "scope_note": None}
    path = RULES_DIR / f"{entry['file']}.json"
    if entry["status"] == "todo" or not path.exists():
        return out
    adu = json.loads(path.read_text()).get("adu") or {}
    out["status"] = _value(adu.get("status"))
    scope = _value(adu.get("scope_districts"))
    if scope:
        out["scope_note"] = f"{out['status']} only in {', '.join(scope)}, {_value(adu.get('status_outside'))} elsewhere"
    return out


def city_status(place: str) -> tuple[str, str]:
    """Class for the two cities from their lot results: what a lot can do today."""
    lots = pd.read_parquet(
        data_root() / "lots" / place / "index.parquet",
        columns=["allowed_today", "approval_today", "approval_detached_today", "approval_internal_today"],
    )
    by_right = (lots.approval_today == "by_right").mean()
    detached_any = lots.approval_detached_today.isin(["by_right", "administrator_exception", "special_exception"])
    if by_right > 0.5:
        note = f"by right on {by_right:.0%} of lots (detached in the yard: {lots.approval_detached_today.mode()[0]})"
        return "allowed_by_right", note
    note = (
        f"legal path on {lots.allowed_today.mean():.1%} of lots, all conversions. "
        f"New detached units: {detached_any.mean():.0%} of lots"
    )
    return "conversion_only", note


def classes(index_path: Path | None = None) -> pd.DataFrame:
    idx = json.loads((index_path or RULES_DIR / "towns_index.json").read_text())
    rows = []
    for e in idx["towns"]:
        if e["file"] in CITY_FILES:
            status, note = city_status(e["file"])
        else:
            s = town_status(e)
            status, note = s["status"], s["scope_note"]
        cls = STATUS_CLASS.get(status, "unknown") if status else "unknown"
        for g in [e["geoid"], *e.get("geoid_aliases", [])]:
            rows.append(
                {
                    "town_geoid": g,
                    "index_name": e["name"],
                    "rule_file": e["file"] if status else None,
                    "review": e["status"] if status else "todo",
                    "adu_status": status,
                    "legal_class": cls,
                    "note": note,
                    "pop_2020_index": e["population"],
                }
            )
    return pd.DataFrame(rows)


def town_table(towns: pd.DataFrame, cls: pd.DataFrame) -> pd.DataFrame:
    """Every 2020 county subdivision with its class. Towns without a file are unknown."""
    t = towns[["GEOID", "NAMELSAD"]].rename(columns={"GEOID": "town_geoid", "NAMELSAD": "name"})
    t = t.merge(cls, on="town_geoid", how="left")
    t["legal_class"] = t.legal_class.fillna("unknown")
    t["review"] = t.review.fillna("none")
    t["has_rule_file"] = t.rule_file.notna()
    t["rule_today"] = t.legal_class.map(OLD_VOCAB)
    return t


def coverage(t: pd.DataFrame, pop: pd.Series) -> pd.DataFrame:
    """Towns and people (ACS 2020-24, split to towns) in each class, with drafted files counted apart."""
    x = t.assign(pop=t.town_geoid.map(pop).fillna(0))
    g = x.groupby("legal_class").agg(
        towns=("town_geoid", "size"),
        towns_drafted=("review", lambda s: int((s == "drafted").sum())),
        pop=("pop", "sum"),
    )
    g["pop_drafted"] = x[x.review == "drafted"].groupby("legal_class")["pop"].sum()
    g["pop_drafted"] = g.pop_drafted.fillna(0)
    g["share_of_pa_pop"] = g["pop"] / x["pop"].sum()
    return g.reindex(CLASSES).fillna(0).reset_index()


def build(save: bool = True) -> pd.DataFrame:
    towns = gpd.read_file(PROCESSED / "towns_2020.gpkg", ignore_geometry=True)
    t = town_table(towns, classes())
    if save:
        t.to_csv(PROCESSED / "town_legal_class.csv", index=False)
    return t


def main() -> None:
    argparse.ArgumentParser(description="Legal class of every town from the rule files").parse_args()
    t = build()
    print(t[t.has_rule_file][["name", "review", "adu_status", "legal_class", "note"]].to_string(index=False))
    print(t.legal_class.value_counts())


if __name__ == "__main__":
    main()
