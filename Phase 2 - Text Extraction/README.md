# Phase 2 — Text Extraction

This document describes how the Phase 1 PDF corpus is converted into structured JSON records ready for survey-detection analysis. It is the methods section for Phase 2: every claim downstream about which papers were correctly parsed, which had clean abstracts, and which needed LLM rescue traces back to a step described here.

## 1. Goal

For each of the ~16,000 PDFs assembled in Phase 1, extract three things:

1. **Identity metadata** : DOI, venue, year, content type
2. **Abstract** : the publisher's canonical abstract, clean of PDF-extraction artifacts
3. **Methods section** : the verbatim text of the section(s) where authors describe their study procedure

The output is one JSON record per paper, validated against a Pydantic schema, written to `data/extracted/<venue>/<year>/<content_type>/<safe_doi>.json`.

## 2. Where the metadata comes from

Per-paper metadata is read from the **file path and filename**, not from the PDF content. Phase 1's folder layout is authoritative:

```
sigchi/VERIFIED COUNT/<venue>/<year>/<content_type>/<safe_doi>.pdf
                       │       │            │              │
                       │       │            │              └── DOI: 10_1145_X_Y → 10.1145/X.Y
                       │       │            └── content_type: Research Article / Short Paper
                       │       └── year: 2022..2026
                       └── venue: CHI, HRI, ISS, ...
```

This means a misclassified PDF (a Short Paper sitting in the Research Article folder, for example) carries the folder's label, not its true type. Phase 1's validation step (`validate_count.py`) is what guarantees the folder labels are correct, so Phase 2 can trust them blindly.

## 3. PDF → TEI XML via GROBID

The corpus is processed through **GROBID** (a machine-learning model for scholarly PDFs) running locally in Docker. GROBID returns a TEI XML document with the paper's title, abstract, section hierarchy, and references represented as structured elements rather than positioned text.

GROBID is the only PDF parser used in production. The single-PDF prototype `extract_paper.py` includes a `pdfplumber` fallback for sanity testing on individual papers, but the batch script `extract_corpus.py` does not, because GROBID's structured output is what makes section-aware extraction possible. Falling back to a flat text dump would defeat the purpose of section isolation in Stage 5.

## 4. Abstract extraction

The abstract is pulled from **two sources, in priority order**:

1. **OpenAlex (primary)** : queried by DOI, returns the publisher's canonical abstract. This is the same text ACM displays on the article landing page, free of PDF-extraction artifacts. No hyphenation breaks, no header/footer noise, no two-column reflow errors.
2. **GROBID (fallback)** : the `<abstract>` element from the TEI XML. Used only if OpenAlex has no abstract for that DOI.

Choosing OpenAlex as the primary source is a quality decision. The OpenAlex abstract is consistently cleaner than the GROBID-extracted one, even when GROBID succeeds. The `abstract_source` field in each record tracks which path produced the value, so downstream stages can filter or weight differently if needed.

## 5. Methods section isolation

The methods text is the hardest part of the pipeline. There is no single `<methods>` tag in the TEI XML; the methods region has to be identified by reading the section headings, and HCI papers vary wildly in how they label their methodology (some use "Method", others "Study Design", others split it into "Participants" + "Procedure" + "Apparatus" + "Measures").

### 5.1 Lexicon + regex classifier

The heading classifier lives in `src/methods.py` (`classify_headings_regex`); `extract_corpus.py` just calls it. It walks the GROBID section list in document order and tags **every heading** with one of four labels:

| Tag | Meaning |
|---|---|
| `methods` | a methods-family heading — starts/continues the methods region |
| `exclude` | results / discussion / back-matter — *ends* the methods region |
| `front` | introduction / related work / background — leading filler |
| `other` | unlabeled or ambiguous — kept only if it sits *inside* the methods region |

Matching is case-insensitive and tolerates a leading section number (the prefix `^\s*(?:\d+(?:\.\d+)*\.?\s*)?`), so `3 Method`, `3.1 Participants`, and `Method` all match. The full HCI-aware lexicons are:

```text
methods : method(s), methodolog(y|ies), materials and methods, study design,
          experimental design, research design, procedure(s), participant(s),
          subject(s), material(s), apparatus, measure(s), stimuli,
          data collection, data analysis, recruit(ment|ing), survey design,
          questionnaire, protocol, setup, condition(s), user study,
          field study | field deployment, evaluation(s), task(s)
          + "Study N" / "Experiment N" / "Phase N"

exclude : result(s), finding(s), discussion(s), limitation(s), conclusion(s),
          future work, acknowledge?ment(s), reference(s), bibliography, appendix

front   : introduction, related work, background, motivation, prior work,
          literature review, abstract
```

**Region bounds.** The region starts at the first `methods` heading (or, for a paper with none, the first non-`front` section) and ends at the first `exclude` heading after it (or the end of the paper). `methods_heading_found` records whether any `methods` heading existed at all.

The text in that region is sliced **verbatim** from the TEI. An `other` (non-lexicon) subsection sitting inside a methods run — e.g. "Audio Stimuli" or "Hardware and Software" — is kept, so unusually-named methods subsections are not dropped; only a `front` heading interrupts the run.

The pattern lists in `src/methods.py` are the source of truth; the block above is a readable mirror. The default classifier is regex; an LLM or hybrid classifier (`src/heading_classifier.py`) is a drop-in replacement that tags the same headings.

### 5.2 Two output fields

Each record carries two methods fields:

- **`methods`** : the tight slice bounded by the classifier
- **`methods_context`** : a wider window that also includes the preceding heading ("Study 1", "Experiment 2") and any immediately following sub-sections like "Participants" or "Measures"

The wider window protects Stage 3 detectors against classifier under-bounding. Both fields are made available; downstream code chooses which to read.

### 5.3 Quality flags

After slicing, `methods_quality_flags` (in `src/methods.py`) runs a set of deterministic, no-LLM checks. Any non-empty result routes the paper to LLM rescue (§6). The flags are:

- `no_methods_heading` — no `methods` heading anywhere in the paper
- `empty_methods` — the tight slice came out empty
- `short_methods` — the methods region is under 400 characters (likely truncated by an early "Results" subsection)
- `caption_leak` — the region begins with a figure/table caption
- `multi_study_truncation` — the paper has multiple studies ("Study 1 … Study 2 …") but the captured region misses some of them

Flagged papers get `needs_llm_methods: true` in the record's `extra` map; everything else is considered clean.

## 6. LLM rescue (only for flagged papers)

`escalate_methods.py` is a separate batch script that reads every record with `needs_llm_methods: true`, sends the full TEI section list (headings only, not full text) to an LLM, and asks it to **pick the methods sections by index**. The LLM never generates text; it returns a list of integer indices. The same verbatim-slicing logic from §5 then extracts the text from those sections.

This split (deterministic first pass, LLM rescue for ambiguous cases) keeps the per-paper cost low and the output reproducible. In a typical full-corpus run, fewer than 10% of papers ever reach the LLM.

The escalated record gets `methods_source: "llm_rescue"` so Stage 3 can treat it differently if desired (for example, by sampling more aggressively for the gold-standard validation set).

## 7. Reliability machinery

`extract_corpus.py` is built for unattended overnight runs across ~16,000 PDFs. The reliability primitives are:

- **Concurrency** : 14 worker threads call GROBID in parallel. GROBID is the bottleneck, not Python.
- **Resumable** : at startup, the script scans `data/extracted/` and skips any DOI whose JSON already exists. Killing it with `Ctrl+C` and restarting picks up exactly where it stopped.
- **Per-paper timeout** : 90 seconds per PDF. Papers GROBID cannot parse in that window are skipped and logged.
- **Per-paper isolation** : every exception is caught and written to `_failures.jsonl`. One bad PDF never crashes the run.
- **Circuit breaker** : if ~25 consecutive papers fail (typically because GROBID has crashed or OOM'd), the script aborts with a clear error rather than burning through the rest of the queue.
- **Single retry** : a transient failure (GROBID timeout, OpenAlex 503) triggers one retry before the paper is flagged as a hard failure.

A full corpus run takes roughly 6 hours on a workstation with GROBID running on the same machine.

## 8. Output schema

Each paper produces one file:

```
data/extracted/<venue>/<year>/<content_type>/<safe_doi>.json
```

Schema (validated by Pydantic at write time, not read time):

```json
{
  "doi":                 "10.1145/X.Y",
  "venue":               "CHI",
  "year":                2024,
  "content_type":        "Research Article",
  "title":               "...",
  "abstract":            "...",
  "abstract_source":     "openalex",
  "methods":             "...",
  "methods_context":     "...",
  "methods_source":      "grobid_classifier",
  "needs_llm_methods":   false,
  "extraction_timestamp": "2026-..."
}
```

Validating at write time means a schema mismatch from the LLM rescue (a bad shape, a truncated index list) is caught before it pollutes the dataset Stage 3 reads.

## 9. Database load

The JSON records are loaded into PostgreSQL via `init_db.py` (creates the schema) and `load_to_db.py` (inserts the records). The database is Neon-hosted (cloud Postgres) so Phase 3+ pipelines can query by venue, year, or quality flag without rereading the JSON files.

`reorganize_extracted.py` is a maintenance helper that reshapes the `data/extracted/` directory if a structural change is needed (for example, adding a new content type after the fact).

## 10. Scripts at a glance

The runnable entry points live in this folder; the reusable extraction and storage
logic they import lives in the `src/` package alongside them (`grobid`, `extract`,
`methods`, `heading_classifier`, `abstract`, `schema`, `models`, `db`, `pdf_fallback`).

| Script | Role |
|---|---|
| `extract_paper.py` | Single-PDF debug CLI: a thin wrapper that runs one PDF through the same `src.extract.extract_record` path as the batch, falling back to `src.pdf_fallback` (pdfplumber) only if GROBID is down. Not part of the production run. |
| `extract_corpus.py` | The production batch script. 14 workers, resumable, circuit-breaker. |
| `escalate_methods.py` | LLM rescue for papers flagged `needs_llm_methods: true`. |
| `init_db.py` | Creates the PostgreSQL schema in the Neon database. |
| `load_to_db.py` | Reads `data/extracted/*.json` and inserts them into Postgres. |
| `reorganize_extracted.py` | Maintenance helper for restructuring the output directory. |

## 11. What Phase 2 delivers to Phase 3

A directory of validated JSON records, one per paper, each carrying:

- Authoritative metadata (DOI, venue, year, content type) inherited from Phase 1
- A clean abstract (OpenAlex primary, GROBID fallback)
- A bounded methods section (`methods` + `methods_context`)
- Source-tracking fields (`abstract_source`, `methods_source`) so downstream stages know which path produced each field
- A quality flag (`needs_llm_methods`) so Phase 3 detectors can choose to skip or treat flagged papers differently

Phase 3 (regex track + NLP track for online-survey detection) reads from `data/extracted/` and the PostgreSQL load.
