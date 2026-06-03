"""
SIGCHI venue PDF downloader (concurrent).

Reads acm_dois_classified.csv (columns: doi, venue, is_sigchi).
For every DOI, builds the ACM PDF URL:  https://dl.acm.org/doi/pdf/{doi}

Workflow:
  1. Open CONCURRENCY URLs at once in Chrome (default: 10).
  2. Watch ~/Downloads for new .pdf files to land.
  3. Match each new file back to its DOI by filename fragment
     (ACM names PDFs after the DOI suffix, e.g. "3491102.3501818.pdf").
  4. Verify %PDF- magic bytes, then move to sigchi/<venue>/<safe_doi>.pdf.

The script is RESUMABLE: it skips any DOI whose file already exists in the
target venue folder. Cloudflare is handled by the browser itself, so make
sure dl.acm.org loads in Chrome (campus / VPN) before starting.

IMPORTANT — Chrome multi-download permission:
  The first time Chrome sees N>1 simultaneous downloads it pops up a permission
  bar at the top of the page. Click "Allow" once, then it remembers the choice
  for dl.acm.org. If you see lots of "timeout" messages early on, this is why.

Usage:
    python sigchi_downloader.py                   # default concurrency = 10
    python sigchi_downloader.py --concurrency 5   # change batch size
    python sigchi_downloader.py --sequential      # old 1-at-a-time mode
    python sigchi_downloader.py --dry-run         # parse CSV, print plan
"""

import argparse
import csv
import os
import random
import shutil
import sys
import time
import webbrowser
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────
SCRIPT_DIR        = Path(__file__).resolve().parent
ROOT              = SCRIPT_DIR.parent          # repo root
CSV_PATH          = ROOT / "data" / "master" / "acm_dois_classified.csv"
ROOT_OUT          = ROOT / "sigchi"
DOWNLOADS_FOLDER  = Path.home() / "Downloads"
DEFAULT_CONCURRENCY = 10    # how many URLs to open per batch
STAGGER_OPEN      = 0.4     # seconds between opening tabs in a batch
WAIT_TIMEOUT      = 30      # seconds to wait per download (sequential mode)
BATCH_WAIT_BASE   = 30      # base seconds for a concurrent batch
BATCH_WAIT_PER    = 4       # extra seconds per item in a concurrent batch
DELAY_BETWEEN_MIN = 3       # min seconds between opens (sequential, jittered)
DELAY_BETWEEN_MAX = 6       # max seconds between opens (sequential, jittered)
DELAY_BETWEEN_BATCHES = 2   # seconds between concurrent batches
PAUSE_EVERY       = 5000    # manual pause every N papers (effectively off)
COOLDOWN_EVERY    = 200     # auto-cooldown after every N successful downloads
COOLDOWN_SECONDS  = 300     # length of auto-cooldown (5 min)
PDF_URL_TEMPLATE  = "https://dl.acm.org/doi/pdf/{doi}"

# Windows Chrome paths (fall back to default browser if not found)
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
]


# ── Helpers ───────────────────────────────────────────────────────────
def safe_name(doi: str) -> str:
    """DOI → filename-safe stem. Matches step3_download.py."""
    return doi.replace("/", "_").replace(".", "_")


def safe_venue(venue: str) -> str:
    """Venue → safe folder name (slashes are illegal in Windows paths)."""
    return venue.replace("/", "-").replace("\\", "-").strip()


def get_chrome_opener():
    """Return a webbrowser controller pointing at Chrome, or default browser."""
    for path in CHROME_CANDIDATES:
        if os.path.exists(path):
            webbrowser.register(
                "chrome", None, webbrowser.BackgroundBrowser(path)
            )
            return webbrowser.get("chrome")
    print("⚠️  Chrome not found in standard locations — using default browser.")
    return webbrowser


def load_rows(csv_path: Path = None):
    path = csv_path or CSV_PATH
    if not path.exists():
        print(f"ERROR: {path} not found.")
        sys.exit(1)
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [r for r in reader if r.get("doi")]


def group_by_venue(rows):
    venues = {}
    for r in rows:
        venues.setdefault(r["venue"], []).append(r)
    return dict(sorted(venues.items(), key=lambda kv: -len(kv[1])))


def already_done_count(venue_dir: Path) -> int:
    if not venue_dir.exists():
        return 0
    # rglob → walks year subfolders too (e.g. sigchi/CHI/2025/*.pdf)
    return len(list(venue_dir.rglob("*.pdf")))


def print_venue_table(venues_dict):
    print(f"\n{'#':>3}  {'Venue':<22} {'Total':>7} {'Done':>6} {'Remaining':>10}")
    print("-" * 56)
    for i, (venue, rows) in enumerate(venues_dict.items(), 1):
        venue_dir = ROOT_OUT / safe_venue(venue)
        done = already_done_count(venue_dir)
        remaining = len(rows) - done
        print(
            f"{i:>3}  {venue:<22} {len(rows):>7} {done:>6} {remaining:>10}"
        )
    print("-" * 56)


def pick_venues(venues_dict):
    """Ask user which venues to process this run."""
    print_venue_table(venues_dict)
    venue_names = list(venues_dict.keys())
    raw = input(
        "\nEnter venues to process (comma-separated names or numbers, "
        "'all' for everything, 'q' to quit): "
    ).strip()

    if raw.lower() in ("q", "quit", "exit"):
        sys.exit(0)
    if raw.lower() == "all" or raw == "":
        return venue_names

    selected = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(venue_names):
                selected.append(venue_names[idx])
            else:
                print(f"  ⚠️  index {token} out of range, skipping")
        else:
            # case-insensitive match
            match = next(
                (v for v in venue_names if v.lower() == token.lower()), None
            )
            if match:
                selected.append(match)
            else:
                print(f"  ⚠️  venue '{token}' not in CSV, skipping")
    # de-dupe, preserve order
    seen = set()
    out = []
    for v in selected:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


# ── Download loops ────────────────────────────────────────────────────
def doi_fragment(doi: str) -> str:
    """Part of DOI used by ACM as the saved filename stem.
    e.g. '10.1145/3491102.3501818' -> '3491102.3501818'
    """
    return doi.split("/", 1)[1] if "/" in doi else doi


def _process_new_pdf(src: Path, dst: Path) -> str:
    """Move src→dst if it's a real PDF. Returns 'ok', 'badpdf', 'err:<msg>'."""
    try:
        with open(src, "rb") as fh:
            header = fh.read(5)
    except Exception as e:
        return f"err:read {e}"
    if header != b"%PDF-":
        try:
            os.remove(src)
        except Exception:
            pass
        return "badpdf"
    try:
        shutil.move(str(src), str(dst))
    except Exception as e:
        return f"err:move {e}"
    return "ok"


def download_venue_sequential(venue, rows, opener):
    """One download at a time. Original step3_download.py behaviour."""
    venue_dir = ROOT_OUT / safe_venue(venue)
    venue_dir.mkdir(parents=True, exist_ok=True)

    # rglob → catches PDFs in year subfolders too
    already = {f.stem for f in venue_dir.rglob("*.pdf")}
    todo = [r for r in rows if safe_name(r["doi"]) not in already]

    print(f"\n{'='*60}")
    print(f"VENUE: {venue}   total={len(rows)}   done={len(already)}   "
          f"todo={len(todo)}   mode=sequential")
    print(f"Output → {venue_dir}")
    print(f"{'='*60}")

    if not todo:
        print("Nothing to do — already complete.")
        return 0, 0
    if not DOWNLOADS_FOLDER.exists():
        print(f"ERROR: Downloads folder not found: {DOWNLOADS_FOLDER}")
        return 0, len(todo)

    downloaded = 0
    failed = 0
    next_cooldown_at = COOLDOWN_EVERY  # next downloaded-count to trigger cooldown

    for i, row in enumerate(todo, 1):
        doi = row["doi"]
        url = PDF_URL_TEMPLATE.format(doi=doi)
        stem = safe_name(doi)

        print(f"\n[{venue} {i}/{len(todo)}] {doi}")
        before = set(f.name for f in DOWNLOADS_FOLDER.glob("*.pdf"))
        try:
            opener.open(url)
        except Exception as e:
            print(f"  ❌ failed to open in browser: {e}")
            failed += 1
            continue

        found = False
        for sec in range(WAIT_TIMEOUT):
            time.sleep(1)
            after = set(f.name for f in DOWNLOADS_FOLDER.glob("*.pdf"))
            new_files = after - before
            partials = list(DOWNLOADS_FOLDER.glob("*.crdownload"))
            if new_files and not partials:
                new_file = sorted(new_files)[0]
                dst = venue_dir / f"{stem}.pdf"
                result = _process_new_pdf(DOWNLOADS_FOLDER / new_file, dst)
                if result == "ok":
                    print(f"  ✅ saved → {dst.name}")
                    downloaded += 1
                elif result == "badpdf":
                    print(f"  ⚠️  not a PDF, removed")
                    failed += 1
                else:
                    print(f"  ⚠️  {result}")
                    failed += 1
                found = True
                break
            if sec % 10 == 9:
                print(f"  …waiting ({sec+1}s)")

        if not found:
            print(f"  ❌ timeout")
            failed += 1
        # Jittered sleep — looks less bot-like to Cloudflare
        sleep_for = random.uniform(DELAY_BETWEEN_MIN, DELAY_BETWEEN_MAX)
        time.sleep(sleep_for)

        if i % PAUSE_EVERY == 0 and i < len(todo):
            print(f"\n--- pause: {downloaded} ok / {failed} failed ---")
            input("Press Enter to continue...")

        # Auto-cooldown: pause after every N successful downloads
        if downloaded >= next_cooldown_at and i < len(todo):
            mins = COOLDOWN_SECONDS // 60
            print(f"\n--- cooldown: {downloaded} downloaded, "
                  f"sleeping {mins} min to avoid rate-limit ---")
            time.sleep(COOLDOWN_SECONDS)
            print("--- resuming ---")
            next_cooldown_at += COOLDOWN_EVERY

    print(f"\n{venue} done: {downloaded} ok, {failed} failed")
    return downloaded, failed


def download_venue_concurrent(venue, rows, opener, concurrency):
    """Open `concurrency` URLs at a time; match files back to DOIs by name."""
    venue_dir = ROOT_OUT / safe_venue(venue)
    venue_dir.mkdir(parents=True, exist_ok=True)

    # rglob → catches PDFs in year subfolders too
    already = {f.stem for f in venue_dir.rglob("*.pdf")}
    todo = [r for r in rows if safe_name(r["doi"]) not in already]

    print(f"\n{'='*60}")
    print(f"VENUE: {venue}   total={len(rows)}   done={len(already)}   "
          f"todo={len(todo)}   concurrency={concurrency}")
    print(f"Output → {venue_dir}")
    print(f"{'='*60}")

    if not todo:
        print("Nothing to do — already complete.")
        return 0, 0
    if not DOWNLOADS_FOLDER.exists():
        print(f"ERROR: Downloads folder not found: {DOWNLOADS_FOLDER}")
        return 0, len(todo)

    downloaded = 0
    failed = 0
    n_batches = (len(todo) + concurrency - 1) // concurrency

    for bi in range(n_batches):
        batch = todo[bi * concurrency:(bi + 1) * concurrency]
        # Map fragment → doi for this batch
        expected = {doi_fragment(r["doi"]): r["doi"] for r in batch}
        before = set(f.name for f in DOWNLOADS_FOLDER.glob("*.pdf"))

        print(f"\n[{venue} batch {bi+1}/{n_batches}] opening {len(batch)} URLs")
        for r in batch:
            try:
                opener.open(PDF_URL_TEMPLATE.format(doi=r["doi"]))
            except Exception as e:
                print(f"  ❌ open failed for {r['doi']}: {e}")
            time.sleep(STAGGER_OPEN)

        # Wait for everything in this batch to land
        max_wait = BATCH_WAIT_BASE + BATCH_WAIT_PER * len(batch)
        matched_dois = set()  # DOIs we've successfully filed
        consumed = set()      # filenames we've moved/removed
        for sec in range(max_wait):
            time.sleep(1)
            partials = list(DOWNLOADS_FOLDER.glob("*.crdownload"))
            after = set(f.name for f in DOWNLOADS_FOLDER.glob("*.pdf"))
            new_files = (after - before) - consumed

            for fname in new_files:
                # Try to match this file to an expected DOI fragment
                matched_doi = None
                for fragment, doi in expected.items():
                    if doi in matched_dois:
                        continue
                    if fragment in fname:
                        matched_doi = doi
                        break
                if matched_doi is None:
                    continue  # leave alone, may belong to next batch / unrelated

                src = DOWNLOADS_FOLDER / fname
                # Skip if Chrome is still writing this exact file
                if not src.exists():
                    continue
                dst = venue_dir / f"{safe_name(matched_doi)}.pdf"
                result = _process_new_pdf(src, dst)
                if result == "ok":
                    print(f"  ✅ {matched_doi} → {dst.name}")
                    downloaded += 1
                    matched_dois.add(matched_doi)
                    consumed.add(fname)
                elif result == "badpdf":
                    print(f"  ⚠️  {fname} not a PDF (likely Cloudflare HTML), removed")
                    failed += 1
                    matched_dois.add(matched_doi)
                    consumed.add(fname)
                else:
                    print(f"  ⚠️  {matched_doi}: {result}")
                    consumed.add(fname)

            if len(matched_dois) >= len(batch):
                break

            if sec % 10 == 9 and not partials:
                print(f"  matched {len(matched_dois)}/{len(batch)} ({sec+1}s)")

        # Anything still unmatched at end of batch is a failure
        unmatched = [r["doi"] for r in batch if r["doi"] not in matched_dois]
        if unmatched:
            print(f"  ❌ batch timeout, {len(unmatched)} not downloaded:")
            for d in unmatched[:5]:
                print(f"     {d}")
            if len(unmatched) > 5:
                print(f"     …and {len(unmatched)-5} more")
            failed += len(unmatched)

        time.sleep(DELAY_BETWEEN_BATCHES)

        # Mid-venue pause every ~PAUSE_EVERY downloaded
        if downloaded and downloaded % PAUSE_EVERY < concurrency \
                and bi < n_batches - 1:
            print(f"\n--- pause for {venue}: {downloaded} ok / {failed} failed ---")
            print("--- close extra Chrome tabs to free memory ---")
            input("Press Enter to continue...")

    print(f"\n{venue} done: {downloaded} ok, {failed} failed")
    return downloaded, failed


# ── Ingest existing PDFs ──────────────────────────────────────────────
def stem_to_doi_candidates(stem: str):
    """Return possible DOIs that could have produced this filename stem.

    Existing folders use one of two conventions:
      A) '/' replaced with '_', dots preserved:   10.1145_3491102.3501818
      B) '/' AND '.' replaced with '_':           10_1145_3491102_3501818
    """
    candidates = set()
    # A) restore '/' on first '_'
    if "_" in stem:
        candidates.add(stem.replace("_", "/", 1))
    # B) shape '10_1145_X_Y' → '10.1145/X.Y'
    parts = stem.split("_")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        prefix = f"{parts[0]}.{parts[1]}"
        if len(parts) == 2:
            candidates.add(prefix)
        else:
            suffix = ".".join(parts[2:])
            candidates.add(f"{prefix}/{suffix}")
    return candidates


def ingest_existing(source_path: Path, rows):
    """Move pre-downloaded PDFs into sigchi/<venue>/<safe_doi>.pdf."""
    if not source_path.exists():
        print(f"ERROR: ingest path does not exist: {source_path}")
        return
    if not source_path.is_dir():
        print(f"ERROR: ingest path is not a directory: {source_path}")
        return

    # Build DOI lookup
    doi_to_venue = {r["doi"]: r["venue"] for r in rows}

    pdfs = list(source_path.glob("*.pdf"))
    print(f"Scanning {source_path}")
    print(f"Found {len(pdfs)} PDFs")
    if not pdfs:
        return

    moved = 0
    skipped_already = 0
    no_match = 0
    bad_pdf = 0
    by_venue = {}
    total = len(pdfs)

    for i, pdf in enumerate(pdfs, 1):
        if i % 50 == 0 or i == total:
            print(f"  …{i}/{total}  moved={moved} skipped={skipped_already} "
                  f"no-match={no_match} bad={bad_pdf}", flush=True)
        # Match against possible DOI shapes
        matched = None
        for doi in stem_to_doi_candidates(pdf.stem):
            if doi in doi_to_venue:
                matched = doi
                break
        if matched is None:
            no_match += 1
            continue

        venue = doi_to_venue[matched]
        venue_dir = ROOT_OUT / safe_venue(venue)
        venue_dir.mkdir(parents=True, exist_ok=True)
        dst = venue_dir / f"{safe_name(matched)}.pdf"

        if dst.exists():
            skipped_already += 1
            continue

        # Verify the file is a real PDF before moving
        try:
            with open(pdf, "rb") as fh:
                header = fh.read(5)
        except Exception as e:
            print(f"  ⚠️  read error {pdf.name}: {e}")
            continue
        if header != b"%PDF-":
            bad_pdf += 1
            continue

        try:
            shutil.move(str(pdf), str(dst))
            moved += 1
            by_venue[venue] = by_venue.get(venue, 0) + 1
        except Exception as e:
            print(f"  ⚠️  move error {pdf.name} → {dst}: {e}")

    print(f"\nINGEST SUMMARY")
    print(f"  Moved:           {moved}")
    print(f"  Already in place:{skipped_already}")
    print(f"  No CSV match:    {no_match}")
    print(f"  Not a PDF:       {bad_pdf}")
    if by_venue:
        print(f"\nBy venue:")
        for v, n in sorted(by_venue.items(), key=lambda kv: -kv[1]):
            print(f"  {v:<20} {n}")


# ── Dry run ───────────────────────────────────────────────────────────
def dry_run(venues_dict):
    print("DRY RUN — no browser, no downloads.\n")
    print_venue_table(venues_dict)
    print("\nFirst 3 URLs per venue (sanity check):")
    for venue, rows in venues_dict.items():
        print(f"\n  {venue}:")
        for r in rows[:3]:
            print(f"    {PDF_URL_TEMPLATE.format(doi=r['doi'])}")


# ── Main ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse CSV, print plan, do not open browser.")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"How many URLs to open per batch (default {DEFAULT_CONCURRENCY}).")
    parser.add_argument("--sequential", action="store_true",
                        help="Old 1-at-a-time mode (overrides --concurrency).")
    parser.add_argument("--ingest", metavar="PATH",
                        help="Move pre-downloaded PDFs from PATH into sigchi/<venue>/ "
                             "based on DOI lookup, then exit.")
    parser.add_argument("--csv", metavar="PATH",
                        help="Override input CSV path (default: acm_dois_classified.csv).")
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve() if args.csv else CSV_PATH
    rows = load_rows(csv_path)
    print(f"Loaded {len(rows)} DOIs from {csv_path.name}")
    venues_dict = group_by_venue(rows)
    print(f"Found {len(venues_dict)} venues")

    ROOT_OUT.mkdir(exist_ok=True)

    if args.ingest:
        ingest_existing(Path(args.ingest), rows)
        return

    if args.dry_run:
        dry_run(venues_dict)
        return

    selected = pick_venues(venues_dict)
    if not selected:
        print("No venues selected — exiting.")
        return

    total_to_do = sum(
        len(venues_dict[v])
        - already_done_count(ROOT_OUT / safe_venue(v))
        for v in selected
    )
    mode = "sequential" if args.sequential else f"concurrent (batch={args.concurrency})"
    print(f"\nSelected {len(selected)} venue(s): {', '.join(selected)}")
    print(f"Mode: {mode}")
    print(f"Total PDFs still to download: {total_to_do}")
    print(f"Downloads watched at: {DOWNLOADS_FOLDER}")
    print(f"PDFs will be saved under: {ROOT_OUT}")
    if not args.sequential:
        print("\nFIRST RUN: Chrome will ask permission to download multiple files.")
        print("Click 'Allow' on the bar at the top of dl.acm.org.")
    input("\nMake sure dl.acm.org loads in Chrome (campus/VPN), "
          "then press Enter to start...")

    opener = get_chrome_opener()

    grand_dl = 0
    grand_fail = 0
    for venue in selected:
        if args.sequential:
            d, f = download_venue_sequential(venue, venues_dict[venue], opener)
        else:
            d, f = download_venue_concurrent(
                venue, venues_dict[venue], opener, args.concurrency
            )
        grand_dl += d
        grand_fail += f

    print(f"\n{'='*60}")
    print("ALL SELECTED VENUES COMPLETE")
    print(f"{'='*60}")
    print(f"Downloaded: {grand_dl}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
