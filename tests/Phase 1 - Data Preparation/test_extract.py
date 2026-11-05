"""Unit tests for module 2. These run without the corpus: the pages they read
are built here, with the text painted in the wrong order on purpose.

    py -m pytest tests -q
"""
import pymupdf

import extract

BODY = 8.9


def span(text, x0, y0, x1=None, size=BODY, bold=False):
    return {"text": text, "bbox": (x0, y0, x1 if x1 is not None else x0 + 5 * len(text), y0 + 9),
            "size": size, "flags": 16 if bold else 0, "font": "LinLibertineT"}


def block(text, page=2, column=1, y=100.0, kind="text", size=BODY, bold=False, marked=False, x0=None, x1=None):
    x0 = {0: 54, 1: 54, 2: 318}[column] if x0 is None else x0
    x1 = (558 if column == 0 else x0 + 241) if x1 is None else x1
    return {"page": page, "kind": kind, "column": column, "bbox": [x0, y, x1, y + 10],
            "size": size, "bold": bold, "text": text, "marked": marked}


PARAGRAPH = "A paragraph of running text that is long enough to count as one. " * 6


# ------------------------------------------------------------- lines and blocks

def test_lines_are_rebuilt_from_positions_not_from_paint_order():
    spans = [span("world", 60, 100), span("second", 10, 111), span("hello", 10, 100)]
    assert extract.block_text(spans) == "hello world\nsecond"


def test_a_superscript_stays_on_its_line():
    spans = [span("Zoom", 10, 100, 30), span("3", 30, 97.5, 33), span(" was used", 33, 100)]
    assert extract.block_text(spans) == "Zoom3 was used"


def test_no_space_is_added_where_one_is_already_there():
    spans = [span("left ", 10, 100, 35), span("right", 60, 100)]
    assert extract.block_text(spans) == "left right"


def test_a_block_holding_a_line_of_each_column_is_split():
    # the last line of the left column and of the right column, merged by MuPDF
    merged = [span("end of the left column", 54, 700, 296), span("end of the right column", 318, 700, 560)]
    parts = extract.split_at_gutter(merged, 306)
    assert [extract.block_text(p) for p in parts] == ["end of the left column", "end of the right column"]


def test_real_full_width_text_is_not_split():
    caption = [span("Figure 9: a caption that runs across the whole", 54, 240, 330),
               span(" page and ends on a short second line", 330, 240, 560),
               span("in the left half only.", 54, 251, 150)]
    assert extract.split_at_gutter(caption, 306) == [caption]
    one_side = [span("a paragraph in the left column", 54, 300, 296)]
    assert extract.split_at_gutter(one_side, 306) == [one_side]


def test_column_of():
    assert extract.column_of((54, 100, 558, 120), 612) == 0      # spans both columns
    assert extract.column_of((54, 100, 294, 120), 612) == 1
    assert extract.column_of((318, 100, 558, 120), 612) == 2


def test_style_of_reads_size_bold_and_footnote_mark():
    heading = [span("3 METHOD", 54, 100, size=10.9, bold=True)]
    assert extract.style_of(heading) == (10.9, True, False)
    footnote = [span("5", 54, 698, 57, size=5.0), span("For each model, the link function was chosen.", 57, 700, size=7.0)]
    assert extract.style_of(footnote) == (7.0, False, True)
    table_row = [span("5 Male 34 Designer", 54, 300, size=7.0)]
    assert extract.style_of(table_row) == (7.0, False, False)


# ------------------------------------------------------------------- the kinds

def test_position_gives_headers_and_page_numbers():
    blocks = [block("CHI '22, New Orleans", y=60.0), block("A Title", page=1, y=77.5),
              block("12", y=300), block("6", y=717), block("Figure 3: ...", y=717)]
    blocks[0]["bbox"][3] = 69.3
    extract.label_position(blocks)
    assert [b["kind"] for b in blocks] == ["header", "text", "text", "page_number", "text"]


def top_block(page, text, x0=72.0, x1=541.7, column=0):
    return {"page": page, "kind": "text", "column": column, "bbox": [x0, 75.2, x1, 84.5], "text": text}


def test_a_header_printed_low_is_caught_because_it_repeats():
    even, odd = "CHI '26, April 13-17, 2026, Barcelona, Spain", "A Long Paper Title That Repeats"
    blocks = [top_block(p, even if p % 2 == 0 else odd) for p in range(2, 9)]
    blocks.append(block("Body text.", y=110))
    assert extract.label_repeated_headers(blocks) == 7
    assert [b["kind"] for b in blocks] == ["header"] * 7 + ["text"]


def test_text_at_the_top_of_a_page_is_not_a_header_unless_it_repeats():
    blocks = [top_block(2, "A paragraph that happens to start a page."),
              top_block(3, "Another paragraph that starts a page."),
              top_block(4, "Yes"), top_block(5, "Yes"), top_block(6, "Yes")]     # repeated, but a table cell
    assert extract.label_repeated_headers(blocks) == 0
    assert all(b["kind"] == "text" for b in blocks)


def test_both_halves_of_a_low_header_are_caught():
    blocks = []
    for page in range(2, 6):
        blocks.append(top_block(page, "CHI '26, April 13-17, 2026, Barcelona, Spain", 72, 300, column=1))
        blocks.append(top_block(page, "Shin et al.", 500, 541, column=2))
        blocks.append(block(f"Body text of page {page}.", page=page, y=100))
    assert extract.label_repeated_headers(blocks) == 8
    assert [b["kind"] for b in blocks] == ["header", "header", "text"] * 4


def test_type_gives_headings_captions_and_the_reference_list():
    blocks = [block("3 METHOD", size=10.9, bold=True), block(PARAGRAPH),
              block("Figure 2: The study setup.", bold=True),
              block("Male 34 Designer", size=7.0),                           # small, before the references
              block("REFERENCES", size=10.9, bold=True),
              block("[1] A. Author. 2020. A paper.", size=7.0), block("[2] B. Author. 2021.", size=7.0),
              block("A APPENDIX", size=10.9, bold=True), block("Q1 Yes No", size=7.0)]
    extract.label_type(blocks, BODY)
    assert [b["kind"] for b in blocks] == ["heading", "text", "caption", "small_text", "heading",
                                           "reference", "reference", "heading", "small_text"]


def test_front_matter_is_page_one_above_the_abstract():
    blocks = [block("A Title", page=1, column=0, y=80, size=17.2, bold=True, kind="heading"),
              block("An Author", page=1, y=130, size=12.0),
              block("ABSTRACT", page=1, y=213, size=10.9, bold=True, kind="heading"),
              block(PARAGRAPH, page=1, y=228)]
    extract.label_front_matter(blocks)
    assert [b["kind"] for b in blocks] == ["front_matter", "front_matter", "heading", "text"]


def test_small_type_at_the_foot_of_a_column_is_a_footnote_if_it_starts_with_a_mark():
    page = [block(PARAGRAPH, y=300),
            block("5 For each model, the link function was chosen.", y=675, size=7.0, kind="small_text", marked=True),
            block("and tested on the outcome.", y=690, size=7.0, kind="small_text"),
            block("Male 34", column=2, y=100, size=7.0, kind="small_text"),      # a table at the top
            block(PARAGRAPH, column=2, y=300)]
    extract.label_column_feet(page)
    assert [b["kind"] for b in page] == ["text", "footnote", "footnote", "small_text", "text"]


def test_a_table_at_the_foot_of_a_column_is_not_a_footnote():
    page = [block(PARAGRAPH, y=300), block("P1 Male 34", y=675, size=7.0, kind="small_text"),
            block("P2 Female 29", y=690, size=7.0, kind="small_text")]
    extract.label_column_feet(page)
    assert [b["kind"] for b in page] == ["text", "small_text", "small_text"]


def test_on_page_one_the_small_print_is_a_notice():
    page = [block(PARAGRAPH, page=1, y=300),
            block("ACM Reference Format: A. Author. 2022. A Title.", page=1, y=480, size=8.0),
            block(PARAGRAPH, page=1, y=560),
            block("Permission to make digital or hard copies ...", page=1, y=620, size=7.0, kind="small_text"),
            block("CHI '22, New Orleans, LA, USA", page=1, y=677, size=7.0, kind="small_text")]
    extract.label_column_feet(page)
    assert [b["kind"] for b in page] == ["text", "notice", "text", "notice", "notice"]


# ------------------------------------------------------------------ the order

def at(name, column, y, kind="text"):
    return block(name, column=column, y=y, kind=kind)


def test_reading_order_left_column_then_right_column():
    page = [at("right top", 2, 100), at("left bottom", 1, 300), at("left top", 1, 100)]
    assert [b["text"] for b in extract.reading_order(page)] == ["left top", "left bottom", "right top"]


def test_a_full_width_block_is_read_after_the_columns_above_it():
    page = [at("below right", 2, 420), at("wide caption", 0, 400), at("above right", 2, 100),
            at("title", 0, 60), at("above left", 1, 100), at("below left", 1, 420)]
    assert [b["text"] for b in extract.reading_order(page)] == [
        "title", "above left", "above right", "wide caption", "below left", "below right"]


def test_a_table_as_wide_as_the_page_is_read_whole_and_row_by_row():
    # 10.1145/3544548.3580794 p.7: the right half of the table used to be
    # read after the running text under its left half
    edges = {1: (54, 241), 2: (318, 241)}
    page = [at("Table 1: Key messages.", 0, 462, kind="caption"),
            block("Strengths", y=515, x0=64, x1=110, bold=True),
            block("AI is superior ...", column=2, y=515, x0=385, x1=615),
            block("Humans are superior ...", y=516, x0=157, x1=300),
            block("Weaknesses", y=548, x0=64, x1=120, bold=True),
            block("left: " + PARAGRAPH, y=600), block("right: " + PARAGRAPH, column=2, y=600)]
    extract.label_wide_tables(page, edges)
    ordered = extract.reading_order(page)
    assert [b["kind"] for b in ordered] == ["caption", "table", "table", "table", "table", "text", "text"]
    assert [b["text"][:9] for b in ordered[1:5]] == ["Strengths", "Humans ar", "AI is sup", "Weaknesse"]
    assert ordered[5]["text"].startswith("left") and ordered[6]["text"].startswith("right")


def test_the_last_line_of_a_paragraph_under_a_table_is_not_a_cell():
    # 10.1145/3772318.3791606 p.14: "and improvements, ... experience." sits under the table
    edges = {1: (54, 241), 2: (318, 241)}
    page = [at("Table 9: Comparison.", 0, 240, kind="caption"),
            block("Use large-scale review data", column=2, y=470, x0=490, x1=615),
            block("and improvements, ultimately enhancing the overall user experience.", column=2, y=540)]
    extract.label_wide_tables(page, edges)
    assert [b["kind"] for b in page] == ["caption", "table", "text"]


def test_references_set_at_body_size_or_under_a_plain_heading_are_still_references():
    blocks = [block("7 REFERENCES", size=10.9, bold=True), block("[1] A. Author. 2020. A paper."),
              block("A APPENDIX", size=10.9, bold=True), block(PARAGRAPH)]
    extract.label_type(blocks, 9.0)
    assert [b["kind"] for b in blocks] == ["heading", "reference", "heading", "text"]
    merged = [block("References\nReferences marked with a star are in the review."), block("[1] A. Author.", size=7.0)]
    extract.label_type(merged, 9.0)
    assert [b["kind"] for b in merged] == ["reference", "reference"]


def test_front_matter_without_an_abstract_heading_ends_at_the_first_long_paragraph():
    blocks = [block("A Title", page=1, column=0, y=80, size=17.2, bold=True, kind="heading"),
              block("An Author", page=1, y=130, size=12.0), block(PARAGRAPH, page=1, y=228)]
    extract.label_front_matter(blocks)
    assert [b["kind"] for b in blocks] == ["front_matter", "front_matter", "text"]


def test_a_figure_caption_does_not_swallow_the_text_under_it():
    edges = {1: (54, 241), 2: (318, 241)}
    page = [at("Figure 2: The setup.", 0, 300, kind="caption"), block(PARAGRAPH, y=330)]
    extract.label_wide_tables(page, edges)
    assert [b["kind"] for b in page] == ["caption", "text"]


# ------------------------------------------------------------------ one paper

def test_extract_reads_a_two_column_page_and_loses_nothing(tmp_path):
    path = tmp_path / "10_1145_1_2.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)          # page 1 is front matter; the test reads page 2
    page = doc.new_page(width=612, height=792)
    # painted out of order: right column first, then the header, the title, the left column
    page.insert_text((320, 200), "right column")
    page.insert_text((54, 68), "running header")
    page.insert_textbox(pymupdf.Rect(54, 80, 558, 110), "A Title Across Both Columns " * 3)
    page.insert_text((54, 200), "left column")
    doc.set_toc([[1, "Introduction", 2]])
    doc.save(str(path))
    doc.close()

    record = extract.extract(path, "2022")
    assert record["pages"] == 2
    assert record["characters_lost"] == 0
    assert record["outline"] == [[1, "Introduction", 2]]
    assert [(b["kind"], b["column"]) for b in record["blocks"]] == [
        ("header", 1), ("text", 0), ("text", 1), ("text", 2)]
    assert record["blocks"][2]["text"] == "left column"
    assert record["blocks"][3]["text"] == "right column"
    assert set(record["blocks"][0]) == {"page", "kind", "column", "bbox", "size", "bold", "text"}


def test_summary_lists_the_papers_that_need_a_look():
    rows = [
        {"pid": "a", "year": "2022", "pages": 10, "pages_without_header": 0, "blocks": 90,
         "kinds": {"text": 60, "reference": 20, "front_matter": 4, "header": 6},
         "text_characters": 5000, "body_size": 8.9, "outline_entries": 20, "characters_lost": 0},
        {"pid": "b", "year": "2022", "pages": 12, "pages_without_header": 2, "blocks": 80,
         "kinds": {"text": 80}, "text_characters": 4000, "body_size": 8.9,
         "outline_entries": 0, "characters_lost": 3},
        {"pid": "c", "year": "2022", "error": "boom"},
    ]
    s = extract.summarize(rows)["per_year"]["2022"]
    assert (s["papers"], s["pages"], s["blocks"]) == (3, 22, 170)
    assert s["kinds"]["text"] == 140 and s["kinds"]["reference"] == 20
    assert s["no_outline"] == s["no_references"] == s["no_abstract"] == ["b"]
    assert s["pages_without_header"] == 2
    assert s["characters_lost"] == {"b": 3}
    assert s["errors"] == ["c"]


def test_a_sentence_that_begins_with_figure_is_not_a_caption():
    blocks = [block("Figure 5 shows an example of the annotation interface."),
              block("Figure 5: The annotation interface."), block("Table 2. Participants."),
              block("Figure 5 The annotation interface", bold=True)]
    extract.label_type(blocks, BODY)
    assert [b["kind"] for b in blocks] == ["text", "caption", "caption", "caption"]


def test_type_a_little_smaller_or_larger_than_the_running_text_is_not_running_text():
    # most tables are set one point smaller, and figure text can be anything
    blocks = [block(PARAGRAPH, size=8.9), block(PARAGRAPH, size=9.1),
              block("Theme Venue Research method", size=8.0), block("Persona 2: As a professor ...", size=9.6)]
    extract.label_type(blocks, 9.0)
    assert [b["kind"] for b in blocks] == ["text", "text", "small_text", "large_text"]


def test_a_table_inside_a_column_is_found_under_its_caption():
    page = [block(PARAGRAPH, y=100),
            block("Table 4: Effect sizes.", y=130, kind="caption", bold=True),
            block("Measure Small Medium Large", y=145),
            block("Cohen's d 0.2 0.5 0.8", y=157),
            block(PARAGRAPH, y=190)]
    extract.label_column_tables(page, {1: (54, 241)})
    assert [b["kind"] for b in page] == ["text", "caption", "table", "table", "text"]


def test_a_caption_printed_under_its_table_finds_the_cells_above_it():
    page = [block(PARAGRAPH, y=100),
            block("Keyword area Search terms", y=130),
            block("UGC keywords crowdsourcing", y=142, x0=70),
            block("Table 1: List of keywords.", y=158, kind="caption", bold=True),
            block(PARAGRAPH, y=200)]
    extract.label_column_tables(page, {1: (54, 241)})
    assert [b["kind"] for b in page] == ["text", "table", "table", "caption", "text"]


def test_a_table_drawn_as_a_picture_takes_nothing_from_the_text_around_it():
    page = [block(PARAGRAPH, y=100),
            block("Table 2: A table that is an image.", y=130, kind="caption", bold=True),
            block("the end of a sentence.", y=260),
            block("Table 3: The other column.", column=2, y=130, kind="caption", bold=True),
            block("Cell at body size", column=2, y=143)]
    extract.label_column_tables(page, {1: (54, 241), 2: (318, 241)})
    assert [b["kind"] for b in page] == ["text", "caption", "text", "caption", "table"]
