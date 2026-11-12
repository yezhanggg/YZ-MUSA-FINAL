"""Slope maths of pipeline/terrain.py on synthetic ground with a known slope. No data drive needed."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import shapely

pytest.importorskip("rasterio")
pytest.importorskip("scipy")

from pipeline import terrain  # noqa: E402

CELL = 3.0


def plane(rows: int, cols: int, grade: float, cell: float = CELL) -> np.ndarray:
    """Ground rising `grade` (rise over run) toward grid east."""
    x = np.arange(cols) * cell
    return np.tile(grade * x, (rows, 1))


def test_horn_on_a_plane() -> None:
    s = terrain.horn_slope_pct(plane(20, 30, 0.2), CELL)
    assert np.isnan(s[0]).all() and np.isnan(s[:, 0]).all()
    assert np.allclose(s[1:-1, 1:-1], 20.0)
    # A diagonal plane: 3 in x and 4 in y gives 5 (percent x 100).
    y = np.arange(20)[:, None] * CELL
    x = np.arange(30)[None, :] * CELL
    s2 = terrain.horn_slope_pct(0.03 * x + 0.04 * y, CELL)
    assert np.allclose(s2[1:-1, 1:-1], 5.0)


def test_horn_nan_spreads_to_neighbors() -> None:
    z = plane(10, 10, 0.1)
    z[5, 5] = np.nan
    s = terrain.horn_slope_pct(z, CELL)
    assert np.isnan(s[4:7, 4:7]).all() and np.isfinite(s[2, 2])


def test_stats_over_a_square() -> None:
    surf = terrain.Surface.from_z(plane(40, 40, 0.3) + 100.0, 0.0, 120.0, CELL)
    sq = shapely.box(30, 30, 60, 60)  # 30 ft square, inside the grid
    st = surf.stats(sq, elevation=True)
    assert st is not None
    assert st["mean_pct"] == pytest.approx(30.0) and st["p90_pct"] == pytest.approx(30.0)
    assert st["share_over_15"] == 1.0 and st["share_over_25"] == 1.0
    # Cell centers inside run from x = 31.5 to 58.5: 27 ft at 0.3 is 8.1 ft of drop.
    assert st["drop_ft"] == pytest.approx(8.1, abs=0.05)
    gentle = terrain.Surface.from_z(plane(40, 40, 0.1), 0.0, 120.0, CELL).stats(sq)
    assert gentle is not None and gentle["share_over_15"] == 0.0 and gentle["mean_pct"] == pytest.approx(10.0)


def test_tiny_polygon_uses_touched_cells() -> None:
    surf = terrain.Surface.from_z(plane(20, 20, 0.2), 0.0, 60.0, CELL)
    st = surf.stats(shapely.box(30.2, 30.2, 30.8, 30.8))
    assert st is not None and st["mean_pct"] == pytest.approx(20.0)


def test_outside_or_nodata_gives_none() -> None:
    surf = terrain.Surface.from_z(np.full((20, 20), np.nan), 0.0, 60.0, CELL)
    assert surf.stats(shapely.box(10, 10, 40, 40)) is None
    surf2 = terrain.Surface.from_z(plane(20, 20, 0.2), 0.0, 60.0, CELL)
    assert surf2.stats(shapely.box(500, 500, 520, 520)) is None


def test_slope_class() -> None:
    th = terrain.Thresholds(15.0, 25.0)
    assert terrain.slope_class(14.9, th) == "ordinary"
    assert terrain.slope_class(15.0, th) == "moderate"
    assert terrain.slope_class(31.0, th) == "steep"
    assert terrain.slope_class(None, th) is None


def half_steep() -> terrain.Surface:
    """West part (x < 60 ft) at 40 percent, east part flat."""
    cols, rows = 50, 40
    x = np.arange(cols) * CELL
    zrow = np.where(x < 60, 0.4 * x, 0.4 * 60)
    return terrain.Surface.from_z(np.tile(zrow, (rows, 1)), 0.0, rows * CELL, CELL)


def test_gentle_fit_keeps_out_of_steep_ground() -> None:
    surf, th = half_steep(), terrain.Thresholds(15.0, 25.0)
    keep = shapely.box(6, 6, 144, 114)
    rec = {"fits": True, "largest_sqft": 1000.0, "angle_deg": 0.0}
    g = terrain.gentle_fit(surf, keep, rec, None, th)
    # Gentle ground runs from about x = 60 to 144 ft and y = 6 to 114 ft.
    assert g["fits"] and g["largest_sqft"] == 1000
    assert g["steep_cut_sqft"] > 50 * 100
    assert 75 * 100 <= g["room_sqft"] <= 85 * 108
    # Only steep ground in the yard: the spot has nowhere to go.
    g2 = terrain.gentle_fit(surf, shapely.box(6, 6, 54, 114), rec, None, th)
    assert not g2["fits"] and g2["largest_sqft"] == 0
    # Never yes where the saved fit says no.
    assert not terrain.gentle_fit(surf, keep, {"fits": False, "largest_sqft": 0}, None, th)["fits"]


def test_gentle_fit_unchanged_on_flat_ground() -> None:
    surf = terrain.Surface.from_z(plane(40, 40, 0.05), 0.0, 120.0, CELL)
    g = terrain.gentle_fit(
        surf, shapely.box(10, 10, 100, 100), {"fits": True, "largest_sqft": 600.0}, None, terrain.Thresholds(15, 25)
    )
    assert g == {"fits": True, "largest_sqft": 600, "room_sqft": None, "steep_cut_sqft": 0.0}


def test_small_steep_specks_are_ignored() -> None:
    z = plane(40, 40, 0.0)
    z[20, 20] = 3.5  # one bump: four steep cells around it, none touching another
    surf = terrain.Surface.from_z(z, 0.0, 120.0, CELL)
    assert surf.steep_ground(shapely.box(3, 3, 117, 117), 25.0).is_empty


def test_lot_terrain_block_and_class() -> None:
    surf, th = half_steep(), terrain.thresholds()
    lot = shapely.box(0, 0, 150, 120)
    keep = shapely.box(6, 6, 144, 114)
    spot = shapely.box(10, 10, 40, 30)  # on the steep part
    fits = {s: {"fits": True, "largest_sqft": 600.0, "angle_deg": 0.0} for s in terrain.SCENARIOS}
    block = terrain.lot_terrain(
        surf,
        lot,
        dict.fromkeys(terrain.SCENARIOS, keep),
        dict.fromkeys(terrain.SCENARIOS, spot),
        fits,
        dict.fromkeys(terrain.SCENARIOS),
        {
            "source": "test",
            "resolution_ft": CELL,
            "thresholds_pct": {"moderate": th.moderate_pct, "steep": th.steep_pct},
        },
    )
    sp = block["spot"]["today"]
    assert sp["mean_pct"] == pytest.approx(40.0) and sp["class"] == "steep"
    assert block["basis"] == "spot_today" and block["steep_site"] is True and block["slope_class"] == "steep"
    assert block["gentle_fit"]["today"]["fits"] is True
    assert sp["drop_ft"] == pytest.approx(0.4 * 27, abs=0.1)


def write_utm_plane(path: Path, bounds_utm: tuple[float, float, float, float], grade: float) -> None:
    """A 1 m DEM in UTM 17N (metres) rising `grade` toward east, like a 3DEP tile."""
    import rasterio
    from rasterio.transform import from_origin

    x0, y0, x1, y1 = bounds_utm
    w, h = int(x1 - x0), int(y1 - y0)
    z = (300.0 + grade * np.arange(w))[None, :].repeat(h, axis=0).astype("float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=w,
        height=h,
        count=1,
        dtype="float32",
        crs="EPSG:26917",
        transform=from_origin(x0, y1, 1.0, 1.0),
        nodata=-999999.0,
    ) as dst:
        dst.write(z, 1)


def write_dem_source(root: Path, place: str, bounds_utm: tuple[float, float, float, float], grade: float) -> None:
    d = root / "raw" / "elevation" / place
    d.mkdir(parents=True, exist_ok=True)
    write_utm_plane(d / "tile.tif", bounds_utm, grade)
    (d / "SOURCES.json").write_text(
        json.dumps(
            {
                "dem": {
                    "source_key": "test:plane",
                    "title": "a test plane",
                    "files": ["tile.tif"],
                    "flown_from": "2024-04-14",
                    "flown_to": "2025-04-02",
                    "license": "public domain",
                }
            }
        )
    )


def test_read_warps_utm_metres_to_local_feet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pyproj import Transformer

    monkeypatch.setenv("ADU_DATA_DIR", str(tmp_path))
    # A patch of Pittsburgh in EPSG:2272 feet and the same ground in UTM metres.
    box2272 = (1340000.0, 410000.0, 1340600.0, 410600.0)
    t = Transformer.from_crs(2272, 26917, always_xy=True)
    xs, ys = t.transform([box2272[0], box2272[2]], [box2272[1], box2272[3]])
    write_dem_source(tmp_path, "pittsburgh", (min(xs) - 100, min(ys) - 100, max(xs) + 100, max(ys) + 100), 0.12)
    assert terrain.available("pittsburgh")
    surf = terrain.Surface.read(terrain.dem_vrt("pittsburgh"), box2272, 2272)
    st = surf.stats(shapely.box(1340100, 410100, 1340500, 410500), elevation=True)
    assert st is not None
    # 12 percent in metres is 12 percent in feet. UTM east and grid east differ by under 2 degrees,
    # which does not change the magnitude.
    assert st["mean_pct"] == pytest.approx(12.0, abs=0.2) and st["share_over_15"] == 0.0
    # 400 ft across at 12 percent, measured between cell centers.
    assert st["drop_ft"] == pytest.approx(0.12 * 400, rel=0.03)
