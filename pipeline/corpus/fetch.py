"""Polite, resumable downloader for public zoning documents.

Rules it keeps:
  - only hosts that are not commercial code hosts (see BLOCKED_HOSTS)
  - robots.txt is read once per host and obeyed, with the honest User-Agent below
  - one request at a time, at least 2 seconds apart per host (more if robots asks)
  - a URL already in the manifest with a file on disk is not fetched again
  - a refusal (401, 403, 429, robots) is recorded and the URL is skipped

Manifest: corpus/manifest.jsonl, one JSON line per attempt
  {url, final_url, geoid, status, content_type, bytes, sha256, fetched_at, robots, path, error, via}

Input: a CSV with columns geoid, url and optional kind (doc or index). For an index
page, links to PDF or DOC files on the same site whose link text or address looks
like zoning text are followed (at most MAX_LINKS per page).

Run:
    python -m pipeline.corpus.fetch sources.csv
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from pipeline.corpus.paths import sub

USER_AGENT = "zoning-text-research/0.1 (public ordinance survey; one request per 2 s; obeys robots.txt)"
MIN_DELAY_S = 2.0
TIMEOUT_S = 60
MAX_BYTES = 120 * 1024 * 1024
MAX_LINKS = 60
BLOCKED_HOSTS = ("ecode360.com", "generalcode.com", "municode.com", "amlegal.com", "zoneomics.com",
                 "codepublishing.com", "codelibrary", "elaws.us", "lawserver.com")
LINK_WORDS = re.compile(r"zon|article|chapter|part|ordinance|definition|district|use|accessory|parking|"
                        r"supplement|appendix|section|table", re.I)
DOC_EXT = re.compile(r"\.(pdf|docx?)($|\?)|/DocumentCenter/View/|getattachment|/download|/files/", re.I)


def manifest_path() -> Path:
    return sub("") / "manifest.jsonl"


def raw_dir(geoid: str) -> Path:
    return sub("raw") / geoid


def is_blocked(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(b in host for b in BLOCKED_HOSTS)


def load_manifest() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    p = manifest_path()
    if p.exists():
        for line in p.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                out[rec["url"]] = rec
    return out


class Fetcher:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self.robot_notes: dict[str, str] = {}
        self.last: dict[str, float] = {}
        self.manifest = load_manifest()

    # ---------------------------------------------------------------- politeness
    def _wait(self, host: str) -> None:
        delay = MIN_DELAY_S
        rp = self.robots.get(host)
        if rp is not None:
            cd = rp.crawl_delay(USER_AGENT)
            if cd:
                delay = max(delay, float(cd))
        gap = time.time() - self.last.get(host, 0.0)
        if gap < delay:
            time.sleep(delay - gap)
        self.last[host] = time.time()

    def robots_ok(self, url: str) -> tuple[bool, str]:
        u = urlparse(url)
        host = f"{u.scheme}://{u.netloc}"
        if host not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            self._wait(u.netloc)
            try:
                r = self.session.get(host + "/robots.txt", timeout=TIMEOUT_S)
                if r.status_code in (401, 403):
                    rp.disallow_all = True
                    note = f"robots {r.status_code}"
                elif r.status_code >= 400:
                    rp.allow_all = True
                    note = f"robots {r.status_code} (none)"
                else:
                    rp.parse(r.text.splitlines())
                    note = "robots read"
            except requests.RequestException as e:
                rp.allow_all = True
                note = f"robots unreachable ({type(e).__name__})"
            self.robots[host] = rp
            self.robot_notes[host] = note
        rp = self.robots[host]
        ok = rp.can_fetch(USER_AGENT, url)
        return ok, ("allowed" if ok else "disallowed") + f" ({self.robot_notes.get(host, '')})"

    # ---------------------------------------------------------------- fetch
    def _record(self, rec: dict[str, Any]) -> dict[str, Any]:
        self.manifest[rec["url"]] = rec
        with manifest_path().open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec

    def fetch(self, url: str, geoid: str, via: str = "") -> dict[str, Any]:
        old = self.manifest.get(url)
        if old and old.get("path") and Path(old["path"]).exists():
            return old
        if old and old.get("status") in (401, 403, 404, 410, "robots", "blocked_host"):
            return old
        base = {"url": url, "geoid": geoid, "via": via,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if is_blocked(url):
            return self._record({**base, "status": "blocked_host", "robots": "not asked",
                                 "error": "commercial code host, not fetched by policy"})
        ok, note = self.robots_ok(url)
        if not ok:
            return self._record({**base, "status": "robots", "robots": note, "error": "robots.txt disallows"})
        self._wait(urlparse(url).netloc)
        try:
            r = self.session.get(url, timeout=TIMEOUT_S, stream=True, allow_redirects=True)
        except requests.RequestException as e:
            return self._record({**base, "status": "error", "robots": note, "error": f"{type(e).__name__}: {e}"[:300]})
        if is_blocked(r.url):
            r.close()
            return self._record({**base, "status": "blocked_host", "final_url": r.url, "robots": note,
                                 "error": "redirected to a commercial code host"})
        if r.status_code != 200:
            r.close()
            return self._record({**base, "status": r.status_code, "final_url": r.url, "robots": note,
                                 "error": r.reason})
        data = bytearray()
        for block in r.iter_content(1 << 16):
            data += block
            if len(data) > MAX_BYTES:
                r.close()
                return self._record({**base, "status": "too_big", "final_url": r.url, "robots": note,
                                     "error": f"over {MAX_BYTES} bytes"})
        ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
        sha = hashlib.sha256(data).hexdigest()
        ext = _ext(ctype, r.url, bytes(data[:8]))
        folder = raw_dir(geoid)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{hashlib.sha1(url.encode()).hexdigest()[:12]}{ext}"
        path.write_bytes(bytes(data))
        return self._record({**base, "status": 200, "final_url": r.url, "content_type": ctype,
                             "bytes": len(data), "sha256": sha, "robots": note, "path": str(path),
                             "last_modified": r.headers.get("Last-Modified")})

    def expand(self, url: str, geoid: str, pattern: str | None = None) -> list[dict[str, Any]]:
        """Fetch an index page, then each linked document on the same site that looks like zoning text."""
        rec = self.fetch(url, geoid, via="index")
        if rec.get("status") != 200 or not rec.get("path"):
            return [rec]
        html = Path(rec["path"]).read_text(errors="ignore")
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        host = urlparse(rec.get("final_url") or url).netloc
        seen, links = set(), []
        rx = re.compile(pattern, re.I) if pattern else None
        for a in soup.find_all("a", href=True):
            href = urljoin(rec.get("final_url") or url, a["href"]).split("#")[0]
            text = " ".join(a.get_text(" ").split())
            if urlparse(href).netloc != host or href in seen or not DOC_EXT.search(href):
                continue
            if rx is not None:
                if not (rx.search(text) or rx.search(href)):
                    continue
            elif not (LINK_WORDS.search(text) or LINK_WORDS.search(href)):
                continue
            seen.add(href)
            links.append((href, text))
        out = [rec]
        for href, text in links[:MAX_LINKS]:
            r2 = self.fetch(href, geoid, via=f"index:{url}")
            r2 = {**r2, "link_text": text}
            out.append(r2)
        return out


def _ext(ctype: str, url: str, head: bytes) -> str:
    if head.startswith(b"%PDF"):
        return ".pdf"
    if "html" in ctype:
        return ".html"
    if "wordprocessingml" in ctype or url.lower().endswith(".docx"):
        return ".docx"
    if "msword" in ctype or url.lower().endswith(".doc"):
        return ".doc"
    if "pdf" in ctype:
        return ".pdf"
    return ".bin"


def run(sources: Path) -> None:
    f = Fetcher()
    rows = list(csv.DictReader(sources.open()))
    for i, row in enumerate(rows, 1):
        kind = (row.get("kind") or "doc").strip()
        if kind == "index":
            recs = f.expand(row["url"], row["geoid"], row.get("pattern") or None)
        else:
            recs = [f.fetch(row["url"], row["geoid"])]
        for r in recs:
            print(f"[{i}/{len(rows)}] {row['geoid']} {r.get('status')} {r.get('bytes', '')} {r['url'][:100]}",
                  flush=True)


if __name__ == "__main__":
    run(Path(sys.argv[1]))
