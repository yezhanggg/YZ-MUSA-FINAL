"""Lot-level money model: what a backyard home costs, what it rents for, and whether it pays.

Every number comes from shared/assumptions.json. app/src/lib/money.ts is the same
model in TypeScript. tests/fixtures/money_cases.json holds cases both must agree on
to the cent, so the screen and the reports cannot drift apart.

Functions are pure: they take the assumptions as an argument (default: the file)
and return plain dicts. Each result lists the assumption keys it used, so the
screen can show the source of every number.

Run:  python -m pipeline.money demo --zip 19143 --size 600 --type detached_new --place philadelphia
"""
from __future__ import annotations

import argparse
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence

ASSUMPTIONS_PATH = Path(__file__).resolve().parents[1] / "shared" / "assumptions.json"

Case = Literal["low", "mid", "high"]
CASES: tuple[Case, ...] = ("low", "mid", "high")
Place = Literal["philadelphia", "pittsburgh", "rest_of_pa"]
Verdict = Literal["pays", "close", "does_not_pay"]
Range = dict[str, float]
Assumptions = Mapping[str, Any]


# ------------------------------------------------------------------ assumptions
@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def load_assumptions(path: str | Path | None = None) -> dict[str, Any]:
    """The assumptions file as a dict. Cached: the pipeline calls this per lot."""
    return _load(str(path or ASSUMPTIONS_PATH))


class Used:
    """Collects the assumption keys a calculation reads."""

    def __init__(self, a: Assumptions):
        self.items: Mapping[str, Any] = a["items"]
        self.keys: set[str] = set()

    def item(self, key: str) -> Mapping[str, Any]:
        self.keys.add(key)
        return self.items[key]

    def value(self, key: str) -> float:
        return float(self.item(key)["value"])

    def range(self, key: str) -> Range:
        it = self.item(key)
        return {c: float(it[c]) for c in CASES}

    def table(self, key: str) -> Any:
        return self.item(key)["table"]

    def sorted(self) -> list[str]:
        return sorted(self.keys)


# ------------------------------------------------------------------ small math
def round_to(x: float, digits: int = 2) -> float:
    """Round half up. Same rule as Math.round in the browser, so both sides agree to the cent."""
    f = 10 ** digits
    return math.floor(x * f + 0.5) / f


def add_up(xs: Iterable[float]) -> float:
    """Plain left-to-right sum. Python's sum() compensates for rounding since 3.12,
    and the browser's does not, so both sides use this to agree to the cent."""
    total = 0.0
    for x in xs:
        total += x
    return total


def interp(points: Sequence[Sequence[float]], x: float) -> float:
    """Linear interpolation over [[x, y], ...] sorted by x. Flat beyond the ends."""
    if x <= points[0][0]:
        return float(points[0][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return float(y0 + (x - x0) / (x1 - x0) * (y1 - y0))
    return float(points[-1][1])


def loan_payment(principal: float, annual_rate: float, years: float) -> float:
    """Monthly payment on a fully amortized loan."""
    if principal <= 0 or years <= 0:
        return 0.0
    n = years * 12
    r = annual_rate / 12
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


def place_of(place: Optional[str]) -> Place:
    """Lots outside the two cities use the statewide numbers."""
    return place if place in ("philadelphia", "pittsburgh") else "rest_of_pa"  # type: ignore[return-value]


def bedrooms_for_size(size_sqft: float, a: Optional[Assumptions] = None, used: Optional[Used] = None) -> int:
    """Bedroom count a unit of this size rents as."""
    u = used or Used(a or load_assumptions())
    cuts = u.table("rents.bedroom_cuts_sqft")
    if size_sqft < cuts["studio_max"]:
        return 0
    if size_sqft < cuts["one_bed_max"]:
        return 1
    return 2


# ------------------------------------------------------------------ cost
def size_factor(size_sqft: float, u: Used) -> float:
    return interp(u.table("cost.size_curve")["points"], size_sqft)


def area_factor(place: Place, u: Used) -> float:
    acf = u.table("cost.area_cost_factor")
    return acf[place] / acf["reference"]


def permit_fee(place: Place, hard_cost: float, u: Used) -> float:
    """Fixed fees plus fees charged on construction value, inside the schedule's min and max."""
    p = u.table(f"soft.permits.{place}")
    return p["fixed"] + min(max(hard_cost * p["per_value"], p["min"]), p["max"])


def adu_cost(size_sqft: float, adu_type: str, place: Optional[str], quality: str = "standard",
             flags: Optional[Mapping[str, Any]] = None, a: Optional[Assumptions] = None,
             used: Optional[Used] = None) -> dict[str, Any]:
    """Itemised all-in cost, low / mid / high.

    flags: septic (bool, lot not on public sewer), hard_psf (number, replaces the
    mid build cost per sq ft from the screen; low and high keep their ratio to mid).
    """
    a = a or load_assumptions()
    u = used or Used(a)
    flags = flags or {}
    pl = place_of(place)
    psf = u.range(f"cost.hard_psf.{adu_type}")
    if flags.get("hard_psf") is not None:
        # The screen moves one number. Keep the spread around it.
        scale = float(flags["hard_psf"]) / psf["mid"]
        psf = {c: psf[c] * scale for c in CASES}
    mult = size_factor(size_sqft, u) * area_factor(pl, u) * u.table("cost.quality")[quality]
    site = u.table("cost.site_work")[adu_type]
    utility = u.table("cost.utility_connection")[adu_type]
    contingency = u.range("cost.contingency")
    design = u.range("soft.design")
    survey = adu_type in u.table("cost.survey_types")["types"]
    new_service = adu_type in u.table("cost.new_service_types")["types"]
    septic = bool(flags.get("septic"))

    items: dict[str, Range] = {k: {} for k in (
        "build", "site_work", "utility_connection", "septic_upgrade", "contingency",
        "design", "permits", "tap_fees", "survey", "construction_tax")}
    for c in CASES:
        build = size_sqft * psf[c] * mult
        items["build"][c] = build
        items["site_work"][c] = float(site[c])
        items["utility_connection"][c] = float(utility[c])
        items["septic_upgrade"][c] = u.range("cost.septic_upgrade")[c] if septic else 0.0
        base = build + site[c] + utility[c] + items["septic_upgrade"][c]
        items["contingency"][c] = base * contingency[c]
        items["design"][c] = build * design[c]
        items["permits"][c] = permit_fee(pl, build, u)
        items["tap_fees"][c] = float(u.table("soft.tap_fees")[pl][c]) if new_service else 0.0
        items["survey"][c] = u.range("soft.survey")[c] if survey else 0.0
        items["construction_tax"][c] = build * u.range("soft.construction_tax.philadelphia")[c] if pl == "philadelphia" else 0.0
    total = {c: add_up(items[k][c] for k in items) for c in CASES}
    return {
        "size_sqft": size_sqft,
        "adu_type": adu_type,
        "place": pl,
        "quality": quality,
        "items": {k: {c: round_to(v[c]) for c in CASES} for k, v in items.items()},
        "total": {c: round_to(total[c]) for c in CASES},
        "per_sqft": {c: round_to(total[c] / size_sqft) for c in CASES},
        "build_cost": {c: round_to(items["build"][c]) for c in CASES},
        "assumptions": u.sorted(),
    }


# ------------------------------------------------------------------ rent
def adu_rent_from_table(rent_by_bedroom: Mapping[str, Optional[float]], size_sqft: float,
                        a: Optional[Assumptions] = None, used: Optional[Used] = None,
                        source: str = "hud_safmr") -> dict[str, Any]:
    """Monthly rent for a unit of this size from {"b0": rent, "b1": ...}.

    If the matching bedroom count is missing, the next smaller one is used, so a
    missing 2 bedroom rent never makes the unit look richer.
    """
    u = used or Used(a or load_assumptions())
    beds = bedrooms_for_size(size_sqft, used=u)
    factor = u.value("rents.rent_factor")
    u.item("rents.source" if source == "hud_safmr" else "rents.fallback")
    for b in range(beds, -1, -1):
        r = rent_by_bedroom.get(f"b{b}")
        if r is not None:
            return {"rent": round_to(float(r) * factor), "bedrooms": beds, "rent_bedrooms": b,
                    "source": source, "assumptions": u.sorted()}
    return {"rent": None, "bedrooms": beds, "rent_bedrooms": None, "source": None, "assumptions": u.sorted()}


def adu_rent(zip_code: str, size_sqft: float, a: Optional[Assumptions] = None, table: Any = None) -> dict[str, Any]:
    """Rent for a ZIP from the HUD SAFMR table on the data drive."""
    from pipeline.market import rent_table_for_zips   # pandas only when a lookup is needed
    rents = rent_table_for_zips([zip_code], table).get(str(zip_code).zfill(5), {})
    out = adu_rent_from_table({f"b{b}": v for b, v in rents.items()}, size_sqft, a)
    out["zip"] = str(zip_code).zfill(5)
    return out


# ------------------------------------------------------------------ financing
def financing_terms(financing: Optional[Mapping[str, Any]], u: Used) -> dict[str, Any]:
    """Resolve a preset name plus screen overrides (rate, years, ltc) to loan terms."""
    f = dict(financing or {})
    name = f.get("preset") or u.table("financing.default_preset")["preset"]
    p = u.table("financing.presets")[name]
    rate = (u.value(p["rate_key"]) if p["rate_key"] else 0.0) + p["spread"]
    mip = u.value(p["mip_key"]) if p["mip_key"] else 0.0
    return {
        "preset": name,
        "label": p["label"],
        "rate": float(f["rate"]) if f.get("rate") is not None else rate,
        "years": float(f["years"]) if f.get("years") is not None else float(p["years"]),
        "ltc": float(f["ltc"]) if f.get("ltc") is not None else float(p["ltc"]),
        "mip": mip,
    }


# ------------------------------------------------------------------ tax
def tax_schedule(place: Place, added_value: float, years: int, u: Used) -> list[dict[str, float]]:
    """Added property tax per year after the unit is finished, with any abatement."""
    if place == "philadelphia":
        full = added_value * u.value("tax.philadelphia.rate")
        abated = u.table("tax.philadelphia.abatement")["schedule"]
    elif place == "pittsburgh":
        mills = u.table("tax.pittsburgh.millage")
        assessed = added_value * u.value("tax.pittsburgh.assessment_ratio")
        u.item("tax.pittsburgh.reassessment")
        full = assessed * (mills["county"] + mills["city"] + mills["school"]) / 1000
        abated = u.table("tax.pittsburgh.abatement")["schedule"]
    else:
        full = added_value * u.value("tax.rest_of_pa.effective_rate")
        abated = []
    out = []
    for y in range(1, years + 1):
        share = float(abated[y - 1]) if y <= len(abated) else 0.0
        out.append({"year": y, "abated_share": share, "tax": full * (1 - share)})
    return out


def tax_for_test(schedule: Sequence[Mapping[str, float]], basis: str) -> float:
    """Yearly tax the pay-off test uses: year 1, the 10-year average, or full tax."""
    if basis == "year1":
        return schedule[0]["tax"]
    if basis == "full":
        return schedule[-1]["tax"]
    first = schedule[:10]
    return add_up(s["tax"] for s in first) / len(first)


# ------------------------------------------------------------------ pro forma
def _case(cost: float, build: float, rent: float, place: Place, terms: Mapping[str, Any],
          self_managed: bool, basis: str, years: int, u: Used) -> dict[str, Any]:
    """Monthly numbers for one total cost."""
    loan = cost * terms["ltc"]
    equity = cost - loan
    debt = loan_payment(loan, terms["rate"], terms["years"]) + loan * terms["mip"] / 12
    vacancy = u.table("operating.vacancy")[place]
    mgmt_rate = 0.0 if self_managed else u.value("operating.management")
    maint_rate = u.value("operating.maintenance")
    collected = rent * (1 - vacancy)
    added_value = build * u.value("tax.assessed_share_of_build_cost")
    schedule = tax_schedule(place, added_value, years, u)
    tax_m = tax_for_test(schedule, basis) / 12
    fixed = (u.value("operating.insurance") + u.table("operating.rental_license")[place]) / 12 + tax_m
    opex = collected * (mgmt_rate + maint_rate) + fixed
    noi = collected - opex
    flow = noi - debt
    # Rent at which cash flow is zero: collected share of rent pays the fixed costs and the loan.
    keep = (1 - vacancy) * (1 - mgmt_rate - maint_rate)
    return {
        "loan": loan, "equity": equity, "debt_service": debt, "collected": collected,
        "vacancy": rent * vacancy, "management": collected * mgmt_rate, "maintenance": collected * maint_rate,
        "fixed": fixed, "tax": tax_m, "opex": opex, "noi": noi, "cash_flow": flow,
        "dscr": noi / debt if debt > 0 else None,
        "yield_on_cost": noi * 12 / cost if cost > 0 else None,
        "cash_on_cash": flow * 12 / equity if equity > 0 else None,
        "payback_years": cost / (noi * 12) if noi > 0 else None,
        "break_even_rent": (fixed + debt) / keep if keep > 0 else None,
        "schedule": schedule,
    }


def pct(x: float, digits: int) -> str:
    """Percent text, rounded half up first so Python and the browser print the same."""
    return f"{round_to(x * 100, digits):.{digits}f}%"


def verdict(mid: Mapping[str, Any], low: Mapping[str, Any], rent: float, u: Used) -> tuple[Verdict, str]:
    """pays | close | does_not_pay, with the reason in words. Rules live in verdict.rules."""
    rules = u.table("verdict.rules")
    band = rules["close_band"]
    if mid["debt_service"] > 0:
        need = f"{round_to(rules['dscr_pays'], 2):.2f}"
        if mid["cash_flow"] >= 0 and mid["dscr"] >= rules["dscr_pays"]:
            return "pays", f"Rent covers running costs and the loan with coverage {round_to(mid['dscr'], 2):.2f} (needs {need})."
        if low["cash_flow"] >= 0 or mid["cash_flow"] >= -band * rent:
            return "close", (f"Coverage {round_to(mid['dscr'], 2):.2f} (needs {need}). It pays at the low cost, "
                             f"or the monthly gap is within {pct(band, 0)} of rent.")
        return "does_not_pay", f"The monthly gap is more than {pct(band, 0)} of rent and it does not pay at the low cost."
    hurdle = u.value(rules["cash_hurdle_key"])
    y = mid["yield_on_cost"]
    if y >= hurdle:
        return "pays", f"Yield on cost {pct(y, 1)} beats the {pct(hurdle, 2)} mortgage rate."
    if y >= (1 - band) * hurdle or low["yield_on_cost"] >= hurdle:
        return "close", f"Yield on cost {pct(y, 1)} is near the {pct(hurdle, 2)} mortgage rate."
    return "does_not_pay", f"Yield on cost {pct(y, 1)} is well below the {pct(hurdle, 2)} mortgage rate."


def _money(x: Optional[float]) -> Optional[float]:
    return None if x is None else round_to(x, 2)


def _ratio(x: Optional[float]) -> Optional[float]:
    return None if x is None else round_to(x, 4)


def pro_forma(lot_facts: Mapping[str, Any], adu: Mapping[str, Any], financing: Optional[Mapping[str, Any]] = None,
              scenario: Optional[Mapping[str, Any]] = None, a: Optional[Assumptions] = None) -> dict[str, Any]:
    """Full monthly and yearly picture for one ADU on one lot.

    lot_facts: place, zip, septic (bool), rent_by_bedroom {"b0".."b4"} (from the lot
        record money block or the SAFMR table), rent_source ("hud_safmr" or "acs_b25031").
    adu: size_sqft, adu_type, quality (basic | standard | premium).
    financing: preset (cash | heloc | construction_to_perm | fha_203k | all_borrowed), rate, years, ltc.
    scenario: self_managed (default true), rent (monthly, replaces the looked-up rent),
        hard_psf (replaces the mid build cost per sq ft), tax_basis (year1 | avg10 | full).
    """
    a = a or load_assumptions()
    u = Used(a)
    sc = dict(scenario or {})
    place = place_of(lot_facts.get("place"))
    size = float(adu["size_sqft"])
    cost = adu_cost(size, adu["adu_type"], place, adu.get("quality", "standard"),
                    {"septic": bool(lot_facts.get("septic")), "hard_psf": sc.get("hard_psf")}, a, u)
    rent_info = adu_rent_from_table(lot_facts.get("rent_by_bedroom") or {}, size, used=u,
                                    source=lot_facts.get("rent_source") or "hud_safmr")
    if sc.get("rent") is not None:
        rent_info = {**rent_info, "rent": round_to(float(sc["rent"])), "source": "user"}
    terms = financing_terms(financing, u)
    rules = u.table("verdict.rules")
    basis = sc.get("tax_basis") or rules["tax_basis"]
    years = int(u.value("pro_forma.schedule_years"))
    self_managed = sc.get("self_managed", True)

    base = {"place": place, "zip": lot_facts.get("zip"), "adu": {"size_sqft": size, "adu_type": adu["adu_type"],
            "quality": adu.get("quality", "standard")}, "cost": cost, "rent": rent_info,
            "financing": {k: (round_to(v, 6) if isinstance(v, float) else v) for k, v in terms.items()}}
    rent = rent_info["rent"]
    if rent is None:
        return {**base, "verdict": None, "verdict_reason": "No market rent for this ZIP.", "assumptions": u.sorted()}

    cases = {c: _case(cost["total"][c], cost["build_cost"][c], rent, place, terms, self_managed, basis, years, u)
             for c in CASES}
    mid, low = cases["mid"], cases["low"]
    v, why = verdict(mid, low, rent, u)
    cap = u.range("value.cap_rate")
    # Value uses full (unabated) tax: a buyer pays full tax once the abatement ends.
    full_tax_m = mid["schedule"][-1]["tax"] / 12
    noi_full = mid["noi"] + mid["tax"] - full_tax_m
    return {
        **base,
        "monthly": {
            "rent": _money(rent),
            "vacancy": _money(mid["vacancy"]),
            "management": _money(mid["management"]),
            "maintenance": _money(mid["maintenance"]),
            "insurance_and_license": _money(mid["fixed"] - mid["tax"]),
            "property_tax": _money(mid["tax"]),
            "operating_costs": _money(mid["vacancy"] + mid["opex"]),
            "net_operating_income": _money(mid["noi"]),
            "loan_payment": _money(mid["debt_service"]),
            "cash_flow": _money(mid["cash_flow"]),
        },
        "cash_flow_by_cost": {c: _money(cases[c]["cash_flow"]) for c in CASES},
        "loan_amount": _money(mid["loan"]),
        "cash_in": _money(mid["equity"]),
        "tax": {
            "basis": basis,
            "added_value": _money(cost["build_cost"]["mid"] * u.value("tax.assessed_share_of_build_cost")),
            "schedule": [{"year": s["year"], "abated_share": s["abated_share"], "tax": _money(s["tax"])} for s in mid["schedule"]],
        },
        "break_even_rent": _money(mid["break_even_rent"]),
        "payback_years": _ratio(mid["payback_years"]),
        "yield_on_cost": _ratio(mid["yield_on_cost"]),
        "cash_on_cash": _ratio(mid["cash_on_cash"]),
        "dscr": _ratio(mid["dscr"]),
        "added_value": {
            "estimate": {c: _money(max(noi_full, 0.0) * 12 / cap[k]) for c, k in (("low", "high"), ("mid", "mid"), ("high", "low"))},
            "method": "Estimate. Yearly net operating income at full tax divided by a cap rate (value.cap_rate). Low uses the high cap rate.",
        },
        "verdict": v,
        "verdict_reason": why,
        "assumptions": u.sorted(),
    }



# ------------------------------------------------------------------ parity fixture
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "money_cases.json"

# (place, zip, adu_type, size, financing preset, extras). Covers both cities and the rest of the
# state, all five types, 300 to 1,000 sq ft, cash and every loan preset, and each screen override.
FIXTURE_SPECS: list[tuple[str, str, str, float, Optional[str], dict[str, Any]]] = [
    ("philadelphia", "19143", "detached_new", 600, None, {}),
    ("philadelphia", "19143", "detached_new", 600, "cash", {}),
    ("philadelphia", "19143", "detached_new", 600, "all_borrowed", {}),
    ("philadelphia", "19103", "detached_new", 300, "construction_to_perm", {}),
    ("philadelphia", "19103", "attached", 800, "heloc", {}),
    ("philadelphia", "19124", "garage_conversion", 400, "cash", {}),
    ("philadelphia", "19124", "internal", 500, "fha_203k", {}),
    ("philadelphia", "19119", "over_garage", 700, "construction_to_perm", {"quality": "premium"}),
    ("philadelphia", "19119", "detached_new", 1000, "construction_to_perm", {"scenario": {"self_managed": False}}),
    ("philadelphia", "19143", "detached_new", 450, "construction_to_perm", {"scenario": {"tax_basis": "year1"}}),
    ("philadelphia", "19143", "detached_new", 750, "construction_to_perm", {"scenario": {"tax_basis": "full"}}),
    ("philadelphia", "19143", "detached_new", 600, "construction_to_perm", {"scenario": {"rent": 1650, "hard_psf": 200}}),
    ("philadelphia", "19143", "detached_new", 600, "construction_to_perm", {"financing": {"rate": 0.055, "years": 25}}),
    ("pittsburgh", "15206", "detached_new", 600, None, {}),
    ("pittsburgh", "15206", "detached_new", 600, "cash", {}),
    ("pittsburgh", "15212", "garage_conversion", 350, "heloc", {}),
    ("pittsburgh", "15212", "over_garage", 900, "fha_203k", {}),
    ("pittsburgh", "15213", "internal", 300, "cash", {"quality": "basic"}),
    ("pittsburgh", "15213", "attached", 650, "construction_to_perm", {}),
    ("pittsburgh", "15232", "detached_new", 800, "all_borrowed", {"scenario": {"self_managed": False}}),
    ("pittsburgh", "15232", "detached_new", 1000, "cash", {}),
    ("rest_of_pa", "17011", "detached_new", 600, "construction_to_perm", {"septic": True}),
    ("rest_of_pa", "16801", "garage_conversion", 500, "cash", {}),
    ("rest_of_pa", "15601", "internal", 700, "heloc", {}),
    ("rest_of_pa", "15601", "attached", 1000, "fha_203k", {"septic": True}),
    ("rest_of_pa", "00000", "detached_new", 600, "construction_to_perm", {"no_rent": True}),
]


def build_fixture(path: Path = FIXTURE_PATH) -> Path:
    """Write the parity cases with Python's answers. The TypeScript test must match them."""
    from pipeline.market import rent_table_for_zips
    rents = rent_table_for_zips([z for _, z, *_ in FIXTURE_SPECS])
    cases = []
    for i, (place, z, kind, size, preset, extra) in enumerate(FIXTURE_SPECS):
        rbb = {} if extra.get("no_rent") else {f"b{b}": v for b, v in rents.get(z, {}).items()}
        lot = {"place": place, "zip": z, "septic": bool(extra.get("septic")), "rent_by_bedroom": rbb}
        adu = {"size_sqft": size, "adu_type": kind, "quality": extra.get("quality", "standard")}
        fin = {"preset": preset, **extra.get("financing", {})}
        sc = extra.get("scenario", {})
        cases.append({"id": f"{i:02d}_{place}_{kind}_{int(size)}_{preset or 'default'}",
                      "input": {"lot_facts": lot, "adu": adu, "financing": fin, "scenario": sc},
                      "expected": pro_forma(lot, adu, fin, sc)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"assumptions_version": load_assumptions()["version"],
                                "note": "Written by python -m pipeline.money fixture. Python and TypeScript must both reproduce these to the cent.",
                                "cases": cases}, indent=1) + "\n")
    return path


# ------------------------------------------------------------------ CLI
def _table(pf: Mapping[str, Any]) -> str:
    c = pf["cost"]
    rows = [("Place", pf["place"]), ("ZIP", pf.get("zip")), ("Type", f"{c['adu_type']} {c['size_sqft']:.0f} sq ft"),
            ("Total cost low / mid / high", " / ".join(f"${c['total'][k]:,.0f}" for k in CASES)),
            ("Cost per sq ft", " / ".join(f"${c['per_sqft'][k]:,.0f}" for k in CASES))]
    for k, v in c["items"].items():
        if v["mid"]:
            rows.append((f"  {k}", " / ".join(f"${v[x]:,.0f}" for x in CASES)))
    r = pf["rent"]
    rows.append(("Rent", f"${r['rent']:,.0f} a month ({r['bedrooms']} bedroom, {r['source']})" if r["rent"] else "none"))
    f = pf["financing"]
    rows.append(("Financing", f"{f['label']}: {f['ltc']:.0%} loan at {f['rate']:.2%} for {f['years']:.0f} years"))
    if pf.get("monthly"):
        for k, v in pf["monthly"].items():
            rows.append((f"  {k.replace('_', ' ')}", f"${v:,.0f}"))
        rows += [("Cash flow at low / mid / high cost", " / ".join(f"${pf['cash_flow_by_cost'][k]:,.0f}" for k in CASES)),
                 ("Break-even rent", f"${pf['break_even_rent']:,.0f}"),
                 ("Yield on cost", f"{pf['yield_on_cost']:.2%}"),
                 ("Payback years (cash basis)", f"{pf['payback_years']}" if pf["payback_years"] else "never"),
                 ("Debt coverage", f"{pf['dscr']}" if pf["dscr"] is not None else "no loan"),
                 ("Tax year 1 / year 11", f"${pf['tax']['schedule'][0]['tax']:,.0f} / ${pf['tax']['schedule'][10]['tax']:,.0f}"),
                 ("Added value (estimate)", " / ".join(f"${pf['added_value']['estimate'][k]:,.0f}" for k in CASES))]
    rows.append(("Verdict", f"{pf['verdict']}: {pf['verdict_reason']}"))
    w = max(len(k) for k, _ in rows)
    return "\n".join(f"{k:<{w}}  {v}" for k, v in rows)


def main() -> None:
    p = argparse.ArgumentParser(description="ADU money model")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="pro forma for one ZIP, size and type")
    d.add_argument("--zip", required=True)
    d.add_argument("--size", type=float, default=600)
    d.add_argument("--type", default="detached_new")
    d.add_argument("--place", default="philadelphia")
    d.add_argument("--quality", default="standard")
    d.add_argument("--financing", default=None, help="cash | heloc | construction_to_perm | fha_203k | all_borrowed")
    d.add_argument("--rate", type=float, default=None)
    d.add_argument("--septic", action="store_true")
    d.add_argument("--managed", action="store_true", help="pay a property manager")
    sub.add_parser("fixture", help="rewrite tests/fixtures/money_cases.json")
    args = p.parse_args()
    if args.cmd == "fixture":
        print(f"wrote {build_fixture()}")
        return
    from pipeline.market import rent_table_for_zips
    rents = rent_table_for_zips([args.zip]).get(args.zip.zfill(5), {})
    lot = {"place": args.place, "zip": args.zip, "septic": args.septic,
           "rent_by_bedroom": {f"b{b}": v for b, v in rents.items()}}
    pf = pro_forma(lot, {"size_sqft": args.size, "adu_type": args.type, "quality": args.quality},
                   {"preset": args.financing, "rate": args.rate}, {"self_managed": not args.managed})
    print(_table(pf))
    print()
    print(json.dumps(pf, indent=2))


if __name__ == "__main__":
    main()
