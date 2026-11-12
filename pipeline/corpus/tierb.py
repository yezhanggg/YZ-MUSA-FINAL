"""Tier B: per-place search files of public zoning text, for the assistant's quote search.

The assistant tool search_zoning_text (app/src/agent/zoningText.ts) loads one file per place and
ranks its passages with BM25 in the browser or in Node. It returns verbatim passages with section,
pages, link and fetch date. It never returns a machine verdict: no status, path or district list.
That is why the machine drafts (corpus/drafts) are not in these files.

Inputs (all under the corpus folder):
  chunks/chunks.jsonl        passages from documents with a text layer (chunk.py)
  ocr/<doc_id>.txt           OCR text of a scanned document, pages split by form feeds (optional)
  text/<doc_id>.json         per document: pages, scanned flag, skipped reason
  manifest.jsonl             fetch log: URL, fetch time, Last-Modified
  availability.csv           survey row per place: source type, landing page, document date
  municipalities.csv         names and counties
  sources/pilot.csv          the fetched sources (kind doc or index)
  sources/shared_text.csv    places that use another place's text (county ordinance)
  sources/county_coverage.csv  more places a county ordinance covers, from the county's own page
  shared/rules/towns_index.json (repo)  which places have a hand-checked rule file

Output (corpus/tierb/):
  manifest.json              {version, built_at, places: [...], texts: {...}}
  text/<text_id>.json.gz     {v, id, docs: [...], chunks: [[doc, section, heading, p0, p1, text], ...]}

A county ordinance is stored once and named by the place it was fetched for. Every place it covers
points at it with text_id.

"complete" is true only when every document of the source has text (a text layer or OCR of every
page) and the source is one whole ordinance, not a set of separate article files. Only then may
the assistant say "not found in the text searched".

Run:
    python -m pipeline.corpus.tierb build              # corpus/tierb/
    python -m pipeline.corpus.tierb publish <dir>      # copy manifest and text files to <dir>
    python -m pipeline.corpus.tierb eval               # BM25 variants on the pilot retrieval questions
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.corpus.chunk import doc_chunks, load_chunks
from pipeline.corpus.paths import RULES, corpus_root, sub

VERSION = 1

# ---------------------------------------------------------------- tokens (same as app/src/agent/zoningText.ts)
TOKEN = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
STOP = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "to",
        "and",
        "or",
        "in",
        "on",
        "for",
        "by",
        "with",
        "be",
        "is",
        "are",
        "shall",
        "may",
        "any",
        "as",
        "at",
        "from",
        "this",
        "that",
        "which",
        "such",
        "than",
        "not",
        "no",
        "its",
        "it",
        "all",
        "each",
        "per",
        "what",
        "does",
        "do",
        "can",
        "i",
        "my",
        "how",
        "much",
        "many",
        "must",
        "there",
    ]
)


def stem(t: str) -> str:
    """Plural s off: dwellings -> dwelling, uses -> use. Keeps ss, us, is (class, status, analysis)."""
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")) and not t[-2].isdigit():
        return t[:-1]
    return t


def tokens(text: str) -> list[str]:
    return [stem(t) for t in TOKEN.findall(text.lower()) if t not in STOP]


# Query words that also search for the words ordinances use. Weight 0.5 for the added words.
EXPAND: list[tuple[re.Pattern[str], list[str]]] = [
    (
        re.compile(
            r"\badus?\b|accessory dwelling|granny|in-law|inlaw|accessory apartment|backyard (home|cottage|house)|"
            r"carriage house|secondary (unit|dwelling)|guest house|casita|accessory unit"
        ),
        ["accessory", "dwelling", "apartment", "in-law", "granny", "carriage", "cottage", "secondary", "adu"],
    ),
    (re.compile(r"\bparking\b|\bpark\b"), ["off-street", "space"]),
    (re.compile(r"\bsetback|\byard\b"), ["setback", "yard"]),
    (re.compile(r"\bsize\b|\bbig\b|square f|floor area|\bsq\b"), ["floor", "area", "square", "feet"]),
    (re.compile(r"\bowner\b|owner-occup|live on"), ["owner", "occupied", "occupy", "reside"]),
    (re.compile(r"\btall\b|\bheight\b"), ["height", "feet", "storie", "story"]),
]
EXPAND_WEIGHT = 0.5


def query_terms(query: str, expand: bool = True) -> dict[str, float]:
    """Query tokens with weights: 1 for the user's words, EXPAND_WEIGHT for added words."""
    out: dict[str, float] = {}
    for t in tokens(query):
        out[t] = 1.0
    if expand:
        low = query.lower()
        for rx, words in EXPAND:
            if rx.search(low):
                for w in words:
                    for t in tokens(w):
                        out.setdefault(t, EXPAND_WEIGHT)
    return out


def bm25(
    passages: list[str], query: str, k: int = 5, expand: bool = True, k1: float = 1.5, b: float = 0.75
) -> list[tuple[float, int]]:
    docs = [tokens(p) for p in passages]
    n = len(docs)
    if not n:
        return []
    avg = sum(len(d) for d in docs) / n
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    q = query_terms(query, expand)
    scored = []
    for i, d in enumerate(docs):
        tf = Counter(d)
        s = 0.0
        for t, w in q.items():
            f = tf.get(t)
            if not f:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += w * idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / avg))
        if s > 0:
            scored.append((s, i))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[:k]


# ---------------------------------------------------------------- sources
def _csv(name: str) -> list[dict[str, str]]:
    """A CSV under the corpus folder, or [] when it is missing."""
    path = corpus_root() / name
    return list(csv.DictReader(path.open())) if path.exists() else []


def places_table() -> dict[str, dict[str, str]]:
    return {r["geoid"]: r for r in _csv("municipalities.csv")}


def rule_index() -> dict[str, str]:
    """GEOID (and alias GEOIDs) -> status of the hand-checked rule file, for drafted and verified towns."""
    p = RULES / "towns_index.json"
    if not p.exists() or not p.read_text().strip():
        return {}
    out = {}
    for t in json.loads(p.read_text()).get("towns", []):
        if t.get("status") in ("drafted", "verified"):
            for g in [t["geoid"], *(t.get("geoid_aliases") or [])]:
                out[g] = t["status"]
    return out


def ocr_pages(doc_id: str) -> list[str] | None:
    p = sub("ocr", create=False) / f"{doc_id}.txt"
    if not p.exists() or p.stat().st_size == 0:
        return None
    pages = p.read_text(errors="replace").split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def ocr_chunks(doc: dict[str, Any], pages: list[str]) -> list[dict[str, Any]]:
    """Passages from OCR text, made the same way as from a text layer."""
    from pipeline.corpus.extract import clean_pages, segment

    d = {**doc, "segments": segment(clean_pages(pages))}
    out = []
    for k, c in enumerate(doc_chunks(d)):
        c["chunk_id"] = f"{doc['doc_id']}:ocr{k}"
        c["ocr"] = True
        out.append(c)
    return out


def _date(s: str | None) -> str | None:
    return s[:10] if s else None


def _last_modified(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%a, %d %b %Y %H:%M:%S GMT").date().isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------- build
def build(out_dir: Path | None = None, min_ocr_chars: int = 200) -> dict[str, Any]:
    out = out_dir or sub("tierb")
    (out / "text").mkdir(parents=True, exist_ok=True)
    places = places_table()
    avail = {r["geoid"]: r for r in _csv("availability.csv")}
    pilot_kind: dict[str, set[str]] = defaultdict(set)
    for r in _csv("sources/pilot.csv"):
        pilot_kind[r["geoid"]].add(r["kind"])
    fetch = {}
    for line in (corpus_root() / "manifest.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("path"):
                fetch[f"{r['geoid']}_{Path(r['path']).stem}"] = r
    rules = rule_index()

    # documents per source place
    docs_by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in sorted(sub("text").glob("*.json")):
        d = json.loads(p.read_text())
        docs_by[d["geoid"]].append(d)
    chunks_by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in load_chunks():
        chunks_by[c["geoid"]].append(c)

    texts: dict[str, dict[str, Any]] = {}
    log: list[str] = []
    for geoid, docs in sorted(docs_by.items()):
        rows = list(chunks_by.get(geoid, []))
        problems: list[str] = []
        doc_meta: list[dict[str, Any]] = []
        n_ocr = 0
        for d in sorted(docs, key=lambda x: x["doc_id"]):
            f = fetch.get(d["doc_id"], {})
            meta = {
                "url": d.get("final_url") or d["url"],
                "fetched_on": _date(d.get("fetched_at") or f.get("fetched_at")),
                "last_modified": _last_modified(f.get("last_modified")),
                "pages": d.get("pages") or None,
                "ocr": False,
            }
            if d.get("skipped"):
                problems.append(f"skipped {d['doc_id']}: {d['skipped']}")
                continue
            if d.get("scanned"):
                pages = ocr_pages(d["doc_id"])
                text_chars = sum(len(x.strip()) for x in pages or [])
                if pages is None or text_chars < min_ocr_chars:
                    problems.append(f"scan without OCR: {d['doc_id']} ({d.get('pages')} pages)")
                    continue
                if len(pages) != int(d.get("pages") or 0):
                    problems.append(f"OCR page count {len(pages)} != {d.get('pages')} for {d['doc_id']}")
                rows.extend(ocr_chunks(d, pages))
                meta["ocr"] = True
                n_ocr += 1
            doc_meta.append({"doc_id": d["doc_id"], **meta})
        if not rows:
            log.append(f"{geoid}: no text ({'; '.join(problems) or 'no documents'})")
            continue
        multi = "index" in pilot_kind.get(geoid, set()) or (avail.get(geoid, {}).get("format") == "multi_pdf")
        if multi:
            problems.append("assembled from separate article files linked on the town page; the set may be incomplete")
        doc_index = {m["doc_id"]: i for i, m in enumerate(doc_meta)}
        packed = []
        for c in rows:
            if c["doc_id"] not in doc_index:
                continue
            packed.append(
                [
                    doc_index[c["doc_id"]],
                    c.get("section"),
                    c.get("heading_path") or "",
                    c.get("page_start"),
                    c.get("page_end"),
                    c["text"],
                ]
            )
        texts[geoid] = {
            "id": geoid,
            "docs": [{k: v for k, v in m.items() if k != "doc_id"} for m in doc_meta],
            "chunks": packed,
            "complete": not problems,
            "problems": problems,
            "ocr_docs": n_ocr,
        }

    # places: own text, shared county text, county coverage list
    links: dict[str, tuple[str, str, str | None]] = {g: (g, "own", None) for g in texts}
    for r in _csv("sources/shared_text.csv") + _csv("sources/county_coverage.csv"):
        if r["source_geoid"] in texts and r["geoid"] not in texts:
            links[r["geoid"]] = (r["source_geoid"], "county", r.get("coverage_url") or None)
    # Pine township's own fetch was a county home page (no text). It is covered by the county text above.

    manifest_places = []
    sizes = {}
    for tid, t in texts.items():
        body = {"v": VERSION, "id": tid, "docs": t["docs"], "chunks": t["chunks"]}
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        dest = out / "text" / f"{tid}.json.gz"
        dest.write_bytes(gzip.compress(raw, 9, mtime=0))
        sizes[tid] = {"raw": len(raw), "gz": dest.stat().st_size}
    for geoid, (tid, how, coverage_url) in sorted(links.items()):
        p = places.get(geoid, {})
        src = places.get(tid, {})
        a = avail.get(tid, {})
        t = texts[tid]
        fetched = sorted({d["fetched_on"] for d in t["docs"] if d["fetched_on"]})
        manifest_places.append(
            {
                "geoid": geoid,
                "name": p.get("name"),
                "county": p.get("county"),
                "text_id": tid,
                "source": "own_site" if how == "own" and a.get("source_type") != "county" else "county",
                "source_note": (
                    None
                    if how == "own"
                    else f"County zoning ordinance, fetched for {src.get('name')} ({src.get('county')} County)."
                ),
                "coverage_url": coverage_url,
                "landing_url": a.get("landing_url") or None,
                "urls": [d["url"] for d in t["docs"]][:3],
                "n_docs": len(t["docs"]),
                "fetched_on": fetched[-1] if fetched else None,
                "doc_date": a.get("doc_date") or None,
                "complete": t["complete"],
                "incomplete_reasons": t["problems"],
                "ocr": t["ocr_docs"] > 0,
                "rule_file": rules.get(geoid),
                "chunks": len(t["chunks"]),
                "bytes_gz": sizes[tid]["gz"],
            }
        )
    manifest = {
        "version": VERSION,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "label": "Unverified text search of public zoning text. Not a rule file, not a zoning determination.",
        "places": manifest_places,
        "texts": {tid: {"chunks": len(t["chunks"]), **sizes[tid]} for tid, t in texts.items()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    return {"places": len(manifest_places), "texts": len(texts), "log": log, "sizes": sizes, "out": str(out)}


def publish(dest: Path, src: Path | None = None) -> dict[str, int]:
    """Copy the manifest and the text files to a publishable folder (same layout)."""
    s = src or sub("tierb")
    (dest / "text").mkdir(parents=True, exist_ok=True)
    m = json.loads((s / "manifest.json").read_text())
    keep = {p["text_id"] for p in m["places"]}
    for old in (dest / "text").glob("*.json.gz"):
        if old.name[: -len(".json.gz")] not in keep:
            old.unlink()
    total = 0
    for tid in keep:
        shutil.copy2(s / "text" / f"{tid}.json.gz", dest / "text" / f"{tid}.json.gz")
        total += (dest / "text" / f"{tid}.json.gz").stat().st_size
    shutil.copy2(s / "manifest.json", dest / "manifest.json")
    return {"files": len(keep) + 1, "bytes": total + (dest / "manifest.json").stat().st_size}


# ---------------------------------------------------------------- retrieval check
def retrieval_eval(k: int = 10) -> dict[str, Any]:
    """Top 5 / top 10 hit rate of BM25 with and without stemming and expansion, on the pilot
    retrieval questions (gold from the rule files on disk), on the text-layer chunks."""
    from pipeline.corpus import evaluate as ev

    ev.GOLD_SOURCE = "worktree"
    ev.GOLD_STATUSES = ("verified",)
    gold = ev.gold_files()
    by_place: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in load_chunks():
        by_place[c["geoid"]].append(c)
    global stem
    plain_stem = stem
    variants = {"bm25": (False, False), "bm25_stem": (True, False), "bm25_stem_expand": (True, True)}
    hits: dict[str, list[int | None]] = {v: [] for v in variants}
    n = 0
    for geoid, g in gold.items():
        cs = by_place.get(geoid)
        if not cs:
            continue
        term = (ev.get(g["rules"], ("adu", "term")) or {}).get("value")
        for qtype, (path, question) in ev.QUESTIONS.items():
            item = ev.get(g["rules"], path)
            if not isinstance(item, dict) or not item.get("section"):
                continue
            if item.get("value") is None and item.get("confidence") == "unverified":
                continue
            labels = [x for x in ev.labels_in(item["section"]) if any(ev.chunk_has(c, x) for c in cs)]
            quotes = [q for q in ev.gold_quotes(item) if any(q in ev.norm(c["text"]) for c in cs)]
            if not labels and not quotes:
                continue

            def ok(c: dict[str, Any], labels: list[str] = labels, quotes: list[str] = quotes) -> bool:
                if labels:
                    return any(ev.chunk_has(c, x) for x in labels)
                return any(q in ev.norm(c["text"]) for q in quotes)

            q = question if not term or qtype == "adu_term" else question.replace("accessory dwelling unit", term)
            n += 1
            passages = [f"{c.get('heading_path') or ''} {c['text']}" for c in cs]
            for name, (use_stem, expand) in variants.items():
                stem = plain_stem if use_stem else (lambda t: t)  # type: ignore[assignment]
                try:
                    top = bm25(passages, q, k, expand=expand)
                finally:
                    stem = plain_stem
                hits[name].append(next((i + 1 for i, (_, j) in enumerate(top) if ok(cs[j])), None))
    rate = lambda xs, kk: round(100 * sum(1 for x in xs if x and x <= kk) / max(len(xs), 1), 1)  # noqa: E731
    return {
        "questions": n,
        "towns": len([g for g in gold if g in by_place]),
        **{v: {"top5": rate(h, 5), "top10": rate(h, 10)} for v, h in hits.items()},
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "publish", "eval"])
    ap.add_argument("dest", nargs="?")
    a = ap.parse_args()
    if a.cmd == "build":
        r = build()
        gz = sorted(v["gz"] for v in r["sizes"].values())
        raw = sum(v["raw"] for v in r["sizes"].values())
        print(
            f"{r['places']} places, {r['texts']} text files, raw {raw / 1e6:.1f} MB, gzip {sum(gz) / 1e6:.1f} MB "
            f"(median {gz[len(gz) // 2] / 1e3:.0f} kB, max {gz[-1] / 1e6:.2f} MB) -> {r['out']}"
        )
        for line in r["log"]:
            print(" ", line)
    elif a.cmd == "publish":
        if not a.dest:
            raise SystemExit("publish needs a destination folder")
        print(publish(Path(a.dest).expanduser()))
    else:
        print(json.dumps(retrieval_eval(), indent=1))
