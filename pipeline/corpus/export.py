"""Per-place files for serving: corpus/serve/<geoid>.json.

Each file holds the place's chunks (text, section, heading path, pages, URL, retrieval
date) and, when one exists, the machine-read draft summary with its quote checks and the
label "machine-read, not verified, read the quoted text". The status shown is the
consistent status (most limiting reading of the model's own checked fields).

Vectors are not exported: the prototype searcher (search_zoning_text.mjs) uses BM25 only,
so it runs in Node or a browser with no model.

Run:
    python -m pipeline.corpus.export
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from pipeline.corpus.chunk import load_chunks, place_aliases
from pipeline.corpus.evaluate import consistent_status
from pipeline.corpus.paths import sub

KEEP = ("chunk_id", "section", "heading_path", "page_start", "page_end", "url", "fetched_at", "text")


def run() -> dict[str, int]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in load_chunks():
        by[c["geoid"]].append({k: c.get(k) for k in KEEP})
    for geoid, src in place_aliases().items():  # a county ordinance shared by several places
        if src in by and geoid not in by:
            by[geoid] = by[src]
    out = sub("serve")
    sizes = {}
    index = []
    for geoid, chunks in by.items():
        summary = None
        p = sub("drafts") / f"{geoid}.json"
        if p.exists():
            d = json.loads(p.read_text())
            summary = {
                "label": d["label"],
                "model": d["model"],
                "made_on": d["made_on"],
                "status_consistent": consistent_status(d["draft"]),
                "draft": d["draft"],
                "unsupported": d["unsupported"],
                "quote_checks": d["quote_checks"],
            }
        doc = {"geoid": geoid, "tier": "B", "chunks": chunks, "summary": summary}
        f = out / f"{geoid}.json"
        f.write_text(json.dumps(doc, separators=(",", ":")))
        sizes[geoid] = f.stat().st_size
        index.append({"geoid": geoid, "chunks": len(chunks), "bytes": sizes[geoid], "has_summary": bool(summary)})
    (out / "index.json").write_text(json.dumps(index, indent=1))
    return sizes


if __name__ == "__main__":
    s = run()
    v = sorted(s.values())
    print(
        f"{len(v)} places, total {sum(v) / 1e6:.1f} MB, median {v[len(v) // 2] / 1e3:.0f} kB, max {v[-1] / 1e6:.2f} MB"
    )
