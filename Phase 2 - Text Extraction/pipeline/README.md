# Abstract extraction pipeline (CHI 2022–2026)

Three steps. Each step is one script, one output file.

| Step | Script | Output |
|---|---|---|
| 1. Get abstracts from OpenAlex | `step1_get_openalex.py` | `data/openalex/abstracts_openalex.csv` |
| 2. Analyze what's missing | `step2_whats_missing.py` | `data/openalex/missing_openalex.csv` + printed report |
| 3. Handle the missing | decided after looking at step 2 | — |

All outputs go to the data store (the original "Who's Answering CHI" folder).
Set it once per terminal: `set WAC_DATA_STORE=C:\Users\H¨P\Desktop\Who's Answering CHI`

Step 1 is resumable (rerun continues where it stopped) and reuses answers already
fetched in earlier runs, so it completes in minutes, not hours.

The earlier multi-source pipeline (`../v2/`) still exists for when we want
cross-validation; this folder is the simple, step-by-step path.
