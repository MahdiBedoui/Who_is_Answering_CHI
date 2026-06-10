#!/usr/bin/env python3
"""Stage 00 -- fetch publisher-side abstract candidates: OpenAlex, Crossref, Semantic Scholar.

Parallel (--workers, default 6) with per-API rate limiting, so we go as fast as each
API politely allows. Resumable: a paper/source is skipped once it has a definitive
answer (ok / not_found / empty); transient errors retry on the next run. --force refetches.

Semantic Scholar without an API key is limited to ~1 request/second and is therefore
the pacing source. Options:
  --s2-api-key KEY        (free key: https://www.semanticscholar.org/product/api)
  --skip semanticscholar  (run fast on OpenAlex+Crossref now, backfill S2 later)

    py 00_fetch_api_candidates.py --data-store "C:\\...\\Who's Answering CHI"
"""
from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


class RateLimiter:
    """Global min-interval between calls to one API, shared across worker threads."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                if now >= self._next:
                    self._next = now + self.min_interval
                    return
                delay = self._next - now
            time.sleep(min(delay, 0.5))


def fetch_openalex(doi: str) -> tuple[str, str]:
    r = requests.get(f"https://api.openalex.org/works/https://doi.org/{doi}",
                     params={"select": "abstract_inverted_index", "mailto": MAILTO},
                     headers=UA, timeout=30)
    if r.status_code == 404:
        return "", "not_found"
    r.raise_for_status()
    inv = r.json().get("abstract_inverted_index")
    if not inv:
        return "", "empty"
    pos = sorted((i, w) for w, idxs in inv.items() for i in idxs)
    return " ".join(w for _, w in pos).strip(), "ok"


def fetch_crossref(doi: str) -> tuple[str, str]:
    r = requests.get(f"https://api.crossref.org/works/{doi}",
                     params={"mailto": MAILTO}, headers=UA, timeout=30)
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
        raise requests.exceptions.RetryError("S2 rate limited (429)")
    r.raise_for_status()
    abstract = r.json().get("abstract") or ""
    return (abstract.strip(), "ok") if abstract.strip() else ("", "empty")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    config.add_common_args(p)
    p.add_argument("--force", action="store_true", help="Refetch even definitive answers.")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--s2-api-key", default=None, help="Semantic Scholar API key (optional).")
    p.add_argument("--skip", nargs="*", default=[], choices=list(config.API_SOURCES),
                   help="Sources to skip this run.")
    args = p.parse_args()

    ds = config.data_store(args.data_store)
    section_dir = config.sections_dir(ds, "abstracts")
    print(f"Data store : {ds}", flush=True)
    print(f"Corpus     : {config.corpus_root(ds)} ({args.venue} {args.years})", flush=True)
    print(f"Records    : {section_dir}", flush=True)

    limiters = {
        "openalex": RateLimiter(0.12),                                  # ~8 rps (polite pool)
        "crossref": RateLimiter(0.06),                                  # ~16 rps
        "semanticscholar": RateLimiter(0.12 if args.s2_api_key else 1.05),  # 1 rps unauth
    }
    fetchers = {
        "openalex": fetch_openalex,
        "crossref": fetch_crossref,
        "semanticscholar": lambda doi: fetch_semanticscholar(doi, args.s2_api_key),
    }
    active = [s for s in config.API_SOURCES if s not in args.skip]
    if "semanticscholar" in active and not args.s2_api_key:
        print("NOTE: semanticscholar without --s2-api-key is capped at ~1 paper/sec "
              "and paces the whole run. Use --skip semanticscholar for a fast first pass.",
              flush=True)

    stats = {s: {"ok": 0, "not_found": 0, "empty": 0, "error": 0, "skipped": 0}
             for s in config.API_SOURCES}
    stats_lock = threading.Lock()
    consec_429 = {s: 0 for s in config.API_SOURCES}
    MAX_CONSEC_429 = 25  # after this many consecutive 429s, drop the source for this run
    done = 0

    def process(paper):
        rec = load_or_new(section_dir, paper)
        dirty = False
        for source in active:
            if not args.force and candidate_attempted(rec, source):
                with stats_lock:
                    stats[source]["skipped"] += 1
                continue
            limiters[source].wait()
            try:
                raw, status = fetchers[source](paper.doi)
            except Exception as exc:  # transient -> retried next run
                with stats_lock:
                    stats[source]["error"] += 1
                    if "429" in str(exc):
                        consec_429[source] += 1
                        if consec_429[source] == MAX_CONSEC_429 and source in active:
                            active.remove(source)
                            print(f"NOTE: {source} rate-limited {MAX_CONSEC_429}x in a row "
                                  "-- disabled for the rest of this run. Its papers stay "
                                  "pending; rerun later (ideally with an API key) to backfill.",
                                  flush=True)
                    else:
                        print(f"  [{source}] {paper.doi}: {exc}", file=sys.stderr, flush=True)
                continue
            text, repairs = clean_stored(raw, pdf_derived=False)
            if status == "ok" and not text:
                status = "empty"
            set_candidate(rec, source, text, status, repairs, raw_len=len(raw))
            with stats_lock:
                consec_429[source] = 0
                key = status if status in ("ok", "not_found", "empty") else "error"
                stats[source][key] += 1
            dirty = True
        if dirty:
            save_record(section_dir, paper, rec)
        return paper

    papers = []
    for n, paper in enumerate(iter_corpus(config.corpus_root(ds), args.venue, args.years), 1):
        if args.limit and n > args.limit:
            break
        papers.append(paper)
    print(f"Queued     : {len(papers)} papers, {args.workers} workers, sources={active}",
          flush=True)
    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(process, pp) for pp in papers]
        for fut in as_completed(futures):
            paper = fut.result()
            done += 1
            if done % 25 == 0:
                rate = done / (time.monotonic() - t0)
                eta_min = (len(papers) - done) / rate / 60 if rate else 0
                with stats_lock:
                    oa = dict(stats["openalex"])
                print(f"  [{done}/{len(papers)}] {paper.year} {paper.doi}  "
                      f"{rate:.1f} papers/s  ETA {eta_min:.0f} min  "
                      f"(openalex ok={oa['ok']} skipped={oa['skipped']})", flush=True)

    print(f"\nProcessed {len(papers)} papers in {(time.monotonic() - t0) / 60:.1f} min")
    for s, c in stats.items():
        print(f"  {s:16s} ok={c['ok']} not_found={c['not_found']} empty={c['empty']} "
              f"error={c['error']} skipped={c['skipped']}")


if __name__ == "__main__":
    main()
