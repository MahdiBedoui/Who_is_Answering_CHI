"""Unit tests for module 7. The model is a stub that returns a fixed answer,
so no API call is made.

    py -m pytest tests -q
"""
import json
import types

import q1_judge as j


def paper(*sections):
    secs, sents = [], []
    for label, study, title, texts in sections:
        secs.append({"title": title, "level": 1, "label": label, "read": True, "study": study})
        sents += [{"text": t, "section": len(secs) - 1, "kind": "text", "page": 1, "block": 0, "joined": False}
                  for t in texts]
    return {"pid": "p", "year": "2024", "sections": secs, "sentences": sents}


P = paper(("abstract", None, "Abstract", ["We report an online survey and interviews."]),
          ("prior_work", None, "2 Related Work", ["Others used MTurk [3]."]),
          ("study", "Study 1", "3 Study 1: Survey", ["We ran a Qualtrics survey with 200 respondents.",
                                                    "Responses were analysed thematically."]),
          ("study", "Study 2", "4 Study 2: Interviews", ["We interviewed 12 respondents over Zoom."]))
EV = {"pid": "p", "year": "2024", "route": "judge", "units": [
    {"unit": "context", "route": "judge", "hits": [{"s": 0}]},
    {"unit": "Study 1", "route": "yes", "hits": [{"s": 2}]},
    {"unit": "Study 2", "route": "judge", "hits": [{"s": 4}]}]}


class Stub:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kw):
        a = self.answers.pop(0)
        msg = types.SimpleNamespace(content=a if isinstance(a, str) else json.dumps(a))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)],
                                     usage=types.SimpleNamespace(prompt_tokens=100, completion_tokens=20))


def study(name, c1, c2, c3, ids=(4,)):
    return {"study": name, "c1": c1, "c1_ids": list(ids), "c2": c2, "c2_ids": list(ids) if c2 == "yes" else [],
            "c3": c3, "c3_ids": list(ids) if c3 == "yes" else [], "best_guess": False, "how_collected": "x"}


def test_candidates_show_judged_units_and_context_cues_never_related_work():
    shown = j.candidates(EV, P)
    texts = [c["text"] for c in shown]
    assert "Others used MTurk [3]." not in texts
    assert "We interviewed 12 respondents over Zoom." in texts
    assert "We report an online survey and interviews." in texts
    assert "We ran a Qualtrics survey with 200 respondents." not in texts    # Study 1 was settled by rules


def test_prompt_numbers_are_the_paper_sentence_indices():
    prompt = j.build_prompt(j.candidates(EV, P))
    assert "[4] (4 Study 2: Interviews) We interviewed 12 respondents over Zoom." in prompt
    assert "## Study 2" in prompt and "## Abstract, limitations, appendix" in prompt


def test_q1_is_derived_from_the_checks_not_taken_from_the_model():
    cands = j.candidates(EV, P)
    ans, why = j.parse_and_check(json.dumps({"studies": [study("Study 2", "yes", "yes", "no")], "q1": "yes"}), cands)
    assert why is None and ans["q1"] == "no" and ans["studies"][0]["q1"] == "no"


def test_a_cited_sentence_that_was_not_shown_is_rejected():
    cands = j.candidates(EV, P)
    _, why = j.parse_and_check(json.dumps({"studies": [study("Study 2", "yes", "yes", "yes", ids=(1,))]}), cands)
    assert why == "c1 cites a sentence it was not shown"


def test_a_yes_without_a_sentence_is_rejected_except_unmoderated():
    cands = j.candidates(EV, P)
    s = study("Study 2", "yes", "yes", "yes"); s["c2_ids"] = []
    _, why = j.parse_and_check(json.dumps({"studies": [s]}), cands)
    assert why == "c2 is yes with no sentence"
    s = study("Study 2", "yes", "yes", "yes"); s["c3_ids"] = []
    ans, why = j.parse_and_check(json.dumps({"studies": [s]}), cands)
    assert why is None and ans["q1"] == "yes"


def test_filler_after_a_no_is_read_as_no():
    cands = j.candidates(EV, P)
    s = study("Study 2", "no", "no", "no"); s["c2"] = []; s["c3"] = None
    ans, why = j.parse_and_check(json.dumps({"studies": [s]}), cands)
    assert why is None and ans["studies"][0]["c2"] == "no"


def test_wrapped_json_is_read():
    cands = j.candidates(EV, P)
    ans, why = j.parse_and_check("Here you go:\n" + json.dumps({"studies": [study("S", "yes", "no", "no")]}), cands)
    assert why is None and ans["q1"] == "no"


def test_one_retry_after_a_rejected_answer():
    rec = j.judge_paper(Stub("not json", {"studies": [study("Study 2", "yes", "yes", "yes")], "reason": "r"}),
                        "m", EV, P)
    assert len(rec["attempts"]) == 2 and rec["attempts"][0]["rejected"] and rec["answer"]["q1"] == "yes"


def test_two_rejected_answers_leave_no_answer():
    rec = j.judge_paper(Stub("x", "y"), "m", EV, P)
    assert "answer" not in rec and len(rec["attempts"]) == 2


def test_score_counts_against_the_reference(capsys):
    rows = [{"pid": "a", "year": "2024", "q1": "yes", "source": "rule"},
            {"pid": "b", "year": "2024", "q1": "no", "source": "judge", "why": "zoom"},
            {"pid": "c", "year": "2024", "q1": None, "source": "pending"}]
    j.score(rows, {"a": "yes", "b": "yes", "c": "no"})
    out = capsys.readouterr().out
    assert "TP 1  FP 0  FN 1  TN 0" in out and "no answer yet: 1" in out


def test_no_studies_found_is_a_no():
    ans, why = j.parse_and_check(json.dumps({"studies": [], "reason": "no data collection"}), j.candidates(EV, P))
    assert why is None and ans["q1"] == "no"
