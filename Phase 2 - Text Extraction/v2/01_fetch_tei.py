#!/usr/bin/env python3
"""Stage 01 -- run GROBID once over the corpus and CACHE the raw TEI XML.

All later section passes (abstract, methods, discussion) re-parse this cache;
PDFs are never sent to GROBID again. Resumable: existing non-empty TEI is skipped.

Requires a running GROBID (docker-compose.yml at repo root, or the EC2 runbook).

    python 01_fetch_tei.py --data-store "../Who's Answering CHI" --workers 8
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

V2_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(V2_DIR))
sys.path.insert(0, str(V2_DIR.parent))  # v1 package: src/

from lib import config  # noqa: E402
from lib.corpus import iter_corpus, CorpusPaper  # noqa: E402
from src.grobid import process_fulltext  # noqa: E402  (reuse v1 client)


def tei_path(tei_root: Path, paper: CorpusPaper) -> Path:
    return tei_root / paper.venue / str(paper.year) / f"{paper.key}.tei.xml"


def process_one(paper: CorpusPaper, tei_root: Path, grobid_url: str) -> str:
    out = tei_path(tei_root, paper)
    tei = process_fulltext(paper.pdf_path, grobid_url=grobid_url)
    if not tei:
        return "fail"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(tei, encoding="utf-8")
    tmp.replace(out)
    return "ok"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    config.add_common_args(p)
    p.add_argument("--grobid-url", default="http://localhost:8070")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--force", action="store_true")
    p.add_argument("--gap-only", action="store_true",
                   help="Process only papers NOT yet resolved in the abstracts records.")
    args = p.parse_args()

    ds = config.data_store(args.data_store)
    _skip_keys = set()
    if args.gap_only:
        from lib.records import resolved_keys
        _skip_keys = resolved_keys(config.sections_dir(ds, 'abstracts'),
                                   args.venue, args.years)
        print(f'--gap-only: skipping {len(_skip_keys)} already-resolved papers', flush=True)
    tei_root = config.tei_dir(ds)

    todo, skipped = [], 0
    for n, paper in enumerate(iter_corpus(config.corpus_root(ds), args.venue, args.years), 1):
        if args.limit and n > args.limit:
            break
        if paper.key in _skip_keys:
            continue
        out = tei_path(tei_root, paper)
        if not args.force and out.exists() and out.stat().st_size > 0:
            skipped += 1
            continue
        todo.append(paper)

    print(f"{len(todo)} to fetch, {skipped} cached", file=sys.stderr)
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_one, pp, tei_root, args.grobid_url): pp for pp in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            paper = futures[fut]
            try:
                res = fut.result()
            except Exception as exc:
                print(f"[tei] {paper.doi}: {exc}", file=sys.stderr)
                res = "fail"
            ok += res == "ok"
            fail += res != "ok"
            if i % 100 == 0:
                print(f"...{i}/{len(todo)} (ok={ok} fail={fail})", file=sys.stderr)

    print(f"\nTEI cache: ok={ok} fail={fail} previously_cached={skipped}")
    if fail:
        print("Failures are retried automatically on the next run.")


if __name__ == "__main__":
    main()
