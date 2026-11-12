"""Does a 600 sq ft backyard unit pay off? One test per 2020 tract.

The test
    cost  = size x cost per sq ft x (1 + soft costs), all borrowed
    pay   = monthly payment (pipeline.money.loan_payment), 30 years
    net   = rent x (1 - operating share)
    yes   = net covers the payment at the mid cost
    maybe = net covers the payment at the low cost, or is within the close band of the mid payment
    no    = anything else

Rent basis (one number everywhere)
    A 600 sq ft unit is a 1-bedroom, so the test uses a 1-bedroom rent: rent_b1 in
    rent_bedrooms_tract.csv. That is the tract median gross rent (B25064) times the
    county ratio of 1-bedroom to all-unit median rent (B25031). The tool uses the same
    column. Cross-checks: raw tract B25031 1-bedroom median, HUD SAFMR 1-bedroom by ZIP,
    and the all-unit median the first report used.

Run:  python -m pipeline.tract.payoff
Saves data/processed/payoff_tract.csv and, in <data root>/processed/5500/,
payoff_sensitivity.csv, payoff_bases.csv and payoff_summary.json.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from pipeline.market import load_safmr
from pipeline.money import loan_payment
from pipeline.tract.io import PROCESSED, RAW5500, item, lmh, out_dir, table, value, write_json

LEVELS = ("low", "mid", "high")
BASIS_LABELS = {
    "rent_b1": "1-bedroom, tract median x county B25031 ratio (headline, same as the tool)",
    "rent_b1_tract": "1-bedroom, raw tract B25031 median",
    "safmr_1br": "1-bedroom, HUD SAFMR FY2026 by ZIP",
    "median_rent_all": "All units, tract median B25064 (first report)",
}


@dataclass(frozen=True)
class Terms:
    """Everything the test needs. Built from shared/assumptions.json by default."""

    size_sqft: float
    psf: dict[str, float]
    soft: float
    years: float
    opex: float
    band: float
    rate: float

    @classmethod
    def from_assumptions(cls, rate_key: str = "financing.pmms30_2026_avg") -> Terms:
        return cls(
            size_sqft=value("payoff.size_sqft"),
            psf=lmh("payoff.hard_psf"),
            soft=value("payoff.soft_share"),
            years=value("payoff.loan_years"),
            opex=value("payoff.opex_share"),
            band=value("payoff.close_band"),
            rate=float(item(rate_key)["value"]),
        )

    def with_rate(self, rate: float) -> Terms:
        return Terms(self.size_sqft, self.psf, self.soft, self.years, self.opex, self.band, rate)


def build_cost(t: Terms) -> dict[str, float]:
    return {k: t.size_sqft * t.psf[k] * (1 + t.soft) for k in LEVELS}


def monthly_payment(t: Terms) -> dict[str, float]:
    """Monthly payment at each cost level, from the shared money model formula."""
    return {k: loan_payment(c, t.rate, t.years) for k, c in build_cost(t).items()}


def breakeven_rent(t: Terms) -> dict[str, float]:
    """Gross rent that exactly covers the payment after operating costs."""
    return {k: p / (1 - t.opex) for k, p in monthly_payment(t).items()}


def pays_test(rent: pd.Series, cost: float, cost_low: float, opex: float, band: float) -> pd.Series:
    """yes / maybe / no per rent. Blank where rent is blank."""
    net = rent * (1 - opex)
    out = np.where(net >= cost, "yes", np.where((net >= cost_low) | (net >= (1 - band) * cost), "maybe", "no"))
    return pd.Series(out, index=rent.index, dtype=object).where(rent.notna())


def classify(rent: pd.Series, t: Terms, level: str = "mid") -> pd.Series:
    pay = monthly_payment(t)
    return pays_test(rent, pay[level], pay["low"], t.opex, t.band)


# ------------------------------------------------------------------ rents
def safmr_by_tract(
    zip_table: pd.DataFrame | None = None, xwalk: pd.DataFrame | None = None, bedrooms: int = 1
) -> pd.Series:
    """SAFMR for a bedroom count, averaged over the ZIPs (ZCTAs) in each tract.

    Blocks are weighted by workers who live there (LODES RAC 2024) plus a tiny floor.
    A ZIP in two metro areas takes the lower rent, as in pipeline.market.
    """
    t = load_safmr() if zip_table is None else zip_table
    zr = t[t.bedrooms == bedrooms].groupby("zip").rent.min()
    if xwalk is None:
        xwalk = block_weights()
    x = xwalk.assign(rent=xwalk.zcta.map(zr)).dropna(subset=["rent"])
    w = x.groupby("trct").wt.sum()
    return (x.rent * x.wt).groupby(x.trct).sum().div(w).rename(f"safmr_{bedrooms}br")


def block_weights() -> pd.DataFrame:
    xw = pd.read_csv(RAW5500 / "jobs" / "pa_xwalk.csv.gz", dtype=str, usecols=["tabblk2020", "trct", "zcta"])
    rac = pd.read_csv(RAW5500 / "jobs" / "pa_rac_2024.csv.gz", dtype={"h_geocode": str}, usecols=["h_geocode", "C000"])
    xw = xw.merge(rac, left_on="tabblk2020", right_on="h_geocode", how="left")
    xw["wt"] = xw.C000.fillna(0) + 0.01
    return xw[["trct", "zcta", "wt"]]


def rent_bases(panel: pd.DataFrame, rent_br: pd.DataFrame, safmr: pd.Series) -> pd.DataFrame:
    """One row per tract with every rent basis (2024 dollars for ACS, FY2026 for SAFMR)."""
    r = panel[["GEOID", "pop_2024", "county"]].merge(
        rent_br[["GEOID", "rent_b1", "rent_b1_tract"]], on="GEOID", how="left"
    )
    r["safmr_1br"] = r.GEOID.map(safmr)
    r["median_rent_all"] = r.GEOID.map(panel.set_index("GEOID").median_rent_2024)
    return r


# ------------------------------------------------------------------ tables
def shares(p: pd.Series, weight: pd.Series | None = None) -> dict[str, float]:
    ok = p.notna()
    w = pd.Series(1.0, index=p.index) if weight is None else weight.fillna(0)
    tot = w[ok].sum()
    return {k: float(w[ok & (p == k)].sum() / tot) for k in ("yes", "maybe", "no")}


def sensitivity(bases: pd.DataFrame, rates: dict[str, float], t: Terms) -> pd.DataFrame:
    """Share of tracts yes / maybe / no for every rent basis x cost level x rate."""
    rows = []
    for basis in BASIS_LABELS:
        for rname, r in rates.items():
            tr = t.with_rate(r)
            for level in LEVELS:
                p = classify(bases[basis], tr, level)
                s = shares(p)
                sp = shares(p, bases.pop_2024)
                rows.append(
                    {
                        "rent_basis": basis,
                        "rate_name": rname,
                        "rate": r,
                        "cost_level": level,
                        "psf": t.psf[level],
                        "tracts": int(p.notna().sum()),
                        "share_yes": s["yes"],
                        "share_maybe": s["maybe"],
                        "share_no": s["no"],
                        "pop_share_yes": sp["yes"],
                    }
                )
    return pd.DataFrame(rows)


def basis_summary(bases: pd.DataFrame) -> pd.DataFrame:
    """Coverage and level of each rent basis, and how it compares with the headline."""
    rows = []
    for b, label in BASIS_LABELS.items():
        s = bases[b]
        both = s.notna() & bases.rent_b1.notna()
        rows.append(
            {
                "rent_basis": b,
                "label": label,
                "tracts": int(s.notna().sum()),
                "median": float(s.median()),
                "median_ratio_to_headline": float((s[both] / bases.rent_b1[both]).median()),
                "corr_with_headline": float(s[both].corr(bases.rent_b1[both])),
            }
        )
    return pd.DataFrame(rows)


def county_table(payoff: pd.DataFrame) -> pd.DataFrame:
    g = payoff.dropna(subset=["pays"]).groupby("county")
    out = g.agg(
        tracts=("GEOID", "size"),
        yes=("pays", lambda s: int((s == "yes").sum())),
        maybe=("pays", lambda s: int((s == "maybe").sum())),
        median_rent_b1=("rent_est", "median"),
    )
    out["share_yes"] = out.yes / out.tracts
    out["share_yes_or_maybe"] = (out.yes + out.maybe) / out.tracts
    return out.reset_index()


# ------------------------------------------------------------------ run
def run(save: bool = True) -> dict[str, Any]:
    panel = pd.read_csv(PROCESSED / "tract_panel.csv", dtype={"GEOID": str, "county": str})
    rent_br = pd.read_csv(PROCESSED / "rent_bedrooms_tract.csv", dtype={"GEOID": str})
    bases = rent_bases(panel, rent_br, safmr_by_tract())
    t = Terms.from_assumptions()
    t_now = Terms.from_assumptions("financing.pmms30")
    basis = table("payoff.rent_basis")["basis"]
    pay = monthly_payment(t)

    payoff = bases[["GEOID", "county"]].copy()
    payoff["rent_est"] = bases[basis].round(0)
    payoff["rent_basis"] = basis
    payoff["net_rent"] = (payoff.rent_est * (1 - t.opex)).round(0)
    payoff["cost_month"] = round(pay["mid"])
    payoff["cost_month_low"] = round(pay["low"])
    payoff["pays"] = classify(payoff.rent_est, t)
    payoff["margin"] = payoff.net_rent - payoff.cost_month
    payoff["pays_rate_now"] = classify(payoff.rent_est, t_now)
    payoff["pays_all_units"] = classify(bases.median_rent_all, t)
    payoff["pays_safmr"] = classify(bases.safmr_1br, t)
    payoff["rent_all_units"] = bases.median_rent_all.round(0)
    payoff["rent_safmr_1br"] = bases.safmr_1br.round(0)

    sens = sensitivity(bases, {"2026 average": t.rate, "latest week": t_now.rate}, t)
    bsum = basis_summary(bases)
    head = shares(payoff.pays)
    summary = {
        "rent_basis": basis,
        "rate": t.rate,
        "rate_now": t_now.rate,
        "build_cost": build_cost(t),
        "monthly_payment": pay,
        "breakeven_rent": breakeven_rent(t),
        "tracts_with_rent": int(payoff.pays.notna().sum()),
        "tracts": int(len(payoff)),
        "share_yes": head["yes"],
        "share_maybe": head["maybe"],
        "share_no": head["no"],
        "count": payoff.pays.value_counts().to_dict(),
        "pop_share": shares(payoff.pays, bases.pop_2024),
        "share_yes_all_units": shares(payoff.pays_all_units)["yes"],
        "share_yes_safmr": shares(payoff.pays_safmr)["yes"],
        "share_yes_rate_now": shares(payoff.pays_rate_now)["yes"],
        "safmr_tract_coverage": float(bases.safmr_1br.notna().mean()),
    }
    if save:
        keep_pred = PROCESSED / "payoff_tract.csv"
        if keep_pred.exists():  # forecast.py adds pred_growth; keep it until the forecast reruns
            old = pd.read_csv(keep_pred, dtype={"GEOID": str})
            if "pred_growth" in old:
                payoff = payoff.merge(old[["GEOID", "pred_growth"]], on="GEOID", how="left")
        payoff.drop(columns=["county"]).to_csv(PROCESSED / "payoff_tract.csv", index=False)
        sens.to_csv(out_dir() / "payoff_sensitivity.csv", index=False)
        bsum.to_csv(out_dir() / "payoff_bases.csv", index=False)
        county_table(payoff).to_csv(out_dir() / "payoff_county.csv", index=False)
        write_json(summary, out_dir() / "payoff_summary.json")
    return {
        "payoff": payoff,
        "bases": bases,
        "sensitivity": sens,
        "basis_summary": bsum,
        "summary": summary,
        "terms": t,
    }


def main() -> None:
    argparse.ArgumentParser(description="Tract payoff test for a 600 sq ft unit").parse_args()
    r = run()
    pd.set_option("display.width", 160)
    s = r["summary"]
    print(
        f"share yes: {s['share_yes']:.3f}  maybe: {s['share_maybe']:.3f}  no: {s['share_no']:.3f}"
        f"  ({s['tracts_with_rent']} tracts)"
    )
    print(r["basis_summary"].round(3).to_string(index=False))
    sens = r["sensitivity"]
    print(
        sens.pivot_table(index=["rent_basis", "rate_name"], columns="cost_level", values="share_yes")[
            list(LEVELS)
        ].round(3)
    )


if __name__ == "__main__":
    main()
