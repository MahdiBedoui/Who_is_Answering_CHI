"""
Find DOIs from an ACM proceedings that are NOT in acm_dois_classified.csv.

How it works:
  1. Queries Crossref's /works endpoint (free, no auth) with cursor pagination
     for proceedings-articles in the target container-title.
  2. Filters returned DOIs by the proceedings ID prefix (e.g. 10.1145/3706598.).
  3. Diffs against DOIs already present in acm_dois_classified.csv.
  4. Writes missing_<TAG>.csv with the gap.

Default config below is for CHI 2025 (proceedings ID 3706598). Change the four
CONFIG values to target a different year / venue and rerun.

Usage:
    python find_missing.py
"""

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────
PROC_ID         = "3699682"
CONTAINER_TITLE = "Proceedings of the 33rd ACM Conference on User Modeling, Adaptation and Personalization"
VENUE_LABEL     = "UMAP"
OUTPUT_TAG      = "umap25_main"
USER_AGENT      = "sigchi-fetcher/1.0 (mailto:bedouimehdi39@gmail.com)"

# ── Paths ─────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT       = SCRIPT_DIR.parent
CSV_PATH   = ROOT / "data" / "master" / "acm_dois_classified.csv"
OUT_PATH   = ROOT / "data" / "downloads" / f"missing_{OUTPUT_TAG}.csv"

CROSSREF   = "https://api.crossref.org/works"
ROWS       = 1000           # max page size Crossref allows
SLEEP_PAGE = 1.0            # be polite between paginated requests


def load_csv_dois_for_proc():
    """Return the set of DOIs in the CSV that belong to this proceedings."""
    if not CSV_PATH.exists():
        print(f"ERROR: {CSV_PATH} not found")
        sys.exit(1)
    prefix = f"10.1145/{PROC_ID}"
    have = set()
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            doi = row.get("doi", "")
            # match both "10.1145/3706598" and "10.1145/3706598.NNNN"
            if doi == prefix or doi.startswith(prefix + "."):
                have.add(doi)
    return have


def fetch_crossref():
    """Cursor-paginate Crossref for all proceedings-articles in the container.
    Return only DOIs starting with 10.1145/<PROC_ID>.
    """
    prefix = f"10.1145/{PROC_ID}"
    want = set()
    cursor = "*"
    page = 0
    total_seen = 0

    while True:
        page += 1
        # Use query.container-title (fuzzy) instead of filter=container-title:
        # because the filter syntax uses comma as a separator and breaks when
        # the title itself contains commas.
        params = {
            "filter": "type:proceedings-article",
            "query.container-title": CONTAINER_TITLE,
            "rows":   str(ROWS),
            "cursor": cursor,
            "select": "DOI,title",
        }
        url = CROSSREF + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  ❌ page {page} request failed: {e}")
            time.sleep(5)
            continue

        msg = payload.get("message", {})
        items = msg.get("items", [])
        next_cursor = msg.get("next-cursor")
        if not items:
            break

        page_matched = 0
        for item in items:
            doi = item.get("DOI", "")
            if doi.startswith(prefix + ".") or doi == prefix:
                want.add(doi)
                page_matched += 1

        total_seen += len(items)
        print(f"  page {page}: {len(items)} items, {page_matched} matched "
              f"prefix → running total {len(want)}")

        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        time.sleep(SLEEP_PAGE)

    print(f"\nCrossref returned {total_seen} items total, "
          f"{len(want)} matched 10.1145/{PROC_ID}.*")
    return want


def main():
    print(f"Target: {VENUE_LABEL} (proceedings ID {PROC_ID})")
    print(f"Container: {CONTAINER_TITLE}\n")

    have = load_csv_dois_for_proc()
    print(f"CSV has {len(have)} DOIs for this proceedings.")

    print(f"\nQuerying Crossref…")
    want = fetch_crossref()

    missing = want - have
    extra   = have - want   # in CSV but not returned by Crossref (sanity)

    print(f"\nDIFF")
    print(f"  In Crossref:        {len(want)}")
    print(f"  In CSV:             {len(have)}")
    print(f"  Missing from CSV:   {len(missing)}")
    print(f"  Extra in CSV:       {len(extra)}  (only meaningful if non-zero)")

    if extra:
        print("\nFirst few CSV-only DOIs (Crossref didn't return):")
        for d in sorted(extra)[:5]:
            print(f"    {d}")

    if not missing:
        print("\n✅ Nothing missing — CSV covers everything Crossref knows.")
        return

    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doi", "venue", "is_sigchi"])
        for d in sorted(missing):
            w.writerow([d, VENUE_LABEL, "True"])

    print(f"\nWrote {OUT_PATH} ({len(missing)} rows)")
    print("Next step: download these with the main script. Either:")
    print("  1. Append them to acm_dois_classified.csv and rerun sigchi_downloader.py")
    print(f"     (back up the original first!).")


if __name__ == "__main__":
    main()
