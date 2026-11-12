# Machine-read zoning layer: design

Date: 2026-11-11. Status: pilot. Nothing here is in the product: not in the app, not in the assistant, not in the lot files. Code: `pipeline/corpus/`. Data and outputs: `<data root>/corpus/`.

Not legal advice. Not a zoning determination.

## The idea in one line

Keep the hand-checked rule files as they are. Add a second, clearly weaker layer: the town's own ordinance text, searchable, with a machine draft that quotes it. Fall back to the statewide baseline when neither exists.

## Three tiers, kept apart

| Tier | What it is | How the assistant may use it | Label shown |
|---|---|---|---|
| A. Hand-checked rule file | `shared/rules/pa_*.json` (36 towns: 21 verified, 15 drafted) and the two city files, read and checked against the code | State values, cite section, link and check date. As today | "Checked rule file, verified on <date>" |
| B. Machine-read town | Ordinance text fetched from the town or county site, split into sections, plus a draft summary made by a small model, each claim tied to a quote that a program found in the text | Quote the text with section, page, link and retrieval date. Show the draft summary only under its label. Never state a conclusion the quotes do not support. Never fill a tier A field from it | "Machine-read, not verified. Read the quoted text." |
| C. Statewide baseline | `shared/rules/pa_statewide.json` | MPC paths, building code, sewage, bills. As today | "Statewide baseline, not this town's code" |

Order: A wins. B is used only for a place with no A file. C is always given beside B, because B may be stale, partial or wrong.

Rules for tier B answers:
- Every sentence about the town's rule carries a quote from `search_zoning_text` or from a summary claim whose `check` is `ok`.
- A summary field with `absence: true` (for example `not_addressed`) is said as "I did not find ADU text in the parts of the ordinance I searched", never as "ADUs are not allowed".
- Fields the model could not support were dropped. They are listed in `unsupported` and must not be stated.
- Always say the document date or retrieval date, and that a newer amendment may exist.
- Always end with: ask the zoning officer before you design or build.

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

## Tools the assistant would call

```
search_zoning_text(place, query, k=5)
  place: name, "name, county" or 10 digit GEOID
  returns: {geoid, tier: "B", label, results: [{section, heading_path, pages, url, retrieved_on, score, text}]}
  empty results when the place has no tier B text

get_machine_summary(place)
  returns: {label: "machine-read, not verified, read the quoted text", model, made_on,
            status_consistent, draft: {field: {value, support: [{quote, section, chunk_id, url,
            page_start, page_end, retrieved_on, check}], absence?}}, unsupported, quote_checks}
  or null
```

`get_rule_text` stays as it is. Its "not in my data" branch would add one line: "Machine-read text is available for this town: use search_zoning_text."

Prototype: `pipeline/corpus/search_zoning_text.mjs` (Node, BM25 only, no model, reads one JSON file per place). Not wired into the app. Neither tool exists in `agent/schema.ts`.

## Serving

- One JSON file per place: `~/musa-drive/corpus/serve/<geoid>.json` with chunks, section, pages, URL, retrieval date and the summary. Pilot: 24 places, 14 MB in all, median 0.6 MB, largest 1.2 MB. Gzip takes text like this to about a quarter.
- Statewide guess: about 900 places with public text, 25% of them scans (left out without OCR). About 700 files, about 400 MB raw, about 100 MB gzipped.
- Option 1, static: put the files in a public bucket or the site's static hosting. The browser loads one place file on demand (like the town rule files today) and runs BM25 in JS. No server. Vectors left out (the browser would need the embedding model).
- Option 2, small server function: one function holds a single file (all chunks, about 400 MB) or a SQLite FTS5 index, plus the float16 vectors (e5-base 768 dims: 1.5 kB per chunk, about 0.3 GB for 200k chunks, or bge-small 384 dims at half that). The query is embedded server side. This gives the hybrid search that scored best in the pilot.
- Start with option 1. Move to option 2 only if BM25 alone misses too much (in the pilot BM25 alone found the cited section in the top 10 for 80% of questions, hybrid 93%).
- Refresh: re-fetch monthly with the manifest (hash and Last-Modified). Re-extract and re-draft only what changed. A draft is redone when its source hash changes.

## Eval questions to add (agent/eval)

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
