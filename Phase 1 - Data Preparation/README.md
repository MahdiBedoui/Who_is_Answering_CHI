# Phase 1 - Data Preparation

From the PDFs to numbered sentences, each knowing its section and what that
section is for. Six modules are run in order and each reads the previous one's
output from `output/`.

```
py "Phase 1 - Data Preparation/inventory.py"    # module 0
py "Phase 1 - Data Preparation/ligatures.py"    # module 1
py "Phase 1 - Data Preparation/extract.py"      # module 2 (skips papers already done; --force to redo)
py "Phase 1 - Data Preparation/sections.py"     # module 3
py "Phase 1 - Data Preparation/zones.py"        # module 4
py "Phase 1 - Data Preparation/sentences.py"    # module 5 (about 10 minutes)
```

Only modules 0 to 2 read the PDFs. PyMuPDF is pinned (1.28.2) in
`requirements.txt`: another version cuts pages into different blocks and
changes the reading order.

## Module 0: `inventory.py`

**Does:** one row per PDF with its DOI, year, size, SHA-256 hash, page count
and whether it opens with text. Compares the count per year with
`config.EXPECTED` and exits with an error if they differ.

**Why:** it is the only check of the population the paper claims (637 / 879 /
1,057 / 1,249 / 1,702 Research Articles, the counts in ACM DL and dblp). It is
also what is published instead of the PDFs, which ACM's licence does not let
us share: anyone with library access can rebuild the corpus and check the
hashes. Unreadable files are flagged, never dropped.

**Result:** 5,524 PDFs, counts match every year, all readable.

**Known issue:** 16 groups of byte-identical files under different DOIs, 38
files in all, mostly 2025 and 2026. The lowest DOI in each group holds the
right paper (checked on one group against Crossref); the others are copies
of it from the ACM DL repeating a response during download. Until those 22
files are downloaded again, 22 papers are analysed with another paper's
text. `output/inventory_summary.json` lists them under `duplicate_files`.

**Output:** `output/inventory.jsonl`, `output/inventory_summary.json`

## Module 1: `ligatures.py`

**Does:** corrects, in memory, the rows of each font's text table that are
wrong for ligature glyphs (fi, ff, fl, ffi, ffl, and rarer ones such as Qu).
Every later module opens PDFs through `open_repaired()`. The file on disk is
never written.

**Why:** in many ACM PDFs the table maps the "fi" glyph to "f", so "Prolific"
is extracted as "Prolifc" and "first" as "frst". The page looks right; only
extracted text is broken, and it breaks exactly the words this study
searches for.

**How:** each font also names its glyphs, and a ligature is named after its
letters (`f_i`, `f_f_i`). The name is the ground truth: rows that disagree
with it are rewritten, everything else is left byte for byte unchanged. A
ligature glyph whose name cannot be read is reported, never guessed.

**Result:** 2,177 of 5,524 papers needed repair (39%: about 70% in 2022 to
2024, 24% in 2025, 3% in 2026), 29,078 rows rewritten. Every paper fully
repaired, and no other row changed in any table. v1 repaired 2,167 and missed
7 CHI 2023 papers entirely (their v1 text still read "fnger", "afordance").

**Output:** `output/ligatures.jsonl`, `output/ligatures_summary.json`

## Module 2: `extract.py`

**Does:** reads every page and writes its text as blocks in the order a
person reads a two-column page. Each block has its page, column, position
and a kind: `text`, `heading`, `caption`, `table`, `footnote`, `reference`,
`header`, `front_matter`, `notice`, `small_text`, `large_text`. The PDF's
outline is saved too.

**Why:** a PDF stores text as positioned pieces in no particular order.
Read naively, a two-column page interleaves its columns. Everything after
this module needs the right order, decided once.

**How:**
1. Lines are rebuilt from positions (pieces within 3.5 pt vertically are one
   line).
2. A block holding a line of each column is split at the gutter.
3. Full-width blocks cut the page into bands; each band is read left column,
   then right.
4. Kinds come from size and position: running headers end above 73 pt or
   repeat at the top of three pages; captions start "Figure N:" or
   "Table N."; table cells sit next to a "Table N" caption. Nothing is
   deleted, only labelled.

**Verified:** besides the tests, every page was compared once with a second,
unrelated reader (pdftotext 22.02), and about 200 pages, most drawn at random,
were read by eye against numbered blocks. The audit script needs Poppler and
is not part of this release; its results are summarised here. Reading order was right on all unflagged pages read
(0 of 56 wrong, so under about 5% at 95%). With block kinds, 91% of
sentences cut at a column end and 88% cut at a page end are carried on by the
next text block. Known limits: a table with no "Table N" caption, or display
equations, can still come out as text.

**Result:** 5,524 papers, 101,840 pages, 2,259,900 blocks, 0 errors. 10
papers have no outline.

**Output:** `output/text/<year>/<pid>.json`, `output/text_summary.json`

## Module 3: `sections.py`

**Does:** cuts each paper into sections, each with its title, level, role
(abstract, body, references, appendix...) and where it starts and ends in
module 2's blocks. Nothing is copied: a section is a pair of positions.

**Why:** where something is said matters. A platform named in the method
section is evidence; the same name in related work is someone else's study.

**How:** headings come from the PDF's own outline, which ACM builds from the
authors' LaTeX, and are found on the page in order (so "Results" under
Study 1 and Study 2 are matched in turn). Fallbacks: a long title split
across lines, a close match, a heading inside running text, one page off.
Papers with no usable outline are cut at module 2's heading blocks. An
entry that cannot be found is reported, never placed by guess.

**Result:** 168,982 sections, 0 errors. 137 outline entries in 79 papers not
found (0.09%). Checked on all papers: sections tile the paper with no gap or
overlap, and first-level numbers increase.

**Output:** `output/sections/<year>/<pid>.json`, `output/sections_summary.json`

## Module 4: `zones.py`

**Does:** labels every section by what it is for: `study`, `limits`,
`appendix`, `abstract`, `prior_work`, `framing` (introduction, conclusion),
`other` (discussion, system description), `apparatus` (title block,
keywords, references), or `unclear`. Labels come from titles only, by the
first rule that applies: a list of known titles, related-work vocabulary,
study-like subsections, title patterns, the parent section's label.

**Why:** "we recruited 300 participants on Prolific" in a method section is
evidence about this paper; in related work it is not.

**Read by default:** `study`, `limits`, `appendix`, `abstract`, `unclear`
(62% of running text). Every section keeps its text; each detector states
which labels it reads.

**Verified:** 96.8% of the 1,581 quote fragments annotators gave in round 1
lie in sections read by default (Q1 92%, Q2 98%, Q3 99.6%). Most of the Q1
remainder is in introductions that announce the study the method section
describes again.

**Output:** `output/zones/<year>/<pid>.json`, `output/zones_summary.json`

## Module 5: `sentences.py`

**Does:** turns each section's running text into sentences. Each sentence
knows its section, page and block, and is numbered by its position in the
paper: these numbers are what the judge (Phase 3) cites.

**How:**
1. A block that stops mid-sentence takes the next text block as its
   continuation, across a column or page break and over a caption, table or
   footnote in between.
2. Line-end hyphens are removed or kept by the paper's own vocabulary
   ("semi-structured" printed whole keeps its hyphen; "evalua- / tion" loses
   it).
3. Sentences are cut at ".", "?" or "!" followed by a capital, digit, quote
   or bracket; not after "et al.", "e.g.", "Fig.", initials or list numbers.
   No sentence-splitting library: the rules are short and each has a test.

Wording is never changed. Sentences never cross a section boundary;
`apparatus` sections are left out.

**Result:** 2,648,721 sentences of running text (67% in sections read by
default), 0 errors. 6.1% were joined from two blocks.

**Verified:** 89% of round-1 quote fragments are found whole in the sentence
list; the rest are annotators' notes rather than quotes, or quotes copied
with the broken ligatures module 1 repairs.

**Output:** `output/sentences/<year>/<pid>.json`, `output/sentences_summary.json`

## Tests

`tests/Phase 1 - Data Preparation/`: one file per module, built on small
hand-made inputs; none needs the corpus.
