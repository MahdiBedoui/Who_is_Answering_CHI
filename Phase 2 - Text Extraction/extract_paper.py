#!/usr/bin/env python3
"""Single-PDF debug CLI for Stage 2 extraction.

A thin wrapper over the production library (`src/`): it runs ONE PDF through the
exact same code path as the corpus batch (`src.extract.extract_record` → GROBID),
so what you see here is what the batch would produce. If GROBID is unreachable it
falls back to the pdfplumber heuristics in `src.pdf_fallback` to fill in
title/abstract/methods on a best-effort basis (debug only — the production batch
never uses the fallback).

Usage:
    python "Phase 2 - Text Extraction/extract_paper.py" path/to/paper.pdf
    python "Phase 2 - Text Extraction/extract_paper.py" paper.pdf --output rec.json
    python "Phase 2 - Text Extraction/extract_paper.py" paper.pdf --grobid-url http://localhost:8070
    python "Phase 2 - Text Extraction/extract_paper.py" paper.pdf --no-fallback
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# src/ lives alongside this script (Phase 2 - Text Extraction/src/); put this
# script's own directory on the path so `from src.X` resolves regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.extract import extract_record  # noqa: E402
from src import pdf_fallback  # noqa: E402


def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)


def extract_one(
    pdf_path: Path,
    grobid_url: str = "http://localhost:8070",
    openalex_mailto: str = "",
    use_fallback: bool = True,
) -> dict:
    """Extract a single PDF via the production path, with optional pdfplumber rescue."""
    record = extract_record(pdf_path, grobid_url=grobid_url, openalex_mailto=openalex_mailto)

    # GROBID failed for this PDF: try the heuristic parser to fill empty fields.
    if use_fallback and not record.get("grobid_ok"):
        try:
            fb = pdf_fallback.extract_with_pdfplumber(pdf_path)
        except Exception as exc:  # noqa: BLE001 -- fallback is best-effort
            log(f"[fallback] ERROR: pdfplumber extraction failed: {exc}")
            fb = {}
        if fb:
            for key in ("title", "abstract", "methods", "venue"):
                if not record.get(key) and fb.get(key):
                    record[key] = fb[key]
            if not record.get("year") and fb.get("year"):
                record["year"] = fb["year"]
            if not record.get("doi") and fb.get("doi"):
                record["doi"] = fb["doi"]
            record.setdefault("extra", {})["fallback"] = "pdfplumber"

    return record


def parse_args(argv=None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(
        description="Extract one ACM SIGCHI paper PDF via the Stage 2 library (debug tool).")
    p.add_argument("pdf_path", type=str, help="Path to one PDF file.")
    p.add_argument("--output", type=str, default=None,
                   help="Write JSON to this file (default: stdout).")
    p.add_argument("--grobid-url", type=str, default="http://localhost:8070",
                   help="GROBID endpoint (default: http://localhost:8070).")
    p.add_argument("--openalex-mailto", type=str, default="",
                   help="Contact email for the OpenAlex polite pool (optional).")
    p.add_argument("--no-fallback", action="store_true",
                   help="Disable the pdfplumber fallback when GROBID is unavailable.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    """Program entry point; returns a process exit code."""
    args = parse_args(argv)
    pdf_path = Path(args.pdf_path)
    if not pdf_path.is_file():
        log(f"ERROR: PDF not found: {pdf_path}")
        return 1

    record = extract_one(
        pdf_path,
        grobid_url=args.grobid_url,
        openalex_mailto=args.openalex_mailto,
        use_fallback=not args.no_fallback,
    )
    payload = json.dumps(record, ensure_ascii=False, indent=2, default=str)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        log(f"[done] wrote JSON to {out_path}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
