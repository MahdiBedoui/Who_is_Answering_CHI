"""Module 0: the corpus inventory.

Contract
  in:  the PDFs on disk under CHI_CORPUS/<year>/Research Article*/*.pdf
  out: output/inventory.jsonl, one row per PDF:
         pid, doi, year, path (relative to the corpus), bytes, sha256,
         pages, readable, error
       output/inventory_summary.json: counts per year against EXPECTED

What it establishes
  - the corpus on disk matches the population the paper claims (637/879/1057/1249/1702)
  - which files PyMuPDF cannot open (they are kept in the manifest, flagged, never dropped)
  - a hash for every file, so the corpus can be verified later and the
    manifest can be published in place of the PDFs

It reads only. Run from the repo root:
    py "Phase 1 - Data Preparation/inventory.py"
"""
import hashlib
import json
import re
import pathlib
import sys
import time

import fitz

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # the repo root, where config.py is
import config  # noqa: E402

PID = re.compile(r"^10_1145_(\d+)_(\d+)$")


def pid_to_doi(pid: str) -> str:
    """'10_1145_3491102_3501822' -> '10.1145/3491102.3501822'"""
    m = PID.match(pid)
    if not m:
        raise ValueError(f"not an ACM pid: {pid!r}")
    return f"10.1145/{m.group(1)}.{m.group(2)}"


def sha256_of(path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def probe(path) -> tuple[int | None, bool, str]:
    """(page count, readable, error). Readable means PyMuPDF opens the file
    and at least one of the first three pages yields text."""
    try:
        doc = fitz.open(str(path))
    except Exception as e:  # noqa: BLE001 - any failure to open is the finding
        return None, False, type(e).__name__ + ": " + str(e)[:120]
    try:
        n = len(doc)
        has_text = any(doc[i].get_text().strip() for i in range(min(3, n)))
        return n, has_text, "" if has_text else "no extractable text in first pages"
    except Exception as e:  # noqa: BLE001
        return None, False, type(e).__name__ + ": " + str(e)[:120]
    finally:
        doc.close()


def inventory_row(path, year: str) -> dict:
    pid = path.stem
    pages, readable, error = probe(path)
    return {
        "pid": pid,
        "doi": pid_to_doi(pid),
        "year": year,
        "path": path.relative_to(config.CORPUS).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_of(path),
        "pages": pages,
        "readable": readable,
        "error": error,
    }


def build() -> list[dict]:
    rows = []
    for year in config.YEARS:
        folder = config.corpus_year_dir(year)
        pdfs = sorted(folder.glob("*.pdf"))
        t0 = time.time()
        for i, p in enumerate(pdfs, 1):
            rows.append(inventory_row(p, year))
            if i % 200 == 0 or i == len(pdfs):
                print(f"  {year}: {i}/{len(pdfs)}  ({time.time() - t0:.0f}s)", flush=True)
    return rows


def summarize(rows: list[dict]) -> dict:
    per_year = {}
    for year in config.YEARS:
        ys = [r for r in rows if r["year"] == year]
        per_year[year] = {
            "on_disk": len(ys),
            "expected": config.EXPECTED[year],
            "readable": sum(r["readable"] for r in ys),
            "unreadable": [r["pid"] for r in ys if not r["readable"]],
        }
    dupes = {}
    for r in rows:
        dupes.setdefault(r["sha256"], []).append(r["pid"])
    return {
        "total_on_disk": len(rows),
        "total_expected": sum(config.EXPECTED.values()),
        "total_readable": sum(r["readable"] for r in rows),
        "per_year": per_year,
        "duplicate_files": {h: p for h, p in dupes.items() if len(p) > 1},
    }


def main() -> None:
    config.require_corpus()
    config.OUTPUT.mkdir(exist_ok=True)
    print(f"corpus: {config.CORPUS}")
    rows = build()
    summary = summarize(rows)

    with open(config.OUTPUT / "inventory.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with open(config.OUTPUT / "inventory_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    print()
    print(f"{'year':<6}{'on disk':>9}{'expected':>10}{'readable':>10}")
    ok = True
    for year, s in summary["per_year"].items():
        flag = "" if s["on_disk"] == s["expected"] else "   <-- mismatch"
        ok &= s["on_disk"] == s["expected"]
        print(f"{year:<6}{s['on_disk']:>9}{s['expected']:>10}{s['readable']:>10}{flag}")
    print(f"{'all':<6}{summary['total_on_disk']:>9}{summary['total_expected']:>10}"
          f"{summary['total_readable']:>10}")
    unread = [p for s in summary["per_year"].values() for p in s["unreadable"]]
    print(f"\nunreadable: {len(unread)}")
    for p in unread:
        print("  ", p)
    if summary["duplicate_files"]:
        print(f"\nduplicate files (same bytes under two names): {len(summary['duplicate_files'])}")
        for h, pids in summary["duplicate_files"].items():
            print("  ", pids)
    print(f"\n-> {config.OUTPUT / 'inventory.jsonl'}")
    print(f"-> {config.OUTPUT / 'inventory_summary.json'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
