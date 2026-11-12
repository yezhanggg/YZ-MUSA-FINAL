"""Text from downloaded PDF and HTML documents, with pages and section labels.

For each document in the manifest (status 200), writes corpus/text/<doc_id>.json:
  {doc_id, geoid, url, fetched_at, sha256, kind, pages, scanned, segments: [
      {section, heading, article, page_start, page_end, text}]}

A segment starts at a line that looks like a section heading. Patterns (start of line):
  "§ 27-1793", "§ 155-10.2"       ecode style printed codes
  "Section 2515", "SEC. 7-309"   word Section
  "2515.2 ...", "1303.08 USE"     dotted numbers with 3 or 4 leading digits
  "1.04.005"                      York style use codes
  "280-108. Title"                chapter-section numbers followed by a title
  "ARTICLE XXV", "PART 3", "CHAPTER 27"  kept as the article heading

Word files (.doc, .docx) are read with the macOS textutil tool, as one page. A PDF or Word link
that came back as an HTML page (a redirect to a home page) is skipped.

Repeated page headers and footers are dropped (a line pattern in the first or last four lines of
more than 15% of pages).
A PDF is flagged scanned when more than half of its pages have under 50 characters of text.
OCR is out of scope.

Run:
    python -m pipeline.corpus.extract            # every fetched document not yet extracted
    python -m pipeline.corpus.extract --force
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.corpus.fetch import load_manifest
from pipeline.corpus.paths import sub

SCANNED_PAGE_CHARS = 50
HEADER_SHARE = 0.15
EDGE_LINES = 4

RX_ARTICLE = re.compile(r"^(ARTICLE|Article|CHAPTER|Chapter|PART|Part|DIVISION|Division)\s+"
                        r"([IVXLC]+|\d+[A-Z]?)\b[.:\s-]*(.*)$")
RX_SECTION = [
    re.compile(r"^§+\s*(\d+[A-Z]?-\d+(?:\.\d+)*[A-Z]?)\.?\s*(.*)$"),
    re.compile(r"^(?:SECTION|Section|SEC\.|Sec\.)\s+(\d+(?:[.-]\d+)*[A-Z]?)\.?\s*(.*)$"),
    re.compile(r"^(\d\.\d{2}\.\d{3})\.?\s+(.*)$"),
    re.compile(r"^(\d{3,4}(?:\.\d+)+[A-Z]?)\.?\s+([A-Z(].*)$"),
    re.compile(r"^(\d{3,4})\.\s+([A-Z][A-Za-z].*)$"),
    re.compile(r"^(\d{1,3}-\d{1,4}(?:\.\d+)?[A-Z]?)\.\s+([A-Z][A-Za-z].*)$"),
    re.compile(r"^(\d{2,3}-\d{1,3}(?:\.[A-Z0-9]{1,3})*)\.?\s+([A-Z][A-Za-z&].*)$"),  # 660-42 Accessory, 660-20.F. NUMBER
]
RX_TOC = re.compile(r"(\.{4,}|…{2,}|\s{2,}\d+\s*$)")
RX_PAGE_ONLY = re.compile(r"^(page\s*)?[\divxlc]{1,4}[a-z]?(\s*of\s*\d+)?$|^[-–\s]*\d{1,4}[-–\s]*$", re.I)


RX_BARE_LABEL = re.compile(r"^(\d\.\d{2}\.\d{3}|\d{3,4}(?:\.\d+)+|§+\s*\d+[A-Z]?-\d+(?:\.\d+)*[A-Z]?)\.?$")
RX_CELL = re.compile(r"^(P|SE|CU|C|N|X|Y|S|A|-|—|•|\*|\d{1,3}%?)$")


def norm_line(line: str) -> str:
    """Line pattern for header and footer detection: digits and page tokens removed."""
    n = re.sub(r"\d+[a-z]?\b", "#", " ".join(line.split()).lower())
    return re.sub(r"^[#.\s§-]+|[#.\s-]+$", "", n)


def detect_heading(line: str) -> tuple[str, str] | None:
    """(label, heading text) when the line starts a section."""
    if len(line) > 220 or RX_TOC.search(line):
        return None
    for k, rx in enumerate(RX_SECTION):
        m = rx.match(line)
        if m:
            label, rest = m.group(1), m.group(2).strip()
            if k >= 2 and re.fullmatch(r"(19|20)\d\d", label):  # a bare year, not a section
                return None
            return label, rest[:160]
    return None


def detect_article(line: str) -> str | None:
    if len(line) > 160 or RX_TOC.search(line):
        return None
    m = RX_ARTICLE.match(line)
    if not m:
        return None
    rest = m.group(3).strip()
    if not m.group(1).isupper():  # "Article 5" in running text, "Article XX herein."
        if rest and (not rest[0].isupper() or re.search(r"\b(herein|hereof|shall|of this|and|or)\b", rest)):
            return None
        if not rest and line.rstrip().endswith("."):
            return None
    if re.search(r"\b(herein|hereof|shall)\b", rest, re.I):
        return None
    return " ".join(line.split())[:160]


def pdf_pages(path: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(path) as doc:
        return [p.get_text("text") for p in doc]


def html_pages(path: Path) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(errors="ignore"), "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        t.decompose()
    for br in soup.find_all(["br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table"]):
        br.insert_after("\n")
    return [soup.get_text("")]


def clean_pages(pages: list[str]) -> list[list[str]]:
    lines_by_page = [[" ".join(x.split()) for x in p.splitlines()] for p in pages]
    lines_by_page = [[x for x in ls if x] for ls in lines_by_page]
    if len(pages) >= 5:
        # only the first and last lines of a page can be a running header or footer
        freq = Counter(n for ls in lines_by_page
                       for n in {norm_line(x) for x in ls[:EDGE_LINES] + ls[-EDGE_LINES:]})
        cut = max(3, HEADER_SHARE * len(pages))
        drop = {n for n, c in freq.items() if c > cut and 4 <= len(n) < 90}
        lines_by_page = [[x for j, x in enumerate(ls)
                          if not ((j < EDGE_LINES or j >= len(ls) - EDGE_LINES) and norm_line(x) in drop)]
                         for ls in lines_by_page]
    return [[x for x in ls if not RX_PAGE_ONLY.match(x)] for ls in lines_by_page]


def _parent(label: str, seen: list[str]) -> str | None:
    """Longest earlier label that is an ancestor of this one (2515 for 2515.2.A). York use codes
    such as 1.04.005 take the last four digit section (1304.01)."""
    best = None
    for prev in reversed(seen[-200:]):
        if prev != label and (label.startswith(prev + ".") or label.startswith(prev + "-")):
            if best is None or len(prev) > len(best):
                best = prev
    if best is None and re.match(r"^\d\.\d{2}\.\d{3}", label):
        best = next((p for p in reversed(seen) if re.match(r"^\d{4}\.", p)), None)
    return best


def segment(lines_by_page: list[list[str]]) -> list[dict[str, Any]]:
    flat = [(pno, line) for pno, lines in enumerate(lines_by_page, 1) for line in lines]
    segs: list[dict[str, Any]] = []
    cur: dict[str, Any] = {"section": None, "heading": "", "article": None, "parent": None,
                           "page_start": 1, "page_end": 1, "lines": []}
    article = None
    seen: list[str] = []
    i = 0
    while i < len(flat):
        pno, line = flat[i]
        a = detect_article(line)
        h = None if a else detect_heading(line)
        if not a and not h and RX_BARE_LABEL.match(line) and i + 1 < len(flat):
            # label alone on its line, title on the next, unless this is a table row
            nxt = [x for _, x in flat[i + 1:i + 4]]
            if nxt and not RX_CELL.match(nxt[0]) and not any(RX_CELL.match(x) for x in nxt[1:3]) \
                    and len(nxt[0]) < 120 and not RX_BARE_LABEL.match(nxt[0]):
                h = (re.sub(r"^§+\s*", "", line.rstrip(".")), nxt[0])
                line = f"{line} {nxt[0]}"
                i += 1
        if a or h:
            if cur["lines"]:
                segs.append(cur)
            if a:
                article = a
            label = h[0] if h else None
            cur = {"section": label, "heading": (h[1] if h else a) or "", "article": article,
                   "parent": _parent(label, seen) if label else None,
                   "page_start": pno, "page_end": pno, "lines": [line]}
            if label:
                seen.append(label)
        else:
            cur["lines"].append(line)
            cur["page_end"] = pno
        i += 1
    if cur["lines"]:
        segs.append(cur)
    out = []
    for s in segs:
        text = "\n".join(s.pop("lines"))
        if text.strip():
            out.append({**s, "text": text})
    return out


def doc_pages(path: Path) -> list[str]:
    """Old Word files (.doc, .docx) through the macOS textutil tool. One page: Word files carry no
    fixed pages."""
    import subprocess

    out = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)], capture_output=True, text=True,
                         timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"textutil failed: {out.stderr[:200]}")
    return [out.stdout]


def served_page_not_doc(rec: dict[str, Any], kind: str) -> bool:
    """A link to a PDF or Word file that came back as an HTML page (a redirect to a home page or a
    login page) is not the document."""
    return kind == "html" and bool(re.search(r"\.(pdf|docx?)($|\?)", rec["url"], re.I))


def extract_doc(rec: dict[str, Any]) -> dict[str, Any]:
    path = Path(rec["path"])
    doc_id = f"{rec['geoid']}_{path.stem}"
    kind = path.suffix.lstrip(".")
    pages: list[str]
    if served_page_not_doc(rec, kind):
        return {"doc_id": doc_id, "geoid": rec["geoid"], "url": rec["url"], "final_url": rec.get("final_url"),
                "kind": kind, "pages": 0, "scanned": None, "segments": [],
                "skipped": "document link served an HTML page (redirect), not the document"}
    if kind == "pdf":
        pages = pdf_pages(path)
    elif kind == "html":
        pages = html_pages(path)
    elif kind in ("doc", "docx"):
        pages = doc_pages(path)
    else:
        return {"doc_id": doc_id, "geoid": rec["geoid"], "url": rec["url"], "kind": kind, "pages": 0,
                "scanned": None, "segments": [], "skipped": f"no extractor for {kind}"}
    empty = sum(1 for p in pages if len(p.strip()) < SCANNED_PAGE_CHARS)
    scanned = kind == "pdf" and len(pages) > 0 and empty / len(pages) > 0.5
    segs = [] if scanned else segment(clean_pages(pages))
    return {"doc_id": doc_id, "geoid": rec["geoid"], "url": rec["url"], "final_url": rec.get("final_url"),
            "fetched_at": rec["fetched_at"], "sha256": rec.get("sha256"), "kind": kind, "pages": len(pages),
            "empty_pages": empty, "scanned": scanned, "link_text": rec.get("link_text"),
            "chars": sum(len(s["text"]) for s in segs), "segments": segs}


def is_zoning_doc(rec: dict[str, Any]) -> bool:
    """Index pages are fetched to find links. They are text only when they are not plain navigation."""
    return rec.get("via") != "index"


def run(force: bool = False) -> list[dict[str, Any]]:
    out_dir = sub("text")
    stats = []
    for rec in load_manifest().values():
        if rec.get("status") != 200 or not rec.get("path") or not is_zoning_doc(rec):
            continue
        doc_id = f"{rec['geoid']}_{Path(rec['path']).stem}"
        dest = out_dir / f"{doc_id}.json"
        if dest.exists() and not force:
            d = json.loads(dest.read_text())
        else:
            d = extract_doc(rec)
            dest.write_text(json.dumps(d))
        stats.append({k: d.get(k) for k in ("doc_id", "kind", "pages", "scanned", "chars")}
                     | {"segments": len(d["segments"]), "labelled": sum(1 for s in d["segments"] if s["section"])})
        print(stats[-1], flush=True)
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    run(ap.parse_args().force)
