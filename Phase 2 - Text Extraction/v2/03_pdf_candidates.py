#!/usr/bin/env python3
"""Stage 03 -- derive the three PDF-side abstract candidates from cached artifacts.

  grobid     : <abstract> from the TEI cache (stage 01)
  pdfplumber : heading-to-heading regex over first-pages text (direct from PDF; fast)
  docling    : abstract section from the cached markdown (stage 02)

No network, no GROBID server needed. Re-runnable at will; this is the stage you
iterate on. Resumable per source; --force recomputes.

    python 03_pdf_candidates.py --data-store "../Who's Answering CHI"
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

V2_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(V2_DIR))
sys.path.insert(0, str(V2_DIR.parent))  # v1 package: src/

from lib import config  # noqa: E402
from lib.corpus import iter_corpus, CorpusPaper  # noqa: E402
from lib.normalize import clean_stored  # noqa: E402
from lib.records import (load_or_new, save_record, set_candidate,  # noqa: E402
                         candidate_attempted)
from src.abstract import abstract_from_tei, abstract_from_text  # noqa: E402


def cand_grobid(paper: CorpusPaper, tei_root: Path) -> tuple[str, str]:
    tei = tei_root / paper.venue / str(paper.year) / f"{paper.key}.tei.xml"
    if not tei.exists():
        return "", "error:tei_not_cached"  # non-definitive: retried after stage 01
    text = abstract_from_tei(tei.read_text(encoding="utf-8"))
    return (text, "ok") if text else ("", "empty")


def cand_pdfplumber(paper: CorpusPaper) -> tuple[str, str]:
    import pdfplumber
    with pdfplumber.open(paper.pdf_path) as pdf:
        chunks = [page.extract_text() or "" for page in pdf.pages[:2]]
    text = abstract_from_text("\n".join(chunks))
    return (text, "ok") if text else ("", "empty")


_MD_ABSTRACT_RE = re.compile(
    r"(?ims)^#{1,4}\s*Abstract\s*$\n+(.*?)(?=^#{1,4}\s|\Z)")
_MD_INLINE_RE = re.compile(
    r"(?is)\babstract\b[\s:]*\n+(.*?)(?:\n#{1,4}\s|\nCCS\s+Concepts|\nKEYWORDS|\Z)")


def cand_docling(paper: CorpusPaper, docling_root: Path) -> tuple[str, str]:
    md_path = docling_root / paper.venue / str(paper.year) / f"{paper.key}.md"
    if not md_path.exists():
        return "", "error:docling_not_cached"  # retried after stage 02
    md = md_path.read_text(encoding="utf-8")
    m = _MD_ABSTRACT_RE.search(md) or _MD_INLINE_RE.search(md[:20000])
    if not m:
        return "", "empty"
    return m.group(1).strip(), "ok"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    config.add_common_args(p)
    p.add_argument("--force", action="store_true")
    p.add_argument("--gap-only", action="store_true",
                   help="Process only papers NOT yet resolved in the abstracts records.")
    p.add_argument("--skip", nargs="*", default=[], choices=list(config.PDF_SOURCES))
    args = p.parse_args()

    ds = config.data_store(args.data_store)
    _skip_keys = set()
    if args.gap_only:
        from lib.records import resolved_keys
        _skip_keys = resolved_keys(config.sections_dir(ds, 'abstracts'),
                                   args.venue, args.years)
        print(f'--gap-only: skipping {len(_skip_keys)} already-resolved papers', flush=True)
    section_dir = config.sections_dir(ds, "abstracts")
    tei_root, docling_root = config.tei_dir(ds), config.docling_dir(ds)

    extractors = {
        "grobid": lambda pp: cand_grobid(pp, tei_root),
        "pdfplumber": cand_pdfplumber,
        "docling": lambda pp: cand_docling(pp, docling_root),
    }
    stats = {s: {"ok": 0, "empty": 0, "error": 0, "skipped": 0} for s in config.PDF_SOURCES}

    n = 0
    for paper in iter_corpus(config.corpus_root(ds), args.venue, args.years):
        n += 1
        if args.limit and n > args.limit:
            break
        if paper.key in _skip_keys:
            continue
        rec = load_or_new(section_dir, paper)
        dirty = False
        for source in config.PDF_SOURCES:
            if source in args.skip:
                continue
            if not args.force and candidate_attempted(rec, source):
                stats[source]["skipped"] += 1
                continue
            try:
                raw, status = extractors[source](paper)
            except Exception as exc:
                print(f"[{source}] {paper.doi}: {exc}", file=sys.stderr)
                stats[source]["error"] += 1
                continue
            text, repairs = clean_stored(raw, pdf_derived=True)
            if status == "ok" and not text:
                status = "empty"
            set_candidate(rec, source, text, status, repairs, raw_len=len(raw))
            key = status if status in ("ok", "empty") else "error"
            stats[source][key] += 1
            dirty = True
        if dirty:
            save_record(section_dir, paper, rec)
        if n % 500 == 0:
            print(f"...{n} papers", file=sys.stderr)

    print(f"\nProcessed {min(n, args.limit) if args.limit else n} papers")
    for s, c in stats.items():
        print(f"  {s:11s} ok={c['ok']} empty={c['empty']} error={c['error']} skipped={c['skipped']}")


if __name__ == "__main__":
    main()
