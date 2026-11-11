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
PATH_ORDER = ["by_right", "administrator_exception", "special_exception", "variance", "not_allowed"]
OK_PATHS = {"by_right", "administrator_exception", "special_exception"}

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
    return sorted(p.stem for p in RULES_DIR.glob("*.json") if p.stem != "schema")


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
        line = (f"No new detached ADU by right here. Every residential accessory structure is capped at "
                f"{cap[0]['value']:,.0f} sq ft and {_value(picked, 'envelope', 'max_height_ft'):,.0f} ft "
                f"({cap[0]['section']})")
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
    """Rule values for one lot under one scenario. See module docstring and README for keys."""
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
