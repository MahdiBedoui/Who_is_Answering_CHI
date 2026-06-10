"""QA flags. Flags never drop a record -- they route it (resolution / report / gold oversample)."""
from __future__ import annotations

import re
from typing import List

from .normalize import SUSPECT_LIGATURE_RE

MIN_LEN = 400
MAX_LEN = 3000

_NON_ASCII_HEAVY = re.compile(r"[^\x00-\x7F]")
_CCS_RE = re.compile(r"(?i)CCS\s+CONCEPTS?|ACM\s+Reference\s+Format")
_MID_SENT_START = re.compile(r"^[a-z,;)]")


def text_flags(text: str) -> List[str]:
    flags: List[str] = []
    t = (text or "").strip()
    if not t:
        return ["empty"]
    if len(t) < MIN_LEN:
        flags.append("too_short")
    if len(t) > MAX_LEN:
        flags.append("too_long")
    if t[-1] not in '.!?"”’':
        flags.append("no_end_punct")
    if _CCS_RE.search(t):
        flags.append("ccs_bleed")
    if SUSPECT_LIGATURE_RE.search(t):
        flags.append("ligature_artifact")
    if _MID_SENT_START.match(t):
        flags.append("mid_sentence_start")
    # crude language check: heavy non-ascii share suggests mojibake / non-English
    if len(_NON_ASCII_HEAVY.findall(t)) > len(t) * 0.15:
        flags.append("non_english_or_mojibake")
    return flags
