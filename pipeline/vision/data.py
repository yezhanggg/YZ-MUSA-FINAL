"""Where the land cover data lives, the box split, and fast box loading.

Inputs are read in place from the course checkout (NAIP tiles, 4-class
labels, sample boxes). Everything this package writes goes under the data
root: caches and labels to processed/vision, runs to models/<run name>.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

# Validation counties of the published model (seed 42 draw in notebook 03).
VAL_COUNTIES = ["42001", "42009", "42011", "42021", "42099", "42109", "42117"]
TEST_COUNTIES = ["42027", "42041"]
STRATA = ["urban", "suburban", "rural"]

SOURCE_ENV = "ADU_VISION_SOURCE"
DEFAULT_SOURCE = "~/Documents/YZ-MUSA-FINAL/data/raw/6950"


def data_root() -> Path:
    """Data root. Uses pipeline.paths when present so every module agrees."""
    try:
        from pipeline.paths import data_root as root

        return root()
    except ImportError:
        return Path(os.environ.get("ADU_DATA_DIR", "~/musa-drive")).expanduser()


def source_dir() -> Path:
    """Read-only folder with naip/, labels/, sample_boxes.gpkg, chesapeake_counties.json."""
    return Path(os.environ.get(SOURCE_ENV, DEFAULT_SOURCE)).expanduser()


def vision_dir() -> Path:
    return data_root() / "processed" / "vision"


def models_dir() -> Path:
    return data_root() / "models"


def labels5_dir() -> Path:
    return vision_dir() / "labels5"


def cache_dir() -> Path:
    return vision_dir() / "npy_cache"


def all_geoids() -> list[str]:
    return split_boxes().GEOID.tolist()


def split_boxes() -> Any:
    """Train / val / test roles, same as notebook 03 and train_unet.py."""
    import geopandas as gpd

    src = source_dir()
    boxes = gpd.read_file(src / "sample_boxes.gpkg")
    have = boxes.GEOID.map(lambda g: (src / "naip" / f"{g}.tif").exists() and (src / "labels" / f"{g}.tif").exists())
    boxes = boxes[have].reset_index(drop=True)
    rng = np.random.default_rng(42)
    order = rng.permutation(boxes[boxes.split == "train"].county.unique())
    val, n, target = [], 0, int(0.15 * (boxes.split == "train").sum())
    for c in order:
        if n >= target:
            break
        val.append(c)
        n += (boxes.county == c).sum()
    # if the draw ever changes, the scores stop being comparable to the published ones
    assert sorted(val) == VAL_COUNTIES, val
    boxes["role"] = np.where(boxes.split == "test", "test", np.where(boxes.county.isin(val), "val", "train"))
    return boxes


def read_image(geoid: str) -> np.ndarray:
    import rasterio

    with rasterio.open(source_dir() / "naip" / f"{geoid}.tif") as s:
        return s.read()


def read_label4(geoid: str) -> np.ndarray:
    import rasterio

    with rasterio.open(source_dir() / "labels" / f"{geoid}.tif") as s:
        return s.read(1)


def read_label(geoid: str, n_classes: int) -> np.ndarray:
    if n_classes == 4:
        return read_label4(geoid)
    f = labels5_dir() / f"{geoid}.npy"
    if not f.exists():
        raise FileNotFoundError(f"{f} missing. Run: python -m pipeline.vision.labels build")
    return np.load(f)


def load_box(geoid: str, n_classes: int) -> tuple[np.ndarray, np.ndarray]:
    """Image and label, fully in memory (used for val and test scoring)."""
    return read_image(geoid), read_label(geoid, n_classes)


def load_box_mm(geoid: str, n_classes: int) -> tuple[np.ndarray, np.ndarray]:
    """Image and label as memory maps, so 122 training boxes do not sit in process memory."""
    cache = cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    fi = cache / f"{geoid}_img.npy"
    if not fi.exists():
        _atomic_save(fi, read_image(geoid))
    if n_classes == 4:
        fl = cache / f"{geoid}_lab4.npy"
        if not fl.exists():
            _atomic_save(fl, read_label4(geoid))
    else:
        fl = labels5_dir() / f"{geoid}.npy"
    return np.load(fi, mmap_mode="r"), np.load(fl, mmap_mode="r")


def _atomic_save(path: Path, arr: np.ndarray) -> None:
    """Write to a temp name first, so a killed job never leaves a half cache file."""
    tmp = path.with_suffix(".tmp.npy")
    np.save(tmp, arr)
    tmp.replace(path)
