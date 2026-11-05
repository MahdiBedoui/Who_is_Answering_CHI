"""Unit tests for module 5. No corpus: the papers are built here.

    py -m pytest tests -q
"""
import collections

import sentences

NO_WORDS = collections.Counter()


def words(*known):
    return collections.Counter(known)


# ------------------------------------------------------------------ cleaning

def test_a_soft_hyphen_at_a_line_end_is_the_typesetters():
    assert sentences.one_line("the evalua­\ntion was run", NO_WORDS, True) == "the evaluation was run"


def test_a_visible_hyphen_is_kept_when_the_paper_prints_the_compound():
    assert sentences.one_line("a semi-\nstructured interview", words("semi-structured"), False) == \
        "a semi-structured interview"


def test_a_visible_hyphen_is_dropped_when_the_paper_prints_the_word_whole():
    assert sentences.one_line("several it-\nerations later", words("iterations"), False) == "several iterations later"


def test_an_unknown_word_follows_how_the_paper_marks_its_line_breaks():
    assert sentences.one_line("cost-\nefficient tools", NO_WORDS, True) == "cost-efficient tools"      # soft hyphens elsewhere
    assert sentences.one_line("partici-\npants came", NO_WORDS, False) == "participants came"       # none: "-" is the line break
    assert sentences.one_line("anti-\nAsian hate", NO_WORDS, False) == "anti-Asian hate"            # a capital: a compound


def test_vocabulary_holds_words_printed_whole_and_not_a_word_broken_over_two_lines():
    blocks = [{"kind": "text", "text": "an on-\nline survey and an online form"}]
    known = sentences.vocabulary(blocks)
    assert known["online"] == 1 and "on-line" not in known


# ---------------------------------------------------------------- paragraphs

def items(*texts):
    return [(i, {"page": 1, "kind": "text"}, t) for i, t in enumerate(texts)]


FULL = "We recruited two hundred participants through Prolific and paid\nthem at the rate the platform recommends for a study of"
ENDED = "We recruited two hundred participants through Prolific and paid\nthem well. - P7"


def test_a_block_cut_mid_sentence_takes_the_next_block():
    got = sentences.paragraphs(items(FULL, "this length. Each session took ten minutes.", "A new paragraph starts here."))
    assert [len(p["parts"]) for p in got] == [2, 1]


def test_a_continuation_that_starts_with_a_capital_needs_a_full_last_line():
    assert len(sentences.paragraphs(items(FULL, "Western Canada. More text."))[0]["parts"]) == 2
    assert len(sentences.paragraphs(items(ENDED + " and so", "Participants also said more."))[0]["parts"]) == 1


def test_a_stray_table_cell_between_the_halves_is_stepped_over():
    got = sentences.paragraphs(items(FULL, "Measure Small Medium Large", "this length. Then it ended."))
    assert got[0]["parts"] == [FULL, "this length. Then it ended."]
    assert got[1]["parts"] == ["Measure Small Medium Large"]


def test_a_list_item_or_a_numbered_heading_is_not_a_continuation():
    assert len(sentences.paragraphs(items(FULL, "• first item of a list"))[0]["parts"]) == 1
    assert len(sentences.paragraphs(items(FULL, "4.1.2 Recruitment. We posted the study."))[0]["parts"]) == 1


def test_a_finished_paragraph_takes_nothing():
    assert [len(p["parts"]) for p in sentences.paragraphs(items("A whole sentence that is long enough to count here.", "another one."))] == [1, 1]


# ----------------------------------------------------------------- sentences

def test_sentences_are_cut_at_full_stops_followed_by_a_capital():
    assert sentences.split_sentences("We ran a survey. It had 20 items! Did it work? Yes.") == \
        ["We ran a survey.", "It had 20 items!", "Did it work?", "Yes."]


def test_abbreviations_initials_and_list_numbers_do_not_end_a_sentence():
    for text in ("Smith et al. [12] found this, cf. Jones (2020) and Fig. 3 Left.",
                 "We followed J. Smith and e.g. Prolific, i.e. A crowd platform.",
                 "1. First we asked about age."):
        assert sentences.split_sentences(text) == [text]


def test_a_footnote_mark_after_the_full_stop_stays_with_its_sentence():
    assert sentences.split_sentences("They were paid ($2.30 US Dollar).9 In total 204 took part.") == \
        ["They were paid ($2.30 US Dollar).9", "In total 204 took part."]
    assert sentences.split_sentences("The mean was 0.5 12 people left.") == ["The mean was 0.5 12 people left."]


def test_a_quotation_ends_with_its_closing_mark():
    assert sentences.split_sentences("P3 said “I liked it.” Others agreed.") == ["P3 said “I liked it.”", "Others agreed."]


# --------------------------------------------------------------------- build

def test_build_joins_across_a_footnote_keeps_sections_apart_and_skips_apparatus():
    blocks = [
        {"page": 1, "kind": "front_matter", "text": "A Title"},
        {"page": 1, "kind": "heading", "text": "1 METHOD "},
        {"page": 1, "kind": "text", "text": FULL},
        {"page": 1, "kind": "footnote", "text": "3 https://www.prolific.co"},
        {"page": 2, "kind": "caption", "text": "Figure 1: The survey page. It has two parts."},
        {"page": 2, "kind": "text", "text": "this length. Each ses­\nsion took ten minutes and ended on an open"},
        {"page": 2, "kind": "heading", "text": "2 RESULTS "},
        {"page": 2, "kind": "text", "text": "question about the task was not asked."},
        {"page": 3, "kind": "reference", "text": "[1] A. Author. 2020."},
    ]
    sectioned = {"sections": [{"body": [0, 0], "end": [1, 0]}, {"body": [1, 9], "end": [6, 0]},
                              {"body": [6, 10], "end": [9, 0]}]}
    zone = lambda title, label: {"title": title, "level": 1, "label": label, "read": label == "study", "study": None}  # noqa: E731
    zoned = {"zones": [zone("", "apparatus"), zone("1 Method", "study"), zone("2 Results", "study")]}
    result = sentences.build({"pid": "p", "year": "2024", "blocks": blocks}, sectioned, zoned)
    got = [(s["section"], s["kind"], s["joined"], s["text"]) for s in result["sentences"]]
    assert got == [
        (1, "text", True, "We recruited two hundred participants through Prolific and paid them at the rate the "
                          "platform recommends for a study of this length."),
        (1, "text", False, "Each session took ten minutes and ended on an open"),
        (1, "footnote", False, "https://www.prolific.co"),
        (1, "caption", False, "Figure 1: The survey page."),
        (1, "caption", False, "It has two parts."),
        (2, "text", False, "question about the task was not asked."),
    ]
    row = sentences.summary_row(result)
    assert row["sentences"] == {"text": 3, "footnote": 1, "caption": 2} and row["joined"] == 1 and row["open_ended"] == 1
