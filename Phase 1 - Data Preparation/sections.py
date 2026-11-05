"""Module 3: section isolation.

Contract
  in:  output/text/<year>/<pid>.json   (module 2)
  out: output/sections/<year>/<pid>.json
         pid, year
         source      where the list of headings came from: "outline" (the
                     PDF's own table of contents) or "headings" (the heading
                     blocks module 2 found, for a paper whose outline is
                     missing or unusable)
         sections    in reading order, each with
                       level, title   as the outline gives them
                       role           front, abstract, ccs, keywords, body,
                                      acknowledgments, references, appendix
                       parent         index of the section it sits under, or null
                       page           where the outline says it starts
                       anchor         how its heading was found (see ANCHORS)
                       start          [block, character] where the heading begins
                       body           [block, character] where its text begins
                       end            [block, character] where the next section begins
                       text_chars     characters of running text inside it
         unanchored  outline entries whose heading was not found on the page.
                     Their text stays in the section before them.
       output/sections_summary.json    counts per year, and every paper that
                                       failed a check

What it establishes
  - where every section starts and ends, as positions in module 2's blocks.
    The sections tile the paper: the first starts at block 0, each ends where
    the next starts, the last ends after the last block. No text is copied,
    moved or dropped; `section_text` reads a section back out.
  - which sections are apparatus and not the paper's argument (`role`), from
    their titles and their place after the reference list

What it does not do
  - It does not decide which sections describe a study. That is module 4.
  - It does not see headings that are missing from the outline. ACM's
    outline stops at the second level, so a third-level heading ("4.1.2
    Recruitment.") stays inside its parent's text.

Safe to rerun. Needs no PDFs. Run from the repo root:
    py "Phase 1 - Data Preparation/sections.py" [--year 2023]
"""
import argparse
import collections
import difflib
import json
import re
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # the repo root, where config.py is
import config  # noqa: E402
from extract import TEXT_DIR

SECTIONS_DIR = config.OUTPUT / "sections"

ROLES = ("front", "abstract", "ccs", "keywords", "body", "acknowledgments", "references", "appendix")

# How a heading was found, from the most to the least certain.
ANCHORS = (
    "heading",        # a heading block on the outline's page starts with the title
    "heading_near",   # the same, one page before or after
    "heading_far",    # the same, anywhere later in the paper (the outline's page was wrong)
    "partial",        # a heading block holds the first lines of a long title
    "fuzzy",          # a heading block matches the title except for a few characters
    "in_text",        # the heading is a line inside a block of running text
    "heading_block",  # not from the outline: taken from module 2's heading blocks
)

FUZZY = 0.85              # share of matching characters that still counts as the same title
PARTIAL_MIN = 10          # a heading block this long may be the start of a longer title
MIN_OUTLINE = 3           # an outline with fewer numbered sections found than this is not used
JOIN = 2                  # a title may run on into this many following heading blocks

APPENDIX_WORD = re.compile(r"^\s*appendix\s+(?=[A-Z]\b)", re.I)
NUMBER = re.compile(r"\s*((?:\d+|[A-Z])(?:\.\d+)*)\.?\s+")
TITLE_ROLES = (
    ("abstract", re.compile(r"abstract$")),
    ("ccs", re.compile(r"ccsconcepts$")),
    ("keywords", re.compile(r"(author)?keywords$|additionalkeywordsandphrases$")),
    ("acknowledgments", re.compile(r"acknowledge?ments?")),
    ("references", re.compile(r"references|bibliography$")),
    ("appendix", re.compile(r"appendi(x|ces)")),
)


# ------------------------------------------------------------ matching titles

def squeeze(text: str) -> str:
    """Letters and digits only, lower case. A title in the outline and the
    same title on the page differ in case, spacing, line breaks and
    punctuation, and in nothing else."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def without_number(title: str) -> str:
    m = NUMBER.match(title)
    return title[m.end():] if m else title


def offset_after(text: str, n: int) -> int:
    """The position in `text` just past its first n letters and digits."""
    seen = 0
    for i, ch in enumerate(text):
        if ch.isascii() and ch.isalnum():
            seen += 1
            if seen >= n:
                return i + 1
    return len(text)


def line_starts(text: str) -> list[int]:
    return [0] + [m.end() for m in re.finditer(r"\n", text) if m.end() < len(text)]


def find_title(text: str, title: str, how: str) -> tuple[int, int] | None:
    """Look for `title` at the start of a line of `text`. Returns the
    positions (where the heading begins, where it ends), or None.

    how = "exact"    the line starts with the title, with or without its number
          "partial"  the text from that line on is the beginning of the title
          "fuzzy"    the line starts with something close to the title
          "strict"   for running text: the title with its number starts a
                     line, or a line is the title and nothing else
    """
    numbered, bare = squeeze(title), squeeze(without_number(title))
    if not bare:
        return None
    for start in line_starts(text):
        rest = text[start:]
        unlabelled = APPENDIX_WORD.sub("", rest, count=1)      # "Appendix A Materials" for "A Materials"
        stripped = without_number(unlabelled)
        for candidate in dict.fromkeys((rest, unlabelled, stripped)):
            lead = len(rest) - len(candidate)
            have = squeeze(candidate)
            for want in dict.fromkeys((numbered, bare)):
                end = start + lead + offset_after(candidate, len(want))
                if how == "exact" and have.startswith(want):
                    return start, end
                if how == "partial" and len(have) >= PARTIAL_MIN and want.startswith(have):
                    return start, len(text)
                if (how == "fuzzy" and len(want) >= PARTIAL_MIN and difflib.SequenceMatcher(
                        None, want, have[:len(want)], autojunk=False).ratio() >= FUZZY):
                    return start, end
        if how == "strict":
            line = squeeze(rest.split("\n", 1)[0])
            if (numbered != bare and squeeze(rest).startswith(numbered)) or line in (numbered, bare):
                return start, start + offset_after(rest, len(numbered if line != bare else bare))
    return None


# ----------------------------------------------------------------- anchoring

def to_position(blocks: list[dict], first: int, offset: int) -> list[int]:
    """An offset into the joined text of blocks first, first+1, ... as a
    [block, character] position."""
    i = first
    while i < len(blocks) - 1 and offset >= len(blocks[i]["text"]) and offset > 0:
        offset -= len(blocks[i]["text"])
        i += 1
    if offset >= len(blocks[i]["text"]):
        return [i + 1, 0]
    return [i, offset]


def anchor_outline(blocks: list[dict], outline: list) -> tuple[list[dict], list[dict]]:
    """Find each outline entry's heading on the page. Returns (anchored,
    unanchored). Headings are looked for in the order of the outline, and
    never before the one found last, so a title that occurs twice ("Results"
    under Study 1 and under Study 2) cannot be matched out of turn."""
    by_page = collections.defaultdict(list)
    for i, b in enumerate(blocks):
        if b["kind"] not in ("header", "page_number", "footnote", "notice"):
            by_page[b["page"]].append(i)
    last_page = blocks[-1]["page"] if blocks else 0

    def heading_text(i):
        text = blocks[i]["text"]
        for j in range(i + 1, min(i + 1 + JOIN, len(blocks))):
            if blocks[j]["kind"] != "heading" or blocks[j]["page"] != blocks[i]["page"]:
                break
            text += blocks[j]["text"]
        return text

    def search(title, pages, how, floor):
        for page in pages:
            for i in by_page.get(page, ()):
                is_heading = blocks[i]["kind"] == "heading"
                if is_heading != (how != "strict") or i < floor[0]:
                    continue
                text = heading_text(i) if is_heading else blocks[i]["text"]
                found = find_title(text, title, how)
                if found and [i, found[0]] >= floor:
                    return i, found
        return None

    anchored, unanchored, floor = [], [], [0, 0]
    for level, title, page in outline:
        near = [p for p in (page + 1, page - 1) if p >= 1]
        later = [p for p in range(1, last_page + 1) if abs(p - page) > 1]
        hit = None
        for name, pages, how in (("heading", [page], "exact"), ("partial", [page], "partial"),
                                 ("fuzzy", [page], "fuzzy"), ("in_text", [page], "strict"),
                                 ("heading_near", near, "exact"), ("in_text", near, "strict"),
                                 ("heading_far", later, "exact")):
            hit = search(title, pages, how, floor)
            if hit:
                break
        if not hit:
            unanchored.append({"level": level, "title": title.strip(), "page": page})
            continue
        i, (start, end) = hit
        body = to_position(blocks, i, end)
        anchored.append({"level": level, "title": title.strip(), "page": page, "anchor": name,
                         "start": to_position(blocks, i, start), "body": body})
        floor = body
    return anchored, unanchored


def headings_as_outline(blocks: list[dict]) -> list[dict]:
    """For a paper with no outline: every heading block module 2 found is a
    section. A block that holds several numbered headings ("3 METHOD" and
    "3.1 Participants" printed one under the other) gives one section each.
    The level is read off the number: "3" is 1, "3.1" is 2."""
    found = []
    for i, b in enumerate(blocks):
        if b["kind"] != "heading":
            continue
        text = b["text"]
        starts = [s for s in line_starts(text) if s == 0 or NUMBER.match(text[s:])]
        for start, stop in zip(starts, starts[1:] + [len(text)]):
            title = " ".join(text[start:stop].split())
            number = NUMBER.match(title)
            if not squeeze(title):
                continue
            found.append({"level": number.group(1).count(".") + 1 if number else 1, "title": title,
                          "page": b["page"], "anchor": "heading_block",
                          "start": [i, start], "body": to_position(blocks, i, stop)})
    return found


def standard_headings(blocks: list[dict], anchored: list[dict]) -> list[dict]:
    """The headings every paper has and an outline may leave out. "CCS
    Concepts" and "Keywords" are never in ACM's outline; without them their
    lines would count as the abstract. Some outlines also lack "Abstract",
    "Acknowledgments" or "References". Each is looked for as a heading block,
    and the three that open the paper also as a line of their own in a text
    block, before the first numbered section."""
    have = {title_role(a["title"]) for a in anchored}
    taken = {tuple(a["start"]) for a in anchored}
    numbered = [a["start"][0] for a in anchored if title_role(a["title"]) is None]
    opening_ends = min(numbered) if numbered else len(blocks)
    extras = []
    for title, opening in (("Abstract", True), ("CCS Concepts", True), ("Keywords", True),
                           ("Acknowledgments", False), ("Acknowledgements", False), ("References", False)):
        if title_role(title) in have:
            continue
        for i, b in enumerate(blocks):
            if opening and (i >= opening_ends or b["page"] > 2):
                break
            if b["kind"] != "heading" and not (opening and b["kind"] == "text"):
                continue
            found = find_title(b["text"], title, "exact" if b["kind"] == "heading" else "strict")
            if found and (i, found[0]) not in taken:
                extras.append({"level": 1, "title": title, "page": b["page"],
                               "anchor": "heading_block" if b["kind"] == "heading" else "in_text",
                               "start": [i, found[0]], "body": to_position(blocks, i, found[1])})
                have.add(title_role(title))
                break
    return extras


# -------------------------------------------------------------------- roles

def title_role(title: str) -> str | None:
    name = squeeze(without_number(title))
    for role, pattern in TITLE_ROLES:
        if pattern.match(name):
            return role
    return None


def give_roles(sections: list[dict]) -> None:
    """A first-level section gets its role from its title; anything on the
    first level after the reference list is an appendix. A subsection has
    the role of the section it sits under."""
    after_references = False
    for s in sections:
        if s["role"] == "front":
            continue
        if s["parent"] is not None:
            s["role"] = sections[s["parent"]]["role"]
            continue
        role = title_role(s["title"])
        s["role"] = role or ("appendix" if after_references else "body")
        after_references |= role == "references"


# ----------------------------------------------------------------- sections

def pieces(blocks: list[dict], start: list[int], end: list[int]):
    """Every (block, its text between the two positions)."""
    for i in range(start[0], min(end[0] + 1, len(blocks))):
        lo = start[1] if i == start[0] else 0
        hi = end[1] if i == end[0] else len(blocks[i]["text"])
        if hi > lo:
            yield blocks[i], blocks[i]["text"][lo:hi]


def section_text(blocks: list[dict], section: dict, kinds=("text",)) -> str:
    """The text of one section, headings of its subsections not included:
    its blocks of the given kinds, from where its text begins to where the
    next section begins."""
    return "\n".join(text for b, text in pieces(blocks, section["body"], section["end"]) if b["kind"] in kinds)


def build(record: dict) -> dict:
    """Cut one paper (a module 2 record) into sections."""
    blocks = record["blocks"]
    source = "outline"
    anchored, unanchored = anchor_outline(blocks, record["outline"])
    if sum(title_role(a["title"]) is None for a in anchored) < MIN_OUTLINE:
        # no outline, or one that lists only the abstract and the references,
        # or one left over from the authors' own PDF tool
        source, anchored, unanchored = "headings", headings_as_outline(blocks), []
    top = min((a["level"] for a in anchored), default=1)
    for a in anchored:                  # an outline nested inside a wrapper entry starts below level 1
        a["level"] -= top - 1
    anchored += standard_headings(blocks, anchored)
    anchored.sort(key=lambda a: a["start"])

    front = {"level": 0, "title": "", "page": 1, "anchor": None, "start": [0, 0], "body": [0, 0]}
    sections = [dict(front, role="front", parent=None)]
    open_at = {}                                    # level -> index of the last section on it
    for a in anchored:
        above = [n for level, n in open_at.items() if level < a["level"]]
        sections.append(dict(a, role=None, parent=max(above) if above else None))
        open_at = {level: n for level, n in open_at.items() if level < a["level"]}
        open_at[a["level"]] = len(sections) - 1
    for s, following in zip(sections, sections[1:] + [None]):
        s["end"] = following["start"] if following else [len(blocks), 0]
        s["text_chars"] = sum(len(t) for b, t in pieces(blocks, s["body"], s["end"]) if b["kind"] == "text")
    give_roles(sections)
    return {"pid": record["pid"], "year": record["year"], "source": source,
            "sections": sections, "unanchored": unanchored}


# ------------------------------------------------------------------- summary

def summary_row(result: dict) -> dict:
    sections = result["sections"]
    roles = collections.Counter(s["role"] for s in sections)
    return {"pid": result["pid"], "year": result["year"], "source": result["source"],
            "sections": len(sections) - 1,
            "anchors": dict(collections.Counter(s["anchor"] for s in sections[1:])),
            "unanchored": len(result["unanchored"]),
            "roles": dict(roles),
            "body_chars": sum(s["text_chars"] for s in sections if s["role"] == "body"),
            "text_chars": sum(s["text_chars"] for s in sections)}


def summarize(rows: list[dict]) -> dict:
    per_year = {}
    for year in sorted({r["year"] for r in rows}):
        ys = [r for r in rows if r["year"] == year]
        ok = [r for r in ys if "error" not in r]
        anchors = collections.Counter()
        for r in ok:
            anchors.update(r["anchors"])
        per_year[year] = {
            "papers": len(ys),
            "from_headings": [r["pid"] for r in ok if r["source"] == "headings"],
            "extra_standard_headings": sum(r["anchors"].get("heading_block", 0) for r in ok if r["source"] == "outline"),
            "sections": sum(r["sections"] for r in ok),
            "anchors": {a: anchors[a] for a in ANCHORS},
            "unanchored": {r["pid"]: r["unanchored"] for r in ok if r["unanchored"]},
            "no_abstract": [r["pid"] for r in ok if not r["roles"].get("abstract")],
            "no_references": [r["pid"] for r in ok if not r["roles"].get("references")],
            "no_body": [r["pid"] for r in ok if r["roles"].get("body", 0) < 3],
            "errors": [r["pid"] for r in ys if "error" in r],
        }
    return {"papers": len(rows), "per_year": per_year}


def main() -> None:
    ap = argparse.ArgumentParser(description="Cut every paper into its sections.")
    ap.add_argument("--year", choices=config.YEARS, help="one year only (default: all)")
    args = ap.parse_args()

    rows = []
    for year in ((args.year,) if args.year else config.YEARS):
        out_dir = SECTIONS_DIR / year
        out_dir.mkdir(parents=True, exist_ok=True)
        files = sorted((TEXT_DIR / year).glob("*.json"))
        if not files:
            raise SystemExit(f"no text for {year}: run extract.py first")
        for f in files:
            try:
                result = build(json.loads(f.read_text(encoding="utf-8")))
                (out_dir / f.name).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                rows.append(summary_row(result))
            except Exception as e:  # noqa: BLE001 - a paper we cannot cut is a finding
                rows.append({"pid": f.stem, "year": year, "error": type(e).__name__ + ": " + str(e)[:120]})
        print(f"  {year}: {len(files)}", flush=True)

    summary = summarize(rows)
    suffix = f"_{args.year}" if args.year else ""
    with open(config.OUTPUT / f"sections_summary{suffix}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    print()
    print(f"{'year':<6}{'papers':>8}{'sections':>10}{'not found':>11}{'in papers':>11}"
          f"{'no outline':>12}{'no abstract':>13}{'no refs':>9}{'errors':>8}")
    for year, s in summary["per_year"].items():
        print(f"{year:<6}{s['papers']:>8}{s['sections']:>10}{sum(s['unanchored'].values()):>11}"
              f"{len(s['unanchored']):>11}{len(s['from_headings']):>12}{len(s['no_abstract']):>13}"
              f"{len(s['no_references']):>9}{len(s['errors']):>8}")
    print(f"\n-> {SECTIONS_DIR}")
    sys.exit(1 if any(s["errors"] for s in summary["per_year"].values()) else 0)


if __name__ == "__main__":
    main()
