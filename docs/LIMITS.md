# Coverage and limits

Moved from the README on 2026-11-22. Figures are as of the dates in each note.

## Three scenarios on every lot

| Scenario | Philadelphia | Pittsburgh | Other lot places |
|---|---|---|---|
| Today's law | Zoning Code 14-604(11) | Ordinance 31-2026, signed Oct 29, 2026 | The town's own zoning code |
| Local reform | Bill 250042 (in committee) | Same as today | Same as today |
| State reform | HB 2186 (passed the House, in Senate committee) | HB 2186 | HB 2186 |

Bills are not law. The state session ends Nov 30, 2026. A bill not enacted by then dies.

## What works today

<!-- source: ~/musa-drive/lots/<place>/manifest.json counts and stats.json all.paths and by_town, read 2026-11-26 (lot data 12). Data versions: pittsburgh-20261126-d747c67f1d, philadelphia-20261126-331f84072a, allentown-20261126-dcb22d8b63, chester_county-20261126-3396fbba65, centre_county-20261126-faba91665f, montgomery_county-20261126-39cb1f34c5 -->

| Lot place | Towns | Lots with a record | Any legal ADU path today | A detached unit is legal and fits today | Same under HB 2186 |
|---|---|---|---|---|---|
| Philadelphia | Philadelphia | 459,998 | 1.2% | 0% | 26.0% |
| Pittsburgh | Pittsburgh | 92,081 | 100% | 65.4% (needs an Administrator's Exception) | 69.7% |
| Allentown | Allentown | 29,158 | 88.3% | 21.5% | 71.3% |
| Montgomery County | Lower Merion, Narberth, Upper Dublin | 26,119 | 78.3% | 25.2% | 83.9% |
| Chester County | West Chester, Phoenixville, West Vincent, Malvern, East Brandywine | 14,847 | 68.9% | 28.7% | 64.2% |
| Centre County | College Township | 3,484 | 53.8% | 47.7% | 81.0% |
| All six | 12 towns | 625,687 | | | |

By town, a detached unit is legal and fits today on 77.2% of Narberth lots, 65.0% in Upper Dublin, 43.8% in West Chester, 49.5% in Phoenixville and 12.8% in West Vincent. Lower Merion, Malvern and East Brandywine allow no new detached unit, so 0%.

- **Fit test.** A vector geometry test on the lot outline, the buildings and the streets, with the setbacks from the rule file. It finds the largest unit that fits and where.
- **Land cover as context.** Lots in all six places carry tree canopy, open ground, hard surface and impervious share. Philadelphia uses the city's 2018 land cover raster. The other five places use the project's model on 2022 aerial images: Pittsburgh the three-model ensemble from 2026-11-18, the rest the U-Net `r34_c5_s0`. They also give the trees and paving inside the suggested spot (the four town places since Nov 15). Accuracy differs by place: Pittsburgh is checked on 128 lots, Centre County lies in a test county of the model (about 0.70 test mIoU), and Allentown, Chester and Montgomery are not validated. Each record says which. 36 Centre County lots have no cover. Land cover does not decide the fit.
- **Ground slope.** Every lot has a slope block from the USGS 1 m lidar DEM.
- **Steep slope rules.** Pittsburgh (915.02 grading and the LS-O, UM-O and SS-O overlays, 906.04, 906.05, 906.08) and Philadelphia (14-704(2)) steep slope rules are in the rule files as cited rows. They are shown as conditions or questions for the city, never as a bar. The Ask rule text and the Pittsburgh and Philadelphia lot records carry them (refreshed Nov 14). They change sentences, not the shares above.
- **Address search.** Ask can find any address in the six lot places, on the map or not. It reads a static address index (3.6 MB, in the lot data bundle). It works live only after the bundle is published.
- **Money.** Itemised costs from one assumptions file (`shared/assumptions.json`). Rent from HUD Small Area Fair Market Rents by ZIP.
- **Town rules.** As of Nov 26, 2026, 223 places have a rule file: Philadelphia, Pittsburgh and 221 towns. 198 are verified by an independent second reading (the two cities and 196 towns). Verified means every finding of the second reading is resolved; where the code itself does not settle a point, the file keeps it as a disputed or secondary reading to ask the zoning officer. 25 towns stay first readings (drafted): the review left an open point, written down for each. 92 of the 221 town codes have no ADU text at all. A statewide baseline covers every other town.
- **An answer for every Pennsylvania place.** Each of the 2,572 county subdivisions gets one best answer and says how good the evidence is: verified rule file, drafted rule file, a dated agency report (or no zoning on record with the state), a search of the town's public zoning text, or the statewide baseline. See [docs/PLACES.md](docs/PLACES.md).

<!-- source: shared/rules/towns_index.json status (2026-11-16, commit 751cfaf) and the town files adu.status. app/public/data/pa_places_meta.json -->

## What does not work yet

- Lot-level answers exist only in the six lot places. Elsewhere the boundaries show each area's ADU rule.
- The lot data bundle is 714.2 MB in the packed format (pack1) since Nov 26, about 286 MB under the 1 GB GitHub Pages limit. It is built in `~/musa-drive/host_pack1` and not yet pushed to the data repository `yezhanggg/backyard-homes-lots`. Deploy the app before pushing it.
- The fit answers have not been checked by hand. A 250-lot labeling sample is drawn (125 per city). On Nov 26 it was labeled by a vision model reading the aerial photo and lot outline, following the hand-label protocol (`~/musa-drive/validation/labels_claude/`). These are not hand labels and not a true accuracy. Against lot data 12, a 600 sq ft unit agrees on 84.2% of Pittsburgh lots (76.6 to 89.6) and 84.7% of Philadelphia lots (77.3 to 90.0); 400 sq ft on 70.8% and 80.5%. About 70% of the gaps are definitions (the label asks for a box anywhere in the open yard; the product applies setbacks), not errors. Two errors it found were fixed: a front on the wrong street (now the street in the address) and a unit counted as fitting when the only room was the front yard.
- Land cover: the best model, picked on validation, is an ensemble of DeepLabV3+, EfficientNet-B2 and a 512 px ResNet-34 (Nov 18). It scores test mIoU 0.7093 and building IoU 0.6554. The targets were 0.72 and 0.65, so the mIoU target is missed. In Pittsburgh it passes the bar for replacing the lot model (0.7147 against 0.7136), so the Pittsburgh lots use the three-model ensemble from 2026-11-18. In Philadelphia the model cannot read trees from the spring 2022 photos, so the city raster is used there. Allentown, Chester and Montgomery have no labels to check the model against. In the four town places the trees and paving inside the suggested spot come from the same model, so they carry the same accuracy as the lot shares.
- The outbuilding detector scores garage AP50 0.469 (final) with classes set by the size rule, against a target of 0.50. The labels are unchecked first-pass labels, so this is not a true accuracy.
- 25 rule files are first readings. Towns whose code is only a PDF or sits behind a login were skipped. Some 2026 ordinances could not be read: Whitpain and Patton adopted new ADU ordinances in autumn 2026 that are not yet in their online codes. Several verified files rest on codes with 2026 amendments that were not read. Each of these carries a caution.
- Montgomery County house heights come from the DVRPC 2015 lidar landbase since Nov 26 (Microsoft heights read about 6 ft low against it and against Centre County's own 3D buildings). A house built after 2015 has no height, and a house under 10 ft tall reads "not checked". The highest-hit height can pick up overhanging trees.
- Pittsburgh's undermined-area overlay (UM-O) comes from the city's Undermined Areas layer (since Nov 26). A lot is flagged when 25% of it is inside (32,865 lots, 35.7%). The layer is coarse; the zoning officer decides.
- A machine-read zoning pilot for more towns exists (`docs/CORPUS.md`). It is not in the product.

