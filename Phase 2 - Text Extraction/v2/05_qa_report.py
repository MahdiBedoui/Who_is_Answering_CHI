#!/usr/bin/env python3
"""Stage 05 -- QA report + flat master CSV over the resolved section records.

Prints per-year coverage, status/source/confidence/flag breakdowns, and writes
<data store>/data/reports/abstracts_master.csv (one row per paper).

    python 05_qa_report.py --data-store "../Who's Answering CHI"
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

V2_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(V2_DIR))

from lib import config  # noqa: E402
from lib.records import iter_records  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    config.add_common_args(p)
    p.add_argument("--section", default="abstracts")
    args = p.parse_args()

    ds = config.data_store(args.data_store)
    section_dir = config.sections_dir(ds, args.section)
    out_csv = config.reports_dir(ds) / f"{args.section}_master.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    by_year_status: dict = defaultdict(Counter)
    by_source = Counter()
    by_conf = Counter()
    flags = Counter()
    cand_ok = Counter()
    agreement_hist = Counter()
    rows = []
    n = 0

    for rec in iter_records(section_dir, args.venue, args.years):
        n += 1
        res = rec.get("resolution") or {}
        status = res.get("status") or "unresolved"
        by_year_status[rec["year"]][status] += 1
        if res.get("source"):
            by_source[res["source"]] += 1
        if res.get("confidence"):
            by_conf[res["confidence"]] += 1
        for f in res.get("flags", []):
            flags[f] += 1
        for s, c in rec.get("candidates", {}).items():
            if c.get("ok"):
                cand_ok[s] += 1
        if res.get("scores"):
            best = max(res["scores"].values())
            agreement_hist[f"{int(best * 20) * 5 / 100:.2f}"] += 1
        rows.append({
            "doi": rec["doi"], "venue": rec["venue"], "year": rec["year"],
            "ptype": rec["ptype"], "status": status,
            "source": res.get("source", ""), "confidence": res.get("confidence", ""),
            "flags": ";".join(res.get("flags", [])),
            "n_candidates": sum(1 for c in rec.get("candidates", {}).values() if c.get("ok")),
            "len": len(res.get("text") or ""),
            "abstract": res.get("text", ""),
        })

    if not n:
        raise SystemExit("No records found. Run stages 00/03/04 first.")

    print(f"=== {args.section}: {n} records ===\n")
    print("Per-year status:")
    for y in sorted(by_year_status):
        c = by_year_status[y]
        tot = sum(c.values())
        resolved = c.get("resolved", 0) + c.get("llm_adjudicated", 0)
        print(f"  {y}: {tot:5d} papers | resolved {resolved:5d} ({100 * resolved / tot:5.1f}%) "
              f"| adjudication pending {c.get('needs_adjudication', 0):4d} "
              f"| manual {c.get('manual_queue', 0):3d} | unresolved {c.get('unresolved', 0):4d}")
    print("\nCandidate availability (ok per source):")
    for s in config.ALL_SOURCES:
        print(f"  {s:16s} {cand_ok.get(s, 0)}")
    print("\nResolved-from source:", dict(by_source.most_common()))
    print("Confidence:", dict(by_conf))
    print("Flags:", dict(flags.most_common()) or "none")
    if agreement_hist:
        print("Best-pair agreement histogram:",
              dict(sorted(agreement_hist.items(), reverse=True)))

    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nMaster CSV: {out_csv} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
