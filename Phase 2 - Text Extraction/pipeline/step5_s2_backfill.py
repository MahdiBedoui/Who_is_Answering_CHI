#!/usr/bin/env python3
"""STEP 5 -- backfill suspect/missing abstracts from Semantic Scholar (unauthenticated).

Targets the DOIs in <batch>/_review.txt and <batch>/_still_missing.txt -- publisher
text from S2 beats any PDF extraction, so a hit here REPLACES the suspect JSON.

Unauthenticated S2 is rate-limited (~1 req/s, shared pool). On 429 the script
backs off and retries; if the pool stays hostile it gives up on that DOI for now --
just rerun later (papers already fixed are skipped). With a key: --s2-api-key.

    py step5_s2_backfill.py --batch-dir "..\\..\\results\\abstracts\\chi2025_research_articles"
"""
import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("s3", HERE / "step3_extract_from_pdf.py")
s3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s3)  # reuse quality()

UA = {"User-Agent": "WhosAnsweringCHI (mailto:bedouimehdi39@gmail.com)"}


def fetch_s2(doi: str, api_key: str | None) -> tuple[str, str]:
    """Returns (abstract, status): ok / empty / not_found / rate_limited."""
    headers = dict(UA)
    if api_key:
        headers["x-api-key"] = api_key
    for attempt in range(3):
        r = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                         params={"fields": "abstract"}, headers=headers, timeout=30)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))  # back off: 5s, 10s, then give up
            continue
        if r.status_code == 404:
            return "", "not_found"
        r.raise_for_status()
        abstract = (r.json().get("abstract") or "").strip()
        return (abstract, "ok") if abstract else ("", "empty")
    return "", "rate_limited"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch-dir", required=True)
    ap.add_argument("--s2-api-key", default=None)
    args = ap.parse_args()
    batch = Path(args.batch_dir).resolve()

    targets = []
    for name in ("_review.txt", "_still_missing.txt"):
        f = batch / name
        if f.exists():
            targets += [d.strip() for d in f.read_text(encoding="utf-8").splitlines() if d.strip()]
    targets = list(dict.fromkeys(targets))
    if not targets:
        sys.exit("Nothing to backfill: _review.txt and _still_missing.txt are empty.")
    print(f"Batch  : {batch.name} -- {len(targets)} papers to try on Semantic Scholar")

    fixed = empty = limited = 0
    remaining = []
    for i, doi in enumerate(targets, 1):
        key = doi.replace("/", "_").replace(".", "_")
        out = batch / f"{key}.json"
        # skip papers already fixed by S2 or docling
        if out.exists():
            rec = json.loads(out.read_text(encoding="utf-8"))
            if rec.get("source") in ("semanticscholar", "docling") and rec.get("quality") == "ok":
                continue
        else:
            rec = None
        try:
            abstract, status = fetch_s2(doi, args.s2_api_key)
        except Exception as exc:
            print(f"  ERROR {doi}: {exc}", flush=True)
            remaining.append(doi)
            continue
        time.sleep(1.1 if not args.s2_api_key else 0.15)
        if status == "ok":
            record = {
                "doi": doi,
                "year": rec.get("year") if rec else None,
                "ptype": rec.get("ptype") if rec else None,
                "section": "abstract",
                "source": "semanticscholar",
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "quality": "ok",
                "text": abstract,
            }
            out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            fixed += 1
        elif status == "rate_limited":
            limited += 1
            remaining.append(doi)
        else:
            empty += 1
            remaining.append(doi)  # S2 has nothing: stays for docling/manual
        if i % 25 == 0:
            print(f"  [{i}/{len(targets)}] fixed={fixed} no-abstract={empty} "
                  f"rate-limited={limited}", flush=True)

    (batch / "_review.txt").write_text("\n".join(remaining) + ("\n" if remaining else ""),
                                       encoding="utf-8")
    print(f"\nDone. S2-fixed: {fixed}  S2-has-nothing: {empty}  rate-limited: {limited}")
    if limited:
        print("Rate-limited papers stay pending -- just rerun this script later.")
    print(f"_review.txt now lists {len(remaining)} papers (for docling step 4 / manual).")


if __name__ == "__main__":
    main()
