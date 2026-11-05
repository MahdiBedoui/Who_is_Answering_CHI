"""Paths and constants shared by every module.

The corpus root comes from the CHI_CORPUS environment variable. Nothing in this package ever writes inside the corpus.
"""
import os
import pathlib

from dotenv import load_dotenv

REPO = pathlib.Path(__file__).resolve().parent
load_dotenv(REPO / ".env")

CORPUS = pathlib.Path(os.environ.get("CHI_CORPUS", "")).expanduser()
OUTPUT = REPO / "output"

# Human annotations (round 1, round 2, the v2 re-label). Released separately from the code;
# point ANNOTATIONS at the folder once you have it. The evaluate_* scripts need it, nothing else does.
ANNOTATIONS = pathlib.Path(os.environ.get("ANNOTATIONS") or REPO / "data" / "annotations").expanduser()

# Optional: the folder of v1's pipeline, for comparing v1 with v2. Without it the comparison is skipped.
V1_DIR = pathlib.Path(os.environ["V1_DIR"]).expanduser() if os.environ.get("V1_DIR") else None

YEARS = ("2022", "2023", "2024", "2025", "2026")

# Research Articles per year in the ACM Digital Library, the population the
# paper is about. Everything downstream is checked against these.
EXPECTED = {"2022": 637, "2023": 879, "2024": 1057, "2025": 1249, "2026": 1702}


def corpus_year_dir(year: str) -> pathlib.Path:
    """The folder of Research Article PDFs for one year. ACM's export named
    the 2026 folder 'Research Articles' (plural); the others are singular."""
    for name in ("Research Article", "Research Articles"):
        p = CORPUS / year / name
        if p.is_dir():
            return p
    raise FileNotFoundError(f"no Research Article folder under {CORPUS / year}")


def require_corpus() -> None:
    if not CORPUS or not CORPUS.is_dir():
        raise SystemExit(
            "CHI_CORPUS is not set or does not exist. Copy .env.example to .env and "
            "point CHI_CORPUS at the folder that holds <year>/Research Article*/*.pdf")
