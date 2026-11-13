"""Build the statewide places table (app/public/data/pa_places.json and its meta file).

Deterministic: the same inputs give the same bytes (the build date comes from Inputs.built_on,
else today). Order of rows: GEOID.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.places_index import census, dced, inventories, ladder
from pipeline.places_index.inputs import Inputs

FIELDS = [
    "geoid",
    "name",
    "type",
    "county",
    "pop",
    "housing_units",
    "zoning_authority",
    "zoning_source",
    "status",
    "status_detail",
    "tier",
    "unit_types",
    "approval",
    "source",
    "rule_file",
    "code_url",
    "has_text_search",
    "contact",
]
OFFICE = {
    "city": "City office",
    "borough": "Borough office",
    "township": "Township office",
    "town": "Town office",
    "municipality": "Municipal office",
}
TIERB_NAME = "Public zoning text, quote search only (tier B corpus)"
DCED_NAME = "PA DCED Municipal Statistics, municipal zoning filing"


def _read_json(path: Path | None) -> Any:
    if path is None or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())


def source_registry(inp: Inputs) -> dict[str, dict[str, Any]]:
    """id -> {name, url, date, licence} from raw/places/SOURCES.json and the inventory sources."""
    reg: dict[str, dict[str, Any]] = {}
    for s in _read_json(inp.sources_json) or []:
        reg[s["id"]] = {
            "name": f"{s['publisher']}: {s['title']}",
            "url": s["url"],
            "date": s.get("date"),
            "licence": s.get("licence"),
        }
    for s in _read_json(inp.inventory_sources_json) or []:
        if not s.get("used"):
            continue
        reg[s["source_id"]] = {
            "name": f"{s['publisher']}: {s['title']}",
            "url": s["url"],
            "date": s.get("inventory_date"),
            "licence": s.get("licence_or_terms"),
        }
    reg["rule_file"] = {
        "name": "Hand-read rule file in shared/rules (the ordinance it cites is a zoning ordinance)",
        "url": "shared/rules/towns_index.json",
        "date": None,
        "licence": "Project file",
    }
    return reg


def tierb_places(path: Path | None) -> dict[str, dict[str, Any]]:
    m = _read_json(path)
    if not m:
        return {}
    return {p["geoid"]: p for p in m.get("places", [])}


def tierb_source(p: dict[str, Any]) -> dict[str, Any]:
    urls = p.get("urls") or []
    url = urls[0] if urls else (p.get("coverage_url") or p.get("landing_url"))
    return {"name": TIERB_NAME, "url": url, "date": p.get("fetched_on")}


def tierb_detail(p: dict[str, Any]) -> str | None:
    parts = []
    if p.get("source") == "county":
        parts.append("county ordinance text")
    if p.get("doc_date"):
        parts.append(f"text: {ladder.short(p['doc_date'], 90)}")
    if p.get("complete") is False:
        parts.append("text may be incomplete")
    return "Searchable public zoning text, " + ", ".join(parts) if parts else "Searchable public zoning text"


def _conflict(geoid: str, name: str, kind: str, kept: str, other: str, note: str) -> dict[str, str]:
    return {"geoid": geoid, "name": name, "kind": kind, "kept": kept, "other": other, "note": note}


def assemble(inp: Inputs) -> tuple[list[dict[str, Any]], pd.DataFrame, list[dict[str, str]], dict[str, Any]]:
    """(rows for the app, full table, conflicts, build facts)."""
    places = census.master(inp.census_pl_zip, inp.census_csv, inp.pep_csv)
    reg = source_registry(inp)
    county_lists = pd.read_csv(inp.county_lists_csv) if inp.county_lists_csv and inp.county_lists_csv.exists() else None
    if inp.dced_zoning_csv and inp.dced_zoning_csv.exists():
        zoning = dced.read_zoning(inp.dced_zoning_csv, places, county_lists)
        ztab, unmatched_dced = zoning.table.set_index("geoid"), zoning.unmatched
    else:
        ztab = pd.DataFrame(
            {"zoning_authority": "unknown", "zoning_source": "none", "zoning_note": "No DCED file"},
            index=places.geoid,
        )
        unmatched_dced = []
    if inp.dced_contact_csv and inp.dced_contact_csv.exists():
        contacts = dced.read_contacts(inp.dced_contact_csv, places).set_index("geoid")
    else:
        contacts = pd.DataFrame(columns=["office", "phone", "url"])
    rules = ladder.read_rules(inp.rules_dir)
    codes = ladder.code_urls(inp.rules_dir)
    base_src = ladder.baseline_source(inp.rules_dir)
    tierb = tierb_places(inp.tierb_manifest)
    inv_rows, inv_unmatched = inventories.read_inventories(inp.inventory_csv, places)
    inv = inventories.pick(inv_rows)
    inv_notes = inventories.notes(inv_rows)
    inv_no_zoning = inventories.no_zoning(inv_rows)
    dced_src = reg.get("dced", {"url": dced.REPORT_URL, "date": None})
    dced_status_src = {"name": DCED_NAME, "url": dced_src["url"], "date": dced_src["date"]}

    rows: list[dict[str, Any]] = []
    full: list[dict[str, Any]] = []
    conflicts: list[dict[str, str]] = []
    recs: list[dict[str, Any]] = places.to_dict("records")  # type: ignore[assignment]
    for p in recs:
        gid = str(p["geoid"])
        pname = str(p["name"])
        z = ztab.loc[gid] if gid in ztab.index else None
        auth = str(z.zoning_authority) if z is not None else "unknown"
        zsrc = str(z.zoning_source) if z is not None else "none"
        znote = z.zoning_note if z is not None and isinstance(z.zoning_note, str) else None
        rule = rules.get(gid)
        rep = inv.get(gid)
        nz_src = None
        own_no = z is not None and getattr(z, "dced_zoning_ordinance", None) == "NO"
        if auth == "unknown" and own_no and gid in inv_no_zoning and not rule and not rep:
            # DCED: no own ordinance (county part unclear). A dated county list says no zoning: agree on none
            auth, zsrc = "none", inv_no_zoning[gid]["source_id"]
            znote = "DCED: no own ordinance. The county planning list says no zoning"
            nz_src = inv_no_zoning[gid]["source"]
        tb = tierb.get(gid)
        legal_class = "unknown"
        if rep and not rule and rep["says_no_zoning"] and auth in ("municipal", "county"):
            conflicts.append(
                _conflict(
                    gid,
                    pname,
                    "inventory_no_zoning_vs_dced_zoning",
                    f"DCED: {auth} zoning ({dced_status_src['date']})",
                    f"{rep['status']} ({rep['source_id']}, {rep['source']['date']})",
                    "The inventory says the place had no zoning code then. DCED now records zoning, so the old answer is not used",
                )
            )
            rep = None
        if rep and rep["use_check"]:
            conflicts.append(
                _conflict(
                    gid,
                    pname,
                    "inventory_use_check",
                    f"reported {rep['status']} ({rep['source_id']}, {rep['source']['date']})",
                    "the inventory lists this use in its ADU column",
                    "Check whether this use is an ADU. " + (rep["status_detail"] or ""),
                )
            )
        if rule:
            tier, status = rule["tier"], rule["status"]
            detail, types, approval, source = (
                rule["status_detail"],
                rule["unit_types"],
                rule["approval"],
                rule["source"],
            )
            legal_class = rule["legal_class"]
            if auth in ("none", "unknown"):
                conflicts.append(
                    _conflict(
                        gid,
                        pname,
                        "rule_file_vs_dced_zoning",
                        f"rule file {rule['rule_file']}",
                        f"DCED zoning_authority {auth}",
                        "A hand-read rule file cites this town's zoning ordinance. Kept municipal",
                    )
                )
                auth, zsrc = "municipal", "rule_file"
            if rep and rep["status"] != status:
                conflicts.append(
                    _conflict(
                        gid,
                        pname,
                        "rule_file_vs_inventory",
                        f"{tier} {status} ({rule['rule_file']})",
                        f"{rep['status']} ({rep['source_id']}, {rep['source']['date']})",
                        rep["status_detail"] or "",
                    )
                )
            elif rep and status == "limited" and inventory_class(rep) != rule["legal_class"]:
                conflicts.append(
                    _conflict(
                        gid,
                        pname,
                        "rule_file_vs_inventory_detail",
                        f"{tier} limited, class {rule['legal_class']} ({rule['rule_file']})",
                        f"limited, class {inventory_class(rep)} ({rep['source_id']}, {rep['source']['date']})",
                        rep["status_detail"] or "",
                    )
                )
        elif rep and not (auth == "none" and str(rep["source"]["date"]) < str(dced_status_src["date"])):
            tier, status = "reported", rep["status"]
            detail, types, approval, source = rep["status_detail"], rep["unit_types"], rep["approval"], rep["source"]
            if status == "limited" and not detail:
                detail = "limited (see the inventory)"
            legal_class = inventory_class(rep)
            if auth == "none":
                conflicts.append(
                    _conflict(
                        gid,
                        pname,
                        "inventory_vs_dced_no_zoning",
                        f"reported {status} ({rep['source_id']}, {rep['source']['date']})",
                        f"DCED: no zoning ordinance ({dced_status_src['date']})",
                        "The inventory is newer than the DCED record. Zoning authority set to unknown",
                    )
                )
                auth, znote = "unknown", "DCED records no zoning ordinance but a newer inventory reports an ADU rule"
        elif auth == "none":
            tier, status = "reported", "no_zoning"
            detail, types, approval, source = ladder.NO_ZONING_DETAIL, None, None, dict(nz_src or dced_status_src)
            legal_class = "no_zoning"
            if rep:
                conflicts.append(
                    _conflict(
                        gid,
                        pname,
                        "inventory_vs_dced_no_zoning",
                        f"no_zoning (DCED, {dced_status_src['date']})",
                        f"{rep['status']} ({rep['source_id']}, {rep['source']['date']})",
                        "The DCED record is newer. Kept no zoning. " + (rep["status_detail"] or ""),
                    )
                )
        elif tb:
            tier, status = "text_search", "unknown"
            detail, types, approval, source = tierb_detail(tb), None, None, tierb_source(tb)
        else:
            tier, status = "baseline", "unknown"
            detail, types, approval, source = None, None, None, dict(base_src)
        if status == "unknown" and gid in inv_notes:
            detail = ". ".join(x for x in [detail, inv_notes[gid]] if x)
        if rep:
            for o in rep["others"]:
                if o["status"] != rep["status"]:
                    conflicts.append(
                        _conflict(
                            gid,
                            pname,
                            "inventory_vs_inventory",
                            f"{rep['status']} ({rep['source_id']}, {rep['source']['date']})",
                            f"{o['status']} ({o['source_id']}, {o['date']})",
                            "Newest inventory kept",
                        )
                    )
        if tb and auth == "none":
            conflicts.append(
                _conflict(
                    gid,
                    pname,
                    "text_vs_dced_no_zoning",
                    f"{tier} {status}",
                    "tier B corpus holds zoning text for this place",
                    "Check whether the text is this place's ordinance",
                )
            )
        if gid in contacts.index:
            c = contacts.loc[gid]
            phone = c.phone if isinstance(c.phone, str) else None
            url = c.url if isinstance(c.url, str) else None
            contact = (
                {"office": OFFICE.get(p["type"], "Municipal office"), "phone": phone, "url": url}
                if (phone or url)
                else None
            )
        else:
            contact = None
        row = {
            "geoid": gid,
            "name": pname,
            "type": p["type"],
            "county": p["county"],
            "pop": int(p["pop"]) if pd.notna(p["pop"]) else None,
            "housing_units": int(p["housing_units"]) if pd.notna(p["housing_units"]) else None,
            "zoning_authority": auth,
            "zoning_source": zsrc,
            "status": status,
            "status_detail": detail,
            "tier": tier,
            "unit_types": types,
            "approval": approval,
            "source": {"name": source["name"], "url": source["url"], "date": source["date"]},
            "rule_file": rule["rule_file"] if rule else None,
            "code_url": codes.get(gid),
            "has_text_search": tb is not None,
            "contact": contact,
        }
        errs = ladder.check_row(row)
        if errs:
            raise ValueError(f"{gid} {pname}: {errs}")
        rows.append(row)
        full.append(
            {
                **{k: v for k, v in row.items() if k not in ("source", "contact", "unit_types")},
                "unit_types": ";".join(types) if types else ("" if types == [] else None),
                "source_name": source["name"],
                "source_url": source["url"],
                "source_date": source["date"],
                "contact_phone": contact["phone"] if contact else None,
                "contact_url": contact["url"] if contact else None,
                "pop_year": int(p["pop_year"]),
                "main_geoid": p["main_geoid"],
                "zoning_note": znote,
                "legal_class": legal_class,
                "inventory_source": rep["source_id"] if rep else None,
                "inventory_status": rep["status"] if rep else None,
                "tierb_text_id": tb.get("text_id") if tb else None,
            }
        )
    facts = {
        "dced_unmatched": unmatched_dced,
        "inventory_rows": int(len(inv_rows)),
        "inventory_unmatched": inv_unmatched[["source_id", "county", "municipality"]].to_dict("records")
        if len(inv_unmatched)
        else [],
        "registry": reg,
        "pop_2020_fallback": places.loc[places.pop_year == 2020, "geoid"].tolist(),
    }
    return rows, pd.DataFrame(full), conflicts, facts


def inventory_class(rep: dict[str, Any]) -> str:
    """Forecast legal class for a reported inventory status (pipeline/tract/legal.py words)."""
    st, detail, path = rep["status"], (rep["status_detail"] or "").lower(), rep["approval"]
    if st in ("not_addressed", "prohibited"):
        return "none"
    if st == "by_right":
        return "by_right"
    if "family" in detail or "relative" in detail or "elder" in detail:
        return "family_only"
    if "conversion" in detail or "existing" in detail:
        return "conversion_only"
    if path == "by_right" and ("owner" in detail or "occup" in detail):
        return "by_right"
    return "discretionary"


def counts(table: pd.DataFrame) -> dict[str, Any]:
    pop = table["pop"].fillna(0)
    total = float(pop.sum())
    hu = table.housing_units.fillna(0)

    def by(col: str) -> list[dict[str, Any]]:
        g = table.assign(_p=pop, _h=hu).groupby(col)
        out = []
        for k, x in g:
            out.append(
                {
                    col: k,
                    "places": int(len(x)),
                    "pop": int(x._p.sum()),
                    "pop_share": round(float(x._p.sum()) / total, 4),
                    "housing_units": int(x._h.sum()),
                }
            )
        return sorted(out, key=lambda r: -r["pop"])

    return {
        "places": int(len(table)),
        "pop_total": int(total),
        "by_tier": by("tier"),
        "by_status": by("status"),
        "by_zoning_authority": by("zoning_authority"),
        "tier_x_status": [
            {"tier": t, "status": s, "places": int(len(x)), "pop": int(x["pop"].fillna(0).sum())}
            for (t, s), x in table.groupby(["tier", "status"])
        ],
    }


def meta(
    rows: list[dict[str, Any]],
    table: pd.DataFrame,
    conflicts: list[dict[str, str]],
    facts: dict[str, Any],
    built_on: str,
) -> dict[str, Any]:
    reg = facts["registry"]
    used = sorted({r["zoning_source"] for r in rows} | set(table.inventory_source.dropna()) | {"dced_contacts"})
    return {
        "about": "Where can you build an ADU today, for every Pennsylvania county subdivision. One tier and one status per place. Not legal advice. Not a zoning determination. See docs/PLACES.md.",
        "built_on": built_on,
        "file": "pa_places.json",
        "fields": FIELDS,
        "enums": {
            "type": list(census.TYPE_WORDS),
            "zoning_authority": list(ladder.AUTHORITIES),
            "status": list(ladder.STATUSES),
            "tier": list(ladder.TIERS),
            "unit_types": list(ladder.UNIT_TYPES),
            "approval": list(ladder.APPROVALS),
        },
        "population": {
            "pop": "Census Vintage 2025 subcounty estimate, July 1, 2025 (sub-est2025_42.csv)",
            "pop_2020_fallback": facts["pop_2020_fallback"],
            "housing_units": "2020 Census PL 94-171 HU100",
        },
        "contact": "Office phone and website as the municipality filed them with DCED (County / Municipal Contact Person report). Ask the office for the zoning officer. No names or emails are copied.",
        "code_url": "Link to the place's zoning code from shared/rules/towns_index.json (code_url, every entry whatever its status), else the rule file's provenance. null where neither has one.",
        "no_zoning": ladder.NO_ZONING_DETAIL + ". House Bill 2186 would not change such a place.",
        "sources": {k: reg[k] for k in used if k in reg},
        "counts": counts(table),
        "conflicts": conflicts,
        "dced_unmatched": facts["dced_unmatched"],
        "inventory_unmatched": facts["inventory_unmatched"],
    }


def write(
    rows: list[dict[str, Any]],
    meta_obj: dict[str, Any],
    table: pd.DataFrame,
    conflicts: list[dict[str, str]],
    out: dict[str, Path],
) -> dict[str, int]:
    for p in out.values():
        p.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    out["app_json"].write_text(body + "\n")
    out["app_meta"].write_text(json.dumps(meta_obj, ensure_ascii=False, indent=1) + "\n")
    table.to_csv(out["table_csv"], index=False)
    pd.DataFrame(conflicts, columns=["geoid", "name", "kind", "kept", "other", "note"]).to_csv(
        out["conflicts_csv"], index=False
    )
    return {k: p.stat().st_size for k, p in out.items()}


def build(inp: Inputs, out: dict[str, Path]) -> dict[str, Any]:
    rows, table, conflicts, facts = assemble(inp)
    built_on = inp.built_on or dt.date.today().isoformat()
    m = meta(rows, table, conflicts, facts, built_on)
    sizes = write(rows, m, table, conflicts, out)
    return {"rows": len(rows), "sizes": sizes, "counts": m["counts"], "conflicts": len(conflicts)}
