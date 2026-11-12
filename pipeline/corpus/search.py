"""Hybrid search over one municipality's zoning text: BM25 plus vectors.

search(place, query, k) takes a GEOID or a municipality name ("Manheim township",
"York city, York") and returns chunks with section, heading path, pages, URL, retrieval
date and score. Scores: reciprocal rank fusion (RRF, k=60) of the BM25 rank and the
vector rank. mode="vector" or mode="bm25" uses one of them alone.

Run:
    python -m pipeline.corpus.search "Manheim township" "accessory dwelling unit special exception" -k 5
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from functools import lru_cache
from typing import Any

import numpy as np

from pipeline.corpus.chunk import load_chunks, place_aliases
from pipeline.corpus.paths import sub

RRF_K = 60
TOKEN = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
STOP = set("the a an of to and or in on for by with be is are shall may any as at from this that which such "
           "than not no its it all each per".split())


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


@lru_cache(maxsize=1)
def _chunks() -> tuple[list[dict[str, Any]], dict[str, list[int]]]:
    rows = load_chunks()
    by_place: dict[str, list[int]] = {}
    for i, c in enumerate(rows):
        by_place.setdefault(c["geoid"], []).append(i)
    for geoid, src in place_aliases().items():  # a county ordinance that covers this place too
        if src in by_place and geoid not in by_place:
            by_place[geoid] = by_place[src]
    return rows, by_place


@lru_cache(maxsize=4)
def _vectors(model: str) -> np.ndarray:
    rows, _ = _chunks()
    ids = json.loads((sub("index") / f"{model}.ids.json").read_text())
    vec = np.load(sub("index") / f"{model}.f16.npy").astype(np.float32)
    pos = {cid: i for i, cid in enumerate(ids)}
    order = [pos[c["chunk_id"]] for c in rows]
    return vec[order]


@lru_cache(maxsize=256)
def _bm25(geoid: str):
    from rank_bm25 import BM25Okapi

    rows, by_place = _chunks()
    docs = [tokens((rows[i].get("heading_path") or "") + " " + rows[i]["text"]) for i in by_place.get(geoid, [])]
    return BM25Okapi(docs) if docs else None


@lru_cache(maxsize=1)
def _names() -> dict[str, str]:
    out: dict[str, str] = {}
    p = sub("") / "municipalities.csv"
    for r in csv.DictReader(p.open()):
        g = r["geoid"]
        # rows are in population order: a shared name goes to the larger place
        for key in [g, r["name"].lower(), f"{r['name']}, {r['county']}".lower(),
                    *[a for a in (r.get("geoid_aliases") or "").split(";") if a]]:
            out.setdefault(key, g)
    return out


def resolve_place(place: str) -> str:
    names = _names()
    key = place.strip().lower()
    if key in names:
        return names[key]
    hits = [g for n, g in names.items() if n.startswith(key)]
    if len(set(hits)) == 1:
        return hits[0]
    raise KeyError(f"place not found or ambiguous: {place}")


def search(place: str, query: str, k: int = 10, model: str = "bge", mode: str = "hybrid") -> list[dict[str, Any]]:
    geoid = resolve_place(place)
    rows, by_place = _chunks()
    idx = by_place.get(geoid, [])
    if not idx:
        return []
    ranks: dict[int, float] = {}
    if mode in ("hybrid", "bm25"):
        bm = _bm25(geoid)
        s = bm.get_scores(tokens(query))
        for r, j in enumerate(np.argsort(-s)[:200]):
            ranks[idx[j]] = ranks.get(idx[j], 0.0) + 1.0 / (RRF_K + r + 1)
    if mode in ("hybrid", "vector"):
        from pipeline.corpus.embed import encode_query

        q = encode_query(model, query)
        sims = _vectors(model)[idx] @ q
        for r, j in enumerate(np.argsort(-sims)[:200]):
            ranks[idx[j]] = ranks.get(idx[j], 0.0) + 1.0 / (RRF_K + r + 1)
    top = sorted(ranks.items(), key=lambda kv: -kv[1])[:k]
    out = []
    for i, score in top:
        c = rows[i]
        out.append({"chunk_id": c["chunk_id"], "geoid": geoid, "section": c.get("section"),
                    "sections": c.get("sections"), "heading_path": c.get("heading_path"),
                    "page_start": c.get("page_start"), "page_end": c.get("page_end"), "url": c.get("url"),
                    "retrieved_on": (c.get("fetched_at") or "")[:10], "score": round(score, 5), "text": c["text"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("place")
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--model", default="bge")
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "bm25", "vector"])
    a = ap.parse_args()
    for r in search(a.place, a.query, a.k, a.model, a.mode):
        print(f"[{r['score']}] {r['section']} | {r['heading_path']} | p.{r['page_start']}-{r['page_end']}")
        print(f"    {r['url']}  (retrieved {r['retrieved_on']})")
        print("    " + " ".join(r["text"].split())[:300])


if __name__ == "__main__":
    main()
