"""tools/terrain_tiles.py: tile ids, Terrarium encoding and the PMTiles writer (no drive needed)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import terrain_tiles as tt  # noqa: E402


def test_tile_ids_round_trip() -> None:
    assert tt.zxy_to_tileid(0, 0, 0) == 0
    assert [tt.zxy_to_tileid(1, x, y) for x, y in ((0, 0), (0, 1), (1, 1), (1, 0))] == [1, 2, 3, 4]
    for z, x, y in ((16, 19028, 24666), (10, 297, 385), (5, 3, 30)):
        assert tt.tileid_to_zxy(tt.zxy_to_tileid(z, x, y)) == (z, x, y)


def test_terrarium_round_trip() -> None:
    h = np.array([[-10.0, 0.0], [123.45, 1290.06]])
    back = tt.decode_terrarium(tt.terrarium(h, 0.1))
    assert np.allclose(back, np.round(h, 1), atol=0.005)


def test_pmtiles_write_and_read(tmp_path: Path) -> None:
    tiles = {tt.zxy_to_tileid(16, 19028 + i, 24666 + j): bytes([i, j]) * 10 for i in range(80) for j in range(80)}
    tiles[tt.zxy_to_tileid(10, 297, 385)] = bytes([1, 0]) * 10  # same bytes as another tile: stored once
    out = tmp_path / "t.pmtiles"
    tt.write_pmtiles(out, tiles, 10, 16, (-75.5, 40.5, -75.4, 40.6), {"name": "t"})
    head, index = tt.read_pmtiles_index(out)
    assert head["minzoom"] == 10 and head["maxzoom"] == 16 and head["tile_type"] == 2
    raw = out.read_bytes()
    assert set(index) == set(tiles)
    for tid, body in tiles.items():
        off, length = index[tid]
        assert raw[off : off + length] == body


@pytest.mark.parametrize("step", [0.1, 1.0])
def test_step_rounds(step: float) -> None:
    h = np.array([[10.04, 10.06]])
    assert np.allclose(tt.decode_terrarium(tt.terrarium(h, step)), np.round(h / step) * step, atol=0.005)


def test_lot_tile_mask_keeps_tiles_near_lots_only(tmp_path) -> None:
    import pandas as pd

    from tools import terrain_tiles as tt

    (tmp_path / "p").mkdir()
    # Two lots far apart: the mask holds their tiles and rings, not the land between.
    pd.DataFrame({"lon": [-75.6, -75.2], "lat": [40.0, 40.0]}).to_parquet(tmp_path / "p" / "index.parquet")
    keep = tt.lot_tile_mask("p", tmp_path, 10, 16)
    assert len(keep[16]) == 18  # 2 lots x 3 x 3
    mid = tt.lonlat_to_tile(-75.4, 40.0, 16)
    assert mid not in keep[16]
    assert all((x >> 6, y >> 6) in keep[10] for x, y in keep[16])
