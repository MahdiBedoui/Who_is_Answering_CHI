#!/usr/bin/env python3
"""STEP 1 -- get every CHI abstract that OpenAlex has.

Reads : the corpus folder   <data store>/sigchi/VERIFIED COUNT/CHI/<year>/<type>/*.pdf
Writes: ONE file            <data store>/data/openalex/abstracts_openalex.csv
        columns: doi, year, ptype, abstract   (abstract empty = OpenAlex has none)

Resumable: DOIs already in the CSV are skipped. Ctrl+C any time, rerun to continue.

    py step1_get_openalex.py --data-store "C:\\Users\\H¨P\\Desktop\\Who's Answering CHI"
"""
import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

MAILTO = "bedouimehdi39@gmail.com"
HEADERS = {"User-Agent": f"WhosAnsweringCHI (mailto:{MAILTO})"}


def doi_from_stem(stem: str) -> str:
    # 10_1145_3613905_3636282  ->  10.1145/3613905.3636282
    parts = stem.split("_")
    return f"{parts[0]}.{parts[1]}/" + ".".join(parts[2:])


def fetch_openalex_abstract(doi: str) -> str:
    """Return the abstract text, or '' if OpenAlex has none."""
    r = requests.get(f"https://api.openalex.org/works/https://doi.org/{doi}",
                     params={"select": "abstract_inverted_index", "mailto": MAILTO},
                     headers=HEADERS, timeout=30)
    if r.status_code == 404:
        return ""
    r.raise_for_status()
    inv = r.json().get("abstract_inverted_index")
    if not inv:
        return ""
    positions = sorted((i, w) for w, idxs in inv.items() for i in idxs)
    return " ".join(w for _, w in positions).strip()


def reuse_earlier_fetch(ds: Path, year: int, stem: str) -> str | None:
    """We already fetched OpenAlex once (the v2 run). Reuse that answer instead of
    calling the API again. Returns None if we have no earlier answer.
    Delete this function (and its call) to force pure API fetching."""
    rec_file = ds / "data" / "sections" / "abstracts" / "CHI" / str(year) / f"{stem}.json"
    if not rec_file.exists():
        return None
    try:
        rec = json.loads(rec_file.read_text(encoding="utf-8"))
        oa = rec.get("candidates", {}).get("openalex")
        if oa and oa.get("status") in ("ok", "empty", "not_found"):
            return oa.get("text", "") or ""
    except (json.JSONDecodeError, OSError):
        pass
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-store", default=os.environ.get("WAC_DATA_STORE"),
                    help="Path to the 'Who's Answering CHI' data folder.")
    ap.add_argument("--years", type=int, nargs="*", default=[2022, 2023, 2024, 2025, 2026])
    args = ap.parse_args()
    if not args.data_store:
        sys.exit("Pass --data-store or set WAC_DATA_STORE.")
    ds = Path(args.data_store).resolve()
    corpus = ds / "sigchi" / "VERIFIED COUNT" / "CHI"
    out = ds / "data" / "openalex" / "abstracts_openalex.csv"
    out.parent.mkdir(parents=True, exist_ok=True)

    # already-done DOIs (resume)
    done = set()
    if out.exists():
        with open(out, encoding="utf-8") as fh:
            done = {row["doi"] for row in csv.DictReader(fh)}
    print(f"Corpus : {corpus}")
    print(f"Output : {out}")
    print(f"Already in CSV: {len(done)} papers\n")

    new_file = not out.exists()
    n_fetched = n_reused = n_missing = 0
    with open(out, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["doi", "year", "ptype", "abstract"])
        for year in sorted(args.years):
            ydir = corpus / str(year)
            if not ydir.is_dir():
                continue
            for tdir in sorted(p for p in ydir.iterdir() if p.is_dir()):
                ptype = "Research Article" if tdir.name.startswith("Research Article") else tdir.name
                for pdf in sorted(tdir.glob("*.pdf")):
                    doi = doi_from_stem(pdf.stem)
                    if doi in done:
                        continue
                    abstract = reuse_earlier_fetch(ds, year, pdf.stem)
                    if abstract is None:
                        try:
                            abstract = fetch_openalex_abstract(doi)
                        except Exception as exc:
                            print(f"  ERROR {doi}: {exc} (will retry on next run)", flush=True)
                            continue
                        time.sleep(0.15)  # stay polite: ~7 requests/sec
                        n_fetched += 1
                    else:
                        n_reused += 1
                    if not abstract:
                        n_missing += 1
                    w.writerow([doi, year, ptype, abstract])
                    fh.flush()
                    done.add(doi)
                    total = n_fetched + n_reused
                    if total % 100 == 0:
                        print(f"  {total} done ({n_missing} without abstract so far)", flush=True)

    print(f"\nDone. fetched from API: {n_fetched}, reused earlier answers: {n_reused}")
    print(f"Total papers in CSV: {len(done)}")
    print("Next: py step2_whats_missing.py")


if __name__ == "__main__":
    main()
