# Phase 2 - NLP and Regex Detectors

Rules that find, in every paper, the sentences that bear on each question,
settle the papers whose evidence points one way, and hand the rest to the
judge (Phase 3) with the sentences it should read. No API calls.

```
py "Phase 2 - NLP and Regex Detectors/q1_evidence.py"     # module 6, on all papers
py "Phase 2 - NLP and Regex Detectors/q23_evidence.py"    # module 8, on Q1-Yes papers (after module 7 --final)
```

## Module 6: `q1_evidence.py`

**Does:** for each study a paper reports, finds the sentences that bear on
Q1's three checks (CODEBOOK.md: data collected for the results, online,
unmoderated) and routes the paper: settled yes, settled no, or judge.

**Why:** the judge costs money per paper and is only as good as what it is
shown. This module settles the papers that need no judgment, and gives the
judge the right sentences instead of a whole paper.

**How:**
1. **Units.** Sentences in `study` and `unclear` sections (module 4) are
   grouped by the study they belong to ("Study 2"), or `main`. The abstract,
   limitations and appendix form one `context` unit. Prior work, framing and
   other sections are not read.
2. **Cues,** each tied to a check and a direction:

   | cue | check | direction |
   |---|---|---|
   | crowd platform (Prolific, MTurk, CloudResearch...) | online | + (also implies unmoderated and collected) |
   | survey tool (Qualtrics, Google Forms, REDCap...) | online | + |
   | online phrase ("online survey", "web-based experiment", crowdworkers) | online | + |
   | remote data (ESM, interaction logs, telemetry, diary app) | online | + |
   | offline (in person, in the lab, paper questionnaire) | online | - |
   | moderated (Zoom, interviews, workshops, think-aloud, experimenter) | unmoderated | - |
   | unmoderated (self-administered, at their own pace, asynchronous) | unmoderated | + |
   | collected ("we conducted a survey", "312 participants completed") | collected | + |
   | screener ("screening survey", "used only to recruit") | collected | - |

3. **Route per unit.** No online cue: **no**, except a survey with no mode
   stated and nothing moderated, which goes to the **judge**. Only offline
   cues: **no**. Online cue in `context` only: **judge** (never settled from
   the abstract). Screener, moderated or mixed online/offline cues: **judge**.
   Online, collected and unmoderated (or a crowd platform): **yes**. Anything
   else: **judge**.
4. **Route per paper.** Yes if any study unit is yes, no if every unit is
   no, judge otherwise.

**Decisions:** doubt goes to the judge, and a paper is settled no only when
it has no online cue at all. Units are studies, not papers, so a formative
online survey is not hidden by a lab study in the same paper. Platform names
that are also words are matched in their platform spelling ("Prolific" not
before "author"; "AMT", "ESM" only in capitals).

**Result (2026-11-01):** 5,524 papers, 0 errors.

| year | papers | settled yes | settled no | to the judge |
|---|---|---|---|---|
| 2022 | 637 | 42 | 314 | 281 |
| 2023 | 879 | 49 | 431 | 399 |
| 2024 | 1,057 | 52 | 528 | 477 |
| 2025 | 1,249 | 77 | 620 | 552 |
| 2026 | 1,702 | 94 | 792 | 816 |
| all | 5,524 | 314 (5.7%) | 2,685 (48.6%) | 2,525 (45.7%) |

On the 400 round-1 reference papers, settled no held 207 papers and none was a
human Yes: nothing is lost before the judge. Settled yes held 21; the one
paper the old reference called No is Yes under the v2 re-label.

**Output:** `output/q1_evidence/<year>/<pid>.json`, `output/q1_evidence_summary.json`

## Module 8: `q23_evidence.py`

**Does:** for every Q1-Yes paper, finds the sentences that may report a
data-quality check (Q2) or say where participants came from (Q3), tagged
with the codebook category each points to.

**How:**
1. **Reads** `study`, `unclear`, `appendix` and `limits` sections.
2. **Cues:** one pattern list per category (13 Q2 checks, 11 Q3 sources,
   named exactly as in the annotation pages), plus two generic cues:
   exclusion ("excluded", "removed", "failed", "data quality") and
   recruitment ("recruited", "advertised", "invited").
3. **Anchors.** Categories whose words are also HCI topics (bots, VPNs,
   social media, forums) count only when a sentence within one of them is
   about recruiting (Q3) or about excluding or checking data (Q2). On the
   first 390 Q1-Yes papers this cut social-media hits from 2,104 to 181 and
   bot hits from 574 to 137, nearly all removed hits being topic sentences.
4. **Route.** Any cue goes to the judge. A paper with none is settled: no
   checks reported, source not reported.

**Decision:** the rules settle only absence. A cue is not a finding: "we
excluded 3 participants" can be a speed filter, an attention check or
neither, and the judge is cheap here (about 2,300 tokens per paper).

**Output:** `output/q23_evidence/<year>/<pid>.json`, `output/q23_evidence_summary.json`

## Tests

`tests/Phase 2 - NLP and Regex Detectors/`: 16 tests for module 6 (including
the round-1 case of an online survey used only to pick interviewees) and 10
for module 8.
