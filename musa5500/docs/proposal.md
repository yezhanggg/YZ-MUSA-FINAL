---
title: "MUSA 5500 Proposal"
---

Sent by email to the course staff, Nov 5, 2026. The text below is the proposal as sent.

What changed since: the housing growth model is gradient boosting, picked from four models under county-held-out cross-validation (the proposal named a random forest). The payoff test uses a 1-bedroom rent. The lot tool shows three rule scenarios on each lot in Philadelphia and Pittsburgh: today's law, local reform and state reform. See [Results](results.md).

**Topic:** Housing Demand and ADU Potential Across Pennsylvania

**Team:** one student

**Background:** A state bill, HB 2186, would allow a backyard home (ADU) on every home lot in Pennsylvania. But legal doesn't mean built. Philadelphia has allowed ADUs in parts of the city since 2012, and only about 10 have been built legally. ADUs get built where demand is growing and the rent covers the cost.

**Research question:** Where are people and jobs growing, did that change after 2019, where would an ADU pay off, and how many could be built by 2031?

**Study area:** All of Pennsylvania, from 2010 to the latest year, by census tract.

**Goal:** Planners can see where housing demand is growing and how many new homes ADUs could add in their town or county. Builders and homeowners can search an address and see whether an ADU would pay off there.

**Data sources:** Census population estimates and ACS through the Census API. IRS migration, LEHD jobs, the Building Permits Survey, and Freddie Mac mortgage rates through scripted downloads. NLCD land cover rasters, OpenStreetMap, and lot counts from my 6950 project (or a simpler estimate from lot sizes if those aren't ready).

**Methods:**

1. Join all the data to census tracts.
2. Compare growth before and after 2019.
3. Group places by trend with K-means.
4. Measure developed land from the rasters and job access with OSMnx.
5. Test where ADU rent covers the cost to build.
6. Use a random forest to predict where housing grew from 2010 to 2020, then use it to estimate how many ADUs could be built by 2031, with a low and high range.

**Expected outcomes:** A multi-page Quarto site on GitHub Pages with interactive maps, a time slider from 2010 to today, and a toggle between current rules and HB 2186. A short written report and a presentation.

**Course requirements:** API collection, 3+ data sources, spatial joins, OSMnx, K-means clustering, raster analysis, and a scikit-learn model, plus interactive visualizations.

**How it splits from 6950:** My 6950 project uses AI on aerial images to find which lots have room for an ADU. This project covers demand and payoff. The two will share one dashboard, but each has its own code and documentation pages.
