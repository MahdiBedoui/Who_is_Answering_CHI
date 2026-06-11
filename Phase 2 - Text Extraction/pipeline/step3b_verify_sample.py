#!/usr/bin/env python3
"""STEP 3b -- build a verification sheet for a random sample of PDF-extracted abstracts.

Picks N random clean extractions ("source": "pdf", "quality": "ok") from a batch,
renders page 1 of each PDF, and writes ONE html file: extracted text on the left,
the actual PDF page on the right. Scroll, compare, count errors.

Also writes verify_sample.csv -- mark each row correct/wrong as you go.
Rule of thumb: 60 samples with 0-1 errors => batch error rate < ~5% at 95% confidence.

    py step3b_verify_sample.py --batch-dir "..\\..\\results\\abstracts\\chi2025_research_articles" --n 60
"""
import argparse
import base64
import csv
import html
import io
import json
import os
import random
import sys
from pathlib import Path


def render_page1(pdf_path: Path, width: int = 700) -> str | None:
    """Return page 1 as a base64 PNG data URI, or None if rendering unavailable."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            im = pdf.pages[0].to_image(resolution=110)
            buf = io.BytesIO()
            im.original.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch-dir", required=True)
    ap.add_argument("--data-store", default=os.environ.get("WAC_DATA_STORE"))
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=26)
    args = ap.parse_args()
    if not args.data_store:
        sys.exit("Pass --data-store or set WAC_DATA_STORE.")
    ds = Path(args.data_store).resolve()
    batch = Path(args.batch_dir).resolve()

    # collect clean pdf-sourced records
    records = []
    for f in sorted(batch.glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if r.get("source") == "pdf" and r.get("quality") == "ok":
            records.append(r)
    if not records:
        sys.exit("No clean pdf-sourced records found in this batch.")
    rng = random.Random(args.seed)
    sample = rng.sample(records, min(args.n, len(records)))
    print(f"{len(records)} clean PDF extractions, sampling {len(sample)}")

    corpus = ds / "sigchi" / "VERIFIED COUNT" / "CHI"
    pdf_index = {p.stem: p for p in corpus.rglob("*.pdf")}

    blocks = []
    for i, r in enumerate(sample, 1):
        key = r["doi"].replace("/", "_").replace(".", "_")
        pdf = pdf_index.get(key)
        img = render_page1(pdf) if pdf else None
        img_html = (f'<img src="{img}" style="width:100%">' if img else
                    f'<p>(page render unavailable -- open the PDF: {html.escape(str(pdf))})</p>')
        blocks.append(f"""
<div style="display:flex;gap:16px;border-top:3px solid #444;padding:14px 0">
  <div style="flex:1;min-width:0">
    <h3 style="margin:0 0 6px">{i}. {html.escape(r['doi'])}</h3>
    <p style="white-space:pre-wrap;font-family:Georgia,serif;line-height:1.45">{html.escape(r['text'])}</p>
  </div>
  <div style="flex:1;min-width:0">{img_html}</div>
</div>""")
        if i % 10 == 0:
            print(f"  rendered {i}/{len(sample)}", flush=True)

    out_html = batch / "verify_sample.html"
    out_html.write_text(
        "<!doctype html><meta charset='utf-8'><title>Verify abstracts</title>"
        "<body style='max-width:1500px;margin:20px auto;font-family:system-ui'>"
        f"<h1>Verification sample -- {batch.name} ({len(sample)} of {len(records)})</h1>"
        "<p>Left: extracted abstract. Right: page 1 of the PDF. "
        "Check the START and END of each abstract especially -- boundary errors are the "
        "most common failure. Record verdicts in verify_sample.csv.</p>"
        + "".join(blocks) + "</body>", encoding="utf-8")

    out_csv = batch / "verify_sample.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["n", "doi", "verdict (correct/wrong)", "notes"])
        for i, r in enumerate(sample, 1):
            w.writerow([i, r["doi"], "", ""])

    print(f"\nReview sheet : {out_html}")
    print(f"Verdict file : {out_csv}")
    print("Open the HTML in your browser, compare, fill the CSV.")


if __name__ == "__main__":
    main()
