#!/usr/bin/env python3
"""Layer-1 QA audit over extracted JSON records.

Scans an extraction output tree and prints a health report: completeness,
GROBID success, abstract sources, methods presence/length, and the breakdown of
quality flags (needs_llm_methods + each methods_quality_flags reason). This is
the cheap, run-on-everything pass -- it surfaces detectable failures and your
LLM-escalation queue. It does NOT measure semantic correctness (that's the gold
set).

Usage:
    python scripts/qa_report.py --input-dir data/extracted_cloud
    python scripts/qa_report.py --input-dir data/extracted_cloud --venue CHI --year 2024
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import List, Optional

# Below this many chars, a methods field is suspiciously short / likely broken.
SHORT_METHODS = 400


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="QA audit over extracted JSON records.")
    p.add_argument("--input-dir", default="data/extracted_cloud", help="Extraction output root.")
    p.add_argument("--venue", default=None, help="Filter to one venue (path contains /<venue>/).")
    p.add_argument("--year", default=None, help="Filter to one year.")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Scan records and print the QA health report."""
    args = parse_args(argv)
    root = Path(args.input_dir)
    files = [p for p in root.rglob("*.json") if not p.name.startswith("_")]
    if args.venue:
        files = [p for p in files if f"/{args.venue}/" in p.as_posix()]
    if args.year:
        files = [p for p in files if f"/{args.year}/" in p.as_posix()]

    total = len(files)
    if total == 0:
        print(f"No JSON records found under {root}")
        return 1

    n_grobid_ok = 0
    n_unreadable = 0
    abstract_src = Counter()
    n_abstract_empty = 0
    n_methods_empty = 0
    n_needs_llm = 0
    n_heading_found = 0
    n_escalated = 0
    flag_counts = Counter()
    classifier_counts = Counter()
    methods_lengths: List[int] = []
    short_methods_docs: List[str] = []

    for fp in files:
        try:
            rec = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            n_unreadable += 1
            continue

        if rec.get("grobid_ok") is True:
            n_grobid_ok += 1
        abstract_src[rec.get("abstract_source") or "(none)"] += 1
        if not (rec.get("abstract") or "").strip():
            n_abstract_empty += 1

        methods = (rec.get("methods") or "").strip()
        methods_lengths.append(len(methods))
        if not methods:
            n_methods_empty += 1
        elif len(methods) < SHORT_METHODS:
            short_methods_docs.append(rec.get("doi", fp.name))

        if rec.get("methods_heading_found") is True:
            n_heading_found += 1

        extra = rec.get("extra", {}) or {}
        if extra.get("needs_llm_methods") is True:
            n_needs_llm += 1
        if extra.get("escalated") is True:
            n_escalated += 1
        classifier_counts[extra.get("heading_classifier") or "(none)"] += 1
        for flag in extra.get("methods_quality_flags", []) or []:
            flag_counts[flag] += 1

    def pct(n: int) -> str:
        return f"{n:5d}  ({100*n/total:5.1f}%)"

    print(f"\n{'='*60}")
    print(f"QA REPORT  --  {root}"
          + (f"  [{args.venue or ''} {args.year or ''}]".rstrip() if (args.venue or args.year) else ""))
    print(f"{'='*60}")
    print(f"Total records           : {total}")
    print(f"Unreadable JSON         : {pct(n_unreadable)}")
    print(f"GROBID ok               : {pct(n_grobid_ok)}")
    print()
    print(f"Abstract empty          : {pct(n_abstract_empty)}")
    print("Abstract source:")
    for src, n in abstract_src.most_common():
        print(f"    {src:12s}        : {pct(n)}")
    print()
    print(f"Methods empty           : {pct(n_methods_empty)}")
    print(f"Methods heading found   : {pct(n_heading_found)}")
    if methods_lengths:
        nonzero = [x for x in methods_lengths if x > 0]
        print(f"Methods length (chars)  : median={int(statistics.median(methods_lengths))} "
              f"mean={int(statistics.mean(methods_lengths))} "
              f"max={max(methods_lengths)} "
              f"(of non-empty: median={int(statistics.median(nonzero)) if nonzero else 0})")
    print(f"Suspiciously short (<{SHORT_METHODS}): {pct(len(short_methods_docs))}")
    print()
    print(f"needs_llm_methods (flagged): {pct(n_needs_llm)}   <-- LLM escalation queue")
    print(f"already escalated          : {pct(n_escalated)}")
    print("Quality flags (a paper can have several):")
    for flag, n in flag_counts.most_common():
        print(f"    {flag:24s}: {pct(n)}")
    print("Heading classifier path:")
    for c, n in classifier_counts.most_common():
        print(f"    {c:24s}: {pct(n)}")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
