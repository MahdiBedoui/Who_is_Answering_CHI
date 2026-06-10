#!/usr/bin/env python3
"""Stage 04 -- resolve each paper's candidates into one abstract (or route it onward).

Resolution table (docs/EXTRACTION_V2_PLAN.md §4):
  publisher text + >=1 PDF candidate agrees        -> resolved (publisher, high)
  publisher candidates agree, no PDF agreement     -> resolved (publisher, high,
                                                      flag pdf_divergent / pdf_unverified)
  single publisher source, no PDF evidence         -> resolved (publisher, medium,
                                                      flag single_source_unverified)
  no publisher; >=2 PDF candidates agree           -> resolved (docling-preferred, medium)
  conflict                                         -> needs_adjudication (--adjudicate calls OpenAI)
  nothing                                          -> manual_queue

    python 04_resolve.py --data-store ...                  # rule-based only
    python 04_resolve.py --data-store ... --adjudicate     # + OpenAI on conflicts
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from itertools import combinations
from pathlib import Path

V2_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(V2_DIR))

from lib import config  # noqa: E402
from lib.normalize import comparison_form, clean_stored  # noqa: E402
from lib.qa_flags import text_flags  # noqa: E402
from lib.records import iter_records, save_record, now_iso  # noqa: E402
from lib.similarity import ratio  # noqa: E402

PUB_PREF = ("openalex", "crossref", "semanticscholar")  # publisher-form preference order
PDF_PREF = ("docling", "pdfplumber", "grobid")          # OCR path preferred


def ok_texts(rec: dict) -> dict:
    return {s: c["text"] for s, c in rec.get("candidates", {}).items()
            if c.get("ok") and c.get("text")}


def pairwise(texts: dict) -> dict:
    forms = {s: comparison_form(t) for s, t in texts.items()}
    return {f"{a}|{b}": round(ratio(forms[a], forms[b]), 4)
            for a, b in combinations(sorted(forms), 2)}


def adjudicate_openai(rec: dict, texts: dict, model: str) -> tuple[str, str] | None:
    """Ask OpenAI to pick/reconstruct the correct abstract. Returns (text, note) or None."""
    try:
        from openai import OpenAI
    except ImportError:
        raise SystemExit("--adjudicate requires: pip install openai")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("--adjudicate requires OPENAI_API_KEY in the environment.")
    client = OpenAI()
    cands = "\n\n".join(f"### candidate `{s}`\n{t}" for s, t in sorted(texts.items()))
    prompt = (
        "Below are candidate extractions of the ABSTRACT of one ACM SIGCHI paper, "
        f"DOI {rec['doi']}, from different extractors. They disagree.\n"
        "Reconstruct the single correct abstract text: fix PDF-extraction artifacts "
        "(missing ligatures like 'afect'->'affect', mid-sentence truncation, bleed from "
        "CCS CONCEPTS/keywords), but NEVER paraphrase, summarize, or add content. "
        "If one candidate is already correct and complete, return it verbatim.\n"
        'Reply as JSON: {"abstract": "...", "note": "<which candidates were right/wrong and why>"}'
        f"\n\n{cands}"
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    try:
        data = json.loads(resp.choices[0].message.content)
        text = (data.get("abstract") or "").strip()
        return (text, data.get("note", "")) if text else None
    except (json.JSONDecodeError, AttributeError, IndexError):
        return None


def resolve_one(rec: dict, threshold: float) -> dict:
    texts = ok_texts(rec)
    scores = pairwise(texts)
    res = {"status": None, "text": "", "source": "", "confidence": "",
           "scores": scores, "flags": [], "adjudication_note": "",
           "parser_version": config.PARSER_VERSION, "resolved_at": now_iso()}

    def agree(a: str, b: str) -> bool:
        k = f"{min(a, b)}|{max(a, b)}"
        return scores.get(k, 0.0) >= threshold

    pubs = [s for s in PUB_PREF if s in texts]
    pdfs = [s for s in PDF_PREF if s in texts]

    if not texts:
        res["status"] = "manual_queue"
        res["flags"] = ["empty"]
        return res

    if pubs:
        best_pub = pubs[0]
        if any(agree(best_pub, s) for s in pdfs):
            res.update(status="resolved", text=texts[best_pub], source=best_pub,
                       confidence="high")
        elif len(pubs) >= 2 and all(agree(pubs[0], s) for s in pubs[1:]):
            res.update(status="resolved", text=texts[best_pub], source=best_pub,
                       confidence="high")
            # Distinguish real conflict from absent PDF evidence (API-only runs).
            res["flags"].append("pdf_divergent" if pdfs else "pdf_unverified")
        elif len(pubs) == 1 and not pdfs:
            # Single publisher source, no PDF evidence yet: accept provisionally.
            # Nothing to adjudicate against; gold set + later PDF passes verify these.
            res.update(status="resolved", text=texts[best_pub], source=best_pub,
                       confidence="medium")
            res["flags"].append("single_source_unverified")
        else:
            res["status"] = "needs_adjudication"
    else:
        agreeing = [(a, b) for a, b in combinations(pdfs, 2) if agree(a, b)]
        if agreeing:
            pick = next((s for s in PDF_PREF if any(s in pair for pair in agreeing)))
            res.update(status="resolved", text=texts[pick], source=pick,
                       confidence="medium")
        else:
            res["status"] = "needs_adjudication"  # PDF-only conflict or single candidate

    res["flags"] += text_flags(res["text"]) if res["text"] else []
    return res


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    config.add_common_args(p)
    p.add_argument("--threshold", type=float, default=config.SIM_THRESHOLD)
    p.add_argument("--adjudicate", action="store_true",
                   help="Call OpenAI on conflicts (needs OPENAI_API_KEY).")
    p.add_argument("--model", default="gpt-4o",
                   help="OpenAI model for adjudication.")
    p.add_argument("--force", action="store_true",
                   help="Re-resolve records already resolved by this parser version.")
    args = p.parse_args()

    ds = config.data_store(args.data_store)
    section_dir = config.sections_dir(ds, "abstracts")

    counts: dict = {}
    n = 0
    for rec in iter_records(section_dir, args.venue, args.years):
        n += 1
        if args.limit and n > args.limit:
            break
        old = rec.get("resolution") or {}
        if (not args.force and old.get("parser_version") == config.PARSER_VERSION
                and old.get("status") in ("resolved", "llm_adjudicated", "manual_queue")):
            counts[old["status"]] = counts.get(old["status"], 0) + 1
            continue

        res = resolve_one(rec, args.threshold)

        if res["status"] == "needs_adjudication" and args.adjudicate:
            texts = ok_texts(rec)
            try:
                out = adjudicate_openai(rec, texts, args.model)
            except SystemExit:
                raise
            except Exception as exc:
                print(f"[adjudicate] {rec['doi']}: {exc}", file=sys.stderr)
                out = None
            if out:
                text, note = out
                text, _ = clean_stored(text, pdf_derived=False)
                res.update(status="llm_adjudicated", text=text, source=f"openai:{args.model}",
                           confidence="low", adjudication_note=note)
                res["flags"] = text_flags(text)

        rec["resolution"] = res
        save_record(section_dir, rec)
        counts[res["status"]] = counts.get(res["status"], 0) + 1
        if n % 500 == 0:
            print(f"...{n} records", file=sys.stderr)

    print(f"\nResolved {n} records:")
    for k in sorted(counts):
        print(f"  {k:20s} {counts[k]}")
    if counts.get("needs_adjudication") and not args.adjudicate:
        print("\nRe-run with --adjudicate to send conflicts to OpenAI.")


if __name__ == "__main__":
    main()
