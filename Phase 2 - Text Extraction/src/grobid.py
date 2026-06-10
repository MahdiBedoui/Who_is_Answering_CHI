"""Thin GROBID REST client for full-text TEI extraction."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import requests


def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)


def process_fulltext(
    pdf_path: Path,
    grobid_url: str = "http://localhost:8070",
    consolidate_header: bool = False,
    timeout: int = 90,
    retries: int = 2,
    backoff: float = 3.0,
) -> Optional[str]:
    """POST a PDF to GROBID's processFulltextDocument endpoint; return TEI XML or None.

    Header consolidation (Crossref lookups) is OFF by default: the corpus already
    has validated DOIs, and consolidation roughly triples per-paper latency.

    A short timeout (default 90s) plus a couple of retries with backoff means a
    transient stall self-heals, and a dead server costs ~90s per paper instead of
    the old 300s -- so an outage no longer silently burns hours.
    """
    endpoint = grobid_url.rstrip("/") + "/api/processFulltextDocument"
    last_exc = None
    for attempt in range(retries + 1):
        try:
            with pdf_path.open("rb") as fh:
                resp = requests.post(
                    endpoint,
                    files={"input": (pdf_path.name, fh, "application/pdf")},
                    data={
                        "consolidateHeader": "1" if consolidate_header else "0",
                        "consolidateCitations": "0",
                        "includeRawCitations": "0",
                    },
                    timeout=timeout,
                )
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            log(f"[grobid] WARNING: request failed for {pdf_path.name}: {exc}")
            return None
        if resp.status_code == 200:
            return resp.text
        # 503 == GROBID busy/overloaded: worth a retry; other codes are not.
        if resp.status_code == 503 and attempt < retries:
            time.sleep(backoff * (attempt + 1))
            continue
        log(f"[grobid] WARNING: HTTP {resp.status_code} for {pdf_path.name}")
        return None
    if last_exc is not None:
        log(f"[grobid] WARNING: giving up on {pdf_path.name}: {last_exc}")
    return None
