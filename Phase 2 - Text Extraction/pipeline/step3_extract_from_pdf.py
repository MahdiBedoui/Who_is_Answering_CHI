#!/usr/bin/env python3
"""STEP 3 -- extract abstracts from the local PDFs for the papers OpenAlex is missing.

Reads : <batch folder>/_missing.txt        (DOIs, from step 1)
        the PDFs in the data store corpus
Writes: <batch folder>/10_1145_xxx.json    same format as step 1, "source": "pdf"
        <batch folder>/_review.txt         extracted but looks suspect -- check by hand
        <batch folder>/_still_missing.txt  nothing extractable -- needs the heavy tool (step 4)

How it works: pdfplumber reads the first 2 pages (two-column aware, plain fallback),
the text between the "ABSTRACT" heading and "CCS CONCEPTS"/"KEYWORDS" is sliced out,
broken ligatures are repaired ("afect" -> "affect"), and quality checks decide
ok / review / still-missing.

    py step3_extract_from_pdf.py --batch-dir "..\\..\\results\\abstracts\\chi2025_research_articles"
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# ---------- extraction ----------

ABSTRACT_RE = re.compile(
    r"(?is)\bAbstract\b[\s:]*\n?(.*?)(?:\n\s*(?:CCS\s+Concepts|Keywords|KEYWORDS|"
    r"ACM\s+Reference\s+Format|1\s+Introduction|1\.\s+Introduction|\bIntroduction\b))")

# Ligature repair: PDF fonts sometimes collapse ff/fi/fl/ffi to a bare "f".
_VOCAB = """
affect affects affected affecting affective effect effects effective effectively effectiveness
efficacy efficient efficiently efficiency sufficient sufficiently insufficient office offline official
difficult difficulty difficulties different differently difference differences differ differs
significant significantly significance specific specifically specification specified specify
find finds finding findings first finally final define defines defined defining definition definitions
identify identifies identified identifying identification influence influences influenced influencing
workflow workflows conflict conflicts confirm confirms confirmed configuration configurations
benefit benefits beneficial field fields figure figures file files filter filters fit fits
reflect reflects reflected reflection refine refined refinement classification classifications
classified artificial scientific justification verification notification notifications profile profiles
confidence confident fifty fifteen traffic affordance affordances offer offers offered offering
""".split()
_REPAIRS = {}
for _w in _VOCAB:
    _c = _w
    for cl in ("ffi", "ffl", "ff", "fi", "fl"):
        _c = _c.replace(cl, "f")
    if _c != _w:
        _REPAIRS[_c] = _w
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z-]*")
_SUSPECT_RE = re.compile(
    r"\b\w*(?:afect|efect|signifc|specifc|difcult|diferen|sufcien|efcien|confict|fnding)\w*\b", re.I)


def repair_ligatures(text: str) -> str:
    def fix(m):
        tok = m.group(0)
        rep = _REPAIRS.get(tok.lower())
        if rep is None:
            return tok
        return rep[0].upper() + rep[1:] if tok[0].isupper() else rep
    return _TOKEN_RE.sub(fix, text)


_BLEED_RE = re.compile(
    r"(?i)CCS Concepts|ACM Reference|this work is licensed|creative commons|"
    r"ACM ISBN|copyright held by|permission to make digital|doi\.org/|"
    r"[\w.+-]+@[\w-]+\.(?:edu|com|org|ac\.\w+)")


def quality(text: str) -> str:
    """'ok', 'review' (extracted but suspect), or 'missing' (unusable)."""
    if not text or len(text) < 200:
        return "missing"
    issues = 0
    if len(text) < 400 or len(text) > 3000:
        issues += 1
    if text[-1] not in '.!?"”':
        issues += 1
    if _SUSPECT_RE.search(text):
        issues += 1
    if _BLEED_RE.search(text):
        issues += 1
    return "ok" if issues == 0 else "review"


def _clean(raw: str) -> str:
    t = unicodedata.normalize("NFKC", raw)
    t = re.sub(r"-\n(\w)", r"\1", t)      # join hyphenated line breaks
    t = re.sub(r"\s*\n\s*", " ", t)       # unwrap lines
    t = re.sub(r"[ \t]+", " ", t).strip()
    return repair_ligatures(t)


def extract_abstract(pdf_path: Path) -> str:
    """Try two-column reading first (ACM layout), plain reading as fallback.
    Returns the best candidate by quality()."""
    import pdfplumber
    twocol, plain = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:2]:
            mid = page.width / 2
            left = page.crop((0, 0, mid, page.height)).extract_text() or ""
            right = page.crop((mid, 0, page.width, page.height)).extract_text() or ""
            twocol.append(left + "\n" + right)
            plain.append(page.extract_text() or "")
    candidates = []
    for text in ("\n".join(twocol), "\n".join(plain)):
        m = ABSTRACT_RE.search(text)
        if m:
            candidates.append(_clean(m.group(1)))
    if not candidates:
        return ""
    for c in candidates:
        if quality(c) == "ok":
            return c
    candidates = [c for c in candidates if quality(c) == "review"] or candidates
    return max(candidates, key=len)


# ---------- main ----------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch-dir", required=True,
                    help="Batch folder from step 1 (contains _missing.txt).")
    ap.add_argument("--data-store", default=os.environ.get("WAC_DATA_STORE"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if not args.data_store:
        sys.exit("Pass --data-store or set WAC_DATA_STORE.")
    ds = Path(args.data_store).resolve()
    batch = Path(args.batch_dir).resolve()
    missing_file = batch / "_missing.txt"
    if not missing_file.exists():
        sys.exit(f"{missing_file} not found -- run step 1 with --out-dir first.")
    dois = [d.strip() for d in missing_file.read_text(encoding="utf-8").splitlines() if d.strip()]
    print(f"Batch  : {batch.name} -- {len(dois)} missing abstracts to try")

    corpus = ds / "sigchi" / "VERIFIED COUNT" / "CHI"
    pdf_index = {p.stem: p for p in corpus.rglob("*.pdf")}

    counts = {"ok": 0, "review": 0, "missing": 0, "no_pdf": 0, "skipped": 0}
    review, still_missing = [], []
    n = 0
    for doi in dois:
        key = doi.replace("/", "_").replace(".", "_")
        out = batch / f"{key}.json"
        if out.exists():
            counts["skipped"] += 1
            continue
        if args.limit and n >= args.limit:
            break
        n += 1
        pdf = pdf_index.get(key)
        if pdf is None:
            counts["no_pdf"] += 1
            still_missing.append(doi)
            continue
        try:
            text = extract_abstract(pdf)
        except Exception as exc:
            print(f"  ERROR {doi}: {exc}", flush=True)
            text = ""
        verdict = quality(text)
        if verdict == "missing":
            counts["missing"] += 1
            still_missing.append(doi)
            continue
        ptype_dir = pdf.parent.name
        record = {
            "doi": doi,
            "year": int(pdf.parent.parent.name),
            "ptype": "Research Article" if ptype_dir.startswith("Research Article") else ptype_dir,
            "section": "abstract",
            "source": "pdf",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "quality": verdict,
            "text": text,
        }
        out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        counts[verdict] += 1
        if verdict == "review":
            review.append(doi)
        if n % 50 == 0:
            print(f"  {n}/{len(dois)} (ok={counts['ok']} review={counts['review']} "
                  f"missing={counts['missing']})", flush=True)

    (batch / "_review.txt").write_text("\n".join(review) + ("\n" if review else ""), encoding="utf-8")
    (batch / "_still_missing.txt").write_text("\n".join(still_missing) + ("\n" if still_missing else ""),
                                              encoding="utf-8")
    print(f"\nDone. clean: {counts['ok']}  needs-review: {counts['review']}  "
          f"unextractable: {counts['missing']}  pdf-not-found: {counts['no_pdf']}  "
          f"already-done: {counts['skipped']}")
    print("Suspect extractions -> _review.txt | unextractable -> _still_missing.txt (step 4: docling)")


if __name__ == "__main__":
    main()
