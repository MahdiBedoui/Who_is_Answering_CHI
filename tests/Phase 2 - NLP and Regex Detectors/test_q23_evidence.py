"""Unit tests for module 8 (Q2 and Q3 evidence).

    py -m pytest tests -q
"""
import q23_evidence as q


def paper(*sections):
    """sections: (label, [sentences])"""
    secs, sents = [], []
    for label, texts in sections:
        secs.append({"title": "", "level": 1, "label": label, "read": True, "study": None})
        sents += [{"text": t, "section": len(secs) - 1} for t in texts]
    return {"pid": "p", "year": "2024", "sections": secs, "sentences": sents}


def cats(*texts, label="study"):
    ev = q.build(paper((label, list(texts))), {"source": "judge", "studies": []})
    return ev["cues"]["q2"], ev["cues"]["q3"], ev


def test_attention_and_reputation_cues():
    q2, q3, _ = cats("We recruited 300 participants on Prolific with an approval rate of at least 95%.",
                     "We excluded 12 participants who failed the attention check.")
    assert "attention check / IMC" in q2 and "reputation filter (approval rate / #HITs)" in q2
    assert q3 == ["Prolific"]


def test_mturk_and_cloudresearch():
    _, q3, _ = cats("Workers were recruited on Amazon Mechanical Turk through CloudResearch.")
    assert set(q3) == {"MTurk", "CloudResearch"}


def test_topic_words_need_an_anchor():
    # a study about chatbots and social media: no Q2 bot check, no Q3 social media source
    q2, q3, _ = cats("Participants chatted with a bot about their social media habits.",
                     "The bot replied within two seconds.")
    assert "bot detection / honeypot" not in q2 and "Social media" not in q3


def test_anchored_words_count_with_an_anchor():
    q2, q3, _ = cats("We recruited participants through posts on Twitter and Reddit.",
                     "To detect bots, we removed responses that answered the hidden question.")
    assert "Social media" in q3 and "Community / forums" in q3 and "bot detection / honeypot" in q2


def test_prior_work_is_not_read():
    q2, q3, ev = cats("Prior studies used attention checks on MTurk [12].", label="prior_work")
    assert q2 == [] and q3 == [] and ev["route"] == "none"


def test_appendix_is_read():
    q2, _, _ = cats("Attention check: please select 'Strongly disagree' for this item.", label="appendix")
    assert "attention check / IMC" in q2


def test_prolific_as_a_word_is_not_a_source():
    _, q3, _ = cats("We recruited a prolific author of fan fiction.")
    assert "Prolific" not in q3


def test_absence_cue():
    _, _, ev = cats("We did not include any attention checks to keep the survey short.")
    assert any(h["q"] == "absence" for h in ev["hits"])


def test_no_cue_settles_none():
    _, _, ev = cats("The prototype logged every tap.", "Logs were sent to our server nightly.")
    assert ev["route"] == "none"


def test_candidates_keep_neighbours_inside_read_sections():
    p = paper(("prior_work", ["Others used MTurk."]),
              ("study", ["Intro sentence.", "We recruited 200 workers on MTurk.", "They were paid $2.", "Unrelated."]))
    ev = q.build(p, {"studies": []})
    shown = [c["n"] for c in q.candidates(ev, p)]
    assert shown == [1, 2, 3]
