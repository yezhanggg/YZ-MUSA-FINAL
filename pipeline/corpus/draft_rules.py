"""Machine-read DRAFT summary of one municipality's ADU rules, with quote checks.

Steps for one place:
  1. retrieve: a fixed set of queries (ADU terms, accessory uses, use table, definitions,
     unlisted uses, conversions and two-family, accessory height and yards, parking,
     nonconforming lots). Hybrid search, top 4 each, merged, capped at MAX_CONTEXT_TOKENS.
  2. extract: one call to claude-haiku-5-5 with a strict instruction and a JSON schema
     (tool use). Every claim carries a quote, the chunk it came from and the section.
  3. verify: each quote must occur in the cited chunk after whitespace and quote-mark
     normalisation. A quote found only in another retrieved chunk is kept and flagged
     "other_chunk". A quote found nowhere is dropped from the summary and listed in
     `unsupported`.

The output is a draft. It is labelled machine-read, not verified. It keeps the source
text, section, page, URL and retrieval date beside each claim.

Spend is logged to corpus/drafts/spend.jsonl. The run stops before a call that could pass
the budget cap.

Run (the API key is read from the environment only):
    python -m pipeline.corpus.draft_rules 4207146896
    python -m pipeline.corpus.draft_rules --all
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date
from typing import Any

from pipeline.corpus.chunk import load_chunks
from pipeline.corpus.paths import sub

MODEL = "claude-haiku-5-5"
PRICE_IN = 0.10 / 1e6  # USD per input token, prompts under 100k tokens (pricing page, 2026-11-11)
PRICE_OUT = 0.50 / 1e6
BUDGET_USD = 5.00
STOP_AT_USD = 4.50
MAX_CONTEXT_TOKENS = 22000
PER_QUERY = 4

QUERIES = [
    "accessory dwelling unit",
    "accessory apartment in-law suite granny flat ECHO elder cottage carriage house secondary dwelling",
    "accessory dwelling unit special exception conditions owner occupancy relatives",
    "permitted accessory uses residential district",
    "use table permitted uses by district special exception conditional use",
    "definition of dwelling unit and family",
    "uses not provided for unlisted uses similar use",
    "conversion of single-family dwelling to two-family duplex",
    "accessory building structure height and yard setbacks",
    "off-street parking spaces per dwelling unit",
    "nonconforming lots of record",
    "maximum floor area of accessory dwelling unit square feet percent of principal dwelling",
]

STATUS = ["allowed_by_right", "special_exception", "conditional_use", "family_only", "conversion_only",
          "not_addressed", "prohibited"]
PATHS = ["by_right", "administrator_exception", "special_exception", "conditional_use", "variance", "not_allowed",
         "unknown"]
FORMS = ["internal", "attached", "detached_new", "over_garage", "garage_conversion"]

CLAIM = {"type": "object", "properties": {
    "quote": {"type": "string", "description": "Exact words copied from the chunk, 5 to 60 words."},
    "chunk": {"type": "string", "description": "Chunk id, e.g. C4"},
    "section": {"type": "string", "description": "Section label as printed in the text"}},
    "required": ["quote", "chunk", "section"]}


def _claim(value_schema: dict[str, Any], desc: str) -> dict[str, Any]:
    return {"type": "object", "description": desc, "properties": {
        "value": value_schema, "support": {"type": "array", "items": CLAIM}}, "required": ["value", "support"]}


SCHEMA = {"type": "object", "properties": {
    "status": _claim({"type": "string", "enum": STATUS}, "ADU status. If two apply pick the most limiting"),
    "term": _claim({"type": ["string", "null"]}, "What the code calls an ADU, in its own words. null if none"),
    "approval_path": _claim({"type": "string", "enum": PATHS}, "Path for an ADU where the code allows one"),
    "fallback_path": _claim({"type": "string", "enum": PATHS},
                            "Path when the lot or district does not qualify, or the use is not listed"),
    "unlisted_use_path": _claim({"type": ["string", "null"], "enum": PATHS + [None]},
                                "Path for a use the code does not list, only if the code has such a clause"),
    "districts": _claim({"type": "array", "items": {"type": "string"}},
                        "District codes where an ADU is allowed (any path). Empty if none"),
    "district_paths": {"type": "array", "description": "Only where the path differs by district",
                       "items": {"type": "object", "properties": {
                           "districts": {"type": "array", "items": {"type": "string"}},
                           "path": {"type": "string", "enum": PATHS},
                           "support": {"type": "array", "items": CLAIM}},
                           "required": ["districts", "path", "support"]}},
    "forms": _claim({"type": "array", "items": {"type": "string", "enum": FORMS}}, "Forms of ADU allowed"),
    "size_caps": {"type": "array", "description": "Each size cap, with the form it applies to", "items": {
        "type": "object", "properties": {
            "applies_to": {"type": "string", "enum": ["all", "internal", "attached", "accessory_building"]},
            "kind": {"type": "string", "enum": ["max_sqft", "max_share_of_house", "min_sqft", "max_bedrooms"]},
            "value": {"type": "number", "description": "Share as a fraction, e.g. 0.4 for 40 percent"},
            "support": {"type": "array", "items": CLAIM}},
        "required": ["applies_to", "kind", "value", "support"]}},
    "occupancy": _claim({"type": ["string", "null"]}, "Who may live in the ADU, plain words"),
    "family_only": _claim({"type": ["boolean", "null"]}, "Only relatives or caregivers may live there"),
    "owner_occupancy": _claim({"type": ["boolean", "null"]}, "The owner must live on the lot"),
    "parking_spaces_for_adu": _claim({"type": ["number", "null"]}, "Extra off-street spaces for the ADU"),
    "conditions": {"type": "array", "description": "Other conditions that limit who may build (lot size, "
                   "utilities, district, building type, existing building only)", "items": {
        "type": "object", "properties": {"condition": {"type": "string"},
                                         "districts": {"type": ["array", "null"], "items": {"type": "string"}},
                                         "support": {"type": "array", "items": CLAIM}},
        "required": ["condition", "support"]}},
    "alternatives": {"type": "array", "description": "Other ways to add a unit that are not an ADU, such as "
                     "a conversion to two-family or a duplex", "items": {
        "type": "object", "properties": {"name": {"type": "string"}, "path": {"type": "string", "enum": PATHS},
                                         "districts": {"type": "array", "items": {"type": "string"}},
                                         "support": {"type": "array", "items": CLAIM}},
        "required": ["name", "path", "support"]}},
    "could_not_find": {"type": "array", "items": {"type": "string"},
                       "description": "Topics the excerpts do not settle"},
}, "required": ["status", "term", "approval_path", "fallback_path", "districts", "forms", "size_caps",
                "occupancy", "family_only", "owner_occupancy", "parking_spaces_for_adu", "conditions",
                "alternatives", "could_not_find"]}

SYSTEM = """You read excerpts of one Pennsylvania municipality's zoning ordinance and fill a draft summary of its rules for accessory dwelling units (ADUs). The draft is checked against the text by a program and by people.

Strict rules:
- Use only the excerpts. Never use outside knowledge of this town or of typical codes. If the excerpts do not settle a field, use null (or an empty list) and add the topic to could_not_find.
- Every value needs support: an exact quote copied character for character from one excerpt (5 to 60 words), the excerpt id (C1, C2...) and the section label printed in the text. A value without a quote is not allowed. Do not paraphrase inside a quote. Do not join text from two places into one quote.
- An excerpt may be a table flattened to text. Read use tables with care: a row lists a use, then one cell per district in the column order of the header.

Status values:
- allowed_by_right: a zoning permit when the standards are met, no hearing.
- special_exception: Zoning Hearing Board hearing.
- conditional_use: governing body hearing.
- family_only: allowed only for relatives or caregivers (ECHO, in-law). Use this even when the path is a special exception, and give the path in approval_path.
- conversion_only: allowed only inside an existing building (for example a garage or carriage house conversion).
- not_addressed: the code has no ADU text.
- prohibited: the code bars ADUs or a second unit on the lot.
If two apply, pick the one that limits most.

Watch for these common errors:
- A rule that applies only in some districts or an overlay is not town-wide. Put the districts in districts or district_paths.
- Keep conditions. Do not drop lot size, utility, owner, family or building type limits.
- A size cap belongs to a form (inside the house, in an accessory building). Say which in applies_to.
- The fallback path is what applies when the ADU rule does not reach the lot. Usually a variance. A clause for uses not provided for gives a special exception or conditional use for unlisted uses: put it in unlisted_use_path, only when such a clause is in the excerpts.
- A conversion of a house to two-family or a duplex is an alternative, not an ADU.

Call the tool record_draft once."""


def norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    s = re.sub(r"-\s*\n\s*", "-", s)
    return " ".join(s.split()).lower()


# ---------------------------------------------------------------- retrieval
def retrieve(geoid: str, model: str = "bge") -> list[dict[str, Any]]:
    from pipeline.corpus.search import search

    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for qi, q in enumerate(QUERIES):
        for r, hit in enumerate(search(geoid, q, PER_QUERY, model=model)):
            score = r * 100 + qi
            if hit["chunk_id"] not in best or score < best[hit["chunk_id"]][0]:
                best[hit["chunk_id"]] = (score, hit)
    picked, total = [], 0
    for _, hit in sorted(best.values(), key=lambda x: x[0]):
        t = len(hit["text"]) // 4
        if total + t > MAX_CONTEXT_TOKENS:
            continue
        picked.append(hit)
        total += t
    return picked


def context(hits: list[dict[str, Any]]) -> str:
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(f"<excerpt id=\"C{i}\" section=\"{h.get('section') or ''}\" path=\"{h.get('heading_path') or ''}\" "
                     f"pages=\"{h.get('page_start')}-{h.get('page_end')}\">\n{h['text']}\n</excerpt>")
    return "\n\n".join(parts)


# ---------------------------------------------------------------- spend
def spent() -> float:
    p = sub("drafts") / "spend.jsonl"
    if not p.exists():
        return 0.0
    return sum(json.loads(x)["usd"] for x in p.read_text().splitlines() if x.strip())


def log_spend(geoid: str, usage: dict[str, int], usd: float, note: str = "") -> None:
    with (sub("drafts") / "spend.jsonl").open("a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "geoid": geoid, "model": MODEL,
                            **usage, "usd": round(usd, 6), "note": note}) + "\n")


def cost(usage: dict[str, int], batch: bool = False) -> float:
    f = 0.5 if batch else 1.0
    return f * (usage.get("input_tokens", 0) * PRICE_IN + usage.get("output_tokens", 0) * PRICE_OUT
                + usage.get("cache_creation_input_tokens", 0) * PRICE_IN * 1.25
                + usage.get("cache_read_input_tokens", 0) * PRICE_IN * 0.1)


def call_model(geoid: str, name: str, ctx: str) -> tuple[dict[str, Any], dict[str, int], float]:
    import anthropic

    if spent() > STOP_AT_USD:
        raise SystemExit(f"spend {spent():.2f} USD is over the stop line {STOP_AT_USD}. Not calling the model")
    client = anthropic.Anthropic()
    t0 = time.time()
    msg = client.messages.create(
        model=MODEL, max_tokens=6000, system=SYSTEM,
        tools=[{"name": "record_draft", "description": "Record the draft ADU summary", "input_schema": SCHEMA}],
        tool_choice={"type": "tool", "name": "record_draft"},
        messages=[{"role": "user", "content": f"Municipality: {name}\n\n{ctx}"}])
    dt = time.time() - t0
    u = msg.usage
    usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
             "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
             "cache_read_input_tokens": u.cache_read_input_tokens or 0}
    usd = cost(usage)
    log_spend(geoid, usage, usd)
    out = next((b.input for b in msg.content if b.type == "tool_use"), None) or {}
    return out, usage | {"seconds": round(dt, 1), "stop_reason": msg.stop_reason}, usd


# ---------------------------------------------------------------- verification
def _check_support(support: list[dict[str, Any]], hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    texts = [norm(h["text"]) for h in hits]
    out = []
    for s in support or []:
        q = norm(s.get("quote", ""))
        m = re.match(r"C?(\d+)", str(s.get("chunk", "")).strip())
        ci = int(m.group(1)) - 1 if m else -1
        status = "missing"
        found = ci
        if len(q) >= 8:
            if 0 <= ci < len(hits) and q in texts[ci]:
                status = "ok"
            else:
                found = next((j for j, t in enumerate(texts) if q in t), -1)
                status = "other_chunk" if found >= 0 else "missing"
        h = hits[found] if 0 <= found < len(hits) else {}
        out.append({**s, "check": status, "chunk_id": h.get("chunk_id"), "url": h.get("url"),
                    "page_start": h.get("page_start"), "page_end": h.get("page_end"),
                    "retrieved_on": h.get("retrieved_on"), "chunk_section": h.get("section")})
    return out


def verify(draft: dict[str, Any], hits: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Check every quote. A claim with no checked quote is dropped and listed as unsupported."""
    unsupported: list[dict[str, Any]] = []
    clean: dict[str, Any] = {}

    def keep(field: str, item: dict[str, Any]) -> dict[str, Any] | None:
        sup = _check_support(item.get("support", []), hits)
        item = {**item, "support": sup}
        empty = item.get("value") in (None, [], "") if "value" in item else False
        if empty:
            return item
        if any(s["check"] in ("ok", "other_chunk") for s in sup):
            return item
        unsupported.append({"field": field, "value": item.get("value", item.get("name", item.get("condition"))),
                            "quotes": [s.get("quote") for s in sup]})
        return None

    for field, val in draft.items():
        if field == "could_not_find":
            clean[field] = val
        elif isinstance(val, dict):
            k = keep(field, val)
            clean[field] = k if k is not None else {"value": None, "support": [], "dropped": True}
        elif isinstance(val, list):
            clean[field] = [k for k in (keep(field, x) for x in val if isinstance(x, dict)) if k is not None]
    return clean, unsupported


# ---------------------------------------------------------------- one place
def place_name(geoid: str) -> str:
    import csv

    for r in csv.DictReader((sub("") / "municipalities.csv").open()):
        if r["geoid"] == geoid:
            return f"{r['name']}, {r['county']} County, Pennsylvania"
    return geoid


def draft(geoid: str, model: str = "bge", force: bool = False) -> dict[str, Any]:
    dest = sub("drafts") / f"{geoid}.json"
    if dest.exists() and not force:
        return json.loads(dest.read_text())
    t0 = time.time()
    hits = retrieve(geoid, model)
    t_ret = time.time() - t0
    raw, usage, usd = call_model(geoid, place_name(geoid), context(hits))
    clean, unsupported = verify(raw, hits)
    n_claims = sum(len(v.get("support", [])) if isinstance(v, dict) else
                   sum(len(x.get("support", [])) for x in v if isinstance(x, dict))
                   for k, v in raw.items() if k != "could_not_find" and isinstance(v, (dict, list)))
    checks = [s["check"] for v in clean.values() if isinstance(v, (dict, list))
              for item in (v if isinstance(v, list) else [v]) if isinstance(item, dict)
              for s in item.get("support", [])]
    out = {"geoid": geoid, "place": place_name(geoid), "label": "machine-read, not verified, read the quoted text",
           "model": MODEL, "made_on": date.today().isoformat(), "retrieval_model": model,
           "chunks": [{k: h[k] for k in ("chunk_id", "section", "heading_path", "page_start", "page_end", "url",
                                          "retrieved_on")} for h in hits],
           "draft": clean, "raw": raw, "unsupported": unsupported,
           "quote_checks": {"total": len(checks), "ok": checks.count("ok"),
                            "other_chunk": checks.count("other_chunk"), "missing": checks.count("missing"),
                            "quotes_in_raw": n_claims},
           "usage": usage, "usd": round(usd, 6), "seconds_total": round(time.time() - t0, 1),
           "seconds_retrieval": round(t_ret, 1), "context_tokens_est": sum(len(h["text"]) // 4 for h in hits)}
    dest.write_text(json.dumps(out, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("geoids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--model", default="bge")
    a = ap.parse_args()
    geoids = a.geoids
    if a.all:
        geoids = sorted({c["geoid"] for c in load_chunks()})
    for g in geoids:
        try:
            d = draft(g, a.model, a.force)
        except SystemExit as e:
            print(e)
            break
        st = d["draft"].get("status", {}).get("value")
        print(f"{g} {d['place']}: status={st} quotes={d['quote_checks']} usd={d['usd']} s={d['seconds_total']} "
              f"total_spent={spent():.4f}", flush=True)


if __name__ == "__main__":
    main()
