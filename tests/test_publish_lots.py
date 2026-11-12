"""tools/publish_lots.sh on a tiny fake lot build: the sale and assessment facts stay on the drive."""

import gzip
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "publish_lots.sh"
FACTS = {
    "year_built": 1925,
    "living_sqft": 1400.0,
    "stories": 2.0,
    "assessed_value": 250000.0,
    "last_sale_date": "2019-05-01",
    "last_sale_price": 1.0,
    "zip": "15217",
}


def pmtiles(meta: dict) -> bytes:
    """A PMTiles v3 file with no tiles and uncompressed metadata, enough for the metadata scrub."""
    blob = json.dumps(meta).encode()
    header = bytearray(127)
    header[:7] = b"PMTiles"
    header[7] = 3
    header[8:72] = struct.pack("<8Q", 127, 0, 127, len(blob), 127 + len(blob), 0, 127 + len(blob), 0)
    header[97] = 1
    return bytes(header) + blob


def fake_build(src: Path) -> Path:
    p = src / "testville"
    (p / "detail").mkdir(parents=True)
    (p / "tiles").mkdir()
    manifest = {"data_version": "testville-1", "built_at": "2026-11-11T00:00", "counts": {"lots": 1, "tracts": 1}}
    (p / "manifest.json").write_text(json.dumps(manifest))
    (p / "stats.json").write_text("{}")
    (p / "lot_tract.json").write_text(json.dumps({"42003-1": "42003000100"}))
    (p / "tiles" / "parcels.pmtiles").write_bytes(pmtiles({"name": "parcels"}))
    head = {"tract": "42003000100", "lots": [{"lot": {"id": "42003-1"}, "facts": dict(FACTS)}]}
    (p / "detail" / "42003000100.json.gz").write_bytes(gzip.compress(json.dumps(head).encode(), mtime=0))
    (p / "detail" / "42003000100.geom.json.gz").write_bytes(gzip.compress(b'{"geometry":[]}', mtime=0))
    return p


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("python3") is None, reason="needs bash and python3")
def test_publish_leaves_out_sale_and_assessment_facts(tmp_path):
    src, out = tmp_path / "lots", tmp_path / "host"
    built = fake_build(src)
    before = (built / "detail" / "42003000100.json.gz").read_bytes()
    env = {**os.environ, "LOT_DATA_DIR": str(src), "LOT_HOST_DIR": str(out), "LOT_PLACES": "testville"}
    run = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    assert "3 sale and assessment values left out" in run.stdout

    head = json.loads(gzip.decompress((out / "lots/testville/detail/42003000100.json.gz").read_bytes()))
    facts = head["lots"][0]["facts"]
    assert facts == {"year_built": 1925, "living_sqft": 1400.0, "stories": 2.0, "zip": "15217"}
    assert (out / "lots/testville/detail/42003000100.geom.json.gz").exists()
    # The drive files are not changed.
    assert (built / "detail" / "42003000100.json.gz").read_bytes() == before
    readme = (out / "README.md").read_text()
    assert "No assessed values and no sale dates or prices" in readme


def layer(name: str, *fields: str) -> dict:
    return {"name": name, "vector_layers": [{"id": name, "fields": dict.fromkeys(fields, "Number")}]}


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("python3") is None, reason="needs bash and python3")
def test_publish_copies_the_answer_tiles_and_refuses_other_fields(tmp_path):
    src, out = tmp_path / "lots", tmp_path / "host"
    built = fake_build(src)
    (built / "tiles" / "lots.pmtiles").write_bytes(pmtiles(layer("parcels", "id", "tr", "s", "t", "mf", "mk", "a")))
    (built / "tiles" / "overview.pmtiles").write_bytes(pmtiles(layer("overview", "a", "n", "d")))
    env = {**os.environ, "LOT_DATA_DIR": str(src), "LOT_HOST_DIR": str(out), "LOT_PLACES": "testville"}
    run = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    for name in ("parcels", "lots", "overview"):
        assert (out / f"lots/testville/tiles/{name}.pmtiles").exists()
    assert "lots/<place>/tiles/overview.pmtiles" in (out / "README.md").read_text()

    # A tile file with any other property (an owner, a price) stops the bundle.
    (built / "tiles" / "lots.pmtiles").write_bytes(pmtiles(layer("parcels", "id", "a", "sale_price")))
    run = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False)
    assert run.returncode != 0
    assert "unexpected tile fields ['sale_price']" in run.stderr + run.stdout
