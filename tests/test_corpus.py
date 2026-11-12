"""Offline tests for the machine-read corpus pipeline (no network, no model, no API)."""
from __future__ import annotations

import pytest

pytest.importorskip("bs4")

from pipeline.corpus import chunk as C  # noqa: E402
from pipeline.corpus import draft_rules as D  # noqa: E402
from pipeline.corpus import evaluate as EV  # noqa: E402
from pipeline.corpus import extract as E  # noqa: E402
from pipeline.corpus import fetch as F  # noqa: E402


@pytest.mark.parametrize("line,label", [
    ("§ 27-1793. Accessory dwelling units.", "27-1793"),
    ("§ 155-10.2 Alternative housing options for elderly", "155-10.2"),
    ("SECTION 2515. ACCESSORY DWELLING UNITS", "2515"),
    ("SECTION 2001. COMPLIANCE REQUIRED", "2001"),
    ("Section 7-309 Accessory dwelling unit", "7-309"),
    ("1303.06 SETBACKS, BUILDING AREA", "1303.06"),
    ("280-108. Accessory uses.", "280-108"),
])
def test_heading_detected(line, label):
    h = E.detect_heading(line)
    assert h is not None and h[0] == label


@pytest.mark.parametrize("line", [
    "2023 Amendments were adopted.",
    "2515 Accessory Dwelling Units .................. 25-30",
    "The lot shall be 2,000 square feet.",
])
def test_not_heading(line):
    assert E.detect_heading(line) is None


def test_article_in_running_text_is_not_a_heading():
    assert E.detect_article("Article XX herein.") is None
    assert E.detect_article("ARTICLE XXV. PERFORMANCE STANDARDS") is not None


def test_running_header_dropped_and_bare_label_kept():
    pages = [f"1302.02 PLANNING AND ZONING CODE {i}\nbody text line {i}\nmore text" for i in range(10)]
    pages[3] = "1302.02 PLANNING AND ZONING CODE 4\n1.04.005\nAccessory Dwelling Unit\na)\nDefinition: a unit."
    lines = E.clean_pages(pages)
    assert all("PLANNING AND ZONING CODE" not in x for ls in lines for x in ls)
    segs = E.segment(lines)
    assert any(s["section"] == "1.04.005" and s["heading"] == "Accessory Dwelling Unit" for s in segs)


def test_use_table_row_is_not_a_heading():
    lines = [["USE DESCRIPTION", "1.04.005", "Accessory Dwelling Unit", "SE", "SE", "SE"]]
    segs = E.segment(lines)
    assert not any(s["section"] == "1.04.005" for s in segs)


def test_parent_label():
    assert E._parent("2515.2", ["2501", "2515"]) == "2515"
    assert E._parent("1.04.005", ["1303.08", "1304.01"]) == "1304.01"


def test_long_section_split_with_overlap():
    text = "\n".join(f"line {i} " + "word " * 30 for i in range(200))
    pieces = list(C._split(text))
    assert len(pieces) > 1
    assert all(C.n_tokens(p) <= C.MAX_TOKENS + 50 for p in pieces)
    assert pieces[0].split("\n")[-1] in pieces[1]


def test_blocked_hosts():
    assert F.is_blocked("https://ecode360.com/12345")
    assert F.is_blocked("https://library.municode.com/pa/x")
    assert F.is_blocked("https://codelibrary.amlegal.com/codes/x")
    assert not F.is_blocked("https://www.yorkcity.org/wp-content/uploads/x.pdf")


def test_quote_check():
    hits = [{"chunk_id": "a", "text": "Accessory dwelling units shall be permitted\nas a use by special exception."},
            {"chunk_id": "b", "text": "One (1) additional off-street parking space shall be provided."}]
    draft = {
        "status": {"value": "special_exception", "support": [
            {"quote": "permitted as a use by special exception", "chunk": "C1", "section": "2515"}]},
        "parking_spaces_for_adu": {"value": 1, "support": [
            {"quote": "One (1) additional off-street parking space", "chunk": "C1", "section": "2515"}]},
        "owner_occupancy": {"value": True, "support": [
            {"quote": "the owner must live in the house", "chunk": "C1", "section": "2515"}]},
        "could_not_find": [],
    }
    clean, unsupported = D.verify(draft, hits)
    assert clean["status"]["support"][0]["check"] == "ok"
    assert clean["parking_spaces_for_adu"]["support"][0]["check"] == "other_chunk"
    assert clean["owner_occupancy"].get("dropped") is True
    assert unsupported and unsupported[0]["field"] == "owner_occupancy"


def test_consistent_status():
    d = {"status": {"value": "special_exception"}, "family_only": {"value": True}, "forms": {"value": ["internal"]}}
    assert EV.consistent_status(d) == "family_only"
    d = {"status": {"value": "special_exception"}, "family_only": {"value": None},
         "forms": {"value": ["garage_conversion"]}}
    assert EV.consistent_status(d) == "conversion_only"


def test_labels_in_citation():
    assert EV.labels_in("2515.2 and 2515.2.A(8)") == ["2515.2", "2515.2"]
    assert "1303.08" in EV.labels_in("Table 1303.08(A)")
    assert EV._related("2515", "2515.2")


def test_absence_kept_and_bare_value_dropped():
    hits = [{"chunk_id": "a", "text": "Single-family detached dwelling. No other use."}]
    draft = {"status": {"value": "not_addressed", "support": []}, "approval_path": "special_exception",
             "could_not_find": ["ADU text"]}
    clean, unsupported = D.verify(draft, hits)
    assert clean["status"]["value"] == "not_addressed" and clean["status"]["absence"] is True
    assert clean["approval_path"].get("dropped") is True
    assert [u["field"] for u in unsupported] == ["approval_path"]


def test_pdf_link_served_as_html_is_skipped():
    rec = {"url": "https://www.example.gov/Documents/Zoning%20Ordinance.pdf", "geoid": "4200000000",
           "path": "/nonexistent/x.html", "fetched_at": "2026-11-11T00:00:00+00:00"}
    assert E.served_page_not_doc(rec, "html")
    assert not E.served_page_not_doc({**rec, "url": "https://www.example.gov/zoning/"}, "html")
    d = E.extract_doc(rec)
    assert d["segments"] == [] and "redirect" in d["skipped"]
