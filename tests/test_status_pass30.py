"""Pass 30: status nuances the engine could not hold before (shared/rules/TOWNS.md, pass 30).

adu.status employee_quarters (Bethel, Delaware), adu.status_dispute (O'Hara 455-1.3, Penn Westmoreland MDR table and
text), a gate's status_only_if (Worcester Option 3) and adu.status_by_overlay (Warwick, Lancaster, VO)."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import rules
from pipeline.places_index import ladder

RULES = Path(__file__).resolve().parents[1] / "shared" / "rules"
DET = {"building_type": "detached", "lot_sqft": 20000, "house_sqft": 2000}
LOT_TOWNS = (
    "philadelphia",
    "pittsburgh",
    "pa_lehigh_allentown",
    "pa_montgomery_lower_merion",
    "pa_montgomery_narberth",
    "pa_montgomery_upper_dublin",
    "pa_chester_west_chester",
    "pa_chester_phoenixville",
    "pa_chester_west_vincent",
    "pa_chester_malvern",
    "pa_chester_east_brandywine",
    "pa_centre_college",
)


def _file(name: str) -> dict:
    return json.loads((RULES / f"{name}.json").read_text())


def _answer(name: str) -> dict:
    return ladder.rule_answer(_file(name), {"file": name, "status": "verified"})


def _conds(out: dict, kind: str) -> list[dict]:
    return [c for c in out["conditions"] if c["kind"] == kind]


def test_employee_quarters_is_its_own_status():
    out = rules.resolve("pa_delaware_bethel", "today", {**DET, "zoning_district": "R-1"})
    assert out["adu_status"] == "employee_quarters"
    assert any(r.startswith("The code's ADU status is employee quarters only (480-41H(5)") for r in out["reasons"])
    assert not _conds(out, "family")  # the code names no relatives
    assert _conds(out, "occupancy")[0]["condition"] == "Household employees, caretakers or watchmen"
    # under the bill the status gives way, as family only does
    assert rules.resolve("pa_delaware_bethel", "state_reform", {**DET, "zoning_district": "R-1"})["adu_status"] == (
        "allowed_by_right"
    )
    a = _answer("pa_delaware_bethel")
    assert (a["status"], a["legal_class"]) == ("limited", "family_only")
    assert a["status_detail"].startswith("quarters for the household's own employees, caretakers or watchmen only")


def test_disputed_status_qualifies_the_lot_the_file_reading_lets_in():
    out = rules.resolve("pa_allegheny_ohara", "today", {**DET, "zoning_district": "R-1", "overlays": []})
    assert out["adu_status"] == "family_only" and out["approval_qualifier"] == "conditional_on_reading"
    lead = "By right only if the reading that lets this lot in holds: The code's ADU status is disputed. "
    line = next(r for r in out["reasons"] if r.startswith(lead))
    assert "Read one way it is family only (455-2.2, 455-4.2B(14)" in line
    assert "Read another way it is prohibited, not allowed (455-1.3, 455-20.7C): 'Unless a proposed use" in line
    assert line.endswith("Ask the zoning officer")
    assert _conds(out, "status_dispute")[0]["section"].startswith("455-1.3")
    # the gate it replaced is gone, so the dispute is said once
    assert not any(c["section"] == "455-1.3" for c in out["conditions"])
    # outside the districts the ADU rule reaches there is no ADU status to dispute
    assert not _conds(rules.resolve("pa_allegheny_ohara", "today", {**DET, "zoning_district": "C"}), "status_dispute")
    # under the bill the town's status gives way, so the dispute is not said
    assert not _conds(
        rules.resolve("pa_allegheny_ohara", "state_reform", {**DET, "zoning_district": "R-1"}), "status_dispute"
    )


def test_disputed_status_counts_as_limited_with_the_more_limiting_class():
    a = _answer("pa_allegheny_ohara")
    assert a["status"] == "limited" and a["approval"] is None  # never a clear allow, never a firm no
    assert a["legal_class"] == "none"  # the more limiting reading
    assert a["status_detail"].startswith(f"{ladder.DISPUTED_DETAIL}: the code supports two readings, so ask")


def test_table_and_text_conflict_takes_the_more_limiting_reading():
    out = rules.resolve("pa_westmoreland_penn", "today", {**DET, "zoning_district": "MDR"})
    assert out["adu_status"] == "not_addressed" and out["approval_qualifier"] is None
    assert set(out["approval_by_type"].values()) == {"variance"}
    line = out["reasons"][0]
    assert line.startswith(
        "The use table and the text conflict on the ADU status in MDR. The text gives not addressed (190-402"
    )
    assert "The use table gives conversion only, by right (Attachment 2): the Zoning Use Table" in line
    assert line.endswith("The tool reads the more limiting one. Ask the zoning officer")
    assert not _conds(
        rules.resolve("pa_westmoreland_penn", "today", {**DET, "zoning_district": "RR"}), "status_dispute"
    )
    unknown = _conds(rules.resolve("pa_westmoreland_penn", "today", DET), "status_dispute")[0]["condition"]
    assert unknown.startswith("The use table and the text conflict on the ADU status in MDR. The use table gives")
    a = _answer("pa_westmoreland_penn")  # a dispute in one district: the town status and path stay
    assert (a["status"], a["approval"], a["legal_class"]) == ("limited", "by_right", "conversion_only")
    assert "ADU status disputed in MDR: the use table and the text conflict" in a["status_detail"]


def test_status_only_if_a_lot_fact():
    def wo(**kw):
        return rules.resolve(
            "pa_montgomery_worcester", "today", {**DET, "zoning_district": "AGR", "lot_sqft": 300000, **kw}
        )

    unknown = [c for c in _conds(wo(), "adu_status") if "Option 3" in c["condition"]]
    assert unknown[0]["condition"].startswith(
        "The code's ADU status is allowed by right only if the lot is in a conservation subdivision developed under "
        "Option 3, country properties (150-110.2A(1)(c)"
    )
    assert unknown[0]["met"] is None
    o1 = wo(in_planned_development=True, planned_development_kind="Option 1")
    assert o1["adu_status"] == "variance"
    assert any(c["met"] is False and "This lot does not qualify" in c["condition"] for c in _conds(o1, "adu_status"))
    o3 = wo(in_planned_development=True, planned_development_kind="Option 3")
    assert o3["adu_status"] == "allowed_by_right"
    a = _answer("pa_montgomery_worcester")
    assert a["status"] == "limited"
    assert a["status_detail"].startswith("only if the lot is in a conservation subdivision developed under Option 3")


def test_status_inside_an_overlay():
    lot = {**DET, "zoning_district": "R-2", "lot_sqft": 12000}
    vo = rules.resolve("pa_lancaster_warwick", "today", {**lot, "overlays": ["VO"]})
    assert vo["adu_status"] == "conditional_use"
    assert vo["reasons"][0].startswith(
        "This lot is in the VO overlay on R-2 land, where the code's ADU status is conditional use (340-23E(9))"
    )
    assert {t: vo["approval_by_type"][t] for t in ("detached_new", "garage_conversion", "over_garage")} == {
        "detached_new": "conditional_use",
        "garage_conversion": "conditional_use",
        "over_garage": "conditional_use",
    }
    assert not any(r.startswith("The code has no ADU rule here") for r in vo["reasons"])
    open_ = rules.resolve("pa_lancaster_warwick", "today", lot)
    assert open_["adu_status"] == "not_addressed"
    assert open_["reasons"][0].endswith("Only if the lot is in the overlay. The lot's overlays were not given")
    plain = rules.resolve("pa_lancaster_warwick", "today", {**lot, "overlays": []})
    assert plain["adu_status"] == "not_addressed"
    assert not any("VO overlay on R-2 land" in r for r in plain["reasons"])
    other = rules.resolve("pa_lancaster_warwick", "today", {**DET, "zoning_district": "A", "lot_sqft": 90000})
    assert other["adu_status"] == "family_only"
    assert not any("VO overlay on R-2 land" in r for r in other["reasons"])
    assert "conditional use in the VO overlay on R-2 land" in _answer("pa_lancaster_warwick")["status_detail"]


def test_overlay_status_opens_a_town_with_no_rule():
    """A town with no ADU rule whose overlay allows one counts as limited, not as not addressed."""
    leaf = {"section": "1", "url": None, "verified_on": "2026-11-26", "confidence": "verified"}
    rule = {
        "adu": {
            "status": {**leaf, "value": "not_addressed"},
            "status_by_overlay": {
                **leaf,
                "value": [{"overlays": ["TND"], "status": "allowed_by_right", "section": "1"}],
            },
        },
        "approval": {"path": {**leaf, "value": "variance"}},
    }
    a = ladder.rule_answer(rule, {"file": "x", "status": "verified"})
    assert a["status"] == "limited" and "allowed by right in the TND overlay" in a["status_detail"]


def test_lint_pass30():
    data = {
        "eligibility": {
            "gates": {"value": [{"condition": "x", "effect": "bars", "status_only_if": "y", "section": "1"}]}
        },
        "adu": {"status_by_overlay": {"value": [{"overlays": ["VO"], "status": "conditional_use", "section": "2"}]}},
    }
    warn = rules.lint(data)
    assert any("status_only_if with no test" in w for w in warn)
    assert any("no approval.alternatives listing with adu_listing, forms" in w for w in warn)
    for name in ("pa_lancaster_warwick", "pa_montgomery_worcester"):
        assert not [w for w in rules.lint(_file(name)) if "status_only_if" in w or "status_by_overlay" in w]


def test_lot_towns_set_none_of_the_pass30_fields():
    """The lot builds resolve as before: no lot town file uses a pass 30 field."""
    for name in LOT_TOWNS:
        d = _file(name)
        adu = d.get("adu") or {}
        assert not ({"status_dispute", "status_by_overlay"} & set(adu)), name
        assert (adu.get("status") or {}).get("value") != "employee_quarters", name
        gates = ((d.get("eligibility") or {}).get("gates") or {}).get("value") or []
        assert not any(g.get("status_only_if") for g in gates), name
