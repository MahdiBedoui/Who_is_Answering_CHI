#!/usr/bin/env python3
"""Review extracted abstracts by source, for manual QA.

Filters extracted records by `abstract_source` (e.g. the GROBID-fallback
abstracts you want to sanity-check) and lays each one out readably: DOI, title,
the abstract text, and the source PDF path so you can cross-check against the
paper. Optionally writes the same to a file for sharing.

Usage:
    python scripts/review_abstracts.py --source grobid
    python scripts/review_abstracts.py --source grobid --out grobid_abstracts.txt
    python scripts/review_abstracts.py --source none           # empty abstracts
    python scripts/review_abstracts.py --source grobid --limit 20
    python scripts/review_abstracts.py --source grobid --csv grobid_abstracts.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import List, Optional, TextIO

VALID_SOURCES = {"grobid", "openalex", "regex", "none", "any"}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Review extracted abstracts by source.")
    p.add_argument("--input-dir", default="data/extracted_cloud", help="Extraction output root.")
    p.add_argument("--source", default="grobid",
                   help="abstract_source to review: grobid | openalex | regex | none | any.")
    p.add_argument("--venue", default=None, help="Filter to one venue.")
    p.add_argument("--year", default=None, help="Filter to one year.")
    p.add_argument("--limit", type=int, default=0, help="Show at most N (0 = all).")
    p.add_argument("--out", default=None, help="Also write the readable layout to this text file.")
    p.add_argument("--csv", default=None, help="Write a CSV (doi,title,abstract,pdf) for review.")
    p.add_argument("--pdf-root", default=r"sigchi\VERIFIED COUNT",
                   help="Local corpus root to remap the stored (cloud) PDF path onto. The stored "
                        "path's prefix up to and including 'CHI/' is replaced with "
                        "<pdf-root>\\CHI\\ so the PDF link works on this machine.")
    return p.parse_args(argv)


def local_pdf_path(stored: str, pdf_root: str) -> str:
    """Remap a cloud-stored PDF path to the local corpus, preserving <year>/<type>/<file>."""
    if not stored:
        return ""
    # Normalize separators, then keep everything from the venue folder onward.
    norm = stored.replace("\\", "/")
    parts = norm.split("/")
    # Find the venue marker (the segment right before the 4-digit year), default to "CHI".
    for i, seg in enumerate(parts):
        if seg.isdigit() and len(seg) == 4 and i > 0:
            tail = "/".join(parts[i - 1:])          # e.g. CHI/2022/Research Article/file.pdf
            return str(Path(pdf_root) / Path(tail))
    return stored  # fall back to stored path if we can't parse it


def matches(rec: dict, source: str) -> bool:
    """Does this record's abstract_source match the requested filter?"""
    src = rec.get("abstract_source") or "none"
    if source == "any":
        return True
    if source == "none":
        return src in ("", "none") or not (rec.get("abstract") or "").strip()
    return src == source


def emit(rec: dict, idx: int, out: Optional[TextIO], pdf_root: str) -> None:
    """Print one record's review block to stdout and optionally a file."""
    doi = rec.get("doi", "")
    title = rec.get("title", "") or "(no title)"
    abstract = (rec.get("abstract") or "").strip() or "(empty)"
    src = rec.get("abstract_source") or "none"
    pdf = local_pdf_path(rec.get("source_pdf_path", ""), pdf_root)
    block = (
        f"[{idx}] {doi}  | source={src}\n"
        f"    TITLE: {title}\n"
        f"    ABSTRACT: {abstract}\n"
        f"    PDF: {pdf}\n"
        f"{'-' * 70}"
    )
    print(block)
    if out is not None:
        out.write(block + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    """Filter records by abstract source and lay them out for manual review."""
    args = parse_args(argv)
    if args.source not in VALID_SOURCES:
        print(f"--source must be one of {sorted(VALID_SOURCES)}")
        return 1

    root = Path(args.input_dir)
    files = [p for p in root.rglob("*.json") if not p.name.startswith("_")]
    if args.venue:
        files = [p for p in files if f"/{args.venue}/" in p.as_posix()]
    if args.year:
        files = [p for p in files if f"/{args.year}/" in p.as_posix()]

    selected: List[dict] = []
    for fp in sorted(files):
        try:
            rec = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if matches(rec, args.source):
            selected.append(rec)

    if args.limit:
        selected = selected[: args.limit]

    out_fh = open(args.out, "w", encoding="utf-8") if args.out else None
    print(f"\n=== {len(selected)} record(s) with abstract source = '{args.source}' ===\n")
    if out_fh:
        out_fh.write(f"=== {len(selected)} record(s) with abstract source = '{args.source}' ===\n\n")
    for i, rec in enumerate(selected, 1):
        emit(rec, i, out_fh, args.pdf_root)
    if out_fh:
        out_fh.close()
        print(f"\n[written] readable layout -> {args.out}")

    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["doi", "title", "abstract_source", "abstract", "pdf"])
            for rec in selected:
                w.writerow([
                    rec.get("doi", ""), rec.get("title", ""),
                    rec.get("abstract_source") or "none",
                    (rec.get("abstract") or "").strip(),
                    local_pdf_path(rec.get("source_pdf_path", ""), args.pdf_root),
                ])
        print(f"[written] CSV -> {args.csv}")

    print(f"\nTotal: {len(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
