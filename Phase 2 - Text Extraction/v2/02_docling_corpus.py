#!/usr/bin/env python3
"""Stage 02 -- run Docling once over the corpus and CACHE its markdown export.

Slow (~1.5 min/paper) but accuracy is the objective: Docling's OCR path recovers
text that broken font maps lose (the ligature failures). Embarrassingly parallel --
run one process per machine/shard on EC2 (see cloud/AWS_RUNBOOK.md in the data store):

    python 02_docling_corpus.py --data-store ... --years 2025          # shard by year
    python 02_docling_corpus.py --data-store ... --shard 0/4           # or modulo shards

Resumable: papers with a cached .md are skipped.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

V2_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(V2_DIR))

from lib import config  # noqa: E402
from lib.corpus import iter_corpus, CorpusPaper  # noqa: E402


def out_paths(root: Path, paper: CorpusPaper) -> tuple[Path, Path]:
    base = root / paper.venue / str(paper.year)
    return base / f"{paper.key}.md", base / f"{paper.key}.meta.json"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    config.add_common_args(p)
    p.add_argument("--force", action="store_true")
    p.add_argument("--gap-only", action="store_true",
                   help="Process only papers NOT yet resolved in the abstracts records.")
    p.add_argument("--shard", default=None, metavar="K/N",
                   help="Process only papers where index %% N == K (e.g. 0/4).")
    p.add_argument("--max-pages", type=int, default=0,
                   help="Convert only the first N pages (0 = all). Abstracts only need ~2.")
    args = p.parse_args()

    shard_k = shard_n = None
    if args.shard:
        shard_k, shard_n = (int(x) for x in args.shard.split("/"))

    ds = config.data_store(args.data_store)
    _skip_keys = set()
    if args.gap_only:
        from lib.records import resolved_keys
        _skip_keys = resolved_keys(config.sections_dir(ds, 'abstracts'),
                                   args.venue, args.years)
        print(f'--gap-only: skipping {len(_skip_keys)} already-resolved papers', flush=True)
    root = config.docling_dir(ds)

    # Lazy import: heavy. Fail early with a clear message.
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
    except ImportError:
        raise SystemExit("docling not installed: pip install docling")

    opts = PdfPipelineOptions()
    opts.do_ocr = True  # the whole point: recover broken text layers
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})

    done = failed = skipped = idx = 0
    for n, paper in enumerate(iter_corpus(config.corpus_root(ds), args.venue, args.years), 1):
        if args.limit and n > args.limit:
            break
        if paper.key in _skip_keys:
            continue
        if shard_n is not None:
            if idx % shard_n != shard_k:
                idx += 1
                continue
            idx += 1
        md_path, meta_path = out_paths(root, paper)
        if not args.force and md_path.exists() and md_path.stat().st_size > 0:
            skipped += 1
            continue
        t0 = time.time()
        try:
            kwargs = {"max_num_pages": args.max_pages} if args.max_pages else {}
            result = converter.convert(str(paper.pdf_path), **kwargs)
            md = result.document.export_to_markdown()
            md_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = md_path.with_suffix(".tmp")
            tmp.write_text(md, encoding="utf-8")
            tmp.replace(md_path)
            meta_path.write_text(json.dumps({
                "doi": paper.doi, "secs": round(time.time() - t0, 1),
                "status": str(result.status), "chars": len(md)}), encoding="utf-8")
            done += 1
        except Exception as exc:
            print(f"[docling] {paper.doi}: {exc}", file=sys.stderr)
            failed += 1
        if (done + failed) % 25 == 0:
            print(f"...converted={done} failed={failed} skipped={skipped}", file=sys.stderr)

    print(f"\nDocling cache: converted={done} failed={failed} previously_cached={skipped}")


if __name__ == "__main__":
    main()
