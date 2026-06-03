#!/usr/bin/env python3
"""Extract structured text (DOI, title, venue, year, abstract, methods) from a single ACM SIGCHI paper PDF.

Stage 2 of the "Who's Answering CHI" pipeline. Uses GROBID as the primary
extractor (TEI XML parsed with lxml) and falls back to pdfplumber + regex
heuristics if GROBID is unreachable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from lxml import etree

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEI_NS: Dict[str, str] = {"tei": "http://www.tei-c.org/ns/1.0"}

# Headings whose sections we KEEP (methods family). Matched case-insensitively
# against the start of the heading text (after stripping leading numbering).
METHODS_PATTERNS: List[str] = [
    r"methods?",
    r"methodolog(?:y|ies)",
    r"materials?\s+and\s+methods?",
    r"study\s+design",
    r"experimental\s+design",
    r"research\s+design",
    r"procedures?",
    r"participants?",
    r"subjects?",
    r"materials?",
    r"apparatus",
    r"measures?",
    r"stimuli",
    r"data\s+collection",
    r"recruit(?:ment|ing)?",
    r"survey\s+design",
    r"questionnaire",
    r"protocol",
    r"setup",
    r"tasks?\s+and\s+procedures?",
]

# Headings that mark the END of the methods family / sections we EXCLUDE.
EXCLUDE_PATTERNS: List[str] = [
    r"results?",
    r"findings?",
    r"discussions?",
    r"limitations?",
    r"conclusions?",
    r"future\s+work",
    r"acknowledge?ments?",
    r"references?",
    r"bibliography",
    r"appendix",
    r"related\s+work",
    r"background",
    r"introduction",
]

METHODS_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:" + "|".join(METHODS_PATTERNS) + r")\b",
                        re.IGNORECASE)
EXCLUDE_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:" + "|".join(EXCLUDE_PATTERNS) + r")\b",
                        re.IGNORECASE)

# Study/experiment subsection markers, used to keep document-order grouping.
STUDY_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:study|experiment|phase)\s+\d+",
                      re.IGNORECASE)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# DOI helpers
# ---------------------------------------------------------------------------

def doi_from_filename(pdf_path: Path) -> str:
    """Infer a DOI from a filename of the form '10_1145_NNNNNNN_NNNNNNN.pdf'."""
    stem = pdf_path.stem
    m = re.match(r"^(10)[_.](\d{3,})[_.](\d+)[_.](\d+)$", stem)
    if m:
        return f"{m.group(1)}.{m.group(2)}/{m.group(3)}.{m.group(4)}"
    # Generic fallback: 10_<registrant>_<rest...> -> 10.<registrant>/<rest joined by '.'>
    parts = stem.split("_")
    if len(parts) >= 3 and parts[0] == "10":
        return f"10.{parts[1]}/{'.'.join(parts[2:])}"
    return ""


def normalize_doi(raw: str) -> str:
    """Strip URL/prefix noise from a DOI string and return the bare DOI."""
    if not raw:
        return ""
    raw = raw.strip()
    raw = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^doi:\s*", "", raw, flags=re.IGNORECASE)
    m = re.search(r"10\.\d{3,}/\S+", raw)
    return m.group(0).rstrip(".,;)") if m else ""


# ---------------------------------------------------------------------------
# GROBID extraction
# ---------------------------------------------------------------------------

def call_grobid(pdf_path: Path, grobid_url: str) -> Optional[str]:
    """POST the PDF to GROBID's processFulltextDocument endpoint; return TEI XML or None."""
    endpoint = grobid_url.rstrip("/") + "/api/processFulltextDocument"
    try:
        with pdf_path.open("rb") as fh:
            log(f"[grobid] sending {pdf_path.name} to {endpoint}")
            resp = requests.post(
                endpoint,
                files={"input": (pdf_path.name, fh, "application/pdf")},
                data={"consolidateHeader": "1", "consolidateCitations": "0"},
                timeout=300,
            )
    except requests.exceptions.RequestException as exc:
        log(f"[grobid] WARNING: GROBID unreachable at {grobid_url}: {exc}")
        return None
    if resp.status_code != 200:
        log(f"[grobid] WARNING: GROBID returned HTTP {resp.status_code}; falling back.")
        return None
    return resp.text


def _tei_text(node: Optional[etree._Element]) -> str:
    """Return concatenated, whitespace-normalized text content of a TEI node."""
    if node is None:
        return ""
    text = "".join(node.itertext())
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _div_heading(div: etree._Element) -> str:
    """Return the heading text of a TEI <div>, or '' if it has no <head>."""
    head = div.find("tei:head", TEI_NS)
    return _tei_text(head)


def _div_body_text(div: etree._Element) -> str:
    """Return the verbatim paragraph text of a TEI <div>, excluding its heading, paragraphs joined by blank lines."""
    paras: List[str] = []
    for child in div:
        tag = etree.QName(child).localname
        if tag == "head":
            continue
        if tag in ("p", "quote", "list", "formula"):
            txt = _tei_text(child)
            if txt:
                paras.append(txt)
    return "\n\n".join(paras)


def parse_tei(tei_xml: str, pdf_path: Path) -> Dict[str, object]:
    """Parse GROBID TEI XML into the output schema dict."""
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(tei_xml.encode("utf-8"), parser=parser)

    # --- Title ---
    title_node = root.find(".//tei:teiHeader//tei:titleStmt/tei:title", TEI_NS)
    if title_node is None:
        title_node = root.find(".//tei:sourceDesc//tei:analytic/tei:title", TEI_NS)
    title = _tei_text(title_node)

    # --- DOI ---
    doi_node = root.find(".//tei:idno[@type='DOI']", TEI_NS)
    doi = normalize_doi(_tei_text(doi_node))

    # --- Year ---
    year = 0
    for date_node in root.findall(".//tei:sourceDesc//tei:date", TEI_NS):
        when = date_node.get("when", "")
        m = re.search(r"(\d{4})", when or _tei_text(date_node))
        if m:
            year = int(m.group(1))
            break

    # --- Venue ---
    venue = ""
    meeting = root.find(".//tei:sourceDesc//tei:meeting", TEI_NS)
    if meeting is not None:
        venue = _tei_text(meeting)
    if not venue:
        mono = root.find(".//tei:sourceDesc//tei:monogr/tei:title", TEI_NS)
        venue = _tei_text(mono)

    # --- Abstract ---
    abstract_node = root.find(".//tei:profileDesc/tei:abstract", TEI_NS)
    if abstract_node is not None:
        abs_paras = [_tei_text(p) for p in abstract_node.findall(".//tei:p", TEI_NS)]
        abs_paras = [p for p in abs_paras if p]
        abstract = "\n\n".join(abs_paras) if abs_paras else _tei_text(abstract_node)
    else:
        abstract = ""

    # --- Methods (body divs in document order) ---
    methods = _collect_methods_from_divs(root)

    return {
        "doi": doi,
        "title": title,
        "venue": venue,
        "year": year,
        "abstract": abstract,
        "methods": methods,
    }


def _collect_methods_from_divs(root: etree._Element) -> str:
    """Walk TEI <body> divs in document order and concatenate every methods-family section verbatim."""
    body = root.find(".//tei:text/tei:body", TEI_NS)
    if body is None:
        return ""
    divs = body.findall("tei:div", TEI_NS)
    blocks: List[str] = []
    keep_active = False  # True while inside a methods region (captures unlabeled sub-divs)

    for div in divs:
        heading = _div_heading(div)
        is_methods = bool(METHODS_RE.match(heading)) if heading else False
        is_exclude = bool(EXCLUDE_RE.match(heading)) if heading else False
        is_study = bool(STUDY_RE.match(heading)) if heading else False

        if is_exclude and not is_methods:
            keep_active = False
            continue

        if is_methods or is_study:
            keep_active = True
            body_text = _div_body_text(div)
            block = f"## {heading}\n\n{body_text}".rstrip() if heading else body_text
            if block.strip():
                blocks.append(block.strip())
            continue

        # Unlabeled or other heading: keep only if we are currently inside a methods region.
        if keep_active:
            body_text = _div_body_text(div)
            block = f"## {heading}\n\n{body_text}".rstrip() if heading else body_text
            if block.strip():
                blocks.append(block.strip())

    return "\n\n".join(blocks).strip()


# ---------------------------------------------------------------------------
# pdfplumber fallback
# ---------------------------------------------------------------------------

def extract_with_pdfplumber(pdf_path: Path) -> Dict[str, object]:
    """Fallback extractor using pdfplumber + heuristic regex parsing."""
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

    # --- Abstract ---
    abstract = _regex_abstract(full_text)

    # --- Methods ---
    methods = _regex_methods(lines)

    return {
        "doi": doi,
        "title": title.strip(),
        "venue": venue,
        "year": year,
        "abstract": abstract,
        "methods": methods,
    }


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
    # Re-join hard-wrapped lines into paragraphs.
    text = re.sub(r"\n{2,}", "", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return text.replace("", "\n\n").strip()


def _regex_methods(lines: List[str]) -> str:
    """Heuristically extract methods-family sections from line-split PDF text."""
    blocks: List[str] = []
    current_heading: Optional[str] = None
    buffer: List[str] = []
    keep_active = False

    def flush() -> None:
        nonlocal buffer, current_heading
        text = "\n".join(buffer).strip()
        if text:
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{2,}", "", text)
            text = re.sub(r"\s*\n\s*", " ", text)
            text = text.replace("", "\n\n").strip()
            head = current_heading or ""
            block = f"## {head}\n\n{text}".strip() if head else text
            blocks.append(block)
        buffer = []

    for ln in lines:
        stripped = ln.strip()
        is_heading = _looks_like_heading(stripped)
        if is_heading:
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
            # Other heading while active: keep as sub-block.
            if keep_active:
                flush()
                current_heading = stripped
                continue
            # Other heading while inactive: ignore.
            continue

        if keep_active:
            buffer.append(ln)

    flush()
    return "\n\n".join(b for b in blocks if b.strip()).strip()


def _looks_like_heading(line: str) -> bool:
    """Heuristic: does this line look like a section heading?"""
    if not line or len(line) > 80:
        return False
    if re.match(r"^\d+(?:\.\d+)*\.?\s+\S", line):  # numbered heading
        return True
    words = line.split()
    if 1 <= len(words) <= 8 and line[0].isupper() and not line.endswith("."):
        # Title-cased-ish short line.
        return True
    return False


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def extract_paper(pdf_path: Path, grobid_url: str) -> Dict[str, object]:
    """Extract the paper record via GROBID, falling back to pdfplumber on failure."""
    record: Optional[Dict[str, object]] = None
    tei_xml = call_grobid(pdf_path, grobid_url)
    if tei_xml:
        try:
            record = parse_tei(tei_xml, pdf_path)
            log("[grobid] parsed TEI successfully.")
        except Exception as exc:  # noqa: BLE001 - want to fall back on any parse error
            log(f"[grobid] WARNING: failed to parse TEI ({exc}); falling back.")
            record = None

    if record is None:
        try:
            record = extract_with_pdfplumber(pdf_path)
        except Exception as exc:  # noqa: BLE001
            log(f"[fallback] ERROR: pdfplumber extraction failed: {exc}")
            record = {"doi": "", "title": "", "venue": "", "year": 0,
                      "abstract": "", "methods": ""}

    return finalize_record(record, pdf_path)


def finalize_record(record: Dict[str, object], pdf_path: Path) -> Dict[str, object]:
    """Apply DOI-from-filename fallback and enforce the exact output schema."""
    if not record.get("doi"):
        inferred = doi_from_filename(pdf_path)
        if inferred:
            log(f"[doi] inferred from filename: {inferred}")
        record["doi"] = inferred

    year_val = record.get("year") or 0
    try:
        year_int = int(year_val)
    except (TypeError, ValueError):
        year_int = 0

    return {
        "doi": str(record.get("doi") or ""),
        "title": str(record.get("title") or ""),
        "venue": str(record.get("venue") or ""),
        "year": year_int,
        "abstract": str(record.get("abstract") or ""),
        "methods": str(record.get("methods") or ""),
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract structured text from a single ACM SIGCHI paper PDF.")
    parser.add_argument("pdf_path", type=str, help="Path to one PDF file.")
    parser.add_argument("--output", type=str, default=None,
                        help="Write JSON to this file (default: stdout).")
    parser.add_argument("--grobid-url", type=str, default="http://localhost:8070",
                        help="GROBID endpoint (default: http://localhost:8070).")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Program entry point; returns a process exit code."""
    args = parse_args(argv)
    pdf_path = Path(args.pdf_path)
    if not pdf_path.is_file():
        log(f"ERROR: PDF not found: {pdf_path}")
        return 1

    record = extract_paper(pdf_path, args.grobid_url)
    payload = json.dumps(record, ensure_ascii=False, indent=2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        log(f"[done] wrote JSON to {out_path}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
