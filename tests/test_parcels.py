"""Checks the parcel vector tiles the tool draws (app/public/data/parcels.pmtiles). Runs on GitHub with only pytest."""

import struct
from pathlib import Path

TILES = Path(__file__).resolve().parents[1] / "app" / "public" / "data" / "parcels.pmtiles"
PA = (-80.6, 39.6, -74.6, 42.4)  # lon / lat box around Pennsylvania, with a small margin


def header():
    with TILES.open("rb") as f:  # the header only, not the whole file
        raw = f.read(127)
    assert len(raw) == 127
    return raw


def test_parcels_file():
    assert TILES.exists()
    assert TILES.stat().st_size < 50 * 1024 * 1024  # under 50 MB


def test_parcels_header():
    h = header()
    assert h[:7] == b"PMTiles"
    assert h[7] == 3  # spec version 3
    root_off, root_len, meta_off, meta_len = struct.unpack("<QQQQ", h[8:40])
    size = TILES.stat().st_size
    assert root_len > 0 and root_off + root_len <= size
    assert meta_off + meta_len <= size
    assert h[99] == 1  # tile type: vector (MVT)
    minz, maxz = h[100], h[101]
    assert minz == 14 and maxz == 15
    lon0, lat0, lon1, lat1 = (v / 1e7 for v in struct.unpack("<iiii", h[102:118]))
    assert PA[0] <= lon0 < lon1 <= PA[2] and PA[1] <= lat0 < lat1 <= PA[3]
