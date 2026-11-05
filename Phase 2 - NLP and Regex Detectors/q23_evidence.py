"""Module 8: Q2 and Q3 evidence.

Contract
  in:  output/q1_final.jsonl                (module 7: Q1 per paper, and per study for judged papers)
       output/sentences/<year>/<pid>.json   (module 5)
  out: output/q23_evidence/<year>/<pid>.json, one per Q1-Yes paper
         pid, year
         online    the paper's online data collections, as module 7 named them
                   (empty for papers module 6 settled: their units are listed)
         hits      every cue found: sentence index, question (q2, q3, absence,
                   recruit), the category it points to, the matched words
         cues      per question, the categories with at least one hit
         route     judge, or none when no Q2, Q3 or recruitment cue was found
                   (then Q2 is "no checks reported" and Q3 "not reported")
       output/q23_evidence_summary.json   routes and cue counts per year

What it establishes
  - for every paper with Q1 Yes, the sentences that may report a
    data-quality check (Q2) or where participants came from (Q3), using the
    category names of CODEBOOK.md and the round-2 annotation pages.
    These are the evidence the judge (module 9) is shown.
  - a route. The rules settle only the absence of evidence: a paper with no
    cue at all. Any cue goes to the judge, because a cue is not a finding
    ("we excluded 3 participants" can be a speed filter, an attention
    check, or neither; "Prolific" can be where participants came from, or
    a platform the paper merely mentions).

What it does not do
  - It does not read prior work or framing sections: a check or platform
    named there is somebody else's.
  - It does not decide which online data collection a check belongs to.
    The judge is told which collections are online and asked about those.

Safe to rerun. Run from the repo root, after module 7's --final:
    py "Phase 2 - NLP and Regex Detectors/q23_evidence.py" [--year 2023]
"""
import argparse
import collections
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # the repo root, where config.py is
import config  # noqa: E402

SENTENCES_DIR = config.OUTPUT / "sentences"
Q1_FINAL = config.OUTPUT / "q1_final.jsonl"
EVIDENCE_DIR = config.OUTPUT / "q23_evidence"

READ_LABELS = ("study", "unclear", "appendix", "limits")    # where a paper reports what it did

# Category names, exactly as the round-2 annotation pages write them.
Q2_CHECKS = ["attention check / IMC", "comprehension check", "CAPTCHA", "reputation filter (approval rate / #HITs)",
             "qualification / screener", "duplicate / IP / VPN check", "speed filter",
             "straight-lining / pattern check", "open-text quality review", "bot detection / honeypot",
             "consistency items", "manual review", "other"]
Q3_SOURCES = ["Prolific", "MTurk", "CloudResearch", "Qualtrics", "University pool", "Social media",
              "Mailing lists", "Snowball", "Community / forums", "Company-internal", "other", "Not reported"]


def rx(pattern: str, flags=re.I) -> re.Pattern:
    return re.compile(pattern, flags)


# (question, category, pattern). "q2"/"q3" point to a category; "exclusion"
# and "recruit" are generic: the sentence may hold a check or a source, the
# judge says which.
CUES = [
    # ---------------- Q2: data-quality checks
    ("q2", "attention check / IMC", rx(
        r"\battention[- ]?(?:check|test|question|item|filter)s?\b|\binstructed[- ]response\b|"
        r"\binstructional manipulation checks?\b|\btrap (?:question|item)s?\b|\bcatch (?:trial|question|item)s?\b|"
        r"\bred[- ]herring\b|\bbogus items?\b|\bvigilance (?:check|question)s?\b")),
    ("q2", "attention check / IMC", rx(r"\bIMCs?\b", 0)),
    ("q2", "comprehension check", rx(
        r"\bcomprehension (?:check|question|quiz|test|item)s?\b|\bmanipulation checks?\b|"
        r"\b(?:check|test|verify|ensure)\w* (?:their |participants' |that participants )?understoo?d?\w* (?:of )?the "
        r"(?:task|instructions|scenario)\b|\bquiz(?:zes)? (?:on|about) the (?:task|instructions)\b")),
    ("q2", "CAPTCHA", rx(r"\b(?:re)?CAPTCHAs?\b")),
    ("q2", "reputation filter (approval rate / #HITs)", rx(
        r"\bapproval (?:rate|rating|ratio)s?\b|\bHITs? approv\w*|\b\d[\d,]* (?:or more )?(?:approved |completed |previous )?"
        r"(?:HITs|tasks|submissions|studies)\b|\bMasters? (?:workers?|qualification)\b|\bacceptance rates?\b|"
        r"\bapproved (?:HITs|submissions|tasks)\b")),
    ("q2", "qualification / screener", rx(
        r"\bscreen(?:er|ing) (?:survey|questionnaire|question|form|criteria)s?\b|\bpre-?screen\w*|\bscreeners?\b|"
        r"\bqualification (?:task|test|survey|question)s?\b|\beligibility (?:criteria|survey|questionnaire|question|check)s?\b|"
        r"\binclusion criteria\b|\bwere (?:eligible|ineligible)\b")),
    ("q2", "duplicate / IP / VPN check", rx(
        r"\bduplicates?\b|\bduplicated (?:responses|entries|submissions)\b|\bIP address\w*|\bVPNs?\b|\bproxies\b|\bproxy servers?\b|"
        r"\bgeo-?locat\w*|\bmore than once\b|\bmultiple (?:submissions|responses|accounts|attempts)\b|"
        r"\b(?:same|repeated) (?:worker|participant|Prolific|MTurk) IDs?\b|\bprevent\w* repeat\w* participation\b")),
    ("q2", "speed filter", rx(
        r"\btoo (?:quickly|fast)\b|\bspeed(?:ers|ing)\b|\bunrealistically (?:fast|short|quick)\b|"
        r"\b(?:completion|response|survey) times? (?:of )?(?:less|shorter|under|below)\b|"
        r"\b(?:less|shorter) than (?:\w+ )?(?:\d+|one|two|three|half) (?:seconds?|minutes?)\b|"
        r"\btime (?:threshold|cutoff|cut-off)s?\b|\bmedian (?:completion |response )?time\b|\brush\w* through\b")),
    ("q2", "straight-lining / pattern check", rx(
        r"\bstraight-?lin\w*|\b(?:same|identical) (?:answer|response|rating|value)s? (?:to|for|on|across) (?:all|every)\b|"
        r"\bpattern(?:ed)? respon\w*|\bcareless (?:respon\w*|answers?)\b|\binsufficient effort\b|\blong-?string\b|"
        r"\bzero variance\b|\bno variance\b")),
    ("q2", "open-text quality review", rx(
        r"\bnonsensical\b|\bgibberish\b|\bmeaningless (?:answers|responses|text)\b|\birrelevant (?:answers|responses|text)\b|"
        r"\blow[- ]effort (?:answers|responses)\b|\bcopy(?:-| and )?past\w*|\b(?:AI|LLM|ChatGPT)[- ]generated (?:answers|responses|text)\b|"
        r"\bopen[- ](?:ended|text) (?:answers|responses) (?:were|that)\b")),
    ("q2", "bot detection / honeypot", rx(
        r"\bbots?\b|\bhoney-?pots?\b|\bfraud\w*|\bautomated (?:responses|submissions|scripts)\b|\bscammers?\b|"
        r"\bRelevantID\b|\bfake (?:responses|participants|respondents|accounts)\b")),
    ("q2", "consistency items", rx(
        r"\bconsistency (?:check|item|question|test)s?\b|\breverse[- ](?:coded|scored|worded)\b|"
        r"\binconsistent (?:answers|responses)\b|\bcontradictory (?:answers|responses)\b")),
    ("q2", "manual review", rx(
        r"\bmanually (?:reviewed|checked|inspected|screened|examined|verified|filtered|removed|excluded)\b|"
        r"\b(?:reviewed|inspected|checked) (?:each|every|all) (?:response|submission|answer)s?\b")),
    ("exclusion", "", rx(
        r"\bexclud\w*|\bexclusion\b|\bremoved \d|\bremov\w* (?:\w+ ){0,3}(?:participants|responses|respondents|workers|submissions|data)\b|"
        r"\bdiscard\w*|\bfiltered (?:out )?\w*|\bdid not pass\b|\bfailed (?:to pass|the|one|at least|both|any)\b|"
        r"\binvalid (?:responses|data|submissions|answers)\b|\bdata quality\b|\bquality (?:control|check|assurance)s?\b|"
        r"\blow[- ]quality\b|\brejected (?:\d+ )?(?:submissions|responses|HITs|workers)\b|\bincomplete (?:responses|submissions|surveys)\b")),
    ("absence", "", rx(
        r"\b(?:did not|didn't|do not|no|without|not) (?:include |use |employ |have |add |apply )?(?:any )?"
        r"(?:attention|quality|comprehension|validity) (?:check|test|question|control)s?\b")),
    # ---------------- Q3: participant sources
    ("q3", "Prolific", rx(r"\bProlific(?:\.co|\.com| Academic)?\b(?! (?:author|writer|use|amount))", 0)),
    ("q3", "MTurk", rx(r"\b(?:Amazon )?Mechanical Turk\b|\bM-?Turk\b")),
    ("q3", "MTurk", rx(r"\bAMT\b", 0)),
    ("q3", "CloudResearch", rx(r"\bCloudResearch\b|\bTurkPrime\b|\bConnect (?:by|from) CloudResearch\b")),
    ("q3", "Qualtrics", rx(r"\bQualtrics(?:'s)? (?:panels?|XM panels?|Panel Services|Research Services|audiences?)\b|"
                          r"\bpanel (?:provided|recruited|sourced) (?:by|through|via) Qualtrics\b")),
    ("q3", "University pool", rx(
        r"\bSONA\b|\b(?:participant|subject|research|psychology|undergraduate|departmental) pools?\b|"
        r"\bcourse credits?\b|\bextra credit\b|\b(?:our|the) (?:university|campus)(?:'s)? (?:students|community)\b|"
        r"\bstudents (?:at|from) (?:our|the|a) (?:university|institution)\b")),
    ("q3", "Social media", rx(
        r"\bsocial media\b|\bsocial networks?\b|\bTwitter\b|\bFacebook\b(?! groups?)|\bInstagram\b|\bLinkedIn\b|\bTikTok\b|"
        r"\bWeChat\b|\bWeibo\b|\bMastodon\b|\bBluesky\b|\bThreads\b|\bYouTube\b|\bX \(formerly")),
    ("q3", "Mailing lists", rx(
        r"\bmailing[- ]lists?\b|\blistservs?\b|\bemail(?:ing)? lists?\b|\be-?mail (?:invitations?|announcements?|newsletters?)\b|"
        r"\bnewsletters?\b|\bdistribution lists?\b")),
    ("q3", "Snowball", rx(r"\bsnowball\w*|\bword[- ]of[- ]mouth\b|\bpersonal (?:networks?|contacts|connections)\b|"
                          r"\breferrals?\b|\breferred (?:by|other)\b|\bshare (?:the survey|it) with\b")),
    ("q3", "Community / forums", rx(
        r"\bforums?\b|\bReddit\b|\bsubreddits?\b|\br/\w+|\bDiscord\b|\bSlack (?:workspace|channel|communit\w*)s?\b|"
        r"\bonline communit(?:y|ies)\b|\bFacebook groups?\b|\bsupport groups?\b|\badvocacy (?:groups?|organi[sz]ations?)\b|"
        r"\bcommunity (?:organi[sz]ations?|groups?|centers?|partners?)\b|\bmeetups?\b")),
    ("q3", "Company-internal", rx(
        r"\b(?:within|across|inside) (?:the|our|a large|one) (?:company|organi[sz]ation|firm|enterprise)\b|"
        r"\b(?:company|corporate|internal) (?:mailing lists?|employees|channels?|intranet)\b|\bemployees (?:of|at) (?:a|the|our)\b")),
    ("q3", "other", rx(
        r"\bToloka\b|\bClickworker\b|\bLucid\b|\bDynata\b|\bYouGov\b|\bCint\b|\bIpsos\b|\bPanelbase\b|\bRespondi\b|"
        r"\bSurvey ?Monkey Audience\b|\bPollfish\b|\bAppen\b|\bUpwork\b|\bFiverr\b|\bmarket research (?:firm|company|panel)\b|"
        r"\bonline panels?\b|\bsurvey panels?\b|\bpanel (?:company|provider|vendor)s?\b|\bflyers?\b|\bposters?\b")),
    ("recruit", "", rx(r"\brecruit\w*|\badvertis\w*|\binvit(?:ed|ation)s?\b|\bsampl(?:ed|ing) (?:from|through|via)\b|"
                       r"\bparticipants were (?:drawn|sourced|obtained)\b")),
]

NEIGHBOURS = 1
MAX_SENTENCES = 250

# Categories whose words are also everyday HCI topics (a study about bots, VPNs or social media).
# Their hits count only when a sentence within one of them is about recruiting (Q3) or about
# excluding or checking data (Q2); the others count wherever they are.
ANCHORED = {"q2": {"bot detection / honeypot", "duplicate / IP / VPN check", "speed filter", "open-text quality review",
                   "consistency items"},
            "q3": {"Social media", "Community / forums", "Snowball", "Mailing lists", "Company-internal", "other",
                   "University pool"}}
Q2_ANCHOR = rx(r"\bexclud\w*|\bremov\w*|\bdiscard\w*|\bfilter\w*|\bquality\b|\bvalid\w*|\bgenuine\b|\blegitimate\b|"
               r"\bensur\w*|\bprevent\w*|\bdetect\w*|\bscreen\w*|\bflag\w*|\bfailed\b|\bcheck\w*|\breject\w*")


def find_hits(text: str) -> list[dict]:
    hits = []
    for q, cat, pat in CUES:
        for m in pat.finditer(text):
            hits.append({"q": q, "cat": cat, "match": m.group(0)})
    return hits


def read_indices(paper: dict) -> list[int]:
    return [i for i, s in enumerate(paper["sentences"]) if paper["sections"][s["section"]]["label"] in READ_LABELS]


def anchor_ok(hit: dict, by_s: dict, sents: list) -> bool:
    if hit["cat"] not in ANCHORED.get(hit["q"], ()):
        return True
    near = range(hit["s"] - NEIGHBOURS, hit["s"] + NEIGHBOURS + 1)
    if hit["q"] == "q3":
        return any(h["q"] == "recruit" for j in near for h in by_s.get(j, []))
    return any(0 <= j < len(sents) and Q2_ANCHOR.search(sents[j]["text"]) for j in near)


def build(paper: dict, q1_row: dict) -> dict:
    sents = paper["sentences"]
    raw = []
    for i in read_indices(paper):
        raw += [{"s": i, **h} for h in find_hits(sents[i]["text"])]
    by_s = collections.defaultdict(list)
    for h in raw:
        by_s[h["s"]].append(h)
    hits = [h for h in raw if anchor_ok(h, by_s, sents)]
    cues = {q: sorted({h["cat"] for h in hits if h["q"] == q and h["cat"]}) for q in ("q2", "q3")}
    counts = collections.Counter(h["q"] for h in hits)
    online = [{"study": s["study"], "how_collected": s.get("how_collected", "")}
              for s in q1_row.get("studies") or [] if s.get("q1") == "yes"]
    route = "judge" if counts else "none"
    return {"pid": paper["pid"], "year": paper["year"], "q1_source": q1_row.get("source"), "online": online,
            "hits": hits, "cues": cues, "counts": dict(counts), "route": route}


def candidates(evidence: dict, paper: dict) -> list[dict]:
    """The sentences the judge is shown: every cue sentence and its
    neighbours inside the read sections, in reading order."""
    sents, secs = paper["sentences"], paper["sections"]
    readable = set(read_indices(paper))
    hit = sorted({h["s"] for h in evidence["hits"]})
    if len(hit) > MAX_SENTENCES:                     # very long papers: keep the specific cues first
        strong = sorted({h["s"] for h in evidence["hits"] if h["q"] in ("q2", "q3", "absence")})
        hit = (strong + [i for i in hit if i not in set(strong)])[:MAX_SENTENCES]
    keep = sorted({j for i in hit for j in range(i - NEIGHBOURS, i + NEIGHBOURS + 1) if j in readable})
    return [{"n": i, "section": secs[sents[i]["section"]].get("title") or "", "text": sents[i]["text"]} for i in keep]


def q1_yes_rows() -> list[dict]:
    if not Q1_FINAL.exists():
        raise SystemExit(f"{Q1_FINAL} is missing: run module 7 with --final first")
    return [r for r in (json.loads(l) for l in Q1_FINAL.open(encoding="utf-8")) if r.get("q1") == "yes"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Find the evidence for Q2 and Q3 in every Q1-Yes paper.")
    ap.add_argument("--year", choices=config.YEARS)
    args = ap.parse_args()
    rows = [r for r in q1_yes_rows() if not args.year or r["year"] == args.year]
    per_year = collections.defaultdict(lambda: {"papers": 0, "routes": collections.Counter(),
                                                "q2": collections.Counter(), "q3": collections.Counter()})
    for r in rows:
        paper = json.loads((SENTENCES_DIR / r["year"] / f"{r['pid']}.json").read_text(encoding="utf-8"))
        ev = build(paper, r)
        out = EVIDENCE_DIR / r["year"] / f"{r['pid']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
        y = per_year[r["year"]]
        y["papers"] += 1
        y["routes"][ev["route"]] += 1
        y["q2"].update(ev["cues"]["q2"])
        y["q3"].update(ev["cues"]["q3"])
    summary = {"per_year": {k: {"papers": v["papers"], "routes": dict(v["routes"]),
                                "q2_cues": dict(v["q2"].most_common()), "q3_cues": dict(v["q3"].most_common())}
                            for k, v in sorted(per_year.items())}}
    suffix = f"_{args.year}" if args.year else ""
    (config.OUTPUT / f"q23_evidence_summary{suffix}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"{'year':<6}{'Q1 yes':>8}{'judge':>7}{'none':>6}")
    for y, s in summary["per_year"].items():
        print(f"{y:<6}{s['papers']:>8}{s['routes'].get('judge', 0):>7}{s['routes'].get('none', 0):>6}")
    print(f"-> {EVIDENCE_DIR}")


if __name__ == "__main__":
    main()
