"""
Organize PDFs in sigchi/<VENUE>/ into year subfolders.

How it works:
  1. Reads acm_dois_classified.csv, finds all DOIs for VENUE.
  2. Groups them by proceedings ID (the prefix before the first dot in the
     DOI suffix, e.g. 3523227 from 10.1145/3523227.3546752).
  3. For each proceedings ID, queries one DOI against Crossref to determine
     its published year.
  4. Moves PDFs in sigchi/<VENUE>/ into sigchi/<VENUE>/<year>/.
     PDFs already in subfolders (e.g. previously organized) are left alone.

Change VENUE at the top to organize a different venue.

Usage:
    python organize_by_year.py
    python organize_by_year.py --dry-run     # show plan, don't move
"""

import argparse
import csv
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────
VENUE      = "UbiComp"
USER_AGENT = "sigchi-fetcher/1.0 (mailto:bedouimehdi39@gmail.com)"

# ── Paths ─────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parent.parent
CSV_PATH  = ROOT / "data" / "master" / "acm_dois_classified.csv"
VENUE_DIR = ROOT / "sigchi" / VENUE


def safe_name(doi: str) -> str:
    return doi.replace("/", "_").replace(".", "_")


def proc_of(doi: str) -> str:
    """10.1145/3523227.3546752 → '3523227'"""
    try:
        suffix = doi.split("/", 1)[1]
        return suffix.split(".")[0]
    except IndexError:
        return ""


def crossref_year(doi: str) -> int | None:
    """Return published year for a DOI, or None on failure."""
    req = urllib.request.Request(
        f"https://api.crossref.org/works/{doi}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            msg = json.loads(r.read().decode("utf-8"))["message"]
    except Exception as e:
        print(f"    crossref error: {e}")
        return None
    for key in ("published-print", "published", "issued", "published-online"):
        parts = msg.get(key, {}).get("date-parts")
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan without moving any files.")
    args = parser.parse_args()

    if not CSV_PATH.exists():
        print(f"ERROR: {CSV_PATH} not found"); sys.exit(1)
    if not VENUE_DIR.exists():
        print(f"ERROR: {VENUE_DIR} not found"); sys.exit(1)

    # 1) Load CSV, group venue DOIs by proc_id
    by_proc = {}
    for r in csv.DictReader(open(CSV_PATH, encoding="utf-8")):
        if r.get("venue") != VENUE:
            continue
        doi = r["doi"]
        proc = proc_of(doi)
        if proc:
            by_proc.setdefault(proc, []).append(doi)

    if not by_proc:
        print(f"No DOIs for venue '{VENUE}' in CSV"); sys.exit(0)

    print(f"Venue: {VENUE}")
    print(f"Distinct proceedings IDs: {len(by_proc)}")
    for p, ds in sorted(by_proc.items(), key=lambda kv: -len(kv[1])):
        print(f"  {p}: {len(ds)} DOIs")

    # 2) Resolve year for each proc_id via Crossref
    print(f"\nLooking up years via Crossref…")
    proc_year = {}
    for proc, dois in by_proc.items():
        y = crossref_year(dois[0])
        proc_year[proc] = y
        print(f"  proc {proc} → {y}")
        time.sleep(0.2)

    # Build DOI → year
    doi_year = {d: proc_year[p] for p, ds in by_proc.items() for d in ds}

    # 3) Walk VENUE_DIR top-level PDFs and move
    print(f"\nScanning {VENUE_DIR} (top level only) …")
    pdfs = [f for f in os.listdir(VENUE_DIR)
            if f.endswith(".pdf") and (VENUE_DIR / f).is_file()]
    print(f"Top-level PDFs: {len(pdfs)}")

    moved = 0
    skipped = 0
    no_match = 0
    by_year_count = {}

    # Build reverse lookup safe_name → DOI for fast match
    stem_to_doi = {safe_name(d): d for d in doi_year}

    for f in pdfs:
        stem = f[:-4]
        doi = stem_to_doi.get(stem)
        if doi is None:
            no_match += 1
            continue
        year = doi_year.get(doi)
        if year is None:
            skipped += 1
            continue
        dst_dir = VENUE_DIR / str(year)
        if args.dry_run:
            print(f"  would move {f} → {dst_dir.name}/")
        else:
            dst_dir.mkdir(exist_ok=True)
            shutil.move(str(VENUE_DIR / f), str(dst_dir / f))
        by_year_count[year] = by_year_count.get(year, 0) + 1
        moved += 1

    print(f"\nSummary:")
    print(f"  {'would move' if args.dry_run else 'moved'}: {moved}")
    print(f"  no DOI match in CSV: {no_match}")
    print(f"  year resolution failed: {skipped}")
    if by_year_count:
        print(f"\nBy year:")
        for y, n in sorted(by_year_count.items()):
            print(f"  {y}: {n}")

if __name__ == "__main__":
    main()
