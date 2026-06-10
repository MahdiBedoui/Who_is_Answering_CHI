#!/usr/bin/env python3
"""Compare GROBID CRF vs deep-learning (full) models on a sample of papers.

Re-processes a sample of PDFs through a GROBID endpoint (point it at the DL/full
image) and runs the SAME extraction logic (src.abstract / src.methods) so any
difference is purely the model, not the code. Compares against the existing
CRF-produced JSON records and writes a side-by-side CSV + summary.

Intended use: stand up the full GROBID image (grobid-full / DL models) on its own
port, then run this against it to see whether DL meaningfully improves abstract
and methods extraction before committing to a full corpus re-run.

Usage (run where GROBID-DL is reachable, e.g. on the instance):
    python scripts/compare_grobid_models.py \
        --extracted-dir data/extracted_cloud \
        --pdf-root /home/ubuntu/chi/corpus \
        --grobid-url http://localhost:8070 \
        --sample flagged --n 50 --out dl_vs_crf.csv

  --sample flagged   : papers with needs_llm_methods=true (methods stress test)
  --sample grobid    : papers whose abstract came from GROBID fallback (the 664)
  --sample random    : a random spread
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import abstract as abs_mod  # noqa: E402
from src import methods as methods_mod  # noqa: E402
from src.grobid import process_fulltext  # noqa: E402
from lxml import etree  # noqa: E402


def log(msg: str) -> None:
    """Print progress to stderr."""
    print(msg, file=sys.stderr, flush=True)


def remap_pdf(stored: str, pdf_root: str) -> str:
    """Remap a stored PDF path onto a given corpus root, preserving venue/year/type/file."""
    if not stored:
        return ""
    parts = stored.replace("\\", "/").split("/")
    for i, seg in enumerate(parts):
        if seg.isdigit() and len(seg) == 4 and i > 0:
            return str(Path(pdf_root) / "/".join(parts[i - 1:]))
    return stored


def select_sample(records: List[dict], mode: str, n: int) -> List[dict]:
    """Pick the sample of records to re-process per the chosen mode."""
    if mode == "flagged":
        pool = [r for r in records if r.get("extra", {}).get("needs_llm_methods") is True]
    elif mode == "grobid":
        pool = [r for r in records if r.get("abstract_source") == "grobid"]
    else:
        pool = list(records)
    random.seed(42)
    random.shuffle(pool)
    return pool[:n]


def dl_extract(pdf_path: Path, grobid_url: str) -> Dict[str, object]:
    """Re-process one PDF through the given GROBID endpoint; return abstract+methods."""
    tei = process_fulltext(pdf_path, grobid_url=grobid_url)
    if not tei:
        return {"ok": False, "abstract": "", "methods": "", "heading_found": None}
    root = etree.fromstring(tei.encode("utf-8"),
                            parser=etree.XMLParser(recover=True, huge_tree=True))
    abstract = abs_mod.abstract_from_tei(tei)
    tight, _ctx, found = methods_mod.extract_methods(root)
    return {"ok": True, "abstract": abstract, "methods": tight, "heading_found": found}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Compare GROBID CRF vs DL on a sample.")
    p.add_argument("--extracted-dir", default="data/extracted_cloud")
    p.add_argument("--pdf-root", required=True, help="Local corpus root holding the PDFs.")
    p.add_argument("--grobid-url", default="http://localhost:8070",
                   help="GROBID-DL endpoint to test against.")
    p.add_argument("--sample", choices=["flagged", "grobid", "random"], default="flagged")
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--out", default="dl_vs_crf.csv")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Run the CRF-vs-DL comparison and write a side-by-side CSV + summary."""
    args = parse_args(argv)
    root = Path(args.extracted_dir)
    records = []
    for fp in root.rglob("*.json"):
        if fp.name.startswith("_"):
            continue
        try:
            records.append(json.loads(fp.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue

    sample = select_sample(records, args.sample, args.n)
    log(f"[compare] sample={args.sample} size={len(sample)} | GROBID-DL={args.grobid_url}")

    rows = []
    dl_abs_gained = dl_methods_gained = dl_heading_gained = 0
    for i, rec in enumerate(sample, 1):
        pdf = Path(remap_pdf(rec.get("source_pdf_path", ""), args.pdf_root))
        if not pdf.is_file():
            log(f"  [{i}] PDF missing: {pdf}")
            continue
        dl = dl_extract(pdf, args.grobid_url)

        crf_abs = (rec.get("abstract") or "").strip()
        crf_meth = (rec.get("methods") or "").strip()
        crf_found = rec.get("methods_heading_found")

        # Heuristic "gained" signals: DL produced content where CRF was empty/shorter.
        if len(dl["abstract"]) > len(crf_abs) + 50:
            dl_abs_gained += 1
        if len(dl["methods"]) > len(crf_meth) + 200:
            dl_methods_gained += 1
        if dl["heading_found"] and not crf_found:
            dl_heading_gained += 1

        rows.append({
            "doi": rec.get("doi", ""),
            "year": rec.get("year", ""),
            "crf_abstract_len": len(crf_abs),
            "dl_abstract_len": len(dl["abstract"]),
            "crf_methods_len": len(crf_meth),
            "dl_methods_len": len(dl["methods"]),
            "crf_heading_found": crf_found,
            "dl_heading_found": dl["heading_found"],
            "crf_abstract": crf_abs,
            "dl_abstract": dl["abstract"],
            "crf_methods": crf_meth[:2000],
            "dl_methods": dl["methods"][:2000],
        })
        if i % 10 == 0:
            log(f"  processed {i}/{len(sample)}")

    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["doi"])
        w.writeheader()
        w.writerows(rows)

    log(f"\n[compare] DONE -> {args.out}")
    log(f"  papers compared           : {len(rows)}")
    log(f"  DL longer abstract (>+50) : {dl_abs_gained}")
    log(f"  DL longer methods (>+200) : {dl_methods_gained}")
    log(f"  DL found heading CRF missed: {dl_heading_gained}")
    log("  (longer != better -- open the CSV and read; this is a signal, not a verdict)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
