# Coverage and limits

Moved from the README on 2026-11-22. Figures are as of the dates in each note. Last full update 2026-11-28 (lot data 13).

## Three scenarios on every lot

| Scenario | Philadelphia | Pittsburgh | Other lot places |
|---|---|---|---|
| Today's law | Zoning Code 14-604(11) | Ordinance 31-2026, signed Oct 29, 2026 | The town's own zoning code |
| Local reform | Bill 250042 (in committee) | Same as today | Same as today |
| State reform | HB 2186 (passed the House, in Senate committee) | HB 2186 | HB 2186 |

Bills are not law. The state session ends Nov 30, 2026. A bill not enacted by then dies.

## What works today

As of 2026-11-28 (lot data 13).

<!-- source: ~/musa-drive/lots/<place>/manifest.json counts and stats.json all.paths and by_town, read 2026-11-28 (lot data 13). Data versions: philadelphia-20261126-331f84072a, pittsburgh-20261126-d747c67f1d, allentown-20261127-9be163090f, montgomery_county-20261128-a60d9ea1ce, delaware_county-20261128-c88715b1cd, lancaster_county-20261128-b62011a32a, bucks_county-20261127-669c83737a, chester_county-20261127-61e3e7c924, york_county-20261127-170b781fee, dauphin_county-20261128-d423841a40, northampton_county-20261128-11547385f4, erie_county-20261128-89125fe9da, cumberland_county-20261127-0e017dd0c9, centre_county-20261127-ad60715d09. Built, not in the app: berks_county-20261127-e6dec1911f -->

| Lot place | Towns | Lots with a record | Any legal ADU path today | A detached unit is legal and fits today | Same under HB 2186 |
|---|---|---|---|---|---|
| Philadelphia | Philadelphia | 459,998 | 1.2% | 0% | 26.0% |
| Pittsburgh | Pittsburgh | 92,081 | 100% | 65.4% (needs an Administrator's Exception) | 69.7% |
| Montgomery County | 24 | 142,072 | 47.2% | 7.0% | 63.0% |
| Delaware County | 19 | 104,738 | 26.9% | 4.5% | 63.1% |
| Lancaster County | 11 | 62,735 | 43.0% | 20.4% | 80.1% |
| Bucks County | 8 | 48,764 | 76.0% | 5.0% | 58.9% |
| Chester County | 14 | 42,306 | 66.8% | 16.4% | 72.3% |
| York County | 7 | 40,295 | 67.5% | 13.7% | 72.7% |
| Dauphin County | Harrisburg, Lower Paxton, Swatara | 35,475 | 92.8% | 57.2% | 67.1% |
| Northampton County | 5 | 33,695 | 66.8% | 33.3% | 68.3% |
| Allentown | Allentown | 29,158 | 88.3% | 21.5% | 71.3% |
| Erie County | Erie city | 26,150 | 99.6% | 90.8% | 90.1% |
| Cumberland County | Upper Allen, Lower Allen, Camp Hill | 10,259 | 94.6% | 53.0% | 79.9% |
| Centre County | College Township, State College | 6,827 | 69.6% | 24.3% | 81.8% |
| All 14 | 100 towns | 1,134,553 | | | |

The towns of each county place and their shares are in [METHODS.md](METHODS.md) section 7. Berks County (Amity township, 3,746 lots) is built but not in the app or the bundle: the County of Berks data agreement bars passing the data on "in its original format" and asks for a credit line. The owner has not decided yet.

By town, a detached unit is legal and fits today on 96.6% of East Nottingham lots, 91.1% in Elizabethtown and 90.8% in Erie. It is 0% in 59 of the 97 county-place towns: in 57 the code gives a new detached unit no legal path today, and in Bristol township and Whitpain it is allowed but fits on no lot.

Erie's share under HB 2186 (90.1%) is a little below today's (90.8%). Under the bill the tool takes 200 sq ft as the smallest unit, the most a town may ask (6305(1)), against its 144 sq ft default today. On 279 Erie lots the building coverage cap or the yard leaves room for a unit under 200 sq ft, so it fits today but not under the bill. 87 lots where no unit is allowed today gain one. The bill's 200 sq ft building cover allowance (6305(4)) is not applied in the fit, so the coverage cap still limits these lots.

- **Fit test.** A vector geometry test on the lot outline, the buildings and the streets, with the setbacks from the rule file. It finds the largest unit that fits and where. Since Nov 27 a unit drawn for information where no detached form is allowed keeps the 10 ft planning separation from the house; before, it was drawn against the house wall. All town places were rebuilt with the fix. The shares did not move.
- **Land cover as context.** The lots of lot data 12 (Philadelphia, Pittsburgh, Allentown and the first 9 county-place towns) carry tree canopy, open ground, hard surface and impervious share. Philadelphia uses the city's 2018 land cover raster. The other places use the project's model on 2022 aerial images: Pittsburgh the three-model ensemble from 2026-11-18, the rest the U-Net `r34_c5_s0`. They also give the trees and paving inside the suggested spot (the four town places since Nov 15). Accuracy differs by place: Pittsburgh is checked on 128 lots, Centre County lies in a test county of the model (about 0.70 test mIoU), and Allentown, Chester and Montgomery are not validated. Each record says which. 36 Centre County lots have no cover. The lots added on Nov 27 and 28 (the 8 new places and the new towns of Chester, Montgomery and Centre) have an empty cover block. Land cover does not decide the fit.
- **Ground slope.** Every lot has a slope block from the USGS 1 m lidar DEM.
- **Steep slope rules.** Pittsburgh (915.02 grading and the LS-O, UM-O and SS-O overlays, 906.04, 906.05, 906.08) and Philadelphia (14-704(2)) steep slope rules are in the rule files as cited rows. They are shown as conditions or questions for the city, never as a bar. The Ask rule text and the Pittsburgh and Philadelphia lot records carry them (refreshed Nov 14). They change sentences, not the shares above.
- **Address search.** Ask can find any address in the lot places, on the map or not, from a static address index in the lot data bundle. Delaware County lots have no address (no assessor data). It works live only after the bundle is published.
- **Money.** Itemised costs from one assumptions file (`shared/assumptions.json`). Rent from HUD Small Area Fair Market Rents by ZIP.
- **Town rules.** As of Nov 27, 2026, 225 places have a rule file: Philadelphia, Pittsburgh and 223 towns. 201 are verified by an independent second reading (the two cities and 199 towns). Verified means every finding of the second reading is resolved; where the code itself does not settle a point, the file keeps it as a disputed or secondary reading to ask the zoning officer. 24 towns stay first readings (drafted): the review left an open point, written down for each. Lower Providence went back to drafted on Nov 27: it adopted a new zoning ordinance and map on Nov 5, 2026, and its file reads the old chapter. 93 of the 223 town codes have no ADU text at all. A statewide baseline covers every other town.
- **An answer for every Pennsylvania place.** Each of the 2,572 county subdivisions gets one best answer and says how good the evidence is: verified rule file, drafted rule file, a dated agency report (or no zoning on record with the state), a search of the town's public zoning text, or the statewide baseline. 203 places answer from a verified file, 47.4% of Pennsylvanians (Nov 27). See [docs/PLACES.md](docs/PLACES.md).

<!-- source: shared/rules/towns_index.json status (2026-11-27) and the town files adu.status. app/public/data/pa_places_meta.json -->

## What does not work yet

As of 2026-11-28.

- Lot-level answers exist only in the 14 lot places. Elsewhere the boundaries show each area's ADU rule.
- The lot data bundle, in the packed format (pack1), is 1,713.5 MB in all (Nov 28). It is over the 1 GB GitHub Pages limit, so it is split over two data repositories (docs/HOSTING.md): 867.1 MB for Philadelphia, Pittsburgh, Allentown, Chester, Centre, Erie, Dauphin and Cumberland counties with the zoning text (862.8 MB of lots and 4.4 MB of `zoning_text/`), and 846.4 MB for Montgomery, Delaware, Lancaster, Northampton, Bucks and York counties. It is not yet pushed. Deploy the app before pushing it.
- **Separation where the rule file gives no number.** Where a detached unit is allowed but the rule file sets no separation from the house, the separation reads "not checked" and the drawn unit can touch the house. This touches Harrisburg (7,096 lots), Bethlehem (6,573), Allentown (5,200), York city and county (4,528), Delaware County (2,150), Warminster (942) and Lancaster city. Whether to apply the 10 ft planning separation there is an open decision for the owner.
- **Data gaps in the new places.** Delaware County has no assessor data (the county's service needs a token): no addresses, unit counts or living area, and a twin or row in a multifamily area is assumed to be one unit. House heights come from the city data in Philadelphia and Pittsburgh, the DVRPC 2015 lidar in Montgomery, Chester, Bucks and Delaware and the county's 3D buildings in Centre. Erie, Dauphin, Lancaster, York, Cumberland and Northampton have none, and Allentown only on Microsoft outlines, so height tests read "not checked" there. Montgomery, Chester, Dauphin, Lancaster, Bucks, Delaware and Allentown have no living area, so share-of-house caps are not checked there. The lots added on Nov 27 and 28 have no land cover block yet.
- Some towns of the lot counties are left out whole: East Donegal (Lancaster, conditional use or a secondary reading), Penn township (York, its 2025 zoning map is not public), Lower Providence (Montgomery, new ordinance, file back to drafted), Millcreek and Harborcreek (Erie, no layer of their current zoning), Forks and Hanover (Northampton), Carlisle (Cumberland), Susquehanna (Dauphin), and towns with no ADU text in Bucks (7) and York (3). Delaware and Montgomery keep their towns with no ADU text: their lots read a use variance today and show what HB 2186 would allow. Each place's `stats.json` lists who is left out and why.
- The fit answers have not been checked by hand. A 250-lot labeling sample is drawn (125 per city). On Nov 26 it was labeled by a vision model reading the aerial photo and lot outline, following the hand-label protocol (`~/musa-drive/validation/labels_claude/`). These are not hand labels and not a true accuracy. Against lot data 12, a 600 sq ft unit agrees on 84.2% of Pittsburgh lots (76.6 to 89.6) and 84.7% of Philadelphia lots (77.3 to 90.0); 400 sq ft on 70.8% and 80.5%. About 70% of the gaps are definitions (the label asks for a box anywhere in the open yard; the product applies setbacks), not errors. Two errors it found were fixed: a front on the wrong street (now the street in the address) and a unit counted as fitting when the only room was the front yard.
- Land cover: the best model, picked on validation, is an ensemble of DeepLabV3+, EfficientNet-B2 and a 512 px ResNet-34 (Nov 18). It scores test mIoU 0.7093 and building IoU 0.6554. The targets were 0.72 and 0.65, so the mIoU target is missed. In Pittsburgh it passes the bar for replacing the lot model (0.7147 against 0.7136), so the Pittsburgh lots use the three-model ensemble from 2026-11-18. In Philadelphia the model cannot read trees from the spring 2022 photos, so the city raster is used there. Allentown, Chester and Montgomery have no labels to check the model against. In the four town places the trees and paving inside the suggested spot come from the same model, so they carry the same accuracy as the lot shares.
- The outbuilding detector scores garage AP50 0.469 (final) with classes set by the size rule, against a target of 0.50. The labels are unchecked first-pass labels, so this is not a true accuracy.
- 24 rule files are first readings. Towns whose code is only a PDF or sits behind a login were skipped. Some 2026 ordinances could not be read: Patton adopted a rental ordinance on Oct 28, 2026 that its minutes say permits one ADU per owner-occupied house, and its text was not readable online, so Patton stays drafted. Lower Providence's new ordinance of Nov 5, 2026 is not read yet. Whitpain's Ord. 4-269 (Sep 15, 2026, family-only ADU) was read from the signed copy. Several verified files rest on codes with 2026 amendments that were not read. Each of these carries a caution.
- Montgomery County house heights come from the DVRPC 2015 lidar landbase since Nov 26 (Microsoft heights read about 6 ft low against it and against Centre County's own 3D buildings). A house built after 2015 has no height, and a house under 10 ft tall reads "not checked". The highest-hit height can pick up overhanging trees.
- Pittsburgh's undermined-area overlay (UM-O) comes from the city's Undermined Areas layer (since Nov 26). A lot is flagged when 25% of it is inside (32,865 lots, 35.7%). The layer is coarse; the zoning officer decides.
- A machine-read zoning pilot for more towns exists (`docs/CORPUS.md`). It is not in the product.

