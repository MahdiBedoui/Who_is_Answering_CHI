#!/usr/bin/env python3
"""Stage 2b: LLM escalation for flagged papers (whole-paper methods recovery).

Scans extracted JSON records for `extra.needs_llm_methods == true`, and for each:
  1. re-runs GROBID on the source PDF to get the full section list,
  2. asks an LLM (default GPT-4.1-nano) which sections are methods -- across ALL
     studies, regardless of heading wording,
  3. slices those sections VERBATIM from GROBID (the LLM only picks indices, it
     never generates text) and overwrites the record's `methods`.

Only flagged records are touched; everything else is left exactly as-is. The
record keeps an audit trail: extra.methods_source='llm-whole-paper',
extra.escalated=true, and the pre-escalation methods in extra.methods_pre_escalation.

Usage:
    python scripts/escalate_methods.py --dry-run        # list what would escalate
    python scripts/escalate_methods.py --limit 5        # escalate 5 (smoke test)
    python scripts/escalate_methods.py                  # escalate all flagged
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lxml import etree  # noqa: E402

from src import heading_classifier as hc  # noqa: E402
from src import methods as methods_mod  # noqa: E402
from src.grobid import process_fulltext  # noqa: E402

TEI_PARSER = etree.XMLParser(recover=True, huge_tree=True)


def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)


def find_flagged(input_dir: Path) -> List[Path]:
    """Return JSON record paths whose extra.needs_llm_methods is true."""
    flagged: List[Path] = []
    for fp in sorted(input_dir.rglob("*.json")):
        if fp.name.startswith("_"):
            continue
        try:
            rec = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if rec.get("extra", {}).get("needs_llm_methods") is True:
            flagged.append(fp)
    return flagged


def escalate_one(
    fp: Path, selector, grobid_url: str, overwrite_escalated: bool
) -> str:
    """Escalate a single flagged record in place; return a status string."""
    rec = json.loads(fp.read_text(encoding="utf-8"))
    extra = rec.setdefault("extra", {})

    if extra.get("escalated") and not overwrite_escalated:
        return "already_escalated"

    pdf_path = Path(rec.get("source_pdf_path", ""))
    if not pdf_path.is_file():
        return "pdf_missing"

    tei_xml = process_fulltext(pdf_path, grobid_url=grobid_url)
    if not tei_xml:
        return "grobid_fail"

    root = etree.fromstring(tei_xml.encode("utf-8"), parser=TEI_PARSER)
    methods, source = methods_mod.escalate_methods_whole_paper(root, selector)
    if not methods:
        return "no_methods_selected"

    # Preserve the pre-escalation methods for audit, then overwrite.
    extra["methods_pre_escalation"] = rec.get("methods", "")
    rec["methods"] = methods
    extra["methods_source"] = source
    extra["escalated"] = True
    fp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return "escalated"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="LLM-escalate flagged papers (whole-paper methods).")
    p.add_argument("--input-dir", default="data/extracted", help="Extracted JSON root.")
    p.add_argument("--grobid-url", default="http://localhost:8070", help="GROBID endpoint.")
    p.add_argument("--llm-provider", choices=["openai", "anthropic"], default="openai")
    p.add_argument("--llm-model", default="gpt-4.1-nano", help="Model for section selection.")
    p.add_argument("--limit", type=int, default=0, help="Escalate at most N (0 = all).")
    p.add_argument("--overwrite-escalated", action="store_true",
                   help="Re-escalate records already marked escalated.")
    p.add_argument("--dry-run", action="store_true", help="List flagged papers; change nothing.")
    return p.parse_args(argv)


def build_selector(provider: str, model: str):
    """Construct the whole-paper section selector for the chosen LLM provider."""
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise SystemExit("ERROR: OPENAI_API_KEY not set in environment.")
        completer = hc.openai_completer(key, model=model)
    else:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise SystemExit("ERROR: ANTHROPIC_API_KEY not set in environment.")
        completer = hc.anthropic_completer(key, model=model)
    return hc.make_whole_paper_selector(completer)


def main(argv: Optional[List[str]] = None) -> int:
    """Find flagged records and escalate their methods via whole-paper LLM selection."""
    args = parse_args(argv)
    flagged = find_flagged(Path(args.input_dir))
    if args.limit:
        flagged = flagged[: args.limit]
    log(f"[escalate] {len(flagged)} flagged record(s) to process")

    if args.dry_run:
        for fp in flagged:
            rec = json.loads(fp.read_text(encoding="utf-8"))
            log(f"  {fp.name}  flags={rec.get('extra', {}).get('methods_quality_flags')}")
        return 0

    selector = build_selector(args.llm_provider, args.llm_model)
    counts: dict = {}
    for i, fp in enumerate(flagged, 1):
        try:
            status = escalate_one(fp, selector, args.grobid_url, args.overwrite_escalated)
        except Exception as exc:  # noqa: BLE001
            status = "error"
            log(f"[escalate] ERROR on {fp.name}: {exc}")
        counts[status] = counts.get(status, 0) + 1
        if i % 10 == 0 or i == len(flagged):
            log(f"[escalate] {i}/{len(flagged)}  {counts}")

    log(f"[escalate] DONE  {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
