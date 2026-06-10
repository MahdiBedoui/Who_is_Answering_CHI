"""pdfplumber heuristic fallback for the single-PDF debug CLI.

GROBID is the only parser used in the production batch (`extract_corpus.py`).
This module exists ONLY so the single-PDF debug tool (`extract_paper.py`) can
still produce a best-effort record when GROBID is unreachable.

It deliberately reuses the production methods lexicon (`METHODS_RE`, `EXCLUDE_RE`,
`STUDY_RE` from `src.methods`) instead of carrying its own copy, so the heuristic
parser stays in step with the real classifier rather than drifting — which is
exactly what the old standalone prototype did.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .methods import EXCLUDE_RE, METHODS_RE, STUDY_RE


def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)


def normalize_doi(raw: str) -> str:
    """Strip URL/prefix noise from a DOI string and return the bare DOI."""
    if not raw:
        return ""
    raw = raw.strip()
    raw = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^doi:\s*", "", raw, flags=re.IGNORECASE)
    m = re.search(r"10\.\d{3,}/\S+", raw)
    return m.group(0).rstrip(".,;)") if m else ""


def _regex_abstract(full_text: str) -> str:
    """Heuristically extract the abstract block from raw PDF text."""
    m = re.search(
        r"(?is)\bAbstract\b[\s:]*\n?(.*?)(?:\n\s*(?:CCS\s+Concepts|Keywords|KEYWORDS|"
        r"ACM\s+Reference|1\s+Introduction|1\.\s+Introduction|Introduction)\b)",
        full_text,
    )
    if not m:
        return ""
    text = re.sub(r"[ \t]+", " ", m.group(1)).strip()
    text = re.sub(r"\n{2,}", "", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return text.strip()


def _looks_like_heading(line: str) -> bool:
    """Heuristic: does this line look like a section heading?"""
    if not line or len(line) > 80:
        return False
    if re.match(r"^\d+(?:\.\d+)*\.?\s+\S", line):  # numbered heading
        return True
    words = line.split()
    if 1 <= len(words) <= 8 and line[0].isupper() and not line.endswith("."):
        return True
    return False


def _regex_methods(lines: List[str]) -> str:
    """Heuristically extract methods-family sections from line-split PDF text.

    Uses the same lexicon as the production TEI classifier (src.methods).
    """
    blocks: List[str] = []
    current_heading: Optional[str] = None
    buffer: List[str] = []
    keep_active = False

    def flush() -> None:
        nonlocal buffer, current_heading
        text = "\n".join(buffer).strip()
        if text:
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{2,}", "", text)
            text = re.sub(r"\s*\n\s*", " ", text).strip()
            head = current_heading or ""
            block = f"## {head}\n\n{text}".strip() if head else text
            blocks.append(block)
        buffer = []

    for ln in lines:
        stripped = ln.strip()
        if _looks_like_heading(stripped):
            is_methods = bool(METHODS_RE.match(stripped))
            is_study = bool(STUDY_RE.match(stripped))
            is_exclude = bool(EXCLUDE_RE.match(stripped)) and not is_methods

            if is_methods or is_study:
                flush()
                current_heading = stripped
                keep_active = True
                continue
            if is_exclude:
                flush()
                keep_active = False
                current_heading = None
                continue
            if keep_active:  # other heading while inside a methods region
                flush()
                current_heading = stripped
                continue
            continue  # other heading while inactive

        if keep_active:
            buffer.append(ln)

    flush()
    return "\n\n".join(b for b in blocks if b.strip()).strip()


def extract_with_pdfplumber(pdf_path: Path) -> Dict[str, object]:
    """Best-effort extraction from a PDF using pdfplumber + heuristic regex parsing.

    Returns a partial record dict ({doi, title, venue, year, abstract, methods});
    empty strings / 0 where a field could not be recovered. Intended only as a
    fallback for the debug CLI when GROBID is unavailable.
    """
    import pdfplumber  # imported lazily so GROBID-only runs don't need it

    log("[fallback] WARNING: using pdfplumber heuristic parser (GROBID unavailable).")

    pages_text: List[str] = []
    meta: Dict[str, str] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        meta = {k: str(v) for k, v in (pdf.metadata or {}).items()}
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
    full_text = "\n".join(pages_text)
    lines = [ln.rstrip() for ln in full_text.splitlines()]

    # --- DOI ---
    doi = ""
    for source in (meta.get("doi", ""), meta.get("Subject", ""), full_text):
        doi = normalize_doi(source)
        if doi:
            break

    # --- Title: prefer metadata, else first substantial non-numeric line. ---
    title = (meta.get("Title") or meta.get("title") or "").strip()
    if not title or len(title) < 4:
        for ln in lines:
            stripped = ln.strip()
            if len(stripped) >= 8 and not stripped.isupper() and not re.match(r"^\d", stripped):
                title = stripped
                break

    # --- Year ---
    year = 0
    ym = re.search(r"(?:19|20)\d{2}", meta.get("CreationDate", "") or "")
    if ym:
        year = int(ym.group(0))
    if not year:
        ym = re.search(r"\b(19|20)\d{2}\b", full_text[:4000])
        if ym:
            year = int(ym.group(0))

    # --- Venue (best effort) ---
    venue = ""
    vm = re.search(r"\b(CHI|UIST|CSCW|DIS|TEI|MobileHCI|UbiComp|IUI|GROUP)\b[^\n]{0,40}?['’]?\s*(\d{2,4})",
                   full_text[:6000])
    if vm:
        yy = vm.group(2)
        venue = f"{vm.group(1)} '{yy[-2:]}" if len(yy) >= 2 else vm.group(1)

    return {
        "doi": doi,
        "title": title.strip(),
        "venue": venue,
        "year": year,
        "abstract": _regex_abstract(full_text),
        "methods": _regex_methods(lines),
    }
