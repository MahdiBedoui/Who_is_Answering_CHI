#!/usr/bin/env python3
"""STEP 2 -- analyze what OpenAlex is missing.

Reads : <data store>/data/openalex/abstracts_openalex.csv   (from step 1)
Writes: <data store>/data/openalex/missing_openalex.csv     (the gap list)
Prints: coverage per year and paper type.

    py step2_whats_missing.py --data-store "C:\\Users\\H¨P\\Desktop\\Who's Answering CHI"
"""
import argparse
import csv
import os
import sys
from collections import Counter
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-store", default=os.environ.get("WAC_DATA_STORE"))
    args = ap.parse_args()
    if not args.data_store:
        sys.exit("Pass --data-store or set WAC_DATA_STORE.")
    ds = Path(args.data_store).resolve()
    src = ds / "data" / "openalex" / "abstracts_openalex.csv"
    out = ds / "data" / "openalex" / "missing_openalex.csv"
    if not src.exists():
        sys.exit(f"{src} not found -- run step 1 first.")

    with open(src, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    missing = [r for r in rows if not r["abstract"].strip()]

    total = Counter((r["year"], r["ptype"]) for r in rows)
    gap = Counter((r["year"], r["ptype"]) for r in missing)

    print(f"Papers checked : {len(rows)}")
    print(f"With abstract  : {len(rows) - len(missing)}  ({100 * (len(rows) - len(missing)) / len(rows):.1f}%)")
    print(f"Missing        : {len(missing)}\n")
    print(f"{'year':6s} {'type':18s} {'missing':>8s} {'total':>7s} {'rate':>6s}")
    for key in sorted(total):
        y, t = key
        print(f"{y:6s} {t:18s} {gap[key]:8d} {total[key]:7d} {100 * gap[key] / total[key]:5.0f}%")

    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["doi", "year", "ptype"])
        for r in missing:
            w.writerow([r["doi"], r["year"], r["ptype"]])
    print(f"\nGap list written to: {out}")
    print("Next: decide how to handle the missing (step 3).")


if __name__ == "__main__":
    main()
