"""Generate the per-file tables of docs/RULES.md from shared/rules/*.json."""
import json, re, sys
from pathlib import Path
R = Path.home()/"Developer/yz-musa-build/shared/rules"
def load(n): return json.loads((R/f"{n}.json").read_text())
def clean(t):
    if t is None: return ""
    t = str(t).replace("; ", ". ").replace(";", ",").replace("—", ", ").replace("–", " to ").replace("|", "/")
    return t.strip()
NAMES = {"internal":"inside the house","garage_conversion":"garage conversion","over_garage":"over a garage",
         "detached_new":"new detached","attached":"attached addition","detached":"detached","semi_detached":"semi-detached",
         "by_right":"by right","administrator_exception":"Administrator's Exception","special_exception":"special exception","variance":"variance","not_allowed":"not allowed"}
def val(v, leaf=None):
    if v is None:
        if leaf and leaf.get("confidence") == "unverified": return "not confirmed"
        return "none set"
    if isinstance(v, bool): return "yes" if v else "no"
    if isinstance(v, list):
        if not v: return "none"
        if all(isinstance(x, str) for x in v): return ", ".join(NAMES.get(x, x) for x in v)
        return f"{len(v)} entries (see below)"
    if isinstance(v, float) and v < 1: return f"{v:g} of the lot" if leaf and "coverage" in str(leaf.get("_key","")) else f"{v:g}"
    if isinstance(v, (int, float)): return f"{v:,}"
    return NAMES.get(v, clean(v))
LABEL = {
 "approval.path":"Approval path when the lot qualifies","approval.fallback_path":"Path when the lot does not qualify",
 "approval.detached_in_yard_path":"Path for a new detached unit in a side or rear yard",
 "eligibility.zoning_districts":"Zoning districts","eligibility.building_types":"House types",
 "eligibility.overlay_bars":"Overlays that bar ADUs","eligibility.min_lot_sqft":"Minimum lot size (sq ft)",
 "eligibility.existing_structure_only":"Only inside an existing building","eligibility.historic_bypass":"Historic path skips the district, type and lot size tests",
 "form.types_allowed":"ADU forms allowed","size.max_sqft":"Maximum size (sq ft)","size.max_share_of_house":"Maximum share of the house",
 "size.min_sqft":"Minimum size (sq ft)","size.historic_exempt":"Historic building may exceed the size cap",
 "envelope.max_height_ft":"Maximum height of an ADU building (ft)","envelope.accessory_structure_max_sqft":"Maximum size of any accessory structure (sq ft)",
 "envelope.internal_uses_district_height":"Unit inside the house uses the district height",
 "envelope.setback_front_ft":"Front setback (ft)","envelope.setback_side_ft":"Side setback (ft)","envelope.setback_rear_ft":"Rear setback (ft)",
 "envelope.setback_rear_alley_ft":"Rear setback on an alley or way (ft)","envelope.separation_ft":"Separation from the house (ft)",
 "envelope.rated_wall_below_ft":"Fire-rated wall needed closer than (ft)","envelope.no_openings_below_ft":"No windows or doors closer than (ft)",
 "envelope.sprinklered_unrated_min_ft":"With sprinklers, unrated wall allowed at (ft)",
 "coverage.max_building_coverage":"Maximum building coverage","coverage.max_impervious":"Maximum impervious share",
 "coverage.min_allowance_sqft":"Building cover allowance for the ADU at least (sq ft)",
 "use.owner_occupancy":"Owner must live on site","use.family_only":"Family members only","use.max_adus":"ADUs per lot",
 "use.short_term_rental_banned":"Short-term rental banned","use.short_term_rental_ban_allowed":"Town may ban rentals under 30 days",
 "use.sale_apart_allowed":"ADU may be sold apart from the house","use.sale_apart_ban_allowed":"Town may bar a separate sale",
 "parking.spaces_required":"Parking spaces required","utilities.new_connection_required":"New utility connection required",
 "utilities.connection_fee_allowed":"Connection fee allowed",
}
MODE = {"set":"replaces","at_least":"town may not go under","at_most":"town may not go over"}
def leaves(d):
    for sec, body in d.items():
        if sec in ("provenance","districts") or not isinstance(body, dict): continue
        for k, v in body.items():
            if isinstance(v, dict): yield f"{sec}.{k}", v
def table(n, bill=False):
    d = load(n); out = []
    if bill: out.append("| Rule | Value | Effect | Section | Checked on | Confidence |\n|---|---|---|---|---|---|")
    else: out.append("| Rule | Value | Section | Checked on | Confidence |\n|---|---|---|---|---|")
    for key, leaf in leaves(d):
        leaf = {**leaf, "_key": key}
        v = val(leaf.get("value"), leaf)
        if key == "eligibility.overlay_bars" and leaf.get("value"): v = f"{len(leaf['value'])} overlays (see below)"
        if key.endswith("share_of_house") and isinstance(leaf.get("value"), float): v = f"{leaf['value']:.0%}"
        if key == "coverage.max_building_coverage" and isinstance(leaf.get("value"), float): v = f"{leaf['value']:.0%}"
        label = LABEL.get(key, key)
        extra = " (labeled planning assumption)" if leaf.get("assumption") else ""
        row = [label + extra, v]
        if bill: row.append(MODE.get(leaf.get("mode","set"), leaf.get("mode")))
        row += [clean(leaf.get("section")), leaf.get("verified_on") or "not checked", leaf.get("confidence")]
        out.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(out)
def notes(n):
    d = load(n); out = []
    for key, leaf in leaves(d):
        if leaf.get("note") and key != "eligibility.overlay_bars":
            out.append(f"- {LABEL.get(key,key)}: {clean(leaf['note'])}")
    return "\n".join(out)
def prov(n):
    p = load(n)["provenance"]; out = [f"- Instrument: {clean(p.get('instrument'))}",
        f"- Status: {clean(p.get('status')).replace('_',' ')}. {clean(p.get('status_detail'))}",
        f"- Effective date: {p.get('effective_date') or 'none recorded'}", f"- File checked on: {p.get('verified_on')}"]
    if p.get("reaches"): out.append(f"- Reaches: {', '.join(p['reaches'])}")
    if p.get("does_not_reach"): out.append(f"- Does not reach: {', '.join(p['does_not_reach'])}")
    if p.get("checks"):
        out.append("- Checks the tool cannot test from data, shown to the user:")
        out += [f"  - {clean(c)}" for c in p["checks"]]
    if p.get("notes"): out.append(f"- Notes: {clean(p['notes'])}")
    return "\n".join(out)
COLS = {"philadelphia": ["min_lot_sqft","setback_front_ft","setback_side_ft","setback_side_semi_ft","setback_rear_ft","max_building_coverage","principal_max_height_ft","parking_spaces"],
        "pittsburgh": ["min_lot_sqft","setback_front_ft","setback_side_ft","max_building_coverage","principal_max_height_ft"]}
HEAD = {"min_lot_sqft":"Min lot (sq ft)","setback_front_ft":"Front (ft)","setback_side_ft":"Side (ft)","setback_side_semi_ft":"Side, semi-detached (ft)",
        "setback_rear_ft":"Rear (ft)","max_building_coverage":"Coverage","principal_max_height_ft":"House height (ft)","parking_spaces":"Parking"}
def cell(leaf):
    if leaf is None: return ""
    v = leaf.get("value")
    if v is None: return "not confirmed" if leaf.get("confidence") == "unverified" else "none set"
    s = f"{v:.0%}" if isinstance(v, float) and v < 1 else f"{v:,}"
    return s + (" (s)" if leaf.get("confidence") == "secondary" else "")
def districts(n):
    d = load(n)["districts"]; cols = [c for c in COLS[n] if any(c in b for b in d.values())]
    out = ["| District | " + " | ".join(HEAD[c] for c in cols) + " | Checked on |", "|---" * (len(cols)+2) + "|"]
    for code, body in d.items():
        dates = sorted({v.get("verified_on") for v in body.values() if isinstance(v, dict) and v.get("verified_on")})
        out.append(f"| {code} | " + " | ".join(cell(body.get(c)) for c in cols) + f" | {', '.join(dates) or 'not checked'} |")
    return "\n".join(out)
def district_sections(n):
    d = load(n)["districts"]; secs = sorted({clean(v.get("section")) for b in d.values() for v in b.values() if isinstance(v, dict)})
    return "\n".join(f"- {s}" for s in secs)
def overlays():
    leaf = load("philadelphia")["eligibility"]["overlay_bars"]
    out = ["| Overlay | Covers | Bars ADUs in | Historic building exempt | Section | Overlay area defined in |", "|---|---|---|---|---|---|"]
    for b in leaf["value"]:
        cov = ("Wards " + ", ".join(map(str, b["wards"]))) if b.get("wards") else ("Council District " + ", ".join(map(str, b.get("council_districts", []))))
        out.append(f"| {b['overlay']} | {cov} | {'all districts' if b['districts'] is None else ' and '.join(b['districts'])} | {'yes' if b['historic_ok'] else 'no'} | {b['section']} | {b.get('applies_section','')} |")
    out.append(f"\nChecked on {leaf['verified_on']}, confidence {leaf['confidence']}. {clean(leaf['note'])}")
    return "\n".join(out)
def unverified():
    out = ["| File | Rule | Value | Section | Note |", "|---|---|---|---|---|"]
    for n in ["philadelphia","pittsburgh","bill250042","hb2186","sb1346","default"]:
        d = load(n)
        for key, leaf in leaves(d):
            if leaf.get("confidence") == "unverified":
                out.append(f"| {n} | {LABEL.get(key,key)} | {val(leaf.get('value'), leaf)}{' (labeled planning assumption)' if leaf.get('assumption') else ''} | {clean(leaf.get('section'))} | {clean(leaf.get('note'))} |")
        for code, body in (d.get("districts") or {}).items():
            for k, leaf in body.items():
                if isinstance(leaf, dict) and leaf.get("confidence") == "unverified":
                    out.append(f"| {n} | district {code}, {HEAD.get(k,k)} | not confirmed | {clean(leaf.get('section'))} | {clean(leaf.get('note'))} |")
    return "\n".join(out)
def secondary():
    out = ["| File | Rule | Value | Section | Note |", "|---|---|---|---|---|"]
    for n in ["philadelphia","pittsburgh","bill250042","hb2186","sb1346","default"]:
        for key, leaf in leaves(load(n)):
            if leaf.get("confidence") == "secondary":
                v = val(leaf.get("value"), {**leaf, "_key": key})
                out.append(f"| {n} | {LABEL.get(key,key)} | {v} | {clean(leaf.get('section'))} | {clean(leaf.get('note'))} |")
    return "\n".join(out)
part = sys.argv[1]; arg = sys.argv[2] if len(sys.argv) > 2 else None
print({"table": lambda: table(arg), "bill": lambda: table(arg, True), "notes": lambda: notes(arg), "prov": lambda: prov(arg),
       "districts": lambda: districts(arg), "dsec": lambda: district_sections(arg), "overlays": overlays,
       "unverified": unverified, "secondary": secondary}[part]())
