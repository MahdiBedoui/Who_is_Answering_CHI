"""Per-paper extraction: PDF path -> validated record dict matching the `papers` table.

Metadata authority:
  * doi / venue / year / ptype come from the corpus FOLDER PATH (Stage-1 validated,
    more reliable than anything parsed from the PDF).
  * title / abstract / methods come from GROBID TEI (with OpenAlex + regex fallbacks).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

from lxml import etree

from . import abstract as abs_mod
from . import methods as methods_mod
from .grobid import process_fulltext

TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}

# Folder names (Research Article / Short Paper / _excluded) -> normalized type.
_PTYPE_MAP = {
    "research article": "Research Article",
    "short paper": "Short Paper",
    "_excluded": "_excluded",
}


def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)


def doi_from_filename(pdf_path: Path) -> str:
    """Infer DOI from '10_1145_NNNNNNN_NNNNNNN.pdf' -> '10.1145/NNNNNNN.NNNNNNN'."""
    parts = pdf_path.stem.split("_")
    if len(parts) >= 3 and parts[0] == "10":
        return f"10.{parts[1]}/{'.'.join(parts[2:])}"
    return ""


def parse_path_metadata(pdf_path) -> Dict[str, object]:
    """Derive venue/year/ptype from a '.../<venue>/<year>/<type>/file.pdf' corpus path.

    Accepts a Path or a str and splits on both separators, so it also works on a
    stored Windows-style `source_pdf_path` when run on a POSIX host.
    """
    venue, year, ptype = "", None, ""
    parts = re.split(r"[\\/]+", str(pdf_path))
    # Find a 4-digit year component; venue is the part before it, type the part after.
    for i, p in enumerate(parts):
        if re.fullmatch(r"(?:19|20)\d{2}", p):
            year = int(p)
            if i - 1 >= 0:
                venue = parts[i - 1]
            if i + 1 < len(parts):
                ptype = _PTYPE_MAP.get(parts[i + 1].lower(), parts[i + 1])
            break
    return {"venue": venue, "year": year, "ptype": ptype}


def _title_from_tei(root: etree._Element) -> str:
    """Extract the paper title from TEI."""
    node = root.find(".//tei:teiHeader//tei:titleStmt/tei:title", TEI_NS)
    if node is None:
        node = root.find(".//tei:sourceDesc//tei:analytic/tei:title", TEI_NS)
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip() if node is not None else ""


def _doi_from_tei(root: etree._Element) -> str:
    """Extract a DOI from TEI metadata, normalized."""
    node = root.find(".//tei:idno[@type='DOI']", TEI_NS)
    raw = "".join(node.itertext()).strip() if node is not None else ""
    m = re.search(r"10\.\d{3,}/\S+", raw)
    return m.group(0).rstrip(".,;)") if m else ""


def extract_record(
    pdf_path: Path,
    grobid_url: str = "http://localhost:8070",
    openalex_mailto: str = "",
    openalex_fallback: bool = True,
    openalex_crosscheck: bool = False,
    openalex_cache_dir: Optional[str] = None,
    heading_classifier: Optional[Callable[[List[str]], List[str]]] = None,
) -> Dict[str, object]:
    """Extract one paper into a dict matching the PaperRecord/`papers` schema.

    OpenAlex usage is split: `openalex_fallback` (default on) fills an empty
    abstract only when the PDF yields none; `openalex_crosscheck` (opt-in)
    fetches per paper to flag PDF/OpenAlex divergence. `heading_classifier` is
    passed to methods.extract_methods (default regex; LLM/hybrid are drop-ins),
    and the path it took is recorded in extra['heading_classifier'].
    """
    meta = parse_path_metadata(pdf_path)
    doi = doi_from_filename(pdf_path)

    tei_xml = process_fulltext(pdf_path, grobid_url=grobid_url)
    record: Dict[str, object] = {
        "doi": doi,
        "title": "",
        "venue": meta["venue"],
        "year": meta["year"],
        "ptype": meta["ptype"],
        "abstract": "",
        "abstract_source": "",
        "abstract_mismatch": False,
        "methods": "",
        "methods_context": "",
        "methods_heading_found": None,
        "source_pdf_path": str(pdf_path),
        "grobid_ok": bool(tei_xml),
        "extra": {},
    }

    if tei_xml:
        try:
            root = etree.fromstring(
                tei_xml.encode("utf-8"), parser=etree.XMLParser(recover=True, huge_tree=True)
            )
            record["title"] = _title_from_tei(root)
            if not doi:
                record["doi"] = _doi_from_tei(root)
            tight, context, found, _headings, _tags = methods_mod.extract_methods_detailed(
                root, classifier=heading_classifier
            )
            record["methods"] = tight
            record["methods_context"] = context
            record["methods_heading_found"] = found
            record["extra"]["heading_classifier"] = (
                getattr(heading_classifier, "source", None)
                or ("regex" if heading_classifier is None else "llm")
            )
            # Deterministic low-confidence flags -> route these to LLM re-extraction.
            qflags = methods_mod.methods_quality_flags(
                tight, context, found, grobid_ok=True,
                headings=_headings, tags=_tags,
            )
            record["extra"]["methods_quality_flags"] = qflags
            record["extra"]["needs_llm_methods"] = bool(qflags)
            abs_info = abs_mod.select_abstract(
                tei_xml=tei_xml, doi=record["doi"], openalex_mailto=openalex_mailto,
                openalex_fallback=openalex_fallback, openalex_crosscheck=openalex_crosscheck,
                cache_dir=openalex_cache_dir,
            )
            record.update(abs_info)
        except Exception as exc:  # noqa: BLE001 -- keep going, flag for reprocess
            log(f"[extract] WARNING: TEI parse failed for {pdf_path.name}: {exc}")
            record["grobid_ok"] = False
            record["extra"] = {"error": str(exc)}
    else:
        # GROBID failed for this PDF -- flag for reprocessing, but still try
        # OpenAlex for at least the abstract so the row is not empty.
        record["extra"] = {"needs_reprocess": True}
        abs_info = abs_mod.select_abstract(
            doi=record["doi"], openalex_mailto=openalex_mailto,
            openalex_fallback=openalex_fallback, openalex_crosscheck=False,
            cache_dir=openalex_cache_dir,
        )
        record.update(abs_info)

    return record
