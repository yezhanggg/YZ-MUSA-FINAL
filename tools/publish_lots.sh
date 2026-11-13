#!/usr/bin/env bash
# Rebuild the lot data bundle for the data repository (GitHub Pages). Copies only the files the app reads
# from the lot build on the drive, leaves out the sale and assessment facts of each lot, removes local paths from
# the metadata, and writes the data README.
# Nothing is uploaded. Publishing is a manual step: see docs/HOSTING.md.
#
#   tools/publish_lots.sh                 # from ~/musa-drive/lots to ~/musa-drive/host
#   LOT_DATA_DIR=... LOT_HOST_DIR=... tools/publish_lots.sh
#
# Output (LOT_HOST_DIR):
#   README.md  .nojekyll  .gitignore
#   lots/<place>/manifest.json  stats.json  lot_tract.json
#   lots/<place>/detail/<GEOID>.json.gz  (+ <GEOID>.geom.json.gz, <GEOID>.pN.json.gz when the build split a tract)
#   lots/<place>/tiles/parcels.pmtiles
#   lots/<place>/tiles/lots.pmtiles  overview.pmtiles  (when built: "Show testable lots", app/build_lot_tiles.py)
set -euo pipefail

SRC="${LOT_DATA_DIR:-$HOME/musa-drive/lots}"
OUT="${LOT_HOST_DIR:-$HOME/musa-drive/host}"
PLACES="${LOT_PLACES:-pittsburgh philadelphia}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

case "$OUT" in
  "$REPO"*) echo "LOT_HOST_DIR is inside the app repo. Use a folder on the drive." >&2; exit 1 ;;
esac

for p in $PLACES; do
  for f in manifest.json stats.json lot_tract.json tiles/parcels.pmtiles; do
    [ -f "$SRC/$p/$f" ] || { echo "missing $SRC/$p/$f" >&2; exit 1; }
  done
  # Optional: without them the app keeps the plain outlines and "Show testable lots" has no colours.
  for f in tiles/lots.pmtiles tiles/overview.pmtiles; do
    [ -f "$SRC/$p/$f" ] || echo "note: no $SRC/$p/$f (run app/build_lot_tiles.py --place $p)" >&2
  done
done

mkdir -p "$OUT/lots"
for p in $PLACES; do
  dst="$OUT/lots/$p"
  mkdir -p "$dst/detail" "$dst/tiles"
  cp "$SRC/$p/stats.json" "$SRC/$p/lot_tract.json" "$dst/"
done

# Tract files: the head file and its split parts, with the sale and assessment facts left out (the app and the
# assistant never read them; see PUBLIC_DROP). Same gzip level as the build (6), no timestamp. Tracts that are gone
# from the build are removed. The drive files are not changed.
python3 - "$SRC" "$OUT/lots" $PLACES <<'PY'
import gzip, json, os, shutil, sys

src, out, places = sys.argv[1], sys.argv[2], sys.argv[3:]
# Facts that stay on the drive and never go out: assessed value and the last sale (date and price).
PUBLIC_DROP = ("assessed_value", "last_sale_date", "last_sale_price")

def strip(doc):
    n = 0
    for rec in doc.get("lots") or []:
        facts = rec.get("facts")
        if isinstance(facts, dict):
            for k in PUBLIC_DROP:
                if k in facts:
                    del facts[k]
                    n += 1
    return n

for p in places:
    sdir, ddir = f"{src}/{p}/detail", f"{out}/{p}/detail"
    names = sorted(f for f in os.listdir(sdir) if f.endswith(".json.gz"))
    dropped = 0
    for name in names:
        s, d = f"{sdir}/{name}", f"{ddir}/{name}"
        if name.endswith(".geom.json.gz"):  # geometry only, no facts
            shutil.copyfile(s, d)
            continue
        with gzip.open(s, "rb") as f:
            raw = f.read()
        doc = json.loads(raw)
        n = strip(doc)
        dropped += n
        body = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode() if n else raw
        tmp = d + ".tmp"
        with open(tmp, "wb") as f:
            f.write(gzip.compress(body, compresslevel=6, mtime=0))
        os.replace(tmp, d)
    for name in set(os.listdir(ddir)) - set(names):
        os.remove(f"{ddir}/{name}")
    print(f"{p}: {len(names)} tract files, {dropped:,} sale and assessment values left out")
PY

# manifest.json and the PMTiles metadata carry absolute paths of the build machine. Keep file names only.
python3 - "$SRC" "$OUT/lots" $PLACES <<'PY'
import gzip, json, os, re, struct, sys

src, out, places = sys.argv[1], sys.argv[2], sys.argv[3:]
PATH = re.compile(r"(/Users|/home|/private|/var/folders|/Volumes)/\S*")

def scrub(v):
    if isinstance(v, dict):
        return {k: scrub(x) for k, x in v.items()}
    if isinstance(v, list):
        return [scrub(x) for x in v]
    if isinstance(v, str):
        return PATH.sub(lambda m: os.path.basename(m.group(0).rstrip("'\"")), v)
    return v

# Tile properties allowed in a published file: ids, tract, housing form, sizes and packed answers. Nothing else.
TILE_FIELDS = {"id", "tr", "s", "t", "mf", "mk", "a", "n", "d"}

def pmtiles_scrub(src_file, dst_file):
    """Rewrite a PMTiles v3 file with its JSON metadata scrubbed. Tiles and directories are copied as is."""
    with open(src_file, "rb") as f:
        data = f.read()
    h = bytearray(data[:127])
    if h[:7] != b"PMTiles" or h[7] != 3:
        raise SystemExit(f"{src_file}: not PMTiles v3")
    root_off, root_len, meta_off, meta_len, leaf_off, leaf_len, tile_off, tile_len = struct.unpack("<8Q", h[8:72])
    comp = h[97]  # internal compression: 1 none, 2 gzip
    meta = data[meta_off:meta_off + meta_len]
    meta = json.loads(gzip.decompress(meta) if comp == 2 else meta)
    meta = scrub(meta)
    layers = meta.get("vector_layers") or json.loads(meta.get("json") or "{}").get("vector_layers") or []
    extra = {f for layer in layers for f in (layer.get("fields") or {})} - TILE_FIELDS
    if extra:
        raise SystemExit(f"{src_file}: unexpected tile fields {sorted(extra)}")
    for k in ("name", "description"):
        if k in meta:
            meta[k] = os.path.basename(dst_file).split(".")[0]
    blob = json.dumps(meta, separators=(",", ":")).encode()
    blob = gzip.compress(blob, mtime=0) if comp == 2 else blob
    root = data[root_off:root_off + root_len]
    leaves = data[leaf_off:leaf_off + leaf_len]
    tiles = data[tile_off:tile_off + tile_len]
    pos = 127
    parts = []
    offs = []
    for chunk in (root, blob, leaves, tiles):
        offs.append((pos, len(chunk)))
        parts.append(chunk)
        pos += len(chunk)
    h[8:72] = struct.pack("<8Q", *[x for o in offs for x in o])
    tmp = dst_file + ".tmp"
    with open(tmp, "wb") as f:
        f.write(bytes(h))
        for c in parts:
            f.write(c)
    os.replace(tmp, dst_file)

for p in places:
    with open(f"{src}/{p}/manifest.json") as f:
        m = scrub(json.load(f))
    with open(f"{out}/{p}/manifest.json", "w") as f:
        json.dump(m, f, indent=1)
        f.write("\n")
    for name in ("parcels.pmtiles", "lots.pmtiles", "overview.pmtiles"):
        if os.path.exists(f"{src}/{p}/tiles/{name}"):
            pmtiles_scrub(f"{src}/{p}/tiles/{name}", f"{out}/{p}/tiles/{name}")
        elif os.path.exists(f"{out}/{p}/tiles/{name}"):
            os.remove(f"{out}/{p}/tiles/{name}")  # gone from the build: do not publish a stale copy
PY

# Data README, .nojekyll (serve files as is, no Jekyll build) and .gitignore for the data repository.
python3 - "$OUT" $PLACES <<'PY'
import json, os, sys
out, places = sys.argv[1], sys.argv[2:]
rows = []
for p in places:
    m = json.load(open(f"{out}/lots/{p}/manifest.json"))
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(f"{out}/lots/{p}") for f in fs)
    rules = ", ".join(sorted(set(v for v in (m.get("rule_files_verified_on") or {}).values() if v)))
    inputs = ", ".join(f"{k} {v.get('modified')}" for k, v in (m.get("inputs") or {}).items())
    rows.append(f"| {p.title()} | `{m['data_version']}` | {m.get('built_at', '')[:10]} | {m.get('counts', {}).get('lots', 0):,} | {m.get('counts', {}).get('tracts', 0)} | {inputs} | {rules} | {size / 1e6:.0f} MB |")
table = "\n".join(rows)
readme = f"""# Backyard Homes PA: lot data

Lot records and parcel tiles for the Testing mode of Backyard Homes PA. The app reads these files over the web.
Nothing here runs. This repository only serves files through GitHub Pages.

Not legal advice. Not a zoning determination. Not a survey. Parcel lines come from public records and are not
survey lines. Check every answer with the city before you build.

## What is here

| Place | Data version | Built | Lots | Tracts | Inputs (date) | Rules checked on | Size |
|---|---|---|---|---|---|---|---|
{table}

```
lots/<place>/manifest.json            data version, build date, counts
lots/<place>/stats.json               city-wide shares per scenario
lots/<place>/lot_tract.json           lot id to census tract
lots/<place>/detail/<GEOID>.json.gz   lot records of one census tract (gzip JSON)
lots/<place>/detail/<GEOID>.geom.json.gz   geometry of a large tract, split out
lots/<place>/tiles/parcels.pmtiles    parcel outlines, read by byte range
lots/<place>/tiles/lots.pmtiles       the same outlines with each lot's answer per scenario and unit type
lots/<place>/tiles/overview.pmtiles   grid squares where there are lots, for the zoomed-out map
```

The `.json.gz` files are served as plain gzip bytes. The app decompresses them in the browser.

Each record holds the lot outline, the address, buildings, land cover, zoning, the rules per scenario, the fit
result and a few public facts about the house (year built, living area, stories, ZIP code). No owner names. No
mailing addresses. No assessed values and no sale dates or prices: those stay out of the published files.

## Sources

- Philadelphia: City of Philadelphia layers on OpenDataPhilly and the city ArcGIS services (parcels, OPA, footprints,
  zoning, overlays, historic, flood, steep slope, streets). Philadelphia Land Cover 2018 (University of Vermont with
  the City of Philadelphia). OpenStreetMap service roads.
- Pittsburgh: Allegheny County layers via PASDA (parcels, roof outlines, street centerlines). City of Pittsburgh
  ArcGIS Online layers (zoning, overlays, historic, steep slope, landslide prone). Allegheny County property
  assessments (WPRDC). Microsoft Global ML Building Footprints. High resolution land cover for Pittsburgh watersheds
  2019 (University of Vermont).
- Allentown: City of Allentown GIS services (parcels with land use, tax parcel use code, units and ZIP, Zone
  Allentown zoning per parcel, zoning overlays, historic districts, building outlines, street centerlines with
  cartway widths). Microsoft Global ML Building Footprints for outlines the city layer misses. USGS 3DEP 1 m DEM.
- All places: US Census TIGER 2020 tracts. HUD Small Area Fair Market Rents. FEMA National Flood Hazard Layer.
- Rules: city zoning codes and state bills, each cited with its link and the date it was checked.

## Licence notes

These notes repeat what the providers state. They are not legal advice.

- Some city and county layers have no stated licence. The Allegheny County layers on PASDA state no licence and say
  "informational purposes only". The City of Pittsburgh layers state no licence (WPRDC lists "License not
  specified"). The City of Philadelphia License says free public use and keeps all rights, but does not say whether
  copies may be republished. The City of Allentown layers state no licence (copyright text "City GIS").
  Republishing these derived files may need the provider's permission. Ask the provider.
- Microsoft building footprints and OpenStreetMap are under the ODbL. The Pittsburgh and Allentown building outlines mix
  county or city and Microsoft outlines, and the Philadelphia alleys use OpenStreetMap. Data derived from them is shared under the ODbL:
  © Microsoft, © OpenStreetMap contributors.
- Allegheny County property assessments are CC0. Owner and mailing columns were dropped at download.
- Census, FEMA and other federal data are US government works.
- The full table is in `docs/LICENSES.md` of the app repository.

## Updating

Rebuilt from the lot build with `tools/publish_lots.sh` in the app repository. See `docs/HOSTING.md` there.
"""
open(f"{out}/README.md", "w").write(readme)
open(f"{out}/.nojekyll", "w").close()
open(f"{out}/.gitignore", "w").write(".DS_Store\n._*\n*.tmp\n")
PY

# Checks: sizes, no file over 50 MB (GitHub warns at 50 MB), no local paths, no owner fields.
python3 - "$OUT" <<'PY'
import os, sys
out = sys.argv[1]
total = 0
big = []
for d, _, fs in os.walk(out):
    if "/.git" in d:
        continue
    for f in fs:
        s = os.path.getsize(os.path.join(d, f))
        total += s
        if s > 50e6:
            big.append((f, s))
for p in sorted(os.listdir(f"{out}/lots")):
    s = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(f"{out}/lots/{p}") for f in fs)
    n = sum(len(fs) for _, _, fs in os.walk(f"{out}/lots/{p}"))
    print(f"{p}: {n} files, {s / 1e6:.1f} MB")
print(f"total: {total / 1e6:.1f} MB (GitHub Pages limit 1 GB)")
if big:
    sys.exit(f"files over 50 MB: {big}")
if total > 1e9:
    sys.exit("bundle over 1 GB")
# No sale or assessment facts in any published tract file.
import gzip
for d, _, fs in os.walk(f"{out}/lots"):
    for f in fs:
        if f.endswith(".json.gz") and not f.endswith(".geom.json.gz"):
            with gzip.open(os.path.join(d, f), "rb") as g:
                body = g.read()
            if b'"assessed_value"' in body or b'"last_sale_' in body:
                sys.exit(f"sale or assessment facts left in {f}")
print("no sale or assessment facts in the tract files")
PY
if grep -rlE '/Users/|/var/folders/' "$OUT/lots" --include='*.json' >/dev/null; then echo "local paths left in json files" >&2; exit 1; fi
if LC_ALL=C grep -rlaE '/Users/|/var/folders/' "$OUT/lots"/*/tiles >/dev/null; then echo "local paths left in the PMTiles metadata" >&2; exit 1; fi
echo "bundle ready in $OUT (nothing uploaded)"
