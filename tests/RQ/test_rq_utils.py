"""Unit tests for rq_utils: statistics and annotation parsing.

    py -m pytest tests -q
"""
import math

import rq_utils as u


def test_wilson_contains_the_proportion_and_is_bounded():
    lo, hi = u.wilson(30, 100)
    assert 0 < lo < .30 < hi < 1
    assert u.wilson(0, 10)[0] == 0


def test_fleiss_perfect_and_chance():
    assert u.fleiss([["Yes"] * 3, ["No"] * 3, ["Yes"] * 3], ["Yes", "No"]) == 1
    assert u.fleiss([["Yes", "No"], ["No", "Yes"]], ["Yes", "No"]) < 0


def test_cohen_matches_hand_value():
    a = ["Yes", "Yes", "No", "No"]
    b = ["Yes", "No", "No", "No"]
    # po = .75, pe = .5*.25 + .5*.75 = .5, kappa = .5
    assert math.isclose(u.cohen(a, b, ["Yes", "No"]), .5)


def test_weighted_prf_uses_weights_and_counts_pending_as_no():
    pred = {"a": "Yes", "b": "pending", "c": "No"}
    truth = {"a": "Yes", "b": "Yes", "c": "No"}
    (p, r, _), (tp, fp, fn, tn) = u.weighted_prf(["a", "b", "c"], pred, truth, {"a": 1, "b": 3, "c": 10})
    assert (tp, fp, fn, tn) == (1, 0, 3, 10) and p == 1 and r == .25


def test_paper_q1_from_three_checks_and_from_v1():
    assert u.paper_q1({"studies": [{"c1": "Yes", "c2": "No"}, {"c1": "Yes", "c2": "Yes", "c3": "Yes"}]}) == "Yes"
    assert u.paper_q1({"studies": [{"c1": "No"}]}) == "No"
    assert u.paper_q1({"studies": [{"q1": "Unsure"}]}) == "Unsure"
    assert u.paper_q1({"studies": [{"c1": "Yes"}]}) is None          # not finished


def test_human_q23_majority_and_union(tmp_path):
    import json
    def export(name, q2, q3):
        study = {"c1": "Yes", "c2": "Yes", "c3": "Yes", "q2_checks": {k: "" for k in q2}, "q3_sources": {k: "" for k in q3}}
        (tmp_path / name).write_text(json.dumps({"papers": [{"id": "p", "studies": [study]}]}))
    export("a.json", ["attention check / IMC", "speed filter"], ["Prolific"])
    export("b.json", ["attention check / IMC"], ["Prolific", "Social media"])
    export("c.json", [], ["Prolific"])
    h = u.human_q23([tmp_path], ["attention check / IMC", "speed filter", "other"], ["Prolific", "Social media", "other"])
    assert h["p"]["n"] == 3 and h["p"]["q2_any"] is True
    assert h["p"]["q2"] == {"attention check / IMC"} and h["p"]["q3"] == {"Prolific"}


def test_category_scores_micro():
    pairs = [({"a"}, {"a"}), ({"a", "b"}, {"a"}), (set(), {"b"})]
    s = u.category_scores(pairs, ["a", "b"], "test")
    assert s["a"]["precision"] == 1 and s["a"]["recall"] == 1
    assert s["micro"]["precision"] == 2 / 3 and s["micro"]["recall"] == 2 / 3
