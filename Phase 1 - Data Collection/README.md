# Phase 1 — Data Collection

This document describes how the ~16,000-paper corpus was assembled, validated, and organized for the *Who's Answering CHI?* project. It is the methods section for Phase 1: every claim in the README about coverage and counts traces back to a step described here.

## 1. Scope

The corpus covers **28 SIGCHI-related venues** published between **2022 and 2026**, across multiple content types: Research Articles (full peer-reviewed papers), Short Papers, and Extended Abstracts. The decision to include all three content types was driven by the project's downstream goal: detecting online-survey usage across the entire visible output of the SIGCHI community.

Excluded from scope:

- Workshops and tutorial summaries that have no DOI of their own
- Adjunct proceedings tracks that ACM tags as `proceedings` (the parent record), not `proceedings-article`
- Pre-2022 papers, except where an event-year mapping pulls them in (e.g., GROUP '23 PACMHCI papers published in late 2022)

The 28 venues are listed in the README coverage table.

## 2. DOI discovery from ACM

The project scrapes DOIs directly from the ACM Digital Library.

### 2.1 Search-based discovery (the standard path)

For most venues, DOIs were discovered by constructing a faceted search URL on `dl.acm.org` and scraping the results page from a Chrome browser console.

```
https://dl.acm.org/action/doSearch
   ?SpecifiedLevelConceptID=<VENUE_CONCEPT_ID>
   &ContentItemType=<research-article|short-paper|extended-abstract>
   &AfterYear=<YYYY>
   &BeforeYear=<YYYY>
   &pageSize=20
```

`SpecifiedLevelConceptID` is the ACM concept ID for each venue (e.g., CHI = `119596`, HRI = `119235`, RecSys = `119457`). The full mapping is in `docs/VENUE_NOTES.md` (one section per venue).

Each search returned an HTML page; a small JavaScript snippet running in the Chrome console extracted every `<a href="/doi/...">` link, deduplicated, and printed the DOI list. The snippet handled pagination by incrementing the `startPage` query parameter.

### 2.2 PACMHCI journal tracks

Four SIGCHI venues: **ISS**, **GROUP**, **EICS**, **MobileHCI** publish their main-track papers in the ACM journal *Proceedings of the ACM on Human-Computer Interaction* (PACMHCI, ISSN `2573-0142`), not in a conference proc.

For these venues, DOIs were discovered through Crossref, filtering by:

```
issn:2573-0142
from-pub-date:<year>-01-01
until-pub-date:<year>-12-31
issue:<ISS|GROUP|MHCI|EICS>
```

The `issue` field is set by the journal and identifies which conference issue a paper belongs to. Crossref's cursor pagination returned all of them; OpenAlex was used as a parallel source for cross-validation.

**Volume-to-year mapping.** PACMHCI is published continuously, and the `issue` text changed to numeric values in Volume 9 (2025). 

Volume 9 mappings were confirmed by sampling 5 papers from each numeric issue and verifying topical fit against the corresponding conference.

### 2.3 Per-venue keep-lists

Every scrape produced a plain-text DOI list, one per line, saved to `data/keep_lists/<venue>/<venue><yy>_<type>.txt`. Examples:

```
data/keep_lists/chi/chi24_ea.txt
data/keep_lists/recsys/recsys23_ra.txt
data/keep_lists/iss/iss22_ra.txt
data/keep_lists/group/group24_ra.txt
```

These keep-lists are the canonical record of what should be in the corpus. The downloader, organizers, and validators all read from them.

## 3. PDF acquisition

The actual PDFs were downloaded by `scripts/sigchi_downloader.py`, which reads a CSV of DOIs and uses a Chrome browser session to fetch each one.

### 3.1 Why Chrome, not requests

ACM uses Cloudflare to prevent automated bulk downloads. Naive HTTP clients (Python `requests`, `urllib`) hit Cloudflare challenge pages and never receive PDFs. A real Chrome session that has solved the challenge once, however, carries that clearance for subsequent requests.

The downloader uses Python's `webbrowser` module to open `https://dl.acm.org/doi/pdf/<doi>` in Chrome. Chrome, already authenticated and clearance-stamped, downloads the PDF to `~/Downloads/`. The downloader then watches that folder, verifies the file starts with `%PDF-` magic bytes, and moves it to `sigchi/<venue>/<safe_doi>.pdf`.

### 3.2 Concurrency and politeness

The default mode opens 10 DOIs at a time, then waits for downloads to complete before the next batch. After every 200 successful downloads, the script enforces a 5-minute cooldown to avoid tripping ACM's rate limiting.

The downloader is **resumable**: at startup, it scans the destination folder and skips any DOI whose PDF already exists. Interrupting it with `Ctrl+C` and restarting later picks up exactly where it stopped.

### 3.3 Failure modes

- **Cloudflare challenge** : appears if the Chrome session has expired. Solving the challenge once manually restores clearance.
- **PDF not yet published** : for venues with future event dates (e.g., CHI '26 EA scraped before the conference), ACM redirects `/doi/pdf/` to `/doi/abs/`. These DOIs are logged as failures and can be retried after the publication date.
- **Truncated downloads** : caught by the `%PDF-` magic-byte check; invalid files are deleted and the DOI is queued for retry.

## 4. Organization

The downloaded PDFs are first stored flat at `sigchi/<venue>/`, then progressively organized into a two-tier structure:

```
sigchi/
├── <venue>/                      ← Tier 1: raw download landing zone (transient)
└── VERIFIED COUNT/
    └── <venue>/
        └── <year>/
            ├── Research Article/
            ├── Short Paper/
            └── _excluded/        ← Tier 2: organized, verified corpus
```

### 4.1 By year : `organize_by_year.py`

For each venue, the script reads `data/master/acm_dois_classified.csv` to find every DOI tagged for that venue, then queries Crossref for the publication year of each unique proceeding-ID. Each PDF whose `safe_doi` matches a known DOI is moved into `sigchi/<venue>/<year>/`.

### 4.2 By type : `organize_by_type.py`

For each year of a venue, the script reads two keep-lists (`<venue><yy>_ra.txt` and `<venue><yy>_short.txt`). Every PDF whose stem matches a DOI in the RA keep-list moves to `Research Article/`; every PDF matching the Short keep-list moves to `Short Paper/`. Anything left over moves to `_excluded/`. The script is venue-agnostic; the `VENUE`, `KEEP_DIR`, and keep-list filenames are configured per run.

### 4.3 Why this structure

Year-then-type, rather than type-then-year, was chosen because:

- The downstream survey-detection pipeline operates per-paper, not per-year-bucket; the structure is only for human-auditability
- Future content-type discoveries (Late-Breaking, Doctoral Consortium) can be added as new subfolders without restructuring

## 5. Cross-source validation

Every venue × year combination was validated against **two independent bibliographic sources**: Crossref and OpenAlex. The validator (`scripts/validate_count.py`) issues queries to both APIs with the same filter and reports:

- Total matches from Crossref
- Total matches from OpenAlex
- DOIs unique to Crossref (potential OpenAlex gaps)
- DOIs unique to OpenAlex (potential Crossref gaps)

A venue × year is considered **validated** when both sources return the same count and the same DOI set. Where they differed (rare; a handful of cases across the entire corpus), the discrepancy was investigated manually:

- **GROUP '24 PACMHCI** : Crossref returned 9 items; OpenAlex returned 9. The 9th item was an editorial ("PACMHCI V8, GROUP, January 2024 Editorial"), correctly excluded as non-research. Final RA count: 8.
- **GROUP '22 PACMHCI** : initial count was 32 (from a publication-date filter), correct count is 45 (when grouped by PACMHCI Volume 6). Pub-year and event-year diverged because GROUP papers are released across multiple PACMHCI volumes.
- **ISS 2025** : appeared with `issue` field set to numeric "8" rather than "ISS". Confirmed as ISS 2025 by manual topical inspection of 5 sample papers (all surface, gaze, multi-touch topics).

Findings of this kind are logged chronologically in `docs/VALIDATION_LOG.md`.

## 6. Reproducing Phase 1

To rebuild the corpus from scratch on a new machine:

```bash
# 1. Clone the repo
git clone <repo-url>
cd "Who's Answering CHI"

# 2. Install dependencies
pip install -r requirements.txt

# 3. For each venue you want to download, edit the venue/year in
#    scripts/sigchi_downloader.py's CSV input and run:
python scripts/sigchi_downloader.py --csv data/downloads/<venue>_missing.csv

# 4. Organize by year (edit VENUE at the top of the script first)
python scripts/organize_by_year.py

# 5. Organize by content type (edit VENUE, KEEP_DIR, RA_FILE, SHORT_FILE)
python scripts/organize_by_type.py

# 6. Validate against both sources
python scripts/validate_count.py --issn 2573-0142 --year 2024 --issue ISS

# 7. Rebuild the contributor-facing manifest
python scripts/build_manifest.py
```

Chrome must be installed and logged in to `dl.acm.org` (with valid institutional access) for step 3 to succeed. The full corpus is ~130 GB.

## 7. What this phase delivers

When Phase 1 is complete (which it is, as of this commit), the repo contains:

- `data/keep_lists/<venue>/` : per-venue, per-year DOI lists, the canonical record of what was scraped from ACM
- `data/master/acm_dois_classified.csv` : every DOI in the corpus, tagged with its venue
- `data/manifest/papers.csv` : every DOI with its on-disk status (downloaded / missing / excluded)
- `data/manifest/coverage_summary.csv` : per-venue, per-year totals validated against two sources
- `sigchi/VERIFIED COUNT/<venue>/<year>/<type>/` : the actual PDFs (local-only, not in git)

Phase 2 (PDF text extraction) reads from `sigchi/VERIFIED COUNT/` and writes JSON records to `data/extracted/`.