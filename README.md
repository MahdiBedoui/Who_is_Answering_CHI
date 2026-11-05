# Who's Answering CHI?

A census of how CHI papers collect data online, and how they protect it:
every Research Article at CHI 2022-2026 (5,524 papers), classified by a
rules-then-LLM pipeline and validated against human annotations.

## What this project does

Every paper is classified on three questions (the full rules are in
[CODEBOOK.md](CODEBOOK.md)):

1. **Q1. Does the paper rest on data collected online, with no researcher
   present?** Yes only if all three hold for at least one of its data
   collections: data was collected from participants for the results, it
   was collected online, and nobody from the research team was there.
   (yes / no, with the sentences it rests on)
2. **Q2. If yes, which data-quality checks do the authors report?**
   Attention checks, speed filters, bot detection, reputation filters and
   nine more categories. (which checks, with their sentences)
3. **Q3. If yes, where did the participants come from?** Prolific, MTurk,
   CloudResearch, social media, university pools and more. (which sources,
   with their sentences)

Q3 makes the sub-analyses possible: quality checks by recruitment source,
platform share over time.

The output is one record per paper, every answer traceable to the paper's
own sentences.

## Corpus snapshot

| Year | Research Articles |
|---|---|
| 2022 | 637 |
| 2023 | 879 |
| 2024 | 1,057 |
| 2025 | 1,249 |
| 2026 | 1,702 |
| **Total** | **5,524** |

Counts match the ACM Digital Library for every year.

## Pipeline architecture

```
                      CHI Research Articles (PDFs)
                        5,524 papers, 2022-2026
                                   │
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ PHASE 1 - DATA PREPARATION                                       │
   │                                                                  │
   │ 0 inventory    DOI, SHA-256, page count; counts vs ACM           │
   │        │                                                         │
   │        ▼                                                         │
   │ 1 ligatures    repair "fi", "ff", "fl" in the text layer         │
   │        │                                                         │
   │        ▼                                                         │
   │ 2 extract      blocks in reading order, labelled by kind         │
   │        │                                                         │
   │        ▼                                                         │
   │ 3 sections     where each section starts and ends                │
   │        │                                                         │
   │        ▼                                                         │
   │ 4 zones        method, related work, limitations, ...            │
   │        │                                                         │
   │        ▼                                                         │
   │ 5 sentences    numbered, tagged with section and study           │
   └──────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ PHASE 2 - NLP AND REGEX DETECTORS        (once per question)     │
   │                                                                  │
   │ Regex: cue patterns per sentence                                 │
   │        Prolific, MTurk, "online survey", Zoom, interview, lab    │
   │ NLP:   each cue placed by section and study, and read as         │
   │        evidence for or against each check                        │
   │                           │                                      │
   │               ┌───────────┼───────────┐                          │
   │               ▼           ▼           ▼                          │
   │           agree yes    agree no    conflict / unclear            │
   │               │           │           │                          │
   └──────────────────────────────────────────────────────────────────┘
                   │           │           ▼
                   │           │       ┌──────────────────────────────┐
                   │           │       │ PHASE 3 - LLM AS JUDGE       │
                   │           │       │ reads the sentences, decides │
                   │           │       │ and cites them by number;    │
                   │           │       │ every citation is checked    │
                   │           │       └──────────────────────────────┘
                   ▼           ▼           ▼
                  YES         NO        yes / no
                   │           │           │
                   └───────────┴───┬───────┘
                                   ▼
                        Q1 for all 5,524 papers
                                   │
                                   ▼
                             Q1 Yes papers
                                   │
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ PHASE 2 + PHASE 3 AGAIN, ON Q1 YES PAPERS ONLY                   │
   │                                                                  │
   │ Detectors find sentences on quality checks and recruiting;       │
   │ the judge decides which checks and which sources are reported    │
   └──────────────────────────────────────────────────────────────────┘
                 │                                   │
                 ▼                                   ▼
       Q2: data-quality checks            Q3: participant sources
                 │                                   │
                 └─────────────────┬─────────────────┘
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ VALIDATION: RQ 1, RQ 2, RQ 3                                     │
   │                                                                  │
   │ Validate vs human annotations: precision, recall, F1, kappa      │
   │ Writes output/results/: one validation file per question         │
   └──────────────────────────────────────────────────────────────────┘
```

Phases 2 and 3 run twice: first for Q1 on every paper, then for Q2 and Q3 on
the Q1 Yes papers only.

## Repository layout

```
.
├── Phase 1 - Data Preparation/          # PDFs -> numbered sentences
│   ├── inventory.py                         # Module 0: corpus manifest, counts vs ACM
│   ├── ligatures.py                         # Module 1: ligature repair in memory
│   ├── extract.py                           # Module 2: text blocks in reading order
│   ├── sections.py                          # Module 3: section boundaries
│   ├── zones.py                             # Module 4: what each section is for
│   ├── sentences.py                         # Module 5: numbered sentences
│   └── README.md                            # Methods, checks and findings per module
├── Phase 2 - NLP and Regex Detectors/   # Evidence per question, clear papers settled
│   ├── q1_evidence.py                       # Module 6: Q1 cues and routing
│   ├── q23_evidence.py                      # Module 8: Q2 and Q3 cues
│   └── README.md
├── Phase 3 - LLM-as-Judge/              # Decides the rest, citing sentences
│   ├── q1_judge.py                          # Module 7: Q1, three checks per data collection
│   ├── q23_judge.py                         # Module 9: quality checks and sources
│   └── README.md                            # Prompts, versions, gate rules
├── RQ 1 - Online Data Collection/
│   └── evaluate_q1.py                       # Validation vs human annotations
├── RQ 2 - Data Quality Checks/
│   └── evaluate_q2.py
├── RQ 3 - Participant Sources/
│   └── evaluate_q3.py
├── tests/                               # Unit tests, one folder per phase
├── CODEBOOK.md                          # The three questions and their rules
├── config.py                            # Paths and constants (reads .env)
├── rq_utils.py                          # Shared by the RQ scripts
├── conftest.py                          # Lets the tests import each folder's scripts
├── requirements.txt                     # Python dependencies (PyMuPDF pinned)
├── .env.example                         # Settings to copy into .env
├── output/                              # Everything the scripts write (gitignored)
└── README.md                            # You are here
```

## Quick start

```
# 1. Install
pip install -r requirements.txt
copy .env.example .env        # set CHI_CORPUS and OPENAI_API_KEY

# 2. Phase 1: PDFs to sentences
py "Phase 1 - Data Preparation/inventory.py"
py "Phase 1 - Data Preparation/ligatures.py"
py "Phase 1 - Data Preparation/extract.py"
py "Phase 1 - Data Preparation/sections.py"
py "Phase 1 - Data Preparation/zones.py"
py "Phase 1 - Data Preparation/sentences.py"

# 3. Q1: rules, then the judge
py "Phase 2 - NLP and Regex Detectors/q1_evidence.py"
py "Phase 3 - LLM-as-Judge/q1_judge.py" --model gpt-4.1-2025-04-14
py "Phase 3 - LLM-as-Judge/q1_judge.py" --model gpt-4.1-2025-04-14 --final

# 4. Q2 and Q3: rules, then the judge, on Q1 Yes papers
py "Phase 2 - NLP and Regex Detectors/q23_evidence.py"
py "Phase 3 - LLM-as-Judge/q23_judge.py"
py "Phase 3 - LLM-as-Judge/q23_judge.py" --final

# 5. Validation
py "RQ 1 - Online Data Collection/evaluate_q1.py"
py "RQ 2 - Data Quality Checks/evaluate_q2.py"
py "RQ 3 - Participant Sources/evaluate_q3.py"

# 6. Tests
py -m pytest tests -q
```

The PDFs are not in this repo: ACM's licence does not allow sharing them.
`output/inventory.jsonl` lists every paper by DOI and SHA-256, so the corpus
can be rebuilt from the ACM Digital Library and checked. The human
annotations are released separately; set `ANNOTATIONS` in `.env` to use the
`evaluate_*` scripts. The judges cost about $55 (Q1) and $10 (Q2 and Q3) at
OpenAI's 2026 prices, and skip papers already answered, so a run can be
interrupted and resumed.


