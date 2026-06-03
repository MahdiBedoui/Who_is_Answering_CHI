"""
Bulk-pull every CHI 2024 paper from Crossref, then diff against PDFs on disk
and flag suspects by page count.

Cursor-paginates /works?filter=type:proceedings-article&query.container-title=...
filters to the 3613904 prefix, dumps a CSV, and prints stats.

Usage:
    python analyze_chi24.py
"""
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT        = Path(__file__).resolve().parent.parent
DISK_DOIS   = ROOT / "data" / "analysis" / "chi24_disk_dois.txt"
OUT_CSV     = ROOT / "data" / "analysis" / "chi24_analysis.csv"
PROC_ID     = "3613904"
CONTAINER   = "Proceedings of the CHI Conference on Human Factors in Computing Systems"
USER_AGENT  = "sigchi-fetcher/1.0 (mailto:bedouimehdi39@gmail.com)"
ROWS_PER    = 1000


def fetch_all():
    """Cursor-paginate Crossref for the container, return list of dicts."""
    items = []
    cursor = "*"
    page = 0
    prefix = f"10.1145/{PROC_ID}"
    while True:
        page += 1
        params = {
            "filter":  "type:proceedings-article",
            "query.container-title": CONTAINER,
            "rows":    str(ROWS_PER),
            "cursor":  cursor,
            "select":  "DOI,title,page,subtitle,subject",
        }
        url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read().decode("utf-8"))
        msg  = payload["message"]
        page_items = msg.get("items", [])
        next_cursor = msg.get("next-cursor")
        kept = [it for it in page_items if it.get("DOI", "").startswith(prefix + ".")
                or it.get("DOI", "") == prefix]
        items.extend(kept)
        print(f"  page {page}: {len(page_items)} returned, {len(kept)} matched "
              f"{prefix}.*  (running: {len(items)})")
        if not next_cursor or next_cursor == cursor or not page_items:
            break
        cursor = next_cursor
        time.sleep(1.0)
    return items


def n_pages(p: str):
    if not p:
        return None
    m = re.match(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$", p)
    if m:
        return int(m.group(2)) - int(m.group(1)) + 1
    if p.strip().isdigit():
        return 1
    return None


def main():
    disk_dois = {d.strip() for d in DISK_DOIS.read_text().splitlines() if d.strip()}
    print(f"On disk: {len(disk_dois)} CHI 2024 DOIs\n")

    print("Pulling Crossref…")
    items = fetch_all()
    cr_by_doi = {it["DOI"]: it for it in items}
    print(f"\nCrossref returned {len(cr_by_doi)} unique CHI 2024 DOIs total.")

    extras   = disk_dois - set(cr_by_doi)
    missing  = set(cr_by_doi) - disk_dois
    print(f"  On disk but NOT in Crossref: {len(extras)}")
    print(f"  In Crossref but NOT on disk: {len(missing)}")

    # Build rows for everything on disk (with crossref enrichment when present)
    rows = []
    for doi in sorted(disk_dois, key=lambda d: int(d.split(".")[-1])):
        it = cr_by_doi.get(doi, {})
        title = " ".join(it.get("title", [])).strip()
        page  = it.get("page", "")
        rows.append({
            "doi":      doi,
            "paper_id": int(doi.split(".")[-1]),
            "title":    title,
            "page":     page,
            "n_pages":  n_pages(page) or "",
            "in_crossref": "yes" if doi in cr_by_doi else "no",
        })

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doi","paper_id","title","page","n_pages","in_crossref"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {OUT_CSV}")

    # Page-count histogram
    with_pages = [r for r in rows if isinstance(r["n_pages"], int)]
    print(f"\nPage-count histogram ({len(with_pages)} of {len(rows)} had parseable pages):")
    bins = Counter()
    for r in with_pages:
        n = r["n_pages"]
        if n <= 2:    bins["1-2"]   += 1
        elif n <= 4:  bins["3-4"]   += 1
        n = r["n_pages"]
        if n <= 2:    bins["1-2"]   += 1
        elif n <= 4:  bins["3-4"]   += 1
        elif n <= 6:  bins["5-6"]   += 1
        elif n <= 8:  bins["7-8"]   += 1
        elif n <= 12: bins["9-12"]  += 1
        elif n <= 20: bins["13-20"] += 1
        else:         bins["21+"]   += 1
    for k in ["1-2","3-4","5-6","7-8","9-12","13-20","21+"]:
        print(f"  {k:>6}: {bins.get(k, 0)}")

    suspects = [r for r in rows if isinstance(r["n_pages"], int) and r["n_pages"] < 8]
    print(f"\nSuspects (< 8 pages, probably NOT research articles): {len(suspects)}")
    for r in sorted(suspects, key=lambda x: x["n_pages"]):
        print(f"  {r['n_pages']:>3}p  {r['doi']}  {r['title'][:80]}")

    ID_ISLANDS = [(3641887, 3642962)]
    in_main = lambda pid: any(lo <= pid <= hi for lo, hi in ID_ISLANDS)
    outliers = [r for r in rows if not in_main(r["paper_id"])]
    print(f"\nOutlier-island papers (already-known strays): {len(outliers)}")
    for r in outliers:
        print(f"  id={r['paper_id']}  {r['n_pages']}p  {r['doi']}  {r['title'][:80]}")


if __name__ == "__main__":    main()
