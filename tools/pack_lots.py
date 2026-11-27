"""Lossless packing of published lot tract files (format "pack1"), to keep the lot data bundle under the 1 GB
GitHub Pages limit. Used by tools/publish_lots.sh. The drive files are not changed.

gzip only finds repeats within 32 KB, and a lot record is about 30 KB, so the copies inside one record that sit far
apart, and the copies shared by every record of a tract, cost nearly their full size. Two moves remove them:

1. Same scenario. In `fit`, `rules` and `buildable`, a scenario (local_reform, state_reform) whose value is the same
   JSON text as an earlier scenario (today first) becomes {"$same": "<earlier scenario>"}. When the whole scenario
   differs, each part inside it (unit type, key, and so on down to MAX_DEPTH levels) of at least MIN_CHILD bytes
   that has the same text at the same path of an earlier scenario becomes {"$same": "<earlier scenario>"} on its own.
2. Shared table. `quality.<key>` values of at least MIN_SHARED bytes are stored once per file in `shared` and become
   {"$ref": i}.

"The same" means the same JSON text, key order included, so unpacking gives back the record byte for byte
(`unpack(pack(doc))` dumps to the same text as `doc`). The browser undoes both in app/src/lib/lot/load.ts
(unpackRecords), before the citation tables and the split geometry are joined.

    python tools/pack_lots.py check <tract.json.gz> ...     # pack, unpack, compare, print the sizes
"""

from __future__ import annotations

import copy
import gzip
import json
import sys
from typing import Any

FORMAT = "pack1"
SCENARIO_BLOCKS = ("fit", "rules", "buildable")
SCENARIOS = ("today", "local_reform", "state_reform")
MIN_CHILD = 200
MIN_SHARED = 64
MAX_DEPTH = 6


def _text(v: Any) -> str:
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False)


def _is_marker(v: Any, key: str) -> bool:
    return isinstance(v, dict) and len(v) == 1 and key in v


def pack(doc: dict[str, Any]) -> dict[str, Any]:
    """Pack a head file or a chunk file in place and return it. A geometry file (no `lots` records) is left as is."""
    lots = doc.get("lots")
    if not isinstance(lots, list) or doc.get("pack"):
        return doc
    shared: list[Any] = []
    index: dict[str, int] = {}
    for rec in lots:
        if not isinstance(rec, dict) or "rules" not in rec:  # geometry entries (.geom files) are never packed
            continue
        for blk in SCENARIO_BLOCKS:
            b = rec.get(blk)
            if not isinstance(b, dict):
                continue
            texts: dict[str, str] = {}
            orig = {s: copy.deepcopy(b[s]) for s in SCENARIOS if s in b}
            for s in SCENARIOS:
                if s not in b:
                    continue
                v = b[s]
                t = _text(v)
                same = next((e for e, et in texts.items() if et == t), None)
                texts[s] = t
                if same is not None:
                    b[s] = {"$same": same}
                    continue
                if not isinstance(v, dict):
                    continue
                earlier = [(e, orig[e]) for e in texts if e != s]
                _pack_children(v, earlier)
        q = rec.get("quality")
        if isinstance(q, dict):
            for k, x in list(q.items()):
                xt = _text(x)
                if len(xt) < MIN_SHARED:
                    continue
                i = index.get(xt)
                if i is None:
                    i = index[xt] = len(shared)
                    shared.append(x)
                q[k] = {"$ref": i}
    doc["pack"] = FORMAT
    if shared:
        doc["shared"] = shared
    return doc


def _pack_children(v: dict[str, Any], earlier: list[tuple[str, Any]], depth: int = 0) -> None:
    """Replace each child of `v` of at least MIN_CHILD bytes that has the same text at the same path of an earlier
    scenario with {"$same": <that scenario>}. Children that differ are searched the same way, down to MAX_DEPTH."""
    for k, x in list(v.items()):
        xt = _text(x)
        if len(xt) < MIN_CHILD:
            continue
        hit = next((e for e, ev in earlier if isinstance(ev, dict) and k in ev and _text(ev[k]) == xt), None)
        if hit is not None:
            v[k] = {"$same": hit}
        elif isinstance(x, dict) and depth < MAX_DEPTH:
            _pack_children(x, [(e, ev[k]) for e, ev in earlier if isinstance(ev, dict) and isinstance(ev.get(k), dict)], depth + 1)


def _unpack_children(v: dict[str, Any], b: dict[str, Any], path: tuple[str, ...]) -> None:
    for k, x in v.items():
        if _is_marker(x, "$same"):
            src: Any = b[x["$same"]]
            for p in (*path, k):
                src = src[p]
            v[k] = copy.deepcopy(src)
        elif isinstance(x, dict):
            _unpack_children(x, b, (*path, k))


def unpack(doc: dict[str, Any]) -> dict[str, Any]:
    """Undo pack() in place. Same as unpackRecords in app/src/lib/lot/load.ts."""
    if doc.get("pack") is None:
        return doc
    if doc["pack"] != FORMAT:
        raise ValueError(f"unknown lot file packing {doc['pack']!r}")
    shared = doc.get("shared") or []
    for rec in doc.get("lots") or []:
        if not isinstance(rec, dict):
            continue
        for blk in SCENARIO_BLOCKS:
            b = rec.get(blk)
            if not isinstance(b, dict):
                continue
            for s in SCENARIOS:
                v = b.get(s)
                if _is_marker(v, "$same"):
                    b[s] = copy.deepcopy(b[v["$same"]])
                elif isinstance(v, dict):
                    _unpack_children(v, b, ())
        q = rec.get("quality")
        if isinstance(q, dict):
            for k, x in q.items():
                if _is_marker(x, "$ref"):
                    q[k] = copy.deepcopy(shared[x["$ref"]])
    del doc["pack"]
    doc.pop("shared", None)
    return doc


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] != "check":
        print(__doc__)
        return 2
    total_a = total_b = 0
    for p in argv[1:]:
        with gzip.open(p, "rb") as f:
            raw = f.read()
        doc = json.loads(raw)
        before = _text(doc)
        packed = pack(copy.deepcopy(doc))
        body = _text(packed).encode()
        a = len(gzip.compress(before.encode(), 6, mtime=0))
        b = len(gzip.compress(body, 6, mtime=0))
        back = _text(unpack(json.loads(body)))
        if back != before:
            print(f"{p}: MISMATCH after unpack")
            return 1
        total_a, total_b = total_a + a, total_b + b
        print(f"{p}: {a:,} -> {b:,} bytes ({100 * (1 - b / a):.0f}% smaller), unpack identical")
    print(f"total {total_a:,} -> {total_b:,} ({100 * (1 - total_b / max(total_a, 1)):.1f}% smaller)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
