"""Address index of a lot place: every lot's street address, split into small files by street name.

The assistant's find_lot tool reads it in the browser to find any address of a place without loading its tract
files. Built from the place's index.parquet (no lot rebuild). Addresses only: house number, street, town, lot id and
tract. No owner, sale or value field is read.

Output in <data root>/lots/<place>/addresses/ (replaced as a whole on every run, so a rerun is safe):
    index.json.gz            towns, shard keys and every street name with its lot count and number range
    shards/<key>.json.gz     the lots of the streets whose name (without a leading N, S, E or W) starts with <key>

Shard keys are prefixes of the street name. A prefix is made one letter longer until its shard holds at most
SHARD_ROWS lots, so one lookup reads the index file and one shard. A street is in the shard of the longest key that
starts its name. The address normalisation is the same as app/src/lib/lot/addressIndex.ts (shared cases in
tests/fixtures/address_norm_cases.json).

CLI:
    python -m pipeline.address_index --place pittsburgh [--place philadelphia ...]
    python -m pipeline.build_lots addresses --place pittsburgh
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.paths import data_root

FORMAT = 1
SHARD_ROWS = 4000
DIR = "addresses"

# Street words to their short form. Same table as WORD in app/src/lib/lot/addressIndex.ts.
WORD: dict[str, str] = {
    "street": "st",
    "str": "st",
    "avenue": "ave",
    "av": "ave",
    "avn": "ave",
    "road": "rd",
    "drive": "dr",
    "drv": "dr",
    "place": "pl",
    "boulevard": "blvd",
    "blv": "blvd",
    "lane": "ln",
    "la": "ln",
    "court": "ct",
    "terrace": "ter",
    "terr": "ter",
    "square": "sq",
    "parkway": "pkwy",
    "pky": "pkwy",
    "highway": "hwy",
    "circle": "cir",
    "alley": "aly",
    "ally": "aly",
    "trail": "trl",
    "crossing": "xing",
    "expressway": "expy",
    "extension": "ext",
    "heights": "hts",
    "saint": "st",
    "mount": "mt",
    "fort": "ft",
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "northeast": "ne",
    "northwest": "nw",
    "southeast": "se",
    "southwest": "sw",
    "first": "1st",
    "second": "2nd",
    "third": "3rd",
    "fourth": "4th",
    "fifth": "5th",
    "sixth": "6th",
    "seventh": "7th",
    "eighth": "8th",
    "ninth": "9th",
    "tenth": "10th",
    "eleventh": "11th",
    "twelfth": "12th",
    "thirteenth": "13th",
    "fourteenth": "14th",
    "fifteenth": "15th",
    "sixteenth": "16th",
    "seventeenth": "17th",
    "eighteenth": "18th",
    "nineteenth": "19th",
    "twentieth": "20th",
}
DIRS = frozenset({"n", "s", "e", "w", "ne", "nw", "se", "sw"})
UNIT = re.compile(r"\b(unit|apt|apartment|ste|suite|fl|floor|rm|room|rear|bldg|building)\b.*$")
TOKEN = re.compile(r"\d+/\d+|\d+[a-z]*|[a-z]+|[-&]")


@dataclass(frozen=True)
class Address:
    """A parsed street address. number is "" when the text has no house number."""

    number: str  # canonical house number: "1815", "12a", "629 1/2", "236-238"
    n: int | None  # first house number
    hi: int | None  # last number of a range ("236-238" -> 238)
    street: str  # normalised street name: "s bancroft st"


def norm_street(words: Sequence[str]) -> str:
    return " ".join(WORD.get(w, w) for w in words if re.fullmatch(r"[a-z0-9]+", w))


def street_core(street: str) -> str:
    """Street name without a leading directional: "s bancroft st" -> "bancroft st". Shards are keyed on this."""
    t = street.split()
    return " ".join(t[1:]) if len(t) > 1 and t[0] in DIRS else street


def parse_address(text: str) -> Address:
    """ "1815 S. Bancroft Street, Philadelphia" -> Address("1815", 1815, None, "s bancroft st"). Text after a comma,
    unit numbers (apt, unit, #, rear) and punctuation are dropped."""
    s = text.lower().split(",")[0]
    s = re.sub(r"#.*$", "", s)
    s = UNIT.sub("", s).replace("'", "")
    s = re.sub(r"[^a-z0-9/&\- ]", " ", s)
    tok = TOKEN.findall(s)
    first = re.fullmatch(r"(\d+)([a-z]?)", tok[0]) if tok else None
    if not first or len(tok) < 2:
        return Address("", None, None, norm_street(tok))
    n = int(first.group(1))
    letter, half, hi = first.group(2), False, None
    i = 1
    while i < len(tok) - 1:  # the number's tail, never the last word (that is the street)
        t, nxt = tok[i], tok[i + 1]
        if t == "1/2":
            half, i = True, i + 1
        elif t in ("-", "&") and nxt == "1/2":
            half, i = True, i + 2
        elif t in ("-", "&") and re.fullmatch(r"\d+", nxt) and i + 2 < len(tok):
            if t == "-" and hi is None and int(nxt) > n:
                hi = int(nxt)
            i += 2
        elif t in ("-", "&") and re.fullmatch(r"[a-z]", nxt) and i + 2 < len(tok):
            letter = letter or nxt
            i += 2
        elif re.fullmatch(r"\d+", t):  # a second number without a dash: "1111 1115 N Wahneta St"
            if hi is None and int(t) > n:
                hi = int(t)
            i += 1
        elif re.fullmatch(r"\d+/\d+", t):
            i += 1
        elif re.fullmatch(r"[a-z]", t) and t not in DIRS and not letter:
            letter, i = t, i + 1
        else:
            break
    number = f"{n}-{hi}" if hi is not None else f"{n}{letter}{' 1/2' if half else ''}"
    return Address(number, n, hi, norm_street(tok[i:]))


# ---------------------------------------------------------------- build


def shard_keys(cores: Counter[str], limit: int = SHARD_ROWS) -> list[str]:
    """Prefix keys so that each shard holds at most `limit` lots (a single street can be larger). Sorted."""
    keys: list[str] = []

    def split(prefix: str, group: dict[str, int]) -> None:
        if sum(group.values()) <= limit or all(len(c) <= len(prefix) for c in group):
            keys.append(prefix)
            return
        rest = {c: v for c, v in group.items() if len(c) <= len(prefix)}
        if rest:
            keys.append(prefix)
        sub: dict[str, dict[str, int]] = defaultdict(dict)
        for c, v in group.items():
            if len(c) > len(prefix):
                sub[c[: len(prefix) + 1]][c] = v
        for p in sorted(sub):
            split(p, sub[p])

    first: dict[str, dict[str, int]] = defaultdict(dict)
    for c, v in cores.items():
        first[c[:1]][c] = v
    for p in sorted(first):
        split(p, first[p])
    return sorted(set(keys))


def key_of(core: str, keys: Sequence[str]) -> str | None:
    """The longest shard key that starts this street name."""
    best = None
    for k in keys:
        if core.startswith(k) and (best is None or len(k) > len(best)):
            best = k
    return best


def shard_file(key: str) -> str:
    return key.replace(" ", "_") + ".json.gz"


def build(rows: pd.DataFrame, place: str, data_version: str | None, limit: int = SHARD_ROWS) -> dict[str, Any]:
    """Index and shard documents from lot rows (lot_id, tract, address and, for a county place, municipality).
    Returns {"index": {...}, "shards": {key: {...}}}. Pure and deterministic."""
    df = rows[rows["address"].notna()].copy()
    df["address"] = df["address"].astype(str).str.strip()
    df = df[df["address"] != ""].sort_values(["lot_id"], kind="stable")
    towns = sorted({str(t) for t in df["municipality"].dropna()}) if "municipality" in df.columns else []
    town_ix = {t: i for i, t in enumerate(towns)}
    prefix = Counter(str(t)[:5] for t in df["tract"]).most_common(1)[0][0] if len(df) else ""
    streets: dict[str, list[tuple[str, str, str, int, str]]] = defaultdict(list)
    labels: dict[str, Counter[str]] = defaultdict(Counter)
    skipped = 0
    for lot, tract, raw, town in zip(
        df["lot_id"].astype(str),
        df["tract"].astype(str),
        df["address"],
        df["municipality"] if "municipality" in df.columns else [None] * len(df),
        strict=True,
    ):
        a = parse_address(raw)
        if not a.street or not a.number:
            skipped += 1
            continue
        up = re.sub(r"\s+", " ", raw.upper())
        label = up[up.find(" ") + 1 :] if " " in up else up
        labels[a.street][label] += 1
        streets[a.street].append((a.number, lot, tract, town_ix.get(str(town), 0) if town is not None else 0, up))
    core_n: Counter[str] = Counter()
    for s, v in streets.items():
        core_n[street_core(s)] += len(v)
    keys = shard_keys(core_n, limit)
    shards: dict[str, dict[str, Any]] = {k: {"key": k, "streets": {}} for k in keys}
    street_list: list[list[Any]] = []
    for s in sorted(streets):
        label = sorted(labels[s].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        out = []
        nums = []
        for number, lot, tract, town, up in sorted(streets[s], key=lambda r: (_num_sort(r[0]), r[0], r[1])):
            lot_s = lot[len(prefix) + 1 :] if lot.startswith(prefix + "-") else "=" + lot
            tract_s = tract[len(prefix) :] if tract.startswith(prefix) else "=" + tract
            row: list[Any] = [number, lot_s, tract_s, town]
            if up != f"{number.upper()} {label}":
                row.append(up)
            out.append(row)
            nums.append(_num_sort(number)[0])
        key = key_of(street_core(s), keys)
        assert key is not None
        shards[key]["streets"][s] = {"label": label, "rows": out}
        st_towns = sorted({r[3] for r in out})
        street_list.append([s, len(out), min(nums), max(nums), st_towns])
    index = {
        "format": FORMAT,
        "kind": "address_index",
        "place": place,
        "data_version": data_version,
        "prefix": prefix,
        "towns": towns,
        "lots": int(len(rows)),
        "addressed": sum(int(v[1]) for v in street_list),
        "skipped": skipped,
        "shards": {k: sum(len(v["rows"]) for v in shards[k]["streets"].values()) for k in keys},
        "streets": street_list,
    }
    return {"index": index, "shards": shards}


def _num_sort(number: str) -> tuple[int, str]:
    m = re.match(r"\d+", number)
    return (int(m.group(0)) if m else 0, number)


def dump(doc: Any) -> bytes:
    """Compact JSON, gzip level 9, no timestamp: the same input gives the same bytes."""
    body = json.dumps(doc, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode()
    return gzip.compress(body, compresslevel=9, mtime=0)


def write(built: dict[str, Any], out: Path) -> dict[str, int]:
    """Write the index into out/addresses/, replacing what was there. Returns file sizes in bytes."""
    final = out / DIR
    tmp = out / f".{DIR}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "shards").mkdir(parents=True)
    sizes: dict[str, int] = {}
    blob = dump(built["index"])
    (tmp / "index.json.gz").write_bytes(blob)
    sizes["index.json.gz"] = len(blob)
    for k, doc in built["shards"].items():
        blob = dump(doc)
        (tmp / "shards" / shard_file(k)).write_bytes(blob)
        sizes[f"shards/{shard_file(k)}"] = len(blob)
    old = out / f".{DIR}.old"
    if old.exists():
        shutil.rmtree(old)
    if final.exists():
        os.replace(final, old)
    os.replace(tmp, final)
    if old.exists():
        shutil.rmtree(old)
    return sizes


COLUMNS = ["lot_id", "tract", "address", "municipality"]


def build_place(place: str, root: Path | None = None) -> dict[str, int]:
    out = (root or data_root() / "lots") / place
    index = out / "index.parquet"
    if not index.exists():
        raise SystemExit(f"no {index}: build the lots first")
    have = set(_schema_names(index))
    rows = pd.read_parquet(index, columns=[c for c in COLUMNS if c in have])
    manifest = out / "manifest.json"
    version = json.loads(manifest.read_text()).get("data_version") if manifest.exists() else None
    built = build(rows, place, version)
    sizes = write(built, out)
    ix = built["index"]
    biggest = max((v for k, v in sizes.items() if k.startswith("shards/")), default=0)
    print(
        f"{place}: {ix['addressed']:,} of {ix['lots']:,} lots, {len(ix['streets']):,} streets, "
        f"{len(ix['shards'])} shards, index {sizes['index.json.gz'] / 1e3:.1f} KB, "
        f"largest shard {biggest / 1e3:.1f} KB, total {sum(sizes.values()) / 1e6:.2f} MB"
        + (f", {ix['skipped']} without a house number left out" if ix["skipped"] else "")
    )
    return sizes


def _schema_names(path: Path) -> list[str]:
    import pyarrow.parquet as pq

    return list(pq.read_schema(path).names)


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline.address_index", description=__doc__.splitlines()[0])
    p.add_argument("--place", action="append", required=True, help="place folder under <data root>/lots (repeat)")
    p.add_argument("--lots-dir", type=Path, help="lot build root (default <data root>/lots)")
    args = p.parse_args(argv)
    for place in args.place:
        build_place(place, args.lots_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
