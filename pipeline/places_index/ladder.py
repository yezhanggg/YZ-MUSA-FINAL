"""The answer ladder: one tier and one status per place.

Pure functions. Rule files are read with `rule_answer`; the ladder itself is `assemble`.

    tier         status allowed                          source of the status
    verified     by_right limited not_addressed prohibited   hand-read rule file (index status verified)
    drafted      same                                        hand-read rule file (index status drafted)
    reported     same, or no_zoning                          dated inventory, or DCED no-zoning record
    text_search  unknown                                     public zoning text (tier B corpus)
    baseline     unknown                                     shared/rules/pa_statewide.json

A rule file always wins. Where an inventory or DCED disagrees with a rule file, the place keeps the
rule file answer and the disagreement goes to the conflicts list.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

TIERS = ("verified", "drafted", "reported", "text_search", "baseline")
STATUSES = ("by_right", "limited", "not_addressed", "prohibited", "no_zoning", "unknown")
AUTHORITIES = ("municipal", "county", "none", "unknown")
UNIT_TYPES = ("detached", "attached", "internal", "garage")
APPROVALS = ("by_right", "administrator_exception", "special_exception", "conditional_use", "variance", "not_allowed")

FORM_TO_UNIT = {
    "detached_new": "detached",
    "attached": "attached",
    "internal": "internal",
    "garage_conversion": "garage",
    "over_garage": "garage",
}
RULE_STATUS = {
    "allowed_by_right": "by_right",
    "special_exception": "limited",
    "conditional_use": "limited",
    "family_only": "limited",
    "conversion_only": "limited",
    "not_addressed": "not_addressed",
    "prohibited": "prohibited",
}
# Legal class used by the MUSA 5500 forecast (pipeline/tract/legal.py vocabulary)
RULE_CLASS = {
    "allowed_by_right": "by_right",
    "special_exception": "discretionary",
    "conditional_use": "discretionary",
    "family_only": "family_only",
    "conversion_only": "conversion_only",
    "not_addressed": "none",
    "prohibited": "none",
}
PATH_WORDS = {
    "by_right": "zoning permit",
    "administrator_exception": "administrator exception",
    "special_exception": "special exception",
    "conditional_use": "conditional use",
    "variance": "variance",
}
BASELINE_SOURCE = {
    "name": "Statewide baseline, not this town's code",
    "url": "shared/rules/pa_statewide.json",
}
# Town files list the districts where an ADU may go, which is normal. Only where the district list is
# itself the main limit is it named in the detail (Philadelphia: 14-604(11), RSA-5 and CMX-1).
DETAIL_EXTRA = {"philadelphia": "RSA-5 and CMX-1 districts only"}
NO_ZONING_DETAIL = "No zoning, so zoning does not limit an ADU. Building and sewage permits still apply"


def _v(x: Any) -> Any:
    return x.get("value") if isinstance(x, dict) else x


def unit_types(forms: list[str] | None) -> list[str] | None:
    if forms is None:
        return None
    out = {FORM_TO_UNIT[f] for f in forms if f in FORM_TO_UNIT}
    return [u for u in UNIT_TYPES if u in out]


def short(text: str | None, limit: int = 160) -> str | None:
    """First `limit` characters of a note, cut at a word."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= limit:
        return t
    return t[: t.rfind(" ", 0, limit)].rstrip(" ,.") + " ..."


def adu_status(rule: dict[str, Any]) -> str | None:
    """adu.status of a town file. The two city files have none: read it from the approval and form."""
    st = _v((rule.get("adu") or {}).get("status"))
    if st:
        return str(st)
    ap = rule.get("approval") or {}
    el = rule.get("eligibility") or {}
    path = _v(ap.get("path"))
    if path in (None, "not_allowed"):
        return "prohibited" if path == "not_allowed" else None
    if _v(el.get("existing_structure_only")):
        return "conversion_only"
    if _v((rule.get("use") or {}).get("family_only")):
        return "family_only"
    return "allowed_by_right" if path == "by_right" else str(path)


def status_detail(rule: dict[str, Any], raw: str | None, rule_name: str = "") -> str | None:
    """Short plain words for a limited status (and the few by-right notes that matter)."""
    ap = rule.get("approval") or {}
    el = rule.get("eligibility") or {}
    use = rule.get("use") or {}
    adu = rule.get("adu") or {}
    path = _v(ap.get("path"))
    owner = bool(_v(use.get("owner_occupancy")))
    parts: list[str] = []
    if raw == "family_only":
        parts.append("family only")
    elif raw == "conversion_only":
        parts.append("conversion of an existing building only")
    with_path = raw in ("family_only", "conversion_only", "special_exception", "conditional_use", "allowed_by_right")
    if with_path and path in PATH_WORDS and not (raw == "allowed_by_right" and not owner):
        parts.append(PATH_WORDS[path])
    if owner and raw not in ("not_addressed", "prohibited"):
        parts.append("owner must live on the lot")
    if rule_name in DETAIL_EXTRA:
        parts.append(DETAIL_EXTRA[rule_name])
    if _v(el.get("overlay_bars")):
        parts.append("barred in some overlays")
    detached_path = _v(ap.get("detached_in_yard_path"))
    if detached_path and detached_path != path:
        parts.append(f"new detached unit in the yard: {PATH_WORDS.get(detached_path, detached_path)}")
    scope = _v(adu.get("scope_districts"))
    if scope:
        outside = _v(adu.get("status_outside")) or "not_addressed"
        parts.append(f"only in {', '.join(scope)}, {outside.replace('_', ' ')} elsewhere")
    if raw == "not_addressed":
        parts.append(
            "no ADU text in the code"
            + (f", {PATH_WORDS[path]} at best" if path in ("variance", "special_exception", "conditional_use") else "")
        )
    if raw == "prohibited":
        parts.append("the code bars ADUs")
    return ", ".join(parts) if parts else None


def rule_answer(rule: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Status, detail, unit types, approval, source and legal class from one rule file."""
    raw = adu_status(rule)
    status = RULE_STATUS.get(raw or "", "unknown")
    scope = _v((rule.get("adu") or {}).get("scope_districts"))
    if status == "by_right" and (scope or _v((rule.get("use") or {}).get("owner_occupancy"))):
        status = "limited"  # by right but only in some districts, or owner occupancy required
    detail = status_detail(rule, raw, entry.get("file", ""))
    if entry.get("status") == "drafted" and entry.get("status_note"):
        note = entry["status_note"]
        open_part = note[note.find("Open:") :] if "Open:" in note else note
        detail = ". ".join(x for x in [detail, short(open_part, 140)] if x)
    prov = rule.get("provenance") or {}
    approval = _v((rule.get("approval") or {}).get("path"))
    forms = _v((rule.get("form") or {}).get("types_allowed"))
    if status in ("not_addressed", "prohibited"):
        types: list[str] | None = []
    else:
        types = unit_types(forms)
    return {
        "status": status,
        "status_detail": detail,
        "unit_types": types,
        "approval": approval if approval in APPROVALS else None,
        "source": {
            "name": prov.get("instrument") or entry.get("name"),
            "url": entry.get("code_url") or prov.get("code_url") or (prov.get("source_urls") or [None])[0],
            "date": prov.get("verified_on") or entry.get("checked_on"),
        },
        "legal_class": RULE_CLASS.get(raw or "", "unknown"),
        "adu_status_raw": raw,
    }


def read_rules(rules_dir: Path) -> dict[str, dict[str, Any]]:
    """geoid (and every alias) -> rule answer plus tier, for index entries with a file and status
    verified or drafted. Entries still `todo` or `in_progress` are not used."""
    idx = json.loads((rules_dir / "towns_index.json").read_text())
    out: dict[str, dict[str, Any]] = {}
    for e in idx["towns"]:
        if e.get("status") not in ("verified", "drafted"):
            continue
        path = rules_dir / f"{e['file']}.json"
        if not path.exists():
            continue
        ans = rule_answer(json.loads(path.read_text()), e)
        ans["tier"] = e["status"]
        ans["rule_file"] = e["file"]
        for g in [e["geoid"], *e.get("geoid_aliases", [])]:
            out[g] = ans
    return out


def code_urls(rules_dir: Path) -> dict[str, str]:
    """geoid (and every alias) -> link to the place's zoning code, for every index entry whatever its status
    (towns not yet read included): the index's code_url, else the rule file's provenance code_url or first source url."""
    idx = json.loads((rules_dir / "towns_index.json").read_text())
    out: dict[str, str] = {}
    for e in idx["towns"]:
        url = e.get("code_url")
        path = rules_dir / f"{e.get('file')}.json"
        if not url and e.get("file") and path.exists():
            prov = json.loads(path.read_text()).get("provenance") or {}
            url = prov.get("code_url") or (prov.get("source_urls") or [None])[0]
        if not url:
            continue
        for g in [e["geoid"], *e.get("geoid_aliases", [])]:
            out[g] = url
    return out


def baseline_source(rules_dir: Path) -> dict[str, Any]:
    p = rules_dir / "pa_statewide.json"
    date = None
    if p.exists():
        date = json.loads(p.read_text()).get("provenance", {}).get("verified_on")
    return {**BASELINE_SOURCE, "date": date}


def check_row(r: dict[str, Any]) -> list[str]:
    """Contract checks for one output row. Empty list = fine."""
    errs = []
    if r["tier"] not in TIERS:
        errs.append(f"tier {r['tier']}")
    if r["status"] not in STATUSES:
        errs.append(f"status {r['status']}")
    if r["zoning_authority"] not in AUTHORITIES:
        errs.append(f"zoning_authority {r['zoning_authority']}")
    if r["status"] == "unknown" and r["tier"] not in ("text_search", "baseline"):
        errs.append("unknown status above text_search")
    if r["tier"] in ("text_search", "baseline") and r["status"] != "unknown":
        errs.append("status claimed at text_search or baseline")
    if r["status"] == "limited" and not r["status_detail"]:
        errs.append("limited without detail")
    if r["status"] == "no_zoning" and r["zoning_authority"] != "none":
        errs.append("no_zoning with zoning")
    if r["tier"] in ("verified", "drafted") and not r["rule_file"]:
        errs.append("rule tier without rule file")
    if r["unit_types"] is not None and any(u not in UNIT_TYPES for u in r["unit_types"]):
        errs.append("unit type")
    if r["approval"] is not None and r["approval"] not in APPROVALS:
        errs.append(f"approval {r['approval']}")
    s = r["source"]
    if not isinstance(s, dict) or not s.get("name") or not s.get("date"):
        errs.append("source without name or date")
    return errs
