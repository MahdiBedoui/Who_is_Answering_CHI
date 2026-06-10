"""Methods-section isolation from GROBID TEI.

Produces three things per paper:
  * methods         -- tight: every section inside the methods REGION, including
                      unlabeled/ambiguous subsections (e.g. "Audio Stimuli",
                      "Hardware and Software") that sit between the first methods
                      heading and the first results/discussion heading. Only
                      front-matter and excluded sections are dropped.
  * methods_context -- recall-safe: the same region, verbatim. (methods and
                      methods_context now differ only when a front-matter section
                      is interleaved inside the region.)
  * methods_heading_found -- whether any methods-family heading existed at all
                      (False => flag for review; common in HCI design papers).

Heading classification is pluggable: pass any classifier callable
`(headings: list[str]) -> list[str]` returning one tag per heading from
{"methods", "exclude", "front", "other"}. The default is regex-based; an LLM
classifier in heading_classifier.py is a drop-in alternative for A/B testing.
"""

from __future__ import annotations

import re
import sys
from typing import Callable, Dict, List, Optional, Tuple

from lxml import etree

TEI_NS: Dict[str, str] = {"tei": "http://www.tei-c.org/ns/1.0"}


def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)

# Tag vocabulary shared by every classifier.
TAG_METHODS = "methods"
TAG_EXCLUDE = "exclude"   # results/discussion/back-matter -- ends the methods region
TAG_FRONT = "front"       # introduction/related work/background -- leading filler
TAG_OTHER = "other"       # unclassified (kept if inside the methods region)

# Headings that ARE methods (HCI-aware lexicon).
METHODS_PATTERNS: List[str] = [
    r"methods?", r"methodolog(?:y|ies)", r"materials?\s+and\s+methods?",
    r"study\s+design", r"experimental\s+design", r"research\s+design",
    r"procedures?", r"participants?", r"subjects?", r"materials?", r"apparatus",
    r"measures?", r"stimuli", r"data\s+collection", r"data\s+analysis",
    r"recruit(?:ment|ing)?", r"survey\s+design", r"questionnaire", r"protocol",
    r"setup", r"conditions?", r"user\s+study", r"field\s+(?:study|deployment)",
    # Loosened: bare "Evaluation"/"Evaluations" and bare "Task"/"Tasks" are
    # common HCI methods headings, not only "Evaluation Method" etc.
    r"evaluations?", r"tasks?",
]

# Headings that END the methods region (sections we EXCLUDE).
EXCLUDE_PATTERNS: List[str] = [
    r"results?", r"findings?", r"discussions?", r"limitations?", r"conclusions?",
    r"future\s+work", r"acknowledge?ments?", r"references?", r"bibliography",
    r"appendix",
]

# Leading front-matter / related-work headings (trimmed in the no-methods fallback).
FRONT_PATTERNS: List[str] = [
    r"introduction", r"related\s+work", r"background", r"motivation",
    r"prior\s+work", r"literature\s+review", r"abstract",
]

STUDY_PATTERNS: List[str] = [r"(?:study|experiment|phase)\s+\d+"]

_NUM = r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?"
METHODS_RE = re.compile(_NUM + r"(?:" + "|".join(METHODS_PATTERNS) + r")\b", re.IGNORECASE)
EXCLUDE_RE = re.compile(_NUM + r"(?:" + "|".join(EXCLUDE_PATTERNS) + r")\b", re.IGNORECASE)
FRONT_RE = re.compile(_NUM + r"(?:" + "|".join(FRONT_PATTERNS) + r")\b", re.IGNORECASE)
STUDY_RE = re.compile(_NUM + r"(?:" + "|".join(STUDY_PATTERNS) + r")\b", re.IGNORECASE)


def classify_heading_regex(heading: str) -> str:
    """Classify a single heading into one of the shared tags using regex/lexicon rules."""
    if not heading:
        return TAG_OTHER
    if METHODS_RE.match(heading) or STUDY_RE.match(heading):
        return TAG_METHODS
    if EXCLUDE_RE.match(heading):
        return TAG_EXCLUDE
    if FRONT_RE.match(heading):
        return TAG_FRONT
    return TAG_OTHER


def classify_headings_regex(headings: List[str]) -> List[str]:
    """Classify a list of headings with the regex/lexicon rules (the default classifier)."""
    return [classify_heading_regex(h) for h in headings]


def region_bounds(tags: List[str]) -> Tuple[int, int, bool]:
    """Return (start, end, heading_found) for the methods region given heading tags.

    start: first methods heading (else first non-front section); end: first
    excluded heading at/after start (else len). heading_found: any methods tag.
    """
    n = len(tags)
    heading_found = TAG_METHODS in tags
    if heading_found:
        start = tags.index(TAG_METHODS)
    else:
        start = 0
        while start < n and tags[start] == TAG_FRONT:
            start += 1
    end = next((i for i in range(start, n) if tags[i] == TAG_EXCLUDE), n)
    return start, end, heading_found


def region_has_ambiguous(tags: List[str]) -> bool:
    """True if the methods region contains an unlabeled/ambiguous ('other') section."""
    start, end, _ = region_bounds(tags)
    return any(tags[i] == TAG_OTHER for i in range(start, end))


# Minimum plausible length for a real methods section (chars). Below this, the
# region likely collapsed (e.g. truncated by an early 'Results' subsection).
MIN_METHODS_CHARS = 400

_CAPTION_LEAK_RE = re.compile(r"^\s*(?:##\s*)?(?:figure|fig\.?|table)\s*\d", re.IGNORECASE)


_STUDY_ID_RE = re.compile(r"(study|experiment|phase)\s+(\d+)", re.IGNORECASE)


def _study_ids(heading: str) -> set:
    """Return the set of (kind, number) study identifiers in a heading, e.g. {('study','2')}."""
    return {(m.group(1).lower(), m.group(2)) for m in _STUDY_ID_RE.finditer(heading or "")}


def multi_study_truncated(headings: List[str], tags: List[str]) -> bool:
    """True if the paper has multiple studies but the methods region misses some of them.

    Multi-study papers interleave method/results per study (Study 1 ... Results ...
    Study 2 ...). The 'stop at first exclude heading' rule truncates after the
    first study, dropping later studies' methods. Detect by comparing the distinct
    study identifiers in the WHOLE paper against those inside the captured region.
    """
    all_ids: set = set()
    for h in headings:
        all_ids |= _study_ids(h)
    if len(all_ids) < 2:
        return False  # single-study (or none) -- nothing to truncate
    start, end, _ = region_bounds(tags)
    region_ids: set = set()
    for i in range(start, end):
        region_ids |= _study_ids(headings[i])
    return bool(all_ids - region_ids)  # some study label lies outside the region


def methods_quality_flags(
    methods: str,
    methods_context: str,
    heading_found: bool,
    grobid_ok: bool,
    headings: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
) -> List[str]:
    """Return deterministic low-confidence flags for a methods extraction (no LLM).

    Any non-empty list means the paper should be routed to LLM re-extraction. Flags:
    no_methods_heading, empty_methods, caption_leak, short_methods,
    multi_study_truncation. The last needs `headings` and `tags` to be supplied.
    """
    flags: List[str] = []
    if not grobid_ok:
        return flags  # GROBID-failed papers are handled by the reprocess path instead
    if not heading_found:
        flags.append("no_methods_heading")
    if not methods.strip():
        flags.append("empty_methods")
    if _CAPTION_LEAK_RE.match(methods_context or ""):
        flags.append("caption_leak")
    # Use the wider context for the length check (tight may legitimately be empty
    # when heading_found is False and is already flagged above).
    if len((methods_context or "").strip()) < MIN_METHODS_CHARS:
        flags.append("short_methods")
    if headings is not None and tags is not None and multi_study_truncated(headings, tags):
        flags.append("multi_study_truncation")
    return flags


def _norm(text: str) -> str:
    """Collapse intra-line whitespace, keep content."""
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _div_heading(div: etree._Element) -> str:
    """Return a TEI <div>'s heading text, or '' if absent."""
    head = div.find("tei:head", TEI_NS)
    return _norm("".join(head.itertext())) if head is not None else ""


def _div_body(div: etree._Element) -> str:
    """Return a TEI <div>'s paragraph text (excluding heading, figures, tables), blank-line joined."""
    paras: List[str] = []
    for child in div:
        tag = etree.QName(child).localname
        if tag == "head":
            continue
        if tag in ("p", "quote", "list", "formula"):
            txt = _norm("".join(child.itertext()))
            if txt:
                paras.append(txt)
    return "\n\n".join(paras)


def _block(heading: str, body: str) -> str:
    """Format a section as '## heading\n\n body' (or bare body if unheaded)."""
    if heading:
        return f"## {heading}\n\n{body}".strip()
    return body.strip()


def slice_methods(
    divs: List[etree._Element], headings: List[str], tags: List[str]
) -> Tuple[str, str, bool]:
    """Slice methods/context from pre-classified divs. Returns (tight, context, heading_found)."""
    start, end, heading_found = region_bounds(tags)

    # methods_context: every section in [start, end), verbatim, document order.
    context_blocks = [_block(headings[i], _div_body(divs[i])) for i in range(start, end)]
    methods_context = "\n\n".join(b for b in context_blocks if b.strip()).strip()

    # methods_tight: keep methods AND unlabeled ('other') subsections inside the
    # region (so non-lexicon methods subsections are NOT dropped); only a
    # front-matter heading interrupts the run. Excluded headings already bound
    # the region via `end`. If no methods heading was found, tight stays empty
    # (the recall-safe context carries the content instead).
    tight_blocks: List[str] = []
    keep = False
    for i in range(start, end):
        if tags[i] == TAG_METHODS:
            keep = True
        elif tags[i] == TAG_FRONT:
            keep = False
        # TAG_OTHER: leave `keep` unchanged -> kept while inside a methods run.
        if keep:
            blk = _block(headings[i], _div_body(divs[i]))
            if blk.strip():
                tight_blocks.append(blk)
    methods_tight = "\n\n".join(tight_blocks).strip()

    return methods_tight, methods_context, heading_found


def extract_methods(
    root: etree._Element,
    classifier: Optional[Callable[[List[str]], List[str]]] = None,
) -> Tuple[str, str, bool]:
    """Return (methods_tight, methods_context, methods_heading_found) from a TEI root.

    `classifier` maps a list of headings to a list of tags; defaults to regex.
    Pass an LLM classifier (see heading_classifier.py) as a drop-in alternative.
    """
    tight, context, found, _, _ = extract_methods_detailed(root, classifier=classifier)
    return tight, context, found


def extract_methods_detailed(
    root: etree._Element,
    classifier: Optional[Callable[[List[str]], List[str]]] = None,
) -> Tuple[str, str, bool, List[str], List[str]]:
    """Like extract_methods but also returns (headings, tags) for QA/flagging."""
    body = root.find(".//tei:text/tei:body", TEI_NS)
    if body is None:
        return "", "", False, [], []
    divs = body.findall("tei:div", TEI_NS)
    if not divs:
        return "", "", False, [], []

    headings = [_div_heading(d) for d in divs]
    classify = classifier or classify_headings_regex
    tags = classify(headings)
    tight, context, found = slice_methods(divs, headings, tags)
    return tight, context, found, headings, tags


def list_sections(root: etree._Element) -> List[Tuple[str, str]]:
    """Return [(heading, body), ...] for every body <div>, in document order."""
    body = root.find(".//tei:text/tei:body", TEI_NS)
    if body is None:
        return []
    out: List[Tuple[str, str]] = []
    for d in body.findall("tei:div", TEI_NS):
        out.append((_div_heading(d), _div_body(d)))
    return out


def escalate_methods_whole_paper(
    root: etree._Element,
    select_method_indices: Callable[[List[Tuple[str, str]]], List[int]],
) -> Tuple[str, str]:
    """Recover methods by having an LLM pick methods sections from the WHOLE paper.

    `select_method_indices` receives the full [(heading, body), ...] list and
    returns the indices of sections that describe how the study was conducted
    (methods/participants/procedure/materials/measures/data-analysis/etc., across
    ALL studies; excluding results/discussion/conclusion/related-work). We then
    slice those exact sections VERBATIM from GROBID -- the LLM only chooses
    indices, it never generates text, so the stored methods stay audit-true.

    Returns (methods_text, methods_source). methods_source is 'llm-whole-paper'
    when the LLM selected sections, else '' (caller keeps the original).
    """
    sections = list_sections(root)
    if not sections:
        return "", ""
    try:
        idxs = select_method_indices(sections)
    except Exception as exc:  # noqa: BLE001 -- never let escalation crash a batch
        log(f"[escalate] WARNING: selector failed ({exc}); keeping original")
        return "", ""
    # Keep valid, de-duplicated indices in document order.
    keep = sorted({i for i in idxs if isinstance(i, int) and 0 <= i < len(sections)})
    if not keep:
        return "", ""
    blocks = [_block(sections[i][0], sections[i][1]) for i in keep]
    methods = "\n\n".join(b for b in blocks if b.strip()).strip()
    return methods, ("llm-whole-paper" if methods else "")
