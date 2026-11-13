"""python -m pipeline.places_index build | analyze"""

from __future__ import annotations

import argparse
import json

from pipeline.places_index.build import build
from pipeline.places_index.inputs import default_inputs, out_paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline.places_index", description="Statewide ADU places table")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="write app/public/data/pa_places.json, its meta file and the drive tables")
    an = sub.add_parser("analyze", help="MUSA 5500 tables and figures from the built table")
    an.add_argument("--no-forecast", action="store_true", help="skip the separate 2031 forecast run")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        r = build(default_inputs(), out_paths())
        print(json.dumps({k: v for k, v in r.items() if k != "counts"}, indent=1))
        for row in r["counts"]["by_tier"]:
            print(f"  {row['tier']:<12} {row['places']:>5} places  {row['pop_share']:.1%} of people")
        for row in r["counts"]["by_status"]:
            print(f"  {row['status']:<14} {row['places']:>5} places  {row['pop_share']:.1%} of people")
        return 0
    import pipeline.places_index.analysis as analysis

    analysis.run(forecast=not a.no_forecast)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
