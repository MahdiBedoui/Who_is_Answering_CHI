"""Corpus walker: enumerate PDFs and map filenames <-> DOIs.

Corpus layout (in the data store):
    sigchi/VERIFIED COUNT/<venue>/<year>/<ptype>/10_1145_XXXX_YYYY.pdf

Filename stem is the DOI with '/' and '.' replaced by '_':
    10_1145_3613905_3636282  ->  10.1145/3613905.3636282
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence


@dataclass(frozen=True)
class CorpusPaper:
    doi: str
    key: str          # filesystem-safe DOI (the pdf stem)
    venue: str
    year: int
    ptype: str        # normalized: "EA" | "Research Article" | raw folder name
    pdf_path: Path


def doi_from_stem(stem: str) -> str:
    parts = stem.split("_")
    if len(parts) < 3 or parts[0] != "10":
        raise ValueError(f"unrecognized DOI filename stem: {stem!r}")
    return f"{parts[0]}.{parts[1]}/" + ".".join(parts[2:])


def key_from_doi(doi: str) -> str:
    return doi.replace("/", "_").replace(".", "_")


def _norm_ptype(folder: str) -> str:
    f = folder.strip()
    if f.lower().startswith("research article"):  # "Research Article" / "Research Articles"
        return "Research Article"
    return f  # "EA" and anything else kept as-is


def iter_corpus(corpus_root: Path, venue: str, years: Sequence[int]) -> Iterator[CorpusPaper]:
    venue_dir = corpus_root / venue
    if not venue_dir.is_dir():
        raise SystemExit(f"ERROR: venue folder not found: {venue_dir}")
    for year in sorted(years):
        ydir = venue_dir / str(year)
        if not ydir.is_dir():
            continue
        for tdir in sorted(p for p in ydir.iterdir() if p.is_dir()):
            ptype = _norm_ptype(tdir.name)
            for pdf in sorted(tdir.glob("*.pdf")):
                try:
                    doi = doi_from_stem(pdf.stem)
                except ValueError:
                    continue  # skip non-DOI-named files
                yield CorpusPaper(doi=doi, key=pdf.stem, venue=venue,
                                  year=year, ptype=ptype, pdf_path=pdf)
