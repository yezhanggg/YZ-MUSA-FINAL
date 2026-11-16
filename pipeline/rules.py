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
import datetime
import functools
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, TypeGuard

RULES_DIR = Path(__file__).resolve().parents[1] / "shared" / "rules"
SCHEMA_PATH = RULES_DIR / "schema.json"
DEFAULT = "default"
SCENARIOS = ("today", "local_reform", "state_reform")
LOCAL_REFORM: dict[str, list[str]] = {"philadelphia": ["bill250042"], "pittsburgh": [], "allentown": []}
STATE_REFORM = "hb2186"
ALL_TYPES = ["detached_new", "garage_conversion", "over_garage", "internal", "attached"]
NEW_STRUCTURE_TYPES = {"detached_new", "attached", "over_garage"}
PRINCIPAL_TYPES = {"internal", "attached"}
# From least to most demanding. An ADU type is "allowed" up to special_exception.
# conditional_use (governing body hearing, MPC 913.2) is used by town files only.
# not_addressed (pass 7, towns only): a form the code does not name (form.types_not_addressed). Not a firm no.
# in_conflict (pass 12, towns only): the code's own passages conflict on the form (form.types_in_conflict). Not settled.
PATH_ORDER = [
    "by_right",
    "administrator_exception",
    "special_exception",
    "conditional_use",
    "in_conflict",
    "not_addressed",
    "variance",
    "not_allowed",
]
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
OUTPUT_KEYS = [
    "allowed",
    "approval_path",
    "reasons",
    "types_allowed",
    *VALUE_KEYS,
    "citations",
    "assumed",
    # Added Nov 11, 2026. The keys above are unchanged.
    "approval_by_type",
    "max_height_by_type",
    "setback_rear_effective_ft",
    "rear_setback_rule",
    "state_limits",
    "fire_separation",
    "historic_path",
]

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
    "detached": "detached",
    "single": "detached",
    "single_family_detached": "detached",
    "semi_detached": "semi_detached",
    "semi-detached": "semi_detached",
    "semi": "semi_detached",
    "twin": "semi_detached",
    "attached": "attached",
    "row": "attached",
    "rowhouse": "attached",
    "row_house": "attached",
    "townhouse": "attached",
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


@functools.cache
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
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
        for e in Draft202012Validator(schema()).iter_errors(data)
    ]


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


def mini_validate(
    value: Any, sch: dict[str, Any], root: dict[str, Any] | None = None, where: str = "(root)"
) -> list[str]:
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


def _mini_object(value: dict[str, Any], sch: dict[str, Any], root: dict[str, Any], where: str) -> list[str]:
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


def _match_code(code: str | None, options: list[Any]) -> Any | None:
    if code is None:
        return None
    return next((o for o in options if _norm(o) == _norm(code)), None)


def _building_type(raw: str | None) -> str | None:
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
        reasons.append(
            "In a historic district. The historic path applies only if the Historical Commission "
            "rates the building contributing. Confirm with the Commission"
        )
    return False


def _historic_town(data: dict[str, Any], lot: dict[str, Any], reasons: list[str]) -> bool:
    """A town file with eligibility.historic_test uses its own test and the lot fact historic_resource.
    Without it, the Philadelphia inputs as in _historic."""
    test = _leaf(data, ("eligibility", "historic_test"))
    if not (_usable(test) and test.get("value")):
        return _historic(lot, reasons)
    words = str(test["value"]).rstrip(". ")
    have = lot.get("historic_resource")
    if have is True:
        reasons.append(f"Historic path used: {words} ({test['section']}). Confirm with the zoning officer")
        return True
    if have is None:
        reasons.append(f"The historic path applies only if: {words} ({test['section']}). Not known for this lot")
    return False


# ------------------------------------------------------------------ layering


def _usable(leaf: dict[str, Any] | None) -> TypeGuard[dict[str, Any]]:
    """A null marked unverified means 'not confirmed'. It never overrides anything."""
    return (
        leaf is not None and bool(leaf) and not (leaf.get("value") is None and leaf.get("confidence") == "unverified")
    )


def _leaf(data: dict[str, Any], path: Path_) -> dict[str, Any] | None:
    return (data.get(path[0]) or {}).get(path[1])


def _must_leaf(data: dict[str, Any], path: Path_) -> dict[str, Any]:
    """_leaf for a leaf the caller already knows is there."""
    leaf = _leaf(data, path)
    if leaf is None:
        raise KeyError(f"rule leaf {'.'.join(path)} is missing")
    return leaf


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
        leaf = _leaf(default, path)
        if path not in picked and _usable(leaf):
            picked[path] = (leaf, DEFAULT)


def _out_key(path: Path_) -> str:
    return next((k for k, p in VALUE_KEYS.items() if p == path), ".".join(path))


def _state_floor(data: dict[str, Any], path: Path_, lot: dict[str, Any]) -> float | None:
    """The number a state floor guarantees for this lot, or None when a lot fact is missing.

    Size: lesser of a share of the house and a fixed sq ft. Height: lesser of a
    fixed height and the house height.
    """
    value = _must_leaf(data, path)["value"]
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


def _apply_state(
    picked: Picked,
    data: dict[str, Any],
    source: str,
    lot: dict[str, Any],
    skip: set[Path_],
    limits: dict[str, Any],
    reasons: list[str],
) -> None:
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
        limits[key] = {
            "mode": mode,
            "value": leaf["value"],
            "for_this_lot": bound,
            "section": leaf["section"],
            "note": leaf.get("note"),
        }
        if path in skip:
            continue
        cur = picked.get(path)
        if bound is None:
            if cur is None or (cur[0].get("value") is not None and cur[0]["value"] < leaf["value"]):
                reasons.append(
                    f"{leaf.get('note') or key} A missing lot fact (house size or height) "
                    f"keeps the local value until it is known"
                )
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


def _active_overlays(bars: list[dict[str, Any]], lot: dict[str, Any], reasons: list[str]) -> set[str] | None:
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
            reasons.append(
                "Council district unknown. Overlays that follow council district lines may be missing "
                "from the overlay list. Check it"
            )
        return listed
    active = {
        "/" + _norm(b["overlay"])
        for b in bars
        if (council is not None and int(council) in b.get("council_districts", []))
        or (ward is not None and int(ward) in b.get("wards", []))
    }
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


def _pick(
    place: str, scenario: str, lot: dict[str, Any], historic: bool, limits: dict[str, Any], reasons: list[str]
) -> Picked:
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
    return {
        "section": leaf["section"],
        "url": leaf.get("url"),
        "verified_on": leaf.get("verified_on"),
        "confidence": leaf["confidence"],
        "source_file": source,
    }


def _checks(place: str, scenario: str) -> list[str]:
    # The top layer's checks only. A reform file restates the place checks it keeps,
    # so a check the reform removes (such as owner occupancy) is not shown.
    local, state = layers_for(place, scenario)
    return list(load_rules((local + state)[-1])["provenance"].get("checks", []))


def _type_reasons(picked: Picked, by_type: dict[str, str]) -> list[str]:
    out = []
    cap = picked.get(("envelope", "accessory_structure_max_sqft"))
    if cap and cap[0].get("value") is not None and by_type["detached_new"] not in OK_PATHS:
        height = _value(picked, "envelope", "max_height_ft")
        line = (
            f"No new detached ADU by right here. Every residential accessory structure is capped at "
            f"{cap[0]['value']:,.0f} sq ft"
            + (f" and {height:,.0f} ft" if height is not None else "")
            + f" ({cap[0]['section']})"
        )
        rule = picked.get(("eligibility", "existing_structure_only"))
        if rule and rule[0].get("value"):
            line += f", and the ADU must use an existing building ({rule[0]['section']})"
        out.append(line)
    yard = picked.get(("approval", "detached_in_yard_path"))
    if yard and by_type["detached_new"] == "administrator_exception":
        out.append(
            f"A new detached ADU in a side or rear yard needs an Administrator's Exception "
            f"({yard[0]['section']}). Not needed above an existing garage that abuts a way. Inside the house, attached, or a garage conversion is by right"
        )
    return out


def _heights(picked: Picked) -> tuple[dict[str, Any], tuple[dict[str, Any], str] | None]:
    structure = _value(picked, "envelope", "max_height_ft")
    principal = picked.get(DISTRICT_HEIGHT) if _value(picked, "envelope", "internal_uses_district_height") else None
    by_type = {t: (principal[0]["value"] if principal and t in PRINCIPAL_TYPES else structure) for t in ALL_TYPES}
    return by_type, principal


def _rear(out: dict[str, Any], lot: dict[str, Any]) -> tuple[float | None, str]:
    alley = lot.get("has_alley")
    if alley is True and out["setback_rear_alley_ft"] is not None:
        return out["setback_rear_alley_ft"], "alley"
    if alley is None:
        return out["setback_rear_ft"], "unknown_alley_used_no_alley_value"
    return out["setback_rear_ft"], "no_alley"


EXTRA_KEYS = ["rule_path_by_type", "lot_conditions_by_type", "citations_by_type"]
NO_OUTBUILDING = "No garage or outbuilding on this lot"


def resolve(place: str, scenario: str, lot: dict[str, Any], extra: bool = False) -> dict[str, Any]:
    """Rule values for one lot under one scenario. See module docstring and README for keys.

    place is a rule file name (philadelphia, pittsburgh, pa_lehigh_allentown). A town in
    towns_index.json may also be given by name or GEOID. A town without a file resolves
    on default.json, so every value is in "assumed".

    extra=True adds EXTRA_KEYS after the usual keys (the usual keys are unchanged):
    rule_path_by_type (the path per ADU type from the rules alone, before the lot's own facts such
    as having no garage), lot_conditions_by_type (the lot fact that changes a type's path) and
    citations_by_type (the section behind each type's path).
    """
    asked = place
    place = _place_file(place)
    if place.startswith("pa_") or (place == DEFAULT and asked != DEFAULT):
        out = _resolve_town(place, scenario, lot)
        return _with_extra(out, place, scenario, lot) if extra else out
    out = _resolve_city(place, scenario, lot)
    return _with_extra(out, place, scenario, lot) if extra else out


def _path_citation(
    place: str, scenario: str, lot: dict[str, Any], path: str, form: str | None = None
) -> dict[str, Any] | None:
    """The rule leaf behind an approval path value: a form's own path, then path, yard path, fallback."""
    data = load_rules(place)
    local, state = layers_for(place, scenario)
    paths = _leaf(data, ("approval", "form_paths"))
    for item in ((paths or {}).get("value") or []) if form and not state else []:
        if form in item["forms"] and item["path"] == path:
            return _citation(_leaf_from(item, paths or {}, path), place)
    for item in (_gate_paths(data, lot, False) + _gate_paths(data, lot, True)) if form and not state else []:
        if form in item["forms"] and item["path"] == path:  # pass 16: the gate whose path the form takes
            gates = _leaf(data, ("eligibility", "gates")) or {}
            return _citation(_leaf_from(item["gate"], gates, path), place)
    for name in reversed(local + state):
        layer = load_rules(name) if name != place else data
        for key in ("path", "detached_in_yard_path", "historic_path", "fallback_path", "unlisted_use_path"):
            leaf = _leaf(layer, ("approval", key))
            if _usable(leaf) and leaf.get("value") == path:
                return _citation(leaf, name)
    barred = _leaf(data, ("approval", "use_variance_barred"))
    if path == "not_allowed" and _usable(barred) and barred.get("value") is True:  # pass 11
        return _citation(barred, place)
    return None


def _with_extra(out: dict[str, Any], place: str, scenario: str, lot: dict[str, Any]) -> dict[str, Any]:
    """Adds EXTRA_KEYS. The rule path per type ignores has_accessory_building, which is a lot fact."""
    bare = {**lot, "has_accessory_building": None}
    base = (
        _resolve_town(place, scenario, bare)
        if place.startswith("pa_") or place == DEFAULT
        else _resolve_city(place, scenario, bare)
    )
    rule_paths = base["approval_by_type"]
    lot_cond = {
        t: NO_OUTBUILDING
        for t in ALL_TYPES
        if lot.get("has_accessory_building") is False and out["approval_by_type"][t] != rule_paths[t]
    }
    cites = {t: _path_citation(place, scenario, lot, rule_paths[t], t) for t in ALL_TYPES}
    return {**out, "rule_path_by_type": rule_paths, "lot_conditions_by_type": lot_cond, "citations_by_type": cites}


def _resolve_city(place: str, scenario: str, lot: dict[str, Any]) -> dict[str, Any]:
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
        "allowed": allowed,
        "approval_path": approval,
        "reasons": reasons
        + fails
        + _type_reasons(picked, by_type)
        + (_checks(place, scenario) if allowed else [])
        + _site_lines(place_rules, lot, types_allowed),
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


# ------------------------------------------------------------------ site rules (steep slope, landslide, undermined)
# site.steep_slopes rows in the two city files. A row is said, as a condition or a question and never as a
# bar, when the lot carries the fact it reads: slope_class (the terrain block's measured class) or a mapped
# area flag (steep_slope_area, landslide_area, undermined_area). A lot without these facts reads as before.

SLOPE_CLASSES = ("ordinary", "moderate", "steep")
SITE_AREAS = ("steep_slope_area", "landslide_area", "undermined_area")


def _site_row_met(row: dict[str, Any], lot: dict[str, Any]) -> bool:
    """True when the lot's facts say the row. A row needs one positive fact: a measured class in its list, or
    its mapped area true. An area that is false or unknown alone never says a row."""
    classes = row.get("slope_classes")
    if classes is not None and lot.get("slope_class") not in classes:
        return False
    area = row.get("area")
    if area is not None:
        if lot.get(area) not in row.get("area_is", [True]):
            return False
        if lot.get(area) is not True and classes is None:
            return False
    return classes is not None or (area is not None and lot.get(area) is True)


def _site_lines(data: dict[str, Any], lot: dict[str, Any], types_allowed: list[str]) -> list[str]:
    """The owner lines of site.steep_slopes for this lot, in file order, for the ADU forms allowed here."""
    leaf = _leaf(data, ("site", "steep_slopes"))
    if not _usable(leaf):
        return []
    out = []
    for row in leaf.get("value") or []:
        if row.get("forms") and not any(t in types_allowed for t in row["forms"]):
            continue
        if _site_row_met(row, lot):
            out.append(row["text"])
    return out


# ------------------------------------------------------------------ town resolver
# Town files (pa_*.json) and towns without a file resolve here. Philadelphia and Pittsburgh
# never come here, so their output is unchanged. A town result has OUTPUT_KEYS + TOWN_KEYS.

TOWN_KEYS = [
    "adu_status",
    "adu_term",
    "conditions",
    "approval_by_district",
    "district_path",
    "fallback",
    "max_share_by_type",
    "parking_total_on_site",
    "parking_reading",
    # Added in pass 3.
    "scope",
    "conditions_overridden",
    "max_size_by_type",
    "setbacks_by_type",
    "alternatives",
    # Added in pass 4: "conditional_on_reading" when the path holds only under one reading of the code.
    "approval_qualifier",
    # Added in pass 4: the path to ask for when the code has no ADU rule (a use not listed).
    "path_to_ask",
    # Added in pass 5.
    "form_labels",
    "yard_tiers",
    # Added in pass 6.
    "max_stories_by_type",
    "adu_status_by_form",
    "size_rule_by_type",
    # Added in pass 7: the lot or house facts that decide a bar but were not given.
    "depends_on",
]
NO_ADU_STATUSES = {"not_addressed", "prohibited"}
# Pass 19: parking.fraction_rounding, the rule the code states for a fraction of a space: the words, and the smallest
# fraction that counts as one more space (0: any fraction).
FRACTION_RULES: dict[str, tuple[str, float]] = {
    "any_fraction_counts": ("any fraction of a space counts as one", 0.0),
    "quarter_or_more_counts": ("a fraction of one quarter or more counts as one", 0.25),
    "half_or_more_counts": ("a fraction of one half or more counts as one", 0.5),
}
# Towns whose resolver output feeds published lot records (pipeline/build_lots.py), when a change to an
# output key that would change those records is held back for them until the lot data is rebuilt.
# Pass 8 lifted the pass 7 hold on Allentown (no ADU parking count where no ADU is allowed).
# Pass 10: the ten lot towns rebuilt on Nov 14. Pass 10 owner-sentence fixes that would change what the lot build
# keeps for them (no separation where no detached form is allowed, a condition gate whose lot fact is unknown,
# ".." in a sentence) waited for their next planned rebuild. Emptied at that rebuild (Nov 15, spot cover rebuild).
# Keep the set: a later pass can hold a change back for lot towns again.
LOT_RECORD_TOWNS: set[str] = set()
# Pass 11 holds only its districts_in_doubt fix (the path to ask, qualified, not a variance; named_by wording) for the
# ten lot towns: State College area (GWC) and Narberth (5A, 5B) use districts_in_doubt. A set of its own, so the pass
# 10 fixes lifted at the Nov 15 rebuild stay lifted. Lifted on Nov 15 (rules-only lot refresh) for the nine towns
# whose lot records it leaves as they are, and on Nov 16 for Narberth, whose tracts were rebuilt: its 9 lots in 5A and
# 5B turned from not allowed to by right (qualified). Keep the set for a later pass.
DOUBT_HOLD_TOWNS: set[str] = set()
# Pass 12 held its owner-sentence fixes for the ten lot towns (the "ADUs per lot" line on a lot with no ADU rule, the
# height cap line without a semicolon). Emptied on Nov 15: the lot records of Allentown and Phoenixville were
# refreshed to the new text (rules only); the other towns' records do not change. Keep the set for a later pass.
PASS12_HOLD_TOWNS: set[str] = set()
# Pass 13 held one owner-sentence fix for the ten lot towns: the ADU status condition as a sentence ("The code's ADU
# status is family only. ...") in place of "family only. ...". The lot build keeps that condition as a reason line.
# Emptied on Nov 16: the lot records of the lot towns were refreshed to the new text. Keep the set for a later pass.
PASS13_HOLD_TOWNS: set[str] = set()
# Pass 14 held its owner-sentence fixes that reach stored lot records, for the same ten lot towns: a services row
# with its figures in units and the missing service named ("min lot 43,560 sq ft ... Depends on whether the lot has
# public sewer (public_sewer)" in place of "min lot 43,560 ... public sewer and water (public_sewer, public_water)"),
# an overlay name said once ("the Historic Resource Overlay", not "... Overlay overlay"), and the bill line's kept
# town rules as sentences ("... (660-28D). Building coverage 50%" in place of ". building coverage 50%"). Emptied on
# Nov 16 with PASS13_HOLD_TOWNS (lot records refreshed). Keep the set for a later pass.
PASS14_HOLD_TOWNS: set[str] = set()
# Pass 15 holds its owner-sentence fix that can reach stored lot records, for the ten lot towns: a services row whose
# sentence is the same as one already said is said once (Upper Dublin A, whose two "public sewer or public water, not
# both" rows read alike when the services are not given). Emptied on Nov 16 (lot data 9): the lot records of the lot
# towns were refreshed (no stored record changed by it). Keep the set for a later pass.
PASS15_HOLD_TOWNS: set[str] = set()
# Pass 16 holds its fixes that can reach stored lot records, for the ten lot towns: the "No height number on file for
# a detached unit" line dropped (and the cap cited) where the accessory building cap that binds the unit gives the
# height, and the yards line naming every gate whose own figures replace the district's (not only the first). Emptied
# on Nov 16 (lot data 9) with PASS15_HOLD_TOWNS (no stored record changed by it). Keep the set for a later pass.
PASS16_HOLD_TOWNS: set[str] = set()
# Pass 17 holds its changes that can reach stored lot records, for the ten lot towns: a lot with no zoning district
# resolving as the path to ask, qualified (not a variance with "zoned unknown"), and the lot build keeping the
# resolver's approval_qualifier and max_share_by_type in each scenario's rules (pipeline/build_lots.py). Emptied on
# Nov 16 (lot data 9): every lot town record gained max_share_by_type (and approval_qualifier where the path is
# qualified), and the tracts of the 13 lots with no district were rebuilt (variance to the qualified path). Keep the
# set for a later pass.
PASS17_HOLD_TOWNS: set[str] = set()
# Pass 18 holds its change that can reach stored lot records, for the ten lot towns until their next lot rebuild: a
# gate's bar line drops the condition's own closing full stop before its sections ("... no other use (330-23B). Not
# allowed here: ..." in place of "... no other use. (330-23B). Not allowed here: ..."). The lot build keeps that
# line as a reason. Every other pass 18 change is to keys the lot record does not keep (alternatives, adu_status,
# conditions) or to fields no lot town file uses.
PASS18_HOLD_TOWNS: set[str] = {
    "pa_lehigh_allentown",
    "pa_centre_college",
    "pa_chester_west_chester",
    "pa_chester_phoenixville",
    "pa_chester_west_vincent",
    "pa_chester_malvern",
    "pa_chester_east_brandywine",
    "pa_montgomery_lower_merion",
    "pa_montgomery_narberth",
    "pa_montgomery_upper_dublin",
}
# Pass 19 holds nothing: no pass 19 change reaches a stored lot record of the ten lot towns. Its new fields
# (size.max_share_is_less_than, parking.spaces_rate, parking.fraction_rounding, gates[].waives_figures, the gate test
# top_of_bank_ft_over) are in no lot town file, and the planned-development changes need in_planned_development,
# which the lot build never gives. The proof (every stored record rebuilt by the code now, byte for byte) found no
# change. Keep the set for a later pass.
PASS19_HOLD_TOWNS: set[str] = set()
NO_DETACHED_HEIGHT = "No height number on file for a detached unit. Ask the zoning officer"
# Pass 7: tests on the house (and the services), not the lot. The lot facts that answer them, in plain words.
HOUSE_TESTS: dict[str, str] = {
    "house_sqft_at_least": "the house's floor area (house_sqft)",
    "house_sqft_over": "the house's floor area (house_sqft)",
    "house_built_before": "the year the house was built (house_year_built)",
    "accessory_building_built_before": "the year the accessory building was built (accessory_building_year_built)",
    "house_exists": "whether a lawful house already stands on the lot (house_exists)",
    "public_sewer": "whether the lot has public sewer (public_sewer)",
    "public_water": "whether the lot has public water (public_water)",
    "lot_width_at_least": "the lot width (lot_width_ft)",
    "lot_width_below": "the lot width (lot_width_ft)",
    "designated_on_plan": "whether the lot is designated on the plan the code names (designated_on_plan)",
    # Pass 9: a mapped area that is not a zoning district (a growth boundary)
    "in_growth_area": "whether the lot is inside the mapped growth area (in_growth_area)",
    # Pass 10: a planned residential or cluster development whose own figures replace the district's
    "in_planned_development": "whether the lot is in a planned or cluster development the code names (in_planned_development)",
}
LOT_TESTS: dict[str, str] = {
    "has_alley": "whether the lot has an alley (has_alley)",
    "has_accessory_building": "whether the lot has an accessory building (has_accessory_building)",
    # Pass 13: the inverse, a rule that holds only on a lot with no accessory building ("Accessory structures shall
    # not be permitted"). Met when the lot has none
    "no_accessory_building": "whether the lot has an accessory building (has_accessory_building)",
    "lot_sqft_at_least": "the lot area (lot_sqft)",
    "lot_sqft_below": "the lot area (lot_sqft)",
    # Pass 9: a test on the parent tract, not the lot. A lot at least as large settles it; a smaller one does not
    "tract_sqft_at_least": "the parent tract area (tract_sqft)",
    "tract_sqft_below": "the parent tract area (tract_sqft)",
    # Pass 19: how far the new building stands landward of the top of bank of a watercourse (Canonsburg 99-23D)
    "top_of_bank_ft_over": "how far the new building stands from the top of bank of the watercourse (top_of_bank_ft)",
}
SIZE_PATHS = [
    ("size", k)
    for k in (
        "max_sqft",
        "max_share_of_house",
        "max_sqft_internal",
        "max_share_internal",
        "max_sqft_accessory_building",
        "max_share_accessory_building",
        "max_sqft_by_form",
        "max_share_by_form",
    )
]
UTILITY_FIELDS = (
    "min_lot_sqft",
    "setback_front_ft",
    "setback_side_ft",
    "setback_rear_ft",
    "principal_max_height_ft",
    "max_building_coverage",
    # Pass 9: density on such a lot, and an accessory building (a detached unit) on it
    "lot_area_per_unit_sqft",
    "accessory_setback_front_ft",
    "accessory_setback_side_ft",
    "accessory_setback_rear_ft",
    "accessory_max_height_ft",
    "accessory_max_stories",
    # Pass 10: impervious cover on such a lot (districts.<code>.max_impervious_coverage)
    "max_impervious_coverage",
    # Pass 11: side yards for both sides together on such a lot (uneven sides: the one-side minimum and the total)
    "setback_sides_total_ft",
)
# Pass 9: the lot facts a utility row can name. in_growth_area is a mapped area that is not a district.
ROW_FACTS = {
    "public_sewer": "public sewer",
    "public_water": "public water",
    "in_growth_area": "the lot is inside the mapped growth area",
}
DETACHED_TYPES = ["detached_new", "garage_conversion", "over_garage"]
GARAGE_TYPES = {"garage_conversion", "over_garage"}
YARDS = ("setback_front_ft", "setback_side_ft", "setback_rear_ft")
# Town conditions HB 2186 would override (6305: no owner occupancy or family rule, ADUs do not count
# toward density, one ADU per residential lot by right).
BILL_OVERRIDES = {
    "adu_status",
    "family",
    "age",
    "care",
    "owner_occupancy",
    "sponsor",
    "lot_area_per_unit",
    "occupancy",
    "lot_size",
    "existing_structure",
    "district",
    "building_type",
    "scope",
}
BILL_NOTE = "Would no longer apply under HB 2186. The bill is not law"
# Pass 8: district figures set by building type (districts.<code>.<key>), replacing the row's figure.
BY_TYPE_FIGURES = {"min_lot_sqft_by_type": "min_lot_sqft", "lot_area_per_unit_by_type": "lot_area_per_unit_sqft"}
# Pass 8: author bookkeeping in a note (dates added, second checks, who read it). Never part of an owner sentence.
BOOKKEEPING = [
    (re.compile(r"\s*\bAdded (?:on )?\d{4}-\d{2}-\d{2}[^.]*\."), ""),
    (re.compile(r"\s*[^.]*\bpending a second (?:check|reading)[^.]*\."), ""),
    (re.compile(r"\s*\b(?:Read|Checked) (?:on )?\d{4}-\d{2}-\d{2}\."), ""),
    (re.compile(r"\s*\bEarlier reading [^.]*\."), ""),
    (re.compile(r",? per the review(?=[,.])"), ""),
    (re.compile(r" read by the reviewer\b"), ""),
]
# Pass 10: a note that ends with a period, joined with ". ", gives "..". Never an ellipsis ("..." stays).
# Pass 14: an area figure in acres at the head of a services row note ("One acre", "Two acres, 150 ft wide").
ACRES = {"one": 1, "an": 1, "half an": 0.5, "two": 2, "three": 3, "four": 4, "five": 5, "1": 1, "2": 2, "3": 3, "5": 5}
ACRE_HEAD = re.compile(r"^(one|an|half an|two|three|four|five|1|2|3|5) acres?\b[ ,.]*", re.I)
# Pass 15: an accessory_rules_where item whose where text names the building itself ("a detached accessory building
# over 600 sq ft: ...", "any detached accessory structure: ...")
NAMES_BUILDING = re.compile(r"^(?:an?|any|every|each)\b[^:]*\b(?:building|structure|garage)s?\b", re.I)
# Pass 17: a where text that opens with the buildings it covers ("garages and carports accessory to ...", "Storage
# sheds: ...") or its own heading ("In a rear yard: ...", "Houses in RA ...: ..."). "An accessory building" is not put
# before it.
LEADS_ITSELF = re.compile(r"^(?:[A-Z]|(?:private )?(?:garages?|sheds?|carports?|storage|accessory)\b)")
SENTENCE_END = re.compile(r"\.\s+(?=[A-Z'])")


def _acc_where_figs(where_txt: str, figs: list[str]) -> str:
    """Pass 17: an envelope.accessory_rules_where item with figures. "An accessory building" goes before a where text
    that does not name the building or lead itself. The figures follow the first sentence, after a colon, unless that
    sentence already has one. Then they close the text as a sentence of their own."""
    w = where_txt.strip().rstrip(".")
    own = bool(NAMES_BUILDING.match(w) or LEADS_ITSELF.match(w))
    lead = w[:1].upper() + w[1:] if own else f"An accessory building {w}"
    parts = SENTENCE_END.split(lead, maxsplit=1)
    first, rest = parts[0], (parts[1] if len(parts) > 1 else "")
    if ":" in first:
        return f"{lead}. Figures: {', '.join(figs)}"
    return f"{first}: {', '.join(figs)}" + (f". {rest}" if rest else "")


# Pass 14: an overlay whose name ends in "Overlay" said once ("the Historic Resource Overlay overlay").
OVERLAY_TWICE = re.compile(r"\b(Overlay|overlay|OVERLAY) overlay\b")
DOUBLE_STOP = re.compile(r"(?<![.\s])\.\.(?!\.)")


def _leaf_from(item: dict[str, Any], parent: dict[str, Any], value: Any) -> dict[str, Any]:
    """A leaf built from a list item (district path or gate), with the parent leaf's date and confidence."""
    return {
        "value": value,
        "section": item.get("section") or parent["section"],
        "url": item.get("url") or parent.get("url"),
        "verified_on": parent.get("verified_on"),
        # pass 10: a list item (a gate) may carry its own confidence
        "confidence": item.get("confidence") or parent["confidence"],
        "note": item.get("note"),
    }


def _district_row(place: dict[str, Any], lot: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    code = _match_code(lot.get("zoning_district"), list((place.get("districts") or {}).keys()))
    row = ((place.get("districts") or {}).get(code) or {}) if code else {}
    hit = _utility_row(row, lot)
    btype = _building_type(lot.get("building_type"))
    by_type = {
        field: row[key]
        for key, field in BY_TYPE_FIGURES.items()
        if _usable(row.get(key))
        and isinstance(row[key].get("value"), dict)
        and row[key]["value"].get(btype) is not None
    }
    if hit is None and by_type:  # pass 8: the lot's house type picks the figure (with public sewer and water)
        row = dict(row)
        for field, leaf in by_type.items():
            row[field] = {**leaf, "value": leaf["value"][btype]}
    if hit is None:
        return code, _impervious_by_lot(row, lot)
    item, parent = hit  # the row for the lot's services replaces the public sewer and water figures
    merged = dict(row)
    for f in UTILITY_FIELDS:
        if f in item:
            merged[f] = _leaf_from(item, parent, item[f])
    # pass 16: a services row's own impervious figure stays (it is the figure the file states for those services)
    return code, merged if "max_impervious_coverage" in item else _impervious_by_lot(merged, lot)


def _lot_bounds(it: dict[str, Any]) -> str:
    """Pass 16: a lot size tier's bounds in words (lot_sqft_over, lot_sqft_at_least, lot_sqft_below,
    lot_sqft_at_most), as size.max_sqft_by_lot_size has them."""
    bounds = []
    if it.get("lot_sqft_over") is not None:
        bounds.append(f"over {_acres(it['lot_sqft_over'])}")
    if it.get("lot_sqft_at_least") is not None:
        bounds.append(f"of at least {_acres(it['lot_sqft_at_least'])}")
    if it.get("lot_sqft_below") is not None:
        bounds.append(f"under {_acres(it['lot_sqft_below'])}")
    if it.get("lot_sqft_at_most") is not None:
        bounds.append(f"of {_acres(it['lot_sqft_at_most'])} or less")
    return f"a lot {' and '.join(bounds) if bounds else 'of any size'}"


def _lot_tier(items: list[dict[str, Any]], area: float | None) -> dict[str, Any] | None:
    """Pass 16: the first tier whose lot size bounds hold for the lot (None without the area or in a gap)."""
    if area is None:
        return None
    for it in items:
        if (
            (it.get("lot_sqft_over") is None or area > it["lot_sqft_over"])
            and (it.get("lot_sqft_at_least") is None or area >= it["lot_sqft_at_least"])
            and (it.get("lot_sqft_below") is None or area < it["lot_sqft_below"])
            and (it.get("lot_sqft_at_most") is None or area <= it["lot_sqft_at_most"])
        ):
            return it
    return None


def _impervious_by_lot(row: dict[str, Any], lot: dict[str, Any]) -> dict[str, Any]:
    """Pass 16: districts.<code>.max_impervious_by_lot_size, impervious cover that changes with lot size. The tier for
    the lot replaces the row's max_impervious_coverage. A services row that states its own figure keeps it (the
    caller). Without the lot area, or in a gap the code leaves, the row's own figure stays."""
    leaf = row.get("max_impervious_by_lot_size")
    if not (_usable(leaf) and leaf.get("value")):
        return row
    it = _lot_tier(leaf["value"], lot.get("lot_sqft"))
    if it is None:
        return row
    return {
        **row,
        "max_impervious_coverage": {
            **{k: v for k, v in leaf.items() if k != "value"},
            "value": it["max_impervious"],
            "section": f"{leaf['section']}, for {_lot_bounds(it)}",
        },
    }


DISPUTE_WORDS: dict[str, tuple[str, str]] = {
    "min_lot_sqft": ("minimum lot", "sqft"),
    "setback_front_ft": ("front yard", "ft"),
    "setback_side_ft": ("side yard", "ft"),
    "setback_rear_ft": ("rear yard", "ft"),
    "max_building_coverage": ("building coverage", "share"),
    "max_impervious_coverage": ("impervious cover", "share"),
    "principal_max_height_ft": ("height", "ft"),
    "principal_max_stories": ("stories", "stories"),
}


def _dispute_fig(field: str, v: float) -> str:
    word, unit = DISPUTE_WORDS[field]
    if unit == "share":
        return f"{word} {v:.0%}"
    if unit == "sqft":
        return f"{word} {v:,.0f} sq ft"
    if unit == "stories":
        return f"{v:g} stories"
    return f"{word} {v:g} ft"


def _figures_in_dispute(row: dict[str, Any], lot: dict[str, Any]) -> str | None:
    """Pass 16: districts.<code>.figures_in_dispute, the row's figures another reading of the code puts at other values
    (a district that permits another district's uses 'as regulated therein' while its own chapter sets other figures).
    The sentence gives both sets of figures, only for fields the row shows a figure for, and says the row is not
    settled."""
    leaf = row.get("figures_in_dispute")
    if not (_usable(leaf) and isinstance(leaf.get("value"), dict)):
        return None
    pairs = []
    for field, other in leaf["value"].items():
        shown = row.get(field)
        if field not in DISPUTE_WORDS or other is None or not (_usable(shown) and shown.get("value") is not None):
            continue
        if shown["value"] != other:
            pairs.append((field, shown["value"], other))
    if not pairs:
        return None
    d = lot.get("zoning_district")
    line = (
        f"Figures for {d} are not settled ({leaf['section']}). {leaf['note'].rstrip('.')}. Shown: "
        + ", ".join(_dispute_fig(f, a) for f, a, _ in pairs)
        + ". The other reading: "
        + ", ".join(_dispute_fig(f, b) for f, _, b in pairs)
        + ". Ask the zoning officer which governs"
    )
    return line


def _impervious_tier_line(row: dict[str, Any], lot: dict[str, Any]) -> str | None:
    """Pass 16: when the tier for the lot is not known (no lot area, or a gap the code leaves), the tiers in words
    and which figure is shown."""
    leaf = row.get("max_impervious_by_lot_size")
    if not (_usable(leaf) and leaf.get("value")):
        return None
    area = lot.get("lot_sqft")
    if _lot_tier(leaf["value"], area) is not None:
        return None
    tiers = ", ".join(f"{it['max_impervious']:.0%} on {_lot_bounds(it)}" for it in leaf["value"])
    line = f"Impervious cover for {lot.get('zoning_district')} depends on lot size: {tiers} ({leaf['section']})"
    base = row.get("max_impervious_coverage")
    shown = (
        f", so the district's base figure of {base['value']:.0%} is shown"
        if _usable(base) and base.get("value") is not None
        else ", so no figure is shown"
    )
    if area is None:
        return line + ". The lot size was not given" + shown
    return line + f". The code gives no figure for a lot of {area:,.0f} sq ft" + shown + ". Ask the zoning officer"


def _utility_match(item: dict[str, Any], lot: dict[str, Any]) -> bool | None:
    """True when the lot's services match the item, None when a fact it names is not known."""
    out: bool | None = True
    for fact in ROW_FACTS:
        want = item.get(fact)
        if want is None:
            continue
        have = lot.get(fact)
        if have is None:
            out = None
        elif bool(have) != bool(want):
            return False
    return out


def _utility_row(row: dict[str, Any], lot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """districts.<code>.utility_rows: the item that fits the lot's public sewer and water, when both are known."""
    leaf = row.get("utility_rows")
    if not (_usable(leaf) and leaf.get("value")):
        return None
    for item in leaf["value"]:
        if _utility_match(item, lot) is True:
            return item, leaf
    return None


def _district_path(place: dict[str, Any], lot: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
    """The approval path for the lot's district, when the file sets one by district."""
    code, row = _district_row(place, lot)
    if _usable(row.get("adu_path")) and row["adu_path"].get("value"):
        return row["adu_path"], f"#districts.{code}.adu_path"
    leaf = _leaf(place, ("approval", "district_paths"))
    if leaf is None:
        return None
    for item in leaf.get("value") or []:
        if _match_code(lot.get("zoning_district"), item["districts"]) is not None:
            hit = _leaf_from(item, leaf, item["path"])
            if item.get("term"):
                hit["term"] = item["term"]
            return hit, "#approval.district_paths"
    return None


def _scope(data: dict[str, Any], lot: dict[str, Any]) -> dict[str, Any]:
    """Where the ADU rule reaches. in_scope is None when the file has no scope or the district is unknown."""
    leaf = _leaf(data, ("adu", "scope_districts"))
    use = _leaf(data, ("adu", "scope_by_use"))
    use = use if _usable(use) and use.get("value") else None
    districts = (leaf or {}).get("value") or (use["value"]["permitted_in"] if use else None) or None
    if not districts or (leaf is None and use is None):
        return {"districts": None, "in_scope": None, "status_outside": None, "section": None}
    outside = (_leaf(data, ("adu", "status_outside")) or {}).get("value") or "not_addressed"
    d = lot.get("zoning_district")
    in_scope = None if d is None else _match_code(d, districts) is not None
    out = {
        "districts": districts,
        "in_scope": in_scope,
        "status_outside": outside,
        "section": (leaf or use or {})["section"],
    }
    by_d = _leaf(data, ("adu", "status_outside_by_district"))
    for item in (by_d or {}).get("value") or [] if in_scope is False else []:
        if _match_code(d, item["districts"]) is not None:  # pass 8: the status outside the scope in this district
            out["status_outside"] = item["status"]
            out["outside_leaf"] = _leaf_from(item, by_d or {}, item["status"])
            break
    doubt = _leaf(data, ("eligibility", "districts_in_doubt"))
    if in_scope is False and _usable(doubt) and _match_code(d, (doubt or {}).get("value") or []) is not None:
        # pass 8: a district in doubt is "ask", never "not addressed" (Upper Providence MH)
        out["in_scope"] = None
        out["in_doubt"] = True
        return out
    if use and in_scope is False and _match_code(d, use["value"].get("not_permitted_in") or []) is None:
        # pass 8: the rule reaches wherever the use is permitted, and this district's list was not read
        out["in_scope"] = None
        out["use_open"] = use
        # pass 9: read, and it does not name the use (while it permits a related one): not settled, never "not on file"
        out["use_read"] = _match_code(d, use["value"].get("read_not_named") or []) is not None
    return out


def _scope_line(scope: dict[str, Any], lot: dict[str, Any], with_section: bool) -> str:
    """Where the ADU rule reaches, and the status here when the lot is outside it."""
    sec = f" ({scope['section']})" if with_section else ""
    use = scope.get("use_open")
    if use and scope.get("use_read"):  # pass 9: the district's use list was read and does not name the use
        u = use["value"]["use"]
        return (
            f"The ADU rule reaches every district where a {u} is a permitted use ({use['section']}). "
            f"{lot.get('zoning_district')}'s use list was read and does not name a {u}. Whether the rule reaches "
            f"{lot.get('zoning_district')} is not settled. Ask the zoning officer"
        )
    if use:  # pass 8: the rule reaches wherever a use is permitted
        u = use["value"]["use"]
        return (
            f"The ADU rule reaches every district where a {u} is a permitted use ({use['section']}). Read so far: "
            f"{', '.join(scope['districts'])}. Whether {lot.get('zoning_district')} permits a {u} is not on file. "
            f"Allowed only if it does. Ask the zoning officer"
        )
    if scope.get("in_doubt"):  # pass 8
        return (
            f"The ADU rule reaches {', '.join(scope['districts'])}{sec}. Whether it reaches "
            f"{lot.get('zoning_district')} is in doubt. Ask the zoning officer"
        )
    hit = scope.get("outside_leaf")
    if hit:  # pass 8: the status outside the scope differs by district
        return (
            f"The ADU rule reaches only {', '.join(scope['districts'])}{sec}. In {lot.get('zoning_district')} the code's "
            f"status is {scope['status_outside'].replace('_', ' ')} ({hit['section']})"
        )
    if with_section:
        return (
            f"The ADU rule reaches only {', '.join(scope['districts'])}{sec}. "
            f"Elsewhere: {scope['status_outside'].replace('_', ' ')}"
        )
    return (
        f"The ADU rule reaches only {', '.join(scope['districts'])}. Elsewhere the code's status is "
        f"{scope['status_outside'].replace('_', ' ')}"
    )


def _outside_scope_data(
    data: dict[str, Any], scope: dict[str, Any] | None = None, lot: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The file as it reads for a lot outside the ADU scope: no ADU numbers, the unlisted-use path or the fallback.
    A district with its own status outside the scope (adu.status_outside_by_district) takes that status."""
    keep: dict[str, Any] = {k: data[k] for k in ("provenance", "envelope", "coverage", "districts") if k in data}
    appr = data.get("approval") or {}
    unlisted_ok = _usable(appr.get("unlisted_use_path")) and (lot is None or _unlisted_here(data, lot))  # pass 9
    path = appr.get("unlisted_use_path") if unlisted_ok else appr.get("fallback_path")
    approval = {
        k: appr[k]
        for k in ("fallback_path", "unlisted_use_path", "unlisted_use_districts", "unlisted_use_scope", "alternatives")
        if k in appr
    }
    if path:
        approval["path"] = path
    adu = dict(data.get("adu") or {})
    # pass 10: a form status (adu.status_by_form) is part of the ADU rule. Outside the rule's districts every form
    # reads as the status outside (not addressed), never the in-scope bar
    adu.pop("status_by_form", None)
    if adu.get("status_outside"):
        adu["status"] = adu["status_outside"]
    if scope and scope.get("outside_leaf"):
        adu["status"] = scope["outside_leaf"]
    return {**keep, "approval": approval, "adu": adu}


def _apply_district_town(
    picked: Picked,
    place: dict[str, Any],
    source: str,
    lot: dict[str, Any],
    principal: dict[str, tuple[dict[str, Any], str]],
) -> None:
    """District values. District yards go to `principal` (attached units). They fill the accessory
    yards only where the file has none, or when district yards bind accessory buildings. A null in
    the row never wipes a value."""
    code, entry = _district_row(place, lot)
    if not code:
        return
    where = f"{source}#districts.{code}"
    bind = (_leaf(place, ("envelope", "district_yards_bind_accessory")) or {}).get("value") is True
    semi = entry.get("setback_side_semi_ft")
    btype = _building_type(lot.get("building_type"))
    use_semi = btype == "semi_detached" and _usable(semi) and semi.get("value") is not None
    for k in YARDS:  # accessory yards set for this district win for a detached unit
        acc = entry.get(f"accessory_{k}")
        if _usable(acc) and acc.get("value") is not None:
            picked[("envelope", k)] = (acc, f"{where}.accessory_{k}")
    for field, path in {
        **DISTRICT_FIELDS,
        "principal_max_height_ft": DISTRICT_HEIGHT,
        "separation_ft": ("envelope", "separation_ft"),
        # pass 10: the district's impervious cover (buildings and paving together), its own line
        "max_impervious_coverage": ("coverage", "max_impervious"),
    }.items():
        leaf = semi if (field == "setback_side_ft" and use_semi) else entry.get(field)
        yard_where = where
        by_t = entry.get(f"{field}_by_type") if field in YARDS else None
        if _usable(by_t) and isinstance(by_t.get("value"), dict) and by_t["value"].get(btype) is not None:
            # pass 13: a yard set by building type in the district row (a twin's own front and rear yards)
            leaf = {**by_t, "value": by_t["value"][btype]}
            yard_where = f"{where}.{field}_by_type.{btype}"
        if not _usable(leaf):
            continue
        if field in YARDS and leaf.get("value") is not None:
            principal[field] = (leaf, yard_where)
            own = picked.get(path)
            if own and own[0].get("value") is not None and (not bind or "accessory_" in own[1]):
                continue  # an accessory yard in the file wins for a detached unit
        if leaf.get("value") is None and (picked.get(path) or ({}, ""))[0].get("value") is not None:
            continue
        picked[path] = (leaf, yard_where)
    abut = entry.get("yards_abutting_residential_ft")  # pass 18: side and rear yards only where the lot abuts R
    fact = lot.get("abuts_residential_district")
    if _usable(abut) and abut.get("value") is not None and fact is not None:
        for k in ("setback_side_ft", "setback_rear_ft"):
            if k not in principal:  # a figure of the row's own wins
                principal[k] = (
                    {**abut, "value": abut["value"] if fact else 0},
                    f"{where}.yards_abutting_residential_ft",
                )
    by_type = entry.get("max_building_coverage_by_type")
    if _usable(by_type) and isinstance(by_type.get("value"), dict) and by_type["value"].get(btype) is not None:
        # Coverage set by building type: the lot's house type picks the share
        picked[("coverage", "max_building_coverage")] = (
            {**by_type, "value": by_type["value"][btype]},
            f"{where}.max_building_coverage_by_type.{btype}",
        )
    total = entry.get("setback_sides_total_ft")  # pass 9: side yards only as a total for both sides
    side = entry.get("setback_side_ft")
    if _usable(total) and total.get("value") is not None and not (_usable(side) and side.get("value") is not None):
        none_leaf = {**total, "value": None}
        principal["setback_side_ft"] = (none_leaf, f"{where}.setback_sides_total_ft")
        if _value(picked, "envelope", "setback_side_ft") is None:  # no single side figure, never the default
            picked[("envelope", "setback_side_ft")] = (none_leaf, f"{where}.setback_sides_total_ft")
    acc_h = entry.get("accessory_max_height_ft")  # pass 9: from a utility row (accessory building on such a lot)
    if _usable(acc_h) and acc_h.get("value") is not None:
        own_h = _value(picked, "envelope", "max_height_ft")
        if own_h is None or acc_h["value"] < own_h:
            picked[("envelope", "max_height_ft")] = (acc_h, f"{where}.accessory_max_height_ft")
    # Pass 12: the general accessory building height cap set by district (it replaces the town-wide figure there)
    acc_cap_h = entry.get("accessory_structure_max_height_ft")
    if _usable(acc_cap_h) and acc_cap_h.get("value") is not None:
        picked[("envelope", "accessory_structure_max_height_ft")] = (
            acc_cap_h,
            f"{where}.accessory_structure_max_height_ft",
        )
    # Pass 15: ADUs per lot set by district (one in R-C and R-S, two in R-U), replacing use.max_adus there
    n_adus = entry.get("max_adus")
    if _usable(n_adus) and n_adus.get("value") is not None:
        picked[("use", "max_adus")] = (n_adus, f"{where}.max_adus")
    # Pass 15: the size above which an accessory building needs a further approval, set by district
    thr = entry.get("accessory_structure_threshold_sqft")
    if _usable(thr) and thr.get("value") is not None:
        picked[("envelope", "accessory_structure_threshold_sqft")] = (
            thr,
            f"{where}.accessory_structure_threshold_sqft",
        )
    # Pass 7: the ADU size cap set by district, or lifted in a district (a null alone never wipes a value)
    cap = entry.get("adu_max_sqft")
    if _usable(cap) and cap.get("value") is not None:
        picked[("size", "max_sqft")] = (cap, f"{where}.adu_max_sqft")
    lift = entry.get("adu_size_cap_lifted")
    if _usable(lift) and lift.get("value") is True:
        for path in SIZE_PATHS:
            picked[path] = ({**lift, "value": None}, f"{where}.adu_size_cap_lifted")


def _rear_yard_only_yards(
    picked: Picked, data: dict[str, Any], place: str, principal: dict[str, tuple[dict[str, Any], str]]
) -> None:
    """Pass 13: envelope.accessory_yards_inside_rear_yard. The file's accessory side and rear yards hold only for a
    building inside the rear yard. Elsewhere it stays in the buildable area and meets the district yards, so those
    are the figures shown (none where the file has no district row). The rear yard figures are said in a condition."""
    flag = _leaf(data, ("envelope", "accessory_yards_inside_rear_yard"))
    if not (_usable(flag) and flag.get("value") is True):
        return
    for k in ("setback_side_ft", "setback_rear_ft"):
        own = picked.get(("envelope", k))
        if not own or own[1] != place:  # only the town-wide accessory yard, never a district one
            continue
        none_leaf = ({**flag, "value": None}, f"{place}#envelope.accessory_yards_inside_rear_yard")
        picked[("envelope", k)] = principal.get(k, none_leaf)


def _pick_town(
    data: dict[str, Any],
    place: str,
    scenario: str,
    lot: dict[str, Any],
    historic: bool,
    limits: dict[str, Any],
    reasons: list[str],
) -> tuple[Picked, Picked, str | None, dict[str, tuple[dict[str, Any], str]]]:
    """(picked after state, picked before state, how the path was chosen, district principal yards)."""
    _, state = layers_for(place, scenario)
    picked: Picked = {}
    principal: dict[str, tuple[dict[str, Any], str]] = {}
    _apply_local(picked, data, place)
    _accessory_yards_scope(picked, data, place, lot)  # pass 18: the town's accessory yards by district
    _apply_district_town(picked, data, place, lot, principal)
    _rear_yard_only_yards(picked, data, place, principal)
    how = None
    hist = _leaf(data, ("approval", "historic_path"))
    dpath = _district_path(data, lot)
    unlisted = _leaf(data, ("approval", "unlisted_use_path"))
    status = (_leaf(data, ("adu", "status")) or {}).get("value")
    if historic and _usable(hist) and hist.get("value"):
        picked[("approval", "path")] = (hist, f"{place}#approval.historic_path")
        how = "historic"
        forms = _leaf(data, ("form", "types_allowed_historic"))
        if _usable(forms) and forms.get("value") is not None:
            picked[("form", "types_allowed")] = (forms, f"{place}#form.types_allowed_historic")
    elif dpath:
        picked[("approval", "path")] = (dpath[0], place + dpath[1])
        how = "district"
    elif status in NO_ADU_STATUSES and _usable(unlisted) and unlisted.get("value") and _unlisted_here(data, lot):
        picked[("approval", "path")] = (unlisted, f"{place}#approval.unlisted_use_path")
        how = "unlisted"
        listed = picked.get(("form", "types_allowed"))
        if listed and listed[0].get("value") == []:  # pass 9: "no ADU form listed" never closes the unlisted-use path
            del picked[("form", "types_allowed")]
    _fill_defaults(picked, load_rules(DEFAULT))
    today = dict(picked)
    for name in state:
        _apply_state(picked, load_rules(name), name, lot, set(), limits, reasons)
    return picked, today, how, principal


def _districts_known(data: dict[str, Any]) -> list[str]:
    """Every district code the file names anywhere it lists districts (rows, lists, paths, gates, scopes)."""
    out = list((data.get("districts") or {}).keys())
    el, ap, adu = data.get("eligibility") or {}, data.get("approval") or {}, data.get("adu") or {}
    lists = [
        (el.get("zoning_districts") or {}).get("value"),
        (el.get("districts_read_no_listing") or {}).get("value"),
        (el.get("districts_in_doubt") or {}).get("value"),
        (adu.get("scope_districts") or {}).get("value"),
        (ap.get("unlisted_use_districts") or {}).get("value"),
    ]
    use = (adu.get("scope_by_use") or {}).get("value") or {}
    lists += [use.get("permitted_in"), use.get("not_permitted_in"), use.get("read_not_named")]
    for key in ("district_paths", "alternatives"):
        lists += [it.get("districts") for it in (ap.get(key) or {}).get("value") or []]
    for g in (el.get("gates") or {}).get("value") or []:
        lists += [g.get("districts"), g.get("not_districts")]
    for item in (adu.get("status_outside_by_district") or {}).get("value") or []:
        lists.append(item.get("districts"))
    for xs in lists:
        out += [str(x) for x in xs or [] if str(x) not in out]
    return out


def _district_read_line(data: dict[str, Any], lot: dict[str, Any]) -> str:
    """Pass 9: for a district with no row in the file, whether it was read and has no ADU listing, or was not read."""
    d = lot.get("zoning_district")
    if not d or _match_code(d, list((data.get("districts") or {}).keys())) is not None:
        return ""
    read = _leaf(data, ("eligibility", "districts_read_no_listing"))
    if _usable(read) and _match_code(d, read.get("value") or []) is not None:
        return f". {d} was read: its use list has no ADU and the file has no figures for it ({read['section']})"
    if _match_code(d, _districts_known(data)) is not None:
        return ""
    return f". {d} is not in the town file: its rules were not read"


def _unlisted_here(data: dict[str, Any], lot: dict[str, Any]) -> bool:
    """approval.unlisted_use_districts: the unlisted-use path reaches only these districts. With the
    district unknown the fallback stands (the path is said in the file's notes)."""
    only = (_leaf(data, ("approval", "unlisted_use_districts")) or {}).get("value")
    d = lot.get("zoning_district")
    return not only or (d is not None and _match_code(d, only) is not None)


def _unlisted_similar(data: dict[str, Any], lot: dict[str, Any]) -> dict[str, Any] | None:
    """Pass 12: approval.unlisted_use_scope similar_only reaching this lot's district (all unlisted-use districts when
    it lists none): the unlisted-use path reaches only uses similar to the listed ones, not any use left out."""
    leaf = _leaf(data, ("approval", "unlisted_use_scope"))
    if not (_usable(leaf) and leaf.get("value") == "similar_only"):
        return None
    where = leaf.get("districts")
    if where and _match_code(lot.get("zoning_district"), where) is None:
        return None
    return leaf


def _form_types_town(picked: Picked, lot: dict[str, Any]) -> list[str]:
    """A unit above an existing garage counts as using an existing structure."""
    types = _value(picked, "form", "types_allowed")
    types = list(ALL_TYPES if types is None else types)
    if _value(picked, "eligibility", "existing_structure_only"):
        types = [t for t in types if t not in NEW_STRUCTURE_TYPES or t == "over_garage"]
    if lot.get("has_accessory_building") is False:
        types = [t for t in types if t not in ("garage_conversion", "over_garage")]
    return [t for t in ALL_TYPES if t in types]


def _gate_overlay(g: dict[str, Any], lot: dict[str, Any]) -> bool | None:
    """Pass 10: is the lot in one of the gate's overlays (eligibility.gates[].overlays)? None when the lot's
    overlays were not given."""
    ov = lot.get("overlays")
    if ov is None:
        return None
    return any(_match_code(o, g["overlays"]) is not None for o in ov)


def _gate_scope(g: dict[str, Any], lot: dict[str, Any], historic: bool) -> bool:
    when = g.get("when", "always")
    if (when == "historic" and not historic) or (when == "not_historic" and historic):
        return False
    if g.get("districts") and _match_code(lot.get("zoning_district"), g["districts"]) is None:
        # pass 10: a gate with overlays also reaches a lot in one of them, whatever its base district
        if not (g.get("overlays") and _gate_overlay(g, lot) is True):
            return False
    elif g.get("overlays") and not g.get("districts") and _gate_overlay(g, lot) is False:
        return False
    if (
        g.get("not_districts")
        and lot.get("zoning_district")
        and _match_code(lot["zoning_district"], g["not_districts"]) is not None
    ):
        return False
    if g.get("except_planned_development") and lot.get("in_planned_development") is True:
        return False  # pass 12: the gate does not reach a lot in a planned or cluster development
    below = g.get("only_below_lot_sqft")  # pass 7: the gate holds only on lots under this size
    if below is not None and lot.get("lot_sqft") is not None and lot["lot_sqft"] >= below:
        return False
    btype = _building_type(lot.get("building_type"))
    return not (g.get("building_types") and btype not in g["building_types"])


def _built_before(year: Any, date: Any) -> bool | None:
    """A building built in `year` stood before `date` (YYYY-MM-DD)? None when the year does not settle it."""
    if year is None or not date:
        return None
    y, m, d = (int(x) for x in str(date).split("-"))
    if int(year) < y:
        return True
    if int(year) > y or (m, d) == (1, 1):
        return False
    return None


def _gate_paths(data: dict[str, Any], lot: dict[str, Any], historic: bool) -> list[dict[str, Any]]:
    """Pass 16: eligibility.gates[].path, the approval the gate's forms need on a lot it reaches (a special exception
    for any new building in a floodplain overlay). As form_paths items ({forms, path}), only where the lot is known to
    be in the gate's overlay or district and its test is met. Otherwise the gate stays a condition."""
    out = []
    for g in (_leaf(data, ("eligibility", "gates")) or {}).get("value") or []:
        if not g.get("path") or not _gate_scope(g, lot, historic):
            continue
        in_district = bool(g.get("districts")) and _match_code(lot.get("zoning_district"), g["districts"]) is not None
        if g.get("overlays") and _gate_overlay(g, lot) is not True and not in_district:
            continue
        if g.get("test") and _gate_met(g, lot) is not True:
            continue
        out.append({"forms": list(g.get("applies_to") or ALL_TYPES), "path": g["path"], "gate": g})
    return out


def _pd_kind_met(g: dict[str, Any], lot: dict[str, Any]) -> bool | None:
    """Pass 18: gates[].planned_development_kinds. The lot must be in a planned or cluster development of one of these
    kinds (Worcester's Option 3, not Options 1 and 2). None when either fact was not given."""
    inside = lot.get("in_planned_development")
    if inside is not True:
        return None if inside is None else False
    kind = lot.get("planned_development_kind")
    return None if kind is None else _match_code(kind, g["planned_development_kinds"]) is not None


def _pd_kind_words(g: dict[str, Any], lot: dict[str, Any]) -> str:
    """Pass 18: the facts a planned_development_kinds gate depends on, in plain words."""
    if lot.get("in_planned_development") is True:
        return "which kind of planned or cluster development the lot is in (planned_development_kind)"
    return f"{HOUSE_TESTS['in_planned_development']} and which kind it is (planned_development_kind)"


def _gate_met(g: dict[str, Any], lot: dict[str, Any]) -> bool | None:
    test, area = g.get("test"), lot.get("lot_sqft")
    if test == "in_planned_development" and g.get("planned_development_kinds"):
        return _pd_kind_met(g, lot)
    if test in HOUSE_TESTS:
        return _house_met(test, g.get("value"), g.get("value_date"), lot)
    if test == "has_alley":
        return None if lot.get("has_alley") is None else bool(lot["has_alley"] or lot.get("corner_lot"))
    if test == "has_accessory_building":
        return lot.get("has_accessory_building")
    if test == "no_accessory_building":  # pass 13: met on a lot with no accessory building
        acc = lot.get("has_accessory_building")
        return None if acc is None else not acc
    if test in ("lot_sqft_at_least", "lot_sqft_below") and g.get("value") is not None:
        if area is None:
            return None
        return area >= g["value"] if test == "lot_sqft_at_least" else area < g["value"]
    if test in ("tract_sqft_at_least", "tract_sqft_below") and g.get("value") is not None:
        return _tract_met(test, g["value"], lot)
    if test == "top_of_bank_ft_over" and g.get("value") is not None:  # pass 19: met when farther than the value
        bank = lot.get("top_of_bank_ft")
        return None if bank is None else bank > g["value"]
    return None


def _tract_met(test: str, value: float, lot: dict[str, Any], strict: bool = False) -> bool | None:
    """Pass 9: a test on the parent tract (lot fact tract_sqft). Without it, a lot at least that large settles it,
    since the tract holds the lot. A smaller lot settles nothing. strict: "over" rather than "at least"."""
    tract = lot.get("tract_sqft")
    if tract is None:
        area = lot.get("lot_sqft")
        if area is None or not (area > value if strict else area >= value):
            return None
        tract = area
    hit = tract > value if strict else tract >= value
    return hit if test == "tract_sqft_at_least" else not hit


def _house_met(test: str, value: Any, date: Any, lot: dict[str, Any]) -> bool | None:
    """Pass 7 tests on the house and the services. None when the fact is not given."""
    if test in ("house_sqft_at_least", "house_sqft_over"):
        house = lot.get("house_sqft")
        if house is None or value is None:
            return None
        return house >= value if test == "house_sqft_at_least" else house > value
    if test == "house_built_before":
        return _built_before(lot.get("house_year_built"), date)
    if test == "accessory_building_built_before":
        if lot.get("has_accessory_building") is False:
            return False
        return _built_before(lot.get("accessory_building_year_built"), date)
    if test in ("lot_width_at_least", "lot_width_below"):
        width = lot.get("lot_width_ft")
        if width is None or value is None:
            return None
        return width >= value if test == "lot_width_at_least" else width < value
    fact = lot.get(test)  # house_exists, public_sewer, public_water, designated_on_plan
    return None if fact is None else bool(fact)


def _cond(
    kind: str,
    text: str,
    leaf: dict[str, Any] | None,
    met: bool | None = None,
    applies_to: list[str] | None = None,
    effect: str = "condition",
) -> dict[str, Any]:
    leaf = leaf or {}
    return {
        "kind": kind,
        "condition": text,
        "met": met,
        "applies_to": applies_to,
        "effect": effect,
        "section": leaf.get("section"),
        "url": leaf.get("url"),
        "confidence": leaf.get("confidence"),
    }


def _per_unit(data: dict[str, Any], lot: dict[str, Any]) -> dict[str, Any] | None:
    _, row = _district_row(data, lot)
    per = (
        row.get("lot_area_per_unit_sqft")
        if _usable(row.get("lot_area_per_unit_sqft"))
        else _leaf(data, ("eligibility", "lot_area_per_unit_sqft"))
    )
    return per if per and per.get("value") else None


def _density(data: dict[str, Any], lot: dict[str, Any]) -> tuple[dict[str, Any], float, bool] | None:
    """(leaf, lot area needed, binding). Binding when the leaf is verified and has no open reading."""
    per = _per_unit(data, lot)
    if not per:
        return None
    units = int(lot.get("existing_units") or 1) + 1
    binding = per.get("confidence") == "verified"
    return per, units * per["value"], binding


def _town_conditions(
    data: dict[str, Any],
    picked: Picked,
    lot: dict[str, Any],
    historic: bool,
    how: str | None,
    scope: dict[str, Any],
    hold: bool = False,
    hold13: bool = False,
    hold14: bool = False,
    hold15: bool = False,
    hold18: bool = False,
) -> list[dict[str, Any]]:
    """Who may live there, owner rule, existing-building-only, type, district and lot gates, each cited.
    hold: a lot town whose pass 10 sentence fixes wait for its next lot rebuild (LOT_RECORD_TOWNS).
    hold14: a lot town whose pass 14 sentence fixes wait for its next lot rebuild (PASS14_HOLD_TOWNS).
    hold15: a lot town whose pass 15 sentence fix waits for its next lot rebuild (PASS15_HOLD_TOWNS).
    hold18: a lot town whose pass 18 sentence fix waits for its next lot rebuild (PASS18_HOLD_TOWNS)."""
    out = []
    status = _leaf(data, ("adu", "status"))
    if scope["districts"] and scope["in_scope"] is not True:
        out.append(
            _cond(
                "scope",
                _scope_line(scope, lot, with_section=False),
                _leaf(data, ("adu", "scope_districts")) or _leaf(data, ("adu", "scope_by_use")),
                scope["in_scope"],
            )
        )
    # Pass 14: with no ADU rule here the reasons already give the status with its note (the head line), so the
    # condition would say it twice
    said = bool(status and status.get("value") in NO_ADU_STATUSES and how not in ("historic", "district"))
    if (
        status
        and status.get("value")
        and status["value"] != "allowed_by_right"
        and not (said and status.get("section"))
    ):
        words = status["value"].replace("_", " ")
        note = status.get("note") or ""
        if hold13:  # a lot town: the pass 12 wording until its next lot rebuild (PASS13_HOLD_TOWNS)
            text = f"{words}. {note}".strip()
            if how == "historic" and status["value"] in NO_ADU_STATUSES:  # pass 9
                text = f"Town-wide: {text} On this lot the historic path applies"
        elif (
            how == "historic" and status["value"] in NO_ADU_STATUSES
        ):  # pass 9. Pass 13: a sentence, never "not addressed."
            text = f"Town-wide, the code's ADU status is {words}. {note}".strip().rstrip(".")
            text += ". On this lot the historic path applies"
        else:
            text = f"The code's ADU status is {words}. {note}".strip()
        out.append(_cond("adu_status", text, status))
    if how == "historic":
        hist = _must_leaf(data, ("approval", "historic_path"))
        out.append(
            _cond(
                "historic",
                f"Historic path: {hist['value'].replace('_', ' ')}. {hist.get('note') or ''}".strip(),
                hist,
                True,
            )
        )
    if how == "unlisted":
        un = _must_leaf(data, ("approval", "unlisted_use_path"))
        similar = _unlisted_similar(data, lot)
        what = (
            "A use similar in nature to a use the district lists"
            + (f" ('{similar['quote']}', {similar['section']})" if similar and similar.get("quote") else "")
            if similar
            else "A use not provided for"
        )
        out.append(
            _cond(
                "other",
                f"The code does not list ADUs. {what} may be approved by "
                f"{_path_words(un)}"
                + (". Whether an ADU is similar is not settled" if similar else "")
                + f". {un.get('note') or ''}".rstrip(),
                un,
            )
        )
    occ = _leaf(data, ("use", "occupancy"))
    if occ and occ.get("value") and how != "historic":
        out.append(_cond("occupancy", occ["value"], occ))
    fam = picked.get(("use", "family_only"))
    if fam and fam[0].get("value") and how != "historic":
        out.append(_cond("family", fam[0].get("note") or "Occupants must be family members", fam[0]))
    own = picked.get(("use", "owner_occupancy"))
    own_by = picked.get(("use", "owner_occupancy_by_form"))
    if own_by and isinstance(own_by[0].get("value"), dict):  # pass 10: the owner rule differs by form
        by = own_by[0]["value"]
        yes = [t for t in ALL_TYPES if by.get(t) is True]
        no = [t for t in ALL_TYPES if by.get(t) is False]
        if yes:
            out.append(
                _cond(
                    "owner_occupancy",
                    f"The owner must live on the lot for {', '.join(t.replace('_', ' ') for t in yes)}"
                    + (f". No owner rule for {', '.join(t.replace('_', ' ') for t in no)}" if no else "")
                    + (f". {own_by[0]['note']}" if own_by[0].get("note") else ""),
                    own_by[0],
                    applies_to=yes,
                )
            )
    elif own and own[0].get("value"):
        out.append(_cond("owner_occupancy", own[0].get("note") or "The owner must live on the lot", own[0]))
    ex = picked.get(("eligibility", "existing_structure_only"))
    if ex and ex[0].get("value"):
        out.append(
            _cond(
                "existing_structure",
                ex[0].get("note") or "Only inside an existing building",
                ex[0],
                lot.get("has_accessory_building"),
            )
        )
    bt = picked.get(("eligibility", "building_types"))
    if bt and bt[0].get("value"):
        btype = _building_type(lot.get("building_type"))
        out.append(
            _cond(
                "building_type",
                f"House type must be {' or '.join(bt[0]['value'])}",
                bt[0],
                None if btype is None else btype in bt[0]["value"],
            )
        )
    zd = picked.get(("eligibility", "zoning_districts"))
    if zd and zd[0].get("value") and how != "district":
        d = lot.get("zoning_district")
        out.append(
            _cond(
                "district",
                f"Zoning district must be one of {', '.join(zd[0]['value'])}",
                zd[0],
                None if d is None else _match_code(d, zd[0]["value"]) is not None,
            )
        )
    ml = picked.get(("eligibility", "min_lot_sqft"))
    if ml and ml[0].get("value") and not historic and "#districts." not in ml[1]:
        area = lot.get("lot_sqft")
        out.append(
            _cond(
                "lot_size",
                f"ADU rule: lot of at least {ml[0]['value']:,.0f} sq ft"
                + (f". {ml[0]['note']}" if ml[0].get("note") else ""),
                ml[0],
                None if area is None else area >= ml[0]["value"],
            )
        )
    dm = _district_min(data, lot)
    by_services = not hold18 and _min_lot_by_services(data, lot)  # pass 18: never "the district minimum" then
    if dm and not historic:
        leaf, need, share = dm
        area = lot.get("lot_sqft")
        met = None if area is None else area >= need
        if _district_min_binds(data):
            rule = _leaf(data, ("eligibility", "requires_conforming_lot")) or _must_leaf(
                data, ("eligibility", "min_lot_share_of_district")
            )
            which = "lot minimum for the lot's sewer and water" if by_services else "district minimum"
            text = (
                f"The ADU needs a lot of at least {need:,.0f} sq ft"
                + (f", {share:.0%} of the {which} of {leaf['value']:,.0f}" if share != 1 else f", the {which}")
                + (f" ({leaf['section']}, {rule['section']})" if by_services else f" ({rule['section']})")
            )
            out.append(_cond("lot_size", text, leaf, met, effect="bars"))
        elif _rcl_reading(data):  # a secondary reading: a condition with "if", never a bar
            rcl = _must_leaf(data, ("eligibility", "requires_conforming_lot"))
            out.append(
                _cond(
                    "lot_size",
                    (
                        "If the ADU needs a lot that meets the lot minimum for the lot's sewer and water, "
                        f"{leaf['value']:,.0f} sq ft ({leaf['section']}, {rcl['section']}, a reading that needs care)"
                        if by_services
                        else f"If the ADU needs a lot that meets the district minimum of {leaf['value']:,.0f} sq ft "
                        f"({rcl['section']}, a reading that needs care)"
                    )
                    + (". This lot is below it. Ask the zoning officer" if met is False else ""),
                    leaf,
                    met,
                )
            )
        elif _pd_replaces_min(data, lot, historic):
            pass  # pass 15: a lot in a planned development whose own lot figures replace the district minimum
            # (pass 19: whether or not the lot meets it. Marshall 208-207 Table 1, a cluster lot's figures)
        elif met is False:
            out.append(
                _cond(
                    "district_lot_rule",
                    (
                        f"This lot is below the lot minimum for its sewer and water, {leaf['value']:,.0f} sq ft "
                        f"({leaf['section']}). "
                        if by_services
                        else f"This lot is below the district minimum of {leaf['value']:,.0f} sq ft. "
                    )
                    + "It may be a nonconforming lot. Ask the zoning officer whether an ADU is allowed on it"
                    + _waiver_note(data, lot, historic, "min_lot"),
                    leaf,
                    False,
                )
            )
        else:
            out.append(
                _cond(
                    "district_lot_rule",
                    (
                        f"The lot minimum for the lot's sewer and water is {leaf['value']:,.0f} sq ft ({leaf['section']})"
                        if by_services
                        else f"The district's minimum lot is {leaf['value']:,.0f} sq ft"
                    )
                    + ". A rule for creating lots, not an ADU rule",
                    leaf,
                    met,
                )
            )
    code, row = _district_row(data, lot)
    abut = row.get("yards_abutting_residential_ft")
    if _usable(abut) and abut.get("value") is not None and lot.get("abuts_residential_district") is None:
        out.append(  # pass 18: the yards hold only where the lot abuts a residential district, which is not known
            _cond(
                "other",
                f"Side and rear yards in {code}: {abut['value']:,.0f} ft where the yard abuts a residential district, "
                "none otherwise. Depends on whether the lot abuts a residential district (abuts_residential_district), "
                "which was not given",
                abut,
            )
        )
    dens = _density(data, lot)
    if dens:
        per, need, binding = dens
        area = lot.get("lot_sqft")
        lead = "" if binding else "If the ADU counts as a dwelling unit: "
        out.append(
            _cond(
                "lot_area_per_unit",
                f"{lead}{per['value']:,.0f} sq ft of lot per dwelling unit. The house and the ADU need "
                f"{need:,.0f} sq ft" + (f". {per['note']}" if per.get("note") else ""),
                per,
                None if area is None else area >= need,
                effect="bars" if binding else "condition",
            )
        )
    thr = picked.get(("envelope", "accessory_structure_threshold_sqft"))
    if thr and thr[0].get("value") is not None:
        out.append(
            _cond(
                "size",
                f"An accessory building over {thr[0]['value']:,.0f} sq ft needs a further approval"
                + (f". {thr[0]['note']}" if thr[0].get("note") else ""),
                thr[0],
                applies_to=DETACHED_TYPES,
            )
        )
    land = _leaf(data, ("approval", "land_development_second_building"))
    if _usable(land) and land.get("value") is True and how not in ("unlisted",):
        # pass 15: a second residential building on a lot is a land development (St. Marys 112)
        out.append(
            _cond(
                "land_development",
                "A new detached unit puts a second residential building on the lot, which the code makes a land "
                "development. It needs land development plan approval as well as the zoning approval"
                + (f". {land['note']}" if land.get("note") else ""),
                land,
                applies_to=["detached_new"],
            )
        )
    tot = picked.get(("envelope", "accessory_floor_area_total_sqft"))
    if tot and tot[0].get("value") is not None:
        out.append(
            _cond(
                "size",
                f"All accessory buildings on the lot together may have at most {tot[0]['value']:,.0f} sq ft "
                f"of ground floor area, an existing garage included",
                tot[0],
                applies_to=DETACHED_TYPES,
            )
        )
    no_adu = bool(status and status.get("value") in NO_ADU_STATUSES and how not in ("district", "historic"))
    base_h = _value(picked, "envelope", "max_height_ft")
    where = _leaf(data, ("envelope", "max_height_where"))
    for item in (where or {}).get("value") or [] if not no_adu else []:
        c = _cond(
            "height",
            f"A detached unit {item['where']} may be up to {item['max_height_ft']:g} ft"
            + (f". Otherwise {base_h:g} ft" if base_h is not None else "")
            + (f". {item['note']}" if item.get("note") else ""),
            _leaf_from(item, where or {}, None),
            applies_to=DETACHED_TYPES,
        )
        c["max_height_ft"] = item["max_height_ft"]
        out.append(c)
    by_st = _leaf(data, ("envelope", "max_height_by_stories"))
    for item in (by_st or {}).get("value") or [] if not no_adu else []:  # pass 8: height by story count
        n = item["stories"]
        c = _cond(
            "height",
            f"A detached unit of {n:g} stor{'y' if n == 1 else 'ies'} may be up to {item['max_height_ft']:g} ft"
            + (f". {item['note']}" if item.get("note") else ""),
            _leaf_from(item, by_st or {}, None),
            applies_to=DETACHED_TYPES,
        )
        c["max_height_ft"] = item["max_height_ft"]
        out.append(c)
    acc_where = _leaf(data, ("envelope", "accessory_rules_where"))
    for item in (acc_where or {}).get("value") or [] if not no_adu else []:  # pass 9: yards by placement or size
        if item.get("districts") and _match_code(lot.get("zoning_district"), item["districts"]) is None:
            continue
        figs = [
            f"{label} {item[k]:g} ft"
            for k, label in (
                ("setback_front_ft", "front"),
                ("setback_side_ft", "side"),
                ("setback_rear_ft", "rear"),
                ("min_from_front_line_ft", "from the front line at least"),
                ("max_height_ft", "height at most"),
            )
            if item.get(k) is not None
        ]
        if item.get("max_share_of_rear_yard") is not None:
            figs.append(f"at most {item['max_share_of_rear_yard']:.0%} of the required rear yard")
        where_txt = item["where"] + (f" (over {item['over_sqft']:,.0f} sq ft)" if item.get("over_sqft") else "")
        if figs:  # pass 17: never the building named twice, and the figures after the where text's first sentence
            text = _acc_where_figs(where_txt, figs)
        else:  # pass 15: an item with no figures carries its rule in the where text. Never "...: ." or the noun twice
            if item.get("over_sqft") and "sq ft" in item["where"]:
                where_txt = item["where"]
            text = (
                where_txt[:1].upper() + where_txt[1:]
                if NAMES_BUILDING.match(where_txt)
                else f"For an accessory building, {where_txt}"
            )
        out.append(
            _cond(
                "other",
                text + (f". {item['note']}" if item.get("note") else ""),
                _leaf_from(item, acc_where or {}, None),
                applies_to=DETACHED_TYPES,
            )
        )
    inside_rear = _leaf(data, ("envelope", "accessory_yards_inside_rear_yard"))
    if _usable(inside_rear) and inside_rear.get("value") is True and not no_adu:  # pass 13
        figs = [
            f"{v:g} ft from the {label} line"
            for k, label in (("setback_side_ft", "side"), ("setback_rear_ft", "rear"))
            for v in [(_leaf(data, ("envelope", k)) or {}).get("value")]
            if v is not None
        ]
        out.append(
            _cond(
                "other",
                "An accessory building inside the rear yard may stand "
                + (" and ".join(figs) if figs else "closer to the lot lines")
                + ". Elsewhere it stays in the buildable area and meets the district yards, which are the figures shown"
                + (f". {inside_rear['note']}" if inside_rear.get("note") else ""),
                inside_rear,
                applies_to=DETACHED_TYPES,
            )
        )
    part = _leaf(data, ("envelope", "accessory_share_of_house_part"))
    for item in (part or {}).get("value") or [] if not no_adu else []:  # pass 10: a share of a named part
        if item.get("districts") and _match_code(lot.get("zoning_district"), item["districts"]) is None:
            continue
        sh = item["share"]
        cap = f"{sh:g} times" if sh > 1 else ("the same area as" if sh == 1 else f"{sh:.0%} of")
        out.append(
            _cond(
                "size",
                f"{item['what'][:1].upper()}{item['what'][1:]}: at most {cap} {item['of']}"
                + (f", {item['when']}" if item.get("when") else "")
                + ". The tool cannot measure that part of the house, so no number is given"
                + (f". {item['note']}" if item.get("note") else ""),
                _leaf_from(item, part or {}, None),
                applies_to=DETACHED_TYPES,
            )
        )
    garage = _leaf(data, ("envelope", "max_height_garage_where"))
    for item in (garage or {}).get("value") or [] if not no_adu else []:  # pass 10: a garage height exception
        area = lot.get("lot_sqft")
        if item.get("lot_over_sqft") is not None and area is not None and area <= item["lot_over_sqft"]:
            continue
        out.append(
            _cond(
                "other",
                f"A garage {item['where']} may be up to {item['max_height_ft']:g} ft"
                + (f". {item['note']}" if item.get("note") else ""),
                _leaf_from(item, garage or {}, None),
                applies_to=DETACHED_TYPES,
            )
        )
    per_res = picked.get(("parking", "spaces_per_resident"))
    if per_res and per_res[0].get("value") is not None and not no_adu:
        c = _cond(
            "parking",
            f"{per_res[0]['value']:g} off-street space per resident of the unit. The count depends on how many people live there"
            + (f". {per_res[0]['note']}" if per_res[0].get("note") else ""),
            per_res[0],
        )
        c["bill_overrides"] = True  # HB 2186: no parking for the ADU
        out.append(c)
    rate = picked.get(("parking", "spaces_rate"))
    rounding = picked.get(("parking", "fraction_rounding"))
    if (
        rate
        and rate[0].get("value") is not None
        and rounding
        and rounding[0].get("value") in FRACTION_RULES
        and not no_adu
    ):
        # pass 19: the code's own rate for the unit and the rounding rule the code states (Douglass 265-230C(7), 265-229C)
        n = _round_spaces(rate[0]["value"], rounding[0]["value"])
        req = picked.get(("parking", "spaces_required"))
        req_n = req[0].get("value") if req else None
        secs = ", ".join(dict.fromkeys(x for x in (rate[0].get("section"), rounding[0].get("section")) if x))
        c = _cond(
            "parking",
            f"The code asks {rate[0]['value']:g} off-street spaces for the unit, and "
            f"{FRACTION_RULES[rounding[0]['value']][0]}"
            + (f", so {n:,.0f} {'space' if n == 1 else 'spaces'}" if req_n is None or req_n == n else "")
            + f" ({secs})"
            + _waiver_note(data, lot, historic, "parking"),
            rate[0],
        )
        c["bill_overrides"] = True  # HB 2186: no parking for the ADU
        out.append(c)
    bar = picked.get(("envelope", "front_yard_barred"))
    rear = picked.get(("envelope", "accessory_rear_yard_only")) if _rear_only_here(data, lot) else None  # pass 17
    if rear and rear[0].get("value") is True:  # pass 8: rear yard only rules out the side yards too
        out.append(
            _cond(
                "front_yard",
                "An accessory building may stand only in the rear yard: not in the front yard and not in a side yard. "
                "It is a bar, not a setback number" + (f". {rear[0]['note']}" if rear[0].get("note") else ""),
                rear[0],
                applies_to=DETACHED_TYPES,
            )
        )
    elif bar and bar[0].get("value") is True:
        out.append(
            _cond(
                "front_yard",
                "An accessory building may not stand in the front yard, between the house and the street. "
                "It is a bar, not a setback number" + (f". {bar[0]['note']}" if bar[0].get("note") else ""),
                bar[0],
                applies_to=DETACHED_TYPES,
            )
        )
    gates = _leaf(data, ("eligibility", "gates")) or {}
    for g in gates.get("value") or []:
        if _gate_scope(g, lot, historic):
            effect = g["effect"]
            scoped = (
                g.get("test")
                or g.get("districts")
                or g.get("not_districts")
                or g.get("building_types")
                or g.get("when") in ("historic", "not_historic")
                or g.get("overlays")  # pass 12: a bar only inside an overlay is scoped by the overlay
            )
            c = _cond(
                g["kind"],
                g["condition"],
                _leaf_from(g, gates, None),
                _gate_met(g, lot),
                g.get("applies_to"),
                effect if (effect != "bars" or scoped) else "condition",
            )
            if effect == "bars" and not scoped:
                c["warning"] = (
                    "A bar with no lot test and no scope is shown as a condition. Add a test or a scope to the gate"
                )
            c["test"] = g.get("test")
            c["bill_overrides"] = bool(g.get("bill_overrides"))
            if g.get("overlays") and not g.get("districts") and _gate_overlay(g, lot) is None:
                # pass 10: an overlay-only gate on a lot whose overlays were not given. Never a bar
                c["overlay_open"] = True
                if effect == "bars" and not g.get("test"):  # pass 12: named for depends_on
                    c["overlay_names"] = " or ".join(g["overlays"])
                c["condition"] = (
                    c["condition"].rstrip(".")
                    + f". Applies only if the lot is in the {' or '.join(g['overlays'])} overlay. "
                    "The lot's overlays were not given"
                )
            if g.get("except_planned_development") and lot.get("in_planned_development") is None:
                c["condition"] = (  # pass 12: said, since whether the lot is in one was not given
                    c["condition"].rstrip(".") + ". Not on a lot in a planned or cluster development"
                )
            if g.get("outside_zoning_chapter"):  # pass 17: a bar from another chapter, whose own appeal rules govern
                c["outside_zoning_chapter"] = g["outside_zoning_chapter"]
            if g.get("supersedes_district_figures"):  # pass 10: the gate's own figures replace the district's
                c["supersedes_district_figures"] = True
                if g.get("supersedes_figures"):  # pass 17: only these district figures are replaced
                    c["supersedes_figures"] = list(g["supersedes_figures"])
                if g.get("overlays") and not g.get("test"):  # pass 12: an overlay whose figures replace the district's
                    c["in_overlay"] = _gate_overlay(g, lot)
                    lot_ovs = lot.get("overlays") or []
                    c["supersedes_overlays"] = [
                        o for o in g["overlays"] if not c["in_overlay"] or _match_code(o, lot_ovs) is not None
                    ]
            dispute = g.get("disputed_by")
            if dispute and effect == "bars" and scoped and not g.get("test") and not c.get("overlay_open"):
                # pass 13: a bar scoped only by district, house type or overlay reaches this lot, so the lot fails it
                # as written. The dispute then makes it depend on the reading, never a plain variance
                c["met"] = False
            if dispute and c["met"] is not True:  # pass 8: a bar another passage may undo. Depends, never a plain no
                c["disputed_by"] = dispute
                c["condition"] = (
                    c["condition"].rstrip(".")
                    + f" ({c['section']}). But {dispute['section']}: {dispute['note'].rstrip('.')}. "
                    "The code does not settle which reading holds. Ask the zoning officer"
                )
                if c["met"] is False:
                    c["effect"] = "condition"
            if effect == "bars" and (g.get("overlays") or g.get("outside_zoning_chapter")):
                # pass 18: a bar on the land (an overlay, another chapter) reaches the other paths too. Popped later
                c["_land_bar"] = g["condition"]
            if c["test"] == "in_planned_development" and g.get("planned_development_kinds") and c["met"] is None:
                c["fact"] = _pd_kind_words(g, lot)  # pass 18: the kind of planned development decides it
                c["condition"] = (
                    c["condition"].rstrip(".")
                    + f". Depends on {c['fact']}, which {'was' if lot.get('in_planned_development') else 'were'} not given. "
                    + "It must be "
                    + " or ".join(g["planned_development_kinds"])
                )
            elif c["test"] in HOUSE_TESTS and c["met"] is None:
                c["condition"] = (
                    c["condition"].rstrip(".") + f". Depends on {HOUSE_TESTS[c['test']]}, which was not given"
                )
            elif c["test"] == "top_of_bank_ft_over" and c["met"] is not None:  # pass 19: the distance was given
                c["condition"] = c["condition"].rstrip(".") + (
                    f". At {lot['top_of_bank_ft']:,.0f} ft from the top of bank the new building is "
                    + ("clear of that line" if c["met"] else "inside that line")
                )
            elif c["test"] in LOT_TESTS and c["met"] is None and c["effect"] != "bars" and not hold:
                # pass 10: a condition never reads as a bar. It depends on the fact, it is not "allowed only if"
                c["condition"] = (
                    c["condition"].rstrip(".") + f". Depends on {LOT_TESTS[c['test']]}, which was not given"
                )
            elif c["test"] and c["met"] is None:
                c["condition"] += ". Allowed only if this holds. The lot fact is not known"
            out.append(c)
    out += _utility_conditions(
        data,
        lot,
        hold14,
        once=not hold15,
        pd=_pd_replaces_min(data, lot, historic),
        pd_all=_pd_gate(data, lot, historic),
    )
    return out


def _utility_figures(item: dict[str, Any], hold: bool = False) -> str:
    """A services row's figures. Pass 14: with units, and an acre restatement at the head of the note folded into
    the area ("min lot 43,560 sq ft (one acre)", never "min lot 43,560. One acre"). hold: the pass 13 wording."""
    parts = []
    for f in UTILITY_FIELDS:
        v = item.get(f)
        if v is None:
            continue
        name = f.replace("_ft", "").replace("_sqft", "").replace("_", " ")
        if f in ("max_building_coverage", "max_impervious_coverage"):
            parts.append(f"{name} {v:.0%}")
        elif hold or f == "accessory_max_stories":
            parts.append(f"{name} {v:,.0f}")
        else:
            parts.append(f"{name} {v:,.0f} {'sq ft' if f.endswith('_sqft') else 'ft'}")
    figs = ", ".join(parts).replace("accessory max stories", "accessory building stories")
    figs = figs.replace("accessory max height", "accessory building height")
    note = (item.get("note") or "").rstrip(".")
    acre = None if hold else ACRE_HEAD.match(note)
    if acre and item.get("min_lot_sqft") and abs(ACRES[acre.group(1).lower()] * 43560 - item["min_lot_sqft"]) < 1:
        figs = figs.replace(
            f"min lot {item['min_lot_sqft']:,.0f} sq ft",
            f"min lot {item['min_lot_sqft']:,.0f} sq ft ({acre.group(0).strip(' ,.').lower()})",
            1,
        )
        note = note[acre.end() :].lstrip(" ,.")
        note = note[:1].upper() + note[1:]
    return figs + (f". {note}" if note else "")


def _utility_open(item: dict[str, Any], lot: dict[str, Any], hold: bool = False) -> tuple[str, str, str]:
    """Pass 14: (the services the figures shown are for, the missing fact in words, its lot keys) for a row whose
    services were not given. Only the services the row names and the lot does not give. hold: the pass 13 wording."""
    named = [f for f in ("public_sewer", "public_water") if item.get(f) is not None]
    keys = [f for f in named if lot.get(f) is None]
    both = "public sewer and water", "public sewer and water", "public_sewer, public_water"
    if hold or not keys:
        return both
    base = both[0] if len(named) == 2 else ROW_FACTS[named[0]]
    return base, both[1] if len(keys) == 2 else ROW_FACTS[keys[0]], ", ".join(keys)


def _utility_conditions(
    data: dict[str, Any],
    lot: dict[str, Any],
    hold: bool = False,
    once: bool = True,
    pd: bool = False,
    pd_all: bool = False,
) -> list[dict[str, Any]]:
    """districts.<code>.utility_rows: the row shown assumes public sewer and water. Say the others, and that
    the figures depend on the services when they are not given. hold: a lot town (PASS14_HOLD_TOWNS).
    once: pass 15, a row whose sentence was already said is not said again (False for PASS15_HOLD_TOWNS).
    pd: pass 19, the lot is in a planned or cluster development whose own lot figures replace the district minimum
    (_pd_replaces_min). A row's lot minimum is dropped then, and a row with no other figure is not said. pd_all: a
    planned-development gate replaces every district figure (_pd_gate), so no services row is said."""
    code = _match_code(lot.get("zoning_district"), list((data.get("districts") or {}).keys()))
    leaf = (((data.get("districts") or {}).get(code) or {}) if code else {}).get("utility_rows")
    if not (_usable(leaf) and leaf.get("value")):
        return []
    if pd_all:  # pass 19: the development's own figures replace every district figure, the services rows too
        return []
    if pd:  # pass 19: Marshall SR cluster lot, the services minimum is the conventional lot's (208-207 Table 1)
        rows = [{k: v for k, v in item.items() if k != "min_lot_sqft"} for item in leaf["value"]]
        rows = [r for r in rows if any(r.get(f) is not None for f in UTILITY_FIELDS)]
        if not rows:
            return []
        leaf = {**leaf, "value": rows}
    out = []
    if (
        all(_utility_match(item, lot) is False for item in leaf["value"])
        and not any(item.get("in_growth_area") is not None for item in leaf["value"])
        and not _base_services(leaf["value"], lot)
    ):  # pass 13: the services were given, and the code has no figures for them. Say so, never "not given"
        out.append(
            _cond(
                "utilities",
                f"The code gives no {code} figures for a lot with {_services_words(lot)}. "
                "The district figures shown are for a lot with public sewer and water",
                leaf,
                None,
            )
        )
    for item in leaf["value"]:
        met = _utility_match(item, lot)
        if met is False:
            continue
        c = _cond("utilities", f"{item['when']}: {_utility_figures(item, hold)}", _leaf_from(item, leaf, None), met)
        if met is None and item.get("in_growth_area") is not None and lot.get("in_growth_area") is None:
            # pass 9: a row keyed on a mapped growth area
            c["condition"] += (
                ". Depends on whether the lot is inside the mapped growth area (in_growth_area), which was not given"
            )
            c["test"] = "in_growth_area"
        elif met is None:
            base, fact, keys = _utility_open(item, lot, hold)
            c["condition"] += (
                f". The district figures shown are for a lot with {base}. "
                f"Depends on whether the lot has {fact} ({keys}), which was not given"
            )
            c["test"] = "public_sewer_water"
            if not hold:  # pass 14: the service that was not given, for depends_on
                c["fact"] = f"whether the lot has {fact}"
        if once and any(o["condition"] == c["condition"] for o in out):
            continue  # pass 15: two rows for "sewer or water missing" read alike on a lot with neither (Upper Uwchlan R-3)
        out.append(c)
    return out


def _district_min(data: dict[str, Any], lot: dict[str, Any]) -> tuple[dict[str, Any], float, float] | None:
    """(district minimum lot leaf, area the ADU needs, share). The share comes from min_lot_share_of_district."""
    _, row = _district_row(data, lot)
    leaf = row.get("min_lot_sqft")
    if not (_usable(leaf) and leaf.get("value")):
        return None
    share = (_leaf(data, ("eligibility", "min_lot_share_of_district")) or {}).get("value") or 1
    return leaf, leaf["value"] * share, share


def _min_lot_by_services(data: dict[str, Any], lot: dict[str, Any]) -> bool:
    """Pass 18: the lot minimum comes from the services row that fits the lot (Lower Saucon 180-94A), not the district
    table. Its sentence then says so, never "the district minimum"."""
    code = _match_code(lot.get("zoning_district"), list((data.get("districts") or {}).keys()))
    hit = _utility_row((data.get("districts") or {}).get(code) or {}, lot) if code else None
    return bool(hit and hit[0].get("min_lot_sqft") is not None)


def _waiver_note(data: dict[str, Any], lot: dict[str, Any], historic: bool, what: str) -> str:
    """Pass 19: eligibility.gates[].waives_figures. In the gate's overlay the code lets the governing body modify or
    waive these figures (Canonsburg Downtown Overlay 170-401G: lot dimensional and parking requirements). Said after
    the figure's line: on a lot in the overlay, or with "If the lot is in" when the lot's overlays were not given."""
    out = ""
    for g in (_leaf(data, ("eligibility", "gates")) or {}).get("value") or []:
        if what not in (g.get("waives_figures") or []) or not g.get("overlays") or not _gate_scope(g, lot, historic):
            continue
        inside = _gate_overlay(g, lot)
        if inside is False:
            continue
        name = " or ".join(g["overlays"])
        it = "the lot minimum" if what == "min_lot" else "the parking requirement"
        out += (
            f". In the {name} the code lets {it} be modified or waived ({g['section']})"
            if inside
            else f". If the lot is in the {name}, the code lets {it} be modified or waived ({g['section']})"
        )
    return out


def _pd_replaces_min(data: dict[str, Any], lot: dict[str, Any], historic: bool) -> bool:
    """Pass 15: the lot is in a planned or cluster development whose own lot figures replace the district minimum:
    districts.<code>.min_lot_replaced_in_planned_development, or a planned-development gate with
    supersedes_district_figures that reaches the lot."""
    if lot.get("in_planned_development") is not True:
        return False
    _, row = _district_row(data, lot)
    flag = row.get("min_lot_replaced_in_planned_development")
    if _usable(flag) and flag.get("value") is True:
        return True
    return _pd_gate(data, lot, historic)


def _pd_gate(data: dict[str, Any], lot: dict[str, Any], historic: bool) -> bool:
    """The lot is in a planned or cluster development whose gate (supersedes_district_figures, test
    in_planned_development) replaces every district figure. Pass 19: a gate with supersedes_figures replaces only the
    figures it lists, never the lot minimum, so it does not count."""
    if lot.get("in_planned_development") is not True:
        return False
    gates = (_leaf(data, ("eligibility", "gates")) or {}).get("value") or []
    return any(
        g.get("supersedes_district_figures")
        and not g.get("supersedes_figures")
        and g.get("test") == "in_planned_development"
        and not g.get("overlays")
        and _gate_scope(g, lot, historic)
        and _gate_met(g, lot) is not False  # pass 18: a development of another kind (planned_development_kinds)
        for g in gates
    )


def _district_min_binds(data: dict[str, Any]) -> bool:
    """A district minimum lot bars an ADU only when the ADU rule ties to it: requires_conforming_lot,
    or a share of the district minimum. Otherwise an existing smaller lot may be nonconforming."""
    rcl = _leaf(data, ("eligibility", "requires_conforming_lot")) or {}
    conf = rcl.get("value") is True and rcl.get("confidence") == "verified"  # pass 7: a secondary reading never bars
    share = (_leaf(data, ("eligibility", "min_lot_share_of_district")) or {}).get("value")
    return conf or share is not None


def _rcl_reading(data: dict[str, Any]) -> bool:
    """requires_conforming_lot true on a reading that is not verified: shown as a condition with "if"."""
    rcl = _leaf(data, ("eligibility", "requires_conforming_lot")) or {}
    return rcl.get("value") is True and rcl.get("confidence") != "verified"


def _apply_gates(
    by_type: dict[str, str], conditions: list[dict[str, Any]], fallback: str, reasons: list[str], hold: bool = False
) -> list[dict[str, Any]]:
    """Apply the bars the lot fails. Returns the conditions that barred a form here.
    hold: a lot town whose pass 18 sentence fix waits for its next lot rebuild (PASS18_HOLD_TOWNS)."""
    barred: list[dict[str, Any]] = []
    for c in conditions:
        if c["effect"] != "bars" or c["met"] is True or c["kind"] == "lot_area_per_unit":
            continue
        if c.get("overlay_open"):
            continue  # pass 10: the lot's overlays are unknown, so an overlay gate never bars
        if c["met"] is None and c.get("test"):
            continue  # unknown lot fact: allowed if the condition holds
        # a form the code does not name still fails a lot or house bar that reaches it (pass 7)
        hit = [
            t
            for t in (c["applies_to"] or ALL_TYPES)
            if by_type.get(t) in OK_PATHS or by_type.get(t) in ("not_addressed", "in_conflict")
        ]
        for t in hit:
            by_type[t] = fallback
        if hit:
            ch = c.get("outside_zoning_chapter")
            text = c["condition"] if hold else c["condition"].rstrip(".")  # pass 18: never ". (" before the sections
            reasons.append(
                f"{text} ({c['section']}). Not allowed here: {', '.join(t.replace('_', ' ') for t in hit)}"
                + (  # pass 17: relief from a bar in another chapter follows that chapter's own appeal rules
                    f". This bar is in {ch} of the code, not the zoning chapter. Relief from it follows {ch}'s own "
                    "appeal rules"
                    if ch
                    else ""
                )
            )
            barred.append(c)
    return barred


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


def _alt_own_figures(a: dict[str, Any]) -> str:
    """Pass 18: an alternative's own accessory height and parking (alternatives[].accessory_max_height_ft,
    parking_spaces), in words. Empty when it has neither."""
    figs = []
    if a.get("accessory_max_height_ft") is not None:
        figs.append(f"an accessory building up to {a['accessory_max_height_ft']:,.0f} ft tall")
    n = a.get("parking_spaces")
    if n is not None:
        figs.append(f"{n:,.0f} parking space{'' if n == 1 else 's'} for the unit beyond the house's")
    return ("Its own figures: " + " and ".join(figs)) if figs else ""


def _alternatives(data: dict[str, Any], lot: dict[str, Any]) -> list[dict[str, Any]]:
    """Other ways to add a unit: not ADUs, or an ADU under another listing (adu_listing). applies is None when the
    lot facts do not settle it, and False for a path that needs three or more units."""
    leaf = _leaf(data, ("approval", "alternatives")) or {}
    out = []
    for a in leaf.get("value") or []:
        d, area = lot.get("zoning_district"), lot.get("lot_sqft")
        in_d = None if not a.get("districts") or d is None else _match_code(d, a["districts"]) is not None
        if not a.get("districts"):
            in_d = True
        min_lot, by_utility = _alt_min_lot_utility(a, d, lot)
        lot_ok = None if min_lot is None or area is None else area >= min_lot
        tract_open = False
        if a.get("min_lot_is_tract") and min_lot is not None:  # pass 9: the tract, not the lot, meets the minimum
            lot_ok = _tract_met("tract_sqft_at_least", min_lot, lot)
            tract_open = lot_ok is None
        applies = (
            False
            if (in_d is False or lot_ok is False)
            else (True if in_d and lot_ok is not False and (min_lot is None or lot_ok) else None)
        )
        if applies and a.get("min_lot_by_utility") and min_lot is None:
            applies = None  # pass 9: the services decide the lot minimum, and they were not given
        dd = a.get("disputed_districts")  # pass 10: passages of the code disagree on whether it reaches a district
        in_dd = bool(dd) and d is not None and _match_code(d, dd["districts"]) is not None
        if in_dd and applies is True:
            applies = None
        tests = _alt_tests(a, lot)  # pass 7: overlays and tests on the house, prior approval, services
        if applies is not False and tests:
            if any(m is False for m, _ in tests):
                applies = False
            elif any(m is None for m, _ in tests):
                applies = None
        conf = a.get("confidence") or leaf.get("confidence")
        settled = conf == "verified"
        path = a["path"].replace("_", " ") + (
            " with land development plan approval" if a.get("land_development") else ""
        )
        flags = []  # pass 6: what the path needs beyond its listing
        if a.get("land_development"):
            flags.append("Needs land development plan approval as well as zoning, so it is not a plain zoning permit")
        if (a.get("min_units") or 0) > 2:
            flags.append(f"Needs {a['min_units']} or more units in all, so it is not a path for one added unit")
            applies = False
        if a.get("min_lot_is_tract") and a.get("min_lot_sqft"):
            flags.append(
                f"The {a['min_lot_sqft']:,.0f} sq ft minimum is for the development tract"
                + (
                    ". Applies only if the tract is that large: the tract size (tract_sqft) was not given"
                    if tract_open
                    else ""
                )
            )
        if by_utility:
            flags.append(by_utility)
        if in_dd:
            flags.append(
                f"Whether it reaches {d} is disputed: {dd['section']}: {dd['note'].rstrip('.')}. Ask the zoning officer"
            )
        if a.get("min_lot_by_district") and min_lot is not None and min_lot != a.get("min_lot_sqft"):
            flags.append(f"In {d} it needs a lot of at least {min_lot:,.0f} sq ft")
        open_tests = [text for m, text in tests if m is None]
        if open_tests and applies is None:
            flags.append("Applies only if: " + ". ".join(open_tests))
        failed = [text for m, text in tests if m is False]
        if failed:
            flags.append("Not on this lot: " + ". ".join(failed))
        lead = (
            # pass 18: a listing whose standards are reserved has its own path only (no_standards)
            f"An ADU under another listing in the code, with its own path{'' if a.get('no_standards') else ' and standards'}"
            if a.get("adu_listing")
            else "Not an ADU. A second unit by another path"
        )
        if a.get("short_term_rental_only"):  # pass 9: a unit for transient guests only, not a home
            lead += ". It is for short-term rental only, not a long-term home"
        own = _alt_own_figures(a)
        if own:  # pass 18: the listing's own accessory height and parking
            flags.append(own)
        dispute = a.get("disputed_path")
        if dispute:  # pass 9: another passage gives the listing a different path
            path = (
                f"{path} ({a['section']}) or {dispute['path'].replace('_', ' ')} ({dispute['section']}): "
                "the code does not settle which. Ask the zoning officer"
            )
            # pass 13: the display path names both paths with their sections, so the note gives the other reading
            # in words only. Each section list is said once
            other = dispute["note"].rstrip(".")
            other = other[:1].lower() + other[1:] if other[1:2].islower() else other
            flags.append(f"The other reading: {other}")
            settled = True  # the display path says the doubt itself
            conf = "secondary"
        out.append(
            {
                **a,
                "url": a.get("url") or leaf.get("url"),
                "applies": applies,
                "confidence": conf,
                "display_path": path if settled else f"listed as {path}, but ask the zoning officer",
                "note": lead
                + "".join(f". {f}" for f in flags)
                + (f". {a['note']}" if a.get("note") else "")
                # pass 10: a dispute about the path alone says which paths, never a vague "not settled". Pass 13: the
                # display path says them, with their sections, so the note does not repeat them
                + ("" if settled else ". The reading is not settled"),
            }
        )
    return out


def _named_with_listing(
    reasons: list[str],
    at: int,
    named: list[str],
    listed: set[str],
    alts: list[dict[str, Any]],
    nn: dict[str, Any],
) -> None:
    """Pass 18: the "does not name" line, said again once an ADU under another listing is known. Forms the listing
    covers on this lot leave the line (the line goes when none is left). A listing that may cover a form on this lot
    is named in the line (Mount Joy: the Village Design Option apartment in a garage, 135-353E(2)(e))."""
    left = [t for t in named if t not in listed]
    maybe = [
        a
        for a in alts
        if a.get("adu_listing") and a.get("forms") and a["applies"] is None and set(a["forms"]) & set(left)
    ]
    if left == named and not maybe:
        return
    if not left:
        reasons.pop(at)
        return
    reasons[at] = (
        f"The code does not name {', '.join(t.replace('_', ' ') for t in left)} ({nn['section']}). "
        "Not addressed for this form, not a firm no. Ask the zoning officer"
        + (f". {nn['note']}" if nn.get("note") else "")
        + "".join(
            f". {a['name']} ({a['section']}) may cover "
            + ", ".join(t.replace("_", " ") for t in left if t in a["forms"])
            + " on this lot. See the other paths"
            for a in maybe
        )
    )


def _alt_land_bars(
    alts: list[dict[str, Any]], conditions: list[dict[str, Any]], overridden: list[dict[str, Any]]
) -> None:
    """Pass 18: a bar on the land (a gate with overlays, or from another chapter of the code) reaches an alternative
    that builds a form the bar names (alternatives[].builds, or forms for an ADU under another listing). Mount Joy: a
    second principal dwelling (135-295) in the identified floodplain area is new construction that Chapter 70 bars.
    The lot fails it: the alternative does not apply. The lot's overlays not given or the bar disputed: it applies
    only if the lot is clear of it. Every condition loses its _land_bar marker here."""
    bars = [(c, c.pop("_land_bar")) for c in conditions if c.get("_land_bar")]
    for c in overridden:
        c.pop("_land_bar", None)
    for a in alts:
        forms = a.get("builds") or (a.get("forms") if a.get("adu_listing") else None)
        if not forms or a["applies"] is False:
            continue
        lines: dict[str, list[str]] = {}  # lead -> the bars it names, so each lead is said once
        for c, raw in bars:
            if not all(t in (c["applies_to"] or ALL_TYPES) for t in forms):
                continue
            text = f"{raw.rstrip('.')} ({c['section']})"
            if c.get("overlay_open"):
                ov = (
                    c["overlay_names"]
                    if c["overlay_names"].lower().endswith("overlay")
                    else f"{c['overlay_names']} overlay"
                )
                lines.setdefault(f"Not if the lot is in the {ov}", []).append(text)
                a["applies"] = None if a["applies"] is not False else False
            elif c.get("disputed_by"):  # the lot fails it as written, and another passage may undo it
                d = c["disputed_by"]
                lines.setdefault("In doubt on this lot", []).append(
                    f"{text}. But {d['section']}: {d['note'].rstrip('.')}"
                )
                a["applies"] = None if a["applies"] is not False else False
            elif c["met"] is False or (
                c["met"] is None and not c.get("test")
            ):  # a bar with no test holds where it reaches
                lines.setdefault("Not on this lot", []).append(text)
                a["applies"] = False
            elif c["met"] is None:
                lines.setdefault("Not if the lot fails this", []).append(text)
                a["applies"] = None if a["applies"] is not False else False
        if lines:
            a["note"] = a["note"] + "".join(f". {lead}: {'. '.join(texts)}" for lead, texts in lines.items())


# Pass 15: conditions of the ADU rule on who may live in the unit, the house type and the districts it reaches. A form
# allowed under another listing (an alternative with adu_listing and forms) is not held to them.
OCCUPANT_KINDS = {
    "adu_status",
    "family",
    "occupancy",
    "owner_occupancy",
    "age",
    "care",
    "sponsor",
    "building_type",
    "district",
    "scope",
}


def _listing_forms(
    alts: list[dict[str, Any]], by_type: dict[str, str], conditions: list[dict[str, Any]]
) -> tuple[list[str], set[str]]:
    """Pass 15: approval.alternatives[].forms. An ADU under another listing (adu_listing) that names the forms it
    covers, and reaches this lot, gives those forms its own path when that path is less demanding (Bloomsburg's
    'Apartment, Accessory', a unit inside the house, by right in R-S, R-U, C-R, MX-1, MX-3, C-W and BC). The ADU rule's
    occupancy conditions then do not reach those forms. Returns the sentences that say so and the forms it frees."""
    lines = []
    freed: set[str] = set()
    for a in alts:
        if not (a.get("adu_listing") and a.get("forms") and a["path"] in OK_PATHS and a["applies"] is True):
            continue
        forms = [t for t in ALL_TYPES if t in a["forms"] and PATH_ORDER.index(a["path"]) < PATH_ORDER.index(by_type[t])]
        if not forms:
            continue
        for t in forms:
            by_type[t] = a["path"]
        freed.update(forms)
        names = ", ".join(t.replace("_", " ") for t in forms)
        lines.append(
            f"{names[:1].upper()}{names[1:]}: {a['path'].replace('_', ' ')} under another "
            f"listing in the code, {a['name']} ({a['section']}). That listing has its own path"
            + ("" if a.get("no_standards") else " and standards")
            + (f". {_alt_own_figures(a)}" if _alt_own_figures(a) else "")
            + ". The ADU "
            "rule's family, occupancy and house type conditions do not reach it"
            + ("" if a.get("confidence") == "verified" else ". The reading is not settled. Ask the zoning officer")
            + ". See the other paths"
        )
    if freed:
        for c in list(conditions):
            if c["kind"] in OCCUPANT_KINDS:
                reach = [t for t in (c.get("applies_to") or ALL_TYPES) if t not in freed]
                if reach:
                    c["applies_to"] = reach
                else:
                    conditions.remove(c)
    return lines, freed


def _adus_by_lot(data: dict[str, Any], lot: dict[str, Any]) -> tuple[int | None, str, dict[str, Any]] | None:
    """Pass 9: use.max_adus_by_lot_size. (ADUs on this lot or None when the size is not given, sentence, leaf)."""
    leaf = _leaf(data, ("use", "max_adus_by_lot_size"))
    if not (_usable(leaf) and leaf.get("value")):
        return None
    rows = []
    for it in leaf["value"]:
        strict = it.get("lot_sqft_over") is not None
        t = it["lot_sqft_over"] if strict else (it.get("lot_sqft_at_least") or 0)
        tract = it.get("basis") == "tract"
        if t <= 0:
            met: bool | None = True
        elif tract:
            met = _tract_met("tract_sqft_at_least", t, lot, strict)
        else:
            area = lot.get("lot_sqft")
            met = None if area is None else (area > t if strict else area >= t)
        rows.append((t, it, met, tract, strict))
    rows.sort(key=lambda r: r[0])
    parts = []
    for t, it, _, tract, strict in rows:
        where = (
            "any lot"
            if t <= 0
            else f"a {'tract' if tract else 'lot'} {'over' if strict else 'of at least'} {t:,.0f} sq ft"
        )
        parts.append(
            f"{it['max_adus']} on {where}"
            + (
                f", each unit after the first at most {it['extra_unit_max_sqft']:,.0f} sq ft"
                if it.get("extra_unit_max_sqft")
                else ""
            )
        )
    pick = None
    for i, (_, it, met, _, _) in enumerate(rows):
        if met is True and all(r[2] is False for r in rows[i + 1 :]):
            pick = it
    basis = "tract" if any(r[3] for r in rows) else "lot"
    line = f"ADUs per lot by size ({leaf['section']}): " + ", ".join(parts)  # pass 12: no semicolons
    if pick is None:
        line += f". This lot: depends on the {basis} size, which was not given" + (
            " (the tract is the parent tract, tract_sqft)" if basis == "tract" else ""
        )
    else:
        line += f". This lot: {pick['max_adus']}" + (
            f", a unit after the first at most {pick['extra_unit_max_sqft']:,.0f} sq ft"
            if pick.get("extra_unit_max_sqft")
            else ""
        )
    if leaf.get("note"):
        line += f". {leaf['note']}"
    return (pick["max_adus"] if pick else None), line, leaf


def _acres(v: float) -> str:
    """Pass 12: a lot area in sq ft, with acres when it is a whole or half number of acres."""
    ac = v / 43560
    return f"{v:,.0f} sq ft" + (f" ({ac:g} acres)" if ac >= 1 and (ac * 2).is_integer() else "")


def _size_by_lot(data: dict[str, Any], lot: dict[str, Any]) -> tuple[float | None, str, dict[str, Any]] | None:
    """Pass 12: size.max_sqft_by_lot_size, a size cap that grows with lot area. (the cap for this lot, or None when
    the lot area is not given or no tier reaches it; the sentence; the leaf)."""
    leaf = _leaf(data, ("size", "max_sqft_by_lot_size"))
    if not (_usable(leaf) and leaf.get("value")):
        return None
    area = lot.get("lot_sqft")
    parts, pick, gap = [], None, False
    for it in leaf["value"]:
        bounds = []
        if it.get("lot_sqft_over") is not None:
            bounds.append(f"over {_acres(it['lot_sqft_over'])}")
        if it.get("lot_sqft_at_least") is not None:
            bounds.append(f"of at least {_acres(it['lot_sqft_at_least'])}")
        if it.get("lot_sqft_below") is not None:
            bounds.append(f"under {_acres(it['lot_sqft_below'])}")
        if it.get("lot_sqft_at_most") is not None:
            bounds.append(f"of {_acres(it['lot_sqft_at_most'])} or less")
        parts.append(f"{it['max_sqft']:,.0f} sq ft on a lot {' and '.join(bounds) if bounds else 'of any size'}")
        if area is None:
            continue
        ok = (
            (it.get("lot_sqft_over") is None or area > it["lot_sqft_over"])
            and (it.get("lot_sqft_at_least") is None or area >= it["lot_sqft_at_least"])
            and (it.get("lot_sqft_below") is None or area < it["lot_sqft_below"])
            and (it.get("lot_sqft_at_most") is None or area <= it["lot_sqft_at_most"])
        )
        if ok and pick is None:
            pick = it
    if area is not None and pick is None:
        gap = True
    line = f"Size cap by lot area ({leaf['section']}): at most " + ", ".join(parts)
    if pick is not None:
        line += f". This lot: at most {pick['max_sqft']:,.0f} sq ft"
    elif gap:
        line += f". The code gives no figure for a lot of {area:,.0f} sq ft. Ask the zoning officer"
    else:
        line += ". This lot: depends on the lot area, which was not given"
    if leaf.get("note"):
        line += f". {leaf['note']}"
    return (pick["max_sqft"] if pick else None), line, leaf


def _exempt_met(ex: dict[str, Any], form: str, lot: dict[str, Any]) -> tuple[bool | None, list[str]]:
    """Pass 9: whether the building for this form meets size.exempt_building, and the facts not given."""
    met: bool | None = True
    open_facts = []
    years = ex.get("older_than_years")
    if years:
        key = "house_year_built" if form in PRINCIPAL_TYPES else "accessory_building_year_built"
        year = lot.get(key)
        if form not in PRINCIPAL_TYPES and lot.get("has_accessory_building") is False:
            return False, []
        cut = datetime.date.today().year - years
        if year is None or int(year) == cut:
            met, open_facts = None, [f"the year the building was built ({key})"]
        elif int(year) > cut:
            return False, []
    if ex.get("historic"):
        h = lot.get("historic_resource")
        h = True if lot.get("historic_individual") else h
        if h is False:
            return False, []
        if h is None:
            met = None
            open_facts.append("whether it is a historic resource (historic_resource)")
    return met, open_facts


def _exempt_frees(data: dict[str, Any], form: str, lot: dict[str, Any], cap: str) -> bool:
    """Pass 9: size.exempt_building frees this form of this cap on this lot."""
    leaf = _leaf(data, ("size", "exempt_building"))
    ex = (leaf or {}).get("value") if _usable(leaf) else None
    if not isinstance(ex, dict):
        return False
    return form in ex["forms"] and cap in ex["caps"] and _exempt_met(ex, form, lot)[0] is True


def _exempt_caps_words(caps: list[str]) -> str:
    """Pass 14: the caps an exempt building is free of, joined with "or" ("setbacks or ADU height limit")."""
    words = {"size": "floor area cap", "height": "ADU height limit", "setbacks": "setbacks"}
    named = [words.get(c, c.replace("_", " ")) for c in caps]
    return named[0] if len(named) == 1 else ", ".join(named[:-1]) + " or " + named[-1]


def _exempt_building(
    data: dict[str, Any],
    lot: dict[str, Any],
    by_type: dict[str, str],
    sizes: dict[str, float | None],
    shares: dict[str, float | None],
    size_rules: dict[str, str | None],
    heights: dict[str, float | None],
    setbacks: dict[str, dict[str, float | None]],
) -> list[str]:
    """Pass 9: size.exempt_building. A unit in a building that qualifies has no cap of the kinds named. With a fact
    not given the caps stay and the sentence says the exemption."""
    leaf = _leaf(data, ("size", "exempt_building"))
    if not (_usable(leaf) and leaf.get("value")):
        return []
    ex = leaf["value"]
    what = ex.get("what") or "a qualifying existing building"
    caps = ex["caps"]
    # pass 14: "no setbacks or ADU height limit", never "no setbacks, ADU height limit"
    none_of = _exempt_caps_words(caps)
    lines = []
    for t in ex["forms"]:
        if by_type.get(t) not in OK_PATHS:
            continue
        met, open_facts = _exempt_met(ex, t, lot)
        if met is False:
            continue
        if met is True:
            if "size" in caps:
                sizes[t], shares[t] = None, None
                size_rules[t] = f"No floor area cap: {what} ({leaf['section']})"
            if "height" in caps:
                heights[t] = None
            if "setbacks" in caps:
                setbacks[t] = {k: None for k in YARDS}
            lines.append(f"{t.replace('_', ' ').capitalize()}: {what} has no {none_of} ({leaf['section']})")
        else:
            lines.append(
                f"{t.replace('_', ' ').capitalize()}: {what} has no {none_of} "
                f"({leaf['section']}). The caps shown hold unless the building qualifies. Depends on "
                f"{' and '.join(open_facts)}, which {'was' if len(open_facts) == 1 else 'were'} not given"
            )
    return lines


def _depends_on(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bars and service rows whose lot or house fact was not given: the answer depends on them."""
    out = []
    for c in conditions:
        test = c.get("test")
        if c.get("overlay_open") and c["effect"] == "bars" and not test:
            # pass 12: a bar only inside an overlay, on a lot whose overlays were not given
            out.append(
                {
                    "fact": f"whether the lot is in the {c['overlay_names']} overlay (overlays)",
                    "test": "overlays",
                    "condition": c["condition"],
                    "section": c["section"],
                    "applies_to": c["applies_to"],
                    "effect": c["effect"],
                    "overlays": c["overlay_names"],
                }
            )
            continue
        if not test or c["met"] is not None or (c["effect"] != "bars" and c["kind"] != "utilities"):
            continue
        fact = (
            (c.get("fact") if test == "in_planned_development" else None)  # pass 18: the kind decides it
            or HOUSE_TESTS.get(test)
            or LOT_TESTS.get(test)
            or c.get("fact")
            or "whether the lot has public sewer and water"
        )
        out.append(
            {
                "fact": fact,
                "test": test,
                "condition": c["condition"],
                "section": c["section"],
                "applies_to": c["applies_to"],
                "effect": c["effect"],
            }
        )
    return out


def _alt_min_lot(a: dict[str, Any], d: Any) -> float | None:
    """An alternative's lot minimum: min_lot_by_district for the lot's district, else min_lot_sqft."""
    by = a.get("min_lot_by_district") or {}
    hit = _match_code(d, list(by)) if d and by else None
    return by[hit] if hit is not None else a.get("min_lot_sqft")


def _alt_min_lot_utility(a: dict[str, Any], d: Any, lot: dict[str, Any]) -> tuple[float | None, str | None]:
    """Pass 9: (lot minimum, sentence). min_lot_by_utility picks the minimum by the lot's public sewer and water.
    With the services not given, the largest minimum is the test (a lot that meets it meets them all) and the
    sentence names each figure. Otherwise _alt_min_lot."""
    rows = a.get("min_lot_by_utility") or []
    if not rows:
        return _alt_min_lot(a, d), None
    for r in rows:
        if _utility_match(r, lot) is True:
            return r["min_lot_sqft"], f"Lot minimum {r['when']}: {r['min_lot_sqft']:,.0f} sq ft"
    known = [r for r in rows if _utility_match(r, lot) is not False]
    if not known:  # pass 13: the services were given and no row fits them. Never "not given"
        if _base_services(rows, lot):
            return _alt_min_lot(a, d), None  # the listing's own figure is the one with the public services
        figs = ", ".join(f"{r['when']}: {r['min_lot_sqft']:,.0f} sq ft" for r in rows)
        return (
            None,
            f"The code gives no lot minimum for a lot with {_services_words(lot)}, only for other services ({figs})",
        )
    figs = ", ".join(f"{r['when']}: {r['min_lot_sqft']:,.0f} sq ft" for r in known or rows)  # pass 12: no semicolons
    area = lot.get("lot_sqft")
    top = max(r["min_lot_sqft"] for r in known or rows)
    low = min(r["min_lot_sqft"] for r in known or rows)
    text = f"The lot minimum depends on public sewer and water ({figs}), which were not given"
    if area is not None and low <= area < top:
        return None, text  # the services decide it: never a yes or a no
    return (top if area is None or area >= top else low), text


def _base_services(rows: list[dict[str, Any]], lot: dict[str, Any]) -> bool:
    """Pass 13: the figures outside the rows are for a lot with the public services the rows name. True unless the
    lot lacks one of them (public sewer, public water) by a fact given."""
    named = [f for f in ("public_sewer", "public_water") if any(r.get(f) is not None for r in rows)]
    return not any(lot.get(f) is False for f in named)


def _services_words(lot: dict[str, Any]) -> str:
    """Pass 13: the lot's given services in plain words ("no public sewer and public water")."""
    have = [ROW_FACTS[f] for f in ("public_sewer", "public_water") if lot.get(f) is True]
    lack = ["no " + ROW_FACTS[f] for f in ("public_sewer", "public_water") if lot.get(f) is False]
    return " and ".join(have + lack) or "these services"


def _alt_tests(a: dict[str, Any], lot: dict[str, Any]) -> list[tuple[bool | None, str]]:
    """(met, plain words) for an alternative's overlays and requires items. A requires item with no test is a fact
    the tool cannot know (a prior approval, a listed building): never met, never failed."""
    out: list[tuple[bool | None, str]] = []
    if a.get("overlays"):
        ov = lot.get("overlays")
        met = None if ov is None else any(_match_code(o, a["overlays"]) is not None for o in ov)
        out.append((met, f"the lot is in the {' or '.join(a['overlays'])} overlay"))
    for r in a.get("requires") or []:
        test = r.get("test")
        if test in HOUSE_TESTS:
            met = _house_met(test, r.get("value"), r.get("value_date"), lot)
        elif test in LOT_TESTS:
            met = _gate_met(r, lot)
        else:
            met = None
        text = r["condition"].rstrip(".") + (f" ({r['section']})" if r.get("section") else "")
        if met is None and test in HOUSE_TESTS:
            text += f". Depends on {HOUSE_TESTS[test]}, which was not given"
        out.append((met, text))
    return out


def _resolve_town(place: str, scenario: str, lot: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    limits: dict[str, Any] = {}
    file_data = load_rules(place)
    scope = _scope(file_data, lot)
    data = _outside_scope_data(file_data, scope, lot) if scope["in_scope"] is False else file_data
    hist_leaf = _leaf(data, ("approval", "historic_path"))
    historic = False
    if (_leaf(data, ("eligibility", "historic_bypass")) or {}).get("value") or (
        _usable(hist_leaf) and hist_leaf.get("value")
    ):
        historic = _historic_town(data, lot, reasons)
    picked, today, how, principal = _pick_town(data, place, scenario, lot, historic, limits, reasons)
    tier = _size_by_lot(data, lot)
    if tier:  # pass 12: the size cap by lot area replaces size.max_sqft (a district's own cap still wins)
        for p in (picked, today):
            if "#districts." not in (p.get(("size", "max_sqft")) or ({}, ""))[1]:
                p[("size", "max_sqft")] = ({**tier[2], "value": tier[0]}, f"{place}#size.max_sqft_by_lot_size")
    state = scenario == "state_reform"
    tiers_out = _apply_yard_tiers(data, picked, principal, lot, reasons)
    status_leaf = _leaf(data, ("adu", "status")) or {}
    status = status_leaf.get("value")
    term = (_leaf(file_data, ("adu", "term")) or {}).get("value")

    fails = _overlay_fails(picked, lot, historic, reasons) + ([] if historic else _base_fails(picked, lot))
    if how in ("district", "historic"):
        fails = [f for f in fails if not f.startswith("Zoned ")]
    fails = [_reword_zoned(f) for f in fails]
    if scope.get("use_open"):  # pass 8: a district whose use list is not on file is not a firm no
        fails = [f for f in fails if not f.startswith("The ADU rule applies only in ")]
    dm = _district_min(data, lot)
    area = lot.get("lot_sqft")
    dm_binds = _district_min_binds(data)
    if dm and dm_binds and not historic and not state and area is not None and area < dm[1]:
        leaf, need, share = dm
        fails.append(
            (
                "The lot minimum for the lot's sewer and water is"
                if place not in PASS18_HOLD_TOWNS and _min_lot_by_services(data, lot)
                else "The district's minimum lot is"
            )
            + f" {leaf['value']:,.0f} sq ft ({leaf['section']})"
            + (f". The ADU rule accepts {share:.0%} of it, {need:,.0f} sq ft" if share != 1 else "")
            + f". This lot is {area:,.0f} sq ft, so any new use needs relief"
        )
    dens = _density(data, lot)
    if dens and dens[2] and not state and area is not None and area < dens[1]:
        per, need, _ = dens
        fails.append(
            f"{per['value']:,.0f} sq ft of lot per dwelling unit ({per['section']}). The house and the ADU need "
            f"{need:,.0f} sq ft. This lot is {area:,.0f} sq ft"
        )
    # Under the bill a district in doubt is opened like any other district (pass 7)
    hold = place in LOT_RECORD_TOWNS
    doubt_hold = place in DOUBT_HOLD_TOWNS
    doubt = (
        _in_doubt(data, lot, doubt_hold) if not state and not historic and how not in ("district", "historic") else None
    )
    doubt_line: list[str] = []
    if doubt:  # listed in the district, while the ADU section names other districts: ask, never a plain no
        fails = [f for f in fails if not f.startswith("The ADU rule applies only in ")]
        # pass 11: the doubt is not a failed test. The path to ask, qualified, never a variance for the doubt alone
        (fails if doubt_hold else doubt_line).append(doubt["reason"])
    no_district = None
    if not state and not historic and how not in ("district", "historic") and place not in PASS17_HOLD_TOWNS:
        no_district = _no_district(data, picked, scope, lot)
    if no_district:  # pass 17: the lot's district is not known. Ask, never "zoned unknown" and a variance
        fails = [f for f in fails if not f.startswith("The ADU rule applies only in ")]
    fallback = _value(picked, "approval", "fallback_path") or "variance"
    base = _value(picked, "approval", "path") or "not_allowed"
    eligible = not fails and base != "not_allowed"
    allowed_forms = _form_types_town(picked, lot)
    yard = _value(picked, "approval", "detached_in_yard_path")
    form_paths = [] if state else ((_leaf(data, ("approval", "form_paths")) or {}).get("value") or [])
    form_paths = form_paths + ([] if state else _gate_paths(data, lot, historic))  # pass 16: a gate's own path
    by_form_leaf = _leaf(data, ("adu", "status_by_form"))
    by_form = (by_form_leaf or {}).get("value") or None
    not_named = [] if state else ((_leaf(data, ("form", "types_not_addressed")) or {}).get("value") or [])
    conflict_leaf = None if state else _leaf(data, ("form", "types_in_conflict"))
    in_conflict = (conflict_leaf or {}).get("value") or []  # pass 9: the code's own passages conflict on the form
    # A lot that fails a district, type or size test needs a variance. A fallback of special exception
    # or conditional use (for example a district path) does not cure that.
    fail_path = fallback if (not fails or fallback not in OK_PATHS) else "variance"
    # pass 12: a form the code bars still has a use variance to ask for, unless the code bars use variances here
    form_bar = _form_variance_barred(data, lot)
    by_type = {}
    for t in ALL_TYPES:
        path = base if (eligible and t in allowed_forms) else (fail_path if fails else fallback)
        if eligible and t == "detached_new" and t in allowed_forms and yard:
            path = yard
        for item in form_paths if (eligible and t in allowed_forms) else []:
            if t in item["forms"]:  # a form's own path: the more demanding of the two
                path = max(path, item["path"], key=PATH_ORDER.index)
        if not state and by_form and by_form.get(t) in NO_ADU_STATUSES and path in OK_PATHS:
            path = fallback if fallback not in OK_PATHS else "variance"
        if not state and by_form and by_form.get(t) == "prohibited":
            # pass 7: the code bars this form. Pass 12: a use variance is still the path, unless use variances are barred
            path = "not_allowed" if form_bar else "variance"
        elif eligible and t in in_conflict and t not in allowed_forms and path not in OK_PATHS:
            path = "in_conflict"  # pass 12: the code's own passages conflict on the form (pass 9). Not a firm no
        elif eligible and t in not_named and t not in allowed_forms and path not in OK_PATHS:
            path = "not_addressed"  # pass 7: the code does not name this form. Not a firm no
        by_type[t] = path
    barred_forms = [] if state or not by_form else [t for t in ALL_TYPES if by_form.get(t) == "prohibited"]
    no_rule_lot = status in NO_ADU_STATUSES and how not in ("district", "historic")
    if barred_forms and by_form_leaf:
        words = [t.replace("_", " ") for t in barred_forms]
        names = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
        if form_bar:
            reasons.append(
                f"The code bars {names} ({by_form_leaf['section']}), and it bars a use variance too "
                f"({form_bar['section']}). Not allowed, not a variance to ask for"
            )
        elif no_rule_lot:  # the use variance path is said below, with its sections
            reasons.append(
                f"The code bars {names} ({by_form_leaf['section']}). A use variance is still a path for them"
            )
        else:
            reasons.append(
                f"The code bars {names} ({by_form_leaf['section']}). A use variance from the Zoning Hearing Board "
                "is still a path to ask for (MPC 910.2). The owner must show unnecessary hardship"
            )
    conflict_out = [t for t in ALL_TYPES if by_type[t] == "in_conflict"]
    if conflict_out and conflict_leaf:
        reasons.append(
            f"The code's text conflicts on {', '.join(t.replace('_', ' ') for t in conflict_out)} "
            f"({conflict_leaf['section']}). Not settled, so neither a yes nor a firm no. Ask the zoning officer"
            + (f". {conflict_leaf['note']}" if conflict_leaf.get("note") else "")
        )
    named_out = [t for t in ALL_TYPES if by_type[t] == "not_addressed" and t not in conflict_out]
    named_at = len(reasons)  # pass 18: the line is said again below when another listing covers its forms
    if named_out:
        nn = _must_leaf(data, ("form", "types_not_addressed"))
        reasons.append(
            f"The code does not name {', '.join(t.replace('_', ' ') for t in named_out)} ({nn['section']}). "
            "Not addressed for this form, not a firm no. Ask the zoning officer"
            + (f". {nn['note']}" if nn.get("note") else "")
        )
    conditions = _town_conditions(
        data,
        today if state else picked,
        lot,
        historic,
        how,
        scope,
        hold,
        place in PASS13_HOLD_TOWNS,
        place in PASS14_HOLD_TOWNS,
        place in PASS15_HOLD_TOWNS,
        place in PASS18_HOLD_TOWNS,
    )
    overridden: list[dict[str, Any]] = []
    chapter_bars: list[dict[str, Any]] = []
    if state:  # under the bill the town's gates show as conditions only, and some no longer apply
        live: list[dict[str, Any]] = []
        for c in conditions:
            (overridden if (c["kind"] in BILL_OVERRIDES or c.get("bill_overrides")) else live).append(c)
        for c in overridden:
            c["note"] = BILL_NOTE
        h_floor = (limits.get("max_height_ft") or {}).get("value")
        for c in [c for c in live if c["kind"] == "height" and h_floor is not None and c["max_height_ft"] < h_floor]:
            live.remove(c)
            c["note"] = (
                "Under HB 2186 (not law) the town must allow at least the bill's height floor, so this cap gives way"
            )
            overridden.append(c)
        size_floor = limits.get("max_size_sqft")
        for c in [c for c in live if c["kind"] == "size"]:
            live.remove(c)
            c["note"] = (
                "Under HB 2186 (not law) the town must allow at least the bill's size floor, so this cap gives way where it is lower"
            )
            overridden.append(c)
        if size_floor:
            fl = size_floor["for_this_lot"]
            reasons.append(
                "Size under HB 2186 (not law): the town must allow at least "
                + (f"{fl:,.0f} sq ft on this lot, " if fl is not None else "")
                + f"the lesser of 50 percent of the house or {size_floor['value']:,.0f} sq ft ({size_floor['section']})"
            )
        kept = _bill_keeps(picked, data, lot)
        if kept:
            if place not in PASS14_HOLD_TOWNS:  # pass 14: each kept rule its own sentence, capitalised
                kept = kept[:1] + [k[:1].upper() + k[1:] for k in kept[1:]]
            reasons.append("Town lot rules the bill does not address still apply: " + ". ".join(kept))
        conditions = live
    else:
        n_fails = len(fails)
        gate_bars = _apply_gates(by_type, conditions, fallback, fails, place in PASS18_HOLD_TOWNS)
        # pass 17: the lot fails only bars from another chapter of the code. Relief follows that chapter's own appeal
        # rules, never the zoning chapter's variance section
        if gate_bars and not n_fails and all(c.get("outside_zoning_chapter") for c in gate_bars):
            chapter_bars = gate_bars
    alts = _alternatives(file_data, lot)
    _alt_land_bars(alts, conditions, overridden)  # pass 18: a bar on the land reaches the other paths too
    listing_line, listed = ([], set()) if state else _listing_forms(alts, by_type, conditions)
    if named_out and not state:
        _named_with_listing(
            reasons, named_at, named_out, listed, alts, _must_leaf(data, ("form", "types_not_addressed"))
        )
    types_allowed = [t for t in ALL_TYPES if by_type[t] in OK_PATHS]
    allowed = bool(types_allowed)
    depends = [] if state else _depends_on(conditions)
    no_rule_here = not state and status in NO_ADU_STATUSES and how not in ("district", "historic")
    barred = _use_variance_barred(file_data, lot, scope) if no_rule_here and not allowed else None
    if barred:  # pass 11: the code bars a use variance here, so not allowed, never a variance to ask for
        for t in ALL_TYPES:
            if by_type[t] == "variance":
                by_type[t] = "not_allowed"
    approval = min(by_type.values(), key=PATH_ORDER.index)
    if no_rule_here:  # pass 14: below the district minimum with no ADU rule, never "whether an ADU is allowed on it"
        for c in conditions:
            if c["kind"] == "district_lot_rule" and c["met"] is False:
                c["condition"] = c["condition"].replace(
                    "Ask the zoning officer whether an ADU is allowed on it",
                    "The code has no ADU rule here, so "
                    + (
                        "the path is the same use variance"
                        if approval == "variance"
                        else "the lot size does not change the path"
                    ),
                )
    # No ADU rule here. A hearing path for a use the code does not list is a path to ask for, not an ADU allowed.
    path_to_ask = None
    lead = "The code bars ADUs here" if status == "prohibited" else "The code has no ADU rule here"
    if no_rule_here and allowed and not set(types_allowed) <= listed:
        ask = picked[("approval", "path")]
        similar = _unlisted_similar(data, lot) if how == "unlisted" else None
        if similar:  # pass 12: the unlisted-use path reaches only uses similar to the listed ones
            note = (
                f"{lead}. A use similar in nature to a use the district lists may be authorized by "
                f"{_path_words(ask[0])} ({ask[0]['section']})"
                + (f": '{similar['quote']}'" if similar.get("quote") else "")
                + ". Whether an ADU is similar is not settled, so ask the zoning officer. "
                "That is a hearing with no set standards for an ADU"
            )
        elif how == "unlisted":
            note = (
                f"{lead}. A use that is not listed may be authorized by "
                f"{_path_words(ask[0])} ({ask[0]['section']}). That is a hearing with no set standards for an ADU"
            )
        else:
            note = (
                f"{lead}. The rule file gives {_path_words(ask[0])} "
                f"({ask[0]['section']}) as the path to ask about. Ask the zoning officer"
            )
        path_to_ask = {"path": ask[0]["value"], "section": ask[0]["section"], "url": ask[0].get("url"), "note": note}
        types_allowed = [t for t in types_allowed if t in listed]  # pass 15: a form under another listing stays allowed
        allowed = bool(types_allowed)
    elif barred:
        quote = barred.get("quote")
        path_to_ask = {
            "path": "not_allowed",
            "section": barred["section"],
            "url": barred.get("url"),
            "note": f"{lead}, and the code itself bars a use variance for it ({barred['section']})"
            + (f": '{quote}'" if quote else "")
            + ". That is a local limit on a power the Zoning Hearing Board has under the state planning code "
            "(MPC 910.2), so whether it holds is a legal question: ask the zoning officer or a lawyer. "
            "The route the code leaves is a zoning amendment" + (f". {barred['note']}" if barred.get("note") else ""),
            "kind": "use_variance_barred",
        }
    elif no_rule_here and not allowed and approval in ("variance", "not_allowed"):
        hit = picked.get(("approval", "fallback_path")) or picked.get(("approval", "path"))
        sec = (hit[0]["section"] if hit else "") or ""
        sec = sec if "910.2" in sec else (f"{sec}, MPC 910.2" if sec else "MPC 910.2")
        path_to_ask = {
            "path": "variance",
            "section": sec,
            "url": hit[0].get("url") if hit else None,
            "note": f"{lead}. The path is a use variance from the Zoning Hearing Board ({sec}). "
            f"The owner must show unnecessary hardship",
        }
    elif no_district and allowed:
        path_to_ask = {
            "path": approval,
            "section": no_district["section"],
            "url": no_district["url"],
            "note": f"{approval.replace('_', ' ').capitalize()} only if {no_district['reason']}",
            "kind": "district_unknown",
        }
    elif doubt and not state:
        ask = picked[("approval", "path")]
        path_to_ask = {
            "path": ask[0]["value"],
            "section": doubt["section"],
            "url": doubt["url"],
            "note": doubt["reason"],
            "kind": "listed_in_doubt",
        }
    elif allowed and not state:
        path_to_ask = _hearing_to_ask(picked, by_type, types_allowed, approval)
    if not allowed and picked.get(("approval", "path"), ({}, ""))[1] == DEFAULT:
        fails.append("No ADU rule on file for this place")

    fb_hit = picked.get(("approval", "fallback_path")) or picked.get(("approval", "path"))
    fb = {
        "path": fallback,
        "section": fb_hit[0]["section"] if fb_hit else None,
        "url": fb_hit[0].get("url") if fb_hit else None,
        "note": fb_hit[0].get("note") if fb_hit else None,
    }
    if chapter_bars and not allowed:  # pass 17: the bar's own sections, and the zoning variance section is not the path
        chs = list(dict.fromkeys(c["outside_zoning_chapter"] for c in chapter_bars))
        secs = list(dict.fromkeys(c["section"] for c in chapter_bars if c.get("section")))
        fb = {
            "path": fallback,
            "section": ", ".join(secs) or None,
            "url": chapter_bars[0].get("url"),
            "note": f"Relief under {' and '.join(chs)}, not the zoning chapter's variance section ({fb['section']}). "
            "Ask the zoning officer"
            if fb["section"]
            else f"Relief under {' and '.join(chs)}. Ask the zoning officer",
        }
    checks = list(file_data["provenance"].get("checks", []))
    if state:
        checks = [f"Today, before the bill: {c}" for c in checks] + _checks(place, scenario)
    head = []
    caution = file_data["provenance"].get("code_caution")
    if caution:
        head.append(f"Code caution: {caution}")
    if status and status != "allowed_by_right" and status_leaf.get("section"):
        when = "Today the" if state else "The"
        dp_less = (
            how == "district"
            and status in BOARDS
            and PATH_ORDER.index(picked[("approval", "path")][0]["value"]) < PATH_ORDER.index(status)
        )
        if dp_less:  # pass 8: the district path is less demanding than the town status, so it leads
            dp0 = picked[("approval", "path")][0]
            head.append(
                f"In {lot.get('zoning_district')} the district path is {dp0['value'].replace('_', ' ')} ({dp0['section']}). "
                f"{when} code's ADU status elsewhere is {status.replace('_', ' ')} ({status_leaf['section']})"
            )
        elif how == "historic" and status in NO_ADU_STATUSES and _usable(hist_leaf):
            # pass 9: a historic-only path allows the unit. Never "not addressed" beside "allowed" with no word of it
            head.append(
                f"{when} code has no general ADU rule (status {status.replace('_', ' ')}, {status_leaf['section']}). "
                f"On this lot the historic path applies: {hist_leaf['value'].replace('_', ' ')} ({hist_leaf['section']})"
            )
        elif how == "district" and status in NO_ADU_STATUSES:
            dp0 = picked[("approval", "path")][0]
            head.append(
                f"{when} code's ADU status town-wide is {status.replace('_', ' ')} ({status_leaf['section']}). "
                f"In {lot.get('zoning_district')} the district path applies: {dp0['value'].replace('_', ' ')}"
                + (f" for the '{dp0['term']}' listing" if dp0.get("term") else "")
                + f" ({dp0['section']})"
            )
        else:
            head.append(
                f"{when} code's ADU status is {status.replace('_', ' ')} ({status_leaf['section']})"
                + (f". {status_leaf['note']}" if status_leaf.get("note") and status in NO_ADU_STATUSES else "")
            )
    if by_form and by_form_leaf:
        when = "Today, by form" if state else "By form"
        head.append(
            f"{when}: "
            + ", ".join(f"{t.replace('_', ' ')} {v.replace('_', ' ')}" for t, v in by_form.items())  # pass 12
            + f" ({by_form_leaf['section']})"
        )
    if scope["districts"] and scope["in_scope"] is not True:
        line = _scope_line(scope, lot, with_section=True)
        if scope.get("in_doubt") and doubt:  # pass 18: the doubt line below says it, so the scope line says it never
            line = f"The ADU rule reaches {', '.join(scope['districts'])} ({scope['section']})"
        head.append(line)
    if not state and not allowed and (status in NO_ADU_STATUSES or scope["in_scope"] is False):
        # pass 9: an overlay-keyed ADU listing reaches this lot (or may): said beside "no ADU rule", never hidden
        for a in alts:
            if a.get("adu_listing") and a.get("overlays") and a["applies"] is not False:
                head.append(
                    f"An ADU under another listing may apply on this lot: {a['name']}, {a['display_path']}"
                    + ("" if a.get("disputed_path") else f" ({a['section']})")
                    + (
                        (
                            f". Only if the lot is in the {' or '.join(a['overlays'])} overlay"
                            if lot.get("overlays") is None
                            else ". It depends on lot facts that were not given"
                        )
                        if a["applies"] is None
                        else ""
                    )
                    + ". See the other paths"
                )
    tail = []
    if path_to_ask:
        if path_to_ask.get("kind") not in ("hearing", "listed_in_doubt", "district_unknown"):  # said in the reasons
            tail.append(path_to_ask["note"])
            if fb["note"] and path_to_ask["path"] == "variance":
                tail.append(fb["note"])
    elif not allowed:
        sec = fb["section"] or ""
        if fallback == "variance" and "910.2" not in sec and not (chapter_bars and not allowed):
            sec = f"{sec}, variance standards MPC 910.2" if sec else "variance standards MPC 910.2"
        tail.append(
            f"Not allowed as of right here. Path: {fallback.replace('_', ' ')}"
            + (f" ({sec})" if sec else "")
            + (f". {fb['note']}" if fb["note"] else "")
        )
    out: dict[str, Any] = {
        "allowed": allowed,
        "approval_path": approval,
        "reasons": head
        + reasons
        + fails
        + doubt_line
        + listing_line
        + tail
        + _town_type_reasons(_cap_in_scope(data, picked, lot), by_type, place in PASS12_HOLD_TOWNS)
        + checks,
        "types_allowed": types_allowed,
    }
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
        if key == "max_share_of_house" and value is None and picked.get(("size", "max_share_of_house_and_unit")):
            # pass 9: the headline share is the share for a unit inside the house (by form in max_share_by_type)
            hit = picked[("size", "max_share_of_house_and_unit")]
            value = hit[0].get("value")
        out[key] = int(value) if key in INTEGER_KEYS and value is not None else value
        if hit:
            citations[key] = _citation(*hit)
            if hit[1] == DEFAULT and value is not None:
                assumed.append(key)
    if _value(picked, "size", "cap_is_greater_of") is True and out["max_size_sqft"] is not None:
        # "X or Y% of the house, whichever is greater": X is not a maximum. A number only with the house size
        share, house = out["max_share_of_house"], lot.get("house_sqft")
        out["max_size_sqft"] = max(out["max_size_sqft"], round(share * house)) if share is not None and house else None
    if "max_adus" in assumed and (not no_rule_here or place in PASS12_HOLD_TOWNS):
        # pass 12: never on a lot where the town has no ADU rule (no rule here, or outside the rule's districts)
        out["reasons"].append(f"ADUs per lot: the code is silent, {out['max_adus']} assumed (default.json)")
    if (
        tier
        and (allowed or state)
        and "#districts." not in (citations.get("max_size_sqft") or {}).get("source_file", "")
    ):
        out["reasons"].append(tier[1])
    by_lot = _adus_by_lot(data, lot) if allowed else None
    if by_lot:  # pass 9: ADUs per lot by lot or tract size
        n, line, leaf = by_lot
        if n is not None:
            out["max_adus"] = max(n, out["max_adus"] or 0) if state else n
            citations["max_adus"] = _citation(leaf, place)
            if "max_adus" in assumed:
                assumed.remove("max_adus")
        out["reasons"].append(line)
    inside = picked.get(("envelope", "unit_within_building_envelope"))
    if inside and inside[0].get("value"):
        out["setback_rear_alley_ft"] = out["setback_rear_ft"]
        if "setback_rear_alley_ft" in assumed:
            assumed.remove("setback_rear_alley_ft")
        if picked.get(("envelope", "setback_rear_ft")):
            citations["setback_rear_alley_ft"] = _citation(*picked[("envelope", "setback_rear_ft")])
    qualifier = None
    if allowed and dens and not dens[2] and not state and area is not None and area < dens[1]:
        per, need, _ = dens
        qualifier = "conditional_on_reading"
        out["reasons"].insert(
            0,
            f"{approval.replace('_', ' ').capitalize()} only if the ADU does not count toward lot area per unit "
            f"({per['section']}). If it counts, this lot needs relief: {need:,.0f} sq ft for the house and the ADU, "
            f"this lot is {area:,.0f} sq ft",
        )
    house_open = [
        x
        for x in depends
        if x["test"] in HOUSE_TESTS and x["effect"] == "bars" and set(x["applies_to"] or ALL_TYPES) & set(types_allowed)
    ]
    if allowed and house_open:  # pass 7: a bar on the house whose fact was not given. Never a plain "allowed"
        qualifier = qualifier or "depends_on_lot_facts"
        out["reasons"].insert(
            0,
            ". ".join(
                f"{by_type[forms[0]].replace('_', ' ').capitalize()}"
                + (f" for {', '.join(t.replace('_', ' ') for t in forms)}" if x["applies_to"] else "")
                + f" only if: {x['condition']} ({x['section']})"
                for x in house_open
                for forms in [[t for t in (x["applies_to"] or ALL_TYPES) if t in types_allowed]]
            ),
        )
    ov_open = [x for x in depends if x["test"] == "overlays" and set(x["applies_to"] or ALL_TYPES) & set(types_allowed)]
    if allowed and ov_open:  # pass 12: a bar only inside an overlay, the lot's overlays not given. Never a plain yes
        qualifier = qualifier or "depends_on_lot_facts"
        out["reasons"].insert(
            0,
            ". ".join(
                f"{by_type[forms[0]].replace('_', ' ').capitalize()}"
                + (f" for {', '.join(t.replace('_', ' ') for t in forms)}" if x["applies_to"] else "")
                + f" only if the lot is not in the {x['overlays']} overlay, "
                f"where the code bars it ({x['section']})"
                for x in ov_open
                for forms in [[t for t in (x["applies_to"] or ALL_TYPES) if t in types_allowed]]
            ),
        )
    disputed = [c for c in conditions if c.get("disputed_by") and c["met"] is False]
    # pass 15: a dispute on a bar scoped to some forms qualifies those forms only, never the lot's whole answer
    # while another form takes the same path without it (Bloomsburg 27-503.2B: a new detached unit only)
    whole = [c for c in disputed if not _form_scoped(c, by_type, types_allowed, approval)]
    form_disputes = [c for c in disputed if c not in whole]
    if allowed and whole and not state:  # pass 8: the lot fails a bar whose reading is disputed
        qualifier = qualifier or "conditional_on_reading"
        out["reasons"].insert(
            0,
            ". ".join(
                f"{approval.replace('_', ' ').capitalize()} only if the reading that lets this lot in holds: "
                + c["condition"]
                for c in whole
            ),
        )
    if allowed and form_disputes and not state:
        out["reasons"].insert(
            0,
            ". ".join(
                f"For {', '.join(t.replace('_', ' ') for t in forms)}: {by_type[forms[0]].replace('_', ' ')} only if "
                "the reading that lets this lot in holds: " + c["condition"]
                for c in form_disputes
                for forms in [[t for t in c["applies_to"] if t in types_allowed]]
            ),
        )
    if allowed and doubt and doubt_line:  # pass 11: in doubt, so the path holds only if the rule reaches the district
        qualifier = qualifier or "conditional_on_reading"
        out["reasons"].insert(
            0,
            f"{approval.replace('_', ' ').capitalize()} only if the ADU rule reaches {lot.get('zoning_district')}, "
            f"which is in doubt ({doubt['section']}). See below",
        )
    if allowed and no_district:  # pass 17: the path holds only if the lot is in a district the rule reaches
        qualifier = qualifier or "depends_on_lot_facts"
        out["reasons"].insert(0, f"{approval.replace('_', ' ').capitalize()} only if {no_district['reason']}")
    use_open = scope.get("use_open")
    if allowed and use_open and not state:  # pass 8: never a plain "allowed" where the use list is not on file
        qualifier = qualifier or "conditional_on_reading"
        out["reasons"].insert(
            0,
            f"{approval.replace('_', ' ').capitalize()} only if a {use_open['value']['use']} is a permitted use in "
            f"{lot.get('zoning_district')} ({use_open['section']}). "
            + (
                "This district's use list was read and does not name it, so it is not settled. "
                if scope.get("use_read")
                else "This district's use list is not on file. "
            )
            + "Ask the zoning officer",
        )
    path_key = ("approval", "path") if (allowed or path_to_ask) else ("approval", "fallback_path")
    for key, path in (("approval_path", path_key), ("types_allowed", ("form", "types_allowed"))):
        if picked.get(path):
            citations[key] = _citation(*picked[path])
    if barred:  # pass 11: the passage that bars the use variance
        citations["approval_path"] = _citation(barred, place)
    if chapter_bars and not allowed and fb["section"]:  # pass 17: the bar from another chapter, not 27-2008
        gates_leaf = _leaf(data, ("eligibility", "gates")) or {}
        citations["approval_path"] = {
            "section": fb["section"],
            "url": fb["url"],
            "verified_on": gates_leaf.get("verified_on"),
            "confidence": chapter_bars[0].get("confidence") or gates_leaf.get("confidence") or "secondary",
            "source_file": place,
        }

    if state:
        _state_town_fixes(out, picked, lot, limits, citations, assumed, reasons)
        if all(
            _value(today, "size", k) is None for k in ("max_sqft", "max_share_of_house", "max_share_of_house_and_unit")
        ):
            out["max_size_sqft"] = None  # the bill's size is a floor the town must allow, not a maximum
            citations.pop("max_size_sqft", None)
    exempt = historic and bool(_value(picked, "size", "historic_exempt"))
    today_forms = set(_form_types_town(today, lot))
    sizes, shares, size_rules = _town_sizes(today, out, limits, state, lot, today_forms, exempt)
    acc_cap = _acc_cap(_cap_in_scope(data, picked, lot))
    if acc_cap["binds"] is True and not state:  # the general accessory caps bind a unit in an accessory building
        house = lot.get("house_sqft")
        for t in DETACHED_TYPES:
            caps = [x for x in (sizes[t], acc_cap["sqft"]) if x is not None]
            if acc_cap["share"] is not None and house:
                caps.append(round(acc_cap["share"] * house))
            sizes[t] = min(caps) if caps else None
            if acc_cap["share"] is not None:
                shares[t] = acc_cap["share"] if shares[t] is None else min(shares[t], acc_cap["share"])
    total_area = _value(picked, "envelope", "accessory_floor_area_total_sqft")
    if total_area is not None and not state:
        for t in DETACHED_TYPES:
            if sizes[t] is None:
                sizes[t] = total_area
    for t in ALL_TYPES:
        if by_type[t] not in OK_PATHS:
            sizes[t], shares[t], size_rules[t] = None, None, None

    heights, notes = _town_heights(
        data,
        today,
        status if how not in ("district", "historic") else None,
        state,
        limits,
        citations,
        assumed,
        lot,
        by_type,
    )
    for a in [] if state else alts:  # pass 18: a listing's own accessory height for the forms it covers here
        h = a.get("accessory_max_height_ft")
        if h is not None and a.get("adu_listing") and a["applies"] is True:
            for t in set(a.get("forms") or []) & listed & set(DETACHED_TYPES):
                heights[t] = h
    if acc_cap["binds"] is True and not state and acc_cap["height"] is not None:
        for t in DETACHED_TYPES:
            if heights[t] is not None or by_type[t] in OK_PATHS:
                heights[t] = acc_cap["height"] if heights[t] is None else min(heights[t], acc_cap["height"])
        if place not in PASS16_HOLD_TOWNS and heights["detached_new"] is not None:
            # pass 16: the accessory building cap that binds the unit is the height on file. Never "no height number"
            notes = [n for n in notes if n != NO_DETACHED_HEIGHT]
            hit = _cap_in_scope(data, picked, lot).get(("envelope", "accessory_structure_max_height_ft"))
            if hit and heights["detached_new"] == acc_cap["height"] and "max_height_ft" not in citations:
                citations["max_height_ft"] = _citation(*hit)
    stories, notes = _town_stories(data, today, lot, by_type, heights, notes, status, how, state)
    town_h = _value(today, "envelope", "max_height_ft")
    lifted = [
        t
        for t in DETACHED_TYPES
        if state and stories and stories[t] is not None and heights[t] is not None and town_h is not None
        if heights[t] > town_h
    ]
    for t in lifted:  # pass 7: a story cap gives way with the height cap under the bill
        assert stories is not None
        stories[t] = None
    if lifted:
        notes = notes + [
            f"Under HB 2186 (not law) the bill's height floor is above the town's {town_h:g} ft cap, "
            f"so the town's story limit gives way too ({', '.join(t.replace('_', ' ') for t in lifted)})"
        ]
    out["reasons"] += notes
    out["max_height_ft"] = heights["detached_new"]
    if heights["detached_new"] is None:
        citations.pop("max_height_ft", None)
    bind_all = (_leaf(data, ("envelope", "adu_yards_bind_all_forms")) or {}).get("value") is True and not state
    setbacks = _town_setbacks(picked, principal, limits, state, by_type, bind_all)
    if not state:  # pass 9: a unit in a qualifying existing building is exempt from some caps
        out["reasons"] += _exempt_building(data, lot, by_type, sizes, shares, size_rules, heights, setbacks)
        for t in ALL_TYPES:  # a form freed of the height limit is freed of the story limit too
            if stories and heights[t] is None and stories[t] is not None and _exempt_frees(data, t, lot, "height"):
                stories[t] = None
        if heights["detached_new"] is None and out["max_height_ft"] is not None:
            out["max_height_ft"] = None
            citations.pop("max_height_ft", None)
    front_bar = picked.get(("envelope", "front_yard_barred"))
    detached_ok = any(t in types_allowed for t in DETACHED_TYPES)
    if not state and not detached_ok and not hold and out.get("separation_ft") is not None:
        # pass 10: a separation is between the house and an accessory building. No detached form, no separation
        out["separation_ft"] = None
        citations.pop("separation_ft", None)
        if "separation_ft" in assumed:
            assumed.remove("separation_ft")
    if front_bar and front_bar[0].get("value") is True:  # a bar, not a setback: no front yard number for the unit
        for t in DETACHED_TYPES:
            setbacks[t]["setback_front_ft"] = None
        if detached_ok:  # pass 9: only for a detached unit allowed here, never the house's own front yard
            out["setback_front_ft"] = None
            citations["setback_front_ft"] = _citation(*front_bar)
            if "setback_front_ft" in assumed:
                assumed.remove("setback_front_ft")
    default_yards = [k for k in YARDS if k in assumed and out.get(k) is not None]
    if default_yards and allowed:  # pass 8: a default yard is never the town's rule (pass 9: under the bill too)
        d = lot.get("zoning_district")
        figs = ", ".join(f"{k.split('_')[1]} {out[k]:g} ft" for k in default_yards)
        where = f"for {d}" if d else "for this lot"
        out["reasons"].append(
            f"Yards: the town file has no yard figures {where}. The {figs} shown are a general default "
            "(default.json), not the town's rule" + _district_read_line(file_data, lot) + ". Ask the zoning officer"
            if detached_ok
            else f"Yards: the town file has no yard figures {where}, so an addition's yards are not known here"
            + _district_read_line(file_data, lot)
            + ". Ask the zoning officer"
        )
        for k in default_yards:  # an addition takes the district yards, which are not on file
            if k not in principal:
                setbacks["attached"][k] = None
    if allowed and not any(t in types_allowed for t in DETACHED_TYPES):
        # pass 8: no accessory building here, so the top-level yards are an addition's (district) yards or none
        for k in YARDS:
            out[k] = setbacks["attached"][k] if "attached" in types_allowed else None
            if out[k] is None:
                citations.pop(k, None)
            elif k in principal:
                citations[k] = _citation(*principal[k])
            if k in assumed:
                assumed.remove(k)
        out["setback_rear_alley_ft"] = None
        citations.pop("setback_rear_alley_ft", None)
        if "setback_rear_alley_ft" in assumed:
            assumed.remove("setback_rear_alley_ft")
    _, d_row = _district_row(data, lot)
    min_h = None if state else d_row.get("min_height_ft")
    if _usable(min_h) and min_h.get("value") is not None:  # pass 17: every building in the district at least this tall
        low = [t for t in DETACHED_TYPES if t in types_allowed and (heights[t] is None or heights[t] < min_h["value"])]
        if low:
            every = set(low) == set(types_allowed)
            if every:
                qualifier = qualifier or "conditional_on_reading"
            lead = (
                f"{approval.replace('_', ' ').capitalize()}"
                if every
                else f"For {', '.join(t.replace('_', ' ') for t in low)}: {by_type[low[0]].replace('_', ' ')}"
            )
            d = lot.get("zoning_district")
            out["reasons"].insert(
                0,
                f"{lead} only if the district's minimum building height does not reach the unit. In {d} a building "
                f"must be at least {min_h['value']:g} ft tall ({min_h['section']})"
                + (
                    f", and the unit may be at most {max(caps):g} ft"
                    if (caps := [h for t in low if (h := heights[t]) is not None]) and len(caps) == len(low)
                    else ""
                )
                + ". The code does not settle whether that reaches an ADU. Ask the zoning officer",
            )
    sides = d_row.get("setback_sides_total_ft")
    one_side = d_row.get("setback_side_ft")
    # pass 11: a planned or cluster development whose own figures replace the district's (supersedes_district_figures).
    # Pass 12: or an overlay whose figures replace them. Not given: the district figures are shown with a plain line
    pd = [] if state else [c for c in conditions if c.get("supersedes_district_figures") and _sup_met(c) is not False]
    if place not in PASS16_HOLD_TOWNS:  # pass 16: the gate the lot is inside leads, whatever its order in the file
        pd = sorted(pd, key=lambda c: _sup_met(c) is not True)
    if pd and _sup_met(pd[0]) is True and _sup_covers(pd[0], "yards"):
        if _usable(sides) and sides.get("value") is not None:  # the district side yards do not apply
            out["reasons"].append(
                f"Side yards for {lot.get('zoning_district')}: this lot is in {_sup_where(pd[0], True)}, whose "
                f"own figures replace the district's ({pd[0]['section']}). See the conditions"
            )
    elif _usable(sides) and sides.get("value") is not None and not _usable(one_side):
        out["reasons"].append(  # pass 9
            f"Side yards for {lot.get('zoning_district')}: {sides['value']:g} ft for both sides together "
            f"({sides['section']}). The code gives no single side figure, so none is shown"
        )
    elif _usable(sides) and sides.get("value") is not None and _usable(one_side) and one_side.get("value") is not None:
        secs = [one_side["section"]] + ([sides["section"]] if sides["section"] != one_side["section"] else [])
        out["reasons"].append(  # pass 10: both figures, never the single side alone
            f"Side yards for {lot.get('zoning_district')}: at least {one_side['value']:g} ft on one side, "
            f"{sides['value']:g} ft for both sides together ({', '.join(secs)})"
        )
    imp = d_row.get("max_impervious_coverage")
    # pass 12: the district cover is replaced too. Pass 17: unless the gate names the figures it replaces without it
    pd_in = bool(pd) and _sup_met(pd[0]) is True and _sup_covers(pd[0], "impervious_coverage")
    tier_line = None if (state or pd_in) else _impervious_tier_line(d_row, lot)
    if tier_line:  # pass 16: cover by lot size, the lot's tier not known
        out["reasons"].append(tier_line)
    in_dispute = None if (state or pd_in) else _figures_in_dispute(d_row, lot)
    if in_dispute:  # pass 16: the row's figures differ under another reading of the code. Both said, row qualified
        out["reasons"].append(in_dispute)
    if (
        _usable(imp) and imp.get("value") is not None and not pd_in
    ):  # pass 10: impervious cover is not building coverage
        bcov = d_row.get("max_building_coverage")
        out["reasons"].append(
            f"Impervious cover for {lot.get('zoning_district')}: at most {imp['value']:.0%} of the lot, buildings and "
            f"paved surfaces together ({imp['section']})"
            + (
                ""
                if _usable(bcov) and bcov.get("value") is not None
                else ". The code sets no separate building coverage"
            )
        )
    if not allowed and not state:
        # pass 13: a yard the file does not hold (a general default) is never a figure for a form here
        for k in [k for k in YARDS if (picked.get(("envelope", k)) or ({}, ""))[1] == DEFAULT]:
            for t in ALL_TYPES:
                if not (t == "attached" and k in principal):
                    setbacks[t][k] = None
    if not allowed and not state:
        # pass 9: no ADU form allowed here, so no accessory (ADU) yards. The top-level yards are the district's own
        # (the house's), or none where the file has no district row. A front-yard bar never blanks them.
        for k in YARDS:
            out[k] = principal[k][0]["value"] if k in principal else None
            if out[k] is None:
                citations.pop(k, None)
            else:
                citations[k] = _citation(*principal[k])
            if k in assumed:
                assumed.remove(k)
        out["setback_rear_alley_ft"] = None
        citations.pop("setback_rear_alley_ft", None)
        if "setback_rear_alley_ft" in assumed:
            assumed.remove("setback_rear_alley_ft")
    min_by = _leaf(data, ("size", "min_sqft_by_form"))
    if _usable(min_by) and isinstance(min_by.get("value"), dict):  # pass 10: a minimum floor area by form
        mins = [(t, min_by["value"][t]) for t in ALL_TYPES if min_by["value"].get(t) is not None and t in types_allowed]
        if mins:
            out["reasons"].append(
                "Minimum floor area: "
                + ", ".join(f"{t.replace('_', ' ')} {v:,.0f} sq ft" for t, v in mins)
                + f" ({min_by['section']})"
            )
    out["reasons"] += _planned_development_yards(
        conditions, principal, out, citations, setbacks, lot, state, place in PASS16_HOLD_TOWNS
    )
    fire = {}
    for key, path in FIRE_KEYS.items():
        hit = picked.get(path)
        fire[key] = hit[0]["value"] if hit else None
        if hit:
            citations[f"fire_separation.{key}"] = _citation(*hit)
    no_unit_rule = not state and status in NO_ADU_STATUSES and how not in ("district", "historic")
    # pass 7: no ADU allowed on this lot today (a district not listed, a failed test): no ADU parking either
    no_unit_rule = no_unit_rule or (not state and not allowed)
    total, reading = _town_parking(picked, today, state, out, no_unit_rule)
    if no_unit_rule:  # no ADU rule here, so no parking count for an ADU either
        out["parking_spaces"] = None
        citations.pop("parking_spaces", None)
        if "parking_spaces" in assumed:
            assumed.remove("parking_spaces")
    out["citations"] = citations
    out["assumed"] = assumed
    out["approval_by_type"] = by_type
    out["max_height_by_type"] = heights
    out["setback_rear_effective_ft"], out["rear_setback_rule"] = _rear(out, lot)
    out["state_limits"] = limits
    out["fire_separation"] = fire
    out["historic_path"] = historic
    dp = picked.get(("approval", "path")) if how == "district" else None
    out.update(
        {
            "adu_status": status,
            "adu_term": term,
            "conditions": conditions,
            "approval_by_district": _by_district(file_data),
            "district_path": (
                {"district": lot.get("zoning_district"), "path": dp[0]["value"], "section": dp[0]["section"]}
                | ({"term": dp[0]["term"]} if dp[0].get("term") else {})
            )
            if dp
            else None,
            "fallback": fb,
            "max_share_by_type": shares,
            "parking_total_on_site": total,
            "parking_reading": reading,
            "scope": {k: scope[k] for k in ("districts", "in_scope", "status_outside")},
            "conditions_overridden": overridden,
            "max_size_by_type": sizes,
            "setbacks_by_type": setbacks,
            "alternatives": alts,
            "approval_qualifier": qualifier,
            "path_to_ask": path_to_ask,
            # Labels describe the town's own forms. Under the bill any form is allowed, so none are shown.
            "form_labels": None if state else (_leaf(file_data, ("form", "labels")) or {}).get("value"),
            "yard_tiers": tiers_out,
            "max_stories_by_type": stories,
            "adu_status_by_form": None if state else by_form,
            "size_rule_by_type": size_rules,
            "depends_on": depends,
        }
    )
    if allowed or state:
        out["reasons"] += _house_type_cases(data, lot, out)
    _clean_owner_text(out, stops=place not in LOT_RECORD_TOWNS, once=place not in PASS14_HOLD_TOWNS)
    dp_path = dp[0]["value"] if dp else None
    if not state and status in BOARDS and dp_path and PATH_ORDER.index(dp_path) < PATH_ORDER.index(status):
        out["adu_status"] = "allowed_by_right" if dp_path == "by_right" else dp_path  # pass 8: the district leads
    hp = hist_leaf["value"] if _usable(hist_leaf) else None
    if (
        not state and how == "historic" and status in NO_ADU_STATUSES and allowed and (hp == "by_right" or hp in BOARDS)
    ):  # pass 9: the historic path leads on this lot, as a district path does
        out["adu_status"] = "allowed_by_right" if hp == "by_right" else hp
    if not state and status == "allowed_by_right" and dp_path in BOARDS:
        # pass 7: a district whose path is a hearing never reads "allowed by right"
        out["adu_status"] = dp_path
    if not state and out["adu_status"] == "allowed_by_right" and approval in ("variance", "not_allowed"):
        # pass 18: the lot fails a test of the by-right rule (Worcester: a lot outside an Option 3 subdivision), so
        # its path is a variance. The status never reads "allowed by right" there
        out["adu_status"] = approval
    if state and allowed and status and status != "allowed_by_right":
        # The bill overrides the town's status (conditions_overridden says so). Today's status is in the reasons.
        out["adu_status"] = "allowed_by_right"
    return {k: out[k] for k in OUTPUT_KEYS + TOWN_KEYS}


def _form_scoped(c: dict[str, Any], by_type: dict[str, str], types_allowed: list[str], approval: str) -> bool:
    """Pass 15: a disputed condition that reaches only some allowed forms (applies_to), while another allowed form
    outside it takes the lot's path. Then the dispute qualifies those forms, not the lot's answer."""
    forms = c.get("applies_to")
    if not forms or not any(t in types_allowed for t in forms):
        return False
    return any(by_type[t] == approval for t in types_allowed if t not in forms)


def _path_words(leaf: dict[str, Any]) -> str:
    """Pass 15: a path in words. A path leaf with code_term (the code's own name for the decision, for example a use
    grant) names it, and says which path the tool reads it as."""
    words = str(leaf["value"]).replace("_", " ")
    term = leaf.get("code_term")
    return f"a {term}, which the tool reads as a {words}" if term else words


def _sup_met(c: dict[str, Any]) -> bool | None:
    """Pass 12: is the lot in the area whose figures replace the district's? An overlay gate with no lot test reads the
    lot's overlays (in_overlay), a planned-development gate its lot fact (met)."""
    return c["in_overlay"] if "in_overlay" in c else c["met"]


def _sup_covers(c: dict[str, Any], fig: str) -> bool:
    """Pass 17: gates[].supersedes_figures names the district figures the gate replaces (yards, building_coverage,
    impervious_coverage). Without it every district figure is replaced, as before."""
    figs = c.get("supersedes_figures")
    return not figs or fig in figs


def _sup_where(c: dict[str, Any], inside: bool) -> str:
    """Pass 12: the area a supersedes_district_figures gate names, in plain words."""
    if c.get("supersedes_overlays"):
        ovs = c["supersedes_overlays"]
        return f"the {ovs[0] if len(ovs) == 1 else ', '.join(ovs[:-1]) + ' or ' + ovs[-1]} overlay"
    return "the development the code names" if inside else "an approved planned or cluster development"


def _planned_development_yards(
    conditions: list[dict[str, Any]],
    principal: dict[str, tuple[dict[str, Any], str]],
    out: dict[str, Any],
    citations: dict[str, Any],
    setbacks: dict[str, dict[str, Any]],
    lot: dict[str, Any],
    state: bool,
    hold16: bool = False,
) -> list[str]:
    """Pass 10: a gate with supersedes_district_figures (a planned or cluster development whose own figures replace
    the district's). On a lot that is in one the district yards are not shown. Pass 12: when that is not given, the
    district yards are shown with a plain line that a lot inside one follows its own figures. An overlay gate with the
    field works the same way, keyed on the lot's overlays."""
    hits = [c for c in conditions if c.get("supersedes_district_figures") and _sup_met(c) is not False]
    if state or not hits:
        return []
    if not hold16:  # pass 16: the gate the lot is inside leads. hold16: the first gate only (PASS16_HOLD_TOWNS)
        hits = sorted(hits, key=lambda h: _sup_met(h) is not True)
    c = hits[0]
    d = lot.get("zoning_district")
    inside = _sup_met(c) is True
    shown = []
    overlay = bool(c.get("supersedes_overlays"))
    for k in YARDS if _sup_covers(c, "yards") else ():  # pass 17: a gate that names its figures may leave the yards
        if inside and overlay and out.get(k) is not None and k not in principal:
            # pass 12: an overlay's figures replace the accessory yards too (Pine TVO: 0 ft for accessory structures)
            shown.append(f"{k.split('_')[1]} {out[k]:g} ft")
            out[k] = None
            citations.pop(k, None)
            for t in setbacks:
                setbacks[t][k] = None
            continue
        if k not in principal or principal[k][0].get("value") is None:
            continue
        v = principal[k][0]["value"]
        if out.get(k) is not None and inside and overlay and out.get(k) != v:
            shown.append(f"{k.split('_')[1]} {out[k]:g} ft")
            out[k] = None
            citations.pop(k, None)
            for t in setbacks:
                setbacks[t][k] = None
            continue
        if out.get(k) == v and "#districts." in (citations.get(k) or {}).get("source_file", ""):
            shown.append(f"{k.split('_')[1]} {v:g} ft")
            if inside:
                out[k] = None
                citations.pop(k, None)
        if inside:
            for t in setbacks:
                if setbacks[t].get(k) == v:
                    setbacks[t][k] = None
    if inside:  # pass 12: the district's building and impervious cover are replaced too
        for k, word, fig in (
            ("max_building_coverage", "building coverage", "building_coverage"),
            ("max_impervious", "impervious cover", "impervious_coverage"),
        ):
            if not _sup_covers(c, fig):  # pass 17: the gate names the figures it replaces, and not this one
                continue
            if out.get(k) is not None and "#districts." in (citations.get(k) or {}).get("source_file", ""):
                shown.append(f"{word} {out[k]:.0%}")
                out[k] = None
                citations.pop(k, None)
    if inside:
        if not shown:
            return []
        also = [
            f"It is also in {_sup_where(o, True)}, whose own figures replace the district's ({o['section']})"
            for o in ([] if hold16 else hits[1:])
            if _sup_met(o) is True and _sup_where(o, True) != _sup_where(c, True)
        ]  # pass 16: every gate the lot is inside is named
        return [
            f"Yards for {d}: this lot is in {_sup_where(c, True)}, whose own figures replace the district's "
            f"({c['section']}). The {'base' if overlay else 'district'} figures ({', '.join(shown)}) do not apply, "
            "so none is shown" + "".join(f". {a}" for a in also) + ". See the conditions"
        ]
    if not shown and not any(principal[k][0].get("value") is not None for k in YARDS if k in principal):
        return []  # no district figure on file, so nothing for the development's figures to replace
    follows = "the overlay's figures" if overlay else "that plan's figures"
    line = (
        f"Yards for {d}: a lot {'in' if overlay else 'inside'} {_sup_where(c, False)} follows {follows} instead of "
        f"the district's ({c['section']})"
    )
    said = {_sup_where(c, False)}
    for o in [] if hold16 else hits[1:]:  # pass 16: every other gate whose own figures replace the district's
        where = _sup_where(o, False)
        if where in said:
            continue
        said.add(where)
        ov = bool(o.get("supersedes_overlays"))
        line += (
            f". A lot {'in' if ov else 'inside'} {where} follows "
            f"{'the overlay' if ov else 'that plan'}'s own figures instead ({o['section']})"
        )
    return [line]


def _owner_text(text: Any, stops: bool = True, once: bool = True) -> Any:
    """Pass 8: a sentence for the owner, without the author's bookkeeping (dates added, second checks).
    Pass 10: and without a doubled full stop (stops=False keeps the pass 9 text for a held lot town).
    Pass 14: and an overlay named once (once=False keeps the pass 13 text for a held lot town)."""
    if not isinstance(text, str):
        return text
    out = text
    for pat, rep in BOOKKEEPING:
        out = pat.sub(rep, out)
    if stops:
        out = DOUBLE_STOP.sub(".", out)
    if once:
        out = OVERLAY_TWICE.sub(r"\1", out)
    return out.strip() if out != text else text


def _clean_owner_text(out: dict[str, Any], stops: bool = True, once: bool = True) -> None:
    """Pass 8: every owner sentence built from a note goes through _owner_text."""
    out["reasons"] = [_owner_text(r, stops, once) for r in out["reasons"]]
    for c in out.get("conditions") or []:
        c["condition"] = _owner_text(c["condition"], stops, once)
    for c in out.get("depends_on") or []:
        c["condition"] = _owner_text(c["condition"], stops, once)
        c["fact"] = _owner_text(c.get("fact"), stops, once)
    for a in out.get("alternatives") or []:
        a["note"] = _owner_text(a.get("note"), stops, once)
        if a.get("conditions"):
            a["conditions"] = _owner_text(a["conditions"], stops, once)
    for key in ("path_to_ask", "fallback"):
        if out.get(key) and out[key].get("note"):
            out[key]["note"] = _owner_text(out[key]["note"], stops, once)


def _house_type_cases(data: dict[str, Any], lot: dict[str, Any], out: dict[str, Any]) -> list[str]:
    """Pass 8: districts.<code>.stricter_by_house_type. A figure that is stricter for a house type the tool cannot
    tell apart: the shown figure reads 'at most' (coverage) or 'at least' (yards), with the stricter case named."""
    _, row = _district_row(data, lot)
    leaf = row.get("stricter_by_house_type")
    if not (_usable(leaf) and leaf.get("value")):
        return []
    btype = _building_type(lot.get("building_type"))
    lines = []
    tail = "The tool cannot tell these house types apart, so check which one the house is"
    for case in leaf["value"]:
        if btype is not None and case["building_type"] != btype:
            continue
        sec = case.get("section") or leaf["section"]
        who = f"a {case['label']}" + ("" if btype is not None else f" ({case['building_type'].replace('_', ' ')})")
        cov, shown = case.get("max_building_coverage"), out.get("max_building_coverage")
        if cov is not None:
            lines.append(
                (
                    f"Building coverage at most {shown:.0%}, and {cov:.0%} for {who}"
                    if shown is not None
                    else f"Building coverage {cov:.0%} for {who}"
                )
                + f" ({sec}). {tail}"
            )
        for kind, keys in (
            ("Outbuilding", ("accessory_setback_side_ft", "accessory_setback_rear_ft")),
            ("House", ("setback_side_ft", "setback_rear_ft")),
        ):
            vals = {k: case[k] for k in keys if case.get(k) is not None}
            if not vals:
                continue
            if (
                kind == "House"
                and (out.get("setbacks_by_type") or {}).get("attached", {}).get("setback_side_ft") is None
            ):
                continue  # house yards matter here only for an attached unit
            shown_side = out.get("setback_side_ft") if kind == "Outbuilding" else None
            names = " and ".join(k.split("_")[-2] for k in vals)
            figs = sorted(set(vals.values()))
            lines.append(
                f"{kind} {names} yards"
                + (f" at least {shown_side:g} ft, and" if shown_side is not None else ":")
                + f" {'/'.join(f'{v:g}' for v in figs)} ft for {who} ({sec}). {tail}"
            )
    return lines


BOARDS = {
    "special_exception": ("the Zoning Hearing Board", "MPC 912.1"),
    "conditional_use": ("the governing body (council, commissioners or supervisors)", "MPC 913.2"),
}


def _hearing_to_ask(
    picked: Picked, by_type: dict[str, str], types_allowed: list[str], approval: str
) -> dict[str, Any] | None:
    """For an ADU allowed after a hearing: which body hears it. None when every allowed form is by right."""
    hearings = [p for p in BOARDS if any(by_type[t] == p for t in types_allowed)]
    if not hearings:
        return None
    path = approval if approval in hearings else hearings[0]
    leaf = picked[("approval", "path")][0]
    # pass 12: approval.path.hearing_named false, the code names no hearing for the decision (Adams 167-21.1)
    silent = leaf.get("hearing_named") is False
    parts = []
    for p in hearings:
        board, mpc = BOARDS[p]
        forms = [t for t in types_allowed if by_type[t] == p]
        which = "" if len(forms) == len(types_allowed) else f" ({', '.join(t.replace('_', ' ') for t in forms)})"
        if silent and p == leaf["value"]:
            parts.append(
                f"A {p.replace('_', ' ')}{which} is decided by {board}. "
                f"The code names no hearing for this decision ({leaf['section']})"
            )
        else:
            parts.append(f"A {p.replace('_', ' ')}{which} is decided by {board} after a public hearing ({mpc})")
    sec = leaf["section"]
    mpc = BOARDS[path][1]
    return {
        "path": path,
        "section": sec if (mpc in sec or (silent and path == leaf["value"])) else f"{sec}, {mpc}",
        "url": leaf.get("url"),
        "note": ". ".join(parts),
        "kind": "hearing",
    }


def _use_variance_barred(data: dict[str, Any], lot: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any] | None:
    """approval.use_variance_barred (pass 11): the code itself bars a use variance for a use the district does not
    permit. It reaches a lot outside the ADU's districts (or anywhere when the town has no ADU rule), in the
    leaf's districts when it lists them."""
    leaf = _leaf(data, ("approval", "use_variance_barred"))
    if not (_usable(leaf) and leaf.get("value") is True) or scope.get("in_scope") is True:
        return None
    if scope.get("in_scope") is None and scope.get("districts"):
        return None  # the district is unknown, in doubt or not on file: not settled, so not barred
    where = leaf.get("districts")
    if where and _match_code(lot.get("zoning_district"), where) is None:
        return None
    return leaf


def _form_variance_barred(data: dict[str, Any], lot: dict[str, Any]) -> dict[str, Any] | None:
    """Pass 12: approval.use_variance_barred reaching this lot's district (all districts when it lists none), for a
    form the code bars (adu.status_by_form prohibited). Then the form is not allowed, never a variance to ask for."""
    leaf = _leaf(data, ("approval", "use_variance_barred"))
    if not (_usable(leaf) and leaf.get("value") is True):
        return None
    where = leaf.get("districts")
    if where and _match_code(lot.get("zoning_district"), where) is None:
        return None
    return leaf


def _in_doubt(data: dict[str, Any], lot: dict[str, Any], hold: bool = False) -> dict[str, Any] | None:
    """eligibility.districts_in_doubt: the district lists the ADU, the ADU section names other districts. Pass 11:
    named_by says which way the doubt runs (adu_section: the ADU section names the district, its own list does not;
    reach: whether the rule reaches it is in doubt for the reason in the note). hold: a lot town (DOUBT_HOLD_TOWNS)."""
    leaf = _leaf(data, ("eligibility", "districts_in_doubt"))
    d = lot.get("zoning_district")
    code = _match_code(d, (leaf or {}).get("value") or []) if d else None
    if not (_usable(leaf) and leaf.get("value") and d) or code is None:
        return None
    named = (_leaf(data, ("eligibility", "zoning_districts")) or {}).get("value") or []
    kind = "district_list" if hold else ((leaf.get("named_by") or {}).get(code) or "district_list")
    # pass 13: a note and sections for this district alone (notes_by_district, sections_by_district), so a lot never
    # reads why other districts are in doubt
    own_note = (leaf.get("notes_by_district") or {}).get(code)
    section = (leaf.get("sections_by_district") or {}).get(code) or leaf["section"]
    note = own_note or leaf.get("note")
    ask = "ask the zoning officer or the Zoning Hearing Board whether it is allowed here"
    if kind == "adu_section":
        lead = f"The ADU section names {d} ({section}), but {d}'s own use list does not name the ADU. Named, but {ask}"
    elif kind == "reach":
        lead = f"Whether the ADU rule reaches {d} is in doubt ({section}). Ask the zoning officer or the Zoning Hearing Board whether it is allowed here"
    else:
        lead = (
            f"{d} lists the ADU ({section}), but the ADU section names "
            + (", ".join(named) if named else "other districts")
            + f". Listed, but {ask}"
        )
    reason = lead + (f". {note}" if note else "")
    return {"reason": reason, "section": section, "url": leaf.get("url"), "kind": kind}


def _no_district(
    data: dict[str, Any], picked: Picked, scope: dict[str, Any], lot: dict[str, Any]
) -> dict[str, Any] | None:
    """Pass 17: a lot whose zoning district is not known, where the ADU rule reaches only some districts (the rule's
    district list or its scope). The path holds only if the lot is in one of them, so ask, never a variance."""
    if lot.get("zoning_district") is not None:
        return None
    hit = picked.get(("eligibility", "zoning_districts"))
    if hit and hit[0].get("value"):
        districts, leaf = hit[0]["value"], hit[0]
    elif scope.get("districts") and scope.get("in_scope") is None:
        districts = scope["districts"]
        leaf = _leaf(data, ("adu", "scope_districts")) or _leaf(data, ("adu", "scope_by_use")) or {}
    else:
        return None
    sec = leaf.get("section") or scope.get("section")
    names = districts[0] if len(districts) == 1 else ", ".join(districts[:-1]) + " or " + districts[-1]
    return {
        "reason": f"the lot is in {names}, where the ADU rule reaches"
        + (f" ({sec})" if sec else "")
        + ". The lot's zoning district is not known. Ask the zoning officer",
        "section": sec,
        "url": leaf.get("url"),
    }


def _bill_keeps(picked: Picked, data: dict[str, Any], lot: dict[str, Any]) -> list[str]:
    """Town lot rules HB 2186 does not address: the district minimum lot, building coverage, front yard."""
    out = []
    _, row = _district_row(data, lot)
    m = row.get("min_lot_sqft")
    if _usable(m) and m.get("value"):
        out.append(f"district minimum lot {m['value']:,.0f} sq ft for creating lots ({m['section']})")
    cov = picked.get(("coverage", "max_building_coverage"))
    if cov and cov[0].get("value") is not None and cov[1] != DEFAULT:
        out.append(f"building coverage {cov[0]['value']:.0%} ({cov[0]['section']})")
    imp = row.get("max_impervious_coverage")  # pass 10: a district's impervious cover
    if _usable(imp) and imp.get("value") is not None:
        out.append(f"impervious cover {imp['value']:.0%} ({imp['section']})")
    front = picked.get(("envelope", "setback_front_ft"))
    if front and front[0].get("value") is not None and front[1] != DEFAULT:
        out.append(f"front yard {front[0]['value']:g} ft ({front[0]['section']})")
    return out


def _reword_zoned(text: str) -> str:
    """'Zoned X. Needs A or B' reads like a call to rezone. Say where the ADU rule applies instead."""
    m = re.match(r"^Zoned (.+?)\. Needs (.+)$", text)
    if not m:
        return text
    return f"The ADU rule applies only in {m.group(2).replace(' or ', ', ')}. This lot is zoned {m.group(1)}"


def _acc_cap(picked: Picked) -> dict[str, Any]:
    """The general accessory structure caps and whether they bind an ADU (True, False, None = not settled)."""
    binds = picked.get(("envelope", "accessory_cap_binds_adu"))
    return {
        "sqft": _value(picked, "envelope", "accessory_structure_max_sqft"),
        "share": _value(picked, "envelope", "accessory_structure_max_share"),
        "height": _value(picked, "envelope", "accessory_structure_max_height_ft"),
        "binds": binds[0].get("value") if binds else None,
        "binds_leaf": binds[0] if binds else None,
    }


def _town_type_reasons(picked: Picked, by_type: dict[str, str], hold: bool = False) -> list[str]:
    """The accessory building cap, said as a cap and only when the file stores one. Never as the reason."""
    cap = picked.get(("envelope", "accessory_structure_max_sqft"))
    if not (cap and cap[0].get("value") is not None):
        return _height_cap_reasons(picked, by_type, hold)
    acc = _acc_cap(picked)
    height = acc["height"] if acc["height"] is not None else _value(picked, "envelope", "max_height_ft")
    secs = [cap[0]["section"]]
    for key in ("accessory_structure_max_share", "accessory_structure_max_height_ft"):
        hit = picked.get(("envelope", key))
        if hit and hit[0].get("value") is not None and hit[0]["section"] not in secs:
            secs.append(hit[0]["section"])
    line = (
        f"Accessory buildings are capped at {cap[0]['value']:,.0f} sq ft"
        + (f" or {acc['share']:.0%} of the house, whichever is less," if acc["share"] is not None else "")
        + (f" and {height:,.0f} ft" if height is not None else "")
        + f" ({', '.join(secs)})"
    )
    leaf = acc["binds_leaf"]
    if leaf is not None:
        if acc["binds"] is True:
            line += f". These caps also bind a unit in an accessory building ({leaf['section']})"
        elif acc["binds"] is False:
            line += f". The ADU text replaces them for the unit ({leaf['section']})"
        else:
            line += f". Whether they also bind the ADU is not settled ({leaf['section']}). Ask the zoning officer"
    return [line]


def _height_cap_reasons(picked: Picked, by_type: dict[str, str], hold: bool = False) -> list[str]:
    """Pass 8: an accessory structure height cap stored without a floor area cap (Allentown 660-41B(4)), said
    where a detached unit is allowed. When it is not settled whether the cap binds the ADU, the ADU's own
    outbuilding rule is said beside it."""
    hit = picked.get(("envelope", "accessory_structure_max_height_ft"))
    if not (hit and hit[0].get("value") is not None) or not any(by_type[t] in OK_PATHS for t in DETACHED_TYPES):
        return []
    acc = _acc_cap(picked)
    line = f"Accessory structures are capped at {hit[0]['value']:g} ft ({hit[0]['section']})"
    leaf = acc["binds_leaf"]
    if leaf is None:
        return [line]
    if acc["binds"] is True:
        return [line + f". This cap also binds a unit in an accessory building ({leaf['section']})"]
    if acc["binds"] is False:
        return [line + f". The ADU text sets the height of a unit in an accessory building instead ({leaf['section']})"]
    own = []
    stories = picked.get(("envelope", "max_height_stories"))
    if stories and stories[0].get("value") is not None:
        own.append(f"at most {stories[0]['value']:g} stories ({stories[0]['section']})")
    feet = picked.get(("envelope", "max_height_ft"))
    if feet and feet[0].get("value") is not None:
        own.append(f"at most {feet[0]['value']:g} ft ({feet[0]['section']})")
    at_house = picked.get(("envelope", "height_capped_at_house"))
    if at_house and at_house[0].get("value") is True:
        own.append(f"no taller than the house ({at_house[0]['section']})")
    rule = f"The outbuilding rule for the ADU: {', '.join(own)}. " if own else ""
    return [
        line + f". Not settled: whether this {hit[0]['value']:g} ft cap also binds an outbuilding with an ADU "
        f"({leaf['section']}). {rule}"
        + (
            "Both are shown; the lower one is the safe reading"
            if hold
            else "Both are shown, and the lower one is the safe reading"  # pass 12: no semicolon
        )
        + ". Ask the zoning officer"
    ]


def _town_stories(
    data: dict[str, Any],
    today: Picked,
    lot: dict[str, Any],
    by_type: dict[str, str],
    heights: dict[str, float | None],
    notes: list[str],
    status: str | None,
    how: str | None,
    state: bool,
) -> tuple[dict[str, float | None] | None, list[str]]:
    """Height in stories, where the code gives stories (districts.<code>.principal_max_stories,
    envelope.max_height_stories). None when the file has none. A story limit replaces the 'not on file
    in feet' notes, so a missing feet number never reads as no limit."""
    _, row = _district_row(data, lot)
    p_leaf = row.get("principal_max_stories") if _usable(row.get("principal_max_stories")) else None
    a_leaf = _leaf(data, ("envelope", "max_height_stories"))
    a_leaf = a_leaf if _usable(a_leaf) else None
    row_st = row.get("accessory_max_stories")  # pass 9: a utility row's story cap for an accessory building
    if (
        _usable(row_st)
        and row_st.get("value") is not None
        and (a_leaf is None or a_leaf.get("value") is None or row_st["value"] < a_leaf["value"])
    ):
        a_leaf = row_st
    principal = (p_leaf or {}).get("value")
    accessory = (a_leaf or {}).get("value")
    if principal is None and accessory is None:
        return None, notes
    no_adu = status in NO_ADU_STATUSES and how not in ("district", "historic")
    if no_adu and not state:
        return {t: None for t in ALL_TYPES}, notes
    inner = principal if _value(today, "envelope", "internal_uses_district_height") is not False else accessory
    out = {t: (inner if t in PRINCIPAL_TYPES else accessory) for t in ALL_TYPES}
    for t in ALL_TYPES:
        if by_type[t] not in OK_PATHS:
            out[t] = None
    notes = list(notes)
    d = lot.get("zoning_district")
    if principal is not None and p_leaf is not None:
        old = f"District height for {d} not on file in feet. Height of a unit in the house not known"
        new = f"District height for {d}: at most {principal:g} stories ({p_leaf['section']}). The code gives no feet figure"
        notes = [new if n == old else n for n in notes]
    if accessory is not None and a_leaf is not None:
        old = NO_DETACHED_HEIGHT
        new = f"Accessory buildings: at most {accessory:g} stories ({a_leaf['section']}). The code gives no feet figure"
        notes = [new if n == old else n for n in notes]
    return out, notes


def _in_tier(tier: dict[str, Any], area: float) -> bool:
    """A yard tier's lot size range. min_lot_sqft is inclusive (at least) and max_lot_sqft exclusive (less than).
    Pass 14: min_lot_sqft_over (more than) and max_lot_sqft_at_most (X or less) carry a code's own figures."""
    if tier.get("min_lot_sqft") is not None and area < tier["min_lot_sqft"]:
        return False
    if tier.get("min_lot_sqft_over") is not None and area <= tier["min_lot_sqft_over"]:
        return False
    if tier.get("max_lot_sqft") is not None and area >= tier["max_lot_sqft"]:
        return False
    return not (tier.get("max_lot_sqft_at_most") is not None and area > tier["max_lot_sqft_at_most"])


def _apply_yard_tiers(
    data: dict[str, Any],
    picked: Picked,
    principal: dict[str, tuple[dict[str, Any], str]],
    lot: dict[str, Any],
    reasons: list[str],
) -> list[dict[str, Any]] | None:
    """Yards that depend on lot size. With the lot size known, the tier's yards apply. Without it,
    the yards are left out and the tiers are returned."""
    _, row = _district_row(data, lot)
    leaf = row.get("yard_tiers") if _usable(row.get("yard_tiers")) else _leaf(data, ("envelope", "yard_tiers"))
    tiers = (leaf or {}).get("value") or []
    if not tiers or leaf is None:
        return None
    area = lot.get("lot_sqft")
    pick = None
    if area is not None:
        pick = next((x for x in tiers if _in_tier(x, area)), None)
    for x in tiers:
        if pick is not None and x is not pick:
            continue
        for k in YARDS:
            if k not in x:
                continue
            tier_leaf = _leaf_from(x, leaf, x[k] if pick is not None else None)
            tier_leaf["confidence"] = leaf["confidence"] if pick is not None else "secondary"
            if x.get("applies_to", "accessory") == "principal":
                if pick is not None:
                    principal[k] = (tier_leaf, "#yard_tiers")
                else:
                    principal[k] = (tier_leaf, "#yard_tiers")  # value None: depends on the tier
            else:
                picked[("envelope", k)] = (tier_leaf, "#yard_tiers")
    if pick is None:
        reasons.append(f"Yards depend on the lot size tier ({leaf['section']}). Give the lot size to get them")
    return [{**x, "chosen": x is pick} for x in tiers]


def _cap_in_scope(data: dict[str, Any], picked: Picked, lot: dict[str, Any]) -> Picked:
    """Drop the accessory structure cap when envelope.accessory_cap_districts leaves out the lot's district. Pass 17:
    drop the town's accessory height cap when envelope.accessory_height_cap_districts leaves it out (a district's own
    cap stays)."""
    scope = (_leaf(data, ("envelope", "accessory_cap_districts")) or {}).get("value")
    d = lot.get("zoning_district")
    if scope and d and _match_code(d, scope) is None:
        picked = {k: v for k, v in picked.items() if k != ("envelope", "accessory_structure_max_sqft")}
    h_scope = (_leaf(data, ("envelope", "accessory_height_cap_districts")) or {}).get("value")
    key = ("envelope", "accessory_structure_max_height_ft")
    if h_scope and d and _match_code(d, h_scope) is None and "#districts." not in (picked.get(key) or ({}, ""))[1]:
        picked = {k: v for k, v in picked.items() if k != key}
    return picked


def _accessory_yards_scope(picked: Picked, data: dict[str, Any], place: str, lot: dict[str, Any]) -> None:
    """Pass 18: envelope.accessory_yards_districts. The town's accessory side and rear yards hold only in these
    districts (Nanticoke 500-302C: unattached accessory structures in R zones). Elsewhere they are not used: the
    district row's accessory yards win, then its principal yards, and with neither no figure is given."""
    leaf = _leaf(data, ("envelope", "accessory_yards_districts"))
    d = lot.get("zoning_district")
    if not (_usable(leaf) and leaf.get("value") and d) or _match_code(d, leaf["value"]) is not None:
        return
    for k in ("setback_side_ft", "setback_rear_ft", "setback_rear_alley_ft"):
        if (picked.get(("envelope", k)) or ({}, ""))[0].get("value") is not None:
            picked[("envelope", k)] = ({**leaf, "value": None}, f"{place}#envelope.accessory_yards_districts")


def _rear_only_here(data: dict[str, Any], lot: dict[str, Any]) -> bool:
    """Pass 17: envelope.accessory_rear_yard_only_districts. False when it leaves out the lot's district."""
    scope = (_leaf(data, ("envelope", "accessory_rear_yard_only_districts")) or {}).get("value")
    d = lot.get("zoning_district")
    return not (scope and d and _match_code(d, scope) is None)


def _state_town_fixes(
    out: dict[str, Any],
    picked: Picked,
    lot: dict[str, Any],
    limits: dict[str, Any],
    citations: dict[str, Any],
    assumed: list[str],
    reasons: list[str],
) -> None:
    """The state floors win over a town share cap and a missing unit count."""
    bill = load_rules(STATE_REFORM)
    share_leaf = _leaf(bill, ("size", "max_share_of_house"))
    size_floor = limits.get("max_size_sqft", {}).get("for_this_lot")
    if out["max_share_of_house"] is not None and share_leaf and out["max_share_of_house"] < share_leaf["value"]:
        limits["max_share_of_house"] = {
            "mode": "at_least",
            "value": share_leaf["value"],
            "for_this_lot": share_leaf["value"],
            "section": share_leaf["section"],
            "note": "The town share cap may not sit under the state floor.",
        }
        out["max_share_of_house"] = share_leaf["value"]
        citations["max_share_of_house"] = _citation(share_leaf, STATE_REFORM)
    if out["max_size_sqft"] is None and size_floor is not None:
        town_share = _value(picked, "size", "max_share_of_house")
        if town_share is None:  # pass 9: the inside-the-house share of a house-and-unit cap
            town_share = _value(picked, "size", "max_share_of_house_and_unit")
        house = lot.get("house_sqft")
        if town_share is not None and house:
            out["max_size_sqft"] = max(round(town_share * house), size_floor)
            citations["max_size_sqft"] = _citation(_must_leaf(bill, ("size", "max_sqft")), STATE_REFORM)
    if out["max_adus"] is None and "max_adus" in limits:
        out["max_adus"] = int(limits["max_adus"]["value"])
        citations["max_adus"] = _citation(_must_leaf(bill, ("use", "max_adus")), STATE_REFORM)


def _round_spaces(rate: float, rule: str) -> int:
    """Pass 19: a parking count from a rate with the code's fraction rule (parking.fraction_rounding)."""
    whole = math.floor(rate + 1e-9)
    frac = rate - whole
    if frac <= 1e-9:
        return whole
    return whole + 1 if frac + 1e-9 >= FRACTION_RULES[rule][1] and (FRACTION_RULES[rule][1] > 0 or frac > 0) else whole


def _share_sqft(share: float, house: float, strict: bool = False) -> int:
    """A share of the house in sq ft. strict (pass 19, size.max_share_is_less_than): "less than" the share, so the
    largest whole sq ft under it (less than 70% of 2,000 sq ft is at most 1,399 sq ft)."""
    if strict:
        return math.ceil(round(share * house, 6)) - 1
    return round(share * house)


def _town_sizes(
    today: Picked,
    out: dict[str, Any],
    limits: dict[str, Any],
    state: bool,
    lot: dict[str, Any],
    today_forms: set[str],
    exempt: bool,
) -> tuple[dict[str, float | None], dict[str, float | None], dict[str, str | None]]:
    """Floor area and share caps per ADU type. Inside or attached: the internal caps. Detached,
    garage or over a garage: the accessory building caps. Each falls back to the general cap, and a cap
    for one form (size.max_sqft_by_form) wins. "X or Y% of the house" is the lesser unless
    size.cap_is_greater_of. A share-only cap is a number when the house size is known. Under the bill the
    town's figure is raised to the floor and the sentence says so. A form barred today and opened by the
    bill gets the bill floor alone, where the town caps ADU size at all."""
    gen_sqft = None if exempt else _value(today, "size", "max_sqft")
    gen_share = _value(today, "size", "max_share_of_house")
    greater = _value(today, "size", "cap_is_greater_of") is True
    by_form = _value(today, "size", "max_sqft_by_form") or {}
    share_by_form = _value(today, "size", "max_share_by_form") or {}
    part = _value(today, "size", "max_share_of_part")
    house_and_unit = _value(today, "size", "max_share_of_house_and_unit")  # pass 9
    strict_share = _value(today, "size", "max_share_is_less_than") is True  # pass 19: "less than 70%" (Nanticoke)
    caps = {
        "internal": (
            _value(today, "size", "max_sqft_internal"),
            _value(today, "size", "max_share_internal"),
        ),
        "accessory": (
            _value(today, "size", "max_sqft_accessory_building"),
            _value(today, "size", "max_share_accessory_building"),
        ),
    }
    bill = limits.get("max_size_sqft") if state else None
    floor = (bill or {}).get("for_this_lot")
    share_floor = limits.get("max_share_of_house", {}).get("value") if state else None
    house = lot.get("house_sqft")
    sizes: dict[str, float | None] = {}
    shares: dict[str, float | None] = {}
    rules_text: dict[str, str | None] = {}
    for t in ALL_TYPES:
        sqft, share = caps["internal" if t in PRINCIPAL_TYPES else "accessory"]
        sqft = gen_sqft if sqft is None else sqft
        share = gen_share if share is None else share
        if by_form.get(t) is not None:
            sqft = by_form[t]
        if share_by_form.get(t) is not None:
            share = share_by_form[t]
        hu_note = ""
        if house_and_unit is not None and share is None:
            # pass 9: a share of the house and the unit together. Inside the house it is that share of the house;
            # an added unit may be share / (1 - share) of the existing house
            share = house_and_unit if t == "internal" else round(house_and_unit / (1 - house_and_unit), 3)
            hu_note = f" ({house_and_unit:.0%} of the house and the unit together)"
        text: str | None = None
        if state and t not in today_forms:  # barred today, opened by the bill
            if (sqft is None and share is None) or bill is None:
                sizes[t], shares[t], rules_text[t] = None, None, None
                continue
            sizes[t], shares[t] = floor, None
            rules_text[t] = (
                "Not allowed by the town today. Under HB 2186 (not law) the town must allow at least the lesser of "
                f"50 percent of the house or {bill['value']:,.0f} sq ft"
                + (
                    f": {floor:,.0f} sq ft on this lot"
                    if floor is not None
                    else ". Give the house size to get the number"
                )
            )
            continue
        # pass 19: the general share cap is "less than" the share (size.max_share_is_less_than). The number is the
        # largest whole sq ft under it. A share for one form or part, or the bill's floor, is not strict
        strict = strict_share and share is not None and share == gen_share and t not in share_by_form
        if state and share_floor is not None and share is not None:
            strict = strict and share >= share_floor
            share = max(share, share_floor)
        town = sqft
        shr = f"{'less than ' if strict else ''}{share:.0%} of the house" if share is not None else ""
        if sqft is not None and share is not None:  # whichever is less, or greater
            n = (max if greater else min)(sqft, _share_sqft(share, house, strict)) if house else None
            text = f"At most {sqft:,.0f} sq ft or {shr}, whichever is {'greater' if greater else 'less'}"
            town = n if n is not None else (None if greater else sqft)
        elif share is not None:  # share only (pass 7)
            n = _share_sqft(share, house, strict) if house else None
            text = f"Less than {share:.0%} of the house" if strict else f"At most {share:.0%} of the house"
            town = n
        if text is not None:
            text += hu_note
            if n is not None and strict:
                text += f", so at most {n:,.0f} sq ft for this house"
            else:
                text += (
                    f": {n:,.0f} sq ft for this house" if n is not None else ". Give the house size to get the number"
                )
        if part:  # pass 8: a share of a named part of the house, which the tool cannot measure
            p_text = f"{part['share']:.0%} of the house's {part['part']}"  # pass 13: "at most" is said once
            if text is not None:
                text += f". Also at most {p_text}, which may be less"
            elif town is not None:
                text = (
                    f"At most {town:,.0f} sq ft and at most {p_text}, whichever is less. The tool cannot measure that "
                    f"part of the house, so {town:,.0f} sq ft is only the outer limit"
                )
            else:
                text = f"At most {p_text}. The tool cannot measure that part of the house, so no number is given"
        final = max(town, floor) if (state and floor is not None and town is not None) else town
        if text is not None and final != town:
            text += f". Under HB 2186 (not law) the town must allow at least {floor:,.0f} sq ft on this lot, so {final:,.0f} sq ft"
        sizes[t], shares[t], rules_text[t] = final, share, text
    return sizes, shares, rules_text


def _town_heights(
    data: dict[str, Any],
    today: Picked,
    status: str | None,
    state: bool,
    limits: dict[str, Any],
    citations: dict[str, Any],
    assumed: list[str],
    lot: dict[str, Any],
    by_type: dict[str, str],
) -> tuple[dict[str, float | None], list[str]]:
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
    if status in NO_ADU_STATUSES and state:
        at_house = None  # no ADU rule: neither the accessory cap nor the house rule is an ADU height
    principal_hit = today.get(DISTRICT_HEIGHT)
    principal = principal_hit[0]["value"] if principal_hit else None
    no_adu = status in NO_ADU_STATUSES
    if no_adu and not state:
        if structure is not None:
            notes.append(
                f"The {structure:g} ft limit is for accessory buildings. The code allows no ADU, so it is not an ADU height"
            )
        return {t: None for t in ALL_TYPES}, notes
    internal_flag = _value(today, "envelope", "internal_uses_district_height")
    inner = principal if internal_flag is not False else structure
    if principal_hit and internal_flag is not False:
        citations["max_height_by_type.internal"] = _citation(*principal_hit)
    if inner is None and lot.get("zoning_district") and (not no_adu or state):
        notes.append(
            f"District height for {lot['zoning_district']} not on file in feet. Height of a unit in the house not known"
        )

    def detached_for(t: str) -> float | None:
        h = garage if (t in GARAGE_TYPES and garage is not None) else structure
        if no_adu:
            h = None  # under the bill the town's accessory cap is not an ADU rule
        if h is None and applies is False and principal is not None:
            h = principal
        if at_house:
            h = house if h is None else (min(h, house) if house else h)
        return h

    det = {t: detached_for(t) for t in DETACHED_TYPES}
    if applies is False and structure is None and principal is not None and principal_hit and not no_adu:
        notes.append(
            f"No accessory height rule reaches an ADU here. The district height ({principal:g} ft) is used for a detached unit"
        )
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
            notes.append(
                f"House height unknown. Used the bill's {lim['value']:g} ft floor. The town may cap it at the house height if that is lower"
            )
        elif any(det[t] is not None and det[t] > floor for t in DETACHED_TYPES):
            notes.append(f"The town's own limit is above the bill's {floor:g} ft floor, so it stands")
        if no_adu and inner is None and principal is not None:
            inner = principal
    elif not any(by_type[t] in OK_PATHS for t in DETACHED_TYPES):
        pass  # no detached form allowed: no detached height line
    elif det["detached_new"] is None and not at_house:
        notes.append(NO_DETACHED_HEIGHT)
    out = {t: (inner if t in PRINCIPAL_TYPES else det[t]) for t in ALL_TYPES}
    if _value(today, "envelope", "attached_height_capped_at_house") is True:  # pass 7: an addition
        if house:
            out["attached"] = house if out["attached"] is None else min(out["attached"], house)
        elif by_type["attached"] in OK_PATHS:
            notes.append("An attached unit may not be taller than the house. House height unknown")
    for t in ALL_TYPES:
        if by_type[t] not in OK_PATHS:
            out[t] = None
    return out, notes


def _town_setbacks(
    picked: Picked,
    principal: dict[str, tuple[dict[str, Any], str]],
    limits: dict[str, Any],
    state: bool,
    by_type: dict[str, str],
    bind_all: bool = False,
) -> dict[str, dict[str, float | None]]:
    """Yards per ADU type. A unit inside the house adds no structure. An attached unit takes the
    district (principal) yards. A detached unit takes the accessory yards (the headline values).
    bind_all: pass 18, envelope.adu_yards_bind_all_forms. The ADU side and rear yards bind every form, so an attached
    unit takes the larger of the district yard and the ADU yard, and a unit in the house takes the ADU yard."""
    out: dict[str, dict[str, float | None]] = {}
    own_yards = ("setback_side_ft", "setback_rear_ft")
    for t in ALL_TYPES:
        if t == "internal" and bind_all and by_type[t] in OK_PATHS:
            out[t] = {k: (_value(picked, "envelope", k) if k in own_yards else None) for k in YARDS}
            continue
        if t == "internal" or by_type[t] not in OK_PATHS:  # no yards for a form not allowed here (pass 7)
            out[t] = {k: None for k in YARDS}
            continue
        yards = {}
        for k in YARDS:
            acc = _value(picked, "envelope", k)
            if t == "attached":  # part of the house: district yards, never a district accessory yard
                own = picked.get(("envelope", k))
                district_acc = bool(own and ".accessory_" in own[1])
                v = principal[k][0]["value"] if k in principal else (None if district_acc else acc)
                if bind_all and k in own_yards and acc is not None and not district_acc:
                    v = acc if v is None else max(v, acc)
            else:
                v = acc
            cap = state and k in limits and limits[k]["mode"] == "at_most" and v is not None
            if cap and t in NEW_STRUCTURE_TYPES and t != "attached":  # the bill's yard cap is for a separate unit
                v = min(v, limits[k]["value"])
            if state and t == "garage_conversion" and k in limits:
                v = None  # 6305(6): no setback for a conversion of an existing structure
            yards[k] = v
        out[t] = yards
    return out


def _town_parking(
    picked: Picked, today: Picked, state: bool, out: dict[str, Any], no_unit_rule: bool = False
) -> tuple[int | None, str | None]:
    """Total spaces on the lot and the open reading. Under the bill the ADU needs no space, so the
    town total drops by the spaces it asked for the ADU. No total where the code has no ADU rule."""
    total = _value(today, "parking", "total_on_site")
    reading = _value(today, "parking", "reading")
    if no_unit_rule:
        return None, reading
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


def find_places(name: Any, county: str | None = None) -> list[dict[str, Any]]:
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


def describe_place(name: Any, county: str | None = None) -> dict[str, Any] | None:
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


def lint(data: dict[str, Any]) -> list[str]:
    """Warnings that do not make a file invalid: a gate that bars with no lot test and no scope."""
    out = []
    for i, g in enumerate(((data.get("eligibility") or {}).get("gates") or {}).get("value") or []):
        scoped = (
            g.get("test")
            or g.get("districts")
            or g.get("not_districts")
            or g.get("building_types")
            or g.get("when") in ("historic", "not_historic")
            or g.get("overlays")  # pass 15: as the resolver reads it since pass 12, an overlay is a scope
        )
        if g.get("effect") == "bars" and not scoped:
            out.append(
                f"eligibility.gates[{i}] ({g.get('section')}): effect bars with no test and no scope. It is shown as a condition"
            )
    # pass 7: two cases where a file said something untrue
    status = ((data.get("adu") or {}).get("status") or {}).get("value")
    un_leaf = (data.get("approval") or {}).get("unlisted_use_path") or {}
    two = r"two-family|two family|duplex"
    # Said once per file, and not when the unlisted-use note already weighs the two-family reading
    said = bool(re.search(two, str(un_leaf.get("note") or "").lower()))
    alts = ((data.get("approval") or {}).get("alternatives") or {}).get("value") or []
    for i, a in enumerate(alts):
        words = " ".join(str(a.get(k) or "") for k in ("name", "conditions", "note")).lower()
        if status == "not_addressed" and un_leaf.get("value") and not said and re.search(two, words):
            said = True
            out.append(
                f"approval.alternatives[{i}] ({a.get('section')}): a two-family dwelling is listed, while the file sets "
                "unlisted_use_path with no word on it. A second unit may be read as that listed use, not an unlisted one. "
                "Say so in the unlisted_use_path note, or drop the path"
            )
        if not a.get("districts") and not a.get("overlays") and "overlay" in words:
            out.append(
                f"approval.alternatives[{i}] ({a.get('section')}): districts is null but the text names an overlay. "
                "Set overlays so it does not read as applying everywhere"
            )
    return out


def _cmd_validate() -> int:
    bad = 0
    for name in rule_names():
        errs = validate(json.loads((RULES_DIR / f"{name}.json").read_text()))
        print(f"{name}: {'ok' if not errs else f'{len(errs)} problems'}")
        for e in errs[:20]:
            print("  ", e)
        bad += bool(errs)
        for w in lint(json.loads((RULES_DIR / f"{name}.json").read_text())):
            print("   warning:", w)
    return 1 if bad else 0


def _yes_no(text: str | None) -> bool | None:
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
        "house_year_built": a.house_year_built,
        "accessory_building_year_built": a.accessory_building_year_built,
        "house_exists": _yes_no(a.house_exists),
        "public_sewer": _yes_no(a.public_sewer),
        "public_water": _yes_no(a.public_water),
        "slope_class": a.slope_class,
        "steep_slope_area": _yes_no(a.steep_slope_area),
        "landslide_area": _yes_no(a.landslide_area),
        "undermined_area": _yes_no(a.undermined_area),
        # Pass 9
        "historic_resource": _yes_no(a.historic_resource),
        "designated_on_plan": _yes_no(a.designated_on_plan),
        "lot_width_ft": a.lot_width_ft,
        "tract_sqft": a.tract_sqft,
        "in_growth_area": _yes_no(a.in_growth_area),
        "in_planned_development": _yes_no(getattr(a, "in_planned_development", None)),
        # Pass 18: the kind of planned or cluster development, as the code names it ("Option 3")
        "planned_development_kind": getattr(a, "planned_development_kind", None),
        "abuts_residential_district": _yes_no(getattr(a, "abuts_residential_district", None)),
        # Pass 19: feet from the new building to the top of bank of a watercourse
        "top_of_bank_ft": getattr(a, "top_of_bank_ft", None),
    }


def main(argv: list[str] | None = None) -> int:
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
    r.add_argument("--house-year-built", type=int)
    r.add_argument("--accessory-building-year-built", type=int)
    r.add_argument("--house-exists", help="yes or no: a lawful house already stands on the lot")
    r.add_argument("--public-sewer", help="yes or no")
    r.add_argument("--public-water", help="yes or no")
    r.add_argument("--slope-class", choices=SLOPE_CLASSES, help="measured slope class from the terrain block")
    r.add_argument("--steep-slope-area", help="yes or no: in the city's mapped steep slope area")
    r.add_argument("--landslide-area", help="yes or no: in the mapped landslide-prone area (Pittsburgh)")
    r.add_argument("--undermined-area", help="yes or no: in the mapped undermined area (Pittsburgh)")
    r.add_argument("--historic-resource", help="yes or no: on the town's historic resource inventory")
    r.add_argument("--designated-on-plan", help="yes or no: the lot is designated on the plan the code names")
    r.add_argument("--lot-width-ft", type=float)
    r.add_argument("--tract-sqft", type=float, help="area of the parent tract, when a rule tests the tract")
    r.add_argument("--in-growth-area", help="yes or no: inside the town's mapped growth area or boundary")
    r.add_argument(
        "--in-planned-development", help="yes or no: the lot is in a planned or cluster development the code names"
    )
    r.add_argument("--planned-development-kind", help="the kind of planned development, as the code names it")
    r.add_argument("--abuts-residential-district", help="yes or no: the lot abuts a residential district")
    r.add_argument(
        "--top-of-bank-ft", type=float, help="feet from the new building to the top of bank of a watercourse"
    )
    a = p.parse_args(argv)
    if a.cmd == "validate":
        return _cmd_validate()
    print(json.dumps(resolve(a.place, a.scenario, _lot_from_args(a)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
