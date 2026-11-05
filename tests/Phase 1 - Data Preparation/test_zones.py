"""Unit tests for module 4. The papers are lists of module 3 sections built
here; only the fields the rules read are filled in.

    py -m pytest tests -q
"""
import zones


def paper(*rows):
    """rows: (level, title) or (level, title, role). Parents are worked out
    the way module 3 does it: the nearest section above with a lower level."""
    sections = [{"level": 0, "title": "", "role": "front", "parent": None, "text_chars": 0}]
    for row in rows:
        level, title, role = (*row, "body")[:3]
        parent = next((i for i in range(len(sections) - 1, 0, -1) if sections[i]["level"] < level), None)
        sections.append({"level": level, "title": title, "role": role, "parent": parent, "text_chars": 100})
    return {"pid": "p", "year": "2024", "sections": sections}


def labels(*rows):
    return {z["title"]: (z["label"], z["rule"]) for z in zones.build(paper(*rows))["zones"]}


def test_normal_drops_the_section_number_and_generalises_other_numbers():
    assert zones.normal("4.1 Methods") == "methods"
    assert zones.normal("A.2 Survey Items") == "survey items"
    assert zones.normal("5 Study 2: Results") == "study N: results"


def test_roles_outside_the_body_decide_on_their_own():
    got = labels((1, "Abstract", "abstract"), (1, "Keywords", "keywords"), (1, "References", "references"),
                 (1, "A Questionnaire", "appendix"))
    assert [got[t][0] for t in ("", "Abstract", "Keywords", "References", "A Questionnaire")] == \
        ["apparatus", "abstract", "apparatus", "apparatus", "appendix"]


def test_listed_titles_and_patterns():
    got = labels((1, "1 Introduction"), (1, "2 Related Work"), (1, "3 Method"), (1, "4 Online Survey of Users"),
                 (1, "5 Limitations"), (1, "6 Threats and Limitations of the Approach"), (1, "7 Discussion"),
                 (1, "8 Hardware Implementation"), (1, "9 Workshop"))
    assert got["1 Introduction"] == ("framing", "listed")
    assert got["2 Related Work"] == ("prior_work", "listed")
    assert got["3 Method"] == ("study", "listed")
    assert got["4 Online Survey of Users"] == ("study", "pattern")
    assert got["5 Limitations"] == ("limits", "listed")
    assert got["6 Threats and Limitations of the Approach"] == ("limits", "pattern")
    assert got["7 Discussion"] == ("other", "listed")
    assert got["8 Hardware Implementation"] == ("other", "system")
    assert got["9 Workshop"] == ("unclear", "listed")


def test_reference_inside_preference_is_not_prior_work():
    assert labels((1, "4 User Preference Survey"))["4 User Preference Survey"][0] == "study"


def test_a_section_with_study_subsections_is_a_study():
    got = labels((1, "4 Exploring Garden Sensors"), (2, "4.1 Participants"), (2, "4.2 Our Garden"))
    assert got["4 Exploring Garden Sensors"] == ("study", "subsection")
    assert got["4.2 Our Garden"] == ("study", "parent")


def test_an_unknown_subsection_takes_its_parents_label():
    got = labels((1, "2 Related Work"), (2, "2.1 Smart Cities"), (1, "3 The Garden"), (2, "3.1 Soil"))
    assert got["2.1 Smart Cities"] == ("prior_work", "parent")
    assert got["3 The Garden"] == ("unclear", "none")
    assert got["3.1 Soil"] == ("unclear", "parent")


def test_inside_a_study_everything_is_read_except_related_work():
    got = labels((1, "5 Study 1"), (2, "5.1 Discussion"), (2, "5.2 Background"), (2, "5.3 Related Work"))
    assert got["5.1 Discussion"] == ("study", "listed under study")
    assert got["5.2 Background"] == ("study", "listed under study")
    assert got["5.3 Related Work"] == ("prior_work", "listed")


def test_inside_an_unknown_section_a_discussion_is_read_too():
    assert labels((1, "3 The Garden"), (2, "3.1 Discussion"))["3.1 Discussion"] == ("unclear", "listed under study")
    assert labels((1, "3 Workshop"), (2, "3.1 Discussion"))["3.1 Discussion"] == ("other", "listed")


def test_read_follows_the_label_and_the_study_number_is_carried_down():
    result = zones.build(paper((1, "1 Introduction"), (1, "4 Experiment 2"), (2, "4.1 Procedure"), (1, "5 The Garden")))
    by = {z["title"]: z for z in result["zones"]}
    assert [by[t]["read"] for t in ("1 Introduction", "4 Experiment 2", "4.1 Procedure", "5 The Garden")] == \
        [False, True, True, True]
    assert by["4.1 Procedure"]["study"] == "Experiment 2" and by["5 The Garden"]["study"] is None


def test_summary_lists_unknown_titles_and_papers_without_a_study_section():
    rows = [zones.summary_row(zones.build(paper((1, "1 Introduction"), (1, "2 The Garden")))),
            zones.summary_row(zones.build(paper((1, "3 Method")))),
            {"pid": "x", "year": "2024", "error": "boom"}]
    s = zones.summarize(rows)
    year = s["per_year"]["2024"]
    assert year["papers"] == 3 and year["errors"] == ["x"] and year["no_study_section"] == ["p"]
    assert year["rules"]["none"] == 1 and s["unknown_titles_most_common"] == {"the garden": 1}
    assert year["read_share"] == 0.6667
