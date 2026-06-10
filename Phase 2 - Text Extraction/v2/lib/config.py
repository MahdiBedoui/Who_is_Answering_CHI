"""Central config for the v2 ensemble pipeline.

The repo holds code only. All large artifacts live in the external data store
(the original working folder). Point every stage at it with --data-store or the
WAC_DATA_STORE environment variable.
"""
from __future__ import annotations

import os
from pathlib import Path

PARSER_VERSION = "v2.0.0"
DEFAULT_VENUE = "CHI"
DEFAULT_YEARS = (2022, 2023, 2024, 2025, 2026)

# Similarity threshold for "two candidates agree" (tune on gold set).
SIM_THRESHOLD = 0.95

API_SOURCES = ("openalex", "crossref", "semanticscholar")
PDF_SOURCES = ("grobid", "pdfplumber", "docling")
ALL_SOURCES = API_SOURCES + PDF_SOURCES


def data_store(cli_value: str | None = None) -> Path:
    root = cli_value or os.environ.get("WAC_DATA_STORE")
    if not root:
        raise SystemExit(
            "ERROR: no data store configured.\n"
            "Pass --data-store <path> or set WAC_DATA_STORE "
            "(path to the local 'Who's Answering CHI' data folder)."
        )
    p = Path(root).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"ERROR: data store not found: {p}")
    return p


def corpus_root(ds: Path) -> Path:
    return ds / "sigchi" / "VERIFIED COUNT"


def tei_dir(ds: Path) -> Path:
    return ds / "data" / "tei"


def docling_dir(ds: Path) -> Path:
    return ds / "data" / "docling"


def sections_dir(ds: Path, section: str) -> Path:
    return ds / "data" / "sections" / section


def reports_dir(ds: Path) -> Path:
    return ds / "data" / "reports"


def add_common_args(parser) -> None:
    parser.add_argument("--data-store", default=None,
                        help="Path to the local data folder (or set WAC_DATA_STORE).")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--years", type=int, nargs="*", default=list(DEFAULT_YEARS))
    parser.add_argument("--limit", type=int, default=0,
                        help="Process at most N papers (0 = all). For smoke tests.")
