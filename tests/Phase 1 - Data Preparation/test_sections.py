"""Unit tests for module 3. No corpus and no PDFs: the papers are built here
as lists of module 2 blocks.

    py -m pytest tests -q
"""
import sections


def block(text, kind="text", page=1):
    return {"page": page, "kind": kind, "text": text}


def paper(blocks, outline):
    return {"pid": "p", "year": "2024", "blocks": blocks, "outline": outline}


PLAIN = paper(
    [block("A Title", "front_matter"),
     block("ABSTRACT ", "heading"), block("We study surveys."),
     block("CCS CONCEPTS ", "heading"), block("• Human-centered computing"),
     block("KEYWORDS\nsurveys, crowdsourcing"),
     block("1 INTRODUCTION ", "heading", 2), block("Surveys are common.", page=2),
     block("2 METHOD \n2.1 Participants ", "heading", 2), block("We recruited 200 people.", page=2),
     block("Figure 1: A chart.", "caption", 2),
     block("2.2 Procedure ", "heading", 3), block("They answered online.", page=3),
     block("REFERENCES ", "heading", 4), block("[1] A. Author. 2020.", "reference", 4),
     block("A QUESTIONNAIRE ", "heading", 5), block("Q1. How old are you?", page=5)],
    [[1, "Abstract", 1], [1, "1 Introduction", 2], [1, "2 Method", 2], [2, "2.1 Participants", 2],
     [2, "2.2 Procedure", 3], [1, "References", 4], [1, "A Questionnaire", 5]])


def by_title(result):
    return {s["title"]: s for s in result["sections"]}


def test_the_sections_tile_the_paper():
    result = sections.build(PLAIN)
    cut = result["sections"]
    assert cut[0]["start"] == [0, 0] and cut[-1]["end"] == [len(PLAIN["blocks"]), 0]
    assert all(a["end"] == b["start"] for a, b in zip(cut, cut[1:]))
    assert result["unanchored"] == []


def test_a_section_reads_back_its_own_text_and_nothing_else():
    cut = by_title(sections.build(PLAIN))
    blocks = PLAIN["blocks"]
    assert sections.section_text(blocks, cut["2.1 Participants"]) == "We recruited 200 people."
    assert sections.section_text(blocks, cut["2.1 Participants"], kinds=("text", "caption")).endswith("A chart.")
    assert sections.section_text(blocks, cut["2 Method"]) == ""       # its text is all in its subsections
    assert sections.section_text(blocks, cut["Abstract"]) == "We study surveys."


def test_two_headings_printed_in_one_block_are_two_sections():
    cut = by_title(sections.build(PLAIN))
    assert cut["2 Method"]["start"] == [8, 0] and cut["2.1 Participants"]["start"] == [8, 10]
    assert cut["2.1 Participants"]["parent"] == sections.build(PLAIN)["sections"].index(cut["2 Method"])


def test_headings_the_outline_leaves_out_are_added():
    cut = by_title(sections.build(PLAIN))
    assert cut["CCS Concepts"]["anchor"] == "heading_block"
    assert cut["Keywords"]["anchor"] == "in_text"
    assert sections.section_text(PLAIN["blocks"], cut["Keywords"]).strip() == "surveys, crowdsourcing"


def test_roles_come_from_titles_and_from_what_follows_the_references():
    cut = by_title(sections.build(PLAIN))
    assert [cut[t]["role"] for t in ("", "Abstract", "CCS Concepts", "Keywords", "1 Introduction",
                                     "2.2 Procedure", "References", "A Questionnaire")] == \
        ["front", "abstract", "ccs", "keywords", "body", "body", "references", "appendix"]


def test_a_heading_at_the_end_of_a_paragraph_block_is_found():
    blocks = [block("ABSTRACT ", "heading"), block("Short."),
              block("1 INTRODUCTION ", "heading"), block("First.\n2 Related Work\nSecond part."),
              block("3 METHOD ", "heading"), block("Third.")]
    result = sections.build(paper(blocks, [[1, "Abstract", 1], [1, "1 Introduction", 1],
                                           [1, "2 Related Work", 1], [1, "3 Method", 1]]))
    cut = by_title(result)
    assert cut["2 Related Work"]["anchor"] == "in_text"
    assert sections.section_text(blocks, cut["1 Introduction"]) == "First.\n"
    assert sections.section_text(blocks, cut["2 Related Work"]).strip() == "Second part."


def test_a_title_that_differs_by_a_few_characters_or_runs_over_two_blocks_is_found():
    blocks = [block("1 INTRODUCTION ", "heading"), block("Text."),
              block("2 Understanding Professionals Performing ", "heading"), block("Data Analysis ", "heading"),
              block("More."), block("Appendix A Survey Questions ", "heading"), block("Q1.")]
    outline = [[1, "1 Introduction", 1], [1, "2 Understanding blackProfessionals Performing Data Analysis", 1],
               [1, "A Survey Questions", 1]]
    result = sections.build(paper(blocks, outline))
    assert result["unanchored"] == []
    assert [s["anchor"] for s in result["sections"][1:]] == ["heading", "fuzzy", "heading"]
    assert sections.section_text(blocks, by_title(result)["2 Understanding blackProfessionals Performing Data Analysis"]) == "More."


def test_a_repeated_title_is_matched_in_order():
    blocks = [block("1 STUDY 1 ", "heading"), block("3.1 Results ", "heading"), block("First results."),
              block("2 STUDY 2 ", "heading"), block("3.1 Results ", "heading"), block("Second results.")]
    outline = [[1, "1 Study 1", 1], [2, "Results", 1], [1, "2 Study 2", 1], [2, "Results", 1]]
    cut = sections.build(paper(blocks, outline))["sections"]
    assert [sections.section_text(blocks, s) for s in cut if s["title"] == "Results"] == ["First results.", "Second results."]


def test_an_entry_that_is_not_on_the_page_is_reported_and_its_text_stays_put():
    blocks = [block("1 INTRODUCTION ", "heading"), block("Text."), block("2 METHOD ", "heading"),
              block("More."), block("3 RESULTS ", "heading"), block("Numbers.")]
    outline = [[1, "1 Introduction", 1], [1, "2 Method", 1], [2, "2.1 Missing Heading", 1], [1, "3 Results", 1]]
    result = sections.build(paper(blocks, outline))
    assert [u["title"] for u in result["unanchored"]] == ["2.1 Missing Heading"]
    assert sections.section_text(blocks, by_title(result)["2 Method"]) == "More."


def test_a_paper_with_no_usable_outline_is_cut_at_its_heading_blocks():
    result = sections.build(paper(PLAIN["blocks"], [[1, "ver4", 1], [2, "Binder1.pdf", -1]]))
    assert result["source"] == "headings" and result["unanchored"] == []
    cut = by_title(result)
    assert cut["2.1 Participants"]["level"] == 2 and cut["2 METHOD"]["level"] == 1
    assert cut["A QUESTIONNAIRE"]["role"] == "appendix"
    assert sections.section_text(PLAIN["blocks"], cut["2.2 Procedure"]) == "They answered online."


def test_summary_lists_the_papers_that_need_a_look():
    rows = [sections.summary_row(sections.build(PLAIN)),
            sections.summary_row(sections.build(paper([block("Only text.")], []))),
            {"pid": "x", "year": "2024", "error": "boom"}]
    s = sections.summarize(rows)["per_year"]["2024"]
    assert s["papers"] == 3 and s["errors"] == ["x"]
    assert s["no_abstract"] == ["p"] and s["no_references"] == ["p"] and s["from_headings"] == ["p"]
