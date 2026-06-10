#!/usr/bin/env python3
"""Stage 06 -- gold set: stratified sample, then evaluate parser accuracy against it.

Sample (~150, stratified year x ptype, oversampling risky records), verify by hand,
then eval. Gold CSVs live in the REPO (data/gold/<section>/) -- they are small and
canonical. Verification: fill `verdict` with one of
    correct      -- resolved text matches the PDF
    wrong        -- put the true abstract in `corrected_text`
    (blank)      -- not yet checked
Acceptance gate to promote a parser version: >=99% correct of checked rows.

    python 06_gold_eval.py sample --data-store ... [--n 150]
    python 06_gold_eval.py eval   --data-store ...
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

V2_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(V2_DIR))

from lib import config  # noqa: E402
from lib.normalize import comparison_form  # noqa: E402
from lib.records import iter_records  # noqa: E402
from lib.similarity import ratio  # noqa: E402

REPO_ROOT = V2_DIR.parent.parent
RISKY = ("llm_adjudicated", "manual_queue")
RISKY_FLAGS = ("pdf_divergent", "ligature_artifact", "no_end_punct", "too_short")


def gold_path(section: str) -> Path:
    return REPO_ROOT / "data" / "gold" / section / "gold_sample.csv"


def cmd_sample(args) -> None:
    ds = config.data_store(args.data_store)
    section_dir = config.sections_dir(ds, args.section)
    strata: dict = defaultdict(list)
    risky: list = []
    for rec in iter_records(section_dir, args.venue, args.years):
        res = rec.get("resolution") or {}
        if not res.get("status"):
            continue
        row = {"doi": rec["doi"], "year": rec["year"], "ptype": rec["ptype"],
               "status": res["status"], "source": res.get("source", ""),
               "flags": ";".join(res.get("flags", [])),
               "resolved_text": res.get("text", ""),
               "verdict": "", "corrected_text": "", "notes": ""}
        is_risky = (res["status"] in RISKY
                    or any(f in res.get("flags", []) for f in RISKY_FLAGS))
        (risky if is_risky else strata[(rec["year"], rec["ptype"])]).append(row)

    rng = random.Random(args.seed)
    n_risky = min(len(risky), args.n // 3)  # oversample: up to a third from risky pool
    sample = rng.sample(risky, n_risky)
    remaining = args.n - len(sample)
    keys = sorted(strata)
    per_stratum = max(1, remaining // max(1, len(keys)))
    for k in keys:
        pool = strata[k]
        sample += rng.sample(pool, min(per_stratum, len(pool)))
    sample = sample[:args.n] if len(sample) > args.n else sample

    out = gold_path(args.section)
    if out.exists() and not args.force:
        raise SystemExit(f"{out} exists -- it may contain manual work. Use --force to overwrite.")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sample[0].keys()))
        w.writeheader()
        w.writerows(sample)
    print(f"Gold sample: {len(sample)} rows ({n_risky} risky-oversampled) -> {out}")
    print("Verify each row against the PDF, fill `verdict` (correct/wrong), then run eval.")


def cmd_eval(args) -> None:
    path = gold_path(args.section)
    if not path.exists():
        raise SystemExit(f"No gold file at {path}. Run `sample` first.")
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    checked = [r for r in rows if r["verdict"].strip()]
    if not checked:
        raise SystemExit("No verdicts filled in yet.")
    correct = [r for r in checked if r["verdict"].strip().lower() == "correct"]
    wrong = [r for r in checked if r["verdict"].strip().lower() == "wrong"]

    print(f"Gold eval ({args.section}): {len(checked)}/{len(rows)} checked")
    acc = len(correct) / len(checked)
    print(f"  accuracy: {len(correct)}/{len(checked)} = {acc:.3%}   (acceptance gate: >=99%)")

    if wrong:
        print("\n  misses (char-similarity of resolved vs corrected):")
        per_year = defaultdict(lambda: [0, 0])
        for r in wrong:
            sim = ratio(comparison_form(r["resolved_text"]),
                        comparison_form(r["corrected_text"])) if r["corrected_text"] else 0.0
            print(f"   - {r['doi']} ({r['year']} {r['ptype']}, src={r['source']}) sim={sim:.2f} "
                  f"flags=[{r['flags']}] {r['notes'][:60]}")
        for r in checked:
            per_year[r["year"]][0] += r["verdict"].strip().lower() == "correct"
            per_year[r["year"]][1] += 1
        print("\n  per-year:", {y: f"{c}/{t}" for y, (c, t) in sorted(per_year.items())})

    print("\n" + ("PASS: parser version may be promoted."
                  if acc >= 0.99 else "FAIL: triage misses, fix, re-run stages 03-05, re-verify."))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("sample")
    config.add_common_args(ps)
    ps.add_argument("--section", default="abstracts")
    ps.add_argument("--n", type=int, default=150)
    ps.add_argument("--seed", type=int, default=26)
    ps.add_argument("--force", action="store_true")
    ps.set_defaults(func=cmd_sample)
    pe = sub.add_parser("eval")
    config.add_common_args(pe)
    pe.add_argument("--section", default="abstracts")
    pe.set_defaults(func=cmd_eval)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
