#!/usr/bin/env python3
"""STEP 6 -- build a full review book for a batch: EVERY paper, abstract next to
the PDF's first page.

Unlike step 3b (random sample, images embedded), this covers all papers and keeps
the images as files in <batch>/_pages/ so the HTML stays small and loads instantly
(images lazy-load as you scroll).

Resumable: already-rendered page images are reused, so a rerun only adds new ones.

    py step6_make_review_book.py --batch-dir "..\\..\\results\\abstracts\\chi2025_research_articles"
"""
import argparse
import html
import json
import os
import sys
import time
from pathlib import Path

BADGE = {"openalex": "#2f7d32", "semanticscholar": "#1565c0",
         "pdf": "#b26a00", "docling": "#6a1b9a"}


def render_page1(pdf_path: Path, out_png: Path) -> bool:
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            im = pdf.pages[0].to_image(resolution=90)
            im.original.save(out_png, format="PNG")
        return True
    except Exception:
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch-dir", required=True)
    ap.add_argument("--data-store", default=os.environ.get("WAC_DATA_STORE"))
    args = ap.parse_args()
    if not args.data_store:
        sys.exit("Pass --data-store or set WAC_DATA_STORE.")
    ds = Path(args.data_store).resolve()
    batch = Path(args.batch_dir).resolve()
    pages = batch / "_pages"
    pages.mkdir(exist_ok=True)

    records = []
    for f in sorted(batch.glob("*.json")):
        try:
            records.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    if not records:
        sys.exit("No abstracts in this batch folder yet.")
    print(f"Batch  : {batch.name} -- {len(records)} papers")

    corpus = ds / "sigchi" / "VERIFIED COUNT" / "CHI"
    pdf_index = {p.stem: p for p in corpus.rglob("*.pdf")}

    blocks = []
    rendered = reused = 0
    t0 = time.time()
    for i, r in enumerate(records, 1):
        key = r["doi"].replace("/", "_").replace(".", "_")
        png = pages / f"{key}.png"
        if png.exists() and png.stat().st_size > 0:
            reused += 1
        else:
            pdf = pdf_index.get(key)
            if pdf and render_page1(pdf, png):
                rendered += 1
        src = r.get("source", "?")
        color = BADGE.get(src, "#555")
        q = r.get("quality", "")
        img = (f'<img src="_pages/{key}.png" loading="lazy" style="width:100%">'
               if png.exists() else "<p>(no page render)</p>")
        blocks.append(f"""
<div style="display:flex;gap:16px;border-top:3px solid #444;padding:14px 0">
  <div style="flex:1;min-width:0">
    <h3 style="margin:0 0 6px">{i}. {html.escape(r['doi'])}
      <span style="background:{color};color:#fff;border-radius:4px;padding:2px 8px;
       font-size:13px;font-weight:normal">{html.escape(src)}{' / ' + q if q else ''}</span></h3>
    <p style="white-space:pre-wrap;font-family:Georgia,serif;line-height:1.45">{html.escape(r.get('text',''))}</p>
  </div>
  <div style="flex:1;min-width:0">{img}</div>
</div>""")
        if i % 100 == 0:
            print(f"  {i}/{len(records)} (rendered {rendered}, reused {reused}, "
                  f"{(time.time()-t0)/60:.1f} min)", flush=True)

    out = batch / "review_all.html"
    out.write_text(
        "<!doctype html><meta charset='utf-8'><title>Review all</title>"
        "<body style='max-width:1500px;margin:20px auto;font-family:system-ui'>"
        f"<h1>{batch.name} -- all {len(records)} papers</h1>"
        "<p>Left: extracted abstract (badge = where it came from). "
        "Right: page 1 of the PDF. Images load as you scroll.</p>"
        + "".join(blocks) + "</body>", encoding="utf-8")
    print(f"\nDone in {(time.time()-t0)/60:.1f} min. Open: {out}")
    print(f"(page images: {rendered} new, {reused} reused, in {pages})")


if __name__ == "__main__":
    main()
