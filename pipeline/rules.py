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
PATH_ORDER = [
    "by_right",
    "administrator_exception",
    "special_exception",
    "conditional_use",
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
    for name in reversed(local + state):
        layer = load_rules(name) if name != place else data
        for key in ("path", "detached_in_yard_path", "historic_path", "fallback_path", "unlisted_use_path"):
            leaf = _leaf(layer, ("approval", key))
            if _usable(leaf) and leaf.get("value") == path:
                return _citation(leaf, name)
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
# Towns whose resolver output feeds published lot records (pipeline/build_lots.py), when a change to an
# output key that would change those records is held back for them until the lot data is rebuilt.
# Pass 8 lifted the pass 7 hold on Allentown (no ADU parking count where no ADU is allowed).
LOT_RECORD_TOWNS: set[str] = set()
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
}
LOT_TESTS: dict[str, str] = {
    "has_alley": "whether the lot has an alley (has_alley)",
    "has_accessory_building": "whether the lot has an accessory building (has_accessory_building)",
    "lot_sqft_at_least": "the lot area (lot_sqft)",
    "lot_sqft_below": "the lot area (lot_sqft)",
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
)
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


def _leaf_from(item: dict[str, Any], parent: dict[str, Any], value: Any) -> dict[str, Any]:
    """A leaf built from a list item (district path or gate), with the parent leaf's date and confidence."""
    return {
        "value": value,
        "section": item.get("section") or parent["section"],
        "url": item.get("url") or parent.get("url"),
        "verified_on": parent.get("verified_on"),
        "confidence": parent["confidence"],
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
        return code, row
    item, parent = hit  # the row for the lot's services replaces the public sewer and water figures
    merged = dict(row)
    for f in UTILITY_FIELDS:
        if f in item:
            merged[f] = _leaf_from(item, parent, item[f])
    return code, merged


def _utility_match(item: dict[str, Any], lot: dict[str, Any]) -> bool | None:
    """True when the lot's services match the item, None when a fact it names is not known."""
    out: bool | None = True
    for fact in ("public_sewer", "public_water"):
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
    return out


def _scope_line(scope: dict[str, Any], lot: dict[str, Any], with_section: bool) -> str:
    """Where the ADU rule reaches, and the status here when the lot is outside it."""
    sec = f" ({scope['section']})" if with_section else ""
    use = scope.get("use_open")
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


def _outside_scope_data(data: dict[str, Any], scope: dict[str, Any] | None = None) -> dict[str, Any]:
    """The file as it reads for a lot outside the ADU scope: no ADU numbers, the unlisted-use path or the fallback.
    A district with its own status outside the scope (adu.status_outside_by_district) takes that status."""
    keep: dict[str, Any] = {k: data[k] for k in ("provenance", "envelope", "coverage", "districts") if k in data}
    appr = data.get("approval") or {}
    path = appr.get("unlisted_use_path") if _usable(appr.get("unlisted_use_path")) else appr.get("fallback_path")
    approval = {k: appr[k] for k in ("fallback_path", "unlisted_use_path", "alternatives") if k in appr}
    if path:
        approval["path"] = path
    adu = dict(data.get("adu") or {})
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
    use_semi = (
        _building_type(lot.get("building_type")) == "semi_detached" and _usable(semi) and semi.get("value") is not None
    )
    for k in YARDS:  # accessory yards set for this district win for a detached unit
        acc = entry.get(f"accessory_{k}")
        if _usable(acc) and acc.get("value") is not None:
            picked[("envelope", k)] = (acc, f"{where}.accessory_{k}")
    for field, path in {
        **DISTRICT_FIELDS,
        "principal_max_height_ft": DISTRICT_HEIGHT,
        "separation_ft": ("envelope", "separation_ft"),
    }.items():
        leaf = semi if (field == "setback_side_ft" and use_semi) else entry.get(field)
        if not _usable(leaf):
            continue
        if field in YARDS and leaf.get("value") is not None:
            principal[field] = (leaf, where)
            own = picked.get(path)
            if own and own[0].get("value") is not None and (not bind or "accessory_" in own[1]):
                continue  # an accessory yard in the file wins for a detached unit
        if leaf.get("value") is None and (picked.get(path) or ({}, ""))[0].get("value") is not None:
            continue
        picked[path] = (leaf, where)
    by_type = entry.get("max_building_coverage_by_type")
    btype = _building_type(lot.get("building_type"))
    if _usable(by_type) and isinstance(by_type.get("value"), dict) and by_type["value"].get(btype) is not None:
        # Coverage set by building type: the lot's house type picks the share
        picked[("coverage", "max_building_coverage")] = (
            {**by_type, "value": by_type["value"][btype]},
            f"{where}.max_building_coverage_by_type.{btype}",
        )
    # Pass 7: the ADU size cap set by district, or lifted in a district (a null alone never wipes a value)
    cap = entry.get("adu_max_sqft")
    if _usable(cap) and cap.get("value") is not None:
        picked[("size", "max_sqft")] = (cap, f"{where}.adu_max_sqft")
    lift = entry.get("adu_size_cap_lifted")
    if _usable(lift) and lift.get("value") is True:
        for path in SIZE_PATHS:
            picked[path] = ({**lift, "value": None}, f"{where}.adu_size_cap_lifted")


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
    _apply_district_town(picked, data, place, lot, principal)
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
    _fill_defaults(picked, load_rules(DEFAULT))
    today = dict(picked)
    for name in state:
        _apply_state(picked, load_rules(name), name, lot, set(), limits, reasons)
    return picked, today, how, principal


def _unlisted_here(data: dict[str, Any], lot: dict[str, Any]) -> bool:
    """approval.unlisted_use_districts: the unlisted-use path reaches only these districts. With the
    district unknown the fallback stands (the path is said in the file's notes)."""
    only = (_leaf(data, ("approval", "unlisted_use_districts")) or {}).get("value")
    d = lot.get("zoning_district")
    return not only or (d is not None and _match_code(d, only) is not None)


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
    if (
        g.get("not_districts")
        and lot.get("zoning_district")
        and _match_code(lot["zoning_district"], g["not_districts"]) is not None
    ):
        return False
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


def _gate_met(g: dict[str, Any], lot: dict[str, Any]) -> bool | None:
    test, area = g.get("test"), lot.get("lot_sqft")
    if test in HOUSE_TESTS:
        return _house_met(test, g.get("value"), g.get("value_date"), lot)
    if test == "has_alley":
        return None if lot.get("has_alley") is None else bool(lot["has_alley"] or lot.get("corner_lot"))
    if test == "has_accessory_building":
        return lot.get("has_accessory_building")
    if test in ("lot_sqft_at_least", "lot_sqft_below") and g.get("value") is not None:
        if area is None:
            return None
        return area >= g["value"] if test == "lot_sqft_at_least" else area < g["value"]
    return None


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
    data: dict[str, Any], picked: Picked, lot: dict[str, Any], historic: bool, how: str | None, scope: dict[str, Any]
) -> list[dict[str, Any]]:
    """Who may live there, owner rule, existing-building-only, type, district and lot gates, each cited."""
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
    if status and status.get("value") and status["value"] != "allowed_by_right":
        out.append(
            _cond("adu_status", f"{status['value'].replace('_', ' ')}. {status.get('note') or ''}".strip(), status)
        )
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
        out.append(
            _cond(
                "other",
                f"The code does not list ADUs. A use not provided for may be approved by "
                f"{un['value'].replace('_', ' ')}. {un.get('note') or ''}".strip(),
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
    if own and own[0].get("value"):
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
    if dm and not historic:
        leaf, need, share = dm
        area = lot.get("lot_sqft")
        met = None if area is None else area >= need
        if _district_min_binds(data):
            rule = _leaf(data, ("eligibility", "requires_conforming_lot")) or _must_leaf(
                data, ("eligibility", "min_lot_share_of_district")
            )
            text = (
                f"The ADU needs a lot of at least {need:,.0f} sq ft"
                + (
                    f", {share:.0%} of the district minimum of {leaf['value']:,.0f}"
                    if share != 1
                    else ", the district minimum"
                )
                + f" ({rule['section']})"
            )
            out.append(_cond("lot_size", text, leaf, met, effect="bars"))
        elif _rcl_reading(data):  # a secondary reading: a condition with "if", never a bar
            rcl = _must_leaf(data, ("eligibility", "requires_conforming_lot"))
            out.append(
                _cond(
                    "lot_size",
                    f"If the ADU needs a lot that meets the district minimum of {leaf['value']:,.0f} sq ft "
                    f"({rcl['section']}, a reading that needs care)"
                    + (". This lot is below it. Ask the zoning officer" if met is False else ""),
                    leaf,
                    met,
                )
            )
        elif met is False:
            out.append(
                _cond(
                    "district_lot_rule",
                    f"This lot is below the district minimum of {leaf['value']:,.0f} sq ft. It may be a nonconforming lot. "
                    f"Ask the zoning officer whether an ADU is allowed on it",
                    leaf,
                    False,
                )
            )
        else:
            out.append(
                _cond(
                    "district_lot_rule",
                    f"The district's minimum lot is {leaf['value']:,.0f} sq ft. A rule for creating lots, not an ADU rule",
                    leaf,
                    met,
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
    bar = picked.get(("envelope", "front_yard_barred"))
    rear = picked.get(("envelope", "accessory_rear_yard_only"))
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
            dispute = g.get("disputed_by")
            if dispute and c["met"] is not True:  # pass 8: a bar another passage may undo. Depends, never a plain no
                c["disputed_by"] = dispute
                c["condition"] = (
                    c["condition"].rstrip(".")
                    + f" ({c['section']}). But {dispute['section']}: {dispute['note'].rstrip('.')}. "
                    "The code does not settle which reading holds. Ask the zoning officer"
                )
                if c["met"] is False:
                    c["effect"] = "condition"
            if c["test"] in HOUSE_TESTS and c["met"] is None:
                c["condition"] = (
                    c["condition"].rstrip(".") + f". Depends on {HOUSE_TESTS[c['test']]}, which was not given"
                )
            elif c["test"] and c["met"] is None:
                c["condition"] += ". Allowed only if this holds. The lot fact is not known"
            out.append(c)
    out += _utility_conditions(data, lot)
    return out


def _utility_conditions(data: dict[str, Any], lot: dict[str, Any]) -> list[dict[str, Any]]:
    """districts.<code>.utility_rows: the row shown assumes public sewer and water. Say the others, and that
    the figures depend on the services when they are not given."""
    code = _match_code(lot.get("zoning_district"), list((data.get("districts") or {}).keys()))
    leaf = (((data.get("districts") or {}).get(code) or {}) if code else {}).get("utility_rows")
    if not (_usable(leaf) and leaf.get("value")):
        return []
    out = []
    for item in leaf["value"]:
        met = _utility_match(item, lot)
        if met is False:
            continue
        figs = ", ".join(
            f"{f.replace('_ft', '').replace('_sqft', '').replace('_', ' ')} "
            + (f"{item[f]:.0%}" if f == "max_building_coverage" else f"{item[f]:,.0f}")
            for f in UTILITY_FIELDS
            if item.get(f) is not None
        )
        c = _cond(
            "utilities",
            f"{item['when']}: {figs}" + (f". {item['note']}" if item.get("note") else ""),
            _leaf_from(item, leaf, None),
            met,
        )
        if met is None:
            c["condition"] += (
                ". The district figures shown are for a lot with public sewer and water. "
                "Depends on whether the lot has public sewer and water (public_sewer, public_water), which was not given"
            )
            c["test"] = "public_sewer_water"
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


def _apply_gates(by_type: dict[str, str], conditions: list[dict[str, Any]], fallback: str, reasons: list[str]) -> None:
    for c in conditions:
        if c["effect"] != "bars" or c["met"] is True or c["kind"] == "lot_area_per_unit":
            continue
        if c["met"] is None and c.get("test"):
            continue  # unknown lot fact: allowed if the condition holds
        # a form the code does not name still fails a lot or house bar that reaches it (pass 7)
        hit = [
            t for t in (c["applies_to"] or ALL_TYPES) if by_type.get(t) in OK_PATHS or by_type.get(t) == "not_addressed"
        ]
        for t in hit:
            by_type[t] = fallback
        if hit:
            reasons.append(
                f"{c['condition']} ({c['section']}). Not allowed here: {', '.join(t.replace('_', ' ') for t in hit)}"
            )


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
    """Other ways to add a unit: not ADUs, or an ADU under another listing (adu_listing). applies is None when the
    lot facts do not settle it, and False for a path that needs three or more units."""
    leaf = _leaf(data, ("approval", "alternatives")) or {}
    out = []
    for a in leaf.get("value") or []:
        d, area = lot.get("zoning_district"), lot.get("lot_sqft")
        in_d = None if not a.get("districts") or d is None else _match_code(d, a["districts"]) is not None
        if not a.get("districts"):
            in_d = True
        min_lot = _alt_min_lot(a, d)
        lot_ok = None if min_lot is None or area is None else area >= min_lot
        applies = (
            False
            if (in_d is False or lot_ok is False)
            else (True if in_d and lot_ok is not False and (min_lot is None or lot_ok) else None)
        )
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
            flags.append(f"The {a['min_lot_sqft']:,.0f} sq ft minimum is for the development tract")
        if a.get("min_lot_by_district") and min_lot is not None and min_lot != a.get("min_lot_sqft"):
            flags.append(f"In {d} it needs a lot of at least {min_lot:,.0f} sq ft")
        open_tests = [text for m, text in tests if m is None]
        if open_tests and applies is None:
            flags.append("Applies only if: " + ". ".join(open_tests))
        failed = [text for m, text in tests if m is False]
        if failed:
            flags.append("Not on this lot: " + ". ".join(failed))
        lead = (
            "An ADU under another listing in the code, with its own path and standards"
            if a.get("adu_listing")
            else "Not an ADU. A second unit by another path"
        )
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
                + ("" if settled else ". The reading is not settled"),
            }
        )
    return out


def _depends_on(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bars and service rows whose lot or house fact was not given: the answer depends on them."""
    out = []
    for c in conditions:
        test = c.get("test")
        if not test or c["met"] is not None or (c["effect"] != "bars" and c["kind"] != "utilities"):
            continue
        fact = HOUSE_TESTS.get(test) or LOT_TESTS.get(test) or "whether the lot has public sewer and water"
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
    data = _outside_scope_data(file_data, scope) if scope["in_scope"] is False else file_data
    hist_leaf = _leaf(data, ("approval", "historic_path"))
    historic = False
    if (_leaf(data, ("eligibility", "historic_bypass")) or {}).get("value") or (
        _usable(hist_leaf) and hist_leaf.get("value")
    ):
        historic = _historic_town(data, lot, reasons)
    picked, today, how, principal = _pick_town(data, place, scenario, lot, historic, limits, reasons)
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
            f"The district's minimum lot is {leaf['value']:,.0f} sq ft ({leaf['section']})"
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
    doubt = _in_doubt(data, lot) if not state and not historic and how not in ("district", "historic") else None
    if doubt:  # listed in the district, while the ADU section names other districts: ask, never a plain no
        fails = [f for f in fails if not f.startswith("The ADU rule applies only in ")]
        fails.append(doubt["reason"])
    fallback = _value(picked, "approval", "fallback_path") or "variance"
    base = _value(picked, "approval", "path") or "not_allowed"
    eligible = not fails and base != "not_allowed"
    allowed_forms = _form_types_town(picked, lot)
    yard = _value(picked, "approval", "detached_in_yard_path")
    form_paths = [] if state else ((_leaf(data, ("approval", "form_paths")) or {}).get("value") or [])
    by_form_leaf = _leaf(data, ("adu", "status_by_form"))
    by_form = (by_form_leaf or {}).get("value") or None
    not_named = [] if state else ((_leaf(data, ("form", "types_not_addressed")) or {}).get("value") or [])
    # A lot that fails a district, type or size test needs a variance. A fallback of special exception
    # or conditional use (for example a district path) does not cure that.
    fail_path = fallback if (not fails or fallback not in OK_PATHS) else "variance"
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
            path = "not_allowed"  # pass 7: the code bars this form, so not a variance to ask for
        elif eligible and t in not_named and t not in allowed_forms and path not in OK_PATHS:
            path = "not_addressed"  # pass 7: the code does not name this form. Not a firm no
        by_type[t] = path
    named_out = [t for t in ALL_TYPES if by_type[t] == "not_addressed"]
    if named_out:
        nn = _must_leaf(data, ("form", "types_not_addressed"))
        reasons.append(
            f"The code does not name {', '.join(t.replace('_', ' ') for t in named_out)} ({nn['section']}). "
            "Not addressed for this form, not a firm no. Ask the zoning officer"
            + (f". {nn['note']}" if nn.get("note") else "")
        )
    conditions = _town_conditions(data, today if state else picked, lot, historic, how, scope)
    overridden: list[dict[str, Any]] = []
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
            reasons.append("Town lot rules the bill does not address still apply: " + ". ".join(kept))
        conditions = live
    else:
        _apply_gates(by_type, conditions, fallback, fails)
    types_allowed = [t for t in ALL_TYPES if by_type[t] in OK_PATHS]
    allowed = bool(types_allowed)
    depends = [] if state else _depends_on(conditions)
    approval = min(by_type.values(), key=PATH_ORDER.index)
    # No ADU rule here. A hearing path for a use the code does not list is a path to ask for, not an ADU allowed.
    path_to_ask = None
    no_rule_here = not state and status in NO_ADU_STATUSES and how not in ("district", "historic")
    lead = "The code bars ADUs here" if status == "prohibited" else "The code has no ADU rule here"
    if no_rule_here and allowed:
        ask = picked[("approval", "path")]
        if how == "unlisted":
            note = (
                f"{lead}. A use that is not listed may be authorized by "
                f"{ask[0]['value'].replace('_', ' ')} ({ask[0]['section']}). That is a hearing with no set standards for an ADU"
            )
        else:
            note = (
                f"{lead}. The rule file gives {ask[0]['value'].replace('_', ' ')} "
                f"({ask[0]['section']}) as the path to ask about. Ask the zoning officer"
            )
        path_to_ask = {"path": ask[0]["value"], "section": ask[0]["section"], "url": ask[0].get("url"), "note": note}
        allowed, types_allowed = False, []
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
            + ". ".join(f"{t.replace('_', ' ')} {v.replace('_', ' ')}" for t, v in by_form.items())
            + f" ({by_form_leaf['section']})"
        )
    if scope["districts"] and scope["in_scope"] is not True:
        head.append(_scope_line(scope, lot, with_section=True))
    tail = []
    if path_to_ask:
        if path_to_ask.get("kind") not in ("hearing", "listed_in_doubt"):  # those are said in the reasons already
            tail.append(path_to_ask["note"])
            if fb["note"] and path_to_ask["path"] == "variance":
                tail.append(fb["note"])
    elif not allowed:
        sec = fb["section"] or ""
        if fallback == "variance" and "910.2" not in sec:
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
        + tail
        + _town_type_reasons(_cap_in_scope(data, picked, lot), by_type)
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
        out[key] = int(value) if key in INTEGER_KEYS and value is not None else value
        if hit:
            citations[key] = _citation(*hit)
            if hit[1] == DEFAULT and value is not None:
                assumed.append(key)
    if _value(picked, "size", "cap_is_greater_of") is True and out["max_size_sqft"] is not None:
        # "X or Y% of the house, whichever is greater": X is not a maximum. A number only with the house size
        share, house = out["max_share_of_house"], lot.get("house_sqft")
        out["max_size_sqft"] = max(out["max_size_sqft"], round(share * house)) if share is not None and house else None
    if "max_adus" in assumed:
        out["reasons"].append(f"ADUs per lot: the code is silent, {out['max_adus']} assumed (default.json)")
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
    disputed = [c for c in conditions if c.get("disputed_by") and c["met"] is False]
    if allowed and disputed and not state:  # pass 8: the lot fails a bar whose reading is disputed
        qualifier = qualifier or "conditional_on_reading"
        out["reasons"].insert(
            0,
            ". ".join(
                f"{approval.replace('_', ' ').capitalize()} only if the reading that lets this lot in holds: "
                + c["condition"]
                for c in disputed
            ),
        )
    use_open = scope.get("use_open")
    if allowed and use_open and not state:  # pass 8: never a plain "allowed" where the use list is not on file
        qualifier = qualifier or "conditional_on_reading"
        out["reasons"].insert(
            0,
            f"{approval.replace('_', ' ').capitalize()} only if a {use_open['value']['use']} is a permitted use in "
            f"{lot.get('zoning_district')} ({use_open['section']}). This district's use list is not on file. "
            "Ask the zoning officer",
        )
    path_key = ("approval", "path") if (allowed or path_to_ask) else ("approval", "fallback_path")
    for key, path in (("approval_path", path_key), ("types_allowed", ("form", "types_allowed"))):
        if picked.get(path):
            citations[key] = _citation(*picked[path])

    if state:
        _state_town_fixes(out, picked, lot, limits, citations, assumed, reasons)
        if _value(today, "size", "max_sqft") is None and _value(today, "size", "max_share_of_house") is None:
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
    if acc_cap["binds"] is True and not state and acc_cap["height"] is not None:
        for t in DETACHED_TYPES:
            if heights[t] is not None or by_type[t] in OK_PATHS:
                heights[t] = acc_cap["height"] if heights[t] is None else min(heights[t], acc_cap["height"])
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
    setbacks = _town_setbacks(picked, principal, limits, state, by_type)
    front_bar = picked.get(("envelope", "front_yard_barred"))
    if front_bar and front_bar[0].get("value") is True:  # a bar, not a setback: no district front yard number
        for t in DETACHED_TYPES:
            setbacks[t]["setback_front_ft"] = None
        out["setback_front_ft"] = None
        citations["setback_front_ft"] = _citation(*front_bar)
        if "setback_front_ft" in assumed:
            assumed.remove("setback_front_ft")
    default_yards = [k for k in YARDS if k in assumed and out.get(k) is not None]
    if default_yards and allowed and not state:  # pass 8: a default yard is never the town's rule
        d = lot.get("zoning_district")
        figs = ", ".join(f"{k.split('_')[1]} {out[k]:g} ft" for k in default_yards)
        where = f"for {d}" if d else "for this lot"
        detached_ok = any(t in types_allowed for t in DETACHED_TYPES)
        out["reasons"].append(
            f"Yards: the town file has no yard figures {where}. The {figs} shown are a general default "
            "(default.json), not the town's rule. Ask the zoning officer"
            if detached_ok
            else f"Yards: the town file has no yard figures {where}, so an addition's yards are not known here. "
            "Ask the zoning officer"
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
    fire = {}
    for key, path in FIRE_KEYS.items():
        hit = picked.get(path)
        fire[key] = hit[0]["value"] if hit else None
        if hit:
            citations[f"fire_separation.{key}"] = _citation(*hit)
    no_unit_rule = not state and status in NO_ADU_STATUSES and how not in ("district", "historic")
    # pass 7: no ADU allowed on this lot today (a district not listed, a failed test): no ADU parking either
    no_unit_rule = no_unit_rule or (not state and not allowed and place not in LOT_RECORD_TOWNS)
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
            "alternatives": _alternatives(file_data, lot),
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
    _clean_owner_text(out)
    dp_path = dp[0]["value"] if dp else None
    if not state and status in BOARDS and dp_path and PATH_ORDER.index(dp_path) < PATH_ORDER.index(status):
        out["adu_status"] = "allowed_by_right" if dp_path == "by_right" else dp_path  # pass 8: the district leads
    if not state and status == "allowed_by_right" and dp_path in BOARDS:
        # pass 7: a district whose path is a hearing never reads "allowed by right"
        out["adu_status"] = dp_path
    if state and allowed and status and status != "allowed_by_right":
        # The bill overrides the town's status (conditions_overridden says so). Today's status is in the reasons.
        out["adu_status"] = "allowed_by_right"
    return {k: out[k] for k in OUTPUT_KEYS + TOWN_KEYS}


def _owner_text(text: Any) -> Any:
    """Pass 8: a sentence for the owner, without the author's bookkeeping (dates added, second checks)."""
    if not isinstance(text, str):
        return text
    out = text
    for pat, rep in BOOKKEEPING:
        out = pat.sub(rep, out)
    return out.strip() if out != text else text


def _clean_owner_text(out: dict[str, Any]) -> None:
    """Pass 8: every owner sentence built from a note goes through _owner_text."""
    out["reasons"] = [_owner_text(r) for r in out["reasons"]]
    for c in out.get("conditions") or []:
        c["condition"] = _owner_text(c["condition"])
    for c in out.get("depends_on") or []:
        c["condition"] = _owner_text(c["condition"])
    for a in out.get("alternatives") or []:
        a["note"] = _owner_text(a.get("note"))
        if a.get("conditions"):
            a["conditions"] = _owner_text(a["conditions"])
    for key in ("path_to_ask", "fallback"):
        if out.get(key) and out[key].get("note"):
            out[key]["note"] = _owner_text(out[key]["note"])


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
    parts = []
    for p in hearings:
        board, mpc = BOARDS[p]
        forms = [t for t in types_allowed if by_type[t] == p]
        which = "" if len(forms) == len(types_allowed) else f" ({', '.join(t.replace('_', ' ') for t in forms)})"
        parts.append(f"A {p.replace('_', ' ')}{which} is decided by {board} after a public hearing ({mpc})")
    sec = leaf["section"]
    mpc = BOARDS[path][1]
    return {
        "path": path,
        "section": sec if mpc in sec else f"{sec}, {mpc}",
        "url": leaf.get("url"),
        "note": ". ".join(parts),
        "kind": "hearing",
    }


def _in_doubt(data: dict[str, Any], lot: dict[str, Any]) -> dict[str, Any] | None:
    """eligibility.districts_in_doubt: the district lists the ADU, the ADU section names other districts."""
    leaf = _leaf(data, ("eligibility", "districts_in_doubt"))
    d = lot.get("zoning_district")
    if not (_usable(leaf) and leaf.get("value") and d) or _match_code(d, leaf["value"]) is None:
        return None
    named = (_leaf(data, ("eligibility", "zoning_districts")) or {}).get("value") or []
    reason = (
        f"{d} lists the ADU ({leaf['section']}), but the ADU section names "
        + (", ".join(named) if named else "other districts")
        + ". Listed, but ask the zoning officer or the Zoning Hearing Board whether it is allowed here"
        + (f". {leaf['note']}" if leaf.get("note") else "")
    )
    return {"reason": reason, "section": leaf["section"], "url": leaf.get("url")}


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


def _town_type_reasons(picked: Picked, by_type: dict[str, str]) -> list[str]:
    """The accessory building cap, said as a cap and only when the file stores one. Never as the reason."""
    cap = picked.get(("envelope", "accessory_structure_max_sqft"))
    if not (cap and cap[0].get("value") is not None):
        return _height_cap_reasons(picked, by_type)
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


def _height_cap_reasons(picked: Picked, by_type: dict[str, str]) -> list[str]:
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
        f"({leaf['section']}). {rule}Both are shown; the lower one is the safe reading. Ask the zoning officer"
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
        old = "No height number on file for a detached unit. Ask the zoning officer"
        new = f"Accessory buildings: at most {accessory:g} stories ({a_leaf['section']}). The code gives no feet figure"
        notes = [new if n == old else n for n in notes]
    return out, notes


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
        pick = next(
            (x for x in tiers if (x.get("min_lot_sqft") or 0) <= area < (x.get("max_lot_sqft") or float("inf"))), None
        )
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
    """Drop the accessory structure cap when envelope.accessory_cap_districts leaves out the lot's district."""
    scope = (_leaf(data, ("envelope", "accessory_cap_districts")) or {}).get("value")
    d = lot.get("zoning_district")
    if scope and d and _match_code(d, scope) is None:
        return {k: v for k, v in picked.items() if k != ("envelope", "accessory_structure_max_sqft")}
    return picked


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
        house = lot.get("house_sqft")
        if town_share is not None and house:
            out["max_size_sqft"] = max(round(town_share * house), size_floor)
            citations["max_size_sqft"] = _citation(_must_leaf(bill, ("size", "max_sqft")), STATE_REFORM)
    if out["max_adus"] is None and "max_adus" in limits:
        out["max_adus"] = int(limits["max_adus"]["value"])
        citations["max_adus"] = _citation(_must_leaf(bill, ("use", "max_adus")), STATE_REFORM)


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
        if state and share_floor is not None and share is not None:
            share = max(share, share_floor)
        town = sqft
        if sqft is not None and share is not None:  # whichever is less, or greater
            n = (max if greater else min)(sqft, round(share * house)) if house else None
            text = f"At most {sqft:,.0f} sq ft or {share:.0%} of the house, whichever is {'greater' if greater else 'less'}"
            town = n if n is not None else (None if greater else sqft)
        elif share is not None:  # share only (pass 7)
            n = round(share * house) if house else None
            text = f"At most {share:.0%} of the house"
            town = n
        if text is not None:
            text += f": {n:,.0f} sq ft for this house" if n is not None else ". Give the house size to get the number"
        if part:  # pass 8: a share of a named part of the house, which the tool cannot measure
            p_text = f"at most {part['share']:.0%} of the house's {part['part']}"
            if text is not None:
                text += f". Also {p_text}, which may be less"
            elif town is not None:
                text = (
                    f"At most {town:,.0f} sq ft and {p_text}, whichever is less. The tool cannot measure that part "
                    f"of the house, so {town:,.0f} sq ft is only the outer limit"
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
        notes.append("No height number on file for a detached unit. Ask the zoning officer")
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
) -> dict[str, dict[str, float | None]]:
    """Yards per ADU type. A unit inside the house adds no structure. An attached unit takes the
    district (principal) yards. A detached unit takes the accessory yards (the headline values)."""
    out: dict[str, dict[str, float | None]] = {}
    for t in ALL_TYPES:
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
    a = p.parse_args(argv)
    if a.cmd == "validate":
        return _cmd_validate()
    print(json.dumps(resolve(a.place, a.scenario, _lot_from_args(a)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
