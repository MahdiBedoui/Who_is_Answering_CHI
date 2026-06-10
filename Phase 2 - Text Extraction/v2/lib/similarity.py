"""Candidate similarity. SequenceMatcher ratio over comparison forms (stdlib, deterministic)."""
from __future__ import annotations

from difflib import SequenceMatcher

from .config import SIM_THRESHOLD


def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def agree(a: str, b: str, threshold: float = SIM_THRESHOLD) -> bool:
    return ratio(a, b) >= threshold
