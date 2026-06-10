"""Pluggable heading classifiers for methods isolation.

A classifier maps a list of section headings to a list of tags drawn from
methods.{TAG_METHODS, TAG_EXCLUDE, TAG_FRONT, TAG_OTHER}, one tag per heading.

Implementations:
  * `regex_classifier`  -- the deterministic default (re-exported from methods).
  * `make_llm_classifier(complete)` -- an LLM that tags the heading LIST only
    (a few dozen tokens per paper). Provider-agnostic: inject a
    `complete(prompt) -> str` function so it works with any model.
  * `make_hybrid_classifier(complete, cache_dir)` -- runs regex first and only
    escalates to the LLM when regex finds NO methods heading (the uncertain
    case). Cheapest + most accurate; caches escalations by heading list.

All are drop-in: pass any of them to methods.extract_methods(..., classifier=...).
The hybrid/LLM objects also expose a thread-local `.source` so callers can
record which path produced each paper's tags (provenance).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .methods import (
    TAG_EXCLUDE,
    TAG_FRONT,
    TAG_METHODS,
    TAG_OTHER,
    classify_headings_regex,
    region_has_ambiguous,
)

# The deterministic default classifier.
regex_classifier: Callable[[List[str]], List[str]] = classify_headings_regex

# Rich LLM label set -> internal slicing tag.
_LLM_TAG_MAP: Dict[str, str] = {
    "methods": TAG_METHODS,
    "results": TAG_EXCLUDE,
    "discussion": TAG_EXCLUDE,
    "back-matter": TAG_EXCLUDE,
    "front-matter": TAG_FRONT,
    "related": TAG_FRONT,
    "other": TAG_OTHER,
}

_PROMPT = """You label section headings from one academic HCI paper.

For EACH heading below, output exactly one label from this set:
  front-matter | related | methods | results | discussion | back-matter | other

Guidance:
- methods: how the study was run -- Method(s), Methodology, Study Design,
  Participants, Procedure, Apparatus, Materials, Measures, Tasks, Conditions,
  Data Collection/Analysis, Recruitment, Survey Design, Evaluation, "Study N",
  "Experiment N", User Study, Field Deployment, and system/approach sections
  that describe what was built and how it was tested.
- front-matter: Introduction, Background, Motivation.
- related: Related Work, Prior Work, Literature Review.
- results: Results, Findings.
- discussion: Discussion, Limitations, Conclusion, Future Work.
- back-matter: Acknowledgments, References, Appendix.
- other: anything that doesn't clearly fit.

Return ONLY a JSON array of strings, same length and order as the input.

Headings:
{headings}
"""


def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)


def _build_prompt(headings: List[str]) -> str:
    """Render the classification prompt from a numbered heading list."""
    listing = "\n".join(f"{i}. {h or '(no heading)'}" for i, h in enumerate(headings))
    return _PROMPT.format(headings=listing)


def _map_tag(raw: str) -> str:
    """Map one raw LLM label to an internal slicing tag (defaults to OTHER)."""
    return _LLM_TAG_MAP.get(str(raw).strip().lower(), TAG_OTHER)


def _parse_tags(text: str, n: int) -> List[str]:
    """Parse a JSON array of labels from model output; raise if it isn't usable."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON array found in model output")
    arr = json.loads(match.group(0))
    if not isinstance(arr, list) or len(arr) != n:
        raise ValueError(f"expected {n} labels, got {len(arr) if isinstance(arr, list) else '?'}")
    return [_map_tag(x) for x in arr]


def make_llm_classifier(
    complete: Callable[[str], str],
    fallback: Callable[[List[str]], List[str]] = classify_headings_regex,
) -> Callable[[List[str]], List[str]]:
    """Build a classifier that tags headings via an injected `complete(prompt)->str` LLM call.

    On any error (network, malformed output, length mismatch) it falls back to
    the regex classifier so a single bad call never aborts a corpus run.
    """

    def classify(headings: List[str]) -> List[str]:
        """Classify headings with the LLM, falling back to regex on failure."""
        if not headings:
            return []
        try:
            out = complete(_build_prompt(headings))
            return _parse_tags(out, len(headings))
        except Exception as exc:  # noqa: BLE001
            log(f"[heading-llm] WARNING: falling back to regex ({exc})")
            return fallback(headings)

    return classify


def _headings_key(headings: List[str]) -> str:
    """Stable cache key for a heading list (order-sensitive)."""
    joined = "␟".join(headings)  # unit-separator unlikely to occur in headings
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def _merge_regex_precedence(regex_tags: List[str], llm_tags: List[str]) -> List[str]:
    """Combine tags with regex precedence: the LLM only fills headings regex tagged 'other'.

    Confident regex calls (methods/exclude/front) are authoritative -- this stops
    the LLM from demoting a lexicon-clear heading like "Data Analysis" (methods)
    to results and truncating the methods region. The LLM adjudicates only the
    genuinely ambiguous ('other') headings.
    """
    if len(regex_tags) != len(llm_tags):
        return regex_tags  # length mismatch -> trust the deterministic path
    return [
        llm if regex == TAG_OTHER else regex
        for regex, llm in zip(regex_tags, llm_tags)
    ]


class HybridClassifier:
    """Regex-first classifier that escalates to an LLM only when regex finds no methods heading.

    Escalations are cached on disk by heading list, so re-runs are free and
    reproducible. `.source` (thread-local) reports the path used for the most
    recent call in the current thread: 'regex', 'llm', or 'llm-cache'.
    """

    def __init__(
        self,
        complete: Callable[[str], str],
        cache_dir: Optional[str] = None,
        fallback: Callable[[List[str]], List[str]] = classify_headings_regex,
    ) -> None:
        """Store the LLM call, optional cache directory, and a thread-local source marker."""
        self._llm = make_llm_classifier(complete, fallback=fallback)
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._local = threading.local()

    @property
    def source(self) -> Optional[str]:
        """Path used for the most recent call in this thread ('regex'|'llm'|'llm-cache')."""
        return getattr(self._local, "source", None)

    def _cache_file(self, headings: List[str]) -> Path:
        """Return the cache path for a heading list."""
        return self._cache_dir / f"{_headings_key(headings)}.json"  # type: ignore[union-attr]

    def _read_cache(self, headings: List[str]) -> Optional[List[str]]:
        """Return cached tags for these headings, or None on miss/invalid."""
        if self._cache_dir is None:
            return None
        cf = self._cache_file(headings)
        if not cf.exists():
            return None
        try:
            data = json.loads(cf.read_text(encoding="utf-8"))
            tags = data.get("tags")
            if isinstance(tags, list) and len(tags) == len(headings):
                return tags
        except Exception:  # noqa: BLE001 -- bad cache file == miss
            return None
        return None

    def _write_cache(self, headings: List[str], tags: List[str]) -> None:
        """Persist tags for these headings (best-effort)."""
        if self._cache_dir is None:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_file(headings).write_text(
                json.dumps({"headings": headings, "tags": tags}), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            log(f"[heading-cache] WARNING: could not cache ({exc})")

    def __call__(self, headings: List[str]) -> List[str]:
        """Classify headings, escalating to the (cached) LLM when regex is uncertain.

        Escalate when regex finds NO methods heading at all, OR when the methods
        region contains an unlabeled/ambiguous ('other') subsection (e.g. a
        methods subsection with a non-lexicon name like "Audio Stimuli"). Papers
        whose methods region is cleanly labeled stay on the free regex path.
        """
        regex_tags = classify_headings_regex(headings)
        confident = (
            TAG_METHODS in regex_tags
            and not region_has_ambiguous(regex_tags)
        )
        if not headings or confident:
            self._local.source = "regex"
            return regex_tags

        cached = self._read_cache(headings)
        if cached is not None:
            self._local.source = "llm-cache"
            return _merge_regex_precedence(regex_tags, cached)

        llm_tags = self._llm(headings)
        self._local.source = "llm"
        self._write_cache(headings, llm_tags)
        return _merge_regex_precedence(regex_tags, llm_tags)


def make_hybrid_classifier(
    complete: Callable[[str], str],
    cache_dir: Optional[str] = None,
    fallback: Callable[[List[str]], List[str]] = classify_headings_regex,
) -> HybridClassifier:
    """Build a regex-first / LLM-escalating classifier with an on-disk escalation cache."""
    return HybridClassifier(complete, cache_dir=cache_dir, fallback=fallback)


def anthropic_completer(api_key: str, model: str = "claude-haiku-4-5-20251001") -> Callable[[str], str]:
    """Return a `complete(prompt)->str` backed by Anthropic (imported lazily; optional dep)."""
    import anthropic  # noqa: F401 -- optional; only needed if you use this completer

    client = anthropic.Anthropic(api_key=api_key)

    def complete(prompt: str) -> str:
        """Send the prompt to a small Claude model and return the text response."""
        msg = client.messages.create(
            model=model, max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")

    return complete


def openai_completer(api_key: str, model: str = "gpt-4.1-nano") -> Callable[[str], str]:
    """Return a `complete(prompt)->str` backed by OpenAI (imported lazily; optional dep)."""
    import openai  # noqa: F401 -- optional; only needed if you use this completer

    client = openai.OpenAI(api_key=api_key)

    def complete(prompt: str) -> str:
        """Send the prompt to a small OpenAI model and return the text response."""
        resp = client.chat.completions.create(
            model=model,
            max_tokens=1024,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""

    return complete


_SELECT_PROMPT = """You are given the numbered sections of one academic HCI paper
(heading + a snippet of body). Identify which sections describe HOW THE RESEARCH
WAS CONDUCTED -- the methods. Include, across ALL studies in the paper:
study design, participants/subjects, recruitment, procedure, materials, apparatus,
measures, conditions, tasks, stimuli, survey/questionnaire design, data collection,
and data analysis. INCLUDE method sections even if titled unusually (e.g.,
"Approach", "Evaluation", "User Study", "Wizard of Oz Study", "Study 1", "Field
Deployment"). EXCLUDE introduction, related/background work, results/findings,
discussion, limitations, conclusion, references, and ALL appendix or supplementary
sections (e.g. headings starting with "Appendix", "A.1", "B ", "C ", or labeled
supplementary material) -- even if they contain method-like code or details.

Return ONLY a JSON array of the integer indices of the methods sections.

Sections:
{sections}
"""


def _build_select_prompt(sections: List, snippet_chars: int = 300) -> str:
    """Render the section-selection prompt from [(heading, body), ...]."""
    lines = []
    for i, (head, body) in enumerate(sections):
        snippet = (body or "")[:snippet_chars].replace("\n", " ")
        lines.append(f"[{i}] {head or '(no heading)'} :: {snippet}")
    return _SELECT_PROMPT.format(sections="\n".join(lines))


def make_whole_paper_selector(
    complete: Callable[[str], str], snippet_chars: int = 300
) -> Callable[[List], List[int]]:
    """Build a selector(sections)->[indices] that asks an LLM which sections are methods.

    `sections` is [(heading, body), ...] for the whole paper. Used by
    methods.escalate_methods_whole_paper to recover methods on flagged papers.
    Raises on unusable output so the caller can keep the original extraction.
    """

    def select(sections: List) -> List[int]:
        """Return indices of methods sections per the LLM (raises on bad output)."""
        if not sections:
            return []
        out = complete(_build_select_prompt(sections, snippet_chars))
        match = re.search(r"\[.*\]", out, re.DOTALL)
        if not match:
            raise ValueError("no JSON array in model output")
        arr = json.loads(match.group(0))
        if not isinstance(arr, list):
            raise ValueError("model output is not a list")
        return [int(x) for x in arr if isinstance(x, (int, float))]

    return select


# ---------------------------------------------------------------------------
# A/B helpers
# ---------------------------------------------------------------------------

def compare_classifiers(
    headings: List[str], classifiers: Dict[str, Callable[[List[str]], List[str]]]
) -> Dict[str, List[str]]:
    """Run several named classifiers on the same headings; return name -> tags."""
    return {name: clf(headings) for name, clf in classifiers.items()}


def tag_disagreements(
    headings: List[str], tags_a: List[str], tags_b: List[str]
) -> List[Dict[str, str]]:
    """Return per-heading rows where two tag lists disagree (for A/B inspection)."""
    rows: List[Dict[str, str]] = []
    for h, a, b in zip(headings, tags_a, tags_b):
        if a != b:
            rows.append({"heading": h, "a": a, "b": b})
    return rows
