# Who's Answering CHI?

> A systematic audit of online-survey methodology, and the integrity practices that surround it, across ~16,000 ACM SIGCHI papers (2022–2026).

[![Stage 1](https://img.shields.io/badge/Stage%201%20%E2%80%94%20Corpus-complete-brightgreen)](Phase%201%20-%20Data%20Collection/README.md)
[![Stage 2](https://img.shields.io/badge/Stage%202%20%E2%80%94%20Classification-in%20progress-yellow)](Phase%202%20-%20Text%20Extraction/README.md)
[![Sources](https://img.shields.io/badge/validated-Crossref%20%2B%20OpenAlex-blue)]()
[![License](https://img.shields.io/badge/code-MIT-green)](LICENSE) [![Data](https://img.shields.io/badge/data-CC--BY--4.0-lightgrey)](LICENSE-DATA)

---

## What this project does

We classify every SIGCHI-published paper from 2022–2026 on three questions:

1. **Did the authors run an online survey?** (yes / no + supporting quotes)
2. **If yes, did they use any fraud-detection methods?** (yes / no + which ones + supporting quotes)
3. **If yes, which participant-source platform or panel did they recruit from?** (e.g., Prolific, MTurk, social media, etc. + supporting quotes)

The third question enables sub-analyses across panels and platforms: comparing fraud-defense practices by recruitment source, tracking platform share over time, and crosstabbing venue × platform × method.

The output is a structured dataset (CSV / JSON), one record per paper, that quantifies, for the first time at this scale, how the SIGCHI community collects and protects online-survey data.

## Status

| Stage | Status | Description |
|---|---|---|
| 1. Corpus assembly | ✓ Complete | ~16,000 papers PDFs downloaded, organized, dual-source validated |
| 2. PDF → text (GROBID) | ⏳ In progress | Extract abstract + methods per paper |
| 3. Regex + NLP detection | Planned | Two parallel tracks classify survey usage |
| 4. LLM adjudication | Planned | Resolve regex/NLP disagreements |
| 5. Fraud-method detection | Planned | Same pipeline, second objective |
| 6. Participant-source classification | Planned | Identify recruitment platform / panel per survey paper (Prolific, MTurk, etc.) |
| 7. Gold-standard validation | Planned | 300 hand-labeled papers → precision / recall / F1 / IRR |

## Corpus snapshot (Stage 1)

**~16,000 papers** across **28 venues**, fully validated against Crossref and OpenAlex:

*(The per-venue, per-year DOI keep-lists in [`data/keep_lists/`](data/keep_lists/) are the canonical machine-readable record of what was scraped and validated.)*

## Pipeline architecture

```
                                STAGE 1 (done)
   ┌────────────────────────────────────────────────────────────────┐
   │  ACM DL  ───►  Crossref ───►  OpenAlex                         │
   │       │           │              │                             │
   │       └───── DOI keep-lists ─────┘                             │
   │                       │                                        │
   │                       ▼                                        │
   │              sigchi_downloader.py  (Chrome, Cloudflare-aware)  │
   │                       │                                        │
   │                       ▼                                        │
   │              organize_by_year.py  →  organize_by_type.py       │
   │                       │                                        │
   │                       ▼                                        │
   │   sigchi/VERIFIED COUNT/<venue>/<year>/{RA,Short,_excluded}/   │
   └────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                          STAGES 2–6 (planned)
   ┌────────────────────────────────────────────────────────────────┐
   │  PDFs in sigchi/VERIFIED COUNT/<venue>/<year>/<type>/          │
   │           │                                                    │
   │           ├── Metadata from FOLDER PATH                        │
   │           │      venue, year, content_type                     │
   │           ├── DOI from FILENAME                                │
   │           │      10_1145_X_Y.pdf → 10.1145/X.Y                 │
   │           │                                                    │
   │           ▼                                                    │
   │     GROBID (Docker, ML parser)                                 │
   │           │                                                    │
   │           ▼                                                    │
   │     TEI XML  (abstract, section hierarchy, references)         │
   │           │                                                    │
   │  ┌────────┴────────┐                                           │
   │  ▼                 ▼                                           │
   │ Abstract:          Methods:                                    │
   │  OpenAlex          GROBID section list                         │
   │  (primary,         → lexicon/regex heading classifier          │
   │   by DOI)            (methods-family vs results/discussion)    │
   │  GROBID            → slice methods region verbatim             │
   │  (fallback)        → quality flag: `needs_llm_methods`         │
   │                                  │                             │
   │                                  ▼ (only flagged papers)       │
   │                       LLM section classifier                   │
   │                       (picks correct sections;                 │
   │                        GROBID still slices the text)           │
   │                                                                │
   │  Pydantic-validated JSON  (one record per paper)               │
   │           │                                                    │
   │           ▼                                                    │
   │  ┌──────────────────────────────────────────────────────────┐  │
   │  │       Stage 3: parallel detection on methods text        │  │
   │  └──────────────────────────────────────────────────────────┘  │
   │              ┌───────────┴───────────┐                         │
   │              ▼                       ▼                         │
   │        Regex track               NLP track                     │
   │       (labels A)                (labels B)                     │
   │              │                       │                         │
   │              └──────► Compare ◄──────┘                         │
   │                       │                                        │
   │           ┌───────────┼───────────┐                            │
   │           ▼           ▼           ▼                            │
   │       agree yes   agree no   disagree                          │
   │           │           │           │                            │
   │           │           │           ▼                            │
   │           │           │      LLM decides                       │
   │           │           │           │                            │
   │           ▼           ▼           ▼                            │
   │      LABEL: YES   LABEL: NO   LABEL: yes/no                    │
   │                       │                                        │
   │                       ▼                                        │
   │              Final labels for all ~16,000                      │
   │                       │                                        │
   │                       ▼                                        │
   │         Validate vs 300 hand-labeled papers                    │
   │                       │                                        │
   │                       ▼                                        │
   │              Precision · Recall · F1 · IRR                     │
   └────────────────────────────────────────────────────────────────┘
```

Pipeline is run **three times**: first for online-survey detection (Obj 1), then for fraud-detection methods (Obj 2), then for participant-source classification (Obj 3). Objectives 2 and 3 are restricted to survey-yes papers.

## Repository layout

```
.
├── Phase 1 - Data Collection/     # Corpus assembly + validation code
│   ├── sigchi_downloader.py           # Concurrent, Cloudflare-aware ACM PDF downloader
│   ├── organize_by_year.py            # Bucket PDFs by publication year
│   ├── organize_by_type.py            # Split into RA / Short / _excluded
│   ├── validate_count.py              # Crossref + OpenAlex cross-check
│   ├── find_missing.py                # Find DOIs missing vs Crossref
│   ├── analyze_chi24.py               # Page-count + completeness analysis
│   ├── diff_chi24.py                  # Compare DOI sets across sources
│   ├── build_chi_ea_csv.py            # Build CHI Extended-Abstract CSV
│   ├── audit_chi_ea.py                # Audit CHI EA keep-lists
│   ├── organize_chi_ea.py             # Organize CHI EA PDFs
│   ├── spot_check.py                  # Manual spot-check helper
│   ├── build_manifest.py             # Build contributor-facing manifest
│   └── README.md                      # Phase 1 methodology (corpus build + validation)
├── Phase 2 - Text Extraction/     # PDF → structured JSON code
│   ├── extract_corpus.py              # Production GROBID batch (resumable, 14 workers)
│   ├── extract_paper.py               # Single-PDF debug CLI (thin wrapper over src/)
│   ├── escalate_methods.py            # LLM rescue for low-confidence methods
│   ├── init_db.py                     # Create PostgreSQL schema
│   ├── load_to_db.py                  # Load JSON records into Postgres
│   ├── reorganize_extracted.py        # Maintenance: reshape data/extracted/
│   ├── qa_report.py                   # Extraction QA: coverage + quality stats
│   ├── review_abstracts.py            # Manual review CLI for extracted abstracts
│   ├── compare_grobid_models.py       # A/B compare GROBID model variants
│   ├── fix_abstracts_experiment.py    # Experiment: re-extract failing abstracts
│   ├── docling_abstract_experiment.py # Experiment: Docling as abstract fallback
│   ├── src/                           # Phase 2 library package (imported by the scripts above)
│   │   ├── grobid.py                      # GROBID REST client (PDF → TEI XML)
│   │   ├── extract.py                     # Per-paper PDF → validated record orchestration
│   │   ├── methods.py                     # Methods-section isolation from TEI
│   │   ├── heading_classifier.py          # Regex / LLM / hybrid heading classifiers
│   │   ├── abstract.py                    # OpenAlex-primary abstract selection
│   │   ├── schema.py                      # Pydantic record contract
│   │   ├── models.py                      # SQLAlchemy ORM (papers table)
│   │   ├── db.py                          # Engine/session + schema creation
│   │   └── pdf_fallback.py                # pdfplumber heuristic fallback (debug CLI only)
│   └── README.md                      # Phase 2 methodology (extraction pipeline)
├── data/
│   ├── keep_lists/<venue>/        # Per-venue, per-year DOI lists (canonical record)
│   ├── master/                    # acm_dois_classified.csv + UbiComp full-paper CSVs
│   └── downloads/                 # *_missing.csv (download queues)
├── docker-compose.yml             # GROBID (+ optional local Postgres) for Phase 2
├── requirements.txt               # Python dependencies
├── .gitignore                     # Excludes the 124 GB PDF corpus and local-only files
├── LICENSE                        # MIT (code)
├── LICENSE-DATA                   # CC-BY-4.0 (DOI keep-lists, coverage data)
└── README.md                      # You are here
```

## Quick start

```bash
# 1. Clone + install
git clone <repo-url>
cd "Who's Answering CHI"
pip install -r requirements.txt

# 2. Verify a venue's count against Crossref + OpenAlex
python "Phase 1 - Data Collection/validate_count.py" --issn 2573-0142 --year 2024 --issue ISS

# 3. Download a venue's missing PDFs
python "Phase 1 - Data Collection/sigchi_downloader.py" --csv data/downloads/<venue>_missing.csv

# 4. Organize by year, then by content type
#    (edit VENUE in each script first)
python "Phase 1 - Data Collection/organize_by_year.py"
python "Phase 1 - Data Collection/organize_by_type.py"
```

The 124 GB PDF corpus is **not** in this repo. Run the downloader against the keep-lists in `data/keep_lists/` to reconstruct it locally.

### Local data store

Large local-only artifacts (the `sigchi/` PDF corpus, `data/extracted_cloud/` extraction outputs, caches) live in a separate data-store folder outside the repo. Every script takes its data location as a CLI flag, so point them there explicitly, e.g.:

```bash
DATA_STORE="../Who's Answering CHI"   # adjust to your local path
python "Phase 2 - Text Extraction/extract_corpus.py" --corpus-root "$DATA_STORE/sigchi/VERIFIED COUNT"
python "Phase 2 - Text Extraction/qa_report.py"      --input-dir   "$DATA_STORE/data/extracted_cloud"
```

## Methodology highlights

- **Dual-source validation** : every paper count is confirmed by both Crossref *and* OpenAlex (see `Phase 1 - Data Collection/validate_count.py`)
- **Per-venue ground truth** : keep-lists are scraped directly from ACM DL using venue concept IDs, never inferred
- **Track separation** : main proceedings (proc-style DOIs) and journal tracks (PACMHCI ISS / GROUP / MHCI / EICS issues) are reconciled per event year, not per publication year
- **Type bucketing** : Research Article / Short Paper / `_excluded` mirrors ACM's own ContentItemType taxonomy

Full methodology, including venue-specific de