# Extraction V2 — Design Plan (for review)

**Objective:** accurate and complete extraction of designated sections — abstract first, then
methods, then discussion/results — from all CHI papers 2022–2026 (~7,210 PDFs).
Cost is explicitly *not* a constraint; accuracy and completeness are the only objectives.

**Status: DRAFT — review before any code is written.**

---

## 1. Core principles

1. **Ensemble, not cascade.** Every extractor runs on every paper. Agreement between
   independent extractors is the confidence signal; disagreement is escalated, never
   silently resolved. (V1's failure: GROBID output was accepted with no gate — ~16%
   ligature loss and ~14% mid-sentence truncation went undetected.)
2. **One section at a time, stored separately.** Each section gets its own pipeline run,
   its own per-paper records, its own gold set, and its own QA report. Re-running the
   methods parser can never touch validated abstracts.
3. **Expensive intermediates are cached once.** GROBID TEI XML and Docling output are
   persisted per paper in the data store. Section extraction is a re-runnable parsing
   pass over cached artifacts — PDFs are read at most twice (GROBID, Docling).
4. **Nothing is "done" by default.** A paper exits the pipeline only as
   `resolved` (with provenance + confidence) or `manual_queue`. No silent gaps.
5. **Agreement ≠ correctness.** A stratified, hand-verified gold set provides the
   absolute accuracy number per parser version before its output is trusted.

## 2. Candidate extractors (abstracts)

| # | Source | Type | Notes |
|---|--------|------|-------|
| A | OpenAlex | API (publisher-derived) | Reference candidate. Author-supplied text, no parsing. Known gaps: 175 (2025), 43 (2026). |
| B | Crossref | API (publisher-deposited) | Overlaps OpenAlex ingestion but query independently; client code exists from Phase 1. |
| C | Semantic Scholar Graph | API | Independent ingestion path; good recent coverage. |
| D | GROBID TEI `<abstract>` | PDF (ML) | Kept as a *candidate/cross-check*, never sole source. TEI cached for methods/discussion anyway. |
| E | pdfplumber + layout regex | PDF (deterministic) | Slice page-1 text between `ABSTRACT` and `CCS CONCEPTS`/`KEYWORDS`. Transparent failure modes. |
| F | Docling (OCR-capable path) | PDF (ML + OCR) | Runs on **all** papers (~7.6 machine-days, parallel on EC2 per `cloud/AWS_RUNBOOK.md`). OCR recovers ligatures/broken ToUnicode that defeat D and E. |

## 3. Normalization (applied before any comparison)

- Unicode NFKC; collapse whitespace; join hyphenated line breaks (`exam-\nple` → `example`).
- Ligature repair: deterministic wordlist (`afect→affect`, `signifcant→significant`,
  `difcult→difficult`, …) built from corpus scan; applied to PDF-derived candidates only,
  every repair logged.
- Strip leading `Abstract`/`ABSTRACT` token and trailing CCS/keyword bleed.
- Comparison form: lowercased, punctuation-light. **Stored form: original casing/punctuation.**

## 4. Resolution logic (per paper)

Pairwise similarity on normalized comparison forms (normalized Levenshtein; threshold
**0.95 = agree**, tune on gold set).

| Case | Outcome |
|---|---|
| Publisher text (A/B/C) exists and ≥1 PDF candidate agrees | `resolved` — publisher form, confidence `high` |
| Publisher candidates agree with each other; no PDF agreement | `resolved` — publisher form, confidence `high`, flag `pdf_divergent` (feeds §7 text-layer risk list) |
| No publisher text; ≥2 PDF candidates agree | `resolved` — Docling form preferred (OCR path), confidence `medium` |
| Candidates conflict below threshold | `adjudicate` — LLM judge sees all candidates + page-1 render, picks/reconstructs, output flagged `llm_adjudicated` |
| All extractors empty/failed | `manual_queue` |

LLM-adjudicated and manual items are disproportionately sampled into the gold set.

## 5. QA gates (flags recorded on every record)

`too_short` (<400 chars) · `too_long` (>3000) · `no_end_punct` · `ccs_bleed` ·
`ligature_artifact` (post-repair residue) · `non_english` · `mid_sentence_start` ·
`source_disagreement_score`. Flags never silently drop a record — they route it.

## 6. Gold set & acceptance

- **Size/stratification:** ~150 papers, stratified by year (5) × type (RA/Short), with
  oversampling of `llm_adjudicated`, `manual_queue`, and `pdf_divergent` records.
- **Protocol:** human verifies the resolved abstract against the PDF (exact-match after
  normalization; char-level F1 as secondary metric).
- **Acceptance to promote a parser version:** ≥99% exact-match on gold set; every miss
  triaged into a failure-mode note before re-run.
- Gold annotations live in `data/gold/abstracts/` (repo-tracked — they're small and canonical).

## 7. Why this also de-risks methods & discussion

The abstract run doubles as a **text-layer census**: papers where PDF extractors diverge
from publisher text get flagged once, and that risk list carries into methods/discussion
extraction — where there is *no* publisher ground truth and the careful path
(Docling/adjudication) must be chosen up front.

## 8. Pipeline & layout

**Repo — `Phase 2 - Text Extraction/v2/`** (V1 scripts remain untouched until V2 is accepted):

```
00_fetch_api_candidates.py   # A, B, C → per-paper candidate records
01_fetch_tei.py              # GROBID → cached TEI (resumable, parallel)
02_docling_corpus.py         # Docling → cached output (resumable, EC2)
03_pdf_candidates.py         # D (from TEI cache), E (pdfplumber) → candidates
04_resolve.py --section abstract   # normalize → compare → resolve/flag
05_qa_report.py --section abstract # coverage, agreement dist, flag counts, per-year
06_gold_eval.py --section abstract # sample, eval, acceptance check
```

**Data store (`../Who's Answering CHI/`, never in git):**

```
data/tei/CHI/<year>/<doi>.tei.xml          # cached GROBID (~1 GB)
data/docling/CHI/<year>/<doi>.json         # cached Docling output
data/sections/abstracts/CHI/<year>/<doi>.json
```

Per-paper section record: all candidates (raw + normalized), pairwise scores, resolved
text, `source`, `confidence`, `parser_version`, flags, timestamps. Analysis-time merge
only; a flat `abstracts_master.csv` is generated by `05_qa_report.py`.

## 9. Execution order

1. Build harness + run **abstracts end-to-end** (validates the whole architecture on the
   section with the best ground truth).
2. Gold-set eval → fix → re-run until acceptance.
3. **Methods**: same ensemble minus A/B/C (no publisher text); boundary logic = heading
   classifier over TEI + Docling structure; agreement between D/E/F is the only automatic
   signal, so gold set grows to ~200.
4. **Discussion/Results** likewise.

## 10. Decisions (resolved 2026-06-10)

1. **Scope:** everything under `VERIFIED COUNT/CHI/` — research articles *and* extended
   abstracts (~7,210 PDFs).
2. **LLM adjudicator:** OpenAI (`OPENAI_API_KEY`).
3. **Gold set workflow:** single rater (Mahdi), no IRR.
4. **2026 corpus:** extract what is in the local folder; no snapshot freeze. Records carry
   timestamps, so late additions can be extracted incrementally (every stage is resumable).
