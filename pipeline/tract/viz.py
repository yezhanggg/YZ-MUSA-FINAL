"""Linked interactive view for the course site (Altair, cross-filter).

    county map  -- click counties (shift-click for more) to filter everything
    scatter     -- tracts: 1-bedroom rent vs predicted 10-year housing growth. Drag a box to brush
    bars        -- trend groups of the selected tracts
    histogram   -- monthly margin (net rent minus payment) of the selected tracts
    table       -- the 12 selected tracts with the best margin

Saves musa5500/figures/tract_explorer.html (standalone, loads Vega from a CDN) and the
Vega-Lite spec as tract_explorer.vl.json. Data is embedded: one row per tract with 7 fields,
and county shapes simplified to about 1 km.

Run:  python -m pipeline.tract.viz
"""

from __future__ import annotations

import argparse
import json
import warnings

import altair as alt
import geopandas as gpd
import pandas as pd

from pipeline.tract.io import INTERACTIVE, PROCESSED

PAYS_COLORS = {"yes": "#1a9850", "maybe": "#d9a400", "no": "#c0392b"}


def tract_table() -> pd.DataFrame:
    pay = pd.read_csv(PROCESSED / "payoff_tract.csv", dtype={"GEOID": str})
    tr = pd.read_csv(PROCESSED / "trends_tract.csv", dtype={"GEOID": str}, usecols=["GEOID", "trend_group"])
    names = gpd.read_file(PROCESSED / "counties_2020.gpkg", ignore_geometry=True).set_index("GEOID").NAME
    t = pay[["GEOID", "rent_est", "margin", "pays", "pred_growth"]].merge(tr, on="GEOID", how="left")
    t = t.dropna(subset=["rent_est", "pays", "pred_growth"])
    t["county"] = t.GEOID.str[:5]
    t["county_name"] = t.county.map(names)
    t["growth_pct"] = (t.pred_growth * 100).clip(-30, 60).round(1)  # clip for the axis only
    t["rent"] = t.rent_est.round(0)
    t["margin"] = t.margin.round(0)
    t["tract"] = t.GEOID.str[5:]
    return t[["tract", "county_name", "rent", "margin", "pays", "growth_pct", "trend_group"]]


def county_shapes(tracts: pd.DataFrame) -> gpd.GeoDataFrame:
    c = gpd.read_file(PROCESSED / "counties_2020.gpkg")[["GEOID", "NAME", "geometry"]].to_crs(4326)
    with warnings.catch_warnings():  # one county ring has a repeated point. Simplify still returns a valid shape
        warnings.simplefilter("ignore", RuntimeWarning)
        c["geometry"] = c.geometry.simplify(0.01, preserve_topology=True)
    share = tracts.groupby("county_name").pays.apply(lambda s: float((s == "yes").mean()))
    c["share_yes"] = c.NAME.map(share).round(3)
    return c.rename(columns={"NAME": "county_name"})[["county_name", "share_yes", "geometry"]]


def chart(t: pd.DataFrame, counties: gpd.GeoDataFrame) -> alt.VConcatChart:
    pick = alt.selection_point(fields=["county_name"], name="county_pick")
    brush = alt.selection_interval(encodings=["x", "y"], name="brush")
    color = alt.Color(
        "pays:N", title="Pays off?", scale=alt.Scale(domain=list(PAYS_COLORS), range=list(PAYS_COLORS.values()))
    )
    # alt.Data has no annotations (only **kwds). alt.InlineData is typed, but altair then inlines
    # the counties instead of listing them under "datasets", which changes the saved spec.
    # unused-ignore: where altair is not installed (CI) it is Any and the ignore has nothing to silence.
    geo = alt.Data(values=json.loads(counties.to_json())["features"])  # type: ignore[no-untyped-call,unused-ignore]
    cmap = (
        alt.Chart(geo)
        .mark_geoshape(stroke="white", strokeWidth=0.5)
        .encode(
            color=alt.Color(
                "properties.share_yes:Q", title="Share of tracts that pay", scale=alt.Scale(scheme="greens")
            ),
            opacity=alt.condition(pick, alt.value(1), alt.value(0.35)),
            tooltip=[
                alt.Tooltip("properties.county_name:N", title="County"),
                alt.Tooltip("properties.share_yes:Q", title="Share yes", format=".0%"),
            ],
        )
        .transform_calculate(county_name="datum.properties.county_name")
        .add_params(pick)
        .project("mercator")
        .properties(width=380, height=230, title="Click a county (shift for more)")
    )
    base = alt.Chart(t).transform_filter(pick)
    scatter = (
        base.mark_circle(size=14, opacity=0.6)
        .encode(
            x=alt.X("rent:Q", title="1-bedroom rent, $ per month", scale=alt.Scale(zero=False)),
            y=alt.Y("growth_pct:Q", title="Predicted housing growth 2020-30, %"),
            color=alt.condition(brush, color, alt.value("#d0d0d0")),
            tooltip=["county_name:N", "tract:N", "rent:Q", "margin:Q", "pays:N", "trend_group:N"],
        )
        .add_params(brush)
        .properties(width=380, height=230, title="Drag a box to select tracts")
    )
    sel = base.transform_filter(brush)
    bars = (
        sel.mark_bar()
        .encode(
            x=alt.X("count():Q", title="Tracts"),
            y=alt.Y("trend_group:N", title=None, sort="-x"),
            color=alt.value("#4c72b0"),
        )
        .properties(width=380, height=200, title="Trend groups in the selection")
    )
    hist = (
        sel.mark_bar()
        .encode(
            x=alt.X("margin:Q", bin=alt.Bin(maxbins=30), title="Net rent minus payment, $"),
            y=alt.Y("count():Q", title="Tracts"),
            color=color.legend(None),
        )
        .properties(width=380, height=200, title="Monthly margin in the selection")
    )
    table = (
        sel.transform_window(rank="row_number()", sort=[alt.SortField("margin", order="descending")])
        .transform_filter(alt.datum.rank <= 12)
        .mark_text(align="left", fontSize=11)
        .encode(y=alt.Y("rank:O", axis=None), text=alt.Text("label:N"))
        .transform_calculate(
            label="datum.county_name + ' ' + datum.tract + '   rent $' + datum.rent"
            " + '   margin $' + datum.margin + '   ' + datum.pays"
        )
        .properties(width=780, height=200, title="Best 12 tracts in the selection, by margin")
    )
    return (
        alt.vconcat(alt.hconcat(cmap, scatter), alt.hconcat(bars, hist), table)
        .properties(title="Pennsylvania tracts: does a 600 sq ft backyard home pay off?")
        .configure_view(stroke=None)
    )


def run() -> dict[str, float]:
    t = tract_table()
    c = county_shapes(t)
    ch = chart(t, c)
    INTERACTIVE.mkdir(parents=True, exist_ok=True)
    html = INTERACTIVE / "tract_explorer.html"
    spec = INTERACTIVE / "tract_explorer.vl.json"
    ch.save(html)
    spec.write_text(json.dumps(ch.to_dict(), separators=(",", ":")))
    return {"html_kb": html.stat().st_size / 1024, "spec_kb": spec.stat().st_size / 1024, "tracts": len(t)}


def main() -> None:
    argparse.ArgumentParser(description="Linked interactive tract view").parse_args()
    print(run())


if __name__ == "__main__":
    main()
