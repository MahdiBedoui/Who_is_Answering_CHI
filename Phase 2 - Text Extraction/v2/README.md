# V2 — Ensemble Section Extraction

Implements [`docs/EXTRACTION_V2_PLAN.md`](../../docs/EXTRACTION_V2_PLAN.md).
First section: **abstracts**, CHI 2022–2026, everything in the corpus (RA + EA).

Principle: every extractor runs on every paper; agreement is the confidence signal;
disagreement escalates (OpenAI adjudication → manual queue). Nothing is dropped silently.

## Setup

```bash
pip install -r ../../requirements.txt
pip install docling          # stage 02
pip install openai           # stage 04 --adjudicate
export WAC_DATA_STORE="../Who's Answering CHI"   # or pass --data-store everywhere
export OPENAI_API_KEY=...                        # stage 04 --adjudicate only
```

## Run order (each stage is resumable; re-run = pick up where it stopped)

| Stage | What | Needs | Cost |
|---|---|---|---|
| `00_fetch_api_candidates.py` | OpenAlex + Crossref + S2 abstracts | network | ~2 h once |
| `01_fetch_tei.py` | GROBID → TEI cache | GROBID server (docker-compose / EC2) | hours, parallel |
| `02_docling_corpus.py` | Docling (OCR on) → markdown cache | GPU helps; shard with `--shard K/N` | days, parallel |
| `03_pdf_candidates.py` | TEI + pdfplumber + docling candidates | caches from 01/02 | minutes |
| `04_resolve.py` | resolution table; `--adjudicate` for OpenAI | `OPENAI_API_KEY` | minutes |
| `05_qa_report.py` | QA report + `abstracts_master.csv` | — | seconds |
| `06_gold_eval.py sample` / `eval` | gold set sample / acceptance check | your eyes | ~150 papers |

Smoke test any stage with `--limit 20`. 03–05 are the iteration loop: tweak parsers,
re-run, compare QA report — caches from 01/02 are never recomputed.

All outputs live in the data store (`data/tei/`, `data/docling/`, `data/sections/abstracts/`,
`data/reports/`) **except** gold annotations, which are small and canonical and live in the
repo at `data/gold/abstracts/`.

## Per-paper record

`data/sections/abstracts/CHI/<year>/<doi-key>.json` — all candidates (with provenance,
ligature repairs, timestamps), pairwise agreement scores, and the resolution
(status / text / source / confidence / QA flags / parser version). See `lib/records.py`.

## Next sections

Methods, then discussion/results, reuse the same harness: new boundary parsers in
stage 03, same resolve/QA/gold stages with `--section`. No publisher ground truth exists
for those sections, so PDF-extractor agreement + bigger gold sets carry the validation.
