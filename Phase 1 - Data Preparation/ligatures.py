"""Module 1: ligature repair.

Contract
  in:  one PDF on disk (read only)
  out: open_repaired(path) -> (document, report)
         document  the PDF opened in memory with its ligature rows corrected;
                   the file on disk is never written
         report    what was found and what was changed (see `repair`)
       Run as a script, it does this for every PDF in the corpus and writes
         output/ligatures.jsonl          one row per PDF
         output/ligatures_summary.json   totals per year

The defect
  A PDF stores text as glyph codes. Each font carries a ToUnicode table that
  turns codes back into characters when text is copied or extracted. In many
  ACM papers the rows for ligature glyphs (fi, ff, fl, ffi, ffl) say "f", so
  "Prolific", for example, is extracted as "Prolifc". Pages still look right, because
  drawing a page never reads this table.

The repair
  The same font also names every glyph, in its /Encoding /Differences array,
  and a ligature glyph is named after its letters: f_i, f_f_i. The name is
  the ground truth. For each font we read the names, find the ToUnicode rows
  that disagree with them, and rewrite those rows. A table that already
  agrees with the names is left byte for byte unchanged. A ligature glyph
  whose name cannot be read is reported, never patched from a word list.

Run from the repo root:
    py "Phase 1 - Data Preparation/ligatures.py" [--year 2023]
"""
import argparse
import collections
import json
import re
import pathlib
import sys
import time
import unicodedata

import pymupdf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # the repo root, where config.py is
import config  # noqa: E402

# ---------------------------------------------------------------- glyph names

PLAIN = {"ff": "ff", "fi": "fi", "fl": "fl", "ffi": "ffi", "ffl": "ffl"}
UNI_NAME = re.compile(r"uni([0-9A-Fa-f]{4})")


def glyph_letters(name: str) -> str | None:
    """The letters a ligature glyph stands for, read from its name.
    None when the name is not a ligature name.

        'f_i' -> 'fi'    'f_f_i' -> 'ffi'    'T_h' -> 'Th'
        'ffi' -> 'ffi'   'uniFB01' -> 'fi'   'f_f.short' -> 'ff'
        'a'   -> None    'space' -> None

    This is the Adobe glyph naming convention: the parts of a ligature are
    joined by "_", and anything after a "." is a variant suffix.
    """
    stem = name.split(".", 1)[0]
    if stem in PLAIN:
        return PLAIN[stem]
    m = UNI_NAME.fullmatch(stem)
    if m:
        cp = int(m.group(1), 16)
        # U+FB00..FB04 are the single-character forms of ff, fi, fl, ffi, ffl
        return unicodedata.normalize("NFKC", chr(cp)) if 0xFB00 <= cp <= 0xFB04 else None
    parts = stem.split("_")
    if len(parts) < 2:
        return None
    letters = []
    for part in parts:
        if len(part) == 1 and part.isascii() and part.isalpha():
            letters.append(part)
        elif part in PLAIN:
            letters.append(PLAIN[part])
        else:
            return None
    return "".join(letters)


def looks_like_ligature(name: str) -> bool:
    """Names we would expect to translate. Used only to report the ones
    glyph_letters could not read, so nothing is skipped silently."""
    stem = name.split(".", 1)[0]
    return "_" in stem or stem in PLAIN or bool(UNI_NAME.fullmatch(stem) and stem.upper().startswith("UNIFB0"))


def parse_differences(encoding: str) -> dict[int, str]:
    """A font's /Differences array as {glyph code: glyph name}.

    The array mixes numbers and names: a number sets the current code, and
    each name after it takes the next code in turn.
        [27 /f_i /f_f_i 39 /quoteright] -> {27: 'f_i', 28: 'f_f_i', 39: 'quoteright'}
    """
    m = re.search(r"/Differences\s*\[(.*?)\]", encoding, re.S)
    if not m:
        return {}
    names, code = {}, None
    for number, name in re.findall(r"(\d+)|/([^\s/\[\]]+)", m.group(1)):
        if number:
            code = int(number)
        elif code is not None:
            names[code] = name
            code += 1
    return names


# ------------------------------------------------------------ ToUnicode tables
#
# A ToUnicode table lists its rows in two kinds of block:
#     beginbfchar   <1b> <0066>            one code -> one string
#     beginbfrange  <1b> <1e> <0066>       codes 1b..1e -> "f", "g", "h", "i"
#                   <1b> <1c> [<0066> <0067>]   the same, spelled out
# Strings are UTF-16BE in hex: <00660069> is "fi".

BFCHAR = re.compile(r"(beginbfchar)(.*?)(endbfchar)", re.S)
BFRANGE = re.compile(r"(beginbfrange)(.*?)(endbfrange)", re.S)
CHAR_ROW = re.compile(r"<([0-9A-Fa-f]+)>(\s*)<([0-9A-Fa-f]*)>")
RANGE_ROW = re.compile(r"<([0-9A-Fa-f]+)>(\s*)<([0-9A-Fa-f]+)>(\s*)(<[0-9A-Fa-f]*>|\[[^\]]*\])")
MAX_RANGE = 256   # ligature glyphs live in one-byte fonts; longer ranges are not ours


def _decode(hex_string: str) -> str:
    if len(hex_string) % 4:
        hex_string = hex_string.zfill(len(hex_string) + (-len(hex_string)) % 4)
    return bytes.fromhex(hex_string).decode("utf-16-be", errors="replace")


def _encode(text: str) -> str:
    return text.encode("utf-16-be").hex()


def _range_targets(lo: int, hi: int, target: str) -> list[str]:
    """The string each code of a bfrange row maps to, in code order."""
    if target.startswith("["):
        return [_decode(h) for h in re.findall(r"<([0-9A-Fa-f]*)>", target)]
    first = _decode(target[1:-1])
    if not first:
        return [""] * (hi - lo + 1)
    # a range counts upward from its first string by its last character
    return [first[:-1] + chr(min(ord(first[-1]) + i, 0xFFFF)) for i in range(hi - lo + 1)]


def read_cmap(cmap: str, codes) -> dict[int, str]:
    """What the table says for each of `codes`. A code with no row is absent
    from the result. A later row wins over an earlier one."""
    wanted, found = set(codes), {}
    for block in re.finditer(r"begin(bfchar|bfrange)(.*?)end\1", cmap, re.S):
        if block.group(1) == "bfchar":
            for src, _, dst in CHAR_ROW.findall(block.group(2)):
                if int(src, 16) in wanted:
                    found[int(src, 16)] = _decode(dst)
        else:
            for lo_h, _, hi_h, _, target in RANGE_ROW.findall(block.group(2)):
                lo, hi = int(lo_h, 16), int(hi_h, 16)
                if hi - lo >= MAX_RANGE:
                    continue
                hits = [c for c in wanted if lo <= c <= hi]
                if hits:
                    targets = _range_targets(lo, hi, target)
                    for c in hits:
                        if c - lo < len(targets):
                            found[c] = targets[c - lo]
    return found


def fix_cmap(cmap: str, truth: dict[int, str]) -> tuple[str, int]:
    """Rewrite every row that disagrees with `truth` ({code: letters}).
    Returns (new table, number of codes corrected). Rows that already agree,
    and every row for a code not in `truth`, come back unchanged."""
    fixed = 0

    def fix_char_row(m):
        nonlocal fixed
        code = int(m.group(1), 16)
        if code not in truth or _decode(m.group(3)) == truth[code]:
            return m.group(0)
        fixed += 1
        return f"<{m.group(1)}>{m.group(2)}<{_encode(truth[code])}>"

    def fix_range_row(m):
        nonlocal fixed
        lo, hi = int(m.group(1), 16), int(m.group(3), 16)
        if hi - lo >= MAX_RANGE:
            return m.group(0)
        targets = _range_targets(lo, hi, m.group(5))
        wrong = [c for c in truth if lo <= c <= hi and c - lo < len(targets)
                 and targets[c - lo] != truth[c]]
        if not wrong:
            return m.group(0)
        for c in wrong:
            targets[c - lo] = truth[c]
        fixed += len(wrong)
        head = f"<{m.group(1)}>{m.group(2)}<{m.group(3)}>{m.group(4)}"
        if lo == hi:
            return head + f"<{_encode(targets[0])}>"
        # a range can no longer count upward once one target is rewritten,
        # so spell every target out
        return head + "[" + " ".join(f"<{_encode(t)}>" for t in targets) + "]"

    cmap = BFCHAR.sub(lambda b: b.group(1) + CHAR_ROW.sub(fix_char_row, b.group(2)) + b.group(3), cmap)
    cmap = BFRANGE.sub(lambda b: b.group(1) + RANGE_ROW.sub(fix_range_row, b.group(2)) + b.group(3), cmap)
    return cmap, fixed


# --------------------------------------------------------------- one document

STATUSES = ("ok", "wrong", "ligature_char", "missing", "no_table")
#   ok             the row holds the letters the glyph name says
#   wrong          the row holds something else                  <- the defect
#   ligature_char  the row holds the one-character form (U+FB01 for fi). Not
#                  an error, but "Proliﬁc" does not match a search for
#                  "Prolific", so we rewrite it to plain letters too.
#   missing        the table has no row for this glyph. Left alone: the
#                  extractor then falls back to the glyph name.
#   no_table       the font has no ToUnicode table. Same fallback.


def _fonts_with_ligatures(doc):
    """Yield (font name, ToUnicode stream xref or None, {code: letters},
    unreadable ligature-like names) for every font that has ligature glyphs."""
    seen = set()
    for page_no in range(len(doc)):
        for xref, _ext, _type, font_name, *_ in doc.get_page_fonts(page_no):
            if xref in seen:
                continue
            seen.add(xref)
            kind, value = doc.xref_get_key(xref, "Encoding")
            if kind == "xref":
                encoding = doc.xref_object(int(value.split()[0]))
            elif kind == "dict":
                encoding = value
            else:
                continue          # a named standard encoding has no /Differences
            truth, unreadable = {}, []
            for code, name in parse_differences(encoding).items():
                letters = glyph_letters(name)
                if letters:
                    truth[code] = letters
                elif looks_like_ligature(name):
                    unreadable.append(name)
            if not truth and not unreadable:
                continue
            kind, value = doc.xref_get_key(xref, "ToUnicode")
            table = int(value.split()[0]) if kind == "xref" else None
            yield font_name, table, truth, unreadable


def _read_stream(doc, xref) -> str | None:
    try:
        data = doc.xref_stream(xref)
    except Exception:  # noqa: BLE001 - an unreadable table is reported as no_table
        return None
    return data.decode("latin-1") if data else None


def _status(mapped: str | None, letters: str) -> str:
    if mapped is None:
        return "missing"
    if mapped == letters:
        return "ok"
    if len(mapped) == 1 and unicodedata.normalize("NFKC", mapped) == letters:
        return "ligature_char"
    return "wrong"


def census(doc) -> collections.Counter:
    """Count the document's ligature glyphs by status."""
    counts = collections.Counter()
    for _name, table, truth, _unreadable in _fonts_with_ligatures(doc):
        cmap = _read_stream(doc, table) if table else None
        if cmap is None:
            counts["no_table"] += len(truth)
            continue
        mapped = read_cmap(cmap, truth)
        for code, letters in truth.items():
            counts[_status(mapped.get(code), letters)] += 1
    return counts


def repair(doc) -> dict:
    """Correct the ligature rows of `doc` in memory and report:

        fonts       fonts that have ligature glyphs
        before      glyph counts by status, as found
        rewritten   codes whose row was corrected
        after       glyph counts by status, after the repair
        unreadable  ligature-like glyph names glyph_letters could not read
        conflicts   codes skipped because two fonts share one table and name
                    the code differently
        collateral  rows for any other glyph that changed. Checked on every
                    table we rewrite.

    Two things must hold, and the corpus run fails if either does not:
    `after` has no "wrong" and no "ligature_char", and `collateral` is 0.
    """
    before = census(doc)
    fonts, unreadable = 0, set()
    by_table = collections.defaultdict(list)      # table xref -> [truth of each font using it]
    for _name, table, truth, bad_names in _fonts_with_ligatures(doc):
        fonts += 1
        unreadable.update(bad_names)
        if table and truth:
            by_table[table].append(truth)

    rewritten = conflicts = collateral = 0
    for table, truths in by_table.items():
        merged, clash = {}, set()
        for truth in truths:
            for code, letters in truth.items():
                if merged.setdefault(code, letters) != letters:
                    clash.add(code)
        for code in clash:
            del merged[code]
        conflicts += len(clash)
        cmap = _read_stream(doc, table)
        if cmap is None:
            continue
        new, n = fix_cmap(cmap, merged)
        if n:
            others = [c for c in range(256) if c not in merged]
            old_rows, new_rows = read_cmap(cmap, others), read_cmap(new, others)
            collateral += sum(old_rows.get(c) != new_rows.get(c) for c in others)
            doc.update_stream(table, new.encode("latin-1"))
            rewritten += n

    return {
        "fonts": fonts,
        "before": dict(before),
        "rewritten": rewritten,
        "after": dict(census(doc)) if rewritten else dict(before),
        "unreadable": sorted(unreadable),
        "conflicts": conflicts,
        "collateral": collateral,
    }


def open_repaired(path):
    """Open a PDF with its ligature rows corrected. Returns (document, report).
    The caller closes the document. This is the only way later modules open
    a PDF."""
    doc = pymupdf.open(str(path))
    # The repair runs before any page is read, so every font is loaded with
    # its corrected table. No save-and-reopen is needed, which matters: 11
    # CHI 2023 files are damaged in a way MuPDF can read but cannot save.
    return doc, repair(doc)


# ------------------------------------------------------------------ the corpus

def paper_row(path, year: str) -> dict:
    row = {"pid": path.stem, "year": year}
    try:
        doc = pymupdf.open(str(path))
        try:
            row.update(repair(doc))
        finally:
            doc.close()
    except Exception as e:  # noqa: BLE001 - a file we cannot process is a finding
        row["error"] = type(e).__name__ + ": " + str(e)[:120]
    return row


def needs_repair(row: dict) -> bool:
    b = row.get("before", {})
    return bool(b.get("wrong") or b.get("ligature_char"))


def not_fully_repaired(row: dict) -> bool:
    a = row.get("after", {})
    return bool(a.get("wrong") or a.get("ligature_char") or row.get("collateral"))


def summarize(rows: list[dict]) -> dict:
    per_year = {}
    for year in sorted({r["year"] for r in rows}):
        ys = [r for r in rows if r["year"] == year]
        per_year[year] = {
            "papers": len(ys),
            "needed_repair": sum(needs_repair(r) for r in ys),
            "rows_rewritten": sum(r.get("rewritten", 0) for r in ys),
            "not_fully_repaired": [r["pid"] for r in ys if not_fully_repaired(r)],
            "errors": [r["pid"] for r in ys if "error" in r],
        }
    status_totals = collections.Counter()
    for r in rows:
        for status, n in r.get("before", {}).items():
            status_totals[status] += n
    return {
        "papers": len(rows),
        "needed_repair": sum(needs_repair(r) for r in rows),
        "rows_rewritten": sum(r.get("rewritten", 0) for r in rows),
        "glyphs_before": dict(status_totals),
        "unreadable_names": sorted({n for r in rows for n in r.get("unreadable", [])}),
        "per_year": per_year,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Ligature census and repair check over the corpus.")
    ap.add_argument("--year", choices=config.YEARS, help="one year only (default: all)")
    args = ap.parse_args()

    config.require_corpus()
    config.OUTPUT.mkdir(exist_ok=True)
    years = (args.year,) if args.year else config.YEARS
    rows = []
    for year in years:
        pdfs = sorted(config.corpus_year_dir(year).glob("*.pdf"))
        t0 = time.time()
        for i, p in enumerate(pdfs, 1):
            rows.append(paper_row(p, year))
            if i % 200 == 0 or i == len(pdfs):
                print(f"  {year}: {i}/{len(pdfs)}  ({time.time() - t0:.0f}s)", flush=True)
    summary = summarize(rows)

    suffix = f"_{args.year}" if args.year else ""
    with open(config.OUTPUT / f"ligatures{suffix}.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with open(config.OUTPUT / f"ligatures_summary{suffix}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    print()
    print(f"{'year':<6}{'papers':>8}{'needed repair':>15}{'rows rewritten':>16}{'not fully repaired':>20}")
    for year, s in summary["per_year"].items():
        print(f"{year:<6}{s['papers']:>8}{s['needed_repair']:>15}{s['rows_rewritten']:>16}"
              f"{len(s['not_fully_repaired']):>20}")
    left = [p for s in summary["per_year"].values() for p in s["not_fully_repaired"]]
    errors = [p for s in summary["per_year"].values() for p in s["errors"]]
    print(f"\nglyphs as found: {summary['glyphs_before']}")
    if summary["unreadable_names"]:
        print(f"glyph names not read: {summary['unreadable_names']}")
    for label, pids in (("not fully repaired", left), ("errors", errors)):
        if pids:
            print(f"{label}: {len(pids)}")
            for p in pids:
                print("  ", p)
    sys.exit(1 if left or errors else 0)


if __name__ == "__main__":
    main()
