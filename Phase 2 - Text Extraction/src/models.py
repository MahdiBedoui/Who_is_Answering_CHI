"""SQLAlchemy ORM models for the Who's Answering CHI corpus database.

The `papers` table is the single, objective-agnostic home for extracted text
(shared by all three classification objectives). Classifier outputs, evidence
spans, and gold labels get their own tables in later stages.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

from sqlalchemy import Boolean, Computed, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Paper(Base):
    """One row per SIGCHI paper: extracted text + provenance, shared across objectives."""

    __tablename__ = "papers"

    # --- Identity ---
    doi: Mapped[str] = mapped_column(String(128), primary_key=True)

    # --- Bibliographic metadata ---
    title: Mapped[Optional[str]] = mapped_column(Text)
    venue: Mapped[Optional[str]] = mapped_column(String(64))
    year: Mapped[Optional[int]] = mapped_column(Integer)
    ptype: Mapped[Optional[str]] = mapped_column(String(32))  # Research Article / Short Paper / _excluded

    # --- Abstract (Stage 2a) ---
    abstract: Mapped[Optional[str]] = mapped_column(Text)
    abstract_source: Mapped[Optional[str]] = mapped_column(String(16))  # grobid | openalex | regex
    abstract_mismatch: Mapped[bool] = mapped_column(Boolean, default=False)  # PDF vs OpenAlex divergence flag

    # --- Methods (Stage 2b — populated later) ---
    methods: Mapped[Optional[str]] = mapped_column(Text)              # tight, classified section(s)
    methods_context: Mapped[Optional[str]] = mapped_column(Text)      # recall-safe wider region
    methods_heading_found: Mapped[Optional[bool]] = mapped_column(Boolean)

    # --- Provenance / QA ---
    source_pdf_path: Mapped[Optional[str]] = mapped_column(Text)
    grobid_ok: Mapped[Optional[bool]] = mapped_column(Boolean)
    extra: Mapped[Optional[dict]] = mapped_column(JSONB)  # free-form QA flags, raw scores, etc.
    extracted_at: Mapped[Optional[_dt.datetime]] = mapped_column(
        server_default=text("now()")
    )

    # --- Full-text search (Postgres generated column + GIN index) ---
    search_tsv: Mapped[Optional[str]] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(abstract,'') || ' ' || coalesce(methods,''))",
            persisted=True,
        ),
    )

    __table_args__ = (
        Index("ix_papers_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_papers_venue_year", "venue", "year"),
    )

    def __repr__(self) -> str:
        """Concise debug representation."""
        return f"<Paper {self.doi} {self.venue} {self.year}>"
