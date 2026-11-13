# Machine-read zoning layer: design

Date: 2026-11-11, tier B added 2026-11-12. Status: the quote search (tier B, below) is in the assistant. The machine drafts are not: no status, path or district from this pipeline reaches the product. Code: `pipeline/corpus/`. Data and outputs: `<data root>/corpus/`.

Not legal advice. Not a zoning determination.

## The idea in one line

Keep the hand-checked rule files as they are. Add a second, clearly weaker layer: the town's own ordinance text, searchable, with a machine draft that quotes it. Fall back to the statewide baseline when neither exists.

## Three tiers, kept apart

| Tier | What it is | How the assistant may use it | Label shown |
|---|---|---|---|
| A. Hand-checked rule file | `shared/rules/pa_*.json` (36 towns: 21 verified, 15 drafted) and the two city files, read and checked against the code | State values, cite section, link and check date | "Checked rule file, verified on <date>" |
| B. Public zoning text | Ordinance text fetched from the town or county site, split into sections | Quote passages word for word with section, pages, link and fetch date. No verdict | "Unverified text search" |
| C. Statewide baseline | `shared/rules/pa_statewide.json` | MPC paths, building code, sewage, bills | "Statewide baseline, not this town's code" |

Order: A wins. B is used for a place with no A file, or for a detail the A file lacks, kept apart and labelled. C is given beside B.

Rules for tier B answers (in the system prompt and the tool result):
- Quote word for word in quotation marks, with section, link and date fetched. Say it is unverified text and to confirm with the town.
- Never turn quotes into a verdict: no allowed / not allowed / by right, no approval path, no district list, unless a quoted sentence says it, attributed to the quote.
- No match: "Not found in the text searched", and only when the full text is on file. With partial text the answer says the text on file is incomplete.
- OCR text is quoted as returned, reading errors included, and said to come from a scan.
- The machine drafts (status, path, districts, "not addressed") are never served. The pilot showed them wrong for 2 of 5 towns, one a false "not addressed".

## Pilot results

<!-- source: ~/musa-drive/corpus/RESULTS.md and ~/musa-drive/corpus/RESULTS_check.md (2026-11-11) -->

**Set.** 31 places with a public copy of the ordinance were tried. 28 were fetched (3 refused by robots.txt, 1 link gone). 146 files, 141 documents extracted. 54 documents are scans with no text layer, and 7 places have only scans. About a quarter of public copies need OCR. 24 places had usable text: 6,367 chunks.

**Retrieval.** Hit = the section cited in the hand-checked file is in the top k. 44 questions on 5 towns.

| System | Top 5 | Top 10 |
|---|---|---|
| BM25 only | 70% | 80% |
| bge-small vectors | 77% | 86% |
| bge-small hybrid | 80% | 89% |
| e5-base vectors | 84% | 93% |
| e5-base hybrid | 84% | 93% |

On the verified towns only (37 questions, 4 towns) e5 hybrid finds the section in the top 10 for 92%. The fallback path (usually an MPC reading, not a sentence in the code) is found for 33%. One question moves a rate by 2 to 25 points, so these are small samples.

**Extraction.** Claude Haiku 5.5 drafts a summary with quotes, three runs on six scored towns:

| Field | Result |
|---|---|
| ADU status, raw | 4 of 6 |
| ADU status, with the consistency rule | 5 of 6 in two runs, 4 of 6 in one |
| Approval path | 4 of 6 |
| Fallback path | 0 of 4 |
| Districts | mean Jaccard 0.2 to 0.35, exact in 1 of 5 |
| Size caps | 8 of 9 in every run |
| Owner occupancy | 4 of 5 |
| Family-only flag | 1 of 5 |
| Conditions found | 22 of 31 |
| Quotes found verbatim in the cited text | 74 of 75 |

On verified towns only (5 towns): status raw 3 of 5, path 4 of 5, family flag 0 of 4, conditions 15 of 23.

**Drafts read by hand.** Five drafts for towns with no hand-checked file were read against the text. 2 were right as shown, 1 partly right (a rule true in four districts read as town-wide) and 2 wrong. One of the wrong ones said "no ADU text found" for a town whose code defines an accessory dwelling and permits it in its district tables. The quote check passed because the quote was real.

**Data problems found.** One place's link led to a county home page, so its draft said "not addressed" from a menu page. Two places share their county's ordinance and had no text. The code was fixed and the text rebuilt. The drafts for those three places were not redone.

**What this means.** Retrieval works well enough to point a reader to the right section. The machine draft is not reliable enough to state a town's rule: it misses conditions, mixes up district lists held in tables, cannot give the fallback path, and can call a town silent when it is not. That is why it stays out of the product, and why tier B answers would quote text rather than state conclusions.

**Cost.** About $0.004 to $0.005 and 7 to 9 s per town for the draft. $0.49 spent in the pilot.

## Tier B in the product (2026-11-12)

**Build.** `python -m pipeline.corpus.tierb build` writes `<data root>/corpus/tierb/`: `manifest.json` (one row per place: name, county, GEOID, text file, own site or county ordinance, links, date fetched, document date, `complete` with reasons when not, OCR flag, rule file status, how many PA towns share the name) and `text/<id>.json.gz` (documents, then passages as `[doc, section, heading, first page, last page, text]`). No drafts in either. `publish <dir>` copies them. `eval` runs the retrieval check below. No network, no model.

**Places.** 66 places from 29 texts. 26 places have their own text, 8 of them read wholly or partly by OCR from scans (Robesonia, Boggs, Beaver, Middle Paxton, Ridgway, Wilkes-Barre, parts of Mont Alto and Whitehall). 40 places are covered by a county ordinance already fetched: Luzerne (19, list from the county zoning page), Lycoming (19, Zoning Partnership list), Warren (2). The county lists are in `corpus/sources/county_coverage.csv`. 61 places have the full text on file. 5 do not: South Middleton, Mont Alto, Manheim, Whitehall (separate article files), Abington (2017 base text, 16 later amendments not included; `corpus/sources/tierb_overrides.csv`). 7 places also have a rule file.

Every own-site and county source in `availability.csv` (39 rows) was already in the pilot, so no new source could be added from it and nothing was fetched. The rest of the 60-place extension came from mapping county ordinances to the places their county page lists. OCR: tesseract through ocrmypdf, 53 scanned documents, 1,311 pages, about 20 minutes of CPU. Quotes from OCR text are verbatim of the OCR, not of the scan.

**Size.** 15.9 MB of text, 4.3 MB gzipped (median 138 kB, largest 0.28 MB per file). A county ordinance is stored once.

**Search: lexical, no vectors.** BM25 in the browser or Node over one place's passages, with a plural stem and query expansion for ADU words ("ADU" also searches accessory, apartment, in-law, granny, carriage, cottage, secondary) and size, parking, height and owner words at half weight. On the pilot retrieval questions (37, verified towns, cited section in the top k):

| Search | Top 5 | Top 10 |
|---|---|---|
| BM25 as in the pilot | 78% | 81% |
| + plural stem | 84% | 86% |
| + query expansion (shipped) | 84% | 89% |
| e5-base hybrid (pilot, needs a model) | 84% | 92% |

The expansion was tuned on the same questions, so 89% is optimistic. Vectors would need the embedding model in the browser, or a server function that embeds the query; the API route runs no tools. One question of difference does not justify either.

A passage counts as a match when it has most of the question's words, the rarest one included. For an ADU question it must also name an ADU (`ADU_PHRASES`: accessory dwelling, accessory apartment, dwelling for a relative, conversion apartment, separate residential dwelling unit and others), so "accessory" and "dwelling" scattered through a definitions page do not count. No match gives no passages and the not-found wording. Passages longer than 1,400 characters are cut to a contiguous excerpt (always an exact substring) around the ADU name or the query words.

**Tools** (`app/src/agent/zoningText.ts`, in `agent/schema.ts` TOOLS, run by `app/src/agent/executors.ts`):
- `search_zoning_text(place, county?, query, k?)`: `{tier: "B", label, place, query, source: {kind, document_date, fetched_on, full_text_on_file, incomplete_because?, ocr?}, found, results: [{quote, section, heading, pages, url, fetched_on, ocr?, words_matched}], how_to_use, next_step}`, plus `rule_file_first` for a town with a rule file. A shared name with no county (13 Penn townships) returns `ambiguous` and asks for the county.
- `list_text_places(county?)`: the places, completeness, dates and rule file status.
- `get_rule_text` adds `text_search` when a town has no rule file but has text.

**Where the files are read.** Browser: `VITE_ZONING_TEXT_URL`, else the lot data URL with `lots/` replaced by `zoning_text/`, else `/data/zoning_text/`. Node (tests, eval): `ZONING_TEXT_DIR`, default `~/musa-drive/corpus/tierb`. The publishable copy is `~/musa-drive/host/zoning_text/` (4.2 MB), next to `host/lots/`: it goes to the same Pages repository with the lot data (docs/HOSTING.md step 4), so with `VITE_LOT_DATA_URL` set no new setting is needed. The API route (`api/agent.ts`) only passes the tool definitions to the model; tools run in the browser.

**Eval.** `agent/eval/questions_tierb.json`, 10 questions (category `tier_b`), read with the generated set. Checks: every quoted span of 4 words or more is in a passage or tool result of the run; verdict and absence patterns outside quotes; not-found wording only with full text; county ordinance named; shared name asks for the county; a verified town answered from its rule file; a town with no text quotes nothing. Claude Haiku 5.5, last three runs after the fixes: 10, 7 and 10 of 10 (27 of 30). Made-up citations 0. One quote not in the text in 30 answers: the model fixed OCR errors inside a quote. Other misses: "doesn't mention" for a no-match, and asking for the county of a unique name. About $0.02 a run.

## Eval questions planned in the pilot (agent/eval)

For towns in tier B only, and for the tier A towns that also have own-site text (used as the check):
1. "Can I build an ADU in <town>?" Must call `search_zoning_text`, quote a section, show the machine-read label and the zoning officer line. Fail if it states allowed or not allowed without a quote.
2. "What is the size limit for an ADU in <town>?" Number must appear in a quoted span. Fail on a number with no quote.
3. A town whose summary says `not_addressed` (absence). Must say "not found in the text searched", not "prohibited".
4. A tier A town that also has tier B text. Must answer from tier A and not mix in tier B values.
5. A town with no text at all. Must fall back to the statewide baseline and say so.
6. A district question for a district-only rule (York SE in six districts, not CBD). Must not call the rule town-wide.
7. Family-only towns (Manheim, Abington). The answer must keep the relative condition.
8. A stale source (Wilkes-Barre 2012, Penn Hills 2020). Must give the document date.

## Training a custom model: what it would and would not add

- There are 38 hand-checked rule files (36 towns and the two cities). That is the test set, not a training set. Training on them would leave nothing honest to measure with.
- A fine-tuned extractor would learn the format of 38 answers, not the law of 2,500 towns. The hard parts are retrieval (finding the use table row and the conditions), reading flattened tables, and keeping conditions and scope. None of these get better from 38 examples.
- Retrieval plus a small general model plus a quote check is cheaper to run, easy to audit (every claim has a span), and does not need labels. The verified towns stay a clean test set.
- What could help later: a small reranker or embedding fine-tune trained on (question, cited section) pairs from the rule files, if the pilot grows to a few hundred checked pairs. Gain would be in retrieval only, and only a few points.

## What the local GPU is for

- Embeddings. bge-small runs at about 120 chunks/s on MPS against 20 on CPU. e5-base about 43 against 6. All public Pennsylvania text (about 200k chunks) embeds in about 30 minutes with bge-small or about 80 minutes with e5-base on a laptop GPU (Apple MPS).
- Re-embedding after a change, and trying other embedding models or a reranker.
- Possibly OCR for scanned PDFs (a quarter of public copies), if a local OCR model is added later.
- It is not needed for extraction. The extraction call is a hosted model and costs under half a cent per town.
