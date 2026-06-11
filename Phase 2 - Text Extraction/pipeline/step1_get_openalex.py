#!/usr/bin/env python3
"""STEP 1 -- get every CHI abstract that OpenAlex has.

Reads : the corpus folder   <data store>/sigchi/VERIFIED COUNT/CHI/<year>/<type>/*.pdf

Two output modes:
  --out-dir FOLDER   one .json file per paper, named by DOI (10_1145_xxx_yyy.json):
                     {doi, year, ptype, section, source, fetched_at, text}
                     Papers OpenAlex has no abstract for get NO file; they are listed
                     in _missing.txt in the same folder.
  --out FILE.csv     one CSV (doi, year, ptype, abstract). Default mode if neither given:
                     <data store>/data/openalex/abstracts_openalex.csv

Resumable in both modes: existing files/rows are skipped. Ctrl+C any time.

    py step1_get_openalex.py --years 2022 --types "Research Article" --out-dir "..\\..\\results\\abstracts\\chi2022_ra"
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
    """We already fetched OpenAlex once today; reuse that saved answer instead of
    calling the API again. Returns None if there is no saved answer."""
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


def iter_papers(corpus: Path, years, types):
    for year in sorted(years):
        ydir = corpus / str(year)
        if not ydir.is_dir():
            continue
        for tdir in sorted(p for p in ydir.iterdir() if p.is_dir()):
            ptype = "Research Article" if tdir.name.startswith("Research Article") else tdir.name
            if types and ptype not in types:
                continue
            for pdf in sorted(tdir.glob("*.pdf")):
                yield year, ptype, pdf.stem, doi_from_stem(pdf.stem)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-store", default=os.environ.get("WAC_DATA_STORE"),
                    help="Path to the 'Who's Answering CHI' data folder.")
    ap.add_argument("--years", type=int, nargs="*", default=[2022, 2023, 2024, 2025, 2026])
    ap.add_argument("--types", nargs="*", default=None,
                    help='Filter paper types, e.g. --types "Research Article" (default: all).')
    ap.add_argument("--out-dir", default=None,
                    help="Folder for one .txt per paper.")
    ap.add_argument("--out", default=None,
                    help="CSV path (used when --out-dir is not given).")
    ap.add_argument("--fresh", action="store_true",
                    help="Ignore saved answers; re-query OpenAlex live.")
    args = ap.parse_args()
    if not args.data_store:
        sys.exit("Pass --data-store or set WAC_DATA_STORE.")
    ds = Path(args.data_store).resolve()
    corpus = ds / "sigchi" / "VERIFIED COUNT" / "CHI"
    print(f"Corpus : {corpus}")

    n_fetched = n_reused = n_missing = 0

    def get_abstract(year, stem, doi):
        nonlocal n_fetched, n_reused
        abstract = None if args.fresh else reuse_earlier_fetch(ds, year, stem)
        if abstract is None:
            abstract = fetch_openalex_abstract(doi)
            time.sleep(0.15)  # stay polite: ~7 requests/sec
            n_fetched += 1
        else:
            n_reused += 1
        return abstract

    if args.out_dir:
        # ---- one .txt per paper ----
        from datetime import datetime, timezone
        out_dir = Path(args.out_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"Output : {out_dir}  (one .json per paper)\n")
        missing = []
        n = 0
        for year, ptype, stem, doi in iter_papers(corpus, args.years, args.types):
            jf = out_dir / f"{stem}.json"
            if jf.exists() and jf.stat().st_size > 0:
                continue  # resume: already saved
            try:
                abstract = get_abstract(year, stem, doi)
            except Exception as exc:
                print(f"  ERROR {doi}: {exc} (will retry on next run)", flush=True)
                continue
            if abstract:
                record = {
                    "doi": doi,
                    "year": year,
                    "ptype": ptype,
                    "section": "abstract",
                    "source": "openalex",
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "text": abstract,
                }
                jf.write_text(json.dumps(record, ensure_ascii=False, indent=1),
                              encoding="utf-8")
            else:
                n_missing += 1
                missing.append(doi)
            n += 1
            if n % 100 == 0:
                print(f"  {n} done ({n_missing} without abstract)", flush=True)
        (out_dir / "_missing.txt").write_text("\n".join(missing) + "\n" if missing else "",
                                              encoding="utf-8")
        print(f"\nDone. {n - n_missing} abstracts saved as .json, {n_missing} missing "
              f"(listed in _missing.txt)")
        print(f"(fetched from API: {n_fetched}, reused saved answers: {n_reused})")
    else:
        # ---- one CSV ----
        out = Path(args.out).resolve() if args.out else ds / "data" / "openalex" / "abstracts_openalex.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        if args.fresh and out.exists():
            out.rename(out.with_suffix(".csv.bak"))  # keep the old one, never delete
            print(f"--fresh: previous CSV moved to {out.name}.bak")
        done = set()
        if out.exists():
            with open(out, encoding="utf-8") as fh:
                done = {row["doi"] for row in csv.DictReader(fh)}
        print(f"Output : {out}\nAlready in CSV: {len(done)} papers\n")
        new_file = not out.exists()
        with open(out, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new_file:
                w.writerow(["doi", "year", "ptype", "abstract"])
            for year, ptype, stem, doi in iter_papers(corpus, args.years, args.types):
                if doi in done:
                    continue
                try:
                    abstract = get_abstract(year, stem, doi)
                except Exception as exc:
                    print(f"  ERROR {doi}: {exc} (will retry on next run)", flush=True)
                    continue
                if not abstract:
                    n_missing += 1
                w.writerow([doi, year, ptype, abstract])
                fh.flush()
                done.add(doi)
                if (n_fetched + n_reused) % 100 == 0:
                    print(f"  {n_fetched + n_reused} done ({n_missing} without abstract)", flush=True)
        print(f"\nDone. fetched from API: {n_fetched}, reused saved answers: {n_reused}")
        print(f"Total papers in CSV: {len(done)}")


if __name__ == "__main__":
    main()
