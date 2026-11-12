"""Section-aware chunks from the extracted text.

A section stays in one chunk when it is under MAX_TOKENS. A longer section is split on
line breaks with OVERLAP_TOKENS of overlap. Short neighbouring sections in one document
are merged until they reach MIN_TOKENS, so a run of one-line headings does not make a
run of empty chunks. Tokens are estimated as characters / 4.

Each chunk keeps: chunk_id, geoid, doc_id, url, fetched_at, section (first label),
sections (all labels inside), parent, article, heading, heading_path, page_start,
page_end, text, n_tokens.

Writes corpus/chunks/chunks.jsonl (all documents) and prints counts.

Run:
    python -m pipeline.corpus.chunk
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pipeline.corpus.paths import sub

MAX_TOKENS = 800
MIN_TOKENS = 80
OVERLAP_TOKENS = 100


def n_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _split(text: str) -> Iterator[str]:
    """Split on lines into pieces under MAX_TOKENS with overlap."""
    lines = text.split("\n")
    buf: list[str] = []
    size = 0
    for line in lines:
        t = n_tokens(line) + 1
        if buf and size + t > MAX_TOKENS:
            yield "\n".join(buf)
            keep: list[str] = []
            ksize = 0
            for prev in reversed(buf):
                ksize += n_tokens(prev) + 1
                if ksize > OVERLAP_TOKENS:
                    break
                keep.insert(0, prev)
            buf, size = keep, sum(n_tokens(x) + 1 for x in keep)
        if t > MAX_TOKENS:  # one very long line (a table flattened into one line)
            for i in range(0, len(line), MAX_TOKENS * 4):
                yield line[i:i + MAX_TOKENS * 4]
            continue
        buf.append(line)
        size += t
    if buf:
        yield "\n".join(buf)


def _root(seg: dict[str, Any]) -> str | None:
    return seg.get("parent") or seg.get("section")


def heading_path(seg: dict[str, Any]) -> str:
    parts = []
    if seg.get("article"):
        parts.append(seg["article"])
    if seg.get("parent"):
        parts.append(seg["parent"])
    label = seg.get("section")
    parts.append(f"{label} {seg.get('heading', '')}".strip() if label else (seg.get("heading") or "")[:80])
    out: list[str] = []
    for p in parts:
        if p and p not in out:
            out.append(p)
    return " > ".join(out)


def doc_chunks(doc: dict[str, Any]) -> list[dict[str, Any]]:
    base = {"geoid": doc["geoid"], "doc_id": doc["doc_id"], "url": doc.get("final_url") or doc["url"],
            "fetched_at": doc.get("fetched_at"), "doc_title": doc.get("link_text")}
    # keep a section with its subsections (660-42, 660-42.A, 660-42.C) while under MAX_TOKENS,
    # and merge short neighbours
    groups: list[list[dict[str, Any]]] = []
    for seg in doc["segments"]:
        if groups:
            size = sum(n_tokens(s["text"]) for s in groups[-1])
            fits = size + n_tokens(seg["text"]) <= MAX_TOKENS
            same = _root(seg) is not None and _root(seg) == _root(groups[-1][0])
            if fits and (same or size < MIN_TOKENS):
                groups[-1].append(seg)
                continue
        groups.append([seg])
    out = []
    for g in groups:
        first = next((s for s in g if s.get("section")), g[0])
        text = "\n".join(s["text"] for s in g)
        labels = [s["section"] for s in g if s.get("section")]
        meta = {**base, "section": first.get("section"), "sections": labels, "parent": first.get("parent"),
                "article": first.get("article"), "heading": first.get("heading"), "heading_path": heading_path(first),
                "page_start": g[0]["page_start"], "page_end": g[-1]["page_end"]}
        pieces = list(_split(text)) if n_tokens(text) > MAX_TOKENS else [text]
        for k, piece in enumerate(pieces):
            out.append({**meta, "part": k if len(pieces) > 1 else None, "text": piece, "n_tokens": n_tokens(piece)})
    return out


def run() -> list[dict[str, Any]]:
    docs = sorted(sub("text").glob("*.json"))
    rows: list[dict[str, Any]] = []
    for p in docs:
        d = json.loads(p.read_text())
        if d.get("scanned") or not d.get("segments"):
            continue
        for k, c in enumerate(doc_chunks(d)):
            c["chunk_id"] = f"{c['doc_id']}:{k}"  # stable when other documents are added
            rows.append(c)
    dest = sub("chunks") / "chunks.jsonl"
    with dest.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    places = len({r["geoid"] for r in rows})
    print(f"{len(rows)} chunks from {len(docs)} documents, {places} places -> {dest}")
    return rows


def place_aliases() -> dict[str, str]:
    """Places that use another place's text: corpus/sources/shared_text.csv with columns
    geoid, source_geoid, note. Used for a county zoning ordinance that covers several sample places
    (the manifest keeps one GEOID per URL)."""
    import csv

    p = sub("sources") / "shared_text.csv"
    if not p.exists():
        return {}
    return {r["geoid"]: r["source_geoid"] for r in csv.DictReader(p.open()) if r.get("geoid")}


def load_chunks(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or sub("chunks") / "chunks.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


if __name__ == "__main__":
    run()
