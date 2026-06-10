#!/usr/bin/env python3
"""Experiment: compare current abstract vs. Abstract->CCS regex span (no pipeline change).

For every record where OpenAlex did NOT supply the abstract (source = grobid /
regex / none), re-read the local PDF with pdfplumber, run the existing
Abstract->CCS regex (src.abstract.abstract_from_text), and write a side-by-side
CSV so you can judge whether the regex span beats what's currently stored.

Runs entirely locally -- no AWS, no GROBID. Touches NOTHING in the dataset; only
writes the comparison CSV. If the span clearly wins, we then wire it into the
pipeline and re-extract just the affected papers.

Usage:
    pip install pdfplumber
    python scripts/fix_abstracts_experiment.py --input-dir data\\extracted_cloud \
        --pdf-root "sigchi\\VERIFIED COUNT" --out abstract_fix_compare.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.abstract import abstract_from_text, _valid  # noqa: E402

# We target every paper where OpenAlex did not provide the abstract.
NON_OPENALEX = {"grobid", "regex", "none", "", None}


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


def first_pages_text(pdf_path: Path, pages: int = 2) -> str:
    """Extract text from the first few pages of a PDF (where the abstract lives)."""
    import pdfplumber  # imported lazily so --help works without the dep
    out = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages[:pages]:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Compare current abstract vs Abstract->CCS regex span.")
    p.add_argument("--input-dir", default="data/extracted_cloud")
    p.add_argument("--pdf-root", default=r"sigchi\VERIFIED COUNT",
                   help="Local corpus root holding the PDFs.")
    p.add_argument("--out", default="abstract_fix_compare.csv")
    p.add_argument("--limit", type=int, default=0, help="Process at most N (0 = all).")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Build the current-vs-span comparison CSV for non-OpenAlex abstracts."""
    args = parse_args(argv)
    root = Path(args.input_dir)
    files = [p for p in root.rglob("*.json") if not p.name.startswith("_")]

    targets = []
    for fp in files:
        try:
            rec = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if rec.get("abstract_source") in NON_OPENALEX:
            targets.append(rec)
    if args.limit:
        targets = targets[: args.limit]
    log(f"[fix-abs] {len(targets)} non-OpenAlex abstract papers to compare")

    rows = []
    n_span_valid = n_span_recovers_empty = n_span_longer = n_pdf_missing = 0
    for i, rec in enumerate(targets, 1):
        pdf = Path(remap_pdf(rec.get("source_pdf_path", ""), args.pdf_root))
        if not pdf.is_file():
            n_pdf_missing += 1
            continue
        try:
            text = first_pages_text(pdf)
            span = abstract_from_text(text)
        except Exception as exc:  # noqa: BLE001
            log(f"  [{i}] PDF read failed {pdf.name}: {exc}")
            continue

        current = (rec.get("abstract") or "").strip()
        span_ok = _valid(span)
        if span_ok:
            n_span_valid += 1
        if not current and span_ok:
            n_span_recovers_empty += 1
        if span_ok and len(span) > len(current) + 50:
            n_span_longer += 1

        rows.append({
            "doi": rec.get("doi", ""),
            "year": rec.get("year", ""),
            "current_source": rec.get("abstract_source") or "none",
            "current_len": len(current),
            "span_len": len(span),
            "span_valid": span_ok,
            "current_abstract": current,
            "regex_span_abstract": span,
        })
        if i % 50 == 0:
            log(f"  processed {i}/{len(targets)}")

    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["doi"])
        w.writeheader()
        w.writerows(rows)

    log(f"\n[fix-abs] DONE -> {args.out}")
    log(f"  papers compared              : {len(rows)}")
    log(f"  PDFs missing (skipped)       : {n_pdf_missing}")
    log(f"  regex span is valid abstract : {n_span_valid}")
    log(f"  span RECOVERS an empty one   : {n_span_recovers_empty}")
    log(f"  span notably longer than cur : {n_span_longer}")
    log("  -> open the CSV and read: is the span a real, complete abstract vs the current?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
