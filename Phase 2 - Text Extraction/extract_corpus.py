#!/usr/bin/env python3
"""Stage 2 corpus driver: extract every PDF to a resumable JSON record via GROBID.

Walks  sigchi/VERIFIED COUNT/<venue>/<year>/{Research Article,Short Paper,_excluded}/*.pdf
and writes one JSON file per paper to the output dir. Safe to stop and restart:
papers whose JSON already exists are skipped (use --overwrite to force).

Designed for a 4-core / 8 GB machine: keep --workers at 2-3 so GROBID (running in
Docker with a 3 GB heap) is the bottleneck, not your RAM.

Usage:
    python scripts/extract_corpus.py
    python scripts/extract_corpus.py --venue CHI --year 2024 --workers 3
    python scripts/extract_corpus.py --limit 20            # smoke test
    python scripts/extract_corpus.py --venue CHI --heading-classifier hybrid
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

# Allow running as `python scripts/extract_corpus.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extract import extract_record, parse_path_metadata  # noqa: E402


def log(message: str) -> None:
    """Print a progress/warning message to stderr."""
    print(message, file=sys.stderr, flush=True)


def find_pdfs(root: Path, venue: Optional[str], year: Optional[str]) -> List[Path]:
    """Collect candidate PDF paths under the corpus root, optionally filtered."""
    if not root.exists():
        raise FileNotFoundError(f"corpus root not found: {root}")
    pdfs = sorted(root.glob("**/*.pdf"))
    if venue:
        pdfs = [p for p in pdfs if f"/{venue}/" in p.as_posix() or f"\\{venue}\\" in str(p)]
    if year:
        pdfs = [p for p in pdfs if f"/{year}/" in p.as_posix() or f"\\{year}\\" in str(p)]
    return pdfs


def _safe(name: str) -> str:
    """Make a path component filesystem-safe (used for venue/year/type subfolders)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("_") or "unknown"


def output_path(out_dir: Path, pdf_path: Path) -> Path:
    """Map a PDF to data/extracted/<venue>/<year>/<type>/<stem>.json (mirrors the corpus)."""
    meta = parse_path_metadata(pdf_path)
    venue = _safe(meta.get("venue") or "unknown")
    year = _safe(meta.get("year") or "unknown")
    ptype = _safe(meta.get("ptype") or "unknown")
    return out_dir / venue / year / ptype / f"{pdf_path.stem}.json"


def process_one(
    pdf_path: Path, out_dir: Path, grobid_url: str, openalex_mailto: str,
    openalex_fallback: bool, openalex_crosscheck: bool, openalex_cache_dir: str,
    overwrite: bool, heading_classifier=None,
) -> Dict[str, object]:
    """Extract a single PDF to JSON; return a small status dict for the progress log."""
    out_file = output_path(out_dir, pdf_path)
    # Resume logic: a paper is "done" only if its JSON exists AND GROBID succeeded.
    # Records written during a GROBID outage (grobid_ok=false / needs_reprocess)
    # are treated as NOT done so a re-run retries them, while good records skip.
    if out_file.exists() and not overwrite:
        try:
            prior = json.loads(out_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- unreadable JSON -> re-extract
            prior = {}
        if prior.get("grobid_ok") is True:
            return {"status": "skipped", "pdf": pdf_path.name}
        # else: fall through and re-extract this previously-failed paper
    try:
        record = extract_record(
            pdf_path, grobid_url=grobid_url, openalex_mailto=openalex_mailto,
            openalex_fallback=openalex_fallback, openalex_crosscheck=openalex_crosscheck,
            openalex_cache_dir=openalex_cache_dir, heading_classifier=heading_classifier,
        )
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        status = "ok" if record.get("grobid_ok") else "grobid_fail"
        return {"status": status, "pdf": pdf_path.name, "doi": record.get("doi", "")}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "pdf": pdf_path.name, "error": str(exc)}


def build_heading_classifier(mode: str, provider: str, model: str, cache_dir: str):
    """Construct the methods heading classifier for the chosen mode (regex|llm|hybrid)."""
    if mode == "regex":
        return None
    import os
    from src import heading_classifier as hc
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise SystemExit(
                "ERROR: --heading-classifier llm/hybrid with --llm-provider openai "
                "requires OPENAI_API_KEY in the environment."
            )
        completer = hc.openai_completer(api_key, model=model)
    elif provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise SystemExit(
                "ERROR: --heading-classifier llm/hybrid with --llm-provider anthropic "
                "requires ANTHROPIC_API_KEY in the environment."
            )
        completer = hc.anthropic_completer(api_key, model=model)
    else:
        raise SystemExit(f"unknown --llm-provider: {provider}")
    if mode == "llm":
        return hc.make_llm_classifier(completer)
    if mode == "hybrid":
        return hc.make_hybrid_classifier(completer, cache_dir=cache_dir)
    raise SystemExit(f"unknown --heading-classifier mode: {mode}")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Extract the SIGCHI corpus to JSON via GROBID.")
    p.add_argument("--corpus-root", default="sigchi/VERIFIED COUNT", help="Root of the PDF corpus.")
    p.add_argument("--output-dir", default="data/extracted", help="Where JSON records are written.")
    p.add_argument("--grobid-url", default="http://localhost:8070", help="GROBID endpoint.")
    p.add_argument("--workers", type=int, default=3, help="Concurrent workers (2-3 for 4 cores).")
    p.add_argument("--venue", default=None, help="Only this venue (e.g. CHI).")
    p.add_argument("--year", default=None, help="Only this year (e.g. 2024).")
    p.add_argument("--limit", type=int, default=0, help="Process at most N PDFs (0 = all).")
    p.add_argument("--overwrite", action="store_true", help="Re-extract even if JSON exists.")
    p.add_argument("--no-openalex-fallback", dest="openalex_fallback", action="store_false",
                   help="Disable the OpenAlex abstract fallback (on by default; fires only when "
                        "the PDF yields no abstract).")
    p.add_argument("--openalex-crosscheck", action="store_true",
                   help="Fetch OpenAlex for EVERY paper to flag PDF/OpenAlex divergence "
                        "(one API call per paper; best run per-venue).")
    p.add_argument("--openalex-cache", default="data/cache/openalex",
                   help="Directory for the DOI-keyed OpenAlex response cache.")
    p.add_argument("--mailto", default="", help="Contact email for the OpenAlex polite pool.")
    p.add_argument("--heading-classifier", choices=["regex", "llm", "hybrid"], default="regex",
                   help="Methods heading classifier: regex (default), llm (always call), or "
                        "hybrid (regex first; LLM only when no methods heading is found).")
    p.add_argument("--llm-provider", choices=["openai", "anthropic"], default="openai",
                   help="LLM provider for the llm/hybrid heading classifier (default: openai).")
    p.add_argument("--llm-model", default="gpt-4.1-nano",
                   help="Model id for the llm/hybrid heading classifier (default: gpt-4.1-nano).")
    p.add_argument("--llm-cache", default="data/cache/headings",
                   help="Directory for the hybrid classifier's escalation cache.")
    p.add_argument("--abort-after", type=int, default=25,
                   help="Circuit breaker: abort the run after this many CONSECUTIVE GROBID "
                        "failures (likely a dead server). 0 disables. Default 25.")
    p.set_defaults(openalex_fallback=True)
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Run the corpus extraction with a thread pool and a failure log."""
    args = parse_args(argv)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fail_log = out_dir / "_failures.jsonl"

    pdfs = find_pdfs(Path(args.corpus_root), args.venue, args.year)
    if args.limit:
        pdfs = pdfs[: args.limit]
    total = len(pdfs)
    classifier = build_heading_classifier(
        args.heading_classifier, args.llm_provider, args.llm_model, args.llm_cache
    )
    log(f"[corpus] {total} PDFs to consider | workers={args.workers} | "
        f"out={out_dir} | classifier={args.heading_classifier}")

    counts = {"ok": 0, "grobid_fail": 0, "skipped": 0, "error": 0}
    started = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool, \
            fail_log.open("a", encoding="utf-8") as flog:
        futures = {
            pool.submit(process_one, pdf, out_dir, args.grobid_url, args.mailto,
                        args.openalex_fallback, args.openalex_crosscheck,
                        args.openalex_cache, args.overwrite, classifier): pdf
            for pdf in pdfs
        }
        done = 0
        consecutive_fail = 0
        aborted = False
        for fut in as_completed(futures):
            res = fut.result()
            counts[res["status"]] = counts.get(res["status"], 0) + 1
            if res["status"] in ("grobid_fail", "error"):
                flog.write(json.dumps(res, ensure_ascii=False) + "\n")
                flog.flush()
                consecutive_fail += 1
            else:
                consecutive_fail = 0
            done += 1
            if done % 25 == 0 or done == total:
                rate = done / max(time.time() - started, 1e-6)
                eta = (total - done) / rate if rate else 0
                log(f"[corpus] {done}/{total}  ok={counts['ok']} "
                    f"skip={counts['skipped']} gfail={counts['grobid_fail']} "
                    f"err={counts['error']}  {rate:.1f}/s  ETA {eta/60:.1f}m")
            # Circuit breaker: many failures in a row almost always means GROBID
            # is down. Abort fast instead of grinding through the whole corpus.
            if args.abort_after and consecutive_fail >= args.abort_after:
                log(f"[corpus] ABORTING: {consecutive_fail} consecutive GROBID failures "
                    f"-- GROBID looks down. Check it (curl {args.grobid_url}/api/isalive), "
                    f"then re-run the SAME command to resume (good records are skipped).")
                aborted = True
                for f in futures:
                    f.cancel()
                break

    log(f"[corpus] {'ABORTED' if aborted else 'DONE'} in {(time.time()-started)/60:.1f}m  {counts}")
    if counts["grobid_fail"] or counts["error"]:
        log(f"[corpus] {counts['grobid_fail']+counts['error']} failures logged to {fail_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
