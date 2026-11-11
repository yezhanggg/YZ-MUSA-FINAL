"""Paths, classes and imagery sources for the backyard structure detector.

Plain constants only. No heavy imports, so every script and both Python
environments can read it.
"""
from __future__ import annotations

from pathlib import Path

DRIVE = Path.home() / "musa-drive"
PROCESSED = DRIVE / "processed"
IMAGERY = DRIVE / "raw" / "imagery"
WORK = PROCESSED / "yolo"
DATASET = WORK / "dataset"
REVIEW = WORK / "review"
MODELS = DRIVE / "models" / "yolo"
LOG_NOTE = DRIVE / "ops" / "logs" / "yolo.md"

CITIES = ("pittsburgh", "philadelphia")
SHORT = {"pittsburgh": "pgh", "philadelphia": "phl"}

# Class ids are fixed. Change them only together with existing label files.
CLASSES = ("garage", "shed", "other_accessory", "pool")
CLASS_ID = {name: i for i, name in enumerate(CLASSES)}

# Size rule in square feet for footprints that are not the main building.
SHED_MAX_SQFT = 180.0
GARAGE_MAX_SQFT = 700.0
GARAGE_ACCESS_FT = 75.0      # a garage sits within this distance of a street or alley centerline
MIN_FOOTPRINT_SQFT = 36.0    # smaller outlines are slivers, not structures
MIN_BOX_PX = 6.0             # boxes thinner than this after clipping are dropped
MIN_VISIBLE = 0.5            # keep a box cut by the chip edge if at least half of it is inside

# Chips: 640 px at the native 0.5 ft pixel, 3 x 3 chips per sample area (960 ft, about 293 m).
CHIP_PX = 640
PIXEL_FT = 0.5
CHIPS_PER_SIDE = 3
AREA_FT = CHIP_PX * PIXEL_FT * CHIPS_PER_SIDE
AREAS_PER_CITY = 60
SEED = 6950
SPLIT_FRACTIONS = {"train": 0.7, "val": 0.15, "test": 0.15}

# Share of sample areas centered on each lot type. The rest go to all other residential types.
AREA_TYPE_SHARES = {"single_family_detached": 0.45, "semi_detached": 0.25, "other": 0.30}
MAX_AREAS_PER_DISTRICT = 2

PEMA_TERMS = (
    "PEMA orthoimagery via PASDA. Access constraints: none. Use constraints: none. "
    "Acknowledgement of the source requested: Pennsylvania Emergency Management Agency (PEMA), "
    "imagery hosted by PASDA (Pennsylvania Spatial Data Access)."
)

# Layer 3 is the image only. Layer 0 also draws the mosaic seamlines as green lines.
SOURCES = {
    "pittsburgh": {
        "name": "PEMA Orthoimagery Cycle 2, West mosaic (2022)",
        "export": "https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/PEMAImagery2022/MapServer/export",
        "layers": "show:3",
        "date": "2022-03-16/2022-04-12",
        "crs": "EPSG:2271",
        "native_pixel_ft": 0.5,
        "terms": PEMA_TERMS,
    },
    "philadelphia": {
        "name": "PEMA Orthoimagery Cycle 2, Eastern PA (2020-2021)",
        "export": "https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/PEMAImagery2021/MapServer/export",
        "layers": "show:3",
        "date": "2020-12-11/2021-03-22",
        "crs": "EPSG:2272",
        "native_pixel_ft": 0.5,
        "terms": PEMA_TERMS,
    },
}

USER_AGENT = "Mozilla/5.0 (compatible; research-tile-client/1.0)"
MAX_PARALLEL = 4


def city_dir(city: str) -> Path:
    return IMAGERY / city


def chips_dir(city: str) -> Path:
    return IMAGERY / city / "chips"


def manifest_path(city: str) -> Path:
    return IMAGERY / city / "chips.csv"


def areas_path(city: str) -> Path:
    return IMAGERY / city / "areas.geojson"
