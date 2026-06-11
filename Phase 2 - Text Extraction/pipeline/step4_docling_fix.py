#!/usr/bin/env python3
"""STEP 4 -- re-extract the suspect/missing abstracts with Docling (layout-aware).

Targets every DOI in <batch>/_review.txt and <batch>/_still_missing.txt.
Docling parses the page layout (it understands columns, footers, license blocks),
so the cross-column failures from step 3 come out clean. Only the first 2 pages
are converted, ~10-15s per paper.

Writes the same JSON format, "source": "docling". Existing JSONs for these DOIs
are OVERWRITTEN only when the Docling result passes the quality gate; otherwise
the step-3 version is kept and the DOI stays listed for manual review.

    pip install docling          (first time only; downloads models on first run)
    py step4_docling_fix.py --batch-dir "..\\..\\results\\abstracts\\chi2025_research_articles"
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("s3", HERE / "step3_extract_from_pdf.py")
s3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s3)  # reuse quality() and _clean()

MD_HEADING_RE = re.compile(r"(?ims)^#{1,4}\s*Abstract\s*$\n+(.*?)(?=^#{1,4}\s|\Z)")
MD_INLINE_RE = re.compile(
    r"(?is)\babstract\b[\s:]*\n+(.*?)(?:\n#{1,4}\s|\nCCS\s+Concepts|\nKEYWORDS|\Z)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch-dir", required=True)
    ap.add_argument("--data-store", default=os.environ.get("WAC_DATA_STORE"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if not args.data_store:
        sys.exit("Pass --data-store or set WAC_DATA_STORE.")
    ds = Path(args.data_store).resolve()
    batch = Path(args.batch_dir).resolve()

    targets = []
    for name in ("_review.txt", "_still_missing.txt"):
        f = batch / name
        if f.exists():
            targets += [d.strip() for d in f.read_text(encoding="utf-8").splitlines() if d.strip()]
    targets = list(dict.fromkeys(targets))  # dedupe, keep order
    if not targets:
        sys.exit("Nothing to fix: _review.txt and _still_missing.txt are empty.")
    print(f"Batch  : {batch.name} -- {len(targets)} papers for Docling")

    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        sys.exit("docling not installed: pip install docling")
    converter = DocumentConverter()

    corpus = ds / "sigchi" / "VERIFIED COUNT" / "CHI"
    pdf_index = {p.stem: p for p in corpus.rglob("*.pdf")}

    fixed = kept = failed = 0
    remaining = []
    n = 0
    for doi in targets:
        if args.limit and n >= args.limit:
            remaining.append(doi)
            continue
        key = doi.replace("/", "_").replace(".", "_")
        out = batch / f"{key}.json"
        # skip papers already fixed by an earlier step-4 run
        if out.exists():
            rec = json.loads(out.read_text(encoding="utf-8"))
            if rec.get("source") == "docling" and rec.get("quality") == "ok":
                continue
        n += 1
        pdf = pdf_index.get(key)
        if pdf is None:
            remaining.append(doi)
            continue
        t0 = time.time()
        try:
            result = converter.convert(str(pdf), max_num_pages=2)
            md = result.document.export_to_markdown()
        except Exception as exc:
            print(f"  ERROR {doi}: {exc}", flush=True)
            failed += 1
            remaining.append(doi)
            continue
        m = MD_HEADING_RE.search(md) or MD_INLINE_RE.search(md[:20000])
        text = s3._clean(m.group(1)) if m else ""
        verdict = s3.quality(text)
        if verdict == "ok":
            record = {
                "doi": doi,
                "year": int(pdf.parent.parent.name),
                "ptype": ("Research Article" if pdf.parent.name.startswith("Research Article")
                          else pdf.parent.name),
                "section": "abstract",
                "source": "docling",
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "quality": "ok",
                "text": text,
            }
            out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            fixed += 1
        else:
            kept += 1            # step-3 version (if any) stays; still needs eyes
            remaining.append(doi)
        if n % 10 == 0:
            print(f"  {n}/{len(targets)} fixed={fixed} still-suspect={kept} "
                  f"({time.time()-t0:.0f}s/paper)", flush=True)

    (batch / "_review.txt").write_text("\n".join(remaining) + ("\n" if remaining else ""),
                                       encoding="utf-8")
    print(f"\nDone. docling-fixed: {fixed}  still-suspect: {kept}  errors: {failed}")
    print(f"_review.txt now lists the {len(remaining)} papers that still need manual eyes.")


if __name__ == "__main__":
    main()
