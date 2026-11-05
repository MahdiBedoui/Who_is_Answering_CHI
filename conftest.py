"""Lets the tests import the scripts of each phase by name (`import extract`).
The phase folders have spaces in their names, so they are folders of
scripts, not Python packages."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
for folder in (ROOT, ROOT / "Phase 1 - Data Preparation", ROOT / "Phase 2 - NLP and Regex Detectors",
               ROOT / "Phase 3 - LLM-as-Judge", ROOT / "RQ 1 - Online Data Collection",
               ROOT / "RQ 2 - Data Quality Checks", ROOT / "RQ 3 - Participant Sources"):
    sys.path.insert(0, str(folder))
