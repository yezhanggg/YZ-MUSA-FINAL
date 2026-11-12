# Money assumptions

Every number the cost, rent and pay-off model uses lives in one file: `shared/assumptions.json`.
The Python pipeline (`pipeline/money.py`) and the browser (`app/src/lib/money.ts`) both read it.
Nothing else holds a cost, rate or tax number.

This page lists each one: what it is, its value and range, where it comes from and how sure we are.

## How sure we are

| Label | Meaning |
|---|---|
| measured | We computed it from an official file (for example the 2026 average of weekly mortgage rates). |
| published | An official or public statistic, fee schedule or law. |
| vendor | A builder, lender, insurer or cost website estimate. No official source exists. |
| assumption | Owner judgement. Change it freely. |

Pennsylvania has no official ADU cost data. All build costs are vendor numbers, so each has a low, mid and high value.
Pages with no date carry the day they were read (2026-11-10).

## What the model does

1. **Cost.** Build cost = size x cost per sq ft for the type x size curve x area cost factor x finish level.
   Then add site work, utility runs, septic if the lot has no public sewer, contingency (on build, site and utilities),
   design (on build), permit fees, water and sewer tap fees, survey, and the Philadelphia construction tax.
   Each item has a low, mid and high value. Low adds up all the low values. High adds up all the high values.
2. **Rent.** Size gives a bedroom count (studio under 450 sq ft, 1 bedroom under 750, else 2).
   Rent is the HUD Small Area Fair Market Rent for the ZIP and that bedroom count.
   Where a ZIP has no SAFMR, use ACS tract median rent by bedrooms.
3. **Running costs.** Vacancy, a management fee if the owner does not manage it, a maintenance reserve, insurance, the rental license and the added property tax.
4. **Tax.** The assessor adds the build cost (mid) to the value. Philadelphia taxes it at 1.3998 percent, with the 10-year abatement that falls 10 points a year.
   Pittsburgh taxes it at 2012 base-year value (about 49 percent of today's value) times county, city and school millage.
   Elsewhere it uses the state median effective rate.
5. **Loan.** A preset gives loan to cost, rate and term. The rest is paid in cash.
6. **Results.** Monthly cash flow, break-even rent, payback years, yield on cost, cash-on-cash return, debt coverage,
   an added value estimate, and a verdict.

## Verdict rules

With a loan:

- **pays**: monthly cash flow at the mid cost is 0 or more, and net operating income is at least 1.20 times the loan payment.
- **close**: it does not pay, but it pays at the low cost, or the monthly gap is within 10 percent of rent.
- **does_not_pay**: everything else.

Paid in cash:

- **pays**: yield on cost (yearly net operating income over total cost) is at least the 30-year mortgage rate.
- **close**: the yield is within 10 percent of that rate, or the low-cost yield clears it.
- **does_not_pay**: everything else.

The test uses the average property tax of the first 10 years, so the Philadelphia abatement counts but does not decide the answer alone.
Change `verdict.rules` to use year 1 or full tax.

## What it gives today (600 sq ft, mid cost, all-in per sq ft)

| Type | Philadelphia | Pittsburgh | Rest of PA |
|---|---|---|---|
| Detached new | 338 (259 to 469) | 314 (240 to 439) | 318 (239 to 448) |
| Attached | 302 (233 to 410) | 279 (216 to 381) | 279 (216 to 381) |
| Over garage | 357 (271 to 484) | 330 (251 to 450) | 334 (250 to 459) |
| Garage conversion | 236 (160 to 353) | 217 (147 to 328) | 221 (146 to 337) |
| Internal conversion | 194 (128 to 292) | 178 (117 to 269) | 178 (117 to 269) |

Smaller units cost more per sq ft. A detached unit in Philadelphia is about 462 per sq ft at 300 sq ft and 272 at 1,000 sq ft (mid).
Rest of PA adds a mid 3,000 sewer tap fee for new services, which is why it is a little above Pittsburgh.

## How to change a number

1. Edit the item in `shared/assumptions.json`. Keep `low <= mid <= high`. Update `sources` (title, url, date) and `confidence`.
   An owner choice is `"confidence": "assumption"` with the source `Owner setting`.
2. Change `version` at the top to today's date.
3. Rebuild the parity cases: `python -m pipeline.money fixture`.
4. Run the checks:
   - `python -m pytest tests/test_money.py -q`
   - `npx vitest run app/src/lib/money.test.ts`
5. Look at one result: `python -m pipeline.money demo --zip 19143 --size 600 --type detached_new --place philadelphia`.

The browser imports the JSON at build time, so a site rebuild picks up the change.

To refresh rents: `python -m pipeline.market download --force`. HUD updates SAFMRs once a year (fiscal year starts 1 October).
Then change `fiscal_year` in `rents.source`.

To refresh the mortgage rate: read the last row of the Freddie Mac PMMS history file and update `financing.pmms30`, `financing.pmms15` and the date.

## Known gaps

- No Pennsylvania ADU cost survey. Build costs are vendor numbers calibrated to land near 300 to 360 per sq ft all-in for a small detached unit in Philadelphia.
- The size curve, finish levels, site work and utility costs for types other than detached are judgement.
- Philadelphia: whether an ADU gets the new-construction abatement (phased) or the improvement abatement (flat 100 percent, owner-occupied only) is decided by the Office of Property Assessment. The 1 percent construction tax rate was not verified.
- Pittsburgh: Chapter 267 rental abatement terms were not verified, so no abatement is applied. Zoning review fee not found.
- Rest of PA: permit fees use the Pittsburgh schedule as a stand-in. Tap-in fees vary by sewer authority.
- Insurance is a whole landlord policy. Adding an ADU to the house policy may cost less.
- Added value is an income estimate. A backyard unit does not sell on its own.

## Every assumption

### Construction cost

| Key | What | Value (mid) | Range low to high | Unit | Confidence | Source and date |
|---|---|---|---|---|---|---|
| `cost.hard_psf.detached_new` | Build cost per sq ft, new detached backyard home | 220 | 190 to 260 | USD per sq ft | vendor | [Block Renovation: ADU construction costs (500 sq ft about 350 per sq ft all-in, 800 sq ft about 275, national 150 to 400)](https://www.blockrenovation.com/guides/a-deep-dive-into-adu-construction-costs-what-the-per-square-foot-numbers-dont-tell-you) 2026-06-19<br>[MassCEC ADU budgeting guide (250 to 500 per sq ft placeholder, hard cost about 85 percent of budget)](https://goclean.masscec.com/adu/budgeting/) 2026-11-10<br>[Cost to Build House: ADU cost in Pennsylvania (600 sq ft: Philadelphia 313 to 363, Pittsburgh 297 per sq ft all-in)](https://www.costtobuildhouse.com/adu-cost-in-pennsylvania) 2026-11-10<br>[NAHB Cost of Constructing a Home 2024 (about 162 per sq ft construction cost for a large house, a floor)](https://eyeonhousing.org/2025/01/cost-of-constructing-a-home-in-2024/) 2025-01<br>[Terner Center California ADU survey (median 250 per sq ft, 2020 prices)](https://ternercenter.berkeley.edu/blog/cci-adu-survey) 2021-04-22 |
| `cost.hard_psf.attached` | Build cost per sq ft, attached addition | 210 | 180 to 250 | USD per sq ft | vendor | [MassCEC ADU budgeting guide (2 bedroom attached 235k to 360k vs detached 250k to 450k)](https://goclean.masscec.com/adu/budgeting/) 2026-11-10<br>[Maxable: what does an ADU cost (attached about 200k, minimal savings vs detached)](https://maxablespace.com/what-does-an-adu-cost-in-2024/) 2024 |
| `cost.hard_psf.over_garage` | Build cost per sq ft, unit over a garage | 250 | 210 to 300 | USD per sq ft | vendor | [Maxable: what does an ADU cost (above garage about 300k, most expensive type)](https://maxablespace.com/what-does-an-adu-cost-in-2024/) 2024<br>[Angi: adding a room above a garage (80k to 210k)](https://www.angi.com/articles/adding-room-above-garage.htm) 2026-11-10 |
| `cost.hard_psf.garage_conversion` | Build cost per sq ft, garage conversion | 160 | 120 to 210 | USD per sq ft | vendor | [Angi: cost to convert a garage to an ADU (58k to 173k)](https://www.angi.com/articles/cost-to-convert-garage-to-adu.htm) 2025<br>[MassCEC ADU budgeting guide (garage conversions not much less than new construction)](https://goclean.masscec.com/adu/budgeting/) 2026-11-10 |
| `cost.hard_psf.internal` | Build cost per sq ft, conversion inside the house (basement, attic, floor) | 140 | 100 to 190 | USD per sq ft | vendor | [Angi: how much does an ADU cost (basement or attic 60k to 150k)](https://www.angi.com/articles/how-much-do-adu-costs.htm) 2026-11-10<br>[MassCEC ADU budgeting guide (interior conversion 120k to 270k)](https://goclean.masscec.com/adu/budgeting/) 2026-11-10 |
| `cost.size_curve` | Size effect on build cost per sq ft | 300:1.25 450:1.1 600:1.0 800:0.9 1000:0.84 1200:0.8 |  | multiplier on cost.hard_psf, by unit size in sq ft | assumption | [Block Renovation: 500 sq ft about 350 per sq ft vs 800 sq ft about 275](https://www.blockrenovation.com/guides/a-deep-dive-into-adu-construction-costs-what-the-per-square-foot-numbers-dont-tell-you) 2026-06-19 |
| `cost.area_cost_factor` | Area cost factor by place | philadelphia 1.17, pittsburgh 1.09, rest_of_pa 1.09, reference 1.09 |  | index, 96-city average = 1.00 | published | [DoD UFS 3-701-01 Area Cost Factors 2026, Table 4-1 CONUS](https://legacy.wbdg.org/FFC/DOD/UFC/ufs_3_701_01_2026_Data_Tables.xlsx) 2026-02-02 |
| `cost.quality` | Finish level | basic 0.9, standard 1.0, premium 1.25 |  | multiplier on build cost | assumption | Owner setting 2026-11-10 |
| `cost.site_work` | Site work (grading, foundation prep, access, tree removal) | detached_new 10000, attached 7000, over_garage 5000, garage_conversion 3000, internal 1000 | detached_new 5000 to 20000, attached 3000 to 15000, over_garage 2000 to 10000, garage_conversion 1000 to 8000, internal 0 to 3000 | USD per project | vendor | [Block Renovation: ADU construction costs](https://www.blockrenovation.com/guides/a-deep-dive-into-adu-construction-costs-what-the-per-square-foot-numbers-dont-tell-you) 2026-06-19 |
| `cost.utility_connection` | Utility runs (water, sewer lateral, electric service or panel upgrade) | detached_new 15000, over_garage 10000, garage_conversion 10000, attached 6000, internal 4000 | detached_new 8000 to 30000, over_garage 5000 to 20000, garage_conversion 5000 to 20000, attached 3000 to 12000, internal 2000 to 8000 | USD per project | vendor | [Block Renovation: ADU construction costs](https://www.blockrenovation.com/guides/a-deep-dive-into-adu-construction-costs-what-the-per-square-foot-numbers-dont-tell-you) 2026-06-19<br>[HomeAdvisor: sewer line cost](https://www.homeadvisor.com/cost/plumbing/repair-a-sewer-main/) 2025<br>[HomeAdvisor: electrical panel upgrade cost](https://www.homeadvisor.com/cost/electrical/upgrade-an-electrical-panel/) 2025 |
| `cost.septic_upgrade` | Septic upgrade where the lot is not on public sewer | 18000 | 7000 to 40000 | USD per project | vendor | [Septic and Well: septic installation cost in Pennsylvania](https://septicandwell.com/articles/septic-installation-cost-pennsylvania) 2026-11-10 |
| `cost.contingency` | Contingency | 0.1 | 0.05 to 0.15 | share of build, site and utility cost | vendor | [Case Design: contingency budget for residential construction (5 to 15 percent)](https://www.casedesign.com/inspiration/do-i-need-a-contingency-budget-for-my-residential-construction-project/) 2026-11-10 |
| `cost.survey_types` | ADU types that need a boundary survey | detached_new, attached |  | list | assumption | Owner setting 2026-11-10 |
| `cost.new_service_types` | ADU types that need a new water and sewer service | detached_new, over_garage, garage_conversion |  | list | assumption | Owner setting 2026-11-10 |

### Soft costs

| Key | What | Value (mid) | Range low to high | Unit | Confidence | Source and date |
|---|---|---|---|---|---|---|
| `soft.design` | Design and engineering | 0.1 | 0.08 to 0.15 | share of build cost | vendor | [HomeAdvisor: architect fees (8 to 15 percent of construction)](https://homeadvisor.com/cost/architects-and-engineers/hire-an-architect) 2025<br>[MassCEC ADU budgeting guide (design 10 to 20 percent)](https://goclean.masscec.com/adu/budgeting/) 2026-11-10 |
| `soft.survey` | Boundary survey | 1200 | 700 to 2000 | USD per project | vendor | [Find Land Surveyor: land survey cost in Philadelphia County](https://findlandsurveyor.com/guides/land-survey-cost-philadelphia-county-pa) 2026-11-10 |
| `soft.permits.philadelphia` | Philadelphia permit fees | fixed 2054, per_value 0.0025, min 0, max 1000000 |  | USD fixed plus share of build cost | published | [Philadelphia L&I PG_012 summary of construction permit fees, effective 2026-10-01](https://www.phila.gov/media/20260729134349/PG_012_INF_Summary-of-construction-permit-fees-Eff-1.1.2025-Rev-7.2026.pdf) 2026-07-29<br>[Philadelphia PZ_008 summary of zoning permit fees](https://www.phila.gov/media/20260720085858/PZ_008_INF_Summary-of-zoning-permit-fees-Rev-7.2026.pdf) 2026-07-20 |
| `soft.permits.pittsburgh` | Pittsburgh permit fees | fixed 0, per_value 0.006, min 130, max 8000 |  | USD fixed plus share of build cost | published | [City of Pittsburgh PLI 2026 fee schedule, effective 2026-01-01](https://www.pittsburghpa.gov/files/assets/city/v/1/pli/documents/fees/2026-fee-schedule-final-2.pdf) 2026-01-01 |
| `soft.permits.rest_of_pa` | Permit fees elsewhere in Pennsylvania | fixed 0, per_value 0.006, min 130, max 8000 |  | USD fixed plus share of build cost | assumption | [City of Pittsburgh PLI 2026 fee schedule (stand-in)](https://www.pittsburghpa.gov/files/assets/city/v/1/pli/documents/fees/2026-fee-schedule-final-2.pdf) 2026-01-01 |
| `soft.tap_fees` | Water and sewer connection and tap fees | philadelphia 605, pittsburgh 610, rest_of_pa 3000 | philadelphia 605 to 605, pittsburgh 610 to 610, rest_of_pa 0 to 6000 | USD per project | published | [Philadelphia Water Department FY26 and FY27 connection charges](https://www.phila.gov/media/20250812093312/FY-26-and-FY-27-Final-Charges.pdf) 2025-08-12<br>[Pittsburgh Water permits](https://www.pgh2o.com/developers-contractors-vendors/permits) 2026-11-10 |
| `soft.construction_tax.philadelphia` | Philadelphia tax on residential construction | 0.01 | 0 to 0.01 | share of build cost | assumption | [Ballard Spahr: Philadelphia zoning, land use and construction update](https://www.ballardspahr.com/Insights/Alerts-and-Articles/2020/12/Philadelphia-Zoning-Land-Use-and-Construction-COVID-19-Update) 2020-12-04 |

### Rent

| Key | What | Value (mid) | Range low to high | Unit | Confidence | Source and date |
|---|---|---|---|---|---|---|
| `rents.source` | Market rent source | dataset HUD Small Area Fair Market Rents, fiscal_year 2026, file processed/market/safmr_pa.parquet, builder python -m pipeline.market download |  | pointer | published | [HUD PDR Small Area Fair Market Rents, open feature service](https://services.arcgis.com/VTyQ9soqVukalItT/ArcGIS/rest/services/HUD_PDR_Small_Area_Fair_Market_Rents/FeatureServer/1) 2025-10-01<br>[HUD Small Area FMRs](https://www.huduser.gov/portal/datasets/fmr/smallarea/index.html) 2025-10-01 |
| `rents.fallback` | Rent fallback where a ZIP has no SAFMR | dataset ACS 2020-24 table B25031 median gross rent by bedrooms, tract, fields rent_b0 to rent_b3 |  | pointer | published | [Census ACS table B25031](https://data.census.gov/table/ACSDT5Y2024.B25031) 2025-12 |
| `rents.bedroom_cuts_sqft` | Unit size to bedroom count | studio_max 450, one_bed_max 750 |  | sq ft | assumption | Owner setting 2026-11-10 |
| `rents.rent_factor` | ADU rent as a share of the SAFMR | 1 |  | multiplier | assumption | Owner setting 2026-11-10 |

### Financing

| Key | What | Value (mid) | Range low to high | Unit | Confidence | Source and date |
|---|---|---|---|---|---|---|
| `financing.pmms30` | 30-year fixed mortgage rate, latest week | 0.0718 |  | annual rate | published | [Freddie Mac PMMS history](https://www.freddiemac.com/pmms/docs/PMMS_history.csv) 2026-11-05 |
| `financing.pmms30_2026_avg` | 30-year fixed mortgage rate, 2026 average | 0.0653 |  | annual rate | measured | [Freddie Mac PMMS history](https://www.freddiemac.com/pmms/docs/PMMS_history.csv) 2026-11-05 |
| `financing.pmms15` | 15-year fixed mortgage rate, latest week | 0.0657 |  | annual rate | published | [Freddie Mac PMMS history](https://www.freddiemac.com/pmms/docs/PMMS_history.csv) 2026-11-05 |
| `financing.heloc_rate` | Home equity line of credit rate, national average | 0.0749 |  | annual rate | vendor | [Bankrate HELOC rates](https://www.bankrate.com/home-equity/heloc-rates/) 2026-11-04 |
| `financing.fha_mip` | FHA annual mortgage insurance premium | 0.0055 |  | share of loan per year | published | [HUD Mortgagee Letter 2023-05](https://www.hud.gov/sites/dfiles/OCHCO/documents/2023-05hsgml.pdf) 2023-02-22 |
| `financing.presets` | Ways to pay | cash: ltc 0.0, spread 0.0, years 0, heloc: ltc 1.0, spread 0.0, years 20, construction_to_perm: ltc 0.8, spread 0.005, years 30, fha_203k: ltc 0.965, spread 0.0, years 30, all_borrowed: ltc 1.0, spread 0.0, years 30 |  | preset | assumption | Owner setting 2026-11-10 |
| `financing.default_preset` | Default way to pay | preset construction_to_perm |  | preset name | assumption | Owner setting 2026-11-10 |

### Operating costs

| Key | What | Value (mid) | Range low to high | Unit | Confidence | Source and date |
|---|---|---|---|---|---|---|
| `operating.vacancy` | Rental vacancy | philadelphia 0.083, pittsburgh 0.059, rest_of_pa 0.074 |  | share of gross rent | published | [Census HVS rental vacancy by metro, 2026](https://www.census.gov/housing/hvs/data/rates/tab4_msa_26_rvr.xlsx) 2026-10-28<br>[Census HVS rental vacancy by state, 2026](https://www.census.gov/housing/hvs/data/rates/tab1_state05_2026_rvr.xlsx) 2026-10-28 |
| `operating.management` | Property management fee | 0.08 |  | share of collected rent | vendor | [Baselane: how much do property managers charge](https://www.baselane.com/resources/how-much-do-property-managers-charge) 2026-11-07 |
| `operating.maintenance` | Maintenance and repairs reserve | 0.1 |  | share of collected rent | vendor | [DoorLoop: property maintenance budget](https://www.doorloop.com/hub/property-maintenance) 2026-11-10 |
| `operating.insurance` | Landlord insurance | 1180 |  | USD per year | vendor | [Steadily: Pennsylvania landlord insurance](https://www.steadily.com/states/pennsylvania) 2026-11-10 |
| `operating.rental_license` | Rental license or registration | philadelphia 69, pittsburgh 35.5, rest_of_pa 0 |  | USD per year | published | [Philadelphia: get a rental license](https://www.phila.gov/services/permits-violations-licenses/get-a-license/business-licenses/rental-and-property/get-a-rental-license/) 2026-11-10<br>[City of Pittsburgh PLI 2026 fee schedule](https://www.pittsburghpa.gov/files/assets/city/v/1/pli/documents/fees/2026-fee-schedule-final-2.pdf) 2026-01-01 |

### Property tax

| Key | What | Value (mid) | Range low to high | Unit | Confidence | Source and date |
|---|---|---|---|---|---|---|
| `tax.assessed_share_of_build_cost` | Added market value the assessor puts on the unit | 1 |  | share of build cost (mid hard cost, before soft costs) | assumption | Owner setting 2026-11-10 |
| `tax.philadelphia.rate` | Philadelphia real estate tax rate | 0.013998 |  | share of assessed market value per year | published | [City of Philadelphia: lower your property tax bill ahead of 2027 valuations](https://www.phila.gov/2026-07-20-learn-how-to-lower-your-property-tax-bill-ahead-of-the-2027-valuations/) 2026-07-20 |
| `tax.philadelphia.abatement` | Philadelphia 10-year abatement for new residential construction | years 1 to 10: 1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1 |  | share of added value not taxed, by year | published | [OPA application: abatement for new residential construction](https://www.phila.gov/media/20250826121006/opa-application-abatement-new-construction-residential-2025.pdf) 2025-08-26<br>[Ballard Spahr on Bill 200366 (phase-down from 2022)](https://www.ballardspahr.com/Insights/Alerts-and-Articles/2020/12/Philadelphia-Zoning-Land-Use-and-Construction-COVID-19-Update) 2020-12-04<br>[OPA application: abatement for residential improvements](https://www.phila.gov/media/20250826121004/opa-application-abatement-rehab-residential-2025.pdf) 2025-08-26 |
| `tax.pittsburgh.millage` | Pittsburgh property tax millage, 2026 | county 6.43, city 9.67, school 10.457 |  | mills (USD per 1,000 of assessed value) | published | [Allegheny County municipal millage profile, Pittsburgh](https://apps.alleghenycounty.us/website/MuniPgh.asp) 2026-11-10<br>[Allegheny Institute: Pittsburgh 2026 budget](https://www.alleghenyinstitute.org/pittsburghs-2026-budget-ends-its-tumultuous-journey/) 2025-12 |
| `tax.pittsburgh.assessment_ratio` | Allegheny County assessed value as a share of market value | 0.493 |  | ratio | published | [Allegheny Institute: Allegheny County's CLR continues its decline](https://www.alleghenyinstitute.org/allegheny-countys-clr-continues-its-decline/) 2026-05-28<br>[WPRDC Allegheny County property assessment user guide (2012 base year)](https://wiki.wprdc.org/wiki/Allegheny_County_Property_Assessment_Data_User_Guide) 2026-11-10 |
| `tax.pittsburgh.reassessment` | When Allegheny County adds a new unit to the tax roll | trigger building or occupancy permit, timing interim assessment for the year the unit is finished |  | rule | published | [53 Pa.C.S. 8817](https://www.palegis.us/statutes/consolidated/view-statute?txtType=HTM&ttl=53&div=0&chapter=88&section=17) 2022-07-07<br>[Allegheny County: building permits and assessments](https://www.alleghenycounty.us/Services/Property-Assessments-and-Real-Estate/Property-Assessments/Building-Permits) 2026-11-10<br>[Allegheny County: interim valuation](https://www.alleghenycounty.us/Services/Property-Assessments-and-Real-Estate/Property-Assessments/Interim-Valuation) 2026-11-10 |
| `tax.pittsburgh.abatement` | Pittsburgh abatement for a new rental unit | none |  | share of added value not taxed, by year | assumption | [City of Pittsburgh real estate tax abatement application (Chapters 265 and 267)](https://www.pittsburghpa.gov/files/assets/city/v/1/finance/documents/real-estate-forms/265-267-re-tax-abatement-application.pdf) 2026-08-17 |
| `tax.rest_of_pa.effective_rate` | Pennsylvania median effective property tax rate | 0.0126 |  | share of market value per year | published | [Tax Foundation: property taxes by state and county, 2026](https://taxfoundation.org/data/all/state/property-taxes-by-state-county/) 2026-03-16 |

### Added value

| Key | What | Value (mid) | Range low to high | Unit | Confidence | Source and date |
|---|---|---|---|---|---|---|
| `value.cap_rate` | Capitalization rate for the added value estimate | 0.0614 | 0.0525 to 0.0677 | annual net income over value | vendor | [Matthews: Philadelphia multifamily market report Q3 2026](https://www.matthews.com/insights/philadelphia-pa-multifamily-market-report-q3-2026) 2026-11-10<br>[Apartment Loan Store: Philadelphia cap rates](https://apartmentloanstore.com/philadelphia/pennsylvania/cap-loan-rates) 2026-07-20 |

### Verdict

| Key | What | Value (mid) | Range low to high | Unit | Confidence | Source and date |
|---|---|---|---|---|---|---|
| `verdict.rules` | Verdict rules | tax_basis avg10, dscr_pays 1.2, close_band 0.1, cash_hurdle_key financing.pmms30 |  | rule | assumption | Owner setting 2026-11-10 |

### Display

| Key | What | Value (mid) | Range low to high | Unit | Confidence | Source and date |
|---|---|---|---|---|---|---|
| `pro_forma.schedule_years` | Years shown in the tax schedule | 12 |  | years | assumption | Owner setting 2026-11-10 |

## Tract analysis (MUSA 5500)

The statewide tract screen in `pipeline/tract/` reads these keys. It is simpler than the lot-level model above: one cost per sq ft, one share of rent for running costs, all borrowed. It uses `financing.pmms30_2026_avg` (main run) and `financing.pmms30` (sensitivity).

| Key | What | Value (mid) | Range low to high | Unit | Confidence | Source and date |
|---|---|---|---|---|---|---|
| `tract.growth.cpi_u` | CPI-U yearly average for 2024 dollars | 2014: 236.736, 2019: 255.657, 2024: 313.689 |  | index | published | [BLS CUUR0000SA0](https://data.bls.gov/timeseries/CUUR0000SA0) 2025-01-15 |
| `tract.growth.min_start` | Smallest start for a growth rate | pop 200, units 100, jobs 50, rent 1 |  | count | assumption | Owner setting 2026-11-10 |
| `tract.payoff.size_sqft` | Unit size | 600 |  | sq ft | assumption | Owner setting 2026-11-10 |
| `tract.payoff.hard_psf` | Build cost per sq ft | 250 | 175 to 300 | USD per sq ft | assumption | [Terner Center](https://ternercenter.berkeley.edu/blog/cci-adu-survey) 2021-04-22 |
| `tract.payoff.soft_share` | Soft costs | 0.15 |  | share of build cost | assumption | Owner setting 2026-11-10 |
| `tract.payoff.loan_years` | Loan length | 30 |  | years | assumption | Owner setting 2026-11-10 |
| `tract.payoff.opex_share` | Running costs | 0.30 |  | share of rent | assumption | Owner setting 2026-11-10 |
| `tract.payoff.close_band` | Band for "maybe" | 0.10 |  | share of payment | assumption | Owner setting 2026-11-10 |
| `tract.payoff.rent_basis` | Rent column | `rent_b1` (1 bedroom, same as the tool) |  | pointer | assumption | [Census B25031](https://data.census.gov/table/ACSDT5Y2024.B25031) 2025-12 |
| `tract.forecast.years` | Forecast years | 5 (2027 to 2031) |  | years | assumption | Owner setting 2026-11-10 |
| `tract.forecast.permits_per_100k` | ADU permits per 100,000 people a year | 53.5 | 26 to 81 | rate | assumption | Proposal, credited to Pew, page not recorded |
| `tract.forecast.pays_weight` | Share of the rate by payoff | yes 1.0, maybe 0.5, no 0.2 |  | multiplier | assumption | Owner setting 2026-11-10 |
| `tract.forecast.rule_factor` | Share of the rate by town rule | limited 0.05 | limited 0.02 to 0.10 | multiplier | assumption | Owner setting 2026-11-10 |
| `tract.forecast.unlisted_rule` | Rule for uncoded towns | limited |  | rule | assumption | Owner setting 2026-11-10 |
| `tract.forecast.lots_index_cap` | Cap on the lots index | 2 |  | multiple | assumption | Owner setting 2026-11-10 |
| `tract.forecast.legal_class_factor` | Share of the rate by town legal class (rule files) | by right 1.0, discretionary / family only / conversion only / unknown 0.05, none 0.005 | 0.02 to 0.10, none 0 to 0.01 | multiplier | assumption | Owner setting 2026-11-11 |
