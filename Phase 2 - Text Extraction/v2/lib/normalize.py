"""Text normalization shared by all candidates before comparison.

Two forms per candidate:
  * stored form   -- cleaned but human-faithful (casing/punctuation preserved)
  * comparison form -- aggressively normalized, used ONLY for similarity scoring
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Ligature repair.
# PDF fonts with broken ToUnicode maps collapse ff/fi/fl/ffi/ffl to a bare "f"
# ("affect" -> "afect", "significant" -> "signifcant"). We repair via a map
# generated from a curated vocabulary of academic/HCI words: for every word
# containing a ligature cluster we derive its collapsed variant.
# Deterministic, logged, and extendable: add words to _VOCAB as the corpus scan
# surfaces new artifacts (05_qa_report.py flags residue).
# ---------------------------------------------------------------------------

_VOCAB = """
affect affects affected affecting affective effect effects effective effectively effectiveness
efficacy efficient efficiently efficiency sufficient sufficiently insufficient office offline official
difficult difficulty difficulties different differently difference differences differ differs
significant significantly significance specific specifically specification specifications specified specify
find finds finding findings first finally final define defines defined defining definition definitions
identify identifies identified identifying identification influence influences influenced influencing
workflow workflows conflict conflicts confirm confirms confirmed confirmatory configuration configurations
benefit benefits beneficial field fields figure figures file files filter filters fit fits fitted
reflect reflects reflected reflection reflections refine refined refinement classification classifications
classified artificial scientific justification verification notification notifications profile profiles
fiction confidence confident confidential field-study fine-grained fifty fifteen difficulty
self-efficacy traffic affordance affordances offer offers offered offering scaffolding
""".split()

_LIG_CLUSTERS = ("ffi", "ffl", "ff", "fi", "fl")


def _collapse(word: str) -> str | None:
    out = word
    hit = False
    for cl in _LIG_CLUSTERS:
        if cl in out:
            out = out.replace(cl, "f")
            hit = True
    return out if hit and out != word else None


_REPAIR_MAP: Dict[str, str] = {}
for _w in _VOCAB:
    _c = _collapse(_w)
    if _c:
        _REPAIR_MAP[_c] = _w

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z-]*")

# Residue detector: common collapsed stems that survived repair (QA flag only).
SUSPECT_LIGATURE_RE = re.compile(
    r"\b\w*(?:afect|efect|signifc|specifc|difcult|diferen|sufcien|efcien|"
    r"identifc|confict|benefcial|defnit|fnding|workfow)\w*\b", re.I)


def repair_ligatures(text: str) -> Tuple[str, List[str]]:
    """Repair known ligature-collapsed words. Returns (text, list_of_repairs)."""
    repairs: List[str] = []

    def fix(m: re.Match) -> str:
        tok = m.group(0)
        rep = _REPAIR_MAP.get(tok.lower())
        if rep is None:
            return tok
        if tok[0].isupper():
            rep = rep[0].upper() + rep[1:]
        repairs.append(f"{tok}->{rep}")
        return rep

    return _TOKEN_RE.sub(fix, text), repairs


# ---------------------------------------------------------------------------
# General cleanup
# ---------------------------------------------------------------------------

_BLEED_RE = re.compile(
    r"(?is)\s*(?:CCS\s+CONCEPTS?|KEYWORDS?\s*:|ACM\s+Reference\s+Format|"
    r"Permission\s+to\s+make\s+digital|1\s+INTRODUCTION|1\.\s*Introduction).*$")
_PREFIX_RE = re.compile(r"(?is)^\s*ABSTRACT\s*[:.\-]?\s*")


def clean_stored(text: str, pdf_derived: bool) -> Tuple[str, List[str]]:
    """Produce the stored form. Ligature repair only on PDF-derived candidates."""
    if not text:
        return "", []
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"-\n(\w)", r"\1", t)          # join hyphenated line breaks
    t = re.sub(r"\s*\n\s*", " ", t)           # unwrap soft breaks
    t = re.sub(r"[ \t]+", " ", t).strip()
    t = _PREFIX_RE.sub("", t)
    t = _BLEED_RE.sub("", t).strip()
    repairs: List[str] = []
    if pdf_derived:
        t, repairs = repair_ligatures(t)
    return t, repairs


_PUNCT_RE = re.compile(r"[^\w\s]")


def comparison_form(stored: str) -> str:
    t = stored.lower()
    t = _PUNCT_RE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()
