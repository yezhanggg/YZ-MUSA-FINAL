"""Offline tests for the tier B builder (pipeline/corpus/tierb.py): tokens, BM25, completeness, county links."""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

import pytest

pytest.importorskip("bs4")

from pipeline.corpus import tierb as T  # noqa: E402

# The same cases are checked in app/src/agent/zoningText.test.ts, so the Python and TypeScript tokens agree.
TOKEN_CASES = [
    ("Accessory Dwelling Units shall be permitted", ["accessory", "dwelling", "unit", "permitted"]),
    ("Section 1304.05 uses, classes and status", ["section", "1304.05", "use", "classe", "status"]),
    ("In-law apartments: 800 sq. ft.", ["in-law", "apartment", "800", "sq", "ft"]),
    ("What does the ADU need?", ["adu", "need"]),
]


@pytest.mark.parametrize("text,want", TOKEN_CASES)
def test_tokens(text: str, want: list[str]) -> None:
    assert T.tokens(text) == want


def test_query_expansion_adds_ordinance_words_at_half_weight() -> None:
    q = T.query_terms("Can I build an ADU?")
    assert q["adu"] == 1.0 and q["build"] == 1.0
    assert q["accessory"] == T.EXPAND_WEIGHT and q["apartment"] == T.EXPAND_WEIGHT
    assert "accessory" not in T.query_terms("Can I build an ADU?", expand=False)


def test_bm25_finds_the_synonym_passage() -> None:
    passages = [
        "Fences and walls shall not exceed six feet.",
        "Accessory apartment. One accessory apartment is permitted in a single-family dwelling.",
        "Signs in the commercial district.",
    ]
    top = T.bm25(passages, "ADU rules", k=3)
    assert top and top[0][1] == 1
    assert T.bm25(passages, "ADU rules", k=3, expand=False) == []


def test_town_key() -> None:
    assert T.town_key("Upper Darby Twp") == "upperdarby"
    assert T.town_key("Wilkes-Barre city") == "wilkesbarre"


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _doc(geoid: str, stem: str, **kw: object) -> dict[str, object]:
    return {
        "doc_id": f"{geoid}_{stem}",
        "geoid": geoid,
        "url": f"https://example.gov/{stem}.pdf",
        "fetched_at": "2026-11-11T18:00:00+00:00",
        "kind": "pdf",
        "pages": 2,
        "scanned": False,
        "segments": [],
        **kw,
    }


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tiny corpus: a full text (A), a multi-file town (B), a scan with OCR (C), a scan without OCR (D),
    a county text (E) and a place covered by it (F)."""
    root = tmp_path / "corpus"
    monkeypatch.setenv("CORPUS_DIR", str(root))
    monkeypatch.setattr(T, "RULES", tmp_path / "rules")
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "towns_index.json").write_text(
        json.dumps({"towns": [{"geoid": "4200000001", "status": "verified", "file": "pa_x_a"}]})
    )
    _write_csv(
        root / "municipalities.csv",
        [
            {"geoid": f"420000000{i}", "name": n, "county": c}
            for i, (n, c) in enumerate(
                [
                    ("Alpha borough", "X"),
                    ("Beta township", "X"),
                    ("Gamma borough", "Y"),
                    ("Delta borough", "Y"),
                    ("Echo borough", "Z"),
                    ("Foxtrot township", "Z"),
                    ("Beta township", "Q"),
                ],
                start=1,
            )
        ],
    )
    _write_csv(
        root / "availability.csv",
        [
            {"geoid": "4200000001", "source_type": "own_site", "format": "pdf", "doc_date": "2024", "landing_url": ""},
            {
                "geoid": "4200000002",
                "source_type": "own_site",
                "format": "multi_pdf",
                "doc_date": "",
                "landing_url": "",
            },
            {"geoid": "4200000005", "source_type": "county", "format": "pdf", "doc_date": "2021", "landing_url": ""},
        ],
    )
    _write_csv(root / "sources" / "pilot.csv", [{"geoid": "4200000002", "url": "u", "kind": "index", "pattern": ""}])
    _write_csv(
        root / "sources" / "shared_text.csv", [{"geoid": "4200000009", "source_geoid": "4200000099", "note": ""}]
    )
    _write_csv(
        root / "sources" / "county_coverage.csv",
        [
            {
                "geoid": "4200000006",
                "source_geoid": "4200000005",
                "note": "n",
                "coverage_url": "https://county.gov/zoning",
            }
        ],
    )
    (root / "manifest.jsonl").write_text("")
    text = root / "text"
    text.mkdir(parents=True)
    docs = [
        _doc("4200000001", "a1"),
        _doc("4200000002", "b1"),
        _doc("4200000003", "c1", scanned=True),
        _doc("4200000004", "d1", scanned=True),
        _doc("4200000005", "e1"),
    ]
    for d in docs:
        (text / f"{d['doc_id']}.json").write_text(json.dumps(d))
    chunks = []
    for g, stem in (("4200000001", "a1"), ("4200000002", "b1"), ("4200000005", "e1")):
        chunks.append(
            {
                "geoid": g,
                "doc_id": f"{g}_{stem}",
                "chunk_id": f"{g}_{stem}:0",
                "section": "101",
                "heading_path": "ARTICLE 1 > 101 Accessory dwelling",
                "page_start": 1,
                "page_end": 1,
                "text": "Section 101. An accessory dwelling unit is a second dwelling unit on a lot.",
            }
        )
    (root / "chunks").mkdir()
    (root / "chunks" / "chunks.jsonl").write_text("\n".join(json.dumps(c) for c in chunks) + "\n")
    (root / "ocr").mkdir()
    page = "SECTION 201. ACCESSORY APARTMENT\nOne accessory apartment is permitted in each single family dwelling.\n"
    (root / "ocr" / "4200000003_c1.txt").write_text(page + "\f" + page + "\f")
    return root


def test_build(corpus: Path) -> None:
    r = T.build()
    m = json.loads((corpus / "tierb" / "manifest.json").read_text())
    by = {p["geoid"]: p for p in m["places"]}
    # A: full text, rule file flagged
    assert by["4200000001"]["complete"] is True and by["4200000001"]["rule_file"] == "verified"
    # B: separate article files: never complete; its name is shared by another county
    assert by["4200000002"]["complete"] is False and by["4200000002"]["same_name"] == 2
    # C: scan read by OCR
    assert by["4200000003"]["ocr"] is True and by["4200000003"]["complete"] is True
    # D: scan without OCR: no text, not listed
    assert "4200000004" not in by and any("4200000004" in line for line in r["log"])
    # F: covered by the county text E, stored once
    assert by["4200000006"]["text_id"] == "4200000005" and by["4200000006"]["source"] == "county"
    assert by["4200000006"]["coverage_url"] == "https://county.gov/zoning"
    assert sorted(p.name for p in (corpus / "tierb" / "text").iterdir()) == [
        f"420000000{i}.json.gz" for i in (1, 2, 3, 5)
    ]
    # No machine verdict in any file
    for f in (corpus / "tierb" / "text").iterdir():
        body = json.loads(gzip.decompress(f.read_bytes()))
        assert set(body) == {"v", "id", "docs", "chunks"}
        assert all(len(c) == 6 for c in body["chunks"])
    assert "summary" not in json.dumps(m) and "status" not in json.dumps(m["places"])


def test_ocr_text_is_kept_verbatim(corpus: Path) -> None:
    T.build()
    body = json.loads(gzip.decompress((corpus / "tierb" / "text" / "4200000003.json.gz").read_bytes()))
    assert body["docs"][0]["ocr"] is True
    assert any("One accessory apartment is permitted" in c[5] for c in body["chunks"])


def test_override_marks_incomplete(corpus: Path) -> None:
    _write_csv(
        corpus / "sources" / "tierb_overrides.csv", [{"geoid": "4200000001", "complete": "false", "reason": "r"}]
    )
    T.build()
    m = json.loads((corpus / "tierb" / "manifest.json").read_text())
    a = next(p for p in m["places"] if p["geoid"] == "4200000001")
    assert a["complete"] is False and a["incomplete_reasons"] == ["r"]


def test_publish_copies_only_listed_files(corpus: Path, tmp_path: Path) -> None:
    T.build()
    dest = tmp_path / "host" / "zoning_text"
    (dest / "text").mkdir(parents=True)
    (dest / "text" / "old.json.gz").write_bytes(b"x")
    out = T.publish(dest)
    assert out["files"] == 5
    assert not (dest / "text" / "old.json.gz").exists()
    assert (dest / "manifest.json").exists()
