"""pipeline/address_index.py: address parsing, shard keys, determinism and the files it writes.

The small fixture index the app tests read (app/src/lib/lot/__fixtures__/addresses/) is this builder's output for
FIXTURE below. To write it again after a format change:
    python tests/test_address_index.py --write
"""

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.address_index import build, build_place, dump, key_of, parse_address, shard_keys, street_core, write

CASES = json.loads((ROOT / "tests" / "fixtures" / "address_norm_cases.json").read_text())
APP_FIXTURE = ROOT / "app" / "src" / "lib" / "lot" / "__fixtures__" / "addresses"

# Two places: a city place (one town) and a county place (two towns). Shard limit 3, so streets split into shards.
FIXTURE = {
    "pittsburgh": [
        ("42003-0084N00213000000", "42003140100", "5704 POCUSSET ST"),
        ("42003-0084N00214000000", "42003140100", "5706 POCUSSET ST"),
        ("42003-0084N00215000000", "42003140100", "5708 POCUSSET ST"),
        ("42003-0048M00024000000", "42003060300", "3602 -3606 SMALLMAN ST"),
        ("42003-0026D00147000000", "42003080200", "321 -323 SAPPHIRE WAY"),
        ("42003-0123J00082000000", "42003110600", "1316 N SHERIDAN AVE"),
        ("42003-0123J00083000000", "42003110600", "1318 N SHERIDAN AVE"),
        ("42003-0090S00182000000", "42003565300", "4427 SWEETBAY ST"),
        ("42003-0016P00062000000", "42003191600", "1404 BELASCO AVE"),
        ("42003-0016P00063000000", "42003191600", "1406 BELASCO AVE"),
        ("42003-0001A00001000000", "42003020100", "2006 1/2 FORBES AVE"),
        ("42003-0001A00002000000", "42003020100", "236 -238 SEMPLE ST UNIT APT 1 &2"),
        ("42003-0001A00003000000", "42003020100", None),
        # The lot record fixture easy_fit (app/src/lib/lot/__fixtures__/easy_fit.json): find_lot then the lot tools.
        ("42003-0086N00208000000", "42003141300", "5459 BEACON ST"),
    ],
    "chester_county": [
        ("42029-15-10-118", "42029300900", "75 WASHINGTON AV", "Phoenixville borough"),
        ("42029-15-10-119", "42029300900", "77 WASHINGTON AV", "Phoenixville borough"),
        ("42029-1-9-845", "42029302500", "324 S DARLINGTON ST", "West Chester borough"),
        ("42029-1-9-846", "42029302500", "326 S DARLINGTON ST", "West Chester borough"),
        ("42029-1-9-900", "42029302500", "75 WASHINGTON ST", "West Chester borough"),
        ("42029-15-9-285", "42029300700", "309 CHURCH ST", "Phoenixville borough"),
        ("42029-1-5-10", "42029302500", "309 CHURCH ST", "West Chester borough"),
        ("42029-1-4-50", "42029302400", "307 W MARSHALL ST", "West Chester borough"),  # fixture wch_detached
    ],
}


def fixture_frame(place: str) -> pd.DataFrame:
    rows = FIXTURE[place]
    cols = ["lot_id", "tract", "address", "municipality"][: len(rows[0])]
    return pd.DataFrame(rows, columns=cols)


def fixture_build(place: str) -> dict:
    return build(fixture_frame(place), place, f"{place}-fixture", limit=3)


def write_fixture() -> None:
    for place in FIXTURE:
        b = fixture_build(place)
        d = APP_FIXTURE / place
        (d / "shards").mkdir(parents=True, exist_ok=True)
        (d / "index.json").write_text(json.dumps(b["index"], indent=1, sort_keys=True) + "\n")
        for k, doc in b["shards"].items():
            (d / "shards" / (k.replace(" ", "_") + ".json")).write_text(
                json.dumps(doc, indent=1, sort_keys=True) + "\n"
            )


@pytest.mark.parametrize("case", CASES, ids=[c["in"] for c in CASES])
def test_parse_matches_shared_cases(case):
    a = parse_address(case["in"])
    assert (a.number, a.n, a.hi, a.street, street_core(a.street)) == (
        case["number"],
        case["n"],
        case["hi"],
        case["street"],
        case["core"],
    )


def test_shard_keys_split_until_small():
    cores = Counter({"bancroft st": 5, "baltimore ave": 5, "bell ave": 1, "spruce st": 2})
    keys = shard_keys(cores, limit=6)
    assert keys == ["bal", "ban", "be", "s"]  # "b" holds 11 lots, "ba" 10: both split
    assert key_of("bancroft st", keys) == "ban"
    assert key_of("bell ave", keys) == "be"
    assert key_of("zebra st", keys) is None
    # One street bigger than the limit ends in a shard of its own.
    keys = shard_keys(Counter({"germantown ave": 10, "green st": 1}), limit=3)
    assert key_of("germantown ave", keys) == "germantown ave"
    assert key_of("green st", keys) in keys


def test_every_street_in_the_shard_of_its_longest_key():
    b = fixture_build("pittsburgh")
    keys = sorted(b["index"]["shards"])
    for k, doc in b["shards"].items():
        for street in doc["streets"]:
            assert key_of(street_core(street), keys) == k
    assert sum(b["index"]["shards"].values()) == b["index"]["addressed"] == 13
    assert max(b["index"]["shards"].values()) <= 3


def test_rows_hold_addresses_only():
    b = fixture_build("chester_county")
    ix = b["index"]
    assert ix["towns"] == ["Phoenixville borough", "West Chester borough"]
    assert ix["prefix"] == "42029"
    streets = {s[0]: s for s in ix["streets"]}
    assert streets["washington ave"][1:] == [2, 75, 77, [0]]
    assert streets["church st"][4] == [0, 1]
    allrows = {s: v for doc in b["shards"].values() for s, v in doc["streets"].items()}
    assert allrows["washington ave"] == {
        "label": "WASHINGTON AV",
        "rows": [["75", "15-10-118", "300900", 0], ["77", "15-10-119", "300900", 0]],
    }
    # Number, lot id, tract, town and (only when the text differs) the address as written. Nothing else.
    for v in allrows.values():
        for r in v["rows"]:
            assert 4 <= len(r) <= 5
            assert all(isinstance(x, str | int) for x in r)


def test_raw_address_kept_when_it_differs():
    b = fixture_build("pittsburgh")
    semple = next(doc["streets"]["semple st"] for doc in b["shards"].values() if "semple st" in doc["streets"])
    assert semple["rows"] == [["236-238", "0001A00002000000", "020100", 0, "236 -238 SEMPLE ST UNIT APT 1 &2"]]
    assert b["index"]["lots"] == 14 and b["index"]["addressed"] == 13


def test_build_is_deterministic_and_order_free():
    df = fixture_frame("pittsburgh")
    a = build(df, "pittsburgh", "v", limit=3)
    b = build(df.sample(frac=1, random_state=3), "pittsburgh", "v", limit=3)
    assert dump(a["index"]) == dump(b["index"])
    assert {k: dump(v) for k, v in a["shards"].items()} == {k: dump(v) for k, v in b["shards"].items()}


def test_app_fixture_is_current():
    """The app tests read the builder's output for FIXTURE. Run this file with --write after a format change."""
    for place in FIXTURE:
        b = fixture_build(place)
        d = APP_FIXTURE / place
        assert json.loads((d / "index.json").read_text()) == b["index"]
        files = sorted(p.name for p in (d / "shards").iterdir())
        assert files == sorted(k.replace(" ", "_") + ".json" for k in b["shards"])
        for k, doc in b["shards"].items():
            assert json.loads((d / "shards" / (k.replace(" ", "_") + ".json")).read_text()) == doc


def test_build_place_writes_and_reruns(tmp_path):
    place = tmp_path / "pittsburgh"
    place.mkdir()
    fixture_frame("pittsburgh").to_parquet(place / "index.parquet")
    (place / "manifest.json").write_text(json.dumps({"data_version": "pgh-1"}))
    (place / "addresses" / "shards").mkdir(parents=True)
    (place / "addresses" / "shards" / "stale.json.gz").write_bytes(b"old")
    sizes = build_place("pittsburgh", tmp_path)
    first = {p.relative_to(place): p.read_bytes() for p in sorted((place / "addresses").rglob("*")) if p.is_file()}
    assert Path("addresses/shards/stale.json.gz") not in first
    assert sum(sizes.values()) == sum(len(v) for v in first.values())
    ix = json.loads(gzip.decompress(first[Path("addresses/index.json.gz")]))
    assert ix["data_version"] == "pgh-1" and ix["place"] == "pittsburgh"
    build_place("pittsburgh", tmp_path)
    again = {p.relative_to(place): p.read_bytes() for p in sorted((place / "addresses").rglob("*")) if p.is_file()}
    assert again == first
    assert not (place / ".addresses.tmp").exists() and not (place / ".addresses.old").exists()


def test_no_private_columns_are_read(tmp_path):
    place = tmp_path / "philadelphia"
    place.mkdir()
    df = pd.DataFrame(
        {
            "lot_id": ["42101-1"],
            "tract": ["42101000100"],
            "address": ["1 MARKET ST"],
            "owner_1": ["SECRET OWNER"],
            "last_sale_price": [123456.0],
        }
    )
    df.to_parquet(place / "index.parquet")
    build_place("philadelphia", tmp_path)
    body = b"".join(gzip.decompress(p.read_bytes()) for p in (place / "addresses").rglob("*.gz"))
    assert b"SECRET" not in body and b"123456" not in body


def test_write_replaces_folder(tmp_path):
    b = fixture_build("chester_county")
    write(b, tmp_path)
    (tmp_path / "addresses" / "extra.txt").write_text("x")
    write(b, tmp_path)
    assert not (tmp_path / "addresses" / "extra.txt").exists()


if __name__ == "__main__" and "--write" in sys.argv:
    write_fixture()
    print(f"wrote {APP_FIXTURE}")
