"""MUSA 5500 analysis of the statewide places table.

Reads the built table (<data root>/processed/places/pa_places.csv) and the tract results already in
the repo (payoff_tract.csv, room_tract.csv, forecast_tract_inputs.csv), and writes:

    <data root>/processed/5500/places_by_status.csv        people and homes by ADU status today
    <data root>/processed/5500/places_by_tier.csv          people and homes by evidence tier
    <data root>/processed/5500/places_tier_x_status.csv
    <data root>/processed/5500/places_scenarios.csv        status shares today, under HB 2186 and SB 1346
    <data root>/processed/5500/places_legal_pays_room.csv  legal x pays x room, by tract piece in each town
    <data root>/processed/5500/places_summary.json         the headline numbers
    <data root>/processed/5500/forecast_places_alt.csv     separate 2031 run with classes from this table
    <data root>/processed/5500/forecast_places_alt.json    and its difference from forecast_summary.json
    musa5500/docs/figures/06_places_*.png

It never writes forecast_summary.json, town_legal_class.csv or any other forecast output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from pipeline.paths import data_root
from pipeline.tract import forecast as F
from pipeline.tract.io import FIGURES, PROCESSED, out_dir, table, value

# Status groups for people. no_zoning is kept apart from by_right: no zoning rule applies at all.
GROUP = {
    "by_right": "by right",
    "no_zoning": "no zoning",
    "limited": "limited",
    "not_addressed": "not allowed today",
    "prohibited": "not allowed today",
    "unknown": "not known",
}
GROUP_ORDER = ["by right", "no zoning", "limited", "not allowed today", "not known"]
# Colors: blue by right, aqua no zoning, yellow limited, red not allowed, gray not known. The four hues
# pass the dataviz palette validator on all pairs (CVD and normal vision); legends carry counts.
GROUP_COLORS = {
    "by right": "#1f5fa8",
    "no zoning": "#1baf7a",
    "limited": "#eda100",
    "not allowed today": "#c23b3a",
    "not known": "#d9d8d4",
}
TIER_ORDER = ["verified", "drafted", "reported", "text_search", "baseline"]
TIER_COLORS = {
    "verified": "#0b3c75",
    "drafted": "#2a78d6",
    "reported": "#7fb0ec",
    "text_search": "#c5dbf5",
    "baseline": "#ecebe8",
}
INK, MUTED = "#222222", "#6b6a66"
TODAY, BILL = "#2a78d6", "#eb6834"


def places_table(path: Path | None = None) -> pd.DataFrame:
    p = path or data_root() / "processed" / "places" / "pa_places.csv"
    t = pd.read_csv(p, dtype={"geoid": str, "main_geoid": str})
    t["group"] = t.status.map(GROUP)
    return t


def share_table(t: pd.DataFrame, col: str, order: list[str] | None = None) -> pd.DataFrame:
    pop, hu = t["pop"].fillna(0), t.housing_units.fillna(0)
    g = (
        t.assign(_p=pop, _h=hu)
        .groupby(col)
        .agg(places=("geoid", "size"), pop=("_p", "sum"), housing_units=("_h", "sum"))
    )
    g["pop_share"] = g["pop"] / pop.sum()
    g["hu_share"] = g.housing_units / hu.sum()
    g["places_share"] = g.places / len(t)
    if order:
        g = g.reindex([o for o in order if o in g.index])
    return g.reset_index()


def scenario_status(t: pd.DataFrame, scenario: str) -> pd.Series:
    """Status group of each place under a scenario. A bill makes one ADU by right in every
    municipality it reaches that has zoning; a place with no zoning is unchanged.
    HB 2186 reaches every municipality (Title 53). SB 1346 amends the MPC, so not Philadelphia or Pittsburgh."""
    g = t.group.copy()
    if scenario == "today":
        return g
    reach = pd.Series(True, index=t.index)
    if scenario == "sb1346":
        reach = ~t.geoid.isin([F.PHILADELPHIA, F.PITTSBURGH])
    zoned = t.status != "no_zoning"
    return g.where(~(reach & zoned), "by right")


def scenarios(t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sc in ("today", "hb2186", "sb1346"):
        g = scenario_status(t, sc)
        s = share_table(t.assign(group=g), "group", GROUP_ORDER)
        s.insert(0, "scenario", sc)
        rows.append(s)
    return pd.concat(rows, ignore_index=True)


def tract_pieces(t: pd.DataFrame, split: pd.DataFrame | None = None) -> pd.DataFrame:
    """Tract x town pieces with people, homes with room (mid) and the payoff screen of the tract."""
    split = split if split is not None else F.town_split()
    inputs = pd.read_csv(PROCESSED / "forecast_tract_inputs.csv", dtype={"GEOID": str})[["GEOID", "pop_2024", "pays"]]
    room = pd.read_csv(PROCESSED / "room_tract.csv", dtype={"GEOID": str})[
        ["GEOID", "lots_room_mid", "lots_room_low", "lots_room_high", "source"]
    ]
    p = split.merge(inputs, on="GEOID", how="left").merge(room, on="GEOID", how="left")
    for c in ("pop_2024", "lots_room_mid", "lots_room_low", "lots_room_high"):
        p[c] = p[c].fillna(0) * p.share
    p = p.merge(
        t[["geoid", "name", "status", "group", "tier", "zoning_authority", "legal_class"]],
        left_on="town_geoid",
        right_on="geoid",
        how="left",
    )
    return p


def legal_pays_room(p: pd.DataFrame) -> pd.DataFrame:
    """People and homes with room by legal path (today and under HB 2186) and payoff screen.

    legal = "permit" where a zoning permit is enough (by right, also with an owner-occupancy rule) or
    there is no zoning. Family-only, conversion-only and hearing paths are not counted as legal here."""
    rows = []
    permit = p.legal_class.isin(["by_right", "no_zoning"])
    for sc in ("today", "hb2186"):
        legal = np.where(permit, "permit", p.group) if sc == "today" else np.full(len(p), "permit")
        x = (
            p.assign(legal=legal)
            .groupby(["legal", "pays"], dropna=False)
            .agg(
                pop=("pop_2024", "sum"),
                lots_room_mid=("lots_room_mid", "sum"),
                lots_room_low=("lots_room_low", "sum"),
                lots_room_high=("lots_room_high", "sum"),
            )
            .reset_index()
        )
        x.insert(0, "scenario", sc)
        rows.append(x)
    return pd.concat(rows, ignore_index=True)


def headline(lpr: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sc in ("today", "hb2186"):
        x = lpr[lpr.scenario == sc]
        legal = x.legal == "permit"
        pays = x.pays.isin(["yes", "maybe"])
        out[sc] = {
            "lots_room_mid_all": float(x.lots_room_mid.sum()),
            "lots_room_mid_legal": float(x[legal].lots_room_mid.sum()),
            "lots_room_mid_legal_pays_yes_maybe": float(x[legal & pays].lots_room_mid.sum()),
            "lots_room_mid_legal_pays_yes": float(x[legal & (x.pays == "yes")].lots_room_mid.sum()),
            "lots_room_low_legal_pays_yes_maybe": float(x[legal & pays].lots_room_low.sum()),
            "lots_room_high_legal_pays_yes_maybe": float(x[legal & pays].lots_room_high.sum()),
            "pop_legal": float(x[legal]["pop"].sum()),
            "pop_legal_pays_yes_maybe": float(x[legal & pays]["pop"].sum()),
            "pop_all": float(x["pop"].sum()),
        }
    return out


# ------------------------------------------------------------------ separate 2031 forecast run
def alt_classes(t: pd.DataFrame) -> pd.DataFrame:
    """Town legal classes from this table, in the forecast's words. No zoning counts as by right
    (nothing in zoning holds an ADU back). Reported inventory statuses count. Unknown stays unknown."""
    cls = t.legal_class.fillna("unknown").replace({"no_zoning": "by_right"})
    return pd.DataFrame(
        {
            "town_geoid": t.geoid,
            "legal_class": cls,
            "review": t.tier.map({"verified": "verified", "drafted": "drafted"}).fillna("none"),
            "has_rule_file": t.rule_file.notna(),
        }
    )


def forecast_tract() -> pd.DataFrame:
    """Tract inputs of the saved forecast run (factor and the lots cap), rebuilt from saved files."""
    t = pd.read_csv(PROCESSED / "forecast_tract_inputs.csv", dtype={"GEOID": str})
    panel = pd.read_csv(
        PROCESSED / "tract_panel.csv", dtype={"GEOID": str}, usecols=["GEOID", "single_family_detached_2024"]
    )
    room = F.room_lots()
    t = t.merge(panel, on="GEOID", how="left").merge(room[["GEOID", "lots_fit"]], on="GEOID", how="left")
    t["lots_cap"] = t.lots_fit.where(t.lots_fit.notna(), t.single_family_detached_2024)
    return t[["GEOID", "pop_2024", "factor", "lots_cap"]]


def forecast_compare(t: pd.DataFrame, split: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    tract = forecast_tract()
    towns = gpd.read_file(PROCESSED / "towns_2020.gpkg", ignore_geometry=True)
    years = value("forecast.years")
    pop_pa = float(tract.pop_2024.sum())
    cur_classes = pd.read_csv(PROCESSED / "town_legal_class.csv", dtype={"town_geoid": str})
    out = {}
    only_nz = alt_classes(
        t.assign(legal_class=t.legal_class.where(t.tier.isin(["verified", "drafted"]) | (t.status == "no_zoning")))
    )
    variants = (("current_classes_rebuilt", cur_classes), ("places_table", alt_classes(t)), ("no_zoning_only", only_nz))
    for key, cls in variants:
        rules = F.town_rules_v2(towns, cls)
        pieces = F.adu_pieces(tract, split, rules, "v2")
        tot = F.scenario_totals(pieces, pop_pa, years)
        out[key] = (tot, pieces)
    saved = json.loads((out_dir() / "forecast_summary.json").read_text())["totals"]
    rows = []
    for sc in F.RULES:
        for lvl in ("low", "mid", "high"):
            rows.append(
                {
                    "scenario": sc,
                    "level": lvl,
                    "saved_forecast_summary": saved[sc][f"by_2031.{lvl}"],
                    "current_classes_rebuilt": float(out["current_classes_rebuilt"][0][("by_2031", lvl)][sc]),
                    "places_table_classes": float(out["places_table"][0][("by_2031", lvl)][sc]),
                }
            )
    cmp = pd.DataFrame(rows)
    cmp["difference"] = cmp.places_table_classes - cmp.current_classes_rebuilt
    pieces = out["places_table"][1]
    by_class = pieces[pieces.rule == "current"].groupby("adu_rule").adus_mid.sum().round(1).to_dict()
    cur = out["current_classes_rebuilt"][1]
    cur_by_class = cur[cur.rule == "current"].groupby("adu_rule").adus_mid.sum().round(1).to_dict()
    rebuilt_ok = bool(np.allclose(cmp.saved_forecast_summary, cmp.current_classes_rebuilt, rtol=1e-6, atol=1e-6))
    info = {
        "what": "Separate 2031 run. Same tract inputs and factors as the saved forecast (forecast_tract_inputs.csv, room_tract.csv). Only the town legal classes change: they come from pa_places (rule files as before, plus no-zoning places counted as by right and reported inventory statuses). Not adopted: forecast_summary.json and town_legal_class.csv are unchanged.",
        "rebuild_matches_saved": rebuilt_ok,
        "class_factors": table("forecast.legal_class_factor"),
        "mid_by_2031_current_rules": {
            "saved": cmp[(cmp.scenario == "current") & (cmp.level == "mid")].saved_forecast_summary.iloc[0],
            "places_table": cmp[(cmp.scenario == "current") & (cmp.level == "mid")].places_table_classes.iloc[0],
        },
        "mid_by_class_current_rules_places_table": by_class,
        "mid_by_class_current_rules_rebuilt": cur_by_class,
        "classes_places_table": alt_classes(t).legal_class.value_counts().to_dict(),
        "mid_by_2031_current_rules_no_zoning_only": float(out["no_zoning_only"][0][("by_2031", "mid")]["current"]),
        "note_no_zoning_only": "Rule files plus the no-zoning places only (inventory statuses left unknown), to split the difference between the two sources",
    }
    return cmp, info


# ------------------------------------------------------------------ figures
def _save(fig: Any, name: str) -> Path:
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / name
    fig.savefig(path, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def fig_maps(t: pd.DataFrame) -> Path:
    g = gpd.read_file(PROCESSED / "towns_2020.gpkg")[["GEOID", "geometry"]].to_crs(2271)
    g = g.merge(t[["geoid", "group", "tier"]], left_on="GEOID", right_on="geoid", how="left")
    counties = gpd.read_file(PROCESSED / "counties_2020.gpkg")[["geometry"]].to_crs(2271)
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.6))
    for ax, col, order, colors, title in (
        (axes[0], "group", GROUP_ORDER, GROUP_COLORS, "ADU status today"),
        (axes[1], "tier", TIER_ORDER, TIER_COLORS, "Best evidence for the answer"),
    ):
        for k in order:
            sub = g[g[col] == k]
            if len(sub):
                sub.plot(ax=ax, color=colors[k], edgecolor="white", linewidth=0.15)
        counties.boundary.plot(ax=ax, color="#9a9994", linewidth=0.35)
        ax.set_axis_off()
        ax.set_title(title, loc="left", fontsize=12, color=INK)
        n = g[col].value_counts()
        handles = [Rectangle((0, 0), 1, 1, color=colors[k]) for k in order]
        labels = [f"{k.replace('_', ' ')} ({n.get(k, 0):,})" for k in order]
        ax.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.02),
            ncol=3,
            frameon=False,
            fontsize=9,
            title="places in each class",
            title_fontsize=9,
        )
    fig.text(
        0.01,
        -0.06,
        "Pennsylvania county subdivisions (2,572). Status: hand-read rule files, DCED zoning filings (no zoning), planning-agency inventories. Not legal advice.",
        fontsize=8,
        color=MUTED,
    )
    return _save(fig, "06_places_status_map.png")


def fig_shares(sc: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(10, 3.2))
    names = {"today": "Today", "hb2186": "HB 2186 (passed House)", "sb1346": "SB 1346"}
    ys = list(range(3))[::-1]
    for y, s in zip(ys, ("today", "hb2186", "sb1346"), strict=True):
        x = sc[sc.scenario == s].set_index("group").reindex(GROUP_ORDER).pop_share.fillna(0)
        left = 0.0
        for k in GROUP_ORDER:
            w = float(x[k])
            if w <= 0:
                continue
            ax.barh(y, w - 0.002 if w > 0.004 else w, left=left, color=GROUP_COLORS[k], height=0.62)
            if w >= 0.045:
                ink = "white" if k in ("by right", "not allowed today") else INK
                ax.text(left + w / 2, y, f"{w:.0%}", ha="center", va="center", fontsize=9, color=ink)
            left += w
    ax.set_yticks(ys, [names[s] for s in ("today", "hb2186", "sb1346")])
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("Share of Pennsylvania residents (2025 estimates)", color=MUTED)
    handles = [Rectangle((0, 0), 1, 1, color=GROUP_COLORS[k]) for k in GROUP_ORDER]
    ax.legend(handles, GROUP_ORDER, ncol=5, loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=9)
    ax.set_title(
        "Where can you build an ADU: people by the rule in their municipality",
        loc="left",
        fontsize=12,
        color=INK,
        pad=30,
    )
    return _save(fig, "06_places_shares.png")


def fig_funnel(h: dict[str, Any]) -> Path:
    fig, ax = plt.subplots(figsize=(10, 3.4))
    steps = [
        ("Homes with room for a 600 sq ft unit", "lots_room_mid_all"),
        ("... where a zoning permit is enough, or no zoning", "lots_room_mid_legal"),
        ("... and the tract's rent pays (yes or maybe)", "lots_room_mid_legal_pays_yes_maybe"),
    ]
    ys = np.arange(len(steps))[::-1]
    for y, (_label, k) in zip(ys, steps, strict=True):
        today, bill = h["today"][k], h["hb2186"][k]
        ax.barh(y + 0.18, bill, height=0.34, color=BILL)
        ax.barh(y - 0.18, today, height=0.34, color=TODAY)
        ax.text(bill, y + 0.18, f"  {bill / 1e6:.2f} M", va="center", fontsize=8.5, color=INK)
        ax.text(today, y - 0.18, f"  {today / 1e6:.2f} M", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(ys, [s[0] for s in steps], fontsize=9)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v / 1e6:.1f} M")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("Homes (mid estimate, room model)", color=MUTED)
    handles = [Rectangle((0, 0), 1, 1, color=c) for c in (TODAY, BILL)]
    ax.legend(handles, ["today", "under HB 2186"], loc="lower right", frameon=False, fontsize=9)
    ax.set_title("Legal, pays off and has room", loc="left", fontsize=12, color=INK)
    return _save(fig, "06_places_legal_pays_room.png")


# ------------------------------------------------------------------ run
def run(forecast: bool = True, table_path: Path | None = None) -> dict[str, Any]:
    t = places_table(table_path)
    o = out_dir()
    by_status = share_table(t, "status", ["by_right", "no_zoning", "limited", "not_addressed", "prohibited", "unknown"])
    by_tier = share_table(t, "tier", TIER_ORDER)
    txs = (
        t.assign(_p=t["pop"].fillna(0), _h=t.housing_units.fillna(0))
        .groupby(["tier", "status"])
        .agg(places=("geoid", "size"), pop=("_p", "sum"), housing_units=("_h", "sum"))
        .reset_index()
    )
    txs["pop_share"] = txs["pop"] / t["pop"].sum()
    sc = scenarios(t)
    by_status.to_csv(o / "places_by_status.csv", index=False)
    by_tier.to_csv(o / "places_by_tier.csv", index=False)
    txs.to_csv(o / "places_tier_x_status.csv", index=False)
    sc.to_csv(o / "places_scenarios.csv", index=False)

    split = F.town_split()
    pieces = tract_pieces(t, split)
    lpr = legal_pays_room(pieces)
    lpr.to_csv(o / "places_legal_pays_room.csv", index=False)
    h = headline(lpr)

    known = t[t.status != "unknown"]
    summary: dict[str, Any] = {
        "built_from": "processed/places/pa_places.csv (python -m pipeline.places_index build)",
        "pop_total": float(t["pop"].sum()),
        "status_pop_share": dict(zip(by_status.status, by_status.pop_share.round(4), strict=True)),
        "status_places": dict(zip(by_status.status, by_status.places.astype(int), strict=True)),
        "tier_pop_share": dict(zip(by_tier.tier, by_tier.pop_share.round(4), strict=True)),
        "tier_places": dict(zip(by_tier.tier, by_tier.places.astype(int), strict=True)),
        "known_status_pop_share": float(known["pop"].sum() / t["pop"].sum()),
        "scenario_by_right_or_no_zoning_pop_share": {
            s: float(sc[(sc.scenario == s) & sc.group.isin(["by right", "no zoning"])].pop_share.sum())
            for s in ("today", "hb2186", "sb1346")
        },
        "legal_pays_room": h,
    }
    if forecast:
        cmp, info = forecast_compare(t, split)
        cmp.to_csv(o / "forecast_places_alt.csv", index=False)
        (o / "forecast_places_alt.json").write_text(json.dumps(info, indent=2, default=float) + "\n")
        summary["forecast_alt"] = {
            "mid_current_rules": info["mid_by_2031_current_rules"],
            "rebuild_matches_saved": info["rebuild_matches_saved"],
        }
    (o / "places_summary.json").write_text(json.dumps(summary, indent=2, default=float) + "\n")
    figs = [fig_maps(t), fig_shares(sc), fig_funnel(h)]
    print(json.dumps(summary, indent=1, default=float))
    print("figures:", *[str(f) for f in figs], sep="\n  ")
    return summary
