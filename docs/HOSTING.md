# Hosting the lot data

Testing mode reads per-tract lot files and parcel tiles that are too big for this repository. They are served from a
second public GitHub repository through GitHub Pages. It costs nothing and needs no new account.

This page has the decision, the steps to publish, how to update the data, and how to roll back.

## What the app reads

Checked by running the production build and logging every request in Chromium (Nov 11, 2026). Under
`VITE_LOT_DATA_URL` (the "base") the app asks for:

| File | When | Size |
|---|---|---|
| `<place>/manifest.json` (both places) | First screen, for the "Lot data" line. Again by the loader on the first lot of a place | 29 KB and 78 KB |
| `<place>/tiles/lots.pmtiles` (both places) | First screen: bytes 0 to 15 (is the file there), then 0 to 16383 (header). Then one range per map tile at zoom 14 and 15. The same outlines as `parcels.pmtiles` plus each lot's answer, for "Show testable lots" | 5.1 MB and 20.6 MB files, 3 KB to 290 KB per range |
| `<place>/tiles/parcels.pmtiles` (both places) | Only when `lots.pmtiles` is missing (an older bundle): then the app draws plain outlines and the switch has no colours | 5.0 MB and 20.1 MB files |
| `<place>/tiles/overview.pmtiles` (both places) | Only after "Show testable lots" is turned on: bytes 0 to 15, the header, then one range per map tile at zoom 5 to 13 | 66 KB and 148 KB files, about 35 KB for the state map and under 10 KB for a city view |
| `<place>/detail/<GEOID>.json.gz` | The first lot of a tract (click, search or link). Later lots in the same tract need no request | up to 1.5 MB |
| `<place>/detail/<GEOID>.geom.json.gz` | With the head file, when the build split the tract (37 Pittsburgh tracts, 22 Philadelphia tracts) | up to 0.8 MB |
| `<place>/detail/<GEOID>.pN.json.gz` | When a head file names extra chunks in `more`. None in the Nov 11 build, kept for later builds | |
| `<place>/stats.json` | When a lot opens, for the city-wide story | 48 KB |
| `<place>/lot_tract.json` | Only when the Ask assistant opens a lot by id that is not in memory | 3.4 MB and 14 MB (gzipped on the fly to 0.3 MB and 1.3 MB) |

The app does not read `app/`, `index.parquet`, `lot_tract.parquet`, `parts/`, `qa/`, `progress.jsonl` or the
`*.before_2272.*` files. They stay on the drive.

The bundle is 115.2 MB for Pittsburgh (169 files) and 341.4 MB for Philadelphia (411 files). 456.5 MB in all
(Nov 12 rebuild, without the sale and assessment facts: it was 467.5 MB with them).

The app's own small files come with the app, not from this bundle. One of them, `data/city_tracts.json` (435 KB,
78 KB gzipped), lists the tracts of Pittsburgh and Philadelphia with their town. A searched address in Testing mode
finds its tract there, so the first lot opens without the 10 MB tract and town files.

## Decision

GitHub Pages from a separate public repository. Fallback: jsDelivr in front of the same repository, split per city.

| Option | Limits (checked Nov 11, 2026) | PMTiles by range | CORS | `.json.gz` | Owner work | What can go wrong |
|---|---|---|---|---|---|---|
| **GitHub Pages, second repo** | Site up to 1 GB. Repo ideally under 1 GB. Soft 100 GB a month bandwidth. Soft 10 builds an hour. 10 minute deploy timeout. Files over 100 MiB blocked | Yes, 206 on GET | `Access-Control-Allow-Origin: *` on files. Not on 404 pages. OPTIONS gets 405, so only simple requests work (the app sends only those) | Sent as `application/gzip`, no `Content-Encoding`. The loader unzips it | Create repo, push, turn on Pages, set one env var | Over 100 GB a month GitHub may ask to move. Repo grows by the changed files on each update. 10 minute cache after an update |
| jsDelivr from the same repo | 150 MB per repo and 20 MB per file by default. Tags cached for a year, branches 12 h. Purge by request | Yes | `*` | Raw bytes | Same repo, plus a tag | 457 MB is over the 150 MB cap, so it needs one repo per city plus a split of Philadelphia, or a request to jsDelivr. Their rules say not a general file host |
| GitHub Releases assets | 2 GiB per file, 1000 files per release | Yes | None. The download redirects to `release-assets.githubusercontent.com` with no CORS header | | | The browser cannot fetch them from the app. Ruled out |
| Inside the Vercel deployment | Hobby: 100 GB a month transfer, 45 min build, no stated cap on build output. CLI upload 100 MB on Hobby (a June 2026 changelog says CLI limits were removed, unclear for Hobby) | Yes | Same origin | Can set headers in `vercel.json` | Files must be in the git repo or fetched at build time | 457 MB in the app's git history forever. iCloud syncs the repo folder. Every deploy uploads it again |
| Vercel Blob | Hobby: 1 GB storage, 10 GB a month transfer, 2,000 advanced operations | Yes | Configurable | Raw | Enable Blob in the Vercel project | 10 GB a month is about 7,000 first lot views. Access stops for the rest of the month when a limit is passed |
| Cloudflare R2 | 10 GB storage, free egress, 1 M writes and 10 M reads a month | Yes | Configurable | Raw | New Cloudflare account and billing setup | Needs a new account. Ruled out |

Why Pages:

- It is the only option with no new account, no size split and CORS on by default.
- Range requests work, so the parcel tiles load piece by piece (about 20 to 120 KB per map view).
- The first lot of a tract costs about 1 MB. At 100 GB a month that is about 100,000 first lot views.
- The data lives apart from the app. An app deploy does not upload 457 MB, and the app repo stays small.

Fallback if Pages stops serving (bandwidth or policy): push the same bundle as two repos (one per city, Philadelphia
split in two) and use jsDelivr URLs pinned to a tag. Or enable Vercel Blob in the project. Only `VITE_LOT_DATA_URL`
changes. The app reads one base URL for both cities, so a split needs the same base path on one host.

Sources:

- GitHub Pages limits: https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
- Large files on GitHub: https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github
- `.nojekyll`: https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site
- jsDelivr limits and caching: https://github.com/jsdelivr/jsdelivr (README)
- GitHub Releases: https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- Vercel limits: https://vercel.com/docs/limits and https://vercel.com/docs/limits/fair-use-guidelines
- Vercel Blob: https://vercel.com/docs/vercel-blob/usage-and-pricing
- Cloudflare R2: https://developers.cloudflare.com/r2/pricing/
- Headers seen on github.io sites with curl (Nov 11, 2026): `206`, `access-control-allow-origin: *`,
  `cache-control: max-age=600`, `.gz` as `application/gzip` with no `content-encoding`, `.json` gzipped on the fly,
  404 and OPTIONS with no CORS header.

## Tested locally

A local server sent the same headers as GitHub Pages, from another origin than the app. The production build pointed
at it with `VITE_LOT_DATA_URL`. Chromium, cold cache, one lot per city.

| Flow | Lot data requests | Lot data bytes | Time to the lot result: no throttle, Fast 4G, Slow 4G |
|---|---|---|---|
| Pittsburgh, open by link (tract with split geometry) | 16 | 0.98 MB | 6.6 s, 7.0 s, 16.1 s |
| Pittsburgh, search "5704 Pocusset St" | 10 | 1.01 MB | 1.5 s, 11.9 s, 56.1 s |
| Pittsburgh, click the next parcel | 0 | 0 | under 0.1 s (tract in memory) |
| Philadelphia, open by link | 27 | 2.04 MB | 3.1 s, 5.2 s, 15.7 s |
| Philadelphia, search "1805 S 2nd St" | 8 | 1.26 MB | 1.6 s, 12.0 s, 60.7 s |
| Philadelphia, click the next parcel | 0 | 0 | under 0.1 s (tract in memory) |
| Wrong `VITE_LOT_DATA_URL` | manifests fail | | The panel says "The lot data could not be loaded. Check your connection and try again." in 5 s. No hang |

Fast 4G is 9 Mbit/s with 60 ms latency. Slow 4G is 1.6 Mbit/s with 150 ms. Most of the search time above was the
app's own tract and town files (about 10 MB, loaded on the first search) and the basemap, not the lot data. The tract
file itself took 0.5 to 1.6 s on Fast 4G and 3 to 11 s on Slow 4G.

Since Nov 12 a search in Testing mode no longer loads the tract and town files. It finds the tract in
`data/city_tracts.json` (78 KB gzipped) and opens the lot file of that tract. The 10 MB files load only when no lot
record contains the point (for the tract report, and in case the point sits in the tract next door), outside the two
cities, or in Projecting mode. Measured in the e2e test `address search in testing mode` (dev server, Chromium,
throttled to 1.6 Mbit/s and 150 ms after the page loads, Photon answered locally), from picking
"1818 E Moyamensing" to the verdict: 69.2 s the old way (3 area files), 20.2 s now (no area file).

The search also asks Photon's house layer (`layer=house`) in parallel when the text starts with a house number, and
lists a house with that number on that street first. Photon's house layer also returns houses that only look alike
(5459 Spring St for 5459 Beacon St), so a house on another street is dropped. With no matching house the list is the
usual one (streets and places), and the address match inside the tract still finds the lot by its address. A tract the manifest does not list now says "We have no lot data for this place yet."
instead of a network error, because Pages sends no CORS header on a 404.

## Publish (owner, once)

You need: GitHub Desktop signed in as `yezhanggg`, the external drive plugged in, and about 30 minutes.

1. **Build the bundle.** In Terminal:
   ```bash
   cd ~/Documents/YZ-MUSA-FINAL
   tools/publish_lots.sh
   ```
   It ends with `bundle ready in /Users/<you>/musa-drive/host (nothing uploaded)` and prints the size per city.
2. **Create the data repository.** In the browser, open https://github.com/new.
   - Repository name: `backyard-homes-lots`.
   - Public.
   - Leave "Add a README", ".gitignore" and "license" off. The bundle has its own README.
   - Click "Create repository".
3. **Clone it with GitHub Desktop.** File > Clone repository > GitHub.com tab > `yezhanggg/backyard-homes-lots`.
   Local path: `/Users/<you>/musa-drive/backyard-homes-lots` (on the external drive). Do not clone into Documents:
   iCloud would sync 457 MB. Click "Clone".
4. **Copy the bundle in.** In Terminal (the copy includes the hidden `.nojekyll` and `.gitignore`):
   ```bash
   rsync -a --delete --exclude .git ~/musa-drive/host/ ~/musa-drive/backyard-homes-lots/
   ```
5. **Commit and push.** In GitHub Desktop the Changes tab lists about 585 files. Summary:
   `Lot data 2026-11-11`. Click "Commit to main", then "Push origin". The upload is about 460 MB.
6. **Turn on Pages.** On github.com open the data repo > Settings > Pages. Source: "Deploy from a branch".
   Branch: `main`, folder `/ (root)`. Save. Wait until the page shows "Your site is live at
   https://yezhanggg.github.io/backyard-homes-lots/" (one to three minutes, see the Actions tab).
7. **Check one file.** Open
   https://yezhanggg.github.io/backyard-homes-lots/lots/pittsburgh/manifest.json in the browser. It shows JSON with
   `"data_version": "pittsburgh-20261111-bdeb5697ae"`.
8. **Point the app at it.** On vercel.com open the app project > Settings > Environment Variables. Add:
   - Key `VITE_LOT_DATA_URL`, value `https://yezhanggg.github.io/backyard-homes-lots/lots/` (with the last
     slash). Environments: Production and Preview.
   - Key `ANTHROPIC_API_KEY`, your Anthropic key, Production and Preview, if it is not there yet. The Ask box needs it.
     It stays on the server and is never put in the bundle.
9. **Redeploy.** Vercel > Deployments > the latest production deployment > "..." menu > Redeploy. `VITE_` values are
   read at build time, so a redeploy is needed after any change to them.
10. **Check the site.** Open the tool, pick ADU Testing, and open
    `/#/?view=test&lot=42003-0086N00208000000&tract=42003141300`. The panel says a backyard cottage fits. Then
    `/#/?view=test&lot=42101-011000034&tract=42101002702` shows a Philadelphia rowhouse with no path today.

## Update the data later

1. Rebuild the lots on the drive (`pipeline/build_lots.py`). Each build writes a new `data_version` in `manifest.json`.
   Then rebuild the map tiles, one city at a time: `app/build_lot_tiles.py --place <place>` (writes
   `tiles/lots.pmtiles` and `tiles/overview.pmtiles`, needs tippecanoe).
2. Run `tools/publish_lots.sh`, then the `rsync` line from step 4.
3. In GitHub Desktop, commit with the data version in the summary (for example `Lot data pittsburgh-20261201-...`)
   and push. Pages updates in a few minutes. No Vercel redeploy is needed when the URL stays the same.

Cache: Pages sends `max-age=600`. For up to 10 minutes a browser can mix old and new files. The loader catches this:
a tract part from another build shows "The lot data is being updated. Reload the page in a minute." A tract older
than the manifest still loads (it is marked stale).

Size: each push adds only the files that changed, but a full rebuild changes most of them. After about two full
updates the repo passes the 1 GB that GitHub recommends. Then start fresh: delete the data repo (Settings > Danger
Zone), create it again with the same name, and publish once more. The URL stays the same.

## Roll back

- Data: in GitHub Desktop open History, right-click the last data commit, choose "Revert changes in commit", then
  "Push origin". Pages serves the old files within a few minutes, plus up to 10 minutes of browser cache.
- App: if the site breaks after the env var change, open Vercel > Deployments, pick the last good deployment and
  choose "Promote to Production" (or "Instant Rollback"). To go back to no lot data, delete `VITE_LOT_DATA_URL` and
  redeploy. Testing mode then says the lot data could not be loaded. Projecting mode does not use these files.

## Licences and privacy

- The data repo README repeats the licence notes from `docs/LICENSES.md`. Some city and county layers state no
  licence (Allegheny County on PASDA, City of Pittsburgh ArcGIS layers). The City of Philadelphia License allows free
  public use but does not say if copies may be republished. Publishing the derived files is a judgement call. Ask the
  providers if the tool goes beyond a class project.
- Microsoft building outlines and OpenStreetMap are ODbL. The derived records are shared under the ODbL with credit.
- No owner names or mailing addresses are in the files. Each record has the address, year built, living area,
  stories and ZIP code of the parcel, from public assessment records.
- No assessed values and no sale dates or prices. The lot build on the drive keeps `facts.assessed_value`,
  `facts.last_sale_date` and `facts.last_sale_price`, but nothing in the app or the assistant reads them, so
  `tools/publish_lots.sh` leaves them out of every published tract file (the drive files are not changed) and
  checks the bundle for them. The assistant's `get_lot_facts` answers "not in the public data" for them, from a
  published or a local record alike. `tests/test_publish_lots.py` runs the script on a small fake build.
- `tools/publish_lots.sh` removes the build machine's folder paths from `manifest.json` and from the PMTiles metadata.
- The tile files carry only lot ids, the tract, the housing form, today's largest cottage size and the packed answers
  (`id`, `tr`, `s`, `t`, `mf`, `mk`, `a`; the overview `a`, `n`, `d`). `tools/publish_lots.sh` stops if a tile file
  lists any other property.
- Not legal advice. Not a survey.
