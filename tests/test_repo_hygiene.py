"""Repo hygiene: no keys or big files, no owner data in fixtures, every rule and assumption sourced.

Files are the ones git would commit (tracked plus untracked, minus .gitignore). Without git,
the test walks the tree and skips the usual build and cache folders.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pipeline import rules

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 5 * 1024 * 1024
# Files that were committed before the 5 MB rule. Each needs a plan, not a quiet pass.
KNOWN_LARGE = {
    "app/public/data/parcels.pmtiles": "map tiles, committed on main (c7e3dba), to move to the data host",
    "app/public/data/lot_detail.pmtiles": "map tiles, committed on main (c7e3dba), to move to the data host",
}
SKIP_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".quarto",
    "_freeze",
    ".vercel",
    "data",
    "runs",
    "no-push",
}
PROSE = (".md", ".qmd")
PROSE_SKIP = ("site/", "node_modules/")
LONG_DASH = chr(0x2014)  # the long dash
# Keys that name owners or their mail. owner_occupancy is a rule (must the owner live there), not owner data.
OWNER_PARTS = ("owner", "mailing")
OWNER_OK = {"owner_occupancy"}


def repo_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            timeout=60,
        ).stdout.decode()
        files = [f for f in out.split("\0") if f]
        if files:
            return [f for f in files if (ROOT / f).is_file()]
    except (OSError, subprocess.SubprocessError):
        pass
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            found.append(str((Path(dirpath) / name).relative_to(ROOT)))
    return found


FILES = repo_files()


def test_no_env_files() -> None:
    bad = [
        f
        for f in FILES
        if Path(f).name == ".env" or (Path(f).name.startswith(".env.") and Path(f).name != ".env.example")
    ]
    assert not bad, f"key files would be committed: {bad}"


def test_no_large_files() -> None:
    big = {f: (ROOT / f).stat().st_size for f in FILES}
    bad = {f: s for f, s in big.items() if s > MAX_BYTES and f not in KNOWN_LARGE}
    assert not bad, "files over 5 MB (keep data on the drive): " + ", ".join(
        f"{f} ({s / 1e6:.1f} MB)" for f, s in sorted(bad.items())
    )


def test_known_large_list_is_current() -> None:
    gone = [f for f in KNOWN_LARGE if f not in FILES or (ROOT / f).stat().st_size <= MAX_BYTES]
    assert not gone, f"drop these from KNOWN_LARGE, they are gone or small now: {gone}"


def test_no_long_dash_in_prose_docs() -> None:
    bad = []
    for f in FILES:
        if not f.endswith(PROSE) or f.startswith(PROSE_SKIP):
            continue
        for i, line in enumerate((ROOT / f).read_text(errors="replace").splitlines(), 1):
            if LONG_DASH in line:
                bad.append(f"{f}:{i}")
    assert not bad, "long dash in prose docs (use a period or a colon): " + ", ".join(bad[:30])


def _keys(obj: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            out |= _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _keys(v)
    return out


def _fixture_files() -> list[str]:
    return [
        f for f in FILES if f.endswith(".json") and (f.startswith("tests/") or "__fixtures__" in f or "/fixtures/" in f)
    ]


def test_fixture_list_not_empty() -> None:
    assert _fixture_files(), "no JSON fixtures found: the owner check below would pass on nothing"


@pytest.mark.parametrize("path", _fixture_files())
def test_no_owner_columns_in_fixtures(path: str) -> None:
    keys = _keys(json.loads((ROOT / path).read_text()))
    bad = sorted(k for k in keys if k.lower() not in OWNER_OK and any(p in k.lower() for p in OWNER_PARTS))
    assert not bad, f"{path} has owner-like keys: {bad}"


@pytest.mark.parametrize("name", rules.rule_names())
def test_rule_values_have_section_and_date(name: str) -> None:
    data = rules.load_rules(name)
    bad = [
        where
        for where, leaf in rules.iter_leaves(data)
        if leaf.get("value") is not None and not (leaf.get("section") and leaf.get("verified_on"))
    ]
    assert not bad, f"{name}.json values without section or verified_on: {bad[:20]}"


def test_assumptions_have_source_and_date() -> None:
    data = json.loads((ROOT / "shared" / "assumptions.json").read_text())
    items = data["items"]
    assert items
    bad = []
    for key, item in items.items():
        sources = item.get("sources") or []
        if not sources:
            bad.append(f"{key}: no source")
        bad += [f"{key}: source '{s.get('title')}' has no date" for s in sources if not s.get("date")]
    assert not bad, "; ".join(bad[:20])
