"""Statewide table of Pennsylvania places: where can you build an ADU today.

One row per 2020 county subdivision (the 2,572 GEOIDs of app/public/data/towns.geojson). Each row gets
exactly one best evidence tier and one ADU status:

    verified     hand-read rule file, second check passed      (shared/rules, index status verified)
    drafted      hand-read rule file with open points          (index status drafted)
    reported     dated planning-agency inventory, or the official no-zoning record (DCED)
    text_search  public zoning text in the tier B corpus, no status claimed
    baseline     nothing local known, the statewide baseline applies

Run:  python -m pipeline.places_index build      # app/public/data/pa_places.json and the meta file
      python -m pipeline.places_index analyze    # MUSA 5500 tables and figures

See docs/PLACES.md. Not legal advice. Not a zoning determination.
"""
