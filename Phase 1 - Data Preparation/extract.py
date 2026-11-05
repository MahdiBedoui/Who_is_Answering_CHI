"""Module 2: text extraction.

Contract
  in:  one PDF, opened through ligatures.open_repaired
  out: output/text/<year>/<pid>.json
         pid, year, pages
         ligature_rows_rewritten
         body_size   the font size of the paper's running text, in points
         outline     the PDF's own table of contents: [level, title, page]
         blocks      every text block of the paper in reading order, each with
                       page    1-based, like the outline
                       kind    what the block is (see KINDS below)
                       column  0 full width, 1 left, 2 right
                       bbox    [x0, y0, x1, y1] in points
                       size    its font size in points
                       bold    whether most of it is bold
                       text    as printed, line breaks kept
       output/text_summary.json   counts per year, and every paper that
                                  failed a check

What it establishes
  - the text of every paper, in the order a person reads a two-column page
  - what each block is, as far as position and type can tell: a running
    header, a heading, a caption, a footnote, a reference, or text. A
    sentence that crosses a column or a page often has a footnote or a
    caption between its two halves; with the kinds, a later module can join
    the halves without moving anything
  - nothing is dropped on purpose: every block is kept and labelled, and each
    paper records how many characters MuPDF's plain-text reading of a page
    has that our blocks do not (`characters_lost`)

What it does not do
  - It does not decide which sections matter. That is modules 3 and 4.
  - It does not clean the text: hyphens at line ends and line breaks stay as
    printed. That is module 5.
  - It does not tell a table cell printed in the type of the running text
    from a short paragraph, unless the table has a "Table N" caption next
    to it. Kinds come from position, type and captions only.

Safe to rerun: a paper whose output file exists is skipped unless --force.
Run from the repo root:
    py "Phase 1 - Data Preparation/extract.py" [--year 2023] [--force]
"""
import argparse
import collections
import json
import re
import pathlib
import sys
import time

import pymupdf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # the repo root, where config.py is
import config  # noqa: E402
from ligatures import open_repaired

TEXT_DIR = config.OUTPUT / "text"

# Layout constants, in points (1/72 inch). CHI papers are US Letter, two columns.
LINE_TOLERANCE = 3.5     # spans whose tops are closer than this are one line
WORD_GAP = 1.0           # a horizontal gap wider than this is a space
CENTRE_MARGIN = 30       # a block reaching this far past the centre on both sides is full width
HEADER_BOTTOM = 73       # a block ending above this is the running header
#   Measured on 218 papers from all five years: running headers end between
#   64 and 72 pt, and the first line of body text never starts above 74 pt.
GUTTER_GAP = 10          # an empty strip this wide over the page centre separates two columns
PAGE_NUMBER_TOP = 712    # a block that is only a number and starts below this is a page number
#   Standard CHI pages carry no footer. A few papers in another layout print
#   page numbers, which would otherwise land between the two columns.
HEADER_BAND = 100        # a header in another layout still starts above this ...
HEADER_REPEATS = 3       # ... and prints the same text at the top of this many pages
HEADER_MIN_LENGTH = 15   # short repeated cells ("Yes", "Table 2") are not headers

# What a block can be. Everything except "text" is something a sentence of
# running text can be interrupted by, or is not running text at all.
KINDS = (
    "header",        # the running header of a page
    "page_number",   # a lone number at the foot of a page
    "front_matter",  # page 1 above the abstract: title, authors, affiliations
    "heading",       # a section heading: bold and larger than the running text
    "caption",       # starts with "Figure 3:" or "Table 2.", or the same in bold
    "table",         # a cell of a table found from its caption
    "footnote",      # small type at the foot of a column, starting with its mark
    "notice",        # page 1 small print: licence, copyright, reference format
    "reference",     # an entry of the reference list
    "small_text",    # other type smaller than the running text: tables, figures, boxes
    "large_text",    # other type larger than the running text: figures, boxes
    "text",          # type of the running text: paragraphs, lists, quotes
)

# Type sizes, relative to the paper's running text. Measured on 700 papers:
# 98.5% of the characters outside headings, captions and references are
# within 0.2 pt of the running text (9 pt). What is not is a table, a figure
# or a box: footnotes, references and headers are 7 pt, most tables 8 pt.
# Headings are 11 or 13 pt and bold; captions are 9 pt and bold.
SMALL = -0.3             # this much smaller than the running text is small type
LARGE = 0.3              # and this much larger is large type
HEADING_LARGER = 1.0     # a heading is at least this much larger, and bold
BOLD_SHARE = 0.7         # share of bold characters that makes a block bold
SUPERSCRIPT = 1.0        # a footnote mark is at least this much smaller than its note
PROSE_MIN_LENGTH = 100   # a column-wide block this long is running text, not a table cell
MARGIN_TOLERANCE = 4     # how far from the column's left edge running text may start
ROW_TOLERANCE = 6        # table cells whose tops are closer than this are one row
TABLE_GAP = 12           # white space this tall between a table and body text ends the table
TABLE_BREAK = 18         # white space this tall ends a table inside a column, whatever follows

CAPTION = re.compile(r"\s*(Figure|Fig\.|Table|Listing|Algorithm)\s*[A-Z]?\d+[a-z]?\s*([:.])?", re.I)
TABLE_CAPTION = re.compile(r"\s*Table\s*[A-Z]?\d", re.I)
REFERENCES = re.compile(r"\s*(\d+|[A-Z])?\.?\s*references\s*$", re.I)
ABSTRACT = re.compile(r"\s*abstract\b", re.I)
NOTICE = re.compile(r"Permission to make|This work is licensed|ACM ISBN|ACM Reference Format|"
                    r"Copyright held|©|Authors.? Contact Information|Corresponding author", re.I)
BOLD_FONT = re.compile(r"Bold|TB|Bd|Black|Heavy|Semibold")
FOOTNOTE_SYMBOLS = "*†‡§¶∗"

# MuPDF's default for this call also decodes every image on the page, which
# we never use and which takes most of the time.
TEXT_ONLY = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES


# ------------------------------------------------------------------ one block

def lines_of(spans: list[dict]) -> list[list[dict]]:
    """Group a block's spans into visual lines, each sorted left to right.

    We rebuild lines from positions and ignore MuPDF's own grouping, because
    some PDFs paint their text out of order. Spans are clustered by their top
    edge: 3.5 pt absorbs superscripts and run-in headings, and body lines are
    about 11 pt apart, so two lines never merge.
    """
    lines, current, top = [], [], None
    for span in sorted(spans, key=lambda s: s["bbox"][1]):
        y = span["bbox"][1]
        if current and y - top > LINE_TOLERANCE:
            lines.append(current)
            current = []
        if not current:
            top = y                      # a line is anchored at its first span
        current.append(span)
    if current:
        lines.append(current)
    for line in lines:
        line.sort(key=lambda s: s["bbox"][0])
    return lines


def block_text(spans: list[dict]) -> str:
    """The text of one block: lines joined by newlines, with a space wherever
    two spans on a line are visibly apart and neither already carries one."""
    out = []
    for line in lines_of([s for s in spans if s["text"]]):
        if out:
            out.append("\n")
        right_edge = None
        for span in line:
            apart = right_edge is not None and span["bbox"][0] - right_edge > WORD_GAP
            if apart and not out[-1].endswith(" ") and not span["text"].startswith(" "):
                out.append(" ")
            out.append(span["text"])
            right_edge = span["bbox"][2]
    return "".join(out)


def split_at_gutter(spans: list[dict], centre: float) -> list[list[dict]]:
    """Undo a merge MuPDF sometimes makes: one block holding a line of the
    left column and a line of the right column, because they sit at the same
    height. Read as one block, that line of the left column would be read
    after the whole right column.

    The test: no piece of the block's text crosses the page centre, and on
    every line that has text on both sides the two sides are at least a
    gutter apart. Real full-width text (a title, a wide caption) always has
    words crossing the centre, so it is never split.

    Returns [spans] unchanged, or [left spans, right spans].
    """
    inked = [s for s in spans if s["text"].strip()]
    left = [s for s in inked if s["bbox"][2] <= centre]
    right = [s for s in inked if s["bbox"][0] >= centre]
    if not left or not right or len(left) + len(right) < len(inked):
        return [spans]
    for line in lines_of(inked):
        ends = [s["bbox"][2] for s in line if s["bbox"][2] <= centre]
        starts = [s["bbox"][0] for s in line if s["bbox"][0] >= centre]
        if ends and starts and min(starts) - max(ends) < GUTTER_GAP:
            return [spans]
    return [left, right]


# ------------------------------------------------------------------- one page

def bounding_box(spans: list[dict]) -> list[float]:
    boxes = [s["bbox"] for s in spans if s["text"].strip()] or [s["bbox"] for s in spans]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def column_of(bbox, page_width: float) -> int:
    x0, _, x1, _ = bbox
    centre = page_width / 2
    if x0 < centre - CENTRE_MARGIN and x1 > centre + CENTRE_MARGIN:
        return 0
    return 1 if x0 < centre else 2


def style_of(spans: list[dict]) -> tuple[float, bool, bool]:
    """(font size, is bold, starts with a footnote mark) for one block.

    The size is the one most of its characters are set in. A footnote mark is
    a raised number or symbol: a first piece of at most three characters set
    at least a point smaller than the block, or one of * † ‡ § ¶.
    """
    inked = [s for s in spans if s["text"].strip()]
    if not inked:
        return 0.0, False, False
    sizes, bold, total = collections.Counter(), 0, 0
    for s in inked:
        n = len(s["text"].strip())
        sizes[round(s["size"], 1)] += n
        total += n
        if s["flags"] & 16 or BOLD_FONT.search(s["font"]):
            bold += n
    size = sizes.most_common(1)[0][0]
    first = lines_of(inked)[0][0]
    mark = first["text"].strip()
    marked = (mark[:1] in FOOTNOTE_SYMBOLS
              or (len(mark) <= 3 and round(first["size"], 1) <= size - SUPERSCRIPT))
    return size, bold / total >= BOLD_SHARE, marked


def read_page(page) -> list[dict]:
    """One page's text blocks with their position and type, not yet labelled
    or ordered. `marked` is used for labelling and removed before writing."""
    width = page.rect.width
    blocks = []
    for raw in page.get_text("dict", flags=TEXT_ONLY)["blocks"]:
        for spans in split_at_gutter([s for line in raw["lines"] for s in line["spans"]], width / 2):
            text = block_text(spans)
            if not text.strip():
                continue
            bbox = [round(v, 1) for v in bounding_box(spans)]
            size, bold, marked = style_of(spans)
            blocks.append({"page": page.number + 1, "kind": "text", "column": column_of(bbox, width),
                           "bbox": bbox, "size": size, "bold": bold, "text": text, "marked": marked})
    return blocks


# ------------------------------------------------------------------ one paper

def body_size_of(blocks: list[dict], pages: int) -> float:
    """The font size of the paper's running text, to the nearest half point:
    the size most characters are set in, counted on long blocks of the first
    half of the paper so that a long reference list in small type cannot win.
    Half points, because one paragraph measures 8.9 and the next 9.1."""
    counted = collections.Counter()
    for minimum in (200, 1):
        for b in blocks:
            if b["page"] <= max(4, pages // 2) and len(b["text"]) >= minimum:
                counted[round(b["size"] * 2) / 2] += len(b["text"])
        if counted:
            break
    return counted.most_common(1)[0][0] if counted else 0.0


def column_edges(blocks: list[dict]) -> dict[int, tuple[float, float]]:
    """{column: (left edge, width)} of the paper's running text, read off its
    long blocks."""
    edges = {}
    for column in (1, 2):
        long_blocks = [b for b in blocks if b["column"] == column and len(b["text"]) >= 300]
        if long_blocks:
            left = collections.Counter(round(b["bbox"][0]) for b in long_blocks).most_common(1)[0][0]
            width = collections.Counter(round(b["bbox"][2] - b["bbox"][0]) for b in long_blocks).most_common(1)[0][0]
            edges[column] = (left, width)
    return edges


def label_position(blocks: list[dict]) -> None:
    """Headers and page numbers, which position alone gives away."""
    for b in blocks:
        text = b["text"].strip()
        if b["bbox"][3] < HEADER_BOTTOM:
            b["kind"] = "header"
        elif b["bbox"][1] > PAGE_NUMBER_TOP and text.isdigit() and len(text) <= 3:
            b["kind"] = "page_number"


def label_repeated_headers(blocks: list[dict]) -> int:
    """Catch the running headers the position rule misses, and return how many.

    About 1 page in 100 prints its header a few points lower than usual:
    papers in a slightly different template, and titles long enough to wrap
    onto a second line. A running header gives itself away another way: the
    same text sits on the top line of many pages. So a block on the top line
    of its page, whose text is on the top line of at least three pages, is a
    header too. A header has two halves (title or venue on the left, authors
    on the right); a short half such as "Shin et al." counts only when the
    other half on its line was caught.
    """
    def squeezed(block):
        return " ".join(block["text"].split())

    top_lines = collections.defaultdict(list)          # page -> blocks on its top line
    for b in blocks:
        if b["kind"] == "text" and b["bbox"][1] < HEADER_BAND:
            top_lines[b["page"]].append(b)
    for page, candidates in top_lines.items():
        top = min(b["bbox"][1] for b in candidates)
        top_lines[page] = [b for b in candidates if b["bbox"][1] - top <= LINE_TOLERANCE]

    seen = collections.Counter(squeezed(b) for line in top_lines.values() for b in line)
    found = 0
    for line in top_lines.values():
        repeated = [b for b in line if seen[squeezed(b)] >= HEADER_REPEATS]
        if any(len(squeezed(b)) >= HEADER_MIN_LENGTH for b in repeated):
            for b in repeated:
                b["kind"] = "header"
                found += 1
    return found


def is_caption(block: dict) -> bool:
    """ "Figure 3: ..." or "Table 2. ...", or the same in bold without the
    colon. A sentence of running text that begins "Figure 3 shows ..." is
    neither."""
    m = CAPTION.match(block["text"])
    return bool(m) and (bool(m.group(2)) or block["bold"])


def label_type(blocks: list[dict], body: float) -> None:
    """Headings, captions and small type, which the type alone gives away.
    Blocks must be in reading order: the reference list is everything from
    the "References" heading to the next heading."""
    in_references = False
    for b in blocks:
        if b["kind"] != "text":
            continue
        lines = b["text"].strip().split("\n")
        larger = b["size"] - body
        if b["bold"] and larger >= HEADING_LARGER and len(b["text"]) < 200:
            b["kind"] = "heading"
            in_references = any(REFERENCES.match(line) for line in lines)
        elif is_caption(b):
            b["kind"] = "caption"
        elif in_references or REFERENCES.match(lines[0]):
            b["kind"] = "reference"
            in_references = True
        elif larger <= SMALL:
            b["kind"] = "small_text"
        elif larger >= LARGE:
            b["kind"] = "large_text"


def label_front_matter(blocks: list[dict]) -> None:
    """Page 1 above the abstract: title, authors, affiliations. Blocks must be
    in reading order. Where page 1 has no abstract heading, the front matter
    ends at the first long paragraph instead."""
    first_page = [b for b in blocks if b["page"] == 1]
    starts = [b for b in first_page if b["kind"] in ("heading", "text") and ABSTRACT.match(b["text"])]
    starts = starts or [b for b in first_page if b["kind"] == "text" and len(b["text"]) >= 300]
    top = starts[0]["bbox"][1] if starts else float("inf")
    for b in first_page:
        if (b["bbox"][1] < top and len(b["text"]) < 300
                and b["kind"] in ("text", "heading", "small_text", "large_text")):
            b["kind"] = "front_matter"


def label_column_feet(page_blocks: list[dict]) -> None:
    """Footnotes and, on page 1, the licence notice.

    Both are small type at the foot of a column with nothing but small type
    below them. A footnote starts with its mark; once one is found, the small
    blocks under it are footnotes too. On page 1, small type at the foot of a
    column that is not a footnote is the notice, and so is the "ACM Reference
    Format" block wherever it sits.
    """
    first_page = bool(page_blocks) and page_blocks[0]["page"] == 1
    for column in (0, 1, 2):
        stack = sorted((b for b in page_blocks if b["column"] == column
                        and b["kind"] not in ("header", "page_number")), key=lambda b: b["bbox"][1])
        foot = []
        while stack and stack[-1]["kind"] == "small_text":
            foot.insert(0, stack.pop())
        if not stack:
            continue                     # a column of nothing but small type is a table or a figure
        started = False
        for b in foot:
            started = started or b["marked"]
            if started:
                b["kind"] = "footnote"
            elif first_page:
                b["kind"] = "notice"
    if first_page:
        for b in page_blocks:
            if b["kind"] in ("text", "small_text", "large_text", "footnote") and NOTICE.search(b["text"][:200]):
                b["kind"] = "notice"


def is_running_text(b: dict, edges: dict) -> bool:
    """A heading at the column's left edge, or a long block of body type as
    wide as its column. Small and large type never count."""
    if b["column"] not in edges or b["kind"] not in ("text", "heading"):
        return False
    left, width = edges[b["column"]]
    aligned = abs(b["bbox"][0] - left) <= MARGIN_TOLERANCE
    if b["kind"] == "heading":
        return aligned
    return (aligned and b["bbox"][2] - b["bbox"][0] >= 0.8 * width
            and len(b["text"]) >= PROSE_MIN_LENGTH)


def is_set_off_text(b: dict, gap: float, edges: dict) -> bool:
    """The short last line of a paragraph next to a table: at the column's
    left edge, in body type, and separated from the table by white space."""
    if b["column"] not in edges or b["kind"] != "text" or b["bold"]:
        return False
    aligned = abs(b["bbox"][0] - edges[b["column"]][0]) <= MARGIN_TOLERANCE
    return aligned and gap >= TABLE_GAP and bool(re.search(r"[a-z]{3}", b["text"]))


def label_wide_tables(page_blocks: list[dict], edges: dict) -> None:
    """Find the cells of tables as wide as the page.

    MuPDF returns such a table as separate blocks in the left and right
    halves of the page. Read column by column, the right half of the table
    would come after the running text under its left half. CHI prints a
    table's caption above it, so: under a full-width "Table N" caption,
    everything down to the first block of running text (or the next
    full-width caption) is the table.
    """
    for caption in page_blocks:
        if not (caption["kind"] == "caption" and caption["column"] == 0 and TABLE_CAPTION.match(caption["text"])):
            continue
        bottom = caption["bbox"][3]
        below = sorted((b for b in page_blocks if b is not caption and b["bbox"][1] >= bottom - 1
                        and b["kind"] not in ("header", "page_number", "footnote", "notice")),
                       key=lambda b: b["bbox"][1])
        for b in below:
            if ((b["kind"] == "caption" and b["column"] == 0) or is_running_text(b, edges)
                    or is_set_off_text(b, b["bbox"][1] - bottom, edges)):
                break
            if b["kind"] != "caption":
                b["kind"] = "table"
                b["table_top"] = caption["bbox"][1]
            bottom = max(bottom, b["bbox"][3])


def label_column_tables(page_blocks: list[dict], edges: dict) -> None:
    """Find the cells of tables that sit inside one column.

    A table set in small type is already kept out of the running text by its
    size. One set at body size is not, and its cells would be read as
    sentences. Starting from a "Table N" caption inside a column, the cells
    are the blocks of that column directly under it, down to the first
    running text or the first wide strip of white space. If nothing is
    there, the caption was printed under its table, and the same walk goes
    upward. The order of the blocks does not change.
    """
    def walk(blocks, edge, down):
        cells = []
        for b in blocks:
            gap = b["bbox"][1] - edge if down else edge - b["bbox"][3]
            if (b["kind"] not in ("text", "small_text", "large_text") or gap >= TABLE_BREAK
                    or is_running_text(b, edges) or is_set_off_text(b, gap, edges)):
                break
            cells.append(b)
            edge = max(edge, b["bbox"][3]) if down else min(edge, b["bbox"][1])
        return cells

    for caption in page_blocks:
        if not (caption["kind"] == "caption" and caption["column"] in (1, 2)
                and TABLE_CAPTION.match(caption["text"])):
            continue
        top, bottom = caption["bbox"][1], caption["bbox"][3]
        column = [b for b in page_blocks if b is not caption and b["column"] == caption["column"]
                  and b["kind"] not in ("header", "page_number", "footnote", "notice")]
        below = sorted((b for b in column if b["bbox"][1] >= bottom - 1), key=lambda b: b["bbox"][1])
        above = sorted((b for b in column if b["bbox"][3] <= top + 1), key=lambda b: -b["bbox"][3])
        for b in walk(below, bottom, True) or walk(above, top, False):
            b["kind"] = "table"


def reading_order(blocks: list[dict]) -> list[dict]:
    """Sort one page's blocks the way a person reads a two-column page.

    A full-width block (a title, a wide figure caption) cuts the page into
    bands. Everything above it is read first, left column then right column,
    then the full-width block itself, then the band below it. The cells of a
    wide table are read as part of the table, row by row, straight after its
    caption.
    """
    cells = [b for b in blocks if "table_top" in b]
    flow = [b for b in blocks if "table_top" not in b]
    cuts = sorted(b["bbox"][1] for b in flow if b["column"] == 0)

    def key(b):
        y = b["bbox"][1]
        if b["column"] == 0:
            band = sum(c < y for c in cuts) + 1       # it opens the band it heads
            return (band, 0, y)
        return (sum(c <= y for c in cuts), b["column"], y)

    ordered = []
    for b in sorted(flow, key=key):
        ordered.append(b)
        mine = sorted((c for c in cells if c["table_top"] == b["bbox"][1] and b["kind"] == "caption"),
                      key=lambda c: c["bbox"][1])
        rows, row_top = [], None
        for c in mine:
            if row_top is None or c["bbox"][1] - row_top > ROW_TOLERANCE:
                rows.append([])
                row_top = c["bbox"][1]
            rows[-1].append(c)
        for row in rows:
            ordered.extend(sorted(row, key=lambda c: c["bbox"][0]))
    return ordered


def order_page(page_blocks: list[dict]) -> list[dict]:
    """Header first, then the page in reading order, then the page number."""
    header = sorted((b for b in page_blocks if b["kind"] == "header"), key=lambda b: b["bbox"][0])
    number = [b for b in page_blocks if b["kind"] == "page_number"]
    rest = [b for b in page_blocks if b["kind"] not in ("header", "page_number")]
    return header + reading_order(rest) + number


def label_and_order(blocks: list[dict], pages: int) -> tuple[list[dict], float]:
    """Give every block its kind and put the paper in reading order. Returns
    (blocks, body size). The steps depend on each other in this order:
    position, then reading order, then type (the reference list is found by
    reading on from its heading), then the rules that build on type."""
    body = body_size_of(blocks, pages)
    edges = column_edges(blocks)
    label_position(blocks)
    label_repeated_headers(blocks)
    by_page = collections.defaultdict(list)
    for b in blocks:
        by_page[b["page"]].append(b)
    ordered = [b for page in sorted(by_page) for b in order_page(by_page[page])]
    label_type(ordered, body)
    label_front_matter(ordered)
    final = []
    for page in sorted(by_page):
        label_column_feet(by_page[page])
        label_wide_tables(by_page[page], edges)
        label_column_tables(by_page[page], edges)
        final.extend(order_page(by_page[page]))
    for b in final:
        b.pop("marked", None)
        b.pop("table_top", None)
    return final, body


def visible_characters(text: str) -> collections.Counter:
    return collections.Counter(ch for ch in text if not ch.isspace())


def extract(path, year: str) -> dict:
    """Everything module 2 knows about one paper (see the contract above),
    plus `characters_lost`: how many visible characters MuPDF's plain text
    has that our blocks do not, counted per page. It is 0 for almost every
    paper. Where it is not, the text is a figure description written for
    screen readers or a stray symbol from a formula, which the block reader
    does not return."""
    doc, report = open_repaired(path)
    try:
        blocks, lost = [], 0
        for page in doc:
            page_blocks = read_page(page)
            blocks.extend(page_blocks)
            ours = visible_characters("".join(b["text"] for b in page_blocks))
            lost += sum((visible_characters(page.get_text()) - ours).values())
        blocks, body = label_and_order(blocks, len(doc))
        return {
            "pid": path.stem,
            "year": year,
            "pages": len(doc),
            "ligature_rows_rewritten": report["rewritten"],
            "characters_lost": lost,
            "body_size": body,
            "outline": [[level, title.strip(), page] for level, title, page in doc.get_toc()],
            "blocks": blocks,
        }
    finally:
        doc.close()


# ------------------------------------------------------------------ the corpus

def summary_row(record: dict) -> dict:
    """The few numbers the summary keeps for one paper."""
    kinds = collections.Counter(b["kind"] for b in record["blocks"])
    with_header = {b["page"] for b in record["blocks"] if b["kind"] == "header"}
    return {"pid": record["pid"], "year": record["year"], "pages": record["pages"],
            "pages_without_header": sum(p not in with_header for p in range(2, record["pages"] + 1)),
            "blocks": len(record["blocks"]), "kinds": dict(kinds),
            "text_characters": sum(len(b["text"]) for b in record["blocks"] if b["kind"] == "text"),
            "body_size": record["body_size"], "outline_entries": len(record["outline"]),
            "characters_lost": record["characters_lost"]}


def summarize(rows: list[dict]) -> dict:
    per_year = {}
    for year in sorted({r["year"] for r in rows}):
        ys = [r for r in rows if r["year"] == year]
        ok = [r for r in ys if "error" not in r]
        kinds = collections.Counter()
        for r in ok:
            kinds.update(r["kinds"])
        per_year[year] = {
            "papers": len(ys),
            "pages": sum(r["pages"] for r in ok),
            "blocks": sum(r["blocks"] for r in ok),
            "kinds": {k: kinds[k] for k in KINDS},
            "pages_without_header": sum(r["pages_without_header"] for r in ok),
            "no_outline": [r["pid"] for r in ok if r["outline_entries"] == 0],
            "no_text": [r["pid"] for r in ok if r["text_characters"] == 0],
            "no_references": [r["pid"] for r in ok if not r["kinds"].get("reference")],
            "no_abstract": [r["pid"] for r in ok if not r["kinds"].get("front_matter")],
            "characters_lost": {r["pid"]: r["characters_lost"] for r in ok if r["characters_lost"]},
            "errors": [r["pid"] for r in ys if "error" in r],
        }
    return {"papers": len(rows), "per_year": per_year}


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract every paper's text in reading order.")
    ap.add_argument("--year", choices=config.YEARS, help="one year only (default: all)")
    ap.add_argument("--force", action="store_true", help="redo papers that already have an output file")
    args = ap.parse_args()

    config.require_corpus()
    pymupdf.TOOLS.mupdf_display_errors(False)    # MuPDF's warnings about odd files; real failures are caught below
    rows = []
    for year in ((args.year,) if args.year else config.YEARS):
        out_dir = TEXT_DIR / year
        out_dir.mkdir(parents=True, exist_ok=True)
        pdfs = sorted(config.corpus_year_dir(year).glob("*.pdf"))
        t0 = time.time()
        for i, pdf in enumerate(pdfs, 1):
            out = out_dir / f"{pdf.stem}.json"
            try:
                if out.exists() and not args.force:
                    record = json.loads(out.read_text(encoding="utf-8"))
                else:
                    record = extract(pdf, year)
                    out.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
                rows.append(summary_row(record))
            except Exception as e:  # noqa: BLE001 - a paper we cannot read is a finding
                rows.append({"pid": pdf.stem, "year": year,
                             "error": type(e).__name__ + ": " + str(e)[:120]})
            if i % 200 == 0 or i == len(pdfs):
                print(f"  {year}: {i}/{len(pdfs)}  ({time.time() - t0:.0f}s)", flush=True)

    summary = summarize(rows)
    # MuPDF cuts a page into blocks differently from one version to the next,
    # so the version is part of the result. requirements.txt pins it.
    summary = {"papers": summary["papers"], "pymupdf_version": pymupdf.__version__,
               "per_year": summary["per_year"]}
    suffix = f"_{args.year}" if args.year else ""
    with open(config.OUTPUT / f"text_summary{suffix}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    print()
    print(f"{'year':<6}{'papers':>8}{'pages':>8}{'no header':>11}{'blocks':>9}{'no outline':>12}"
          f"{'chars lost':>12}{'errors':>8}")
    failed = False
    for year, s in summary["per_year"].items():
        print(f"{year:<6}{s['papers']:>8}{s['pages']:>8}{s['pages_without_header']:>11}{s['blocks']:>9}{len(s['no_outline']):>12}"
              f"{len(s['characters_lost']):>12}{len(s['errors']):>8}")
        failed |= bool(s["errors"] or s["no_text"])
    for label in ("no_text", "errors"):
        pids = [p for s in summary["per_year"].values() for p in s[label]]
        if pids:
            print(f"\n{label}: {len(pids)}")
            for p in pids:
                print("  ", p)
    print(f"\n-> {TEXT_DIR}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
