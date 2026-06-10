#!/usr/bin/env python3
"""Migrate flat data/extracted/*.json into data/extracted/<venue>/<year>/<type>/.

Idempotent and safe: reads each record's stored venue/year/ptype (falling back to
its source_pdf_path) to compute the destination, then MOVES the file there. Files
already in a subfolder are left alone. Run once after switching the extractor to
the nested output layout, so existing work is found by the resume/skip check.

Usage:
    python "Phase 2 - Text Extraction/reorganize_extracted.py"                 # migrate data/extracted
    python "Phase 2 - Text Extraction/reorganize_extracted.py" --dry-run        # show planned moves only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional

# src/ lives alongside this script (Phase 2 - Text Extraction/src/); put this
# script's own directory on the path so `from src.X` resolves regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.extract import parse_path_metadata  # noqa: E402


def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)


def _safe(name: str) -> str:
    """Make a path component filesystem-safe."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("_") or "unknown"


def destination(root: Path, record: dict) -> Optional[Path]:
    """Compute the nested destination path for a record (None if undetermined).

    Prefers the record's stored venue/year/ptype; falls back to deriving them from
    the corpus `source_pdf_path` via the shared library parser. Returns None (skip)
    when none of the three can be determined, rather than creating an 'unknown' bucket.
    """
    venue = record.get("venue") or ""
    year = str(record.get("year") or "")
    ptype = record.get("ptype") or ""
    if not (venue and year and ptype):
        meta = parse_path_metadata(record.get("source_pdf_path", ""))
        venue = venue or (meta["venue"] or "")
        year = year or (str(meta["year"]) if meta["year"] else "")
        ptype = ptype or (meta["ptype"] or "")
    if not (venue and year and ptype):
        return None
    return root / _safe(venue) / _safe(str(year)) / _safe(ptype)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Reorganize flat extracted JSON into subfolders.")
    p.add_argument("--input-dir", default="data/extracted", help="Extracted JSON root.")
    p.add_argument("--dry-run", action="store_true", help="Show planned moves, change nothing.")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Move each flat *.json into its venue/year/type subfolder."""
    args = parse_args(argv)
    root = Path(args.input_dir)
    if not root.exists():
        log(f"ERROR: {root} not found")
        return 1

    # Only files sitting directly in root (flat layout); skip already-nested ones.
    flat = [p for p in root.glob("*.json") if not p.name.startswith("_")]
    moved = skipped = failed = 0

    for fp in flat:
        try:
            record = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log(f"[skip] unreadable {fp.name}: {exc}")
            failed += 1
            continue
        dest_dir = destination(root, record)
        if dest_dir is None:
            log(f"[skip] cannot determine venue/year/type for {fp.name}")
            failed += 1
            continue
        dest = dest_dir / fp.name
        if dest.resolve() == fp.resolve():
            skipped += 1
            continue
        if args.dry_run:
            log(f"[dry-run] {fp.name} -> {dest.relative_to(root)}")
            moved += 1
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        fp.replace(dest)
        moved += 1

    verb = "would move" if args.dry_run else "moved"
    log(f"[reorganize] {verb}={moved} skipped={skipped} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
