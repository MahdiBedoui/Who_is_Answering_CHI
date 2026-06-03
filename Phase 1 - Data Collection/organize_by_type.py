"""
organize_by_type.py — split each year folder of a venue into
Research Article/ and Short Paper/ subfolders.

Resulting structure:
    sigchi/VERIFIED COUNT/<VENUE>/2022/Research Article/*.pdf
    sigchi/VERIFIED COUNT/<VENUE>/2022/Short Paper/*.pdf
    sigchi/VERIFIED COUNT/<VENUE>/2023/Research Article/*.pdf
    sigchi/VERIFIED COUNT/<VENUE>/2023/Short Paper/*.pdf
    ...

How it works:
  1. Reads two keep-list files (RA + Short). Each file can be:
       - a plain text file of DOIs, one per line
       - a CSV with a "doi,venue,is_sigchi" header
       - anything else — the script regex-extracts every 10.1145/* or
         10.5555/* DOI it finds.
  2. Walks sigchi/VERIFIED COUNT/<VENUE>/ recursively.
  3. For each PDF, creates "Research Article/" or "Short Paper/" inside
     its parent folder (typically a year folder) and moves it in.
  4. PDFs not in either list are left in place.

Edit the CONFIG block at the top per venue, then run:
    python organize_by_type.py
    python organize_by_type.py --dry-run     # show plan without moving
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────
VENUE       = "SUI"
KEEP_DIR    = "sui"            # subfolder under data/keep_lists/
RA_FILE     = "sui_ra.csv"
SHORT_FILE  = ""
RA_LABEL    = "Research Article"   # subfolder name for RA bucket
SHORT_LABEL = "Short Paper"        # subfolder name for second bucket (e.g. "Extended Abstract")

# Folder layout — change if your VERIFIED COUNT path differs
ROOT          = Path(__file__).resolve().parent.parent   # repo root
BASE          = ROOT / "data" / "keep_lists" / KEEP_DIR   # where RA_FILE/SHORT_FILE live
VERIFIED_BASE = ROOT / "sigchi" / "VERIFIED COUNT"
VENUE_DIR     = VERIFIED_BASE / VENUE


# ── Helpers ───────────────────────────────────────────────────────────
def load_dois(path_str: str):
    """Regex-extract every 10.1145/* and 10.5555/* DOI from a file."""
    if not path_str:
        return set()
    p = BASE / path_str
    if not p.exists():
        print(f"  WARNING: {p} not found, treating as empty")
        return set()
    text = p.read_text(encoding="utf-8", errors="ignore")
    return set(re.findall(r"10\.(?:1145|5555)/\d+(?:\.\d+)?", text))


def safe_name(doi: str) -> str:
    return doi.replace("/", "_").replace(".", "_")


# ── Main ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan without moving any files.")
    args = parser.parse_args()

    if not VENUE_DIR.exists():
        print(f"ERROR: {VENUE_DIR} not found")
        sys.exit(1)

    ra_stems    = {safe_name(d) for d in load_dois(RA_FILE)}
    short_stems = {safe_name(d) for d in load_dois(SHORT_FILE)}
    print(f"Venue:           {VENUE}")
    print(f"RA keep-set:     {len(ra_stems)}")
    print(f"Short keep-set:  {len(short_stems)}")
    overlap = ra_stems & short_stems
    if overlap:
        print(f"  ⚠️  {len(overlap)} DOIs appear in BOTH lists — RA will win.")

    moved_ra = 0
    moved_short = 0
    no_match = 0
    by_year_type = {}   # {(year, type): count} for the summary

    bucket_names = {RA_LABEL, SHORT_LABEL, "_excluded"}
    for root, dirs, files in os.walk(VENUE_DIR):
        root_path = Path(root)
        # Don't descend into excluded/bucket folders
        dirs[:] = [d for d in dirs if d not in bucket_names]
        # Skip any folder that's already a bucket
        if root_path.name in bucket_names:
            continue
        for f in files:
            if not f.endswith(".pdf"):
                continue
            stem = f[:-4]
            if stem in ra_stems:
                dst_dir = root_path / RA_LABEL
                kind = RA_LABEL
                moved_ra += 1
            elif stem in short_stems:
                dst_dir = root_path / SHORT_LABEL
                kind = SHORT_LABEL
                moved_short += 1
            else:
                no_match += 1
                continue
            # Track by parent year name (or whatever the folder is called)
            year_label = root_path.name if root_path != VENUE_DIR else "(top level)"
            by_year_type[(year_label, kind)] = \
                by_year_type.get((year_label, kind), 0) + 1
            src = root_path / f
            if args.dry_run:
                print(f"  would move {year_label}/{f} → {year_label}/{kind}/")
            else:
                dst_dir.mkdir(exist_ok=True)
                shutil.move(str(src), str(dst_dir / f))

    print(f"\nSummary:")
    print(f"  → {RA_LABEL}: {moved_ra}")
    print(f"  → {SHORT_LABEL}: {moved_short}")
    print(f"  unclassified (left in place): {no_match}")

    if by_year_type:
        print(f"\nBreakdown by year:")
        years = sorted({y for (y, _) in by_year_type})
        for y in years:
            ra_n  = by_year_type.get((y, RA_LABEL), 0)
            sh_n  = by_year_type.get((y, SHORT_LABEL), 0)
            print(f"  {y}:  {RA_LABEL}={ra_n}  {SHORT_LABEL}={sh_n}")


if __name__ == "__main__":
    main()
