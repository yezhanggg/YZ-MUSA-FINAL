---
title: "MUSA 6950 Proposal"
---

Submitted Nov 3, 2026.

**Room for a Backyard Home: Measuring ADU Capacity Across Pennsylvania with GeoAI**

Team: Ye Zhang

**Background and Research Question:** Pennsylvania needs more housing, but most towns make it hard to build an accessory dwelling unit (ADU), a small second home on a lot, like a backyard cottage. A state bill, HB 2186, would allow one on every home lot. But no one knows how many lots actually have room for one. Backyards also hold a lot of trees, so building there has an environmental cost.

**Research question:** How many home lots in Pennsylvania have room for a backyard ADU, how many could fit one without cutting down trees, and can AI on aerial images measure this better than building outlines alone?

**Study Area:** The whole state of Pennsylvania (all 67 counties), with results for every census tract, town, and county.

**Goal:** Builders and homeowners can type in an address and see if an ADU fits and where. Planners can see how many new homes ADUs could add in their town or county.

**Data Sources:** Aerial images of the whole state (NAIP, 2022), building outlines (Microsoft), and property lines from counties that share them. For training, I will use land cover maps from Philadelphia and the Chesapeake Bay area, plus a few hundred lots I label by hand.

**Proposed AI Methods:** First, a U-Net sorts each image into buildings, trees, and open ground, since building outlines alone do not show trees or pavement. I will compare it with a simpler Random Forest model. Second, YOLO finds garages and sheds the outlines miss. Third, a simple rule checks if each lot has an open spot big enough for an ADU, with and without cutting trees. I will test accuracy on lots I labeled myself, then run it statewide.

**Expected Outcomes:** A model that maps buildings, trees, and open ground; a map of how many lots can fit an ADU, with and without cutting trees; a check of how accurate the AI is; and a dashboard with an address search and a town and county view. I will share the results in a written report and a presentation.

**About the Larger Project:** This is half of a bigger ADU project. This half asks whether an ADU fits. My MUSA 5500 project asks whether people need housing there and whether an ADU would pay off, using population, job, and rent trends since 2010. Together they show whether there is room for ADUs where people need housing. Both will share one dashboard, but each class will have its own code and documentation.
