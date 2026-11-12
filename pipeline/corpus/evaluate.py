"""Score retrieval and machine extraction against the hand-checked town rule files.

Gold: shared/rules/pa_*.json as committed (read with `git show HEAD:...`, so a file being
edited by someone else does not change the score), or the working tree with --gold worktree.
--verified-only drops towns whose index status is "drafted". Only towns with corpus text are scored.

Retrieval: each hand-checked fact becomes a question. A question is scorable when the
section the town file cites can be found somewhere in that town's corpus text (else the
copy we hold is not the copy the reviewer read, and the question is skipped). A hit at k
means one of the top k chunks carries the cited section: its label, parent or an ancestor
of the cited label, or the label printed in its text.

Extraction: status exact, approval path, fallback path, districts (Jaccard), numeric caps
within 5 percent, owner and family flags, parking, conditions and alternatives found by
section, unsupported claims.

Run:
    python -m pipeline.corpus.evaluate retrieval
    python -m pipeline.corpus.evaluate extraction
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from typing import Any

from pipeline.corpus.chunk import load_chunks
from pipeline.corpus.draft_rules import norm
from pipeline.corpus.paths import REPO, sub

RX_LABEL = re.compile(r"\d+[A-Z]?-\d+(?:\.\d+)*[A-Z]?|\d\.\d{2}\.\d{3}|\d{3,4}(?:\.\d+)*")

QUESTIONS = {  # type -> (gold getter path, question text)
    "adu_term": (("adu", "term"), "What does the zoning ordinance call an accessory dwelling unit or in-law apartment?"),
    "status": (("adu", "status"), "Are accessory dwelling units allowed?"),
    "approval_path": (("approval", "path"), "What approval is needed for an accessory dwelling unit: permit, special "
                      "exception or conditional use?"),
    "districts": (("eligibility", "zoning_districts"), "In which zoning districts is an accessory dwelling unit "
                  "allowed?"),
    "size_cap": (("size", "max_sqft"), "What is the maximum floor area of an accessory dwelling unit?"),
    "size_share": (("size", "max_share_of_house"), "What share of the principal dwelling floor area may an "
                   "accessory unit use?"),
    "owner_occupancy": (("use", "owner_occupancy"), "Must the property owner live on the lot with an accessory "
                        "dwelling unit?"),
    "family": (("use", "family_only"), "Is the accessory unit limited to relatives or family members?"),
    "parking": (("parking", "spaces_required"), "How many off-street parking spaces does an accessory dwelling "
                "unit need?"),
    "unlisted_use": (("approval", "unlisted_use_path"), "How are uses not listed or not provided for in the "
                     "ordinance handled?"),
    "alternatives": (("approval", "alternatives"), "Can a single-family house be converted to a two-family "
                     "dwelling or duplex?"),
    "fallback": (("approval", "fallback_path"), "What if a use is not permitted in the district: variance?"),
}


# ---------------------------------------------------------------- gold
def git_json(path: str) -> Any:
    out = subprocess.run(["git", "-C", str(REPO), "show", f"HEAD:{path}"], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return json.loads(out.stdout)


GOLD_SOURCE = "head"  # "head": committed files, "worktree": files on disk
GOLD_STATUSES = ("verified", "drafted")


def read_gold(path: str) -> Any:
    if GOLD_SOURCE == "worktree":
        p = REPO / path
        if not p.exists() or not p.read_text().strip():
            return None
        return json.loads(p.read_text())
    return git_json(path)


def gold_files() -> dict[str, dict[str, Any]]:
    idx = read_gold("shared/rules/towns_index.json") or {"towns": []}
    out = {}
    for t in idx["towns"]:
        if t.get("status") not in GOLD_STATUSES or not t.get("file", "").startswith("pa_"):
            continue
        d = read_gold(f"shared/rules/{t['file']}.json")
        if d:
            out[t["geoid"]] = {"file": t["file"], "status": t["status"], "rules": d}
    return out


def get(d: dict[str, Any], path: tuple[str, ...]) -> Any:
    for p in path:
        d = d.get(p) if isinstance(d, dict) else None
    return d


def labels_in(section: str | None) -> list[str]:
    """Section labels inside a citation, e.g. '2515.2 and 2515.2.A(8)' -> ['2515.2', '2515.2']."""
    if not section:
        return []
    found = [re.sub(r"(?<=\d)[A-Z]$", "", f) for f in RX_LABEL.findall(section)]  # 660-42C -> 660-42
    return [f for f in found if not re.fullmatch(r"(19|20)\d\d", f) and f not in ("910.2",)]


def _related(a: str, b: str) -> bool:
    """Same label, or one is an ancestor of the other (2515 and 2515.2)."""
    return a == b or b.startswith(a + ".") or a.startswith(b + ".") or b.startswith(a + "-") \
        or a.startswith(b + "(") or b.startswith(a + "(")


def gold_quotes(item: dict[str, Any]) -> list[str]:
    """Quoted words in the reviewer's note, normalised, first 60 characters, at least 4 words."""
    out = []
    for m in re.findall(r"[\'\"\u2018\u201c]([^\'\"\u2019\u201d]{20,})[\'\"\u2019\u201d]", item.get("note") or ""):
        q = norm(m.replace("...", " ").split(" ... ")[0])[:60].strip()
        if len(q.split()) >= 4:
            out.append(q)
    return out


def chunk_has(c: dict[str, Any], label: str) -> bool:
    own = [x for x in [c.get("section"), c.get("parent"), *(c.get("sections") or [])] if x]
    if any(_related(x, label) for x in own):
        return True
    t = " " + norm(c["text"]) + " "
    return re.search(r"(?<![\d.])" + re.escape(label.lower()) + r"(?![\d])", t) is not None


# ---------------------------------------------------------------- retrieval
def retrieval(models: tuple[str, ...] = ("bge", "e5"), ks: tuple[int, ...] = (5, 10), tag: str = "") -> dict[str, Any]:
    from pipeline.corpus.search import search

    gold = gold_files()
    chunks = load_chunks()
    by_place: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in chunks:
        by_place[c["geoid"]].append(c)
    rows = []
    for geoid, g in gold.items():
        if geoid not in by_place:
            continue
        term = (get(g["rules"], ("adu", "term")) or {}).get("value")
        for qtype, (path, question) in QUESTIONS.items():
            item = get(g["rules"], path)
            if not isinstance(item, dict) or not item.get("section"):
                continue
            if item.get("value") is None and item.get("confidence") == "unverified":
                continue
            labels = [x for x in labels_in(item["section"]) if any(chunk_has(c, x) for c in by_place[geoid])]
            target = "section"
            if labels:
                def ok(h: dict[str, Any], labels: list[str] = labels) -> bool:
                    return any(chunk_has(h, x) for x in labels)
            else:
                # the copy we hold may number sections differently (ordinance vs codified chapter):
                # fall back to the words the reviewer quoted in the note
                quotes = [qq for qq in gold_quotes(item) if any(qq in norm(c["text"]) for c in by_place[geoid])]
                if not quotes:
                    rows.append({"geoid": geoid, "file": g["file"], "qtype": qtype, "scorable": False,
                                 "cited": item["section"]})
                    continue
                target = "quote"

                def ok(h: dict[str, Any], quotes: list[str] = quotes) -> bool:
                    t = norm(h["text"])
                    return any(qq in t for qq in quotes)
            q = question if not term or qtype == "adu_term" else question.replace("accessory dwelling unit", term)
            row = {"geoid": geoid, "file": g["file"], "qtype": qtype, "scorable": True, "cited": item["section"],
                   "target": target, "labels": labels, "query": q}
            for model in models:
                for mode in ("hybrid", "vector"):
                    hits = search(geoid, q, max(ks), model=model, mode=mode)
                    row[f"{model}_{mode}_rank"] = next((i + 1 for i, h in enumerate(hits) if ok(h)), None)
            hits = search(geoid, q, max(ks), mode="bm25")
            row["bm25_rank"] = next((i + 1 for i, h in enumerate(hits) if ok(h)), None)
            rows.append(row)
    scored = [r for r in rows if r["scorable"]]
    systems = [f"{m}_{mode}" for m in models for mode in ("hybrid", "vector")] + ["bm25"]
    summary: dict[str, Any] = {"towns": sorted({r["file"] for r in scored}), "questions": len(scored),
                               "by_quote": sum(1 for r in scored if r.get("target") == "quote"),
                               "unscorable": len(rows) - len(scored), "by_system": {}, "by_type": {}}
    for s in systems:
        summary["by_system"][s] = {f"top{k}": _rate(scored, s, k) for k in ks}
    for qtype in QUESTIONS:
        sub_rows = [r for r in scored if r["qtype"] == qtype]
        if sub_rows:
            summary["by_type"][qtype] = {"n": len(sub_rows), **{f"{s}@{k}": _rate(sub_rows, s, k)
                                                                 for s in systems for k in ks}}
    out = sub("eval")
    (out / f"retrieval_rows{tag}.json").write_text(json.dumps(rows, indent=1))
    (out / f"retrieval_summary{tag}.json").write_text(json.dumps(summary, indent=1))
    return summary


def _rate(rows: list[dict[str, Any]], system: str, k: int) -> float:
    key = f"{system}_rank"
    return round(sum(1 for r in rows if r.get(key) and r[key] <= k) / len(rows), 3) if rows else 0.0


# ---------------------------------------------------------------- extraction
STATUS_FROM_FLAGS = True


def consistent_status(draft: dict[str, Any]) -> str | None:
    """Apply the town-file rule 'pick the most limiting' to the model's own fields:
    family_only true makes the status family_only, a garage or carriage house conversion as the
    only form makes it conversion_only. Uses only values that passed the quote check."""
    st = (draft.get("status") or {}).get("value")
    if st in (None, "not_addressed", "prohibited"):
        return st
    if (draft.get("family_only") or {}).get("value") is True:
        return "family_only"
    forms = (draft.get("forms") or {}).get("value") or []
    if forms and set(forms) <= {"garage_conversion"}:
        return "conversion_only"
    return st


def _val(item: Any) -> Any:
    return item.get("value") if isinstance(item, dict) else None


def _dists(xs: Any) -> set[str]:
    return {re.sub(r"[\s-]", "", str(x)).upper() for x in (xs or [])}


def gold_caps(r: dict[str, Any]) -> dict[str, float]:
    size = r.get("size", {})
    out = {}
    for k in ("max_sqft", "max_share_of_house", "max_sqft_internal", "max_sqft_accessory_building",
              "max_share_internal", "max_share_accessory_building", "min_sqft"):
        v = _val(size.get(k))
        if isinstance(v, (int, float)):
            out[k] = float(v)
    return out


def machine_caps(d: dict[str, Any]) -> dict[str, float]:
    out = {}
    for c in d.get("size_caps") or []:
        kind, to, v = c.get("kind"), c.get("applies_to"), c.get("value")
        if kind == "max_bedrooms" or v is None:
            continue
        if kind == "min_sqft":
            out["min_sqft"] = v
        elif to in ("all", None):
            out[kind] = v
        elif to in ("internal", "attached"):
            out["max_sqft_internal" if kind == "max_sqft" else "max_share_internal"] = v
        else:
            out["max_sqft_accessory_building" if kind == "max_sqft" else "max_share_accessory_building"] = v
    return out


def extraction(drafts_dir: str | None = None, tag: str = "") -> dict[str, Any]:
    from pathlib import Path

    gold = gold_files()
    rows = []
    for p in sorted((Path(drafts_dir) if drafts_dir else sub("drafts")).glob("*.json")):
        d = json.loads(p.read_text())
        g = gold.get(d["geoid"])
        if not g:
            continue
        r, m = g["rules"], d["draft"]
        gs = _val(get(r, ("adu", "status")))
        row: dict[str, Any] = {"geoid": d["geoid"], "file": g["file"], "gold_status_of_file": g["status"],
                               "status_gold": gs, "status_raw": _val(m.get("status")),
                               "status_consistent": consistent_status(m)}
        row["path_gold"], row["path_machine"] = _val(get(r, ("approval", "path"))), _val(m.get("approval_path"))
        row["fallback_gold"], row["fallback_machine"] = (_val(get(r, ("approval", "fallback_path"))),
                                                         _val(m.get("fallback_path")))
        row["unlisted_gold"], row["unlisted_machine"] = (_val(get(r, ("approval", "unlisted_use_path"))),
                                                         _val(m.get("unlisted_use_path")))
        gd = _dists(_val(get(r, ("eligibility", "zoning_districts"))))
        md = _dists(_val(m.get("districts")))
        row["districts_gold"], row["districts_machine"] = sorted(gd), sorted(md)
        row["districts_jaccard"] = round(len(gd & md) / len(gd | md), 3) if (gd or md) else None
        row["districts_extra"], row["districts_missed"] = sorted(md - gd), sorted(gd - md)
        gc, mc = gold_caps(r), machine_caps(m)
        caps = {}
        for k in set(gc) | set(mc):
            a, b = gc.get(k), mc.get(k)
            caps[k] = {"gold": a, "machine": b,
                       "match": (a is not None and b is not None and abs(a - b) <= 0.05 * max(abs(a), 1e-9))}
        row["caps"] = caps
        for fld, gp in (("owner_occupancy", ("use", "owner_occupancy")), ("family_only", ("use", "family_only")),
                        ("parking", ("parking", "spaces_required"))):
            mk = "parking_spaces_for_adu" if fld == "parking" else fld
            row[f"{fld}_gold"], row[f"{fld}_machine"] = _val(get(r, gp)), _val(m.get(mk))
        msecs = {lab for v in m.values() if isinstance(v, (dict, list))
                 for it in (v if isinstance(v, list) else [v]) if isinstance(it, dict)
                 for s in it.get("support", []) for lab in labels_in(s.get("section")) + labels_in(s.get("chunk_section"))}
        gates = _val(get(r, ("eligibility", "gates"))) or []
        gate_found = [any(_related(a, b) for a in labels_in(gt.get("section")) for b in msecs) for gt in gates]
        row["conditions_gold"], row["conditions_found_by_section"] = len(gates), sum(gate_found)
        alts = _val(get(r, ("approval", "alternatives"))) or []
        row["alternatives_gold"] = len(alts)
        row["alternatives_machine"] = len(m.get("alternatives") or [])
        row["unsupported"] = len(d["unsupported"])
        row["quote_checks"] = d["quote_checks"]
        row["usd"], row["seconds"] = d["usd"], d["seconds_total"]
        row["tokens_in"], row["tokens_out"] = d["usage"]["input_tokens"], d["usage"]["output_tokens"]
        rows.append(row)
    summary = summarize(rows)
    out = sub("eval")
    (out / f"extraction_rows{tag}.json").write_text(json.dumps(rows, indent=1))
    (out / f"extraction_summary{tag}.json").write_text(json.dumps(summary, indent=1))
    return summary


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"towns": 0}

    def rate(pred) -> float:
        xs = [pred(r) for r in rows]
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 3) if xs else None  # type: ignore[return-value]

    conf: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    conf2: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        conf[r["status_gold"]][str(r["status_raw"])] += 1
        conf2[r["status_gold"]][str(r["status_consistent"])] += 1
    cap_pairs = [c for r in rows for c in r["caps"].values() if c["gold"] is not None]
    cap_extra = [c for r in rows for c in r["caps"].values() if c["gold"] is None]
    q_total = sum(r["quote_checks"]["total"] for r in rows)
    return {
        "towns": n,
        "status_exact_raw": rate(lambda r: r["status_raw"] == r["status_gold"]),
        "status_exact_consistent": rate(lambda r: r["status_consistent"] == r["status_gold"]),
        "confusion_raw": {k: dict(v) for k, v in conf.items()},
        "confusion_consistent": {k: dict(v) for k, v in conf2.items()},
        "path_match": rate(lambda r: r["path_machine"] == r["path_gold"]),
        "fallback_match": rate(lambda r: None if r["fallback_gold"] is None else r["fallback_machine"] == r["fallback_gold"]),
        "unlisted_found": rate(lambda r: None if not r["unlisted_gold"] else r["unlisted_machine"] == r["unlisted_gold"]),
        "districts_mean_jaccard": rate(lambda r: r["districts_jaccard"]),
        "districts_exact": rate(lambda r: None if r["districts_jaccard"] is None else r["districts_jaccard"] == 1.0),
        "caps_gold": len(cap_pairs), "caps_matched": sum(1 for c in cap_pairs if c["match"]),
        "caps_extra_machine_only": len(cap_extra),
        "owner_occupancy_match": rate(lambda r: None if r["owner_occupancy_gold"] is None else
                                      r["owner_occupancy_machine"] == r["owner_occupancy_gold"]),
        "family_only_match": rate(lambda r: None if r["family_only_gold"] is None else
                                  r["family_only_machine"] == r["family_only_gold"]),
        "parking_match": rate(lambda r: None if r["parking_gold"] is None else r["parking_machine"] == r["parking_gold"]),
        "conditions_gold": sum(r["conditions_gold"] for r in rows),
        "conditions_found_by_section": sum(r["conditions_found_by_section"] for r in rows),
        "alternatives_gold": sum(r["alternatives_gold"] for r in rows),
        "alternatives_machine": sum(r["alternatives_machine"] for r in rows),
        "unsupported_claims": sum(r["unsupported"] for r in rows),
        "quotes": q_total, "quotes_ok": sum(r["quote_checks"]["ok"] for r in rows),
        "quotes_other_chunk": sum(r["quote_checks"]["other_chunk"] for r in rows),
        "usd_total": round(sum(r["usd"] for r in rows), 4),
        "usd_mean": round(sum(r["usd"] for r in rows) / n, 5),
        "seconds_mean": round(sum(r["seconds"] for r in rows) / n, 1),
        "tokens_in_mean": round(sum(r["tokens_in"] for r in rows) / n),
        "tokens_out_mean": round(sum(r["tokens_out"] for r in rows) / n),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["retrieval", "extraction"])
    ap.add_argument("--drafts-dir")
    ap.add_argument("--tag", default="")
    ap.add_argument("--gold", choices=["head", "worktree"], default="head",
                    help="read the town files from the last commit or from the working tree")
    ap.add_argument("--verified-only", action="store_true", help="score against verified towns only")
    a = ap.parse_args()
    GOLD_SOURCE = a.gold
    if a.verified_only:
        GOLD_STATUSES = ("verified",)
    res = retrieval(tag=a.tag) if a.what == "retrieval" else extraction(a.drafts_dir, a.tag)
    print(json.dumps(res, indent=1))
