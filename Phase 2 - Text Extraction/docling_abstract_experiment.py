#!/usr/bin/env python3
"""Experiment: extract abstracts with Docling and compare to what we have.

For a sample of papers (default: those where OpenAlex did NOT supply the
abstract), convert the PDF with Docling, then pull the abstract two ways:
  (A) structural -- the text under the "Abstract" section heading in Docling's
      reading-order Markdown;
  (B) span       -- the Abstract->CCS regex applied to that clean Markdown.
Writes a side-by-side CSV vs. the currently stored abstract so you can judge
Docling's accuracy. Changes NOTHING in the dataset.

Docling gives layout-aware, reading-order-correct text (no column interleaving),
which is its main advantage over pdfplumber for this task.

Setup:
    pip install docling

Usage:
    python scripts/docling_abstract_experiment.py \
        --input-dir data\\extracted_cloud --pdf-root "sigchi\\VERIFIED COUNT" \
        --bucket non-openalex --n 10 --out docling_abstracts.csv

  --bucket non-openalex : papers OpenAlex couldn't cover (the ~884) [default]
  --bucket grobid       : the 664 GROBID-fallback abstracts
  --bucket any          : a random spread (sanity vs OpenAlex's good ones)
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.abstract import abstract_from_text, _valid  # noqa: E402

NON_OPENALEX = {"grobid", "regex", "none", "", None}

# Markdown heading line, e.g. "## Abstract" or "# 1 Introduction".
_HEADING = re.compile(r"^\s*#{1,6}\s+(.*\S)\s*$")
_ABSTRACT_HEAD = re.compile(r"^\s*(?:\d+\s*)?abstract\b", re.IGNORECASE)


def log(msg: str) -> None:
    """Print progress to stderr."""
    print(msg, file=sys.stderr, flush=True)


def remap_pdf(stored: str, pdf_root: str) -> str:
    """Remap a stored (cloud) PDF path onto a local corpus root; keep venue/year/type/file."""
    if not stored:
        return ""
    parts = stored.replace("\\", "/").split("/")
    for i, seg in enumerate(parts):
        if seg.isdigit() and len(seg) == 4 and i > 0:
            return str(Path(pdf_root) / Path("/".join(parts[i - 1:])))
    return stored


def abstract_from_markdown_structure(md: str) -> str:
    """Return the text under the first 'Abstract' heading, up to the next heading."""
    lines = md.splitlines()
    grabbing = False
    out: List[str] = []
    for line in lines:
        h = _HEADING.match(line)
        if h:
            if grabbing:                       # hit the next heading -> stop
                break
            if _ABSTRACT_HEAD.match(h.group(1)):
                grabbing = True
            continue
        if grabbing:
            out.append(line)
    text = re.sub(r"\s*\n\s*", " ", "\n".join(out))
    return re.sub(r"[ \t]+", " ", text).strip()


_CONVERTER = None


def _get_converter():
    """Build a Docling converter ONCE with OCR disabled (ACM PDFs are born-digital)."""
    global _CONVERTER
    if _CONVERTER is None:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import InputFormat
        opts = PdfPipelineOptions()
        opts.do_ocr = False            # huge speedup: no OCR on digital PDFs
        opts.do_table_structure = False  # we don't need table parsing for abstract/methods
        _CONVERTER = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
    return _CONVERTER


def docling_markdown(pdf_path: Path) -> str:
    """Convert a PDF to reading-order Markdown with Docling (OCR off, converter reused)."""
    result = _get_converter().convert(str(pdf_path))
    return result.document.export_to_markdown()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Docling abstract extraction experiment.")
    p.add_argument("--input-dir", default="data/extracted_cloud")
    p.add_argument("--pdf-root", default=r"sigchi\VERIFIED COUNT")
    p.add_argument("--bucket", choices=["non-openalex", "grobid", "any"], default="non-openalex")
    p.add_argument("--n", type=int, default=10, help="Sample size (Docling is slow; keep small).")
    p.add_argument("--out", default="docling_abstracts.csv")
    return p.parse_args(argv)


def select(records: List[dict], bucket: str, n: int) -> List[dict]:
    """Pick the sample of records to test."""
    if bucket == "non-openalex":
        pool = [r for r in records if r.get("abstract_source") in NON_OPENALEX]
    elif bucket == "grobid":
        pool = [r for r in records if r.get("abstract_source") == "grobid"]
    else:
        pool = list(records)
    random.seed(42)
    random.shuffle(pool)
    return pool[:n]


def main(argv: Optional[List[str]] = None) -> int:
    """Run Docling on a sample and write a current-vs-Docling comparison CSV."""
    args = parse_args(argv)
    root = Path(args.input_dir)
    records = []
    for fp in root.rglob("*.json"):
        if fp.name.startswith("_"):
            continue
        try:
            records.append(json.loads(fp.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue

    sample = select(records, args.bucket, args.n)
    log(f"[docling] bucket={args.bucket} size={len(sample)} (Docling is slow -- be patient)")

    rows = []
    n_struct_valid = n_span_valid = n_recovers_empty = 0
    for i, rec in enumerate(sample, 1):
        pdf = Path(remap_pdf(rec.get("source_pdf_path", ""), args.pdf_root))
        if not pdf.is_file():
            log(f"  [{i}] PDF missing: {pdf}")
            continue
        t0 = time.time()
        try:
            md = docling_markdown(pdf)
        except Exception as exc:  # noqa: BLE001
            log(f"  [{i}] Docling failed on {pdf.name}: {exc}")
            continue
        secs = time.time() - t0

        struct = abstract_from_markdown_structure(md)
        span = abstract_from_text(md)
        current = (rec.get("abstract") or "").strip()

        if _valid(struct):
            n_struct_valid += 1
        if _valid(span):
            n_span_valid += 1
        if not current and (_valid(struct) or _valid(span)):
            n_recovers_empty += 1

        rows.append({
            "doi": rec.get("doi", ""),
            "year": rec.get("year", ""),
            "current_source": rec.get("abstract_source") or "none",
            "current_len": len(current),
            "docling_struct_len": len(struct),
            "docling_span_len": len(span),
            "secs": round(secs, 1),
            "current_abstract": current,
            "docling_struct_abstract": struct,
            "docling_span_abstract": span,
        })
        log(f"  [{i}/{len(sample)}] {rec.get('doi','')}  struct={len(struct)} "
            f"span={len(span)} current={len(current)}  ({secs:.1f}s)")

    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["doi"])
        w.writeheader()
        w.writerows(rows)

    log(f"\n[docling] DONE -> {args.out}")
    log(f"  papers processed            : {len(rows)}")
    log(f"  Docling STRUCTURE valid abs : {n_struct_valid}")
    log(f"  Docling SPAN valid abs      : {n_span_valid}")
    log(f"  recovers a currently-empty  : {n_recovers_empty}")
    log("  -> open CSV: compare docling_struct_abstract / docling_span_abstract vs current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
