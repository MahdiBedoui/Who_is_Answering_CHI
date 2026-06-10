#!/usr/bin/env python3
"""Stage 00 -- fetch publisher-side abstract candidates: OpenAlex, Crossref, Semantic Scholar.

Resumable: a paper/source is skipped once it has a definitive answer (ok / not_found /
empty). Transient HTTP errors are retried on the next run. Use --force to refetch all.

    python 00_fetch_api_candidates.py --data-store "../Who's Answering CHI" [--limit 20]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import requests

V2_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(V2_DIR))

from lib import config  # noqa: E402
from lib.corpus import iter_corpus  # noqa: E402
from lib.normalize import clean_stored  # noqa: E402
from lib.records import (load_or_new, save_record, set_candidate,  # noqa: E402
                         candidate_attempted)

MAILTO = "bedouimehdi39@gmail.com"
UA = {"User-Agent": f"WhosAnsweringCHI/2.0 (mailto:{MAILTO})"}
_TAG_RE = re.compile(r"<[^>]+>")


def _get(url: str, params: dict | None = None, timeout: int = 30):
    return requests.get(url, params=params, headers=UA, timeout=timeout)


def fetch_openalex(doi: str) -> tuple[str, str]:
    r = _get(f"https://api.openalex.org/works/https://doi.org/{doi}",
             params={"select": "abstract_inverted_index", "mailto": MAILTO})
    if r.status_code == 404:
        return "", "not_found"
    r.raise_for_status()
    inv = r.json().get("abstract_inverted_index")
    if not inv:
        return "", "empty"
    pos = sorted((i, w) for w, idxs in inv.items() for i in idxs)
    return " ".join(w for _, w in pos).strip(), "ok"


def fetch_crossref(doi: str) -> tuple[str, str]:
    r = _get(f"https://api.crossref.org/works/{doi}", params={"mailto": MAILTO})
    if r.status_code == 404:
        return "", "not_found"
    r.raise_for_status()
    abstract = r.json().get("message", {}).get("abstract", "")
    if not abstract:
        return "", "empty"
    return _TAG_RE.sub(" ", abstract).strip(), "ok"  # strip JATS markup


def fetch_semanticscholar(doi: str, api_key: str | None) -> tuple[str, str]:
    headers = dict(UA)
    if api_key:
        headers["x-api-key"] = api_key
    r = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                     params={"fields": "abstract"}, headers=headers, timeout=30)
    if r.status_code == 404:
        return "", "not_found"
    if r.status_code == 429:
        raise requests.exceptions.RetryError("S2 rate limited")
    r.raise_for_status()
    abstract = r.json().get("abstract") or ""
    return (abstract.strip(), "ok") if abstract.strip() else ("", "empty")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    config.add_common_args(p)
    p.add_argument("--force", action="store_true", help="Refetch even definitive answers.")
    p.add_argument("--sleep", type=float, default=0.4, help="Seconds between API calls.")
    p.add_argument("--s2-api-key", default=None, help="Semantic Scholar API key (optional).")
    p.add_argument("--skip", nargs="*", default=[], choices=list(config.API_SOURCES),
                   help="Sources to skip this run.")
    args = p.parse_args()

    ds = config.data_store(args.data_store)
    section_dir = config.sections_dir(ds, "abstracts")
    print(f"Data store : {ds}", flush=True)
    print(f"Corpus     : {config.corpus_root(ds)} ({args.venue} {args.years})", flush=True)
    print(f"Records    : {section_dir}", flush=True)
    print("Fetching (resumable; Ctrl+C any time, rerun to continue)...", flush=True)
    fetchers = {
        "openalex": lambda doi: fetch_openalex(doi),
        "crossref": lambda doi: fetch_crossref(doi),
        "semanticscholar": lambda doi: fetch_semanticscholar(doi, args.s2_api_key),
    }

    stats = {s: {"ok": 0, "not_found": 0, "empty": 0, "error": 0, "skipped": 0}
             for s in config.API_SOURCES}
    n = 0
    for paper in iter_corpus(config.corpus_root(ds), args.venue, args.years):
        n += 1
        if args.limit and n > args.limit:
            break
        rec = load_or_new(section_dir, paper)
        dirty = False
        for source in config.API_SOURCES:
            if source in args.skip:
                continue
            if not args.force and candidate_attempted(rec, source):
                stats[source]["skipped"] += 1
                continue
            try:
                raw, status = fetchers[source](paper.doi)
            except Exception as exc:  # transient -> retried next run
                print(f"[{source}] {paper.doi}: {exc}", file=sys.stderr)
                stats[source]["error"] += 1
                continue
            text, repairs = clean_stored(raw, pdf_derived=False)
            if status == "ok" and not text:
                status = "empty"
            set_candidate(rec, source, text, status, repairs, raw_len=len(raw))
            stats[source][status if status in ("ok", "not_found", "empty") else "error"] += 1
            dirty = True
            time.sleep(args.sleep)
        if dirty:
            save_record(section_dir, paper, rec)
        if n % 25 == 0:
            oa = stats["openalex"]
            print(f"  [{n}] {paper.year} {paper.doi}  "
                  f"(openalex ok={oa['ok']} empty={oa['empty']} skipped={oa['skipped']})",
                  flush=True)

    print(f"\nProcessed {min(n, args.limit) if args.limit else n} papers")
    for s, c in stats.items():
        print(f"  {s:16s} ok={c['ok']} not_found={c['not_found']} empty={c['empty']} "
              f"error={c['error']} skipped={c['skipped']}")


if __name__ == "__main__":
    main()
