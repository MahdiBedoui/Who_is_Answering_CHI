# Phase 3 - LLM-as-Judge

An LLM decides the papers the rules (Phase 2) left open, from the paper's own
sentences. It cites sentences by number; the text is looked up here, so a
quote cannot be invented.

Needs `OPENAI_API_KEY` in `.env`.

```
py "Phase 3 - LLM-as-Judge/q1_judge.py" --model gpt-4.1-2025-04-14 --dry     # prompts and size, no API
py "Phase 3 - LLM-as-Judge/q1_judge.py" --model gpt-4.1-2025-04-14           # judge every paper sent on
py "Phase 3 - LLM-as-Judge/q1_judge.py" --model gpt-4.1-2025-04-14 --final   # merge rules + judge
py "Phase 3 - LLM-as-Judge/q23_judge.py"                                     # Q2 and Q3 (gpt-4.1 by default)
py "Phase 3 - LLM-as-Judge/q23_judge.py" --final
```

Both judges are safe to rerun and to interrupt: papers already answered under
the same prompt version and model are never asked again, and stored answers
are re-checked against the current gate before anything new is asked. If
credits run out, rerun the same command.

## Module 7: `q1_judge.py`

**What the model sees:** every sentence of each study unit module 6 could not
settle, in reading order, numbered by its position in the paper and tagged
with its section; plus the cue sentences of the abstract, limitations and
appendix with three neighbours each. Related work and framing are never
shown. Papers over 400 sentences keep the cue sentences and their neighbours.
About 11,000 input tokens per paper.

**What it answers:** per data collection, the three checks (c1 collected,
c2 online, c3 unmoderated) as yes or no, the sentence numbers each rests on,
a best-guess flag, and a few words on how the data was collected. The system
prompt is the codebook.

**The gate** rejects an answer that is not JSON, has a check that is not yes
or no, has a yes on c1 or c2 with no sentence, or cites a sentence it was not
shown. A c3 yes may cite none (nobody present is rarely written down). One
retry; a second rejection leaves the paper `rejected`.

**Q1 is derived here, not taken from the model:** a data collection is Yes
only if all three checks are yes, a paper is Yes if any collection is.

**Prompt versions** (each answer is stored under its prompt version and
model, so nothing is overwritten):

| version | change | why |
|---|---|---|
| q1-v2.0 | first run on the reference | 8% of answers rejected by the gate |
| q1-v2.1 | filler after a no is accepted; c3 yes may rest on absence; crowd tasks are unmoderated unless a session is described | the gate was rejecting valid answers |
| q1-v2.2 | each data collection judged on its own; existing data and the authors' notes fail c1; context survey sentences shown | studies with a survey and interviews were failed on the interviews |
| **q1-v2.3** | sessions around a collection do not moderate it; interviews are moderated in any medium; a formative survey reported as findings counts | real online collections were cancelled by an onboarding or exit interview |

The prompt is frozen at q1-v2.3. Versions were tuned on round-1 papers, so
round 2 is the held-out test.

**Model:** `gpt-4.1-2025-04-14`, temperature 0. On round 1 under the v2
codebook it scored precision 0.98 and recall 0.97, against 0.87 and 0.71 for
gpt-4o-mini (see RQ 1).

**Corpus run:** 2,525 papers judged, 9 without a valid answer after two
attempts (rerun to retry). About 10,600 input and 300 output tokens per
paper; about $55 at OpenAI's 2026 prices.

**Output:** `output/q1_judge/<prompt version>/<model>/<year>/<pid>.json` (one
per judged paper, with the sentences shown, every raw answer and the checked
answer), `output/q1_final.jsonl` (one row per paper: Q1, source rule or
judge, and per data collection the three checks with their sentence numbers)

## Module 9: `q23_judge.py`

**What the model sees:** the paper's online data collections (from module 7)
and module 8's sentences, numbered. About 2,300 input tokens per paper.

**What it answers:** the data-quality checks reported on that online data,
each with sentence numbers and a few words; whether the paper says it used
none; the participant sources, each with sentence numbers. Categories are the
codebook's.

**Rules in the prompt:** a check counts only if applied to the paper's own
online data; an exclusion with a stated reason goes in that reason's
category, one with no reason is "other: unexplained exclusion"; a platform
filter such as "US residents, approval above 95%" is two checks
(qualification / screener and reputation filter); Qualtrics as a survey tool
is not a source, a Qualtrics panel is.

**The gate** rejects unknown categories, a category with no sentence or one
it was not shown, "other" without saying what, and a stated absence with no
sentence.

**Model and prompt:** `gpt-4.1-2025-04-14`, temperature 0, `q23-v1.0`.

**Output:** `output/q23_judge/<prompt version>/<model>/<year>/<pid>.json`,
`output/q23_final.jsonl` (one row per Q1-Yes paper, with the sentence text
behind every category)

## Tests

`tests/Phase 3 - LLM-as-Judge/`: both judges with a stub model in place of
the API (what is shown, numbering, derivation of Q1, every gate rule, the
retry).
