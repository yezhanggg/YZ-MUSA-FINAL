"""ADU zoning rules: load the cited rule files and resolve them for one lot.

Rule files live in shared/rules/. Each value is a leaf with its section, url,
verified_on date and confidence. resolve() stacks files for a scenario:

    today          place file
    local_reform   place file + the local bill (Philadelphia: bill250042)
    state_reform   place file + hb2186 (state law limits what the town may impose)

Gaps the place leaves unconfirmed are filled from default.json (building code
defaults and labeled planning assumptions) and listed in "assumed". Under
state_reform the values are what a lot can count on, and "state_limits" says
which ones come from a state floor or cap.

Not legal advice and not a zoning determination.

CLI:
    python -m pipeline.rules validate
    python -m pipeline.rules resolve --place philadelphia --scenario today --district RSA-5 \
        --building-type detached --overlays "" --lot-sqft 2000
"""
from __future__ import annotations

import argparse
import functools
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

RULES_DIR = Path(__file__).resolve().parents[1] / "shared" / "rules"
SCHEMA_PATH = RULES_DIR / "schema.json"
DEFAULT = "default"
SCENARIOS = ("today", "local_reform", "state_reform")
LOCAL_REFORM: dict[str, list[str]] = {"philadelphia": ["bill250042"], "pittsburgh": []}
STATE_REFORM = "hb2186"
ALL_TYPES = ["detached_new", "garage_conversion", "over_garage", "internal", "attached"]
NEW_STRUCTURE_TYPES = {"detached_new", "attached", "over_garage"}
PRINCIPAL_TYPES = {"internal", "attached"}
# From least to most demanding. An ADU type is "allowed" up to special_exception.
# conditional_use (governing body hearing, MPC 913.2) is used by town files only.
PATH_ORDER = ["by_right", "administrator_exception", "special_exception", "conditional_use", "variance", "not_allowed"]
OK_PATHS = {"by_right", "administrator_exception", "special_exception", "conditional_use"}
# Town files (pa_<county>_<town>.json) are listed in this index. The statewide file is the
# baseline for a town without a file. Neither the index nor the schema is a rule file.
TOWNS_INDEX = RULES_DIR / "towns_index.json"
STATEWIDE = "pa_statewide"
NOT_RULE_FILES = {"schema", "towns_index"}

# Output key -> (section, field) in a rule file. The order is the output order.
VALUE_KEYS: dict[str, tuple[str, str]] = {
    "max_adus": ("use", "max_adus"),
    "max_size_sqft": ("size", "max_sqft"),
    "min_size_sqft": ("size", "min_sqft"),
    "max_share_of_house": ("size", "max_share_of_house"),
    "min_lot_sqft": ("eligibility", "min_lot_sqft"),
    "max_height_ft": ("envelope", "max_height_ft"),
    "setback_front_ft": ("envelope", "setback_front_ft"),
    "setback_side_ft": ("envelope", "setback_side_ft"),
    "setback_rear_ft": ("envelope", "setback_rear_ft"),
    "setback_rear_alley_ft": ("envelope", "setback_rear_alley_ft"),
    "separation_ft": ("envelope", "separation_ft"),
    "max_building_coverage": ("coverage", "max_building_coverage"),
    "max_impervious": ("coverage", "max_impervious"),
    "owner_occupancy": ("use", "owner_occupancy"),
    "parking_spaces": ("parking", "spaces_required"),
}
FIRE_KEYS: dict[str, tuple[str, str]] = {
    "rated_wall_below_ft": ("envelope", "rated_wall_below_ft"),
    "no_openings_below_ft": ("envelope", "no_openings_below_ft"),
    "sprinklered_unrated_min_ft": ("envelope", "sprinklered_unrated_min_ft"),
}
OUTPUT_KEYS = ["allowed", "approval_path", "reasons", "types_allowed", *VALUE_KEYS,
               "citations", "assumed",
               # Added Nov 11, 2026. The keys above are unchanged.
               "approval_by_type", "max_height_by_type", "setback_rear_effective_ft", "rear_setback_rule",
               "state_limits", "fire_separation", "historic_path"]

# A per-district entry overrides these place-level paths.
DISTRICT_FIELDS: dict[str, tuple[str, str]] = {
    "setback_front_ft": ("envelope", "setback_front_ft"),
    "setback_side_ft": ("envelope", "setback_side_ft"),
    "setback_rear_ft": ("envelope", "setback_rear_ft"),
    "max_building_coverage": ("coverage", "max_building_coverage"),
    "parking_spaces": ("parking", "spaces_required"),
}
DISTRICT_HEIGHT = ("district", "principal_max_height_ft")
INTEGER_KEYS = {"max_adus", "parking_spaces"}
BUILDING_TYPE_ALIASES = {
    "detached": "detached", "single": "detached", "single_family_detached": "detached",
    "semi_detached": "semi_detached", "semi-detached": "semi_detached", "semi": "semi_detached",
    "twin": "semi_detached", "attached": "attached", "row": "attached", "rowhouse": "attached",
    "row_house": "attached", "townhouse": "attached",
}

Path_ = tuple[str, str]
Picked = dict[Path_, tuple[dict[str, Any], str]]  # path -> (leaf, source file name)


# ------------------------------------------------------------------ loading and validation

@functools.lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text())


def rule_names() -> list[str]:
    """Every rule file name (without .json), schema excluded."""
    return sorted(p.stem for p in RULES_DIR.glob("*.json") if p.stem not in NOT_RULE_FILES)


def validate(data: dict[str, Any]) -> list[str]:
    """All problems with one rule file as readable strings. Empty means valid."""
    return _schema_errors(data) + _source_errors(data)


def load_rules(name: str) -> dict[str, Any]:
    """Read and validate shared/rules/<name>.json."""
    path = RULES_DIR / f"{name}.json"
    if not path.exists():
        raise ValueError(f"no rule file '{name}'. Known: {', '.join(rule_names())}")
    return _load_cached(str(path))


@functools.lru_cache(maxsize=None)
def _load_cached(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    errs = validate(data)
    if errs:
        raise ValueError(f"{Path(path).name} is not valid:\n  " + "\n  ".join(errs[:20]))
    return data


def _schema_errors(data: dict[str, Any]) -> list[str]:
    # jsonschema is optional so the tests run with only pytest installed.
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return mini_validate(data, schema())
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
            for e in Draft202012Validator(schema()).iter_errors(data)]


def _source_errors(data: dict[str, Any]) -> list[str]:
    """A value needs a source. A non-null unverified value must be a labeled assumption."""
    errors = []
    for where, leaf in iter_leaves(data):
        if leaf.get("value") is None:
            continue
        if not leaf.get("url") or not leaf.get("verified_on"):
            errors.append(f"{where}: a value needs url and verified_on")
        if leaf.get("confidence") == "unverified" and not leaf.get("assumption"):
            errors.append(f"{where}: unverified value must be null unless it is a labeled assumption")
    return errors


def iter_leaves(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(dotted path, leaf) for every leaf in a rule file, district tables included."""
    out = []
    for sec, body in data.items():
        if sec in ("provenance", "districts") or not isinstance(body, dict):
            continue
        out += [(f"{sec}.{k}", v) for k, v in body.items() if isinstance(v, dict)]
    for code, body in (data.get("districts") or {}).items():
        out += [(f"districts.{code}.{k}", v) for k, v in body.items() if isinstance(v, dict)]
    return out


# A small JSON Schema subset, enough for schema.json, used when jsonschema is missing.
_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def mini_validate(value: Any, sch: dict[str, Any], root: Optional[dict[str, Any]] = None,
                  where: str = "(root)") -> list[str]:
    """Validate against the subset of JSON Schema that schema.json uses."""
    root = root or sch
    if "$ref" in sch:
        return mini_validate(value, _deref(root, sch["$ref"]), root, where)
    errs = _mini_scalar(value, sch, where)
    if errs:
        return errs
    if isinstance(value, dict):
        errs += _mini_object(value, sch, root, where)
    if isinstance(value, list) and "items" in sch:
        for i, item in enumerate(value):
            errs += mini_validate(item, sch["items"], root, f"{where}/{i}")
    return errs


def _deref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def _mini_scalar(value: Any, sch: dict[str, Any], where: str) -> list[str]:
    types = sch.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else types
        if not any(_TYPES[t](value) for t in types):
            return [f"{where}: {value!r} is not of type {types}"]
    if "enum" in sch and value not in sch["enum"]:
        return [f"{where}: {value!r} is not one of {sch['enum']}"]
    if _TYPES["number"](value):
        if "minimum" in sch and value < sch["minimum"]:
            return [f"{where}: {value} is under {sch['minimum']}"]
        if "maximum" in sch and value > sch["maximum"]:
            return [f"{where}: {value} is over {sch['maximum']}"]
    if isinstance(value, str):
        if "pattern" in sch and not re.search(sch["pattern"], value):
            return [f"{where}: {value!r} does not match {sch['pattern']}"]
        if len(value) < sch.get("minLength", 0):
            return [f"{where}: string is too short"]
    if isinstance(value, list) and len(value) < sch.get("minItems", 0):
        return [f"{where}: too few items"]
    return []


def _mini_object(value: dict[str, Any], sch: dict[str, Any], root: dict[str, Any],
                 where: str) -> list[str]:
    errs = [f"{where}: '{k}' is a required property" for k in sch.get("required", []) if k not in value]
    props = sch.get("properties", {})
    extra = sch.get("additionalProperties", True)
    for k, v in value.items():
        if k in props:
            errs += mini_validate(v, props[k], root, f"{where}/{k}")
        elif extra is False:
            errs.append(f"{where}: additional property '{k}' is not allowed")
        elif isinstance(extra, dict):
            errs += mini_validate(v, extra, root, f"{where}/{k}")
    return errs


# ------------------------------------------------------------------ lot facts

def _norm(code: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code).upper())


def _match_code(code: Optional[str], options: list[Any]) -> Optional[Any]:
    if code is None:
        return None
    return next((o for o in options if _norm(o) == _norm(code)), None)


def _building_type(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return BUILDING_TYPE_ALIASES.get(str(raw).strip().lower().replace(" ", "_"), str(raw).lower())


def _historic(lot: dict[str, Any], reasons: list[str]) -> bool:
    """True only when the building is known to qualify as historic.

    14-604(11)(d)(.1): designated as historic under Chapter 14-1000, or in a historic
    district and contributing in the Historical Commission's opinion. Being in a
    district is not enough, so a district flag alone does not open the historic path.
    The old single 'historic' flag is read the same careful way.
    """
    individual = bool(lot.get("historic_individual"))
    in_district = bool(lot.get("historic_district")) or bool(lot.get("historic"))
    contributing = lot.get("historic_contributing")
    if individual or (in_district and contributing is True):
        reasons.append("Historic path used. Confirm historic status with the Historical Commission")
        return True
    if in_district:
        reasons.append("In a historic district. The historic path applies only if the Historical Commission "
                       "rates the building contributing. Confirm with the Commission")
    return False


# ------------------------------------------------------------------ layering

def _usable(leaf: Optional[dict[str, Any]]) -> bool:
    """A null marked unverified means 'not confirmed'. It never overrides anything."""
    return bool(leaf) and not (leaf.get("value") is None and leaf.get("confidence") == "unverified")


def _leaf(data: dict[str, Any], path: Path_) -> Optional[dict[str, Any]]:
    return (data.get(path[0]) or {}).get(path[1])


def _layer_paths(data: dict[str, Any]) -> list[Path_]:
    skip = ("provenance", "districts")
    return [(s, f) for s, body in data.items() if s not in skip and isinstance(body, dict) for f in body]


def _value(picked: Picked, section: str, field: str) -> Any:
    hit = picked.get((section, field))
    return hit[0].get("value") if hit else None


def _apply_local(picked: Picked, data: dict[str, Any], source: str) -> None:
    """Place and local bill layers replace values. They carry no floors or caps."""
    for path in _layer_paths(data):
        leaf = _leaf(data, path)
        if _usable(leaf):
            picked[path] = (leaf, source)


def _apply_district(picked: Picked, place: dict[str, Any], source: str, lot: dict[str, Any]) -> None:
    code = _match_code(lot.get("zoning_district"), list((place.get("districts") or {}).keys()))
    if code is None:
        return
    entry, where = place["districts"][code], f"{source}#districts.{code}"
    for field, path in DISTRICT_FIELDS.items():
        if _usable(entry.get(field)):
            picked[path] = (entry[field], where)
    semi = entry.get("setback_side_semi_ft")
    if _building_type(lot.get("building_type")) == "semi_detached" and _usable(semi):
        picked[("envelope", "setback_side_ft")] = (semi, where)
    if _usable(entry.get("principal_max_height_ft")):
        picked[DISTRICT_HEIGHT] = (entry["principal_max_height_ft"], where)


def _fill_defaults(picked: Picked, default: dict[str, Any]) -> None:
    for path in _layer_paths(default):
        if path not in picked and _usable(_leaf(default, path)):
            picked[path] = (_leaf(default, path), DEFAULT)


def _out_key(path: Path_) -> str:
    return next((k for k, p in VALUE_KEYS.items() if p == path), ".".join(path))


def _state_floor(data: dict[str, Any], path: Path_, lot: dict[str, Any]) -> Optional[float]:
    """The number a state floor guarantees for this lot, or None when a lot fact is missing.

    Size: lesser of a share of the house and a fixed sq ft. Height: lesser of a
    fixed height and the house height.
    """
    value = _leaf(data, path)["value"]
    if path == ("size", "max_sqft"):
        share = _leaf(data, ("size", "max_share_of_house"))
        if share is None:
            return value
        house = lot.get("house_sqft")
        return round(min(value, share["value"] * house)) if house else None
    if path == ("envelope", "max_height_ft"):
        height = lot.get("house_height_ft")
        return min(value, height) if height else None
    return value


def _apply_state(picked: Picked, data: dict[str, Any], source: str, lot: dict[str, Any],
                 skip: set[Path_], limits: dict[str, Any], reasons: list[str]) -> None:
    """Apply a state bill. 'set' replaces. Floors and caps change the value a lot can count on."""
    for path in _layer_paths(data):
        leaf = _leaf(data, path)
        if not _usable(leaf) or path == ("size", "max_share_of_house"):
            continue
        mode = leaf.get("mode", "set")
        if mode == "set":
            picked[path] = (leaf, source)
            continue
        key = _out_key(path)
        bound = _state_floor(data, path, lot) if mode == "at_least" else leaf["value"]
        limits[key] = {"mode": mode, "value": leaf["value"], "for_this_lot": bound,
                       "section": leaf["section"], "note": leaf.get("note")}
        if path in skip:
            continue
        cur = picked.get(path)
        if bound is None:
            if cur is None or (cur[0].get("value") is not None and cur[0]["value"] < leaf["value"]):
                reasons.append(f"{leaf.get('note') or key} A missing lot fact (house size or height) "
                               f"keeps the local value until it is known")
            continue
        if cur is not None and cur[0].get("value") is None:
            continue  # the town sets no limit. A floor or cap does not add one.
        old = None if cur is None else cur[0]["value"]
        new = bound if old is None else (max(old, bound) if mode == "at_least" else min(old, bound))
        if new != old:
            picked[path] = ({**leaf, "value": new}, source)


def layers_for(place: str, scenario: str) -> tuple[list[str], list[str]]:
    """(local layers, state layers) for a place and scenario."""
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    local = [place] + (LOCAL_REFORM.get(place, []) if scenario == "local_reform" else [])
    state = [STATE_REFORM] if scenario == "state_reform" else []
    return local, state


# ------------------------------------------------------------------ eligibility

def _active_overlays(bars: list[dict[str, Any]], lot: dict[str, Any], reasons: list[str]
                     ) -> Optional[set[str]]:
    """Overlay names that cover the lot.

    The union of the overlay list and the overlays implied by council district and
    ward. A mapped layer can lag a new overlay (/SIX was added in 2026), while
    council district lines are reliable, so both inputs count.
    """
    listed = None if lot.get("overlays") is None else {"/" + _norm(o) for o in lot["overlays"]}
    council, ward = lot.get("council_district"), lot.get("ward")
    if council is None and ward is None:
        if listed is None and bars:
            reasons.append("Overlay unknown. Give the overlay list, or the council district and ward")
        elif bars and any(b.get("council_districts") for b in bars):
            reasons.append("Council district unknown. Overlays that follow council district lines may be missing "
                           "from the overlay list. Check it")
        return listed
    active = {"/" + _norm(b["overlay"]) for b in bars
              if (council is not None and int(council) in b.get("council_districts", []))
              or (ward is not None and int(ward) in b.get("wards", []))}
    active |= listed or set()
    ward_bars = [b for b in bars if b.get("wards")]
    if ward is None and listed is None and ward_bars:
        wards = sorted({w for b in ward_bars for w in b["wards"]})
        names = ", ".join(b["overlay"] for b in ward_bars)
        reasons.append(f"Ward unknown. Wards {', '.join(map(str, wards))} ({names}) bar all ADUs. Check the ward")
    if council is None and any(b.get("council_districts") for b in bars):
        reasons.append("Council district unknown. Some overlays follow council district lines. Check it")
    return active


def _overlay_fails(picked: Picked, lot: dict[str, Any], historic: bool, reasons: list[str]) -> list[str]:
    bars = _value(picked, "eligibility", "overlay_bars") or []
    have = _active_overlays(bars, lot, reasons)
    if not have:
        return []
    fails = []
    for bar in bars:
        if "/" + _norm(bar["overlay"]) not in have:
            continue
        in_scope = bar["districts"] is None or _match_code(lot.get("zoning_district"), bar["districts"]) is not None
        if in_scope and not (bar["historic_ok"] and historic):
            scope = "all ADUs" if bar["districts"] is None else f"ADUs in {' and '.join(bar['districts'])}"
            fails.append(f"Inside the {bar['overlay']} overlay, which bars {scope} ({bar['section']})")
    return fails


def _base_fails(picked: Picked, lot: dict[str, Any]) -> list[str]:
    """District, building type and lot size tests. Skipped on the historic path."""
    fails = []
    districts = _value(picked, "eligibility", "zoning_districts")
    district = lot.get("zoning_district")
    if districts and _match_code(district, districts) is None:
        fails.append(f"Zoned {district or 'unknown'}. Needs {' or '.join(districts)}")
    types = _value(picked, "eligibility", "building_types")
    btype = _building_type(lot.get("building_type"))
    if types and btype not in types:
        names = " or ".join(t.replace("_", "-") for t in types)
        fails.append(f"{(btype or 'unknown').replace('_', '-').capitalize()} building. Needs a {names} house")
    min_lot = _value(picked, "eligibility", "min_lot_sqft")
    area = lot.get("lot_sqft")
    if min_lot and area is not None and area < min_lot:
        fails.append(f"Lot is {area:,.0f} sq ft. Needs {min_lot:,.0f} sq ft or more")
    return fails


def _form_types(picked: Picked, lot: dict[str, Any]) -> list[str]:
    """ADU forms the rules allow on this lot, before the approval path."""
    types = _value(picked, "form", "types_allowed")
    types = list(ALL_TYPES if types is None else types)
    if _value(picked, "eligibility", "existing_structure_only"):
        types = [t for t in types if t not in NEW_STRUCTURE_TYPES]
    if lot.get("has_accessory_building") is False:
        types = [t for t in types if t != "garage_conversion"]
    return [t for t in ALL_TYPES if t in types]


def _approval_by_type(picked: Picked, lot: dict[str, Any], eligible: bool) -> dict[str, str]:
    base = _value(picked, "approval", "path") or "not_allowed"
    fallback = _value(picked, "approval", "fallback_path") or "not_allowed"
    if not eligible or base == "not_allowed":
        return {t: fallback for t in ALL_TYPES}
    yard = _value(picked, "approval", "detached_in_yard_path")
    allowed = _form_types(picked, lot)
    out = {}
    for t in ALL_TYPES:
        path = base if t in allowed else fallback
        if t in allowed and yard and t == "detached_new":
            path = yard
        if t in allowed and yard and t == "over_garage":
            # Above an existing garage that abuts a way needs no exception.
            on_way = lot.get("has_alley") is True and lot.get("has_accessory_building") is True
            path = base if on_way else yard
        out[t] = path
    return out


# ------------------------------------------------------------------ resolve

def _pick(place: str, scenario: str, lot: dict[str, Any], historic: bool,
          limits: dict[str, Any], reasons: list[str]) -> Picked:
    local, state = layers_for(place, scenario)
    picked: Picked = {}
    for i, name in enumerate(local):
        _apply_local(picked, load_rules(name), name)
        if i == 0:
            _apply_district(picked, load_rules(name), name, lot)
    _fill_defaults(picked, load_rules(DEFAULT))
    skip: set[Path_] = set()
    if historic and _value(picked, "size", "historic_exempt"):
        skip.add(("size", "max_sqft"))  # no local cap to raise
    for name in state:
        _apply_state(picked, load_rules(name), name, lot, skip, limits, reasons)
    return picked


def _citation(leaf: dict[str, Any], source: str) -> dict[str, Any]:
    return {"section": leaf["section"], "url": leaf.get("url"), "verified_on": leaf.get("verified_on"),
            "confidence": leaf["confidence"], "source_file": source}


def _checks(place: str, scenario: str) -> list[str]:
    # The top layer's checks only. A reform file restates the place checks it keeps,
    # so a check the reform removes (such as owner occupancy) is not shown.
    local, state = layers_for(place, scenario)
    return list(load_rules((local + state)[-1])["provenance"].get("checks", []))


def _type_reasons(picked: Picked, by_type: dict[str, str]) -> list[str]:
    out = []
    cap = picked.get(("envelope", "accessory_structure_max_sqft"))
    if cap and by_type["detached_new"] not in OK_PATHS:
        height = _value(picked, "envelope", "max_height_ft")
        line = (f"No new detached ADU by right here. Every residential accessory structure is capped at "
                f"{cap[0]['value']:,.0f} sq ft" + (f" and {height:,.0f} ft" if height is not None else "")
                + f" ({cap[0]['section']})")
        rule = picked.get(("eligibility", "existing_structure_only"))
        if rule and rule[0].get("value"):
            line += f", and the ADU must use an existing building ({rule[0]['section']})"
        out.append(line)
    yard = picked.get(("approval", "detached_in_yard_path"))
    if yard and by_type["detached_new"] == "administrator_exception":
        out.append(f"A new detached ADU in a side or rear yard needs an Administrator's Exception "
                   f"({yard[0]['section']}). Not needed above an existing garage that abuts a way. Inside the house, attached, or a garage conversion is by right")
    return out


def _heights(picked: Picked) -> tuple[dict[str, Any], Optional[tuple[dict[str, Any], str]]]:
    structure = _value(picked, "envelope", "max_height_ft")
    principal = picked.get(DISTRICT_HEIGHT) if _value(picked, "envelope", "internal_uses_district_height") else None
    by_type = {t: (principal[0]["value"] if principal and t in PRINCIPAL_TYPES else structure) for t in ALL_TYPES}
    return by_type, principal


def _rear(out: dict[str, Any], lot: dict[str, Any]) -> tuple[Optional[float], str]:
    alley = lot.get("has_alley")
    if alley is True and out["setback_rear_alley_ft"] is not None:
        return out["setback_rear_alley_ft"], "alley"
    if alley is None:
        return out["setback_rear_ft"], "unknown_alley_used_no_alley_value"
    return out["setback_rear_ft"], "no_alley"


def resolve(place: str, scenario: str, lot: dict[str, Any]) -> dict[str, Any]:
    """Rule values for one lot under one scenario. See module docstring and README for keys.

    place is a rule file name (philadelphia, pittsburgh, pa_lehigh_allentown). A town in
    towns_index.json may also be given by name or GEOID. A town without a file resolves
    on default.json, so every value is in "assumed".
    """
    asked = place
    place = _place_file(place)
    if place.startswith("pa_") or (place == DEFAULT and asked != DEFAULT):
        return _resolve_town(place, scenario, lot)
    reasons: list[str] = []
    limits: dict[str, Any] = {}
    layers_for(place, scenario)
    place_rules = load_rules(place)
    historic = False
    if (_leaf(place_rules, ("eligibility", "historic_bypass")) or {}).get("value"):
        historic = _historic(lot, reasons)
    picked = _pick(place, scenario, lot, historic, limits, reasons)

    fails = _overlay_fails(picked, lot, historic, reasons) + ([] if historic else _base_fails(picked, lot))
    by_type = _approval_by_type(picked, lot, not fails)
    types_allowed = [t for t in ALL_TYPES if by_type[t] in OK_PATHS]
    allowed = bool(types_allowed)
    approval = min(by_type.values(), key=PATH_ORDER.index)
    path_key = ("approval", "path") if allowed else ("approval", "fallback_path")
    if not allowed and picked.get(("approval", "path"), ({}, ""))[1] == DEFAULT:
        fails.append("No ADU rule on file for this place")

    out: dict[str, Any] = {
        "allowed": allowed, "approval_path": approval,
        "reasons": reasons + fails + _type_reasons(picked, by_type) + (_checks(place, scenario) if allowed else []),
        "types_allowed": types_allowed,
    }
    citations, assumed = {}, []
    for key, path in VALUE_KEYS.items():
        hit = picked.get(path)
        value = hit[0].get("value") if hit else None
        if key == "max_size_sqft" and historic and _value(picked, "size", "historic_exempt"):
            value, hit = None, picked.get(("size", "historic_exempt"))
        if key == "min_lot_sqft" and historic:
            value, hit = None, picked.get(("eligibility", "historic_bypass"))  # no lot size test
        out[key] = int(value) if key in INTEGER_KEYS and value is not None else value
        if hit:
            citations[key] = _citation(*hit)
            if hit[1] == DEFAULT and value is not None:
                assumed.append(key)
    for key, path in (("approval_path", path_key), ("types_allowed", ("form", "types_allowed"))):
        if picked.get(path):
            citations[key] = _citation(*picked[path])
    heights, principal = _heights(picked)
    if principal:
        citations["max_height_by_type.internal"] = _citation(*principal)
    fire = {}
    for key, path in FIRE_KEYS.items():
        hit = picked.get(path)
        fire[key] = hit[0]["value"] if hit else None
        if hit:
            citations[f"fire_separation.{key}"] = _citation(*hit)
    out["citations"] = citations
    out["assumed"] = assumed
    out["approval_by_type"] = by_type
    out["max_height_by_type"] = heights
    out["setback_rear_effective_ft"], out["rear_setback_rule"] = _rear(out, lot)
    out["state_limits"] = limits
    out["fire_separation"] = fire
    out["historic_path"] = historic
    return {k: out[k] for k in OUTPUT_KEYS}


# ------------------------------------------------------------------ town resolver
# Town files (pa_*.json) and towns without a file resolve here. Philadelphia and Pittsburgh
# never come here, so their output is unchanged. A town result has OUTPUT_KEYS + TOWN_KEYS.

TOWN_KEYS = ["adu_status", "adu_term", "conditions", "approval_by_district", "district_path", "fallback",
             "max_share_by_type", "parking_total_on_site", "parking_reading",
             # Added in pass 3.
             "scope", "conditions_overridden", "max_size_by_type", "setbacks_by_type", "alternatives",
             # Added in pass 4: "conditional_on_reading" when the path holds only under one reading of the code.
             "approval_qualifier"]
NO_ADU_STATUSES = {"not_addressed", "prohibited"}
DETACHED_TYPES = ["detached_new", "garage_conversion", "over_garage"]
GARAGE_TYPES = {"garage_conversion", "over_garage"}
YARDS = ("setback_front_ft", "setback_side_ft", "setback_rear_ft")
# Town conditions HB 2186 would override (6305: no owner occupancy or family rule, ADUs do not count
# toward density, one ADU per residential lot by right).
BILL_OVERRIDES = {"adu_status", "family", "age", "care", "owner_occupancy", "sponsor", "lot_area_per_unit",
                  "existing_structure", "district", "building_type", "scope"}
BILL_NOTE = "Would no longer apply under HB 2186. The bill is not law"


def _leaf_from(item: dict[str, Any], parent: dict[str, Any], value: Any) -> dict[str, Any]:
    """A leaf built from a list item (district path or gate), with the parent leaf's date and confidence."""
    return {"value": value, "section": item.get("section") or parent["section"], "url": item.get("url") or parent.get("url"),
            "verified_on": parent.get("verified_on"), "confidence": parent["confidence"], "note": item.get("note")}


def _district_row(place: dict[str, Any], lot: dict[str, Any]) -> tuple[Optional[str], dict[str, Any]]:
    code = _match_code(lot.get("zoning_district"), list((place.get("districts") or {}).keys()))
    return code, ((place.get("districts") or {}).get(code) or {}) if code else {}


def _district_path(place: dict[str, Any], lot: dict[str, Any]) -> Optional[tuple[dict[str, Any], str]]:
    """The approval path for the lot's district, when the file sets one by district."""
    code, row = _district_row(place, lot)
    if _usable(row.get("adu_path")) and row["adu_path"].get("value"):
        return row["adu_path"], f"#districts.{code}.adu_path"
    leaf = _leaf(place, ("approval", "district_paths"))
    for item in (leaf or {}).get("value") or []:
        if _match_code(lot.get("zoning_district"), item["districts"]) is not None:
            return _leaf_from(item, leaf, item["path"]), "#approval.district_paths"
    return None


def _scope(data: dict[str, Any], lot: dict[str, Any]) -> dict[str, Any]:
    """Where the ADU rule reaches. in_scope is None when the file has no scope or the district is unknown."""
    leaf = _leaf(data, ("adu", "scope_districts"))
    districts = (leaf or {}).get("value") or None
    if not districts:
        return {"districts": None, "in_scope": None, "status_outside": None, "section": None}
    outside = (_leaf(data, ("adu", "status_outside")) or {}).get("value") or "not_addressed"
    d = lot.get("zoning_district")
    return {"districts": districts, "in_scope": None if d is None else _match_code(d, districts) is not None,
            "status_outside": outside, "section": leaf["section"]}


def _outside_scope_data(data: dict[str, Any]) -> dict[str, Any]:
    """The file as it reads for a lot outside the ADU scope: no ADU numbers, the unlisted-use path or the fallback."""
    keep = {k: data[k] for k in ("provenance", "envelope", "coverage", "districts") if k in data}
    appr = data.get("approval") or {}
    path = appr.get("unlisted_use_path") if _usable(appr.get("unlisted_use_path")) else appr.get("fallback_path")
    approval = {k: appr[k] for k in ("fallback_path", "unlisted_use_path", "alternatives") if k in appr}
    if path:
        approval["path"] = path
    adu = dict(data.get("adu") or {})
    if adu.get("status_outside"):
        adu["status"] = adu["status_outside"]
    return {**keep, "approval": approval, "adu": adu}


def _apply_district_town(picked: Picked, place: dict[str, Any], source: str, lot: dict[str, Any],
                         principal: dict[str, tuple[dict[str, Any], str]]) -> None:
    """District values. District yards go to `principal` (attached units). They fill the accessory
    yards only where the file has none, or when district yards bind accessory buildings. A null in
    the row never wipes a value."""
    code, entry = _district_row(place, lot)
    if not code:
        return
    where = f"{source}#districts.{code}"
    bind = (_leaf(place, ("envelope", "district_yards_bind_accessory")) or {}).get("value") is True
    semi = entry.get("setback_side_semi_ft")
    use_semi = _building_type(lot.get("building_type")) == "semi_detached" and _usable(semi) and semi.get("value") is not None
    for field, path in {**DISTRICT_FIELDS, "principal_max_height_ft": DISTRICT_HEIGHT,
                        "separation_ft": ("envelope", "separation_ft")}.items():
        leaf = semi if (field == "setback_side_ft" and use_semi) else entry.get(field)
        if not _usable(leaf):
            continue
        if field in YARDS and leaf.get("value") is not None:
            principal[field] = (leaf, where)
            own = picked.get(path)
            if own and own[0].get("value") is not None and not bind:
                continue  # an accessory yard in the file wins for a detached unit
        if leaf.get("value") is None and (picked.get(path) or ({}, ""))[0].get("value") is not None:
            continue
        picked[path] = (leaf, where)


def _pick_town(data: dict[str, Any], place: str, scenario: str, lot: dict[str, Any], historic: bool,
               limits: dict[str, Any], reasons: list[str]
               ) -> tuple[Picked, Picked, Optional[str], dict[str, tuple[dict[str, Any], str]]]:
    """(picked after state, picked before state, how the path was chosen, district principal yards)."""
    _, state = layers_for(place, scenario)
    picked: Picked = {}
    principal: dict[str, tuple[dict[str, Any], str]] = {}
    _apply_local(picked, data, place)
    _apply_district_town(picked, data, place, lot, principal)
    how = None
    hist = _leaf(data, ("approval", "historic_path"))
    dpath = _district_path(data, lot)
    unlisted = _leaf(data, ("approval", "unlisted_use_path"))
    status = (_leaf(data, ("adu", "status")) or {}).get("value")
    if historic and _usable(hist) and hist.get("value"):
        picked[("approval", "path")] = (hist, f"{place}#approval.historic_path")
        how = "historic"
    elif dpath:
        picked[("approval", "path")] = (dpath[0], place + dpath[1])
        how = "district"
    elif status in NO_ADU_STATUSES and _usable(unlisted) and unlisted.get("value"):
        picked[("approval", "path")] = (unlisted, f"{place}#approval.unlisted_use_path")
        how = "unlisted"
    _fill_defaults(picked, load_rules(DEFAULT))
    today = dict(picked)
    for name in state:
        _apply_state(picked, load_rules(name), name, lot, set(), limits, reasons)
    return picked, today, how, principal


def _form_types_town(picked: Picked, lot: dict[str, Any]) -> list[str]:
    """A unit above an existing garage counts as using an existing structure."""
    types = _value(picked, "form", "types_allowed")
    types = list(ALL_TYPES if types is None else types)
    if _value(picked, "eligibility", "existing_structure_only"):
        types = [t for t in types if t not in NEW_STRUCTURE_TYPES or t == "over_garage"]
    if lot.get("has_accessory_building") is False:
        types = [t for t in types if t not in ("garage_conversion", "over_garage")]
    return [t for t in ALL_TYPES if t in types]


def _gate_scope(g: dict[str, Any], lot: dict[str, Any], historic: bool) -> bool:
    when = g.get("when", "always")
    if (when == "historic" and not historic) or (when == "not_historic" and historic):
        return False
    if g.get("districts") and _match_code(lot.get("zoning_district"), g["districts"]) is None:
        return False
    if g.get("not_districts") and lot.get("zoning_district") and _match_code(lot["zoning_district"], g["not_districts"]) is not None:
        return False
    btype = _building_type(lot.get("building_type"))
    if g.get("building_types") and btype not in g["building_types"]:
        return False
    return True


def _gate_met(g: dict[str, Any], lot: dict[str, Any]) -> Optional[bool]:
    test, area = g.get("test"), lot.get("lot_sqft")
    if test == "has_alley":
        return None if lot.get("has_alley") is None else bool(lot["has_alley"] or lot.get("corner_lot"))
    if test == "has_accessory_building":
        return lot.get("has_accessory_building")
    if test in ("lot_sqft_at_least", "lot_sqft_below") and g.get("value") is not None:
        if area is None:
            return None
        return area >= g["value"] if test == "lot_sqft_at_least" else area < g["value"]
    return None


def _cond(kind: str, text: str, leaf: Optional[dict[str, Any]], met: Optional[bool] = None,
          applies_to: Optional[list[str]] = None, effect: str = "condition") -> dict[str, Any]:
    leaf = leaf or {}
    return {"kind": kind, "condition": text, "met": met, "applies_to": applies_to, "effect": effect,
            "section": leaf.get("section"), "url": leaf.get("url"), "confidence": leaf.get("confidence")}


def _per_unit(data: dict[str, Any], lot: dict[str, Any]) -> Optional[dict[str, Any]]:
    _, row = _district_row(data, lot)
    per = row.get("lot_area_per_unit_sqft") if _usable(row.get("lot_area_per_unit_sqft")) else _leaf(data, ("eligibility", "lot_area_per_unit_sqft"))
    return per if per and per.get("value") else None


def _density(data: dict[str, Any], lot: dict[str, Any]) -> Optional[tuple[dict[str, Any], float, bool]]:
    """(leaf, lot area needed, binding). Binding when the leaf is verified and has no open reading."""
    per = _per_unit(data, lot)
    if not per:
        return None
    units = int(lot.get("existing_units") or 1) + 1
    binding = per.get("confidence") == "verified"
    return per, units * per["value"], binding


def _town_conditions(data: dict[str, Any], picked: Picked, lot: dict[str, Any], historic: bool,
                     how: Optional[str], scope: dict[str, Any]) -> list[dict[str, Any]]:
    """Who may live there, owner rule, existing-building-only, type, district and lot gates, each cited."""
    out = []
    status = _leaf(data, ("adu", "status"))
    if scope["districts"] and scope["in_scope"] is not True:
        out.append(_cond("scope", f"The ADU rule reaches only {', '.join(scope['districts'])}. Elsewhere the code's status is "
                                  f"{scope['status_outside'].replace('_', ' ')}", _leaf(data, ("adu", "scope_districts")),
                         scope["in_scope"]))
    if status and status.get("value") and status["value"] != "allowed_by_right":
        out.append(_cond("adu_status", f"{status['value'].replace('_', ' ')}. {status.get('note') or ''}".strip(), status))
    if how == "historic":
        hist = _leaf(data, ("approval", "historic_path"))
        out.append(_cond("historic", f"Historic path: {hist['value'].replace('_', ' ')}. {hist.get('note') or ''}".strip(), hist, True))
    if how == "unlisted":
        un = _leaf(data, ("approval", "unlisted_use_path"))
        out.append(_cond("other", f"The code does not list ADUs. A use not provided for may be approved by "
                                  f"{un['value'].replace('_', ' ')}. {un.get('note') or ''}".strip(), un))
    occ = _leaf(data, ("use", "occupancy"))
    if occ and occ.get("value") and how != "historic":
        out.append(_cond("occupancy", occ["value"], occ))
    fam = picked.get(("use", "family_only"))
    if fam and fam[0].get("value") and how != "historic":
        out.append(_cond("family", fam[0].get("note") or "Occupants must be family members", fam[0]))
    own = picked.get(("use", "owner_occupancy"))
    if own and own[0].get("value"):
        out.append(_cond("owner_occupancy", own[0].get("note") or "The owner must live on the lot", own[0]))
    ex = picked.get(("eligibility", "existing_structure_only"))
    if ex and ex[0].get("value"):
        out.append(_cond("existing_structure", ex[0].get("note") or "Only inside an existing building", ex[0],
                         lot.get("has_accessory_building")))
    bt = picked.get(("eligibility", "building_types"))
    if bt and bt[0].get("value"):
        btype = _building_type(lot.get("building_type"))
        out.append(_cond("building_type", f"House type must be {' or '.join(bt[0]['value'])}", bt[0],
                         None if btype is None else btype in bt[0]["value"]))
    zd = picked.get(("eligibility", "zoning_districts"))
    if zd and zd[0].get("value") and how != "district":
        d = lot.get("zoning_district")
        out.append(_cond("district", f"Zoning district must be one of {', '.join(zd[0]['value'])}", zd[0],
                         None if d is None else _match_code(d, zd[0]["value"]) is not None))
    ml = picked.get(("eligibility", "min_lot_sqft"))
    if ml and ml[0].get("value") and not historic and "#districts." not in ml[1]:
        area = lot.get("lot_sqft")
        out.append(_cond("lot_size", f"ADU rule: lot of at least {ml[0]['value']:,.0f} sq ft" + (f". {ml[0]['note']}" if ml[0].get("note") else ""),
                         ml[0], None if area is None else area >= ml[0]["value"]))
    dm = _district_min(data, lot)
    if dm and not historic:
        leaf, need, share = dm
        area = lot.get("lot_sqft")
        met = None if area is None else area >= need
        if _district_min_binds(data):
            rule = _leaf(data, ("eligibility", "requires_conforming_lot")) or _leaf(data, ("eligibility", "min_lot_share_of_district"))
            text = (f"The ADU needs a lot of at least {need:,.0f} sq ft" + (f", {share:.0%} of the district minimum of {leaf['value']:,.0f}" if share != 1 else
                    f", the district minimum") + f" ({rule['section']})")
            out.append(_cond("lot_size", text, leaf, met, effect="bars"))
        elif met is False:
            out.append(_cond("lot_size", f"This lot is below the district minimum of {leaf['value']:,.0f} sq ft. It may be a nonconforming lot. "
                                         f"Ask the zoning officer whether an ADU is allowed on it", leaf, False))
        else:
            out.append(_cond("lot_size", f"The district's minimum lot is {leaf['value']:,.0f} sq ft. A rule for creating lots, not an ADU rule",
                             leaf, met))
    dens = _density(data, lot)
    if dens:
        per, need, binding = dens
        area = lot.get("lot_sqft")
        lead = "" if binding else "If the ADU counts as a dwelling unit: "
        out.append(_cond("lot_area_per_unit", f"{lead}{per['value']:,.0f} sq ft of lot per dwelling unit. The house and the ADU need "
                                              f"{need:,.0f} sq ft" + (f". {per['note']}" if per.get("note") else ""),
                         per, None if area is None else area >= need, effect="bars" if binding else "condition"))
    gates = _leaf(data, ("eligibility", "gates"))
    for g in (gates or {}).get("value") or []:
        if _gate_scope(g, lot, historic):
            c = _cond(g["kind"], g["condition"], _leaf_from(g, gates, None), _gate_met(g, lot), g.get("applies_to"), g["effect"])
            c["test"] = g.get("test")
            if c["test"] and c["met"] is None:
                c["condition"] += ". Allowed only if this holds. The lot fact is not known"
            out.append(c)
    return out


def _district_min(data: dict[str, Any], lot: dict[str, Any]) -> Optional[tuple[dict[str, Any], float, float]]:
    """(district minimum lot leaf, area the ADU needs, share). The share comes from min_lot_share_of_district."""
    _, row = _district_row(data, lot)
    leaf = row.get("min_lot_sqft")
    if not (_usable(leaf) and leaf.get("value")):
        return None
    share = (_leaf(data, ("eligibility", "min_lot_share_of_district")) or {}).get("value") or 1
    return leaf, leaf["value"] * share, share


def _district_min_binds(data: dict[str, Any]) -> bool:
    """A district minimum lot bars an ADU only when the ADU rule ties to it: requires_conforming_lot,
    or a share of the district minimum. Otherwise an existing smaller lot may be nonconforming."""
    conf = (_leaf(data, ("eligibility", "requires_conforming_lot")) or {}).get("value") is True
    share = (_leaf(data, ("eligibility", "min_lot_share_of_district")) or {}).get("value")
    return conf or share is not None


def _apply_gates(by_type: dict[str, str], conditions: list[dict[str, Any]], fallback: str, reasons: list[str]) -> None:
    for c in conditions:
        if c["effect"] != "bars" or c["met"] is True or c["kind"] == "lot_area_per_unit":
            continue
        if c["met"] is None and c.get("test"):
            continue  # unknown lot fact: allowed if the condition holds
        hit = [t for t in (c["applies_to"] or ALL_TYPES) if by_type.get(t) in OK_PATHS]
        for t in hit:
            by_type[t] = fallback
        if hit:
            reasons.append(f"{c['condition']} ({c['section']}). Not allowed here: {', '.join(t.replace('_', ' ') for t in hit)}")


def _by_district(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    base = _leaf(data, ("approval", "path")) or {}
    out: dict[str, dict[str, Any]] = {}
    for d in (_leaf(data, ("eligibility", "zoning_districts")) or {}).get("value") or []:
        out[d] = {"path": base.get("value"), "section": base.get("section")}
    leaf = _leaf(data, ("approval", "district_paths"))
    for item in (leaf or {}).get("value") or []:
        for d in item["districts"]:
            out[d] = {"path": item["path"], "section": item["section"]}
    for code, row in (data.get("districts") or {}).items():
        if _usable(row.get("adu_path")) and row["adu_path"].get("value"):
            out[code] = {"path": row["adu_path"]["value"], "section": row["adu_path"]["section"]}
    return out


def _alternatives(data: dict[str, Any], lot: dict[str, Any]) -> list[dict[str, Any]]:
    """Other ways to add a unit (not ADUs). applies is None when the lot facts do not settle it."""
    leaf = _leaf(data, ("approval", "alternatives"))
    out = []
    for a in (leaf or {}).get("value") or []:
        d, area = lot.get("zoning_district"), lot.get("lot_sqft")
        in_d = None if not a.get("districts") or d is None else _match_code(d, a["districts"]) is not None
        if not a.get("districts"):
            in_d = True
        lot_ok = None if a.get("min_lot_sqft") is None or area is None else area >= a["min_lot_sqft"]
        applies = False if (in_d is False or lot_ok is False) else (True if in_d and lot_ok is not False and
                                                                    (a.get("min_lot_sqft") is None or lot_ok) else None)
        out.append({**a, "url": a.get("url") or leaf.get("url"), "applies": applies,
                    "note": "Not an ADU. A second unit by another path"})
    return out


def _resolve_town(place: str, scenario: str, lot: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    limits: dict[str, Any] = {}
    file_data = load_rules(place)
    scope = _scope(file_data, lot)
    data = _outside_scope_data(file_data) if scope["in_scope"] is False else file_data
    hist_leaf = _leaf(data, ("approval", "historic_path"))
    historic = False
    if (_leaf(data, ("eligibility", "historic_bypass")) or {}).get("value") or (_usable(hist_leaf) and hist_leaf.get("value")):
        historic = _historic(lot, reasons)
    picked, today, how, principal = _pick_town(data, place, scenario, lot, historic, limits, reasons)
    state = scenario == "state_reform"
    status_leaf = _leaf(data, ("adu", "status")) or {}
    status = status_leaf.get("value")
    term = (_leaf(file_data, ("adu", "term")) or {}).get("value")

    fails = _overlay_fails(picked, lot, historic, reasons) + ([] if historic else _base_fails(picked, lot))
    if how in ("district", "historic"):
        fails = [f for f in fails if not f.startswith("Zoned ")]
    dm = _district_min(data, lot)
    area = lot.get("lot_sqft")
    dm_binds = _district_min_binds(data)
    if dm and dm_binds and not historic and not state and area is not None and area < dm[1]:
        leaf, need, share = dm
        fails.append(f"The district's minimum lot is {leaf['value']:,.0f} sq ft ({leaf['section']})"
                     + (f". The ADU rule accepts {share:.0%} of it, {need:,.0f} sq ft" if share != 1 else "")
                     + f". This lot is {area:,.0f} sq ft, so any new use needs relief")
    dens = _density(data, lot)
    if dens and dens[2] and not state and area is not None and area < dens[1]:
        per, need, _ = dens
        fails.append(f"{per['value']:,.0f} sq ft of lot per dwelling unit ({per['section']}). The house and the ADU need "
                     f"{need:,.0f} sq ft. This lot is {area:,.0f} sq ft")
    fallback = _value(picked, "approval", "fallback_path") or "variance"
    base = _value(picked, "approval", "path") or "not_allowed"
    eligible = not fails and base != "not_allowed"
    allowed_forms = _form_types_town(picked, lot)
    yard = _value(picked, "approval", "detached_in_yard_path")
    # A lot that fails a district, type or size test needs a variance. A fallback of special exception
    # or conditional use (for example a district path) does not cure that.
    fail_path = fallback if (not fails or fallback not in OK_PATHS) else "variance"
    by_type = {}
    for t in ALL_TYPES:
        path = base if (eligible and t in allowed_forms) else (fail_path if fails else fallback)
        if eligible and t == "detached_new" and t in allowed_forms and yard:
            path = yard
        by_type[t] = path
    conditions = _town_conditions(data, today if state else picked, lot, historic, how, scope)
    overridden: list[dict[str, Any]] = []
    if state:  # under the bill the town's gates show as conditions only, and some no longer apply
        live = []
        for c in conditions:
            (overridden if c["kind"] in BILL_OVERRIDES else live).append(c)
        for c in overridden:
            c["note"] = BILL_NOTE
        conditions = live
    else:
        _apply_gates(by_type, conditions, fallback, fails)
    types_allowed = [t for t in ALL_TYPES if by_type[t] in OK_PATHS]
    allowed = bool(types_allowed)
    approval = min(by_type.values(), key=PATH_ORDER.index)
    if not allowed and picked.get(("approval", "path"), ({}, ""))[1] == DEFAULT:
        fails.append("No ADU rule on file for this place")

    fb_hit = picked.get(("approval", "fallback_path")) or picked.get(("approval", "path"))
    fb = {"path": fallback, "section": fb_hit[0]["section"] if fb_hit else None,
          "url": fb_hit[0].get("url") if fb_hit else None, "note": fb_hit[0].get("note") if fb_hit else None}
    checks = list(file_data["provenance"].get("checks", []))
    if state:
        checks += _checks(place, scenario)
    head = []
    if status and status != "allowed_by_right" and status_leaf.get("section"):
        when = "Today the" if state else "The"
        if how == "district" and status in NO_ADU_STATUSES:
            dp0 = picked[("approval", "path")][0]
            head.append(f"{when} code's ADU status town-wide is {status.replace('_', ' ')} ({status_leaf['section']}). "
                        f"In {lot.get('zoning_district')} the district path applies: {dp0['value'].replace('_', ' ')} ({dp0['section']})")
        else:
            head.append(f"{when} code's ADU status is {status.replace('_', ' ')} ({status_leaf['section']})"
                        + (f". {status_leaf['note']}" if status_leaf.get("note") and status in NO_ADU_STATUSES else ""))
    if scope["districts"] and scope["in_scope"] is not True:
        head.append(f"The ADU rule reaches only {', '.join(scope['districts'])} ({scope['section']}). "
                    f"Elsewhere: {scope['status_outside'].replace('_', ' ')}")
    tail = []
    if not allowed:
        sec = fb["section"] or ""
        if fallback == "variance" and "910.2" not in sec:
            sec = f"{sec}, variance standards MPC 910.2" if sec else "variance standards MPC 910.2"
        tail.append(f"Not allowed as of right here. Path: {fallback.replace('_', ' ')}" + (f" ({sec})" if sec else "")
                    + (f". {fb['note']}" if fb["note"] else ""))
    out: dict[str, Any] = {"allowed": allowed, "approval_path": approval,
                           "reasons": head + reasons + fails + tail + _type_reasons(picked, by_type) + checks,
                           "types_allowed": types_allowed}
    citations, assumed = {}, []
    for key, path in VALUE_KEYS.items():
        hit = picked.get(path)
        value = hit[0].get("value") if hit else None
        if key == "max_size_sqft" and historic and _value(picked, "size", "historic_exempt"):
            value, hit = None, picked.get(("size", "historic_exempt"))
        if key == "min_lot_sqft" and historic:
            value, hit = None, picked.get(("eligibility", "historic_bypass"))
        if key == "min_lot_sqft" and value is None and dm and dm_binds and not historic and not state:
            value, hit = dm[1], (dm[0], f"{place}#districts")
        out[key] = int(value) if key in INTEGER_KEYS and value is not None else value
        if hit:
            citations[key] = _citation(*hit)
            if hit[1] == DEFAULT and value is not None:
                assumed.append(key)
    if "max_adus" in assumed:
        out["reasons"].append(f"ADUs per lot: the code is silent, {out['max_adus']} assumed (default.json)")
    qualifier = None
    if allowed and dens and not dens[2] and not state and area is not None and area < dens[1]:
        per, need, _ = dens
        qualifier = "conditional_on_reading"
        out["reasons"].insert(0, f"{approval.replace('_', ' ').capitalize()} only if the ADU does not count toward lot area per unit "
                                 f"({per['section']}). If it counts, this lot needs relief: {need:,.0f} sq ft for the house and the ADU, "
                                 f"this lot is {area:,.0f} sq ft")
    path_key = ("approval", "path") if allowed else ("approval", "fallback_path")
    for key, path in (("approval_path", path_key), ("types_allowed", ("form", "types_allowed"))):
        if picked.get(path):
            citations[key] = _citation(*picked[path])

    if state:
        _state_town_fixes(out, picked, lot, limits, citations, assumed, reasons)
    sizes, shares = _town_sizes(picked, out, limits, state, lot)
    for t in ALL_TYPES:
        if by_type[t] not in OK_PATHS:
            sizes[t], shares[t] = None, None

    heights, notes = _town_heights(data, today, status if how not in ("district", "historic") else None, state, limits,
                                   citations, assumed, lot, by_type)
    out["reasons"] += notes
    out["max_height_ft"] = heights["detached_new"]
    if heights["detached_new"] is None:
        citations.pop("max_height_ft", None)
    setbacks = _town_setbacks(picked, principal, limits, state, by_type)
    fire = {}
    for key, path in FIRE_KEYS.items():
        hit = picked.get(path)
        fire[key] = hit[0]["value"] if hit else None
        if hit:
            citations[f"fire_separation.{key}"] = _citation(*hit)
    total, reading = _town_parking(picked, today, state, out)
    out["citations"] = citations
    out["assumed"] = assumed
    out["approval_by_type"] = by_type
    out["max_height_by_type"] = heights
    out["setback_rear_effective_ft"], out["rear_setback_rule"] = _rear(out, lot)
    out["state_limits"] = limits
    out["fire_separation"] = fire
    out["historic_path"] = historic
    dp = picked.get(("approval", "path")) if how == "district" else None
    out.update({
        "adu_status": status, "adu_term": term, "conditions": conditions,
        "approval_by_district": _by_district(file_data),
        "district_path": {"district": lot.get("zoning_district"), "path": dp[0]["value"], "section": dp[0]["section"]} if dp else None,
        "fallback": fb, "max_share_by_type": shares,
        "parking_total_on_site": total, "parking_reading": reading,
        "scope": {k: scope[k] for k in ("districts", "in_scope", "status_outside")},
        "conditions_overridden": overridden, "max_size_by_type": sizes, "setbacks_by_type": setbacks,
        "alternatives": _alternatives(file_data, lot),
        "approval_qualifier": qualifier,
    })
    return {k: out[k] for k in OUTPUT_KEYS + TOWN_KEYS}


def _state_town_fixes(out: dict[str, Any], picked: Picked, lot: dict[str, Any], limits: dict[str, Any],
                      citations: dict[str, Any], assumed: list[str], reasons: list[str]) -> None:
    """The state floors win over a town share cap and a missing unit count."""
    bill = load_rules(STATE_REFORM)
    share_leaf = _leaf(bill, ("size", "max_share_of_house"))
    size_floor = limits.get("max_size_sqft", {}).get("for_this_lot")
    if out["max_share_of_house"] is not None and share_leaf and out["max_share_of_house"] < share_leaf["value"]:
        limits["max_share_of_house"] = {"mode": "at_least", "value": share_leaf["value"], "for_this_lot": share_leaf["value"],
                                        "section": share_leaf["section"], "note": "The town share cap may not sit under the state floor."}
        out["max_share_of_house"] = share_leaf["value"]
        citations["max_share_of_house"] = _citation(share_leaf, STATE_REFORM)
    if out["max_size_sqft"] is None and size_floor is not None:
        town_share = _value(picked, "size", "max_share_of_house")
        house = lot.get("house_sqft")
        if town_share is not None and house:
            out["max_size_sqft"] = max(round(town_share * house), size_floor)
            citations["max_size_sqft"] = _citation(_leaf(bill, ("size", "max_sqft")), STATE_REFORM)
    if out["max_adus"] is None and "max_adus" in limits:
        out["max_adus"] = int(limits["max_adus"]["value"])
        citations["max_adus"] = _citation(_leaf(bill, ("use", "max_adus")), STATE_REFORM)


def _town_sizes(picked: Picked, out: dict[str, Any], limits: dict[str, Any], state: bool, lot: dict[str, Any]
                ) -> tuple[dict[str, Optional[float]], dict[str, Optional[float]]]:
    """Floor area and share caps per ADU type. Inside or attached: the internal caps. Detached,
    garage or over a garage: the accessory building caps. Each falls back to the general cap."""
    gen_sqft, gen_share = out["max_size_sqft"], out["max_share_of_house"]
    caps = {"internal": (_value(picked, "size", "max_sqft_internal"), _value(picked, "size", "max_share_internal")),
            "accessory": (_value(picked, "size", "max_sqft_accessory_building"), _value(picked, "size", "max_share_accessory_building"))}
    floor = limits.get("max_size_sqft", {}).get("for_this_lot") if state else None
    share_floor = limits.get("max_share_of_house", {}).get("value") if state else None
    sizes, shares = {}, {}
    for t in ALL_TYPES:
        sqft, share = caps["internal" if t in PRINCIPAL_TYPES else "accessory"]
        sqft = gen_sqft if sqft is None else sqft
        share = gen_share if share is None else share
        if state and floor is not None and sqft is not None:
            sqft = max(sqft, floor)
        if state and share_floor is not None and share is not None:
            share = max(share, share_floor)
        sizes[t], shares[t] = sqft, share
    return sizes, shares


def _town_heights(data: dict[str, Any], today: Picked, status: Optional[str], state: bool, limits: dict[str, Any],
                  citations: dict[str, Any], assumed: list[str], lot: dict[str, Any], by_type: dict[str, str]
                  ) -> tuple[dict[str, Optional[float]], list[str]]:
    """Inside or attached: the district height. Detached forms: the accessory cap (garage cap for a
    garage), capped at the house when the code says so. The district height only when the file says no
    accessory rule reaches an ADU. Under the bill its height is a floor that never lowers a town value.
    No height for a form that is not allowed."""
    notes: list[str] = []
    structure = _value(today, "envelope", "max_height_ft")
    garage = _value(today, "envelope", "max_height_garage_ft")
    at_house = _value(today, "envelope", "height_capped_at_house")
    applies = _value(today, "envelope", "accessory_height_applies")
    house = lot.get("house_height_ft")
    principal_hit = today.get(DISTRICT_HEIGHT)
    principal = principal_hit[0]["value"] if principal_hit else None
    no_adu = status in NO_ADU_STATUSES
    if no_adu and not state:
        if structure is not None:
            notes.append(f"The {structure:g} ft limit is for accessory buildings. The code allows no ADU, so it is not an ADU height")
        return {t: None for t in ALL_TYPES}, notes
    internal_flag = _value(today, "envelope", "internal_uses_district_height")
    inner = principal if internal_flag is not False else structure
    if principal_hit and internal_flag is not False:
        citations["max_height_by_type.internal"] = _citation(*principal_hit)
    if inner is None and lot.get("zoning_district") and principal_hit is None:
        notes.append(f"District row for {lot['zoning_district']} not on file. Height of a unit in the house not known")

    def detached_for(t: str) -> Optional[float]:
        h = garage if (t in GARAGE_TYPES and garage is not None) else structure
        if no_adu:
            h = None  # under the bill the town's accessory cap is not an ADU rule
        if h is None and applies is False and principal is not None:
            h = principal
        if at_house:
            h = house if h is None else (min(h, house) if house else h)
        return h

    det = {t: detached_for(t) for t in DETACHED_TYPES}
    if applies is False and structure is None and principal is not None and not no_adu:
        notes.append(f"No accessory height rule reaches an ADU here. The district height ({principal:g} ft) is used for a detached unit")
        citations["max_height_by_type.detached_new"] = _citation(*principal_hit)
    if at_house and house is None:
        notes.append("A detached unit may not be taller than the house. House height unknown")
    if state and "max_height_ft" in limits:
        lim = limits["max_height_ft"]
        floor = lim["for_this_lot"]
        guessed = floor is None
        if guessed:
            floor = lim["value"]
        for t in DETACHED_TYPES:
            det[t] = floor if det[t] is None else max(det[t], floor)
        if guessed and any(det[t] == floor for t in DETACHED_TYPES):
            assumed.append("max_height_ft")
            notes.append(f"House height unknown. Used the bill's {lim['value']:g} ft floor. The town may cap it at the house height if that is lower")
        elif any(det[t] is not None and det[t] > floor for t in DETACHED_TYPES):
            notes.append(f"The town's own limit is above the bill's {floor:g} ft floor, so it stands")
        if no_adu and inner is None and principal is not None:
            inner = principal
    elif not any(by_type[t] in OK_PATHS for t in DETACHED_TYPES):
        pass  # no detached form allowed: no detached height line
    elif det["detached_new"] is None and not at_house:
        notes.append("No height number on file for a detached unit. Ask the zoning officer")
    out = {t: (inner if t in PRINCIPAL_TYPES else det[t]) for t in ALL_TYPES}
    for t in ALL_TYPES:
        if by_type[t] not in OK_PATHS:
            out[t] = None
    return out, notes


def _town_setbacks(picked: Picked, principal: dict[str, tuple[dict[str, Any], str]], limits: dict[str, Any],
                   state: bool, by_type: dict[str, str]) -> dict[str, dict[str, Optional[float]]]:
    """Yards per ADU type. A unit inside the house adds no structure. An attached unit takes the
    district (principal) yards. A detached unit takes the accessory yards (the headline values)."""
    out: dict[str, dict[str, Optional[float]]] = {}
    for t in ALL_TYPES:
        if t == "internal":
            out[t] = {k: None for k in YARDS}
            continue
        yards = {}
        for k in YARDS:
            acc = _value(picked, "envelope", k)
            if t == "attached":
                v = principal[k][0]["value"] if k in principal else acc
            else:
                v = acc
            if state and k in limits and limits[k]["mode"] == "at_most" and v is not None and t in NEW_STRUCTURE_TYPES:
                v = min(v, limits[k]["value"])
            yards[k] = v
        out[t] = yards
    return out


def _town_parking(picked: Picked, today: Picked, state: bool, out: dict[str, Any]
                  ) -> tuple[Optional[int], Optional[str]]:
    """Total spaces on the lot and the open reading. Under the bill the ADU needs no space, so the
    town total drops by the spaces it asked for the ADU."""
    total = _value(today, "parking", "total_on_site")
    reading = _value(today, "parking", "reading")
    if state and total is not None:
        town_adu = _value(today, "parking", "spaces_required")
        total = None if town_adu is None else int(total) - int(town_adu) + int(out["parking_spaces"] or 0)
    if out["parking_spaces"] is None and reading and not state:
        out["reasons"].append(f"Parking for the ADU is open: {reading}")
    return (int(total) if total is not None else None), reading


# ------------------------------------------------------------------ towns

def _town_key(text: Any) -> str:
    """'Upper Darby Twp' and 'upper darby township' -> 'upperdarby'."""
    words = re.sub(r"[^a-z0-9 ]", " ", str(text).lower().replace("-", " ")).split()
    drop = {"city", "borough", "boro", "township", "twp", "town", "municipality", "of", "the", "pa", "pennsylvania"}
    return "".join(w for w in words if w not in drop)


@functools.lru_cache(maxsize=1)
def _towns_index() -> dict[str, Any]:
    if not TOWNS_INDEX.exists():
        return {"towns": []}
    return json.loads(TOWNS_INDEX.read_text())


def list_places() -> list[dict[str, Any]]:
    """Every place in towns_index.json: name, county, GEOID, rule file, status and check date."""
    keys = ("name", "county", "type", "geoid", "file", "status", "checked_on", "population", "batch")
    return [{k: t.get(k) for k in keys} | {"has_file": _has_file(t)} for t in _towns_index().get("towns", [])]


def _has_file(town: dict[str, Any]) -> bool:
    return bool(town.get("file")) and (RULES_DIR / f"{town['file']}.json").exists()


def find_places(name: Any, county: Optional[str] = None) -> list[dict[str, Any]]:
    """Index entries that match a name, 'County: name', 'name, County', a GEOID or a file name.

    Largest population first. An exact Census name or a GEOID gives one entry.
    """
    towns = _towns_index().get("towns", [])
    text = str(name or "").strip()
    if re.fullmatch(r"42\d{8}", text):
        return [t for t in towns if t["geoid"] == text or text in (t.get("geoid_aliases") or [])]
    if any(t.get("file") == text for t in towns):
        return [t for t in towns if t.get("file") == text]
    for sep in (",", ":", "/"):
        if county is None and sep in text:
            left, right = (s.strip() for s in text.split(sep, 1))
            for c, n in ((right, left), (left, right)):
                c = re.sub(r"(?i)\s*county$", "", c)
                if any(_town_key(t["county"]) == _town_key(c) for t in towns):
                    county, text = c, n
                    break
    hits = [t for t in towns if _town_key(t["name"]) == _town_key(text)]
    if county:
        c = _town_key(re.sub(r"(?i)\s*county$", "", county))
        hits = [t for t in hits if _town_key(t["county"]) == c]
    exact = [t for t in hits if t["name"].lower() == text.lower()]
    return sorted(exact or hits, key=lambda t: -(t.get("population") or 0))


def describe_place(name: Any, county: Optional[str] = None) -> Optional[dict[str, Any]]:
    """One index entry with has_file and also_matches, or None when the town is not in the index."""
    hits = find_places(name, county)
    if not hits:
        return None
    out = dict(hits[0])
    out["has_file"] = _has_file(out)
    out["also_matches"] = [f"{t['name']} ({t['county']} County, {t['geoid']})" for t in hits[1:]]
    return out


def _place_file(place: str) -> str:
    """A rule file name for resolve(). Index names and GEOIDs map to the town file, or to default."""
    if (RULES_DIR / f"{place}.json").exists() and place not in NOT_RULE_FILES:
        return place
    town = describe_place(place)
    if town is None:
        return place  # load_rules raises a clear error
    return town["file"] if town["has_file"] else DEFAULT


# ------------------------------------------------------------------ CLI

def _cmd_validate() -> int:
    bad = 0
    for name in rule_names():
        errs = validate(json.loads((RULES_DIR / f"{name}.json").read_text()))
        print(f"{name}: {'ok' if not errs else f'{len(errs)} problems'}")
        for e in errs[:20]:
            print("  ", e)
        bad += bool(errs)
    return 1 if bad else 0


def _yes_no(text: Optional[str]) -> Optional[bool]:
    return None if text is None else text.lower() in ("1", "true", "yes", "y")


def _lot_from_args(a: argparse.Namespace) -> dict[str, Any]:
    return {
        "zoning_district": a.district,
        "overlays": None if a.overlays is None else [o for o in a.overlays.split(",") if o],
        "council_district": a.council,
        "ward": a.ward,
        "building_type": a.building_type,
        "lot_sqft": a.lot_sqft,
        "house_sqft": a.house_sqft,
        "house_height_ft": a.house_height_ft,
        "historic_individual": _yes_no(a.historic_individual),
        "historic_district": _yes_no(a.historic_district),
        "historic_contributing": _yes_no(a.historic_contributing),
        "has_alley": _yes_no(a.alley),
        "has_accessory_building": _yes_no(a.accessory_building),
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline.rules", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="check every rule file against the schema")
    r = sub.add_parser("resolve", help="print resolved rules for one lot as JSON")
    r.add_argument("--place", required=True)
    r.add_argument("--scenario", default="today", choices=SCENARIOS)
    r.add_argument("--district")
    r.add_argument("--overlays", help="comma list as in the city overlay layer, e.g. /NE,/VDO. Empty string means none")
    r.add_argument("--council", type=int)
    r.add_argument("--ward", type=int)
    r.add_argument("--building-type", help="detached, semi_detached, attached (rowhouse)")
    r.add_argument("--lot-sqft", type=float)
    r.add_argument("--house-sqft", type=float)
    r.add_argument("--house-height-ft", type=float)
    r.add_argument("--historic-individual", help="yes or no: designated under Chapter 14-1000")
    r.add_argument("--historic-district", help="yes or no: inside a designated historic district")
    r.add_argument("--historic-contributing", help="yes or no: Historical Commission rates it contributing")
    r.add_argument("--alley", help="yes or no")
    r.add_argument("--accessory-building", help="yes or no")
    a = p.parse_args(argv)
    if a.cmd == "validate":
        return _cmd_validate()
    print(json.dumps(resolve(a.place, a.scenario, _lot_from_args(a)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
