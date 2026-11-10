"""Lot-level ADU rule check for Philadelphia pilot lots (today's rules).

Philadelphia Zoning Code 14-604(11), path A (see shared/adu_rules_pa.md):
  RSA-5 or CMX-1, lot 1,600 sq ft or more, detached or semi-detached,
  Council District 1, 2, 3, or 7, and outside the /FNE /NE /FDO /VDO /NDO /EDO overlays
  (the L&I checklist screens these). Even then, only a conversion is allowed
  (inside the house or a garage that existed in 2012), max 800 sq ft, owner on site.
  No new backyard cottage. Anything else needs a ZBA variance.
Historic buildings (path B) are not checked here.

Run (geospatial env), after musa6950 notebook 04 made data/processed/6950_lots_sf.gpkg:
    python shared/lot_rules.py
Output: data/processed/lot_rules_pilot.csv  (lot_id, rule_lot, rule_why, phl_zoning, phl_council)
"""
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RAW, OUT, download, step  # noqa: E402

BASE = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/{}/FeatureServer/0/query"
LAYERS = {"zoning": "Zoning_BaseDistricts", "council": "Council_Districts_2024", "overlays": "Zoning_Overlays"}
ADU_ZONES = {"RSA5", "CMX1"}
ADU_DISTRICTS = {1, 2, 3, 7}
SCREEN_OVERLAYS = ("/FNE", "/NE", "/FDO", "/VDO", "/NDO", "/EDO")
SQFT = 10.7639


def get_layer(key):
    dest = RAW / "rules" / f"phl_{key}.geojson"
    if not dest.exists():
        frames, offset = [], 0
        while True:   # ArcGIS returns at most 2,000 rows per call
            part = dest.with_suffix(f".{offset}.geojson")
            download(BASE.format(LAYERS[key]), part, params={
                "where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson",
                "resultOffset": offset, "resultRecordCount": 2000})
            g = gpd.read_file(part)
            part.unlink()
            frames.append(g)
            if len(g) < 2000:
                break
            offset += 2000
        pd.concat(frames).to_file(dest, driver="GeoJSON")
    return gpd.read_file(dest)


def main():
    step("Philadelphia lot rules (today)")
    lots = gpd.read_file(OUT / "6950_lots_sf.gpkg")
    lots = lots[lots.county == "42101"] if "county" in lots else lots[lots.GEOID.str.startswith("42101")]
    pts = lots[["lot_id", "lot_m2", "geometry"]].copy()
    pts["geometry"] = pts.geometry.representative_point()
    pts = pts.to_crs(4326)

    zoning = get_layer("zoning")[["code", "geometry"]]
    council = get_layer("council")[["district_num", "geometry"]]
    overlays = get_layer("overlays")
    overlays = overlays[overlays.overlay_symbol.fillna("").str.startswith(SCREEN_OVERLAYS)][["overlay_symbol", "geometry"]]

    j = gpd.sjoin(pts, zoning, how="left", predicate="within").drop(columns="index_right")
    j = j[~j.lot_id.duplicated()]
    j = gpd.sjoin(j, council, how="left", predicate="within").drop(columns="index_right")
    j = j[~j.lot_id.duplicated()]
    j["in_overlay"] = j.lot_id.isin(gpd.sjoin(j[["lot_id", "geometry"]], overlays, predicate="within").lot_id)

    zone_ok = j.code.fillna("").str.replace("-", "").isin(ADU_ZONES)
    dist_ok = j.district_num.isin(ADU_DISTRICTS)
    size_ok = j.lot_m2 * SQFT >= 1600
    why = []
    for z, d, s, o, code, num in zip(zone_ok, dist_ok, size_ok, j.in_overlay, j.code, j.district_num):
        miss = []
        if not d:
            miss.append(f"Council District {int(num) if pd.notna(num) else '?'} (needs 1, 2, 3, or 7)")
        if not z:
            miss.append(f"zoned {code or '?'} (needs RSA-5 or CMX-1)")
        if not s:
            miss.append("lot under 1,600 sq ft")
        if o:
            miss.append("inside a screened overlay")
        why.append("; ".join(miss))
    j["rule_lot"] = ["conversion_only" if not w else "variance" for w in why]
    j["rule_why"] = [w if w else "Meets 14-604(11): conversion only, max 800 sq ft, owner on site" for w in why]
    out = j[["lot_id", "rule_lot", "rule_why", "code", "district_num"]].rename(
        columns={"code": "phl_zoning", "district_num": "phl_council"})
    out.to_csv(OUT / "lot_rules_pilot.csv", index=False)
    print(f"  saved lot_rules_pilot.csv ({len(out)} Philadelphia lots)")
    print(out.rule_lot.value_counts().to_string())
    print("  top zoning codes:", out.phl_zoning.value_counts().head(5).to_dict())


if __name__ == "__main__":
    main()
