# Machine-read zoning layer: design

Date: 2026-11-11. Status: pilot. Nothing here is wired into the app.

Not legal advice. Not a zoning determination.

## The idea in one line

Keep the hand-checked rule files as they are. Add a second, clearly weaker layer: the town's own ordinance text, searchable, with a machine draft that quotes it. Fall back to the statewide baseline when neither exists.

## Three tiers, kept apart

| Tier | What it is | How the assistant may use it | Label shown |
|---|---|---|---|
| A. Verified rule file | `shared/rules/pa_*.json`, read and checked by people | State values, cite section, link and check date. As today | "Checked rule file, verified on <date>" |
| B. Machine-read town | Ordinance text fetched from the town or county site, split into sections, plus a draft summary made by a small model, each claim tied to a quote that a program found in the text | Quote the text with section, page, link and retrieval date. Show the draft summary only under its label. Never state a conclusion the quotes do not support. Never fill a tier A field from it | "Machine-read, not verified. Read the quoted text." |
| C. Statewide baseline | `shared/rules/pa_statewide.json` | MPC paths, building code, sewage, bills. As today | "Statewide baseline, not this town's code" |

Order: A wins. B is used only for a place with no A file. C is always given beside B, because B may be stale, partial or wrong.

Rules for tier B answers:
- Every sentence about the town's rule carries a quote from `search_zoning_text` or from a summary claim whose `check` is `ok`.
- A summary field with `absence: true` (for example `not_addressed`) is said as "I did not find ADU text in the parts of the ordinance I searched", never as "ADUs are not allowed".
- Fields the model could not support were dropped. They are listed in `unsupported` and must not be stated.
- Always say the document date or retrieval date, and that a newer amendment may exist.
- Always end with: ask the zoning officer before you design or build.

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

Prototype: `pipeline/corpus/search_zoning_text.mjs` (Node, BM25 only, no model, reads one JSON file per place). Not wired into the app.

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

- There are about 40 hand-checked towns. That is the test set, not a training set. Training on them would leave nothing honest to measure with.
- A fine-tuned extractor would learn the format of 40 answers, not the law of 2,500 towns. The hard parts are retrieval (finding the use table row and the conditions), reading flattened tables, and keeping conditions and scope. None of these get better from 40 examples.
- Retrieval plus a small general model plus a quote check is cheaper to run, easy to audit (every claim has a span), and does not need labels. The verified towns stay a clean test set.
- What could help later: a small reranker or embedding fine-tune trained on (question, cited section) pairs from the rule files, if the pilot grows to a few hundred checked pairs. Gain would be in retrieval only, and only a few points.

## What the local GPU is for

- Embeddings. bge-small runs at about 120 chunks/s on MPS against 20 on CPU. e5-base about 43 against 6. All public Pennsylvania text (about 200k chunks) embeds in about 30 minutes with bge-small or about 80 minutes with e5-base on the M3 Pro.
- Re-embedding after a change, and trying other embedding models or a reranker.
- Possibly OCR for scanned PDFs (a quarter of public copies), if a local OCR model is added later.
- It is not needed for extraction. The extraction call is a hosted model and costs under half a cent per town.
