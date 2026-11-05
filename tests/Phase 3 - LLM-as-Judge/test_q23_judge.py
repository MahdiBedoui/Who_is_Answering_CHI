"""Unit tests for module 9 (Q2 and Q3 judge). No API: a stub client returns canned answers.

    py -m pytest tests -q
"""
import json

import q23_judge as j

CANDS = [{"n": n, "section": "Method", "text": f"sentence {n}"} for n in (3, 4, 5, 9)]


def ans(**kw):
    d = {"q2": {"checks": [], "absence_stated": False, "absence_ids": []}, "q3": {"sources": []}, "reason": "r"}
    d.update(kw)
    return json.dumps(d)


def test_valid_answer_passes_and_normalises_names():
    raw = ans(q2={"checks": [{"check": "Attention check / IMC", "ids": [4], "what": "instructed item"}],
                  "absence_stated": False, "absence_ids": []},
              q3={"sources": [{"source": "prolific", "ids": [3], "what": "Prolific"}]})
    a, why = j.parse_and_check(raw, CANDS)
    assert why is None
    assert list(a["q2_checks"]) == ["attention check / IMC"] and list(a["q3_sources"]) == ["Prolific"]


def test_category_without_sentence_is_rejected():
    raw = ans(q2={"checks": [{"check": "speed filter", "ids": [], "what": ""}]})
    assert j.parse_and_check(raw, CANDS)[0] is None


def test_sentence_not_shown_is_rejected():
    raw = ans(q3={"sources": [{"source": "MTurk", "ids": [42], "what": ""}]})
    assert j.parse_and_check(raw, CANDS)[1].startswith("MTurk cites")


def test_unknown_category_is_rejected():
    raw = ans(q2={"checks": [{"check": "vibes check", "ids": [3], "what": ""}]})
    assert "unknown" in j.parse_and_check(raw, CANDS)[1]


def test_other_needs_what():
    bad = ans(q2={"checks": [{"check": "other", "ids": [3], "what": ""}]})
    good = ans(q2={"checks": [{"check": "other (say what it is)", "ids": [3], "what": "incomplete responses removed"}]})
    assert j.parse_and_check(bad, CANDS)[0] is None
    assert "other" in j.parse_and_check(good, CANDS)[0]["q2_checks"]


def test_absence_needs_a_sentence():
    raw = ans(q2={"checks": [], "absence_stated": True, "absence_ids": []})
    assert j.parse_and_check(raw, CANDS)[0] is None
    raw = ans(q2={"checks": [], "absence_stated": True, "absence_ids": [9]})
    assert j.parse_and_check(raw, CANDS)[0]["q2_absence_stated"] is True


def test_repeated_category_is_merged():
    raw = ans(q3={"sources": [{"source": "Social media", "ids": [3], "what": "Twitter"},
                              {"source": "Social media", "ids": [5], "what": "Facebook"}]})
    a, _ = j.parse_and_check(raw, CANDS)
    assert a["q3_sources"]["Social media"]["ids"] == [3, 5]


def test_empty_lists_mean_none_reported():
    a, why = j.parse_and_check(ans(), CANDS)
    assert why is None and a["q2_checks"] == {} and a["q3_sources"] == {}


class Stub:
    def __init__(self, answers):
        self.answers = list(answers)
        self.chat = self
        self.completions = self

    def create(self, **kw):
        assert kw.get("temperature") == 0
        txt = self.answers.pop(0)
        msg = type("M", (), {"content": txt})
        return type("R", (), {"choices": [type("C", (), {"message": msg})], "usage": None})


def test_judge_paper_retries_once_after_a_rejection():
    paper = {"pid": "p", "year": "2024", "sentences": [{"text": f"s{i}", "section": 0} for i in range(3)],
             "sections": [{"title": "Method", "label": "study", "study": None}]}
    ev = {"pid": "p", "year": "2024", "online": [], "hits": [{"s": 1, "q": "q3", "cat": "MTurk", "match": "MTurk"}]}
    good = ans(q3={"sources": [{"source": "MTurk", "ids": [1], "what": ""}]})
    rec = j.judge_paper(Stub(["not json", good]), "gpt-4.1-2025-04-14", ev, paper)
    assert len(rec["attempts"]) == 2 and rec["answer"]["q3_sources"]["MTurk"]["ids"] == [1]
