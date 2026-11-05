"""Module 5: sentences.

Contract
  in:  output/text/<year>/<pid>.json       (module 2: blocks)
       output/sections/<year>/<pid>.json   (module 3: where sections start and end)
       output/zones/<year>/<pid>.json      (module 4: what each section is for)
  out: output/sentences/<year>/<pid>.json
         pid, year
         sections    module 4's list, so the file can be read on its own
         sentences   in reading order, each with
                       text      one sentence on one line, hyphenation undone
                       section   index into `sections`
                       kind      text, caption or footnote
                       page      where it starts
                       block     the module 2 block its paragraph starts in
                       joined    true if its two halves stood in different blocks
       output/sentences_summary.json   counts per year, and every paper that
                                       failed a check

What it establishes
  - the unit every detection module reads: a sentence, with the section it
    belongs to and a way back to the page
  - a sentence that the layout cut in two is whole again. A paragraph that
    stops mid-sentence at the foot of a column carries on in the next block
    of running text, past the footnote, caption or table between them.
    Sentences never cross a section boundary.
  - words the typesetter hyphenated at a line end are whole again
    ("evalua-" + "tion"), and compounds that are really hyphenated stay so
    ("semi-" + "structured")

What it does not do
  - It does not read tables, headings, references or the title block.
    Captions and footnotes are split into sentences too, apart from the
    running text and marked by `kind`.
  - It does not change wording, case or spelling. The view the detection
    modules match against (lower case, one spelling per platform name) is
    theirs to build.

Safe to rerun. Needs no PDFs. Run from the repo root:
    py "Phase 1 - Data Preparation/sentences.py" [--year 2023]
"""
import argparse
import collections
import itertools
import json
import re
import statistics
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # the repo root, where config.py is
import config  # noqa: E402
from extract import TEXT_DIR
from sections import SECTIONS_DIR, pieces
from zones import ZONES_DIR

SENTENCES_DIR = config.OUTPUT / "sentences"

KINDS = ("text", "caption", "footnote")

OPEN_MIN = 40            # a block shorter than this is not a paragraph that can be left open
INTRUDER_MAX = 80        # a block shorter than this without a full stop may be a stray table cell
FULL_LINE = 0.85         # a last line this long, against the lines above it, reaches the margin
LOOK_AHEAD = 3           # how many blocks further on the rest of a cut sentence is looked for
LONG = 1000              # a sentence longer than this is reported: probably several, or a table

SOFT_HYPHEN = "­"
HYPHENS = "-‐‑"

# A full stop after one of these does not end a sentence.
ABBREVIATIONS = frozenset("""e.g i.e et al vs cf fig figs eq eqs sec secs tab no nos approx ca resp viz
dr mr mrs ms prof inc ltd co st jr sr vol pp p ch app def ref refs incl excl min max avg std dept univ""".split())

WORD = re.compile(r"[A-Za-z]+(?:[-‐‑][A-Za-z]+)*")
LIST_ITEM = re.compile(r"\s*([•◦▪■–—*]|\(?\d{1,2}[.)]\s|\(?[a-z]\)\s|[-]\s)")
RUN_IN_HEADING = re.compile(r"\s*\d+(\.\d+){1,3}\.?\s+[A-Z]")
FOOTNOTE_MARK = re.compile(r"^\s*(\d{1,2}|[*†‡§¶∗])\s*")
BOUNDARY = re.compile(r"([.!?])([\"”’')\]]*)(\d{1,2})?\s+(?=[A-Z0-9\"“‘(\[])")


# ------------------------------------------------------------------ cleaning

def vocabulary(blocks: list[dict]) -> collections.Counter:
    """Every word and hyphenated compound printed whole in the paper, lower
    case. It settles what a hyphen at a line end is: if the paper writes
    "semi-structured" on one line, "semi-" + "structured" is that compound."""
    words = collections.Counter()
    for b in blocks:
        if b["kind"] in ("text", "caption", "footnote", "reference"):
            for line in b["text"].split("\n"):
                words.update(w.lower() for w in WORD.findall(line.strip().rstrip(HYPHENS + SOFT_HYPHEN)))
    return words


def uses_soft_hyphens(blocks: list[dict]) -> bool:
    """Most papers mark the typesetter's line-end hyphens with an invisible
    "soft hyphen" character. In those a visible hyphen at a line end was
    typed by the authors."""
    return any(SOFT_HYPHEN + "\n" in b["text"] or SOFT_HYPHEN + " \n" in b["text"] for b in blocks)


def join_hyphen(left: str, right: str, words: collections.Counter, soft: bool) -> str:
    """Join the two halves of a word split by a visible hyphen at a line end:
    without the hyphen if the paper prints the word that way elsewhere, with
    it if it prints the compound, and otherwise by how the paper marks its
    line breaks."""
    head = re.search(r"[A-Za-z]+$", left[:-1])
    tail = re.match(r"[A-Za-z]+", right)
    if not head or not tail:
        return left + right
    whole, compound = (head.group() + tail.group()).lower(), (head.group() + "-" + tail.group()).lower()
    if words[whole] and not words[compound]:
        return left[:-1] + right
    if words[compound] or soft or not tail.group()[0].islower():
        return left + right
    return left[:-1] + right


def one_line(text: str, words: collections.Counter, soft: bool) -> str:
    """A block's text as one line: line-end hyphenation undone, line breaks
    turned into spaces."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    out = ""
    for line in lines:
        if not out:
            out = line
        elif out.endswith(SOFT_HYPHEN):
            out = out[:-1] + line
        elif out[-1] in HYPHENS and len(out) > 1 and out[-2].isalpha():
            out = join_hyphen(out, line, words, soft)
        else:
            out += " " + line
    return re.sub(r"\s+", " ", out.replace(SOFT_HYPHEN, "")).strip()


# ---------------------------------------------------------------- paragraphs

def is_open(text: str) -> str:
    """How a block ends: "open" when it plainly stops mid-sentence (on a
    letter, a digit, a comma or a hyphen), "maybe" after a closing bracket
    or quote, "" when it ends a sentence."""
    text = text.rstrip()
    if len(text) < OPEN_MIN or not re.search(r"[a-z]{3}", text):
        return ""
    last = text[-1]
    if last.isalnum() or last in "," + HYPHENS + SOFT_HYPHEN + "—–(":
        return "open"
    return "maybe" if last in ")]”\"’%;" else ""


def last_line_is_full(text: str) -> bool:
    """Whether a block's last line runs to the right margin, as far as the
    text can tell: it is about as long as the lines above it. A paragraph
    cut by the end of a column stops on a full line. A paragraph that is
    over, a quote's attribution or a label stops on a short one."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return False
    return len(lines[-1]) >= FULL_LINE * statistics.median(len(line) for line in lines[:-1])


def starts_new(text: str) -> bool:
    return bool(LIST_ITEM.match(text) or RUN_IN_HEADING.match(text))


def is_stray(text: str) -> bool:
    """A short block with no sentence in it: most often a cell of a table
    printed in the type of the running text."""
    text = text.strip()
    return len(text) < INTRUDER_MAX and not re.search(r"[.!?:]$", text) and not text[:1].islower()


def paragraphs(items: list[tuple[int, dict, str]]) -> list[dict]:
    """Put a section's blocks of running text together into paragraphs.
    items: (block index, block, its text inside the section), in reading
    order. A block that stops mid-sentence takes the next block as its
    continuation: always when that block starts in lower case, otherwise
    only when the first block stops on a full line. If the next block is a stray short one and a block just
    after it starts in lower case, that one is the continuation and the
    stray block is left where it is."""
    out, used = [], set()
    for n, (index, block, text) in enumerate(items):
        if n in used:
            continue
        parts, last = [text], n
        while True:
            state = is_open(parts[-1])
            following = [m for m in range(last + 1, min(last + 1 + LOOK_AHEAD, len(items))) if m not in used]
            if not state or not following:
                break
            nxt = following[0]
            lower = items[nxt][2].lstrip()[:1].islower()
            if state == "maybe" and not lower:
                break
            hyphenated = parts[-1].rstrip()[-1] in HYPHENS + SOFT_HYPHEN
            if not lower and not hyphenated and not last_line_is_full(parts[-1]):
                break                     # "... - P7" and then a new paragraph: nothing was cut
            if not lower and is_stray(items[nxt][2]):
                later = [m for m in following[1:] if items[m][2].lstrip()[:1].islower()]
                if not later:
                    break
                nxt = later[0]
            elif starts_new(items[nxt][2]):
                break
            parts.append(items[nxt][2])
            used.add(nxt)
            last = nxt
        out.append({"block": index, "page": block["page"], "parts": parts})
    return out


def join_parts(parts: list[str], words, soft) -> str:
    """The blocks of one paragraph as one line. A word hyphenated across the
    gap between two blocks is joined like one hyphenated at a line end."""
    return one_line("\n".join(parts), words, soft)


# ----------------------------------------------------------------- sentences

def split_sentences(text: str) -> list[str]:
    """Cut one paragraph into sentences: at a full stop, question mark or
    exclamation mark that is followed by a space and a capital letter, a
    digit, or an opening quote or bracket. Not after an abbreviation
    ("e.g.", "et al.", "Fig."), an initial ("J. Smith") or a list number
    ("1. First")."""
    sentences, start = [], 0
    for m in BOUNDARY.finditer(text):
        before = text[start:m.start()]
        token = before.rsplit(None, 1)[-1] if before.strip() else ""
        token = token.lstrip("([“\"‘'").lower()
        if m.group(1) == ".":
            if token in ABBREVIATIONS or re.fullmatch(r"([a-z]\.)+[a-z]", token):   # "et al.", "c.f.", "a.k.a."
                continue
            if len(token) == 1 and token.isalpha():                 # an initial
                continue
            if token.isdigit() and len(before.strip()) <= 3:        # "1. First item"
                continue
            if m.group(3) and not (token and (token[-1].isalpha() or token[-1] in ")]”\"’")):   # "0.5 12 people"
                continue
        sentences.append(text[start:m.end()].strip())
        start = m.end()
    rest = text[start:].strip()
    if rest:
        sentences.append(rest)
    return sentences


def letters(text: str) -> int:
    """How many letters and digits a text has. Cleaning changes neither, so
    the count says where in a paragraph one block ended and the next began."""
    return sum(ch.isascii() and ch.isalnum() for ch in text)


def build(record: dict, sectioned: dict, zoned: dict) -> dict:
    """One paper's sentences, from its blocks, sections and zones."""
    blocks = record["blocks"]
    index_of = {id(b): i for i, b in enumerate(blocks)}
    words, soft = vocabulary(blocks), uses_soft_hyphens(blocks)
    sentences = []
    for n, (section, zone) in enumerate(zip(sectioned["sections"], zoned["zones"])):
        if zone["label"] == "apparatus":
            continue
        inside = [(index_of[id(b)], b, text) for b, text in pieces(blocks, section["body"], section["end"])]
        groups = {"text": paragraphs([i for i in inside if i[1]["kind"] == "text"])}
        for kind in ("caption", "footnote"):
            groups[kind] = [{"block": i, "page": b["page"], "parts": [FOOTNOTE_MARK.sub("", text) if kind == "footnote" else text]}
                            for i, b, text in inside if b["kind"] == kind]
        found = []
        for kind, paras in groups.items():
            for p in paras:
                seams, at = set(itertools.accumulate(letters(part) for part in p["parts"][:-1])), 0
                for s in split_sentences(join_parts(p["parts"], words, soft)):
                    end = at + letters(s)
                    found.append({"text": s, "section": n, "kind": kind, "page": p["page"], "block": p["block"],
                                  "joined": any(at < seam < end for seam in seams)})
                    at = end
        sentences += sorted(found, key=lambda s: s["block"])
    return {"pid": record["pid"], "year": record["year"],
            "sections": [{k: z[k] for k in ("title", "level", "label", "read", "study")} for z in zoned["zones"]],
            "sentences": sentences}


# ------------------------------------------------------------------- summary

def summary_row(result: dict) -> dict:
    sentences = result["sentences"]
    text = [s for s in sentences if s["kind"] == "text"]
    read = [s for s in text if result["sections"][s["section"]]["read"]]
    lengths = [len(s["text"]) for s in text]
    return {"pid": result["pid"], "year": result["year"],
            "sentences": dict(collections.Counter(s["kind"] for s in sentences)),
            "read": len(read),
            "joined": sum(s["joined"] for s in text),
            "median_length": statistics.median(lengths) if lengths else 0,
            "long": sum(n > LONG for n in lengths),
            "open_ended": sum(bool(re.search(r"[a-z,]$", s["text"])) and len(s["text"]) >= OPEN_MIN for s in text)}


def summarize(rows: list[dict]) -> dict:
    per_year = {}
    for year in sorted({r["year"] for r in rows}):
        ys = [r for r in rows if r["year"] == year]
        ok = [r for r in ys if "error" not in r]
        kinds = collections.Counter()
        for r in ok:
            kinds.update(r["sentences"])
        per_year[year] = {
            "papers": len(ys),
            "sentences": {k: kinds[k] for k in KINDS},
            "read": sum(r["read"] for r in ok),
            "joined": sum(r["joined"] for r in ok),
            "open_ended": sum(r["open_ended"] for r in ok),
            "median_length": statistics.median(r["median_length"] for r in ok) if ok else 0,
            "long": {r["pid"]: r["long"] for r in ok if r["long"] >= 5},
            "no_sentences": [r["pid"] for r in ok if not r["sentences"].get("text")],
            "errors": [r["pid"] for r in ys if "error" in r],
        }
    return {"papers": len(rows), "per_year": per_year}


def main() -> None:
    ap = argparse.ArgumentParser(description="Turn every paper's running text into sentences.")
    ap.add_argument("--year", choices=config.YEARS, help="one year only (default: all)")
    args = ap.parse_args()

    rows = []
    for year in ((args.year,) if args.year else config.YEARS):
        out_dir = SENTENCES_DIR / year
        out_dir.mkdir(parents=True, exist_ok=True)
        files = sorted((ZONES_DIR / year).glob("*.json"))
        if not files:
            raise SystemExit(f"no zones for {year}: run zones.py first")
        for f in files:
            try:
                load = lambda folder: json.loads((folder / year / f.name).read_text(encoding="utf-8"))  # noqa: E731
                result = build(load(TEXT_DIR), load(SECTIONS_DIR), load(ZONES_DIR))
                (out_dir / f.name).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                rows.append(summary_row(result))
            except Exception as e:  # noqa: BLE001 - a paper we cannot split is a finding
                rows.append({"pid": f.stem, "year": year, "error": type(e).__name__ + ": " + str(e)[:120]})
        print(f"  {year}: {len(files)}", flush=True)

    summary = summarize(rows)
    suffix = f"_{args.year}" if args.year else ""
    with open(config.OUTPUT / f"sentences_summary{suffix}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    print()
    print(f"{'year':<6}{'papers':>8}{'sentences':>11}{'read':>10}{'joined':>9}{'open end':>10}"
          f"{'median':>8}{'errors':>8}")
    for year, s in summary["per_year"].items():
        print(f"{year:<6}{s['papers']:>8}{s['sentences']['text']:>11}{s['read']:>10}{s['joined']:>9}"
              f"{s['open_ended']:>10}{s['median_length']:>8.0f}{len(s['errors']):>8}")
    print(f"\n-> {SENTENCES_DIR}")
    sys.exit(1 if any(s["errors"] or s["no_sentences"] for s in summary["per_year"].values()) else 0)


if __name__ == "__main__":
    main()
