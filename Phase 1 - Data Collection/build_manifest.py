#!/usr/bin/env python3
"""Rebuild data/manifest/papers.csv and data/manifest/coverage_summary.csv.

For every DOI in any keep-list under data/keep_lists/, plus every PDF found
on disk under sigchi/, write one row to papers.csv with status:
  - downloaded : PDF found in sigchi/VERIFIED COUNT/<venue>/<year>/<type>/
  - excluded   : PDF found in sigchi/VERIFIED COUNT/<venue>/<year>/_excluded/
  - missing    : DOI in a keep-list but no PDF on disk
  - orphan     : PDF on disk but not in any keep-list

coverage_summary.csv aggregates totals per venue x year x content_type.

Usage:
    python scripts/build_manifest.py
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterator, Tuple

ROOT = Path(__file__).resolve().parent.parent
KEEP_DIR = ROOT / "data" / "keep_lists"
SIGCHI_DIR = ROOT / "sigchi"
MANIFEST_DIR = ROOT / "data" / "manifest"
MASTER_CSV = ROOT / "data" / "master" / "acm_dois_classified.csv"

# Map keep-list subfolder name -> canonical venue label (matches sigchi/ folder names)
VENUE_MAP: Dict[str, str] = {
    "autoui": "AutomotiveUI", "cc": "C&C", "chi": "CHI", "chiplay": "CHI PLAY",
    "ci": "CI", "compass": "COMPASS", "cscw": "CSCW", "cui": "CUI", "dis": "DIS",
    "educhi": "EduCHI", "eics": "EICS", "etra": "ETRA", "group": "GROUP",
    "hri": "HRI", "icmi": "ICMI", "idc": "IDC", "imx": "IMX", "iss": "ISS",
    "iui": "IUI", "mobilehci": "MobileHCI", "recsys": "RecSys", "scf": "SCF",
    "sui": "SUI", "tei": "TEI", "ubicomp": "UbiComp-IMWUT", "umap": "UMAP",
    "vrst": "VRST",
}

# Filename suffix -> content_type label
TYPE_MAP: Dict[str, str] = {
    "ra": "Research Article",
    "short": "Short Paper",
    "ea": "Extended Abstract",
    "companion_ea": "Companion Extended Abstract",
}

# Folder name -> content_type (for VERIFIED COUNT layout)
FOLDER_TYPE: Dict[str, str] = {
    "Research Article": "Research Article",
    "Short Paper": "Short Paper",
    "_excluded": "Excluded",
}


def stem_of(doi: str) -> str:
    """DOI -> filename stem ('10.1145/X.Y' -> '10_1145_X_Y')."""
    return doi.replace("/", "_").replace(".", "_")


def doi_of(stem: str) -> str:
    """Inverse of stem_of, best-effort. Returns '' if it can't be parsed."""
    parts = stem.split("_")
    if len(parts) == 3 and parts[0] == "10" and parts[1] == "1145":
        return f"{parts[0]}.{parts[1]}/{parts[2]}"
    if len(parts) >= 4 and parts[0] == "10" and parts[1] == "1145":
        return f"{parts[0]}.{parts[1]}/{parts[2]}.{parts[3]}"
    return ""


def parse_keep_list_name(fname: str) -> Tuple[str, str, str]:
    """'chi24_ra.txt' -> ('chi', '2024', 'ra'). Returns ('','','') on no match."""
    m = re.match(r"^([a-z&]+?)(\d{2})_(ra|short|ea|companion_ea)\.txt$", fname)
    if not m:
        return ("", "", "")
    venue_code, yy, ttype = m.group(1), m.group(2), m.group(3)
    return (venue_code, f"20{yy}", ttype)


def walk_keep_lists() -> Iterator[Tuple[str, str, str, str]]:
    """Yield (doi, venue, year, content_type) from every per-year keep-list."""
    for venue_folder in KEEP_DIR.iterdir():
        if not venue_folder.is_dir():
            continue
        for kl in venue_folder.glob("*.txt"):
            venue_code, year, ttype = parse_keep_list_name(kl.name)
            if not venue_code:
                continue  # skip multi-year aggregates (handled by walk_all_keep_dois)
            venue = VENUE_MAP.get(venue_code, venue_code.upper())
            content_type = TYPE_MAP.get(ttype, ttype)
            dois = set(re.findall(r"10\.1145/\d+(?:\.\d+)?",
                                   kl.read_text(encoding="utf-8", errors="ignore")))
            for d in dois:
                yield (d, venue, year, content_type)


def walk_all_keep_dois() -> set:
    """Every DOI in any keep-list (per-year or aggregate) OR the master CSV."""
    all_dois = set()
    # keep-lists
    for venue_folder in KEEP_DIR.iterdir():
        if not venue_folder.is_dir():
            continue
        for kl in venue_folder.glob("*.txt"):
            text = kl.read_text(encoding="utf-8", errors="ignore")
            all_dois.update(re.findall(r"10\.1145/\d+(?:\.\d+)?", text))
    # master CSV (the canonical 21k-DOI catalog)
    if MASTER_CSV.exists():
        with open(MASTER_CSV, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = (row.get("doi") or "").strip()
                if d:
                    all_dois.add(d)
    return all_dois


def walk_master_csv() -> Iterator[Tuple[str, str]]:
    """Yield (doi, venue) from the master DOI catalog, if it exists."""
    if not MASTER_CSV.exists():
        return
    with open(MASTER_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = (row.get("doi") or "").strip()
            v = (row.get("venue") or "").strip()
            if d:
                yield (d, v)


def walk_pdfs() -> Iterator[Tuple[str, str, str, str, str, bool]]:
    """Yield (doi, venue, year, content_type, filename, in_verified) per PDF.

    `in_verified` is True if the PDF lives under sigchi/VERIFIED COUNT/.
    That flag is treated as proof-of-corpus-membership even if the DOI
    isn't in any keep-list or the master CSV.
    """
    if not SIGCHI_DIR.exists():
        return
    for pdf in SIGCHI_DIR.rglob("*.pdf"):
        rel = pdf.relative_to(SIGCHI_DIR)
        parts = list(rel.parts)
        in_vc = parts[0] == "VERIFIED COUNT"
        if in_vc:
            parts = parts[1:]  # strip the "VERIFIED COUNT" prefix
        # Now parts looks like one of:
        #   [<venue>, <year>, <type>, <file>]     -- nested with type
        #   [<venue>, <year>, <file>]             -- nested without type
        #   [<venue>, <file>]                     -- venue only
        #   [<file>]                              -- loose
        venue = year = content_type = ""
        if len(parts) >= 4 and re.fullmatch(r"\d{4}", parts[1]):
            venue, year = parts[0], parts[1]
            content_type = FOLDER_TYPE.get(parts[2], parts[2])
        elif len(parts) >= 3 and re.fullmatch(r"\d{4}", parts[1]):
            venue, year = parts[0], parts[1]
        elif len(parts) >= 2:
            venue = parts[0]
        d = doi_of(pdf.stem)
        if not d:
            continue
        yield (d, venue, year, content_type, pdf.name, in_vc)


def main() -> None:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    # Index every PDF on disk by stem
    # stem -> (venue, year, ct, filename, in_verified_count)
    disk: Dict[str, Tuple[str, str, str, str, bool]] = {}
    for d, venue, year, ct, fname, in_vc in walk_pdfs():
        disk[stem_of(d)] = (venue, year, ct, fname, in_vc)

    # Collect every DOI mentioned anywhere in keep-lists (for orphan detection)
    all_keep_dois = walk_all_keep_dois()

    # Track DOIs we've already emitted a row for (avoid duplicates)
    rows = []
    seen: set = set()

    # Pass 1: per-year keep-lists give exact venue / year / content_type metadata
    for d, venue, year, ct in walk_keep_lists():
        if d in seen:
            continue
        seen.add(d)
        s = stem_of(d)
        if s in disk:
            disk_venue, disk_year, disk_ct, fname, _ = disk[s]
            status = "excluded" if disk_ct == "Excluded" else "downloaded"
            rows.append({
                "doi": d, "venue": disk_venue or venue,
                "year": disk_year or year,
                "content_type": disk_ct or ct,
                "filename": fname, "status": status,
            })
        else:
            rows.append({
                "doi": d, "venue": venue, "year": year,
                "content_type": ct, "filename": "", "status": "missing",
            })

    # Pass 2: PDFs on disk not yet emitted. A PDF is a corpus paper if it lives
    # under VERIFIED COUNT/ (folder placement is itself proof of curation) OR
    # its DOI appears in any keep-list / master CSV. Everything else is orphan.
    for s, (venue, year, ct, fname, in_vc) in disk.items():
        d = doi_of(s)
        if d in seen:
            continue
        seen.add(d)
        if in_vc or d in all_keep_dois:
            status = "excluded" if ct == "Excluded" else "downloaded"
            rows.append({
                "doi": d, "venue": venue, "year": year,
                "content_type": ct, "filename": fname, "status": status,
            })
        else:
            rows.append({
                "doi": d, "venue": venue, "year": year,
                "content_type": ct, "filename": fname, "status": "orphan",
            })

    # Pass 3: master-CSV DOIs not yet emitted and not on disk -> missing.
    # These are corpus DOIs we haven't downloaded and no per-year keep-list covered.
    for d, venue in walk_master_csv():
        if d in seen:
            continue
        seen.add(d)
        rows.append({
            "doi": d, "venue": venue, "year": "", "content_type": "",
            "filename": "", "status": "missing",
        })

    rows.sort(key=lambda r: (r["venue"], r["year"], r["content_type"], r["doi"]))

    papers_csv = MANIFEST_DIR / "papers.csv"
    with open(papers_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["doi","venue","year","content_type","filename","status"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {papers_csv}  ({len(rows)} rows)")

    # Coverage summary: counts per (venue, year, content_type)
    summary: Dict[Tuple[str, str, str], Dict[str, int]] = defaultdict(
        lambda: {"downloaded": 0, "missing": 0, "excluded": 0, "orphan": 0})
    for r in rows:
        key = (r["venue"], r["year"], r["content_type"])
        summary[key][r["status"]] += 1

    summary_csv = MANIFEST_DIR / "coverage_summary.csv"
    with open(summary_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["venue", "year", "content_type", "downloaded", "missing", "excluded", "orphan", "total"])
        for (venue, year, ct), counts in sorted(summary.items()):
            total = sum(counts.values())
            w.writerow([venue, year, ct, counts["downloaded"], counts["missing"],
                        counts["excluded"], counts["orphan"], total])
    print(f"Wrote {summary_csv}  ({len(summary)} venue-year-type groups)")

    # Tiny stdout summary
    totals: Dict[str, int] = defaultdict(int)
    for r in rows:
        totals[r["status"]] += 1
    print("\nStatus counts:")
    for k in ["downloaded", "missing", "excluded", "orphan"]:
        print(f"  {k:>10}: {totals[k]}")


if __name__ == "__main__":
    main()
