#!/usr/bin/env python3
"""Sanity-check a random sample of DOIs by pulling their Crossref metadata.

Use this when you suspect a keep-list has venue mis-tags, year drift, or wrong
content type. Pulls N random DOIs from a keep-list (or per-year files for a
venue) and prints title / year / container / event / page count side by side.

Usage:
    python scripts/spot_check.py --keep-list data/keep_lists/chi/chi24_ra.txt --n 5
    python scripts/spot_check.py --venue chi --n 3
    python scripts/spot_check.py --doi 10.1145/3613904.3641887
    python scripts/spot_check.py --keep-list <file> --n 5 --show issue volume
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
KEEP_DIR = ROOT / "data" / "keep_lists"
UA = "whos-answering-chi/1.0 (mailto:bedouimehdi39@gmail.com)"


def fetch_one(doi: str) -> Optional[Dict]:
    """Return Crossref metadata for one DOI, or None on failure."""
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/')}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))["message"]
    except Exception as e:
        print(f"  ! Crossref error for {doi}: {e}", file=sys.stderr)
        return None


def dois_from_text(text: str) -> List[str]:
    """Extract every 10.1145/... DOI from arbitrary text."""
    return sorted(set(re.findall(r"10\.1145/\d+(?:\.\d+)?", text)))


def collect_dois(args: argparse.Namespace) -> List[str]:
    """Resolve --doi, --keep-list, or --venue into a deduplicated DOI list."""
    if args.doi:
        return [args.doi]
    if args.keep_list:
        path = Path(args.keep_list)
        if not path.exists():
            print(f"keep-list not found: {path}", file=sys.stderr); sys.exit(1)
        return dois_from_text(path.read_text(encoding="utf-8", errors="ignore"))
    if args.venue:
        folder = KEEP_DIR / args.venue
        if not folder.exists():
            print(f"venue folder not found: {folder}", file=sys.stderr); sys.exit(1)
        out: List[str] = []
        for f in sorted(folder.glob("*.txt")):
            out.extend(dois_from_text(f.read_text(encoding="utf-8", errors="ignore")))
        return sorted(set(out))
    print("Provide one of --doi, --keep-list, or --venue", file=sys.stderr); sys.exit(1)


def format_row(msg: Dict, extra: List[str]) -> Dict[str, str]:
    """Pluck the fields we always show, plus any --show extras."""
    title = " ".join(msg.get("title", []))[:70]
    container = (msg.get("container-title") or [""])[0][:50]
    event = (msg.get("event", {}) or {}).get("name", "")[:50]
    pub = (msg.get("published-print") or msg.get("published") or {}).get("date-parts", [[None]])[0]
    year = pub[0] if pub else "?"
    page = msg.get("page", "")
    row = {
        "doi":       msg.get("DOI", ""),
        "year":      str(year),
        "page":      page,
        "title":     title,
        "container": container,
        "event":     event,
    }
    for fld in extra:
        row[fld] = str(msg.get(fld, ""))[:40]
    return row


def main() -> None:
    p = argparse.ArgumentParser()
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--doi", help="A single DOI to inspect.")
    src.add_argument("--keep-list", help="Path to a single keep-list .txt.")
    src.add_argument("--venue", help="Venue folder under data/keep_lists/ (e.g. 'chi').")
    p.add_argument("--n", type=int, default=5,
                   help="Number of random DOIs to sample (default 5; ignored for --doi).")
    p.add_argument("--show", nargs="*", default=[],
                   help="Extra Crossref fields to display per DOI (e.g. issue volume subtype).")
    p.add_argument("--seed", type=int, default=None,
                   help="Random seed for reproducible sampling.")
    args = p.parse_args()

    dois = collect_dois(args)
    print(f"Found {len(dois)} DOIs in source", file=sys.stderr)

    if args.seed is not None:
        random.seed(args.seed)
    if not args.doi and len(dois) > args.n:
        dois = random.sample(dois, args.n)
    print(f"Sampling {len(dois)} DOIs", file=sys.stderr)

    rows: List[Dict[str, str]] = []
    for d in dois:
        msg = fetch_one(d)
        if msg is None:
            rows.append({"doi": d, "year": "ERR", "page": "", "title": "(fetch failed)",
                         "container": "", "event": ""})
        else:
            rows.append(format_row(msg, args.show))
        time.sleep(0.2)

    # Pretty print
    cols = ["doi", "year", "page", "title", "container", "event"] + list(args.show)
    widths = {c: max(len(c), max((len(r.get(c, "")) for r in rows), default=0)) for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print("\n" + header)
    print("-" * len(header))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


if __name__ == "__main__":
    main()
