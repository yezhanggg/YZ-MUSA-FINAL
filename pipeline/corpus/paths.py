"""Folders for the corpus. All under the data drive, never the repo."""

from __future__ import annotations

import os
from pathlib import Path

from pipeline.paths import data_root

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / "shared" / "rules"


def corpus_root() -> Path:
    return Path(os.environ.get("CORPUS_DIR", data_root() / "corpus")).expanduser()


def sub(name: str, create: bool = True) -> Path:
    p = corpus_root() / name
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def cache_root() -> Path:
    return data_root() / "cache"


def set_model_cache() -> None:
    """Keep model downloads on the data drive."""
    hf = cache_root() / "hf"
    hf.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(hf))
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(hf / "st"))
    os.environ.setdefault("TORCH_HOME", str(cache_root() / "torch"))


def progress_log() -> Path:
    p = data_root() / "ops" / "logs" / "corpus.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
