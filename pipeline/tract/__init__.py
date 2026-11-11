"""Tract-level analysis for MUSA 5500: growth, trend groups, payoff, forecast.

Each module holds logic that used to live in the course notebooks. The notebooks
now load data, call these functions and show the result.

Modules:
    io        where inputs and outputs live, and the tract settings in shared/assumptions.json
    acs_moe   ACS margins of error from the Census summary files (no key needed)
    growth    2010 to 2020 tract crosswalk, growth before and after 2019, MOE flags
    groups    trend groups: scaling check, k sweep, stability, three methods compared
    payoff    rent vs cost test for a 600 sq ft unit, with a sensitivity table
    forecast  housing growth model, validation, intervals, ADUs by 2031
    migration IRS county migration rates
    viz       linked interactive chart for the course site
"""
