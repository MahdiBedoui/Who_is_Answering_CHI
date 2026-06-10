"""Pydantic schema validating an extracted paper record before it reaches the DB.

This is the contract between extraction (which emits JSON) and storage. It
normalizes types, enforces the DOI shape, and guards against junk (e.g. an
"abstract" that is really the whole paper).
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

DOI_RE = re.compile(r"^10\.\d{3,}/\S+$")


class PaperRecord(BaseModel):
    """Validated extraction record; field names mirror the `papers` table."""

    doi: str
    title: str = ""
    venue: str = ""
    year: Optional[int] = None
    ptype: str = ""

    abstract: str = ""
    abstract_source: str = ""          # grobid | openalex | regex | ""
    abstract_mismatch: bool = False

    methods: str = ""
    methods_context: str = ""
    methods_heading_found: Optional[bool] = None

    source_pdf_path: str = ""
    grobid_ok: Optional[bool] = None
    extra: dict = Field(default_factory=dict)

    @field_validator("doi")
    @classmethod
    def _check_doi(cls, v: str) -> str:
        """Require a syntactically valid DOI (empty is rejected — every paper has one)."""
        v = (v or "").strip()
        if not DOI_RE.match(v):
            raise ValueError(f"invalid DOI: {v!r}")
        return v

    @field_validator("year")
    @classmethod
    def _check_year(cls, v: Optional[int]) -> Optional[int]:
        """Coerce/sanity-check publication year to a plausible range, else None."""
        if v in (None, 0):
            return None
        try:
            year = int(v)
        except (TypeError, ValueError):
            return None
        return year if 1990 <= year <= 2100 else None

    @field_validator("abstract")
    @classmethod
    def _check_abstract(cls, v: str) -> str:
        """Drop implausibly long 'abstracts' (likely mis-segmented full text)."""
        v = (v or "").strip()
        # Abstracts over ~6000 chars almost always mean GROBID merged sections.
        return v if len(v) <= 6000 else ""
