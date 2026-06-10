"""Abstract isolation: OpenAlex-primary, with GROBID/regex fallback + cross-check.

Priority for the STORED abstract:
  1. OpenAlex abstract       (PRIMARY -- publisher's canonical text, no PDF artifacts)
  2. GROBID TEI <abstract>   (fallback when OpenAlex has no abstract for the DOI)
  3. Regex from raw PDF text (last resort when GROBID TEI also failed)

OpenAlex controls:
  * openalex_fallback (default ON)  -- master switch for consulting OpenAlex. When
    ON, OpenAlex is the primary source; when OFF, the PDF (GROBID -> regex) is
    primary and OpenAlex is not used at all.
  * openalex_crosscheck (opt-in)    -- additionally compares the OpenAlex abstract
    against the GROBID TEI abstract and sets abstract_mismatch on sharp divergence.
    This is now a GROBID-EXTRACTION QA signal (publisher abstract is trusted),
    surfacing papers where GROBID mis-segmented the front matter.

OpenAlex responses are cached on disk by DOI (when cache_dir is given) so
re-runs never re-fetch and the dataset stays reproducible.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from lxml import etree

TEI_NS: Dict[str, str] = {"tei": "http://www.tei-c.org/ns/1.0"}

MIN_LEN = 50      # shorter than this is almost never a real abstract
MAX_LEN = 6000    # longer than this means sections got merged
JACCARD_MISMATCH = 0.30  # below this overlap, flag PDF vs OpenAlex divergence

# A "Figure 1: ..." / "Table 2 ..." candidate is a caption, not an abstract.
_CAPTION_RE = re.compile(r"^\s*(?:figure|fig\.?|table)\s*\d", re.IGNORECASE)


def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Tier 1: GROBID TEI
# ---------------------------------------------------------------------------

def abstract_from_tei(tei_xml: str) -> str:
    """Extract the abstract text from a GROBID TEI document, paragraphs joined by blank lines."""
    if not tei_xml:
        return ""
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(tei_xml.encode("utf-8"), parser=parser)
    node = root.find(".//tei:profileDesc/tei:abstract", TEI_NS)
    if node is None:
        return ""
    paras = ["".join(p.itertext()) for p in node.findall(".//tei:p", TEI_NS)]
    paras = [re.sub(r"\s+", " ", p).strip() for p in paras]
    paras = [p for p in paras if p]
    text = "\n\n".join(paras) if paras else re.sub(r"\s+", " ", "".join(node.itertext())).strip()
    return text


# ---------------------------------------------------------------------------
# Tier 2: regex over raw PDF text
# ---------------------------------------------------------------------------

def abstract_from_text(pdf_text: str) -> str:
    """Heuristically extract the abstract from raw PDF text by header boundaries."""
    if not pdf_text:
        return ""
    m = re.search(
        r"(?is)\bAbstract\b[\s:]*\n?(.*?)(?:\n\s*(?:CCS\s+Concepts|Keywords|KEYWORDS|"
        r"ACM\s+Reference\s+Format|1\s+Introduction|1\.\s+Introduction|\bIntroduction\b))",
        pdf_text,
    )
    if not m:
        return ""
    text = m.group(1)
    text = re.sub(r"-\n", "", text)            # de-hyphenate line breaks
    text = re.sub(r"\s*\n\s*", " ", text)      # unwrap soft line breaks
    return re.sub(r"[ \t]+", " ", text).strip()


# ---------------------------------------------------------------------------
# Tier 3 + cross-check: OpenAlex (with on-disk cache)
# ---------------------------------------------------------------------------

def reconstruct_inverted_index(inv: Optional[Dict[str, List[int]]]) -> str:
    """Rebuild a plain abstract string from an OpenAlex abstract_inverted_index."""
    if not inv:
        return ""
    positions: List[Tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda t: t[0])
    return " ".join(word for _, word in positions).strip()


def _cache_path(cache_dir: Optional[str], doi: str) -> Optional[Path]:
    """Return the on-disk cache file path for a DOI, or None if caching is disabled."""
    if not cache_dir:
        return None
    return Path(cache_dir) / (doi.replace("/", "_") + ".json")


def fetch_openalex_abstract(
    doi: str, mailto: str = "", timeout: int = 20, cache_dir: Optional[str] = None
) -> str:
    """Fetch and reconstruct a paper's abstract from OpenAlex by DOI (cached; '' on failure)."""
    if not doi:
        return ""

    cache_file = _cache_path(cache_dir, doi)
    if cache_file is not None and cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return reconstruct_inverted_index(data.get("abstract_inverted_index"))
        except Exception:  # noqa: BLE001 -- treat a bad cache file as a miss
            pass

    url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    params = {"mailto": mailto} if mailto else {}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        log(f"[openalex] WARNING: request failed for {doi}: {exc}")
        return ""
    if resp.status_code != 200:
        log(f"[openalex] WARNING: HTTP {resp.status_code} for {doi}")
        return ""
    data = resp.json()
    inv = data.get("abstract_inverted_index")

    if cache_file is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"abstract_inverted_index": inv}), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 -- caching is best-effort
            log(f"[openalex] WARNING: could not cache {doi}: {exc}")

    return reconstruct_inverted_index(inv)


# ---------------------------------------------------------------------------
# Selection + cross-check
# ---------------------------------------------------------------------------

def _tokens(text: str) -> set:
    """Lowercase alphanumeric token set for overlap comparison."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def jaccard(a: str, b: str) -> float:
    """Token-level Jaccard similarity between two strings (0.0 if either is empty)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _valid(text: str) -> bool:
    """Is this a plausible abstract: right length AND not a figure/table caption?"""
    t = text.strip()
    if not (MIN_LEN <= len(t) <= MAX_LEN):
        return False
    if _CAPTION_RE.match(t):
        return False
    return True


def select_abstract(
    tei_xml: Optional[str] = None,
    pdf_text: Optional[str] = None,
    doi: str = "",
    openalex_mailto: str = "",
    openalex_fallback: bool = True,
    openalex_crosscheck: bool = False,
    cache_dir: Optional[str] = None,
) -> Dict[str, object]:
    """Choose the best abstract across tiers; optionally fall back to / cross-check OpenAlex.

    Returns a dict: {abstract, abstract_source, abstract_mismatch}.
    """
    # OpenAlex is the PRIMARY source: the publisher's canonical abstract, free of
    # PDF-extraction artifacts (no figure captions, hyphenation, or column merges).
    # `openalex_fallback` is the master switch for consulting OpenAlex at all; when
    # it is off, the PDF (GROBID -> regex) becomes primary instead.
    oa_abs = ""
    if doi and openalex_fallback:
        oa_abs = fetch_openalex_abstract(doi, openalex_mailto, cache_dir=cache_dir)

    tei_abs = abstract_from_tei(tei_xml or "")
    regex_abs = abstract_from_text(pdf_text or "")

    # Priority order: OpenAlex -> GROBID TEI -> regex.
    chosen, source = "", ""
    if _valid(oa_abs):
        chosen, source = oa_abs, "openalex"
    elif _valid(tei_abs):
        chosen, source = tei_abs, "grobid"
    elif _valid(regex_abs):
        chosen, source = regex_abs, "regex"

    # Cross-check (opt-in): when we have BOTH an OpenAlex abstract and a GROBID TEI
    # abstract, flag sharp divergence. This is now a GROBID-extraction QA signal
    # (the publisher abstract is trusted), surfacing papers where GROBID
    # mis-segmented the front matter -- regardless of which source we stored.
    mismatch = False
    if openalex_crosscheck and _valid(oa_abs) and _valid(tei_abs):
        if jaccard(oa_abs, tei_abs) < JACCARD_MISMATCH:
            mismatch = True
            log(f"[abstract] WARNING: GROBID/OpenAlex abstract divergence for {doi} "
                f"(GROBID extraction flagged for review)")

    return {
        "abstract": chosen,
        "abstract_source": source,
        "abstract_mismatch": mismatch,
    }
