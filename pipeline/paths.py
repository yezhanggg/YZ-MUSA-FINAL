"""Where the data lives.

Data is large and stays off the code checkout. One env var points at the data
root so every module and every machine resolves the same folders.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "ADU_DATA_DIR"
DEFAULT_ROOT = "~/musa-drive"


def data_root() -> Path:
    """Data root from ADU_DATA_DIR, else ~/musa-drive."""
    return Path(os.environ.get(ENV_VAR, DEFAULT_ROOT)).expanduser()


def raw_dir(place: str, create: bool = False) -> Path:
    """Folder for files as downloaded (after light cleaning) for one place."""
    return _folder(data_root() / "raw" / place, create)


def processed_dir(place: str, create: bool = False) -> Path:
    """Folder for built tables for one place."""
    return _folder(data_root() / "processed" / place, create)


def log_dir(create: bool = False) -> Path:
    """Folder for run notes and logs."""
    return _folder(data_root() / "ops" / "logs", create)


def _folder(path: Path, create: bool) -> Path:
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path
