"""Unit tests for module 1. These run without the corpus.

The table snippets are real rows copied from CHI papers, so each test pins
one way the defect is written in the wild.

    py -m pytest tests -q
"""
import ligatures as lig


def test_glyph_letters_reads_ligature_names():
    assert lig.glyph_letters("f_i") == "fi"
    assert lig.glyph_letters("f_f_i") == "ffi"
    assert lig.glyph_letters("T_h") == "Th"
    assert lig.glyph_letters("ffl") == "ffl"
    assert lig.glyph_letters("uniFB01") == "fi"
    assert lig.glyph_letters("f_f.short") == "ff"


def test_glyph_letters_ignores_ordinary_names():
    for name in ("a", "f", "space", "quoteright", "uni0041", "underscore", "f_longname"):
        assert lig.glyph_letters(name) is None


def test_parse_differences_counts_codes_from_each_number():
    enc = "<< /Type /Encoding /Differences [ 27 /f_i /f_f_i 39 /quoteright ] >>"
    assert lig.parse_differences(enc) == {27: "f_i", 28: "f_f_i", 39: "quoteright"}
    assert lig.parse_differences("<< /BaseEncoding /WinAnsiEncoding >>") == {}


# 10.1145/3491102.3517436, font LinLibertineT: one row per code
BFCHAR_TABLE = """4 beginbfchar
<1B> <0066>
<1C> <0066>
<41> <0041>
<1E> <0066>
endbfchar"""

# 10.1145/3544548.3580745, font LinLibertineT: the same defect written as ranges
BFRANGE_TABLE = """3 beginbfrange
<15><15><015b>
<1b><1b><0066>
<1c><1c><0066>
endbfrange"""

TRUTH = {0x1B: "fi", 0x1C: "ffi", 0x1E: "fl"}


def test_fix_cmap_rewrites_wrong_bfchar_rows_only():
    new, n = lig.fix_cmap(BFCHAR_TABLE, TRUTH)
    assert n == 3
    assert "<1B> <00660069>" in new          # fi
    assert "<1C> <006600660069>" in new      # ffi
    assert "<1E> <0066006c>" in new          # fl
    assert "<41> <0041>" in new              # an ordinary letter is untouched
    assert lig.read_cmap(new, TRUTH) == TRUTH


def test_fix_cmap_rewrites_single_code_ranges():
    new, n = lig.fix_cmap(BFRANGE_TABLE, TRUTH)
    assert n == 2
    assert "<1b><1b><00660069>" in new
    assert "<15><15><015b>" in new
    assert lig.read_cmap(new, [0x1B, 0x1C]) == {0x1B: "fi", 0x1C: "ffi"}


def test_fix_cmap_spells_out_a_range_that_spans_several_codes():
    table = "1 beginbfrange\n<1a> <1c> <0065>\nendbfrange"      # 1a->e, 1b->f, 1c->g
    new, n = lig.fix_cmap(table, {0x1B: "fi"})
    assert n == 1
    assert lig.read_cmap(new, [0x1A, 0x1B, 0x1C]) == {0x1A: "e", 0x1B: "fi", 0x1C: "g"}


def test_fix_cmap_leaves_a_healthy_table_byte_identical():
    healthy = "2 beginbfchar\n<1B> <00660069>\n<41> <0041>\nendbfchar\n1 beginbfrange\n<61><7a><0061>\nendbfrange"
    assert lig.fix_cmap(healthy, TRUTH) == (healthy, 0)


def test_status_names_the_four_cases():
    assert lig._status("fi", "fi") == "ok"
    assert lig._status("f", "fi") == "wrong"
    assert lig._status("ﬁ", "fi") == "ligature_char"
    assert lig._status(None, "fi") == "missing"


def test_summary_counts_papers_that_needed_and_kept_damage():
    rows = [
        {"pid": "a", "year": "2022", "before": {"wrong": 4}, "rewritten": 4, "after": {"ok": 4}},
        {"pid": "b", "year": "2022", "before": {"ok": 4}, "rewritten": 0, "after": {"ok": 4}},
        {"pid": "c", "year": "2023", "before": {"wrong": 2}, "rewritten": 1, "after": {"ok": 1, "wrong": 1}},
    ]
    s = lig.summarize(rows)
    assert s["needed_repair"] == 2
    assert s["rows_rewritten"] == 5
    assert s["per_year"]["2022"]["not_fully_repaired"] == []
    assert s["per_year"]["2023"]["not_fully_repaired"] == ["c"]


def test_fix_cmap_changes_no_other_row():
    # the two ligature codes sit between ordinary rows, some with look-alike values
    table = "5 beginbfchar\n<0A> <02D9>\n<1A> <001B>\n<1B> <0066>\n<1C> <0066>\n<41> <0041>\nendbfchar"
    new, n = lig.fix_cmap(table, {0x1B: "fi", 0x1C: "ffi"})
    others = [0x0A, 0x1A, 0x41]
    assert n == 2
    assert lig.read_cmap(new, others) == lig.read_cmap(table, others) == {0x0A: "\u02d9", 0x1A: "\x1b", 0x41: "A"}


def test_open_repaired_returns_a_readable_document(tmp_path):
    import pymupdf
    path = tmp_path / "plain.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "a first finding")
    doc.save(str(path))
    doc.close()
    doc, report = lig.open_repaired(path)
    assert report["rewritten"] == 0
    assert "a first finding" in doc[0].get_text()
    doc.close()
