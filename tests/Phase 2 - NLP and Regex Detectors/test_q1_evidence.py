"""Unit tests for module 6. Papers are module 5 sentence files built here;
only the fields the module reads are filled in. Several sentences are the
annotators' own quotes from round 1.

    py -m pytest tests -q
"""
import q1_evidence as q


def paper(*sections):
    """sections: (label, study, [sentences])"""
    secs, sents = [], []
    for label, study, texts in sections:
        secs.append({"title": "", "level": 1, "label": label, "read": True, "study": study})
        sents += [{"text": t, "section": len(secs) - 1, "kind": "text", "page": 1, "block": 0, "joined": False}
                  for t in texts]
    return {"pid": "p", "year": "2024", "sections": secs, "sentences": sents}


def route(*sections, **kw):
    return q.build(paper(*sections), **kw)["route"]


def cues(text):
    return {h["cue"] for h in q.find_hits(text)}


def test_platform_names_that_are_also_words():
    assert "crowd_platform" in cues("We recruited 200 participants on Prolific.")
    assert "crowd_platform" in cues("Participants were recruited via Prolific Academic and paid $3.")
    assert "crowd_platform" not in cues("Prolific authors in this area have argued otherwise.")
    assert "crowd_platform" not in cues("He is a prolific writer.")
    assert "crowd_platform" in cues("We posted the task on Amazon Mechanical Turk (MTurk).")
    assert "crowd_platform" in cues("Workers on AMT with a 95% approval rate could take part.")
    assert "crowd_platform" not in cues("The amt of time varied.")


def test_unmoderated_is_not_moderated():
    assert "moderated" not in cues("The study was unmoderated and took 20 minutes.")
    assert "unmoderated" in cues("The study was unmoderated and took 20 minutes.")
    assert "moderated" in cues("Sessions were moderated over Zoom.")


def test_crowd_study_is_settled_yes():
    assert route(("study", "Study 1", ["We recruited 300 participants on Prolific.",
                                       "Participants rated each image on a 7-point scale."])) == "yes"


def test_survey_tool_with_respondents_is_settled_yes():
    assert route(("study", None, ["We distributed the survey through Qualtrics.",
                                  "We received 412 responses from 18 countries; 380 respondents finished."])) == "yes"


def test_interview_only_paper_is_settled_no():
    assert route(("study", None, ["We conducted semi-structured interviews with 15 practitioners.",
                                  "Interviews lasted about an hour and were transcribed."])) == "no"


def test_lab_study_is_settled_no():
    assert route(("study", None, ["Participants came to our lab for a 45-minute session.",
                                  "They completed six tasks with the prototype in person."])) == "no"


def test_bittersweet_is_settled_no():
    # CHI 2022, the round-1 tie: an in-platform survey used only to pick interviewees. Nothing says
    # the survey was online in the words the cues know, the interviews make the session moderated,
    # and the screener sentence marks check 1: the answer the workshop reached, No.
    got = q.build(paper(("study", None, [
        "We recruited participants via a screening survey on Facebook and then interviewed participants about their "
        "experiences with seeing sensitive content via the Memories feature.",
        "Clicking on the invitation took participants to an in-platform survey screen.",
        "The survey data were only used to recruit participants and inform us about what issues might come up before "
        "each interview."])))
    assert got["route"] == "no"
    assert got["units"][0]["checks"]["c1"] in ("no", "mixed")


def test_zoom_interviews_after_an_online_survey_go_to_the_judge():
    assert route(("study", None, ["We conducted an online survey with 120 respondents.",
                                  "We then held follow-up interviews over Zoom with 12 of them."])) == "judge"


def test_survey_with_no_mode_goes_to_the_judge():
    assert route(("study", None, ["We conducted a survey with 87 respondents about their reading habits."])) == "judge"


def test_questionnaire_inside_a_moderated_session_is_settled_no():
    assert route(("study", None, ["After each task the experimenter handed participants the SUS questionnaire.",
                                  "We then held a short interview about their experience."])) == "no"


def test_platform_only_in_the_abstract_cannot_settle_yes():
    assert route(("abstract", None, ["We ran a study with 500 Prolific participants."]),
                 ("study", None, ["We built a prototype and describe its architecture."])) == "judge"


def test_related_work_is_not_read():
    assert route(("prior_work", None, ["Prior studies recruited thousands of workers on MTurk [12]."]),
                 ("study", None, ["We interviewed 10 designers in person."])) == "no"


def test_framing_is_read_only_on_request():
    p = (("framing", None, ["We report an online survey of 300 drivers."]),
         ("study", None, ["The prototype runs on a Raspberry Pi."]))
    assert route(*p) == "no"
    assert route(*p, framing=True) == "judge"


def test_one_study_yes_makes_the_paper_yes():
    assert route(("study", "Study 1", ["We interviewed 12 nurses in person."]),
                 ("study", "Study 2", ["We then ran an online experiment with 240 MTurk workers."])) == "yes"


def test_logs_from_a_deployment_count_as_online():
    assert "remote_data" in cues("We collected interaction logs from the app over four weeks.")
    assert "remote_data" in cues("Participants answered ESM prompts five times a day.")


def test_summary_counts_routes_and_errors():
    s = q.summarize([{"pid": "a", "year": "2024", "route": "yes", "reason": "Study 1: online, unmoderated, collected"},
                     {"pid": "b", "year": "2024", "route": "no", "reason": "no unit has an online cue"},
                     {"pid": "c", "year": "2024", "error": "KeyError: x"}])
    y = s["per_year"]["2024"]
    assert y["papers"] == 3 and y["routes"] == {"yes": 1, "no": 1} and len(y["errors"]) == 1
