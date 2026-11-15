"""Spot cover map per place (pipeline/vision/cover_lookup.py), on a tiny fake class map."""

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("osgeo")

from pipeline.vision import cover_lookup  # noqa: E402

TOWNS = ("allentown", "centre_county", "chester_county", "montgomery_county")


def _tile(path, x0, y0, arr, epsg=26918):
    from rasterio.transform import from_origin

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=arr.shape[0],
        width=arr.shape[1],
        count=1,
        dtype="uint8",
        crs=f"EPSG:{epsg}",
        transform=from_origin(x0, y0, 0.6, 0.6),
        nodata=255,
    ) as d:
        d.write(arr, 1)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("ADU_DATA_DIR", str(tmp_path))
    cover_lookup.source_for.cache_clear()
    yield tmp_path
    cover_lookup.source_for.cache_clear()


@pytest.mark.parametrize("place", TOWNS)
def test_town_places_read_their_model_class_maps(root, place):
    arr = np.zeros((100, 100), dtype=np.uint8)
    arr[:, :50] = 2  # west half tree
    arr[:, 50:] = 4  # east half hard surface
    _tile(root / "processed" / place / "cover_work" / "r34_c5_s0" / "tiles" / "r000_c000.tif", 450000, 4500000, arr)
    path, classes, source = cover_lookup.source_for(place)
    assert path.endswith(f"processed/{place}/cover_work/r34_c5_s0/tiles.vrt")
    assert classes is cover_lookup.MODEL_CLASSES and source == "model:r34_c5_s0"

    from pyproj import Transformer
    from shapely.geometry import box
    from shapely.ops import transform

    # a 30 m square in the middle of the tile, half on each class
    utm = box(450000 + 15, 4500000 - 45, 450000 + 45, 4500000 - 15)
    wgs = transform(Transformer.from_crs(26918, 4326, always_xy=True).transform, utm)
    out = cover_lookup.cover_in_polygon(place, wgs)
    total = sum(v for k, v in out.items() if k.endswith("_sqft"))
    assert total == pytest.approx(900 * cover_lookup.SQFT_PER_M2, rel=0.05)
    assert out["tree_sqft"] == pytest.approx(out["hard_surface_sqft"], rel=0.1)
    assert out["open_sqft"] == 0 and out["building_sqft"] == 0
    assert out["source"] == "model:r34_c5_s0"


def test_known_sources_and_unknown_place(root):
    assert cover_lookup.source_for("philadelphia")[2] == "landcover_2018"
    assert set(cover_lookup.MODEL_RUNS) == {"pittsburgh", *TOWNS}
    with pytest.raises(ValueError):
        cover_lookup.source_for("nowhere")
