"""Where the builder reads from and writes to. Tests pass their own Inputs with fixture paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pipeline.paths import data_root

REPO = Path(__file__).resolve().parents[2]
RULES_DIR = REPO / "shared" / "rules"
APP_DATA = REPO / "app" / "public" / "data"


def raw_places() -> Path:
    """Raw downloads for this table: <data root>/raw/places."""
    return data_root() / "raw" / "places"


def census_cache() -> Path:
    return Path(os.environ.get("TOWN_TARGETS_CACHE", data_root() / "cache" / "census"))


@dataclass(frozen=True)
class Inputs:
    """Every file the build reads. A missing optional file is treated as empty."""

    # Census 2020 PL 94-171 zip (county subdivisions) or a small CSV with the same columns (tests)
    census_pl_zip: Path | None = None
    census_csv: Path | None = None
    # Census Vintage 2025 subcounty population estimates
    pep_csv: Path | None = None
    # DCED Municipal Statistics exports (raw/places/dced)
    dced_zoning_csv: Path | None = None
    dced_contact_csv: Path | None = None
    # County pages that list the municipalities under a county zoning ordinance
    county_lists_csv: Path | None = None
    # Planning-agency ADU inventories, one row per municipality per inventory
    inventory_csv: Path | None = None
    inventory_sources_json: Path | None = None
    # Registry of the raw sources (publisher, url, date, licence): raw/places/SOURCES.json
    sources_json: Path | None = None
    # Hand-read rule files and their index
    rules_dir: Path = RULES_DIR
    # Tier B corpus manifest (places with searchable public zoning text)
    tierb_manifest: Path | None = None
    # Build date written to the meta file (fixed in tests so the output is byte-stable)
    built_on: str | None = None


def default_inputs() -> Inputs:
    raw = raw_places()
    root = data_root()
    return Inputs(
        census_pl_zip=census_cache() / "pa2020.pl.zip",
        pep_csv=root / "data" / "raw" / "5500" / "pop" / "sub-est2025_42.csv",
        dced_zoning_csv=raw / "dced" / "CountyMuniBuilding_Excel.csv",
        dced_contact_csv=raw / "dced" / "CountyMuniContact_office.csv",
        county_lists_csv=raw / "county_lists" / "county_zoning_lists.csv",
        inventory_csv=raw / "inventories" / "inventory_rows.csv",
        inventory_sources_json=raw / "inventories" / "SOURCES_inventories.json",
        sources_json=raw / "SOURCES.json",
        rules_dir=RULES_DIR,
        tierb_manifest=root / "corpus" / "tierb" / "manifest.json",
    )


def out_paths() -> dict[str, Path]:
    """Outputs: the app data file and its meta, and the fuller tables on the data drive."""
    proc = data_root() / "processed" / "places"
    return {
        "app_json": APP_DATA / "pa_places.json",
        "app_meta": APP_DATA / "pa_places_meta.json",
        "table_csv": proc / "pa_places.csv",
        "conflicts_csv": proc / "pa_places_conflicts.csv",
    }
